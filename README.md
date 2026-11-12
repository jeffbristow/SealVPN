# Seal VPN for Proton

A touch app for **Ubuntu Touch 24.04 (arm64)** that runs **Proton VPN's own Linux client**. Proton has no Ubuntu Touch app, so Seal VPN puts a phone screen on the official Proton VPN CLI and its libraries, bundled unchanged. Sign in with your Proton account and connect to any Proton server.

Not made by or affiliated with Proton AG.

- `qml/Main.qml`: the screen (Lomiri Components)
- `host/sealvpn.py`: drives Proton's CLI controller (sign-in with 2FA, servers, connect/disconnect, settings)
- `host/autoconnect.py`: "Connect at startup" (systemd user service)
- `tools/fetch_deps.py`: downloads Proton's client and the Ubuntu packages it needs, and checks them against the archives' GPG keys in `tools/keys/`
- `vendor/lib/MANIFEST.json`: the exact package versions in the last build

Architecture, building and installing are in [README.txt](README.txt).

## Build

```
node build.js             # → dist/sealvpn.jeffbristow_<version>_arm64.click
node build.js --refresh   # download the newest Proton client first
```

The downloaded packages (`vendor/`) aren't in git. The first build fetches them with `tools/fetch_deps.py` (Python 3).

## License

GPL-3.0, the same license as the Proton VPN client it bundles.
