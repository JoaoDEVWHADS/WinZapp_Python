"""Drop the WPPConnect server's development packages from the bundled runtime.

client/api is built with its devDependencies (TypeScript, Babel, ESLint,
Jest...), and build_app.py used to ship all of them: about 50,000 files in
node_modules, two thirds of them only ever used to compile src/ into dist/.
Every file costs the user time on every update — Sparkle unpacks and
verifies the whole app, and winzapp_mac/paths_mac.py clones the runtime into
Application Support.

What a Windows end user runs is the reference: ApiSetupDialog installs only
the runtime packages (`npm install --omit=dev`) after
core/api_dependencies.prepare_api_dependencies() has promoted every
devDependency that dist/ imports (@babel/runtime, mongoose, redis...). The
staged copy gets the same manifest, and this keeps exactly what npm would
install for it.

`npm prune --omit=dev` is not used. Measured on the 2.1.0 runtime
(2026-10-15) it trusted the lockfile's stale "dev" flags over the promoted
manifest and deleted @babel/runtime, mongoose, redis, crypto-js and
prom-client — dist/ requires all five. So the closure is computed here from
package-lock.json, the way Node resolves a require(), and every bare import
of dist/ and start.js is then resolved by the bundled Node itself: a missing
package stops the build instead of shipping.
"""

import importlib.util
import json
import os
import re
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
API_DEPENDENCIES = os.path.join(os.path.dirname(HERE), "client", "core", "api_dependencies.py")
# require('pkg') / require("@scope/pkg/sub") with an npm-shaped (lowercase)
# name. dist/ is CommonJS (Babel), so this is every package it loads; the
# lowercase rule skips the page-side require('WAWeb...') calls wa-js evaluates
# inside WhatsApp Web, which are not Node modules.
_REQUIRE = re.compile(r'''\brequire\(\s*["']((?:@[a-z0-9~-][a-z0-9._~-]*/)?[a-z0-9~-][a-z0-9._~-]*(?:/[^"'\s]*)?)["']\s*\)''')
# Read by the server at run time but outside dist/: start.js's own requires.
EXTRA_ENTRY_FILES = ("start.js",)


def load_api_dependencies():
    """client/core/api_dependencies.py by path: pure standard library, and
    the same promotion ApiSetupDialog applies on Windows."""
    spec = importlib.util.spec_from_file_location("winzapp_api_dependencies", API_DEPENDENCIES)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def package_name(spec):
    """'@scope/pkg/sub/path' -> '@scope/pkg', 'pkg/sub' -> 'pkg'."""
    parts = spec.split("/")
    return "/".join(parts[:2]) if spec.startswith("@") else parts[0]


def _resolve(packages, from_path, name):
    """Where Node finds *name* when required from lockfile path *from_path*:
    its own node_modules, then each enclosing one up to the root."""
    path = from_path
    while True:
        candidate = (path + "/node_modules/" + name) if path else ("node_modules/" + name)
        if candidate in packages:
            return candidate
        if not path:
            return None
        cut = path.rfind("/node_modules/")
        path = path[:cut] if cut >= 0 else ""


def runtime_closure(lock, roots):
    """Lockfile paths reachable from the root package's *roots* through
    dependencies, optionalDependencies and peerDependencies. An optional or
    peer package the lockfile does not hold is simply absent, as in npm."""
    packages = lock.get("packages", {})
    keep = set()
    todo = [("", name) for name in roots]
    while todo:
        from_path, name = todo.pop()
        path = _resolve(packages, from_path, name)
        if path is None or path in keep:
            continue
        keep.add(path)
        entry = packages[path]
        if entry.get("link") and entry.get("resolved") in packages:
            keep.add(entry["resolved"])
            entry = packages[entry["resolved"]]
        for field in ("dependencies", "optionalDependencies", "peerDependencies"):
            todo.extend((path, dep) for dep in entry.get(field, {}))
    return keep


