"""
Seal VPN for Proton -- the app's native side (pyotherside).

The app is a touch front end for Proton VPN's OWN Linux client code: the
official Proton VPN CLI's Controller (proton.vpn.cli.core.controller) and the
libraries under it (proton-vpn-api-core, proton-core ...), bundled in the click
under lib/. So signing in, the server list, WireGuard keys/certificates,
connecting (NetworkManager), the kill switch and NetShield all work exactly as
in Proton's CLI, and the app identifies to Proton as that client
(linux-vpn-cli@<version>).

Proton's code is asyncio: it runs here on one event loop in a background
thread; the screen's calls (pyotherside, another thread) wait on it.
"""

import asyncio
import ctypes
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request

try:
    import pyotherside
except ImportError:  # tests on a PC
    pyotherside = None

APP = "sealvpn.jeffbristow"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIB_PY = os.environ.get("SEALVPN_PY", os.path.join(ROOT, "lib", "python"))
LIB_NATIVE = os.environ.get("SEALVPN_NATIVE", os.path.join(ROOT, "lib", "native"))
LIB_TYPELIB = os.environ.get("SEALVPN_TYPELIB", os.path.join(ROOT, "lib", "girepository-1.0"))
CONF_DIR = os.path.expanduser("~/.config/" + APP)
PREFS = os.path.join(CONF_DIR, "prefs.json")
UNIT_DIR = os.path.expanduser("~/.config/systemd/user")
UNIT = "sealvpn-autoconnect.service"

# Old Seal VPN (config-file version) left these behind; they block Proton's tunnels.
OLD_KILL_SWITCH = "Seal VPN kill switch"
OLD_META = os.path.expanduser("~/.local/share/" + APP + "/servers.json")


def _setup_paths():
    """Make the bundled libraries importable (nothing is installed system-wide)."""
    if LIB_PY not in sys.path:
        sys.path.insert(0, LIB_PY)
    old = os.environ.get("GI_TYPELIB_PATH", "")
    if LIB_TYPELIB not in old.split(":"):
        os.environ["GI_TYPELIB_PATH"] = LIB_TYPELIB + (":" + old if old else "")
    # libsodium (PyNaCl) is loaded by soname; preloading it globally lets the
    # bundled extension find it without LD_LIBRARY_PATH.
    if os.path.isdir(LIB_NATIVE):
        for n in sorted(os.listdir(LIB_NATIVE)):
            if re.match(r"^lib.*\.so\.\d+$", n):
                ctypes.CDLL(os.path.join(LIB_NATIVE, n), mode=ctypes.RTLD_GLOBAL)


_setup_paths()


def _send(event, *args):
    if pyotherside:
        pyotherside.send(event, *args)


def _ok(**kw):
    kw["ok"] = True
    return kw


def _err(msg, **kw):
    kw.update(ok=False, error=str(msg))
    return kw


# ------------------------------------------------------------ the event loop
_loop = asyncio.new_event_loop()
threading.Thread(target=_loop.run_forever, name="proton-loop", daemon=True).start()


def _await(coro, timeout=120):
    return asyncio.run_coroutine_threadsafe(coro, _loop).result(timeout)


_ctl = None
_ctl_lock = threading.Lock()
_subscribed = False


def _controller():
    """Proton's CLI Controller (created once; loads settings and the session from the keyring)."""
    global _ctl
    with _ctl_lock:
        if _ctl is None:
            from proton.vpn.cli.core.controller import Controller, Params
            _ctl = _await(Controller.create(Params(), None))
            # Proton's controller installs a global excepthook that reports crashes (if the
            # user allows anonymous crash reports); keep Python's normal one for this app.
            sys.excepthook = sys.__excepthook__
        return _ctl


def _ensure_subscribed():
    """Push every connection state change to the screen."""
    global _subscribed
    if _subscribed:
        return
    ctl = _controller()

    class Sub:
        def status_update(self, state):
            try:
                _send("state", _state_dict(state))
            except Exception:  # noqa: BLE001
                pass

    conn = _await(ctl.get_vpn_connector())
    conn.register(Sub())
    _subscribed = True


# ------------------------------------------------------------- formatting
FEATURE_NAMES = {1: "Secure Core", 2: "Tor", 4: "P2P", 8: "Streaming", 16: "IPv6"}


