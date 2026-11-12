"""
Seal VPN for Proton -- "Connect at startup".
Run by the systemd user service sealvpn-autoconnect.service after login:
waits for a network and for the keyring (Proton's saved sign-in), then
connects the way the app would (fastest / last server / a country).
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sealvpn  # noqa: E402


def log(*a):
    print("sealvpn-autoconnect:", *a, flush=True)


def network_up():
    r = subprocess.run(["nmcli", "-t", "-f", "STATE", "general"], capture_output=True, text=True)
    return r.stdout.strip().startswith("connected")


def main():
    target = sealvpn.startup_target()
    if sealvpn.prefs().get("startup", "off") == "off":
        log("connect at startup is off")
        return 0
    deadline = time.time() + 300
    while not network_up() and time.time() < deadline:
        time.sleep(5)
    for attempt in range(1, 6):
        st = sealvpn.status()
        if st.get("ok") and not st.get("loggedIn"):
            log("not signed in (or the keyring is still locked); retrying")
        elif st.get("ok") and st.get("state") in ("CONNECTED", "CONNECTING"):
            log("already connected to", (st.get("server") or {}).get("name"))
            return 0
        elif st.get("ok"):
            r = sealvpn.connect(target)
            if r.get("ok"):
                log("connected to", r["server"]["name"])
                return 0
            log("attempt %d failed: %s" % (attempt, r.get("error")))
        else:
            log("attempt %d: %s" % (attempt, st.get("error")))
        time.sleep(20)
        # a fresh controller re-reads the session (the keyring may have unlocked meanwhile)
        sealvpn._ctl = None
        sealvpn._subscribed = False
    log("giving up")
    return 1


if __name__ == "__main__":
    sys.exit(main())
