"""PC-side checks of host/sealvpn.py parts that don't need the phone.
Run by build.js:  python -I test/test_sealvpn.py <path to host/>"""
import os
import sys
import tempfile

sys.path.insert(0, sys.argv[1])
import sealvpn  # noqa: E402  (bundled Proton libraries aren't importable on a PC; only pure helpers are tested)

fails = 0


def check(name, cond):
    global fails
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails += 1


class AuthenticationFailedError(Exception):
    pass


class Odd(Exception):
    pass


check("friendly: wrong password", sealvpn._friendly(AuthenticationFailedError()) == "Wrong username or password.")
check("friendly: unknown error keeps its text", sealvpn._friendly(Odd("boom")) == "boom")
check("friendly: unknown error without text", sealvpn._friendly(Odd()) == "Odd")

d = tempfile.mkdtemp()
sealvpn.CONF_DIR, sealvpn.PREFS = d, os.path.join(d, "prefs.json")
check("startup: nothing saved", sealvpn.startup_target() == {})
sealvpn._remember("US-FL#297")
sealvpn._remember("CH#10")
sealvpn._remember("US-FL#297")
p = sealvpn.prefs()
check("recent: newest first, no duplicates", p["recent"] == ["US-FL#297", "CH#10"] and p["last"] == "US-FL#297")
p["startup"] = "last"
sealvpn._save_prefs(p)
check("startup: last server", sealvpn.startup_target() == {"server": "US-FL#297"})
p["startup"], p["startupCountry"] = "country", "CH"
sealvpn._save_prefs(p)
check("startup: country", sealvpn.startup_target() == {"country": "CH"})
p["startup"] = "fastest"
sealvpn._save_prefs(p)
check("startup: fastest", sealvpn.startup_target() == {})

print("%d failed" % fails if fails else "all host checks passed")
sys.exit(1 if fails else 0)
