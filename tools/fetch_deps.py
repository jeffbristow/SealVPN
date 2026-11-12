"""
Seal VPN for Proton -- fetch and verify the bundled libraries.

    python -I tools/fetch_deps.py        (build.js runs it)

Downloads, from the official repositories only:
  * Proton VPN's Linux client (repo.protonvpn.com/debian, "stable"): the CLI and
    the libraries it is built on, arm64 builds where they are native;
  * the Ubuntu 24.04 (noble) arm64 packages they need that Ubuntu Touch 24.04
    doesn't ship (ports.ubuntu.com: noble, noble-updates, noble-security).
Every repository index is GPG-verified (tools/keys/), every package is checked
against the SHA256 in that index. The newest version of each package is used.
The result is unpacked into vendor/lib/ (git-ignored):
    vendor/lib/python/             -> the click's lib/python   (Python packages)
    vendor/lib/native/             -> lib/native               (libsodium)
    vendor/lib/girepository-1.0/   -> lib/girepository-1.0     (NM-1.0.typelib)
    vendor/lib/MANIFEST.json       package versions
Downloads are cached in vendor/debs/.
Not bundled: proton-vpn-daemon (split tunneling; needs eBPF tooling the phone
lacks -- Proton's code runs without it).
"""
import hashlib
import io
import json
import lzma
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYS = os.path.join(ROOT, "tools", "keys")
VENDOR = os.path.join(ROOT, "vendor")
DEBS = os.path.join(VENDOR, "debs")
OUT = os.path.join(VENDOR, "lib")
UA = {"User-Agent": "SealVPN-build (apt-like fetch)"}

PROTON = "https://repo.protonvpn.com/debian"
UBUNTU = "https://ports.ubuntu.com/ubuntu-ports"
SUITES = ["noble", "noble-updates", "noble-security"]

PROTON_PKGS = ["proton-vpn-cli", "python3-proton-vpn-api-core", "python3-proton-core", "python3-dbus-fast",
               "python3-proton-keyring-linux", "python3-proton-vpn-local-agent", "python3-proton-vpn-lib"]
PROTON_SKIP = {"proton-vpn-daemon"}
# Not part of Ubuntu Touch 24.04 (found by resolving the CLI's dependencies against the phone's packages)
UBUNTU_PKGS = ["python3-aiohttp", "python3-bcrypt", "python3-openssl", "python3-importlib-metadata", "python3-keyring",
               "python3-secretstorage", "python3-jinja2", "python3-nacl", "python3-fido2", "python3-sentry-sdk",
               "python3-click", "python3-tabulate", "python3-packaging", "python3-systemd", "python3-cairo",
               "python3-gi-cairo", "gir1.2-nm-1.0", "python3-yarl", "python3-async-timeout", "python3-aiosignal",
               "python3-attr", "python3-frozenlist", "python3-multidict", "python3-zipp", "python3-jaraco.classes",
               "python3-jeepney", "python3-markupsafe", "libsodium23", "python3-colorama", "python3-more-itertools"]


def gpgv_path():
    for p in [shutil.which("gpgv"), r"C:\Program Files\Git\usr\bin\gpgv.exe"]:
        if p and os.path.exists(p):
            return p
    sys.exit("gpgv not found (install Git for Windows or gnupg)")


def gp(path):
    """Paths as Git for Windows' (MSYS) gpgv understands them: C:/x -> /c/x."""
    if os.name == "nt" and "Git" in gpgv_path():
        p = os.path.abspath(path).replace("\\", "/")
        return "/" + p[0].lower() + p[2:]
    return path


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as r:
        return r.read()