def _features(server):
    out = []
    try:
        for f in server.features:
            n = FEATURE_NAMES.get(int(f))
            if n:
                out.append(n)
    except Exception:  # noqa: BLE001
        pass
    return out


def _server_dict(s, tier=None):
    d = {"name": s.name, "city": s.city or "", "country": s.exit_country, "countryName": s.exit_country_name,
         "entry": s.entry_country, "entryName": s.entry_country_name, "load": s.load,
         "features": _features(s), "tier": s.tier, "enabled": bool(s.enabled)}
    d["feat"] = ", ".join(f for f in d["features"] if f != "IPv6")  # plain text for list models
    if tier is not None:
        d["locked"] = s.tier > tier
    return d


def _cached_server(name):
    try:
        sl = _controller()._api.server_list  # cached copy; no network
        if sl:
            s = sl.get_by_name(name)
            if s:
                return _server_dict(s)
    except Exception:  # noqa: BLE001
        pass
    return None


def _state_dict(state):
    t = type(state).__name__.upper()   # Disconnected, Connecting, Connected, Disconnecting, Error
    d = {"state": t, "server": None, "protocol": ""}
    conn = getattr(getattr(state, "context", None), "connection", None)
    if conn is not None and t != "DISCONNECTED":
        name = getattr(conn, "server_name", "") or ""
        d["server"] = _cached_server(name) or {"name": name}
        d["protocol"] = getattr(conn, "protocol", "") or ""
    if t == "ERROR":
        ev = getattr(getattr(state, "context", None), "event", None)
        d["error"] = type(ev).__name__ if ev is not None else "Error"
    return d


def _friendly(e):
    n = type(e).__name__
    msg = {
        "AuthenticationFailedError": "Wrong username or password.",
        "Authentication2FAFailedError": "That two-factor code wasn't accepted. Sign in again.",
        "AuthenticationRequiredError": "Please sign in first.",
        "SignoutRequiredError": "Already signed in.",
        "RequiresHigherTierError": "That needs a paid Proton VPN plan.",
        "VPNConnection2FARequiredError": "Proton wants two-factor authentication before connecting. Sign out and in again.",
        "VPNConnectionError": "The connection failed. Try another server.",
        "TimeoutError": "Timed out. Check your internet connection and try again.",
        "ProtonAPIHumanVerificationNeeded": "Proton asked for a CAPTCHA, which this app can't show. Try again later or from another network.",
        "ProtonAPINotReachable": "Can't reach Proton. Check your internet connection (or turn the kill switch off).",
        "ProtonAPINotAvailable": "Proton's servers are unavailable right now. Try again later.",
        "CountryCodeError": "Unknown country.",
        "InvalidDNS": "Not a valid DNS address.",
    }.get(n)
    if msg:
        return msg
    s = str(e).strip()
    return s if s else n


# ------------------------------------------------------------------ account
def start():
    """First call from the screen: account + connection state, plus clean-up of the old version."""
    try:
        cleanup = _cleanup_old_version()
        ctl = _controller()
        _ensure_subscribed()
        r = status()
        r["cleanup"] = cleanup
        r["manualVpns"] = manual_vpns()
        return r
    except Exception as e:  # noqa: BLE001
        return _err(_friendly(e))


def status():
    try:
        ctl = _controller()
        conn = _await(ctl.get_vpn_connector())
        r = _ok(loggedIn=ctl.is_logged_in, account=ctl.account_name if ctl.is_logged_in else "",
                tier=ctl.user_tier if ctl.is_logged_in else 0)
        r.update(_state_dict(conn.current_state))
        r["rx"], r["tx"] = _counters()
        return r
    except Exception as e:  # noqa: BLE001
        return _err(_friendly(e))


def _counters():
    try:
        for n in os.listdir("/sys/class/net"):
            if re.match(r"^proton\d+$", n):  # Proton's tunnel interface (proton0)
                b = "/sys/class/net/%s/statistics/" % n
                return int(open(b + "rx_bytes").read()), int(open(b + "tx_bytes").read())
    except (OSError, ValueError):
        pass
    return 0, 0


_pending_2fa = False


