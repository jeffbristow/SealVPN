/* =====================================================================
 * Seal VPN for Proton (Ubuntu Touch) — build.js
 *   node build.js            checks + dist/sealvpn.jeffbristow_<version>_arm64.click
 *   node build.js --refresh  first re-download Proton's client + the Ubuntu libraries
 *                            (tools/fetch_deps.py; also runs when vendor/lib/python is missing,
 *                            e.g. in a fresh clone)
 * A click is a Debian-style ar archive: debian-binary, _click-binary,
 * control.tar.gz (control, manifest, md5sums) and data.tar.gz (the files);
 * built here without clickable (same builder as Seal Chat for Ubuntu Touch).
 * ===================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const crypto = require('crypto');
const { execFileSync } = require('child_process');

const ROOT = __dirname;
const PKG = 'sealvpn.jeffbristow';
const VERSION = require(path.join(ROOT, 'package.json')).version;
const LIB = path.join(ROOT, 'vendor', 'lib');
const py = process.platform === 'win32' ? 'python' : 'python3';

/* ---------- 1. THE BUNDLED PROTON CLIENT + CHECKS ---------- */
if (process.argv.includes('--refresh') || !fs.existsSync(path.join(LIB, 'python')))
  execFileSync(py, ['-I', path.join(ROOT, 'tools', 'fetch_deps.py')], { stdio: 'inherit' });
const libManifest = JSON.parse(fs.readFileSync(path.join(LIB, 'MANIFEST.json'), 'utf8'));
execFileSync(py, ['-I', path.join(ROOT, 'test', 'test_sealvpn.py'), path.join(ROOT, 'host')], { stdio: 'inherit' });
for (const f of ['sealvpn.py', 'autoconnect.py']) execFileSync(py, ['-I', '-m', 'py_compile', path.join(ROOT, 'host', f)], { stdio: 'inherit' });
JSON.parse(fs.readFileSync(path.join(ROOT, 'sealvpn.apparmor'), 'utf8'));

/* ---------- 2. THE FILES ---------- */
const files = [];                                   // [name, Buffer | null (folder), mode]
const dirs = new Set();
function addDir(d) { if (!d || d === '.' || dirs.has(d)) return; addDir(path.posix.dirname(d)); dirs.add(d); files.push(['./' + d, null]); }
function add(dest, data, mode) { addDir(path.posix.dirname(dest)); files.push(['./' + dest, Buffer.isBuffer(data) ? data : Buffer.from(data), mode || 0o644]); }
const lf = (f) => Buffer.from(fs.readFileSync(path.join(ROOT, f), 'utf8').replace(/\r\n/g, '\n'));
function addTree(src, dest) {
  for (const n of fs.readdirSync(src).sort()) {
    if (n === '__pycache__' || n.endsWith('.pyc')) continue;
    const f = path.join(src, n), d = dest + '/' + n;
    if (fs.statSync(f).isDirectory()) { addDir(d); addTree(f, d); }
    else add(d, fs.readFileSync(f), /\.so(\.\d+)*$/.test(n) ? 0o755 : 0o644);
  }
}

add('qml/Main.qml', lf('qml/Main.qml'));
add('host/sealvpn.py', lf('host/sealvpn.py'));
add('host/autoconnect.py', lf('host/autoconnect.py'), 0o755);
add('host/version.txt', VERSION + '\n');
add('assets/icon.svg', lf('assets/icon.svg'));
for (const f of ['sealvpn.desktop', 'sealvpn.apparmor', 'README.txt']) add(f, lf(f));
for (const d of ['python', 'native', 'girepository-1.0', 'licenses']) addTree(path.join(LIB, d), 'lib/' + d);
add('lib/MANIFEST.json', fs.readFileSync(path.join(LIB, 'MANIFEST.json')));

const manifest = {
  name: PKG, title: 'Seal VPN for Proton', version: VERSION, maintainer: 'Jeff Bristow <noreply@sealpgp.com>',
  description: 'Proton VPN for Ubuntu Touch, using Proton\'s official Linux client',
  framework: process.env.UT_FRAMEWORK || 'ubuntu-touch-24.04-1.x', architecture: 'arm64',
  hooks: { sealvpn: { apparmor: 'sealvpn.apparmor', desktop: 'sealvpn.desktop' } },
  'installed-size': String(Math.ceil(files.reduce((s, [, d]) => s + (d ? d.length : 0), 0) / 1024))
};
const manifestBuf = Buffer.from(JSON.stringify(manifest, null, 2) + '\n');
add('manifest.json', manifestBuf);

