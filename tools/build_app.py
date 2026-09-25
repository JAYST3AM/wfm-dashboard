#!/usr/bin/env python3
r"""Build the one-click app ("WFM Trader.exe") and the release ZIP.

    python tools/build_app.py              # build dist/WFM Trader/ (exe + _internal)
    python tools/build_app.py --bundle     # ... and dist/WFM-Trader-<date>.zip (release asset)
    python tools/build_app.py --selftest   # toolchain + bundle rules only, no build

How it works: tools/wfm_app.py is frozen with PyInstaller into an exe that doubles as the
Python runtime for its folder (see that file's docstring). The app's own .py files stay REAL
files next to the exe, so scripts/ keeps its normal layout, `data/` stays a normal folder and
any future `python scripts/x.py` in the docs still lines up with
`"WFM Trader.exe" scripts/x.py`.

The ZIP is what a user downloads: it must never contain personal data. bundle_plan() is the
single source of truth for what ships and what is skipped; tests assert the exclusions
(secrets.json, data/*, tests/, static/collection_log.json, static/hi).
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Directories that never ship: dev-only, personal, or build output.
EXCLUDE_DIRS = {'.git', '.github', '.hermes', 'tests', 'assets', 'dist', 'build', '__pycache__'}
# Whole paths (file or dir, relative to the repo) that never ship.
EXCLUDE_PATHS = {
    'secrets.json',                       # the user's warframe.market login
    'scripts/trader',                     # the private trader engines: never in a release
    'static/collection_log.json',         # regenerated from the local save (personal progress)
    'static/hi',                          # locally generated hi-res set
    'tools/preview_frames',               # dev-only preview frames
}
EXCLUDE_SUFFIXES = ('.pyc', '.pyo')
# Modules the app never needs inside the exe (dev-only or heavyweight).
EXCLUDE_MODULES = ('PIL', 'numpy', 'pytest', 'tkinter', 'matplotlib', 'setuptools', 'pip',
                   'PyInstaller')      # the builder itself: dev-only, and it is big
# data/ ships EMPTY except for the placeholder.
DATA_KEEP = {'.gitkeep'}


def app_imports(root=REPO):
    """Every module the app's own .py files import, dotted and deduplicated.

    The exe IS the interpreter for those files, so anything they import has to be baked in -
    PyInstaller only sees what its entry point imports, and the entry point is just the
    launcher. Deriving the list from the source means a new `import x` in any script is picked
    up by the next build with no list to maintain.
    """
    import ast
    import importlib.util

    local = set()
    for base, dirs, names in os.walk(root):
        rel_base = os.path.relpath(base, root)
        rel_base = '' if rel_base == '.' else rel_base
        dirs[:] = [d for d in dirs
                   if d not in EXCLUDE_DIRS and not d.startswith('.')
                   and ((os.path.join(rel_base, d) if rel_base else d).replace(os.sep, '/')
                        not in EXCLUDE_PATHS)]
        for n in names:
            if n.endswith('.py'):
                local.add(os.path.splitext(n)[0])

    found = set()
    for base, dirs, names in os.walk(root):
        rel_base = os.path.relpath(base, root)
        rel_base = '' if rel_base == '.' else rel_base
        dirs[:] = [d for d in dirs
                   if d not in EXCLUDE_DIRS and not d.startswith('.')
                   and ((os.path.join(rel_base, d) if rel_base else d).replace(os.sep, '/')
                        not in EXCLUDE_PATHS)]
        for n in sorted(names):
            if not n.endswith('.py'):
                continue
            try:
                with open(os.path.join(base, n), encoding='utf-8') as fh:
                    tree = ast.parse(fh.read())
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        found.add(a.name)
                elif isinstance(node, ast.ImportFrom):
                    if not node.level and node.module:      # level>0 = our own package
                        found.add(node.module)

    keep = []
    for name in sorted(found):
        top = name.split('.')[0]
        if top in local or top in EXCLUDE_MODULES or name == '__future__':
            continue
        try:
            if importlib.util.find_spec(name) is None:
                continue
        except (ImportError, ValueError, AttributeError):
            continue
        keep.append(name)
    return keep

START_HERE = """WFM Trader - how to start
=========================