def login(username, password):
    global _pending_2fa
    try:
        ctl = _controller()
        if ctl.is_logged_in:
            return _ok(twofa=False, account=ctl.account_name)
        need = _await(ctl.login(username.strip(), lambda: password))
        _pending_2fa = bool(need)
        if need:
            return _ok(twofa=True, securityKeyOnly=False)
        return _ok(twofa=False, account=ctl.account_name)
    except Exception as e:  # noqa: BLE001
        return _err(_friendly(e))


def submit_2fa(code):
    global _pending_2fa
    try:
        ctl = _controller()
        if not _await(ctl.submit_2fa_code(re.sub(r"\s", "", code))):
            return _err("That code wasn't accepted. Try the next one.")
        _pending_2fa = False
        return _ok(account=ctl.account_name)
    except Exception as e:  # noqa: BLE001
        return _err(_friendly(e))


def logout():
    try:
        set_startup("off")
        _await(_controller().logout())
        return _ok()
    except Exception as e:  # noqa: BLE001
        return _err(_friendly(e))


# ------------------------------------------------------------------ servers
def countries():
    """One line per country: name, server counts, best load, features."""
    try:
        ctl = _controller()
        sl = _await(ctl.get_updated_server_list())
        tier = ctl.user_tier
        by = {}
        for s in sl.logicals:
            c = by.setdefault(s.exit_country, {"code": s.exit_country, "name": s.exit_country_name,
                                               "servers": 0, "available": 0, "cities": set(), "features": set(),
                                               "bestLoad": 101})
            c["servers"] += 1
            if s.city:
                c["cities"].add(s.city)
            for f in _features(s):
                c["features"].add(f)
            if s.enabled and s.tier <= tier:
                c["available"] += 1
                c["bestLoad"] = min(c["bestLoad"], s.load)
        out = []
        for c in by.values():
            c["cities"] = len(c["cities"])
            c["features"] = sorted(c["features"])
            out.append(c)
        out.sort(key=lambda c: c["name"])
        return _ok(countries=out, tier=tier)
    except Exception as e:  # noqa: BLE001
        return _err(_friendly(e))


def servers(country_code):
    """All servers of a country, by city then load."""
    try:
        ctl = _controller()
        sl = _await(ctl.get_updated_server_list())
        tier = ctl.user_tier
        out = [_server_dict(s, tier) for s in sl.logicals if s.exit_country == country_code]
        out.sort(key=lambda d: (d["city"] or "~", "Secure Core" in d["features"], not d["enabled"], d["locked"], d["load"]))
        return _ok(servers=out, tier=tier)
    except Exception as e:  # noqa: BLE001
        return _err(_friendly(e))


FEATURE_FLAGS = {"p2p": 4, "securecore": 1, "tor": 2}


def connect(target):
    """target: {"server": "US-FL#297"} or {"country": "US", "city": "Miami", "feature": "p2p"} or {} (fastest)."""
    try:
        from proton.vpn.session.servers.types import ServerFeatureEnum
        ctl = _controller()
        target = target or {}
        feats = ServerFeatureEnum(FEATURE_FLAGS.get(target.get("feature") or "", 0))
        server = _await(ctl.find_logical_server(server_name=target.get("server") or None,
                                                country=target.get("country") or None,
                                                city=target.get("city") or None, features=feats))
        if server is None:
            return _err("No available server matches that.")
        if _await(ctl.is_connection_active()):
            _await(ctl.disconnect())
        state = _await(ctl.connect(server), timeout=150)
        if state is None:
            return _err("Couldn't connect to %s. Try another server." % server.name)
        _remember(server.name)
        _later_ip_check()
        return _ok(server=_server_dict(server))
    except Exception as e:  # noqa: BLE001
        return _err(_friendly(e))


def disconnect():
    try:
        _await(_controller().disconnect())
        _later_ip_check()
        return _ok()
    except Exception as e:  # noqa: BLE001
        return _err(_friendly(e))


# ------------------------------------------------------------------ settings
# setting_path -> (available on the free plan, kind)
SETTINGS = {
    "killswitch": (True, "killswitch"),
    "features.netshield": (False, "netshield"),
    "features.vpn_accelerator": (False, "bool"),
    "features.moderate_nat": (False, "bool"),
    "features.port_forwarding": (False, "bool"),
    "ipv6": (True, "bool"),
    "anonymous_crash_reports": (True, "bool"),
}