/* ---------- 3. THE CLICK ---------- */
function tar(entries) {
  const blocks = [];
  const oct = (n, len) => n.toString(8).padStart(len - 1, '0') + '\0';
  const now = Math.floor(Date.now() / 1000);
  for (const [name, data, mode] of entries) {
    const h = Buffer.alloc(512);
    const isDir = data === null;
    let nm = isDir && name !== './' ? name + '/' : name, prefix = '';
    if (Buffer.byteLength(nm) > 99) {               // ustar: split into prefix (155) + name (100)
      const i = nm.lastIndexOf('/', 154);
      prefix = nm.slice(0, i); nm = nm.slice(i + 1);
      if (Buffer.byteLength(nm) > 99 || Buffer.byteLength(prefix) > 154) throw new Error('path too long for the click: ' + name);
    }
    h.write(nm, 0, 100, 'utf8');
    h.write(oct(mode || (isDir ? 0o755 : 0o644), 8), 100);
    h.write(oct(0, 8), 108); h.write(oct(0, 8), 116);
    h.write(oct(isDir ? 0 : data.length, 12), 124);
    h.write(oct(now, 12), 136);
    h.write('        ', 148);
    h.write(isDir ? '5' : '0', 156);
    h.write('ustar\0', 257); h.write('00', 263);
    h.write('root', 265); h.write('root', 297);
    h.write(prefix, 345, 155, 'utf8');
    let sum = 0; for (const b of h) sum += b;
    h.write(oct(sum, 7) + ' ', 148);
    blocks.push(h);
    if (!isDir) { blocks.push(data); const pad = (512 - (data.length % 512)) % 512; if (pad) blocks.push(Buffer.alloc(pad)); }
  }
  blocks.push(Buffer.alloc(1024));
  return Buffer.concat(blocks);
}
function ar(members) {
  const parts = [Buffer.from('!<arch>\n')];
  const now = String(Math.floor(Date.now() / 1000));
  for (const [name, data] of members) {
    const h = Buffer.alloc(60, ' ');
    h.write(name.padEnd(16), 0); h.write(now.padEnd(12), 16);
    h.write('0'.padEnd(6), 28); h.write('0'.padEnd(6), 34); h.write('100644'.padEnd(8), 40);
    h.write(String(data.length).padEnd(10), 48); h.write('`\n', 58);
    parts.push(h, data);
    if (data.length % 2) parts.push(Buffer.from('\n'));
  }
  return Buffer.concat(parts);
}

const md5sums = files.filter(([, d]) => d).map(([n, d]) => `${crypto.createHash('md5').update(d).digest('hex')}  ${n.slice(2)}`).join('\n') + '\n';
const control = [`Package: ${PKG}`, `Version: ${VERSION}`, 'Click-Version: 0.4', 'Architecture: arm64',
  `Maintainer: ${manifest.maintainer}`, `Installed-Size: ${manifest['installed-size']}`, `Description: ${manifest.description}`, ''].join('\n');
const controlTar = zlib.gzipSync(tar([['./', null], ['./control', Buffer.from(control)], ['./manifest', manifestBuf], ['./md5sums', Buffer.from(md5sums)]]));
const dataTar = zlib.gzipSync(tar([['./', null], ...files]), { level: 9 });
const click = ar([['debian-binary', Buffer.from('2.0\n')], ['_click-binary', Buffer.from('0.4\n')], ['control.tar.gz', controlTar], ['data.tar.gz', dataTar]]);
const out = path.join(ROOT, 'dist', `${PKG}_${VERSION}_arm64.click`);
fs.mkdirSync(path.dirname(out), { recursive: true });
fs.writeFileSync(out, click);
console.log(`click: ${out} (${(click.length / 1048576).toFixed(1)} MB; Proton CLI ${libManifest.proton['proton-vpn-cli']}, api-core ${libManifest.proton['python3-proton-vpn-api-core']})`);
