=====================================================================
 SEAL VPN FOR PROTON (Ubuntu Touch 24.04, arm64) — project source
=====================================================================

Proton VPN has no Ubuntu Touch app. Seal VPN is a touch front end for
Proton VPN's OWN Linux client: the official Proton VPN CLI and the
libraries it's built on (proton-vpn-api-core, proton-core, …, GPLv3),
bundled unchanged in the click. Sign in with a Proton account, then
connect to any Proton server. Not made by or affiliated with Proton AG.

HOW IT WORKS
  qml/Main.qml          the screen (Lomiri Components)
  host/sealvpn.py       the native side (pyotherside). It drives Proton's
                        CLI Controller (proton.vpn.cli.core.controller) on an
                        asyncio loop in a background thread: login + 2FA,
                        server list, find fastest/country/city/feature,
                        connect/disconnect, Proton's settings. So the app
                        talks to Proton as Proton's CLI does
                        (linux-vpn-cli@<version>+aarch64).
  host/autoconnect.py   "Connect at startup": run by the systemd USER service
                        ~/.config/systemd/user/sealvpn-autoconnect.service
                        (written/enabled from Settings; runs the installed
                        click via /opt/click.ubuntu.com/sealvpn.jeffbristow/current)
  lib/python, lib/native, lib/girepository-1.0
                        the bundled libraries (see BUILD). sealvpn.py puts them
                        on sys.path, preloads libsodium and sets GI_TYPELIB_PATH
                        itself — nothing is installed system-wide.
  Connections are NetworkManager WireGuard connections made by Proton's code
  ("ProtonVPN <server>", interface proton0); they keep running with the app
  closed. Proton's session is kept in the keyring (gnome-keyring).
  Proton's settings: ~/.config/Proton/VPN/   logs: ~/.cache/Proton/VPN/logs/
  App prefs (recent servers, connect at startup): ~/.config/sealvpn.jeffbristow/

PERMISSIONS
  UNCONFINED click (sealvpn.apparmor): NetworkManager, the keyring and a
  systemd user service. Lomiri starts apps as systemd user units, and
  polkit's org.freedesktop.NetworkManager.rules lets the sudo group in the
  active local session modify system connections — no password prompt.
  (nmcli over `adb shell` is NOT in that context; test through
  `systemd-run --user --wait`.)

KILL SWITCH (Proton's own)
  Off / Standard (blocks if the VPN drops; a deliberate disconnect releases
  it) / Advanced (= Proton's "permanent": no internet unless connected, also
  after a restart; NM connection pvpn-killswitch-perm).
  Proton adds the route that lets the tunnel past the switch when it
  connects, so changing the switch while connected makes the app reconnect.
  Emergency off:  nmcli connection delete pvpn-killswitch-perm
                  nmcli connection delete pvpn-killswitch

NOT AVAILABLE ON THE PHONE
  Split tunneling: Proton's proton-vpn-daemon needs eBPF tooling (bcc) that
  Halium kernels lack; it isn't bundled, and Proton's code runs without it.
  Security-key (FIDO2) sign-in: use an authenticator code.
  Proton's "human verification" (CAPTCHA) at sign-in isn't supported by the
  CLI code: sign-in then fails with a message; try again later.

UPGRADING FROM 1.x (config-file version)
  On first start the app deletes 1.x's "Seal VPN kill switch" (it would
  block Proton's tunnels) and offers to remove other WireGuard connections
  (imported .conf files) so they don't clash.

BUILD
  node build.js            → dist\sealvpn.jeffbristow_<version>_arm64.click
  node build.js --refresh  re-download the newest Proton client first
  tools/fetch_deps.py (run by build.js when vendor/lib is missing):
    * repo.protonvpn.com/debian "stable": Release GPG-checked with
      tools/keys/proton-archive-keyring.gpg (Proton Technologies AG,
      84B0 D349 2C76 C9C6 F587 3C18 EDA3 E226 3034 9F1C — the same key as in
      Proton's protonvpn-stable-release package), packages SHA256-checked;
    * ports.ubuntu.com noble/-updates/-security arm64: InRelease GPG-checked
      with tools/keys/ubuntu-archive-keyring.gpg (from the phone), packages
      SHA256-checked;
    * newest version of each pinned package (lists at the top of the file);
      the build stops if Proton adds a dependency that isn't bundled.
  Needs Python 3 and gpgv (Git for Windows has one) on the PC.
  Version: package.json.  Bundled versions: lib/MANIFEST.json in the click.
  Licences: lib/licenses/ (each package's Debian copyright file;
  python3-proton-vpn-local-agent ships none — GPLv3, Proton AG).

INSTALL
  copy the click to the phone, then:
    busctl --system call com.lomiri.click /com/lomiri/click com.lomiri.click Install s /home/phablet/<file>.click
