"""client/api_patches/decrypt.js returns exactly the original media bytes.

WhatsApp media is AES-256-CBC with PKCS#7 padding plus a 10-byte MAC. A file
whose size is a multiple of 16 gets a whole padding block of 0x10, which
magix() used to leave on the saved file (a downloaded APK then failed to
parse on Android). The shipped file runs under Node with its two npm
dependencies replaced by equivalents from Node's own crypto, so no
node_modules is needed.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DECRYPT = ROOT / "client/api_patches/decrypt.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="Node required to run decrypt.js")

HARNESS = r"""
const crypto = require('crypto');
const vm = require('vm');
const fs = require('fs');
const { Readable, Writable } = require('stream');
const { pipeline } = require('stream/promises');
const [path, sizesJson] = process.argv.slice(1);
const hkdf = (ikm, length, { salt, info, hash }) =>
  Buffer.from(crypto.hkdfSync(hash, ikm, salt, info, length));
const fakeRequire = (name) => ({
  'futoin-hkdf': { default: hkdf, __esModule: true },
  atob: { default: (s) => Buffer.from(s, 'base64').toString('binary'), __esModule: true },
}[name] || require(name));
const module = { exports: {} };
vm.runInThisContext('(function (exports, require, module) {' +
  fs.readFileSync(path, 'utf8') + '\n})')(module.exports, fakeRequire, module);
const { magix, newMagix } = module.exports;

const mediaKey = crypto.randomBytes(32);
const expanded = hkdf(mediaKey, 112, { salt: Buffer.alloc(32), info: 'WhatsApp Document Keys', hash: 'sha256' });
const encrypt = (plain) => {
  const cipher = crypto.createCipheriv('aes-256-cbc', expanded.subarray(16, 48), expanded.subarray(0, 16));
  return Buffer.concat([cipher.update(plain), cipher.final(), crypto.randomBytes(10)]);
};
(async () => {
  const out = {};
  for (const size of JSON.parse(sizesJson)) {
    const plain = crypto.randomBytes(size);
    const file = encrypt(plain);
    const viaMagix = magix(file, mediaKey.toString('base64'), 'document', size);
    const chunks = [];
    const sink = new Writable({ write(c, _e, cb) { chunks.push(c); cb(); } });
    const pieces = [];
    for (let i = 0; i < file.length; i += 7) pieces.push(file.subarray(i, i + 7));
    await pipeline(Readable.from(pieces), newMagix(mediaKey.toString('base64'), 'document', size), sink);
    out[size] = { magix: Buffer.compare(viaMagix, plain) === 0,
                  newMagix: Buffer.compare(Buffer.concat(chunks), plain) === 0 };
  }
  console.log(JSON.stringify(out));
})();
"""


@pytest.mark.parametrize("size", [16, 4096, 65536, 1, 17, 4095, 4097])
def test_decrypt_returns_original_bytes(size):
    result = subprocess.run(
        [NODE, "-e", HARNESS, str(DECRYPT), json.dumps([size])],
        capture_output=True, text=True, timeout=60, check=True,
    )
    assert json.loads(result.stdout)[str(size)] == {"magix": True, "newMagix": True}