1. Install AlecaFrame (https://alecaframe.com) and open Warframe once so it
   reads your inventory. This app reads that local data; it needs nothing else.

2. Double-click "WFM Trader.exe" in this folder.

   First start: it builds your data (prices, statistics, rank lanes, every
   page). Takes 20-40 minutes and is resumable - you can close the window and
   start it again later to continue.

   After that: it starts the dashboard and opens it in your browser
   (http://127.0.0.1:8787). Keep the window open while you use the dashboard;
   close it to stop.

Nothing to install, no Python needed - the exe brings its own.

Optional (Windows): make it start with your PC - right-click WFM Trader.exe ->
Send to -> Desktop (create shortcut), then put that shortcut in
Win+R -> shell:startup
"""


# ---------------------------------------------------------------------------- what ships
def git_tracked(root=REPO):
    """Relative paths git tracks (forward slashes), or None when git is unavailable.

    The release ships *tracked* files only: anything personal or private that lives in the
    working tree but is deliberately out of the repository (the trader engines, the hi-res set,
    a secrets.json, the local collection log) can then never leak into a download.
    """
    try:
        out = subprocess.run(['git', '-C', root, 'ls-files'], capture_output=True,
                             text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return {ln.strip().replace('\\', '/') for ln in out.stdout.splitlines() if ln.strip()}


def bundle_plan(root=REPO, tracked='auto'):
    """(files, skipped): exactly what the release ZIP puts inside the app folder.

    tracked='auto' also drops anything git does not track (personal/private/local files),
    so the download can only ever contain repository content. Pass tracked=False to see the
    static rule layer alone (used by --selftest and the tests, which may run before the build
    tools themselves are committed).
    """
    root = os.path.abspath(root)
    files, skipped = [], []
    for base, dirs, names in os.walk(root):
        rel_base = os.path.relpath(base, root)
        rel_base = '' if rel_base == '.' else rel_base
        keep = []
        for d in sorted(dirs):
            rel = (os.path.join(rel_base, d) if rel_base else d).replace(os.sep, '/')
            if d in EXCLUDE_DIRS or d.startswith('.') or rel in EXCLUDE_PATHS:
                skipped.append(rel + '/')
            else:
                keep.append(d)
        dirs[:] = keep
        for n in sorted(names):
            rel_u = (os.path.join(rel_base, n) if rel_base else n).replace(os.sep, '/')
            if rel_u in EXCLUDE_PATHS or n in EXCLUDE_PATHS:
                skipped.append(rel_u)
                continue
            if n.endswith(EXCLUDE_SUFFIXES) or (n.startswith('.') and n != '.gitkeep'):
                skipped.append(rel_u)
                continue
            if rel_u.startswith('data/') and n not in DATA_KEEP:
                skipped.append(rel_u)
                continue
            files.append(rel_u)
    tracked_set = git_tracked(root) if tracked else None
    if tracked_set is not None:
        keep, dropped = [], []
        for rel in files:
            (keep if rel in tracked_set else dropped).append(rel)
        if dropped:
            print('not shipping %d untracked file(s), e.g. %s'
                  % (len(dropped), ', '.join(sorted(dropped)[:4])))
        skipped += ['%s (untracked)' % d for d in dropped]
        files = keep
    return files, skipped


def plan_bytes(root=REPO):
    total = 0
    for rel in bundle_plan(root)[0]:
        try:
            total += os.path.getsize(os.path.join(root, rel))
        except OSError:
            pass
    return total


# ---------------------------------------------------------------------------- build
def build(root=REPO, dist=None, work=None):
    """Freeze tools/wfm_app.py into "<dist>/WFM Trader/WFM Trader.exe" (+ _internal)."""
    try:
        import PyInstaller.__main__ as pyi
    except ImportError:
        print('PyInstaller is not installed. Install it with:  pip install pyinstaller')
        return None
    dist = dist or os.path.join(root, 'dist')
    work = work or os.path.join(root, 'build')
    icon = os.path.join(root, 'static', 'favicon.ico')
    args = ['--noconfirm', '--clean', '--onedir', '--console',
            '--name', 'WFM Trader',
            '--distpath', dist, '--workpath', work, '--specpath', work,
            '--collect-all', 'cryptography',          # dispatched scripts import it
            '--paths', root,
            os.path.join(root, 'tools', 'wfm_app.py')]
    hidden = app_imports(root)
    for name in hidden:
        args += ['--hidden-import', name]
    for name in EXCLUDE_MODULES:
        args += ['--exclude-module', name]
    print('baking %d app imports into the runtime (e.g. %s)'
          % (len(hidden), ', '.join(hidden[:6])))
    if os.path.exists(icon):
        args += ['--icon', icon]
    print('building: %s' % ' '.join(args[:8]) + ' ...')
    pyi.run(args)
    exe_dir = os.path.join(dist, 'WFM Trader')
    exe = os.path.join(exe_dir, 'WFM Trader.exe')
    if not os.path.exists(exe):
        print('build failed - no exe at %s' % exe)
        return None
    print('built   : %s (%.1f MB)' % (exe, os.path.getsize(exe) / 1048576.0))
    return exe_dir


def bundle(root=REPO, stamp=None):
    """Stage the exe + the app files and zip them into dist/WFM-Trader-<stamp>.zip."""
    exe_dir = os.path.join(root, 'dist', 'WFM Trader')
    if not os.path.exists(os.path.join(exe_dir, 'WFM Trader.exe')):
        print('no build yet - run: python tools/build_app.py')
        return None
    stamp = stamp or time.strftime('%Y-%m-%d')
    stage_root = os.path.join(root, 'dist', 'stage')
    stage = os.path.join(stage_root, 'WFM Trader')
    shutil.rmtree(stage_root, ignore_errors=True)
    os.makedirs(stage, exist_ok=True)

    # 1. the frozen runtime (exe + _internal)
    for name in sorted(os.listdir(exe_dir)):
        src = os.path.join(exe_dir, name)
        dst = os.path.join(stage, name)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)

    # 2. the app's own files, minus anything personal
    files, _skipped = bundle_plan(root)
    for rel in files:
        src = os.path.join(root, rel)
        dst = os.path.join(stage, rel.replace('/', os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    os.makedirs(os.path.join(stage, 'data'), exist_ok=True)
    with open(os.path.join(stage, 'START HERE.txt'), 'w', encoding='utf-8') as fh:
        fh.write(START_HERE)

    # 3. zip ("WFM Trader/..." inside, so extracting gives one clean folder)
    zip_path = os.path.join(root, 'dist', 'WFM-Trader-%s.zip' % stamp)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for base, _dirs, names in os.walk(stage):
            for name in sorted(names):
                full = os.path.join(base, name)
                zf.write(full, os.path.join('WFM Trader', os.path.relpath(full, stage)))
    print('zip     : %s (%.1f MB, %d app files + the runtime)'
          % (zip_path, os.path.getsize(zip_path) / 1048576.0, len(files)))
    return zip_path


# ---------------------------------------------------------------------------- selftest
def selftest(root=REPO):
    ok = True

    def chk(what, got, want=True):
        nonlocal ok
        good = got == want
        ok = ok and good
        print('%-54s %s' % (what, 'ok' if good else 'FAIL (got %r, want %r)' % (got, want)))

    try:
        import PyInstaller
        have_pyi, version = True, PyInstaller.__version__
    except ImportError:
        have_pyi, version = False, '-'
    print('PyInstaller: %s %s' % (version if have_pyi else 'NOT INSTALLED (pip install pyinstaller)', ''))
    chk('entry point exists', os.path.isfile(os.path.join(root, 'tools', 'wfm_app.py')))
    chk('icon exists', os.path.isfile(os.path.join(root, 'static', 'favicon.ico')))

    files, skipped = bundle_plan(root, tracked=False)
    for need in ('server.py', 'README.md', 'requirements.txt', 'setup.bat',
                 'scripts/setup.py', 'scripts/profiles.py', 'static/index.html',
                 'tools/supervise.py', 'tools/wfm_app.py', 'data/.gitkeep'):
        chk('ships %s' % need, need in files)
    for banned in ('secrets.json', 'static/collection_log.json', 'data/owned.json',
                   'data/prices.json', 'tests/test_profiles.py', 'static/hi/index.json',
                   'scripts/trader/auto.py', 'scripts/trader/lister.py'):
        chk('never ships %s' % banned, banned in files, False)
    chk('no .pyc ships', any(f.endswith('.pyc') for f in files), False)
    untracked = len(bundle_plan(root, tracked=True)[1]) - len(bundle_plan(root, tracked=False)[1])
    print('note: %d extra item(s) in this working tree are untracked and would not ship' % max(0, untracked))
    print('plan: %d files, %.1f MB' % (len(files), plan_bytes(root) / 1048576.0))
    print('')
    print('selftest:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog='build_app.py', description=__doc__.splitlines()[0])
    ap.add_argument('--bundle', action='store_true', help='also build the release ZIP')
    ap.add_argument('--selftest', action='store_true', help='checks only, no build')
    ap.add_argument('--stamp', default=None, help='date stamp for the ZIP name')
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not build():
        return 1
    if a.bundle:
        if not bundle(stamp=a.stamp):
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