def settings():
    try:
        ctl = _controller()
        s = _await(ctl.get_settings())
        dns = s.custom_dns
        return _ok(killswitch=int(s.killswitch), netshield=int(s.features.netshield),
                   vpn_accelerator=bool(s.features.vpn_accelerator), moderate_nat=bool(s.features.moderate_nat),
                   port_forwarding=bool(s.features.port_forwarding), ipv6=bool(s.ipv6),
                   anonymous_crash_reports=bool(s.anonymous_crash_reports),
                   custom_dns=bool(dns.enabled), custom_dns_ips=", ".join(str(getattr(x, "ip", x)) for x in dns.ip_list),
                   free=ctl.user_on_free_tier if ctl.is_logged_in else True,
                   startup=prefs().get("startup", "off"), startupCountry=prefs().get("startupCountry", ""))
    except Exception as e:  # noqa: BLE001
        return _err(_friendly(e))


def set_setting(path, value):
    try:
        from proton.vpn.cli.core.controller import Feature
        from proton.vpn.core.settings.features import NetShield
        from proton.vpn.killswitch.interface.killswitch import KillSwitchState
        free_ok, kind = SETTINGS[path]
        v = {"killswitch": lambda x: KillSwitchState(int(x)), "netshield": lambda x: NetShield(int(x)),
             "bool": bool}[kind](value)
        ctl = _controller()
        _await(ctl.save_feature_setting(Feature(setting_path=path, available_on_free_tier=free_ok), v), timeout=90)
        if path == "killswitch":
            # Proton adds the route that lets the tunnel past its kill switch when it
            # connects; switching the kill switch on mid-connection would cut the tunnel
            # off, so reconnect to the same server.
            st = status()
            if st.get("ok") and st.get("state") == "CONNECTED" and st.get("server"):
                r = connect({"server": st["server"]["name"]})
                if not r["ok"]:
                    return _ok(warning="Kill switch saved, but reconnecting failed: " + r["error"])
                return _ok(reconnected=True)
        return _ok()
    except Exception as e:  # noqa: BLE001
        return _err(_friendly(e))


def set_custom_dns(enabled, ips):
    try:
        from proton.vpn.cli.core.controller import Feature
        ctl = _controller()
        entries = ctl.parse_dns_ips([x for x in re.split(r"[,\s]+", ips or "") if x]) if enabled else []
        if enabled and not entries:
            return _err("Enter at least one DNS address.")
        _await(ctl.save_feature_setting(Feature(setting_path="custom_dns", available_on_free_tier=False),
                                        ctl.to_custom_dns(bool(enabled), entries)), timeout=90)
        return _ok()
    except Exception as e:  # noqa: BLE001
        return _err(_friendly(e))


# ------------------------------------------------------ connect at startup
def prefs():
    try:
        with open(PREFS) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_prefs(p):
    os.makedirs(CONF_DIR, exist_ok=True)
    tmp = PREFS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(p, f, indent=1)
    os.replace(tmp, PREFS)


def _remember(name):
    p = prefs()
    recent = [n for n in p.get("recent", []) if n != name]
    p["recent"] = [name] + recent[:4]
    p["last"] = name
    _save_prefs(p)


def recent():
    out = []
    for n in prefs().get("recent", []):
        out.append(_cached_server(n) or {"name": n})
    return out