def verify_detached(keyring, sig, data, what):
    tmp = os.path.join(VENDOR, "_verify")
    os.makedirs(tmp, exist_ok=True)
    s, d = os.path.join(tmp, "sig"), os.path.join(tmp, "data")
    open(s, "wb").write(sig)
    open(d, "wb").write(data)
    r = subprocess.run([gpgv_path(), "--keyring", gp(keyring), gp(s), gp(d)], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("GPG check FAILED for %s:\n%s" % (what, r.stderr))


def verify_clearsigned(keyring, data, what):
    tmp = os.path.join(VENDOR, "_verify")
    os.makedirs(tmp, exist_ok=True)
    f, o = os.path.join(tmp, "inrelease"), os.path.join(tmp, "signed")
    open(f, "wb").write(data)
    if os.path.exists(o):
        os.remove(o)
    r = subprocess.run([gpgv_path(), "--keyring", gp(keyring), "--output", gp(o), gp(f)], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("GPG check FAILED for %s:\n%s" % (what, r.stderr))
    return open(o, "rb").read()  # only the signed part


def sha256_index(release_text):
    out, on = {}, False
    for line in release_text.splitlines():
        if line.startswith("SHA256:"):
            on = True
            continue
        if on and not line.startswith(" "):
            on = False
        if on:
            h, _, name = line.split()
            out[name] = h
    return out


def parse_packages(text):
    pk = {}
    for block in text.split("\n\n"):
        d, key = {}, None
        for line in block.splitlines():
            if line.startswith(" ") and key:
                d[key] += "\n" + line
                continue
            if ":" in line:
                key, v = line.split(":", 1)
                d[key] = v.strip()
        if "Package" in d:
            pk.setdefault(d["Package"], []).append(d)
    return pk


def vkey(v):
    v = v.split(":")[-1]
    return [(0, int(x)) if x.isdigit() else (1, x) for x in re.split(r"[.\-+~]", v)]


def checked(data, want, what):
    got = hashlib.sha256(data).hexdigest()
    if got != want:
        sys.exit("SHA256 mismatch for %s" % what)
    return data


def proton_index():
    rel = get(PROTON + "/dists/stable/Release")
    verify_detached(os.path.join(KEYS, "proton-archive-keyring.gpg"), get(PROTON + "/dists/stable/Release.gpg"), rel, "Proton Release")
    idx = sha256_index(rel.decode())
    pk = {}
    for arch in ["all", "arm64"]:
        name = "main/binary-%s/Packages" % arch
        data = checked(get(PROTON + "/dists/stable/" + name), idx[name], "Proton " + name)
        for n, l in parse_packages(data.decode()).items():
            pk.setdefault(n, []).extend(l)
    return pk


def ubuntu_index():
    pk = {}
    for s in SUITES:
        rel = verify_clearsigned(os.path.join(KEYS, "ubuntu-archive-keyring.gpg"), get(UBUNTU + "/dists/%s/InRelease" % s), "Ubuntu " + s)
        idx = sha256_index(rel.decode())
        for c in ["main", "universe"]:
            name = "%s/binary-arm64/Packages.xz" % c
            data = lzma.decompress(checked(get(UBUNTU + "/dists/%s/%s" % (s, name)), idx[name], "Ubuntu %s %s" % (s, name)))
            for n, l in parse_packages(data.decode("utf-8", "replace")).items():
                pk.setdefault(n, []).extend(l)
        print("  Ubuntu %s: signature and indexes OK" % s)
    return pk


def fetch(base, d):
    os.makedirs(DEBS, exist_ok=True)
    f = os.path.join(DEBS, os.path.basename(d["Filename"]))
    if os.path.exists(f) and hashlib.sha256(open(f, "rb").read()).hexdigest() == d["SHA256"]:
        return f
    data = checked(get(base + "/" + d["Filename"]), d["SHA256"], d["Package"])
    open(f, "wb").write(data)
    return f


def lp(p):  # Windows long paths
    p = os.path.abspath(p)
    return ("\\\\?\\" + p) if os.name == "nt" else p


def unpack(deb, files):
    """Map a package's files into vendor/lib."""
    b = open(deb, "rb").read()
    assert b[:8] == b"!<arch>\n", deb
    i = 8
    while i < len(b):
        h = b[i:i + 60]
        mn, sz = h[:16].decode().strip().rstrip("/"), int(h[48:58])
        data = b[i + 60:i + 60 + sz]
        i += 60 + sz + (sz % 2)
        if not mn.startswith("data.tar"):
            continue
        with tarfile.open(fileobj=io.BytesIO(data)) as t:
            for m in t.getmembers():
                rel = os.path.normpath(m.name).replace("\\", "/")
                if rel.startswith("..") or os.path.isabs(rel):
                    continue
                dest = None
                if rel.startswith("usr/lib/python3/dist-packages/"):
                    dest = "python/" + rel[len("usr/lib/python3/dist-packages/"):]
                elif rel.startswith("usr/lib/aarch64-linux-gnu/girepository-1.0/"):
                    dest = "girepository-1.0/" + os.path.basename(rel)
                elif re.match(r"^usr/share/doc/[^/]+/copyright$", rel):
                    dest = "licenses/" + rel.split("/")[3] + ".copyright"  # each package's licence terms
                elif re.match(r"^usr/lib/aarch64-linux-gnu/libsodium\.so\.\d+\.\d+\.\d+$", rel):
                    dest = "native/libsodium.so.23"  # stored under its soname: no symlink needed
                if not dest or "__pycache__" in dest or not m.isfile():
                    continue
                p = os.path.join(OUT, *dest.split("/"))
                os.makedirs(lp(os.path.dirname(p)), exist_ok=True)
                with open(lp(p), "wb") as f:
                    f.write(t.extractfile(m).read())
                files.append(dest)


def main():
    print("Proton VPN repository (stable)...")
    ppk = proton_index()
    print("  signature and indexes OK")
    print("Ubuntu 24.04 arm64...")
    upk = ubuntu_index()
    manifest = {"proton": {}, "ubuntu": {}}
    plan = []
    for n in PROTON_PKGS:
        d = max(ppk[n], key=lambda d: vkey(d["Version"]))
        manifest["proton"][n] = d["Version"]
        plan.append((PROTON, d))
    # Proton may add dependencies in a new release: refuse to build silently without them
    known = set(PROTON_PKGS) | PROTON_SKIP
    for n in PROTON_PKGS:
        d = max(ppk[n], key=lambda d: vkey(d["Version"]))
        for alt in re.split(r",\s*", d.get("Depends", "")):
            dep = re.split(r"[\s(|:]", alt.strip())[0]
            if dep in ppk and dep not in known:
                sys.exit("Proton's %s now depends on %s, which isn't bundled yet: add it to PROTON_PKGS" % (n, dep))
    for n in UBUNTU_PKGS:
        d = max(upk[n], key=lambda d: vkey(d["Version"]))
        manifest["ubuntu"][n] = d["Version"]
        plan.append((UBUNTU, d))
    if os.path.exists(OUT):
        shutil.rmtree(lp(OUT))
    os.makedirs(OUT)
    files = []
    for base, d in plan:
        unpack(fetch(base, d), files)
    manifest["files"] = len(files)
    with open(os.path.join(OUT, "MANIFEST.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    shutil.rmtree(os.path.join(VENDOR, "_verify"), ignore_errors=True)
    print("vendor/lib: %d files from %d packages (Proton CLI %s, api-core %s)" % (
        len(files), len(plan), manifest["proton"]["proton-vpn-cli"], manifest["proton"]["python3-proton-vpn-api-core"]))


if __name__ == "__main__":
    main()
