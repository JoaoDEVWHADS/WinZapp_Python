"""Run only the patched utility in a VM, with storage/network fully stubbed."""

from pathlib import Path
import subprocess
import shutil
import sys

import pytest


def test_s3_is_loaded_only_for_an_upload():
    root = Path(__file__).resolve().parents[1]
    node = root / ("client/node/node.exe" if sys.platform == "win32" else "client/node/node")
    node_executable = str(node) if node.is_file() else shutil.which("node")
    if not node_executable or not (root / "client/api/node_modules/@babel/core").is_dir():
        pytest.skip("bundled API build tools are unavailable")
    script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const babel = require('./client/api/node_modules/@babel/core');
const code = babel.transformSync(fs.readFileSync('./client/api_patches/src/util/functions.ts', 'utf8'), {
  filename: 'functions.ts', babelrc: false, configFile: false,
  presets: [require.resolve('./client/api/node_modules/@babel/preset-typescript')],
  plugins: [require.resolve('./client/api/node_modules/@babel/plugin-transform-modules-commonjs')]
}).code;
let loads = 0, uploads = 0;
const config = {webhook: {uploadS3: true}, websocket: {},
  aws_s3: {region: 'test', access_key_id: 'test', secret_key: 'test', defaultBucketName: 'bucket'}};
const exports = {};
const load = name => {
  if (name === '../config') return {__esModule: true, default: config};
  if (name === '@aws-sdk/client-s3') {
    loads++;
    return {S3Client: class {async send() {uploads++;}},
      PutObjectCommand: class {}, CreateBucketCommand: class {}, PutPublicAccessBlockCommand: class {}};
  }
  if (name === './bucketAlreadyExists') return {bucketAlreadyExists: async () => true};
  if (name === 'mime-types') return {extension: () => 'ogg'};
  if (['fs', 'os', 'path', 'util', 'crypto'].includes(name)) return require(name);
  if (name === '..') return {logger: {error: e => {throw e;}}};
  return {};
};
vm.runInNewContext(code, {exports, require: load, Buffer});
assert.equal(loads, 0);
(async () => {
  const client = {session: 'test', decryptFile: async () => Buffer.from('media')};
  const req = {serverOptions: {webhook: {uploadS3: false}, websocket: {}}, logger: {error: e => {throw e;}}};
  const message = {mimetype: 'audio/ogg'};
  await exports.autoDownload(client, req, message);
  assert.equal(message.body, Buffer.from('media').toString('base64'));
  assert.equal(loads, 0);
  req.serverOptions.webhook.uploadS3 = true;
  await exports.autoDownload(client, req, message);
  assert.equal(loads, 1);
  assert.equal(uploads, 1);
  assert.ok(message.fileUrl.startsWith('https://bucket.s3.amazonaws.com/'));
})().catch(e => { console.error(e); process.exitCode = 1; });
'''
    result = subprocess.run([node_executable, "-"], input=script,
                            cwd=root, text=True, capture_output=True, timeout=30,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 0, result.stderr