def set_startup(mode, country=""):
    """mode: off | fastest | last | country -- a systemd user service connects after login."""
    try:
        p = prefs()
        p["startup"], p["startupCountry"] = mode, country
        _save_prefs(p)
        unit_path = os.path.join(UNIT_DIR, UNIT)
        if mode == "off":
            subprocess.run(["systemctl", "--user", "disable", UNIT], capture_output=True)
            if os.path.exists(unit_path):
                os.remove(unit_path)
            subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
            return _ok()
        os.makedirs(UNIT_DIR, exist_ok=True)
        # /opt/click.ubuntu.com/<pkg>/current always points at the installed version
        cur = "/opt/click.ubuntu.com/%s/current" % APP
        base = cur if os.path.isdir(cur) else ROOT
        with open(unit_path, "w") as f:
            f.write("[Unit]\nDescription=Seal VPN for Proton: connect at startup\n"
                    "After=graphical-session.target\n\n"
                    "[Service]\nType=oneshot\nExecStart=/usr/bin/python3 -I %s/host/autoconnect.py\n"
                    "TimeoutStartSec=600\n\n[Install]\nWantedBy=default.target\n" % base)
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        r = subprocess.run(["systemctl", "--user", "enable", UNIT], capture_output=True, text=True)
        if r.returncode != 0:
            return _err("Couldn't set up the startup service: " + (r.stderr or r.stdout).strip())
        return _ok()
    except Exception as e:  # noqa: BLE001
        return _err(_friendly(e))


def startup_target():
    p = prefs()
    m = p.get("startup", "off")
    if m == "last" and p.get("last"):
        return {"server": p["last"]}
    if m == "country" and p.get("startupCountry"):
        return {"country": p["startupCountry"]}
    return {}


# ------------------------------------------- the old (config-file) version
def _nm(*args):
    return subprocess.run(["nmcli"] + list(args), capture_output=True, text=True, timeout=45)


def _cleanup_old_version():
    """The config-file Seal VPN's kill switch would block Proton's own tunnels: remove it."""
    done = []
    r = _nm("-t", "-f", "NAME,TYPE", "connection", "show")
    for line in r.stdout.splitlines():
        name, _, typ = line.rpartition(":")
        if name.replace("\\:", ":") == OLD_KILL_SWITCH and typ == "dummy":
            if _nm("connection", "delete", OLD_KILL_SWITCH).returncode == 0:
                done.append("Removed the old Seal VPN kill switch (Proton's own kill switch replaces it).")
    if os.path.exists(OLD_META):
        try:
            os.remove(OLD_META)
        except OSError:
            pass
    return done


def manual_vpns():
    """WireGuard connections not made by Proton's client (e.g. imported .conf files)."""
    out = []
    r = _nm("-t", "-f", "NAME,UUID,TYPE,AUTOCONNECT,ACTIVE", "connection", "show")
    for line in r.stdout.splitlines():
        f = re.split(r"(?<!\\):", line)
        if len(f) >= 5 and f[2] == "wireguard" and not f[0].startswith("ProtonVPN "):
            out.append({"name": f[0].replace("\\:", ":"), "uuid": f[1], "autoconnect": f[3] == "yes", "active": f[4] == "yes"})
    return out


def remove_manual_vpn(uuid):
    r = _nm("connection", "delete", uuid)
    return _ok() if r.returncode == 0 else _err((r.stderr or r.stdout).strip())


# ---------------------------------------------------------------- public IP
_ip_lock = threading.Lock()


def check_ip():
    threading.Thread(target=_ip_worker, daemon=True).start()
    return _ok()


def _later_ip_check():
    def w():
        time.sleep(3)
        _ip_worker()
    threading.Thread(target=w, daemon=True).start()


def _ip_worker():
    if not _ip_lock.acquire(blocking=False):
        return
    try:
        res = {"ok": False, "ip": "", "place": "", "isp": ""}
        try:
            req = urllib.request.Request("https://ipinfo.io/json",
                                         headers={"User-Agent": "SealVPN-UbuntuTouch", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                j = json.loads(r.read().decode())
            res.update(ok=True, ip=j.get("ip", ""), place=", ".join(x for x in (j.get("city", ""), j.get("country", "")) if x),
                       isp=re.sub(r"^AS\d+\s+", "", j.get("org", "")))
        except Exception as e:  # noqa: BLE001
            res["error"] = "No internet" if any(k in str(e) for k in ("nreachable", "timed out", "resolution", "No route")) else "Unavailable"
        _send("ip", res)
    finally:
        _ip_lock.release()


def version():
    try:
        with open(os.path.join(HERE, "version.txt")) as f:
            return f.read().strip()
    except OSError:
        return "dev"


def proton_version():
    try:
        from importlib import metadata
        return "CLI %s · api-core %s" % (metadata.version("proton-vpn-cli"), metadata.version("proton-vpn-api-core"))
    except Exception:  # noqa: BLE001
        return ""