def removable(lock, keep):
    """Installed lockfile paths outside *keep*, outermost first, never one
    that holds a kept package."""
    out = []
    for path in sorted(lock.get("packages", {}), key=lambda p: (p.count("/node_modules/"), p)):
        if not path.startswith("node_modules/") or path in keep:
            continue
        if any(k.startswith(path + "/") for k in keep):
            continue
        if any(path.startswith(done + "/") for done in out):
            continue
        out.append(path)
    return out


def entry_imports(api_dir):
    """Bare package names imported by dist/ and start.js — what the server
    loads at run time. Babel also compiles upstream's Jest files into dist/;
    they import test tooling and are skipped, as prepare_api_dependencies()
    skips them."""
    names = set()
    files = [os.path.join(api_dir, f) for f in EXTRA_ENTRY_FILES]
    for root, _dirs, filenames in os.walk(os.path.join(api_dir, "dist")):
        if "tests" in os.path.relpath(root, api_dir).split(os.sep):
            continue
        files += [os.path.join(root, f) for f in filenames
                  if f.endswith(".js") and ".test." not in f and ".spec." not in f]
    for path in files:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        for spec in _REQUIRE.findall(text):
            if not spec.startswith("node:"):
                names.add(package_name(spec))
    return names


def _drop_dangling_links(node_modules):
    """.bin entries of removed packages would point nowhere inside the signed app."""
    for root, dirs, files in os.walk(node_modules):
        for name in dirs + files:
            path = os.path.join(root, name)
            if os.path.islink(path) and not os.path.exists(path):
                os.unlink(path)


def unresolved_imports(api_dir, node, names):
    """The names among *names* the bundled Node cannot resolve from api_dir.
    Node's own builtin modules are never missing."""
    script = ("const {builtinModules} = require('module');"
              "const names = JSON.parse(process.argv[1]);"
              "const missing = names.filter(n => !builtinModules.includes(n) && (() => {"
              "  try { require.resolve(n + '/package.json', {paths: [process.cwd()]}); return false; }"
              "  catch (e) { try { require.resolve(n, {paths: [process.cwd()]}); return false; }"
              "              catch (e2) { return true; } } })());"
              "process.stdout.write(JSON.stringify(missing));")
    r = subprocess.run([node, "-e", script, json.dumps(sorted(names))], cwd=api_dir,
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def prune_dev_modules(api_dir, node):
    """Remove from *api_dir*/node_modules every package the server cannot
    reach at run time. Returns (packages removed, unresolved imports): the
    caller stops the build on any of the latter. Leaves everything in place
    when the manifest has install scripts it cannot judge, as
    prepare_api_dependencies() does."""
    flags = load_api_dependencies().prepare_api_dependencies(api_dir, building=False)
    if flags != ["--omit=dev"]:
        print("   (manifest has its own install/build scripts; development packages kept)")
        return 0, []
    with open(os.path.join(api_dir, "package.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    with open(os.path.join(api_dir, "package-lock.json"), encoding="utf-8") as fh:
        lock = json.load(fh)
    roots = set(manifest.get("dependencies", {})) | set(manifest.get("optionalDependencies", {}))
    roots |= set(manifest.get("peerDependencies", {})) | entry_imports(api_dir)
    keep = runtime_closure(lock, roots)
    drop = removable(lock, keep)
    for path in drop:
        full = os.path.join(api_dir, *path.split("/"))
        if os.path.islink(full):
            os.unlink(full)
        elif os.path.isdir(full):
            shutil.rmtree(full)
    node_modules = os.path.join(api_dir, "node_modules")
    _drop_dangling_links(node_modules)
    # npm's cache of the installed tree; it would still list what was removed.
    hidden = os.path.join(node_modules, ".package-lock.json")
    if os.path.isfile(hidden):
        os.remove(hidden)
    return len(drop), unresolved_imports(api_dir, node, entry_imports(api_dir))
