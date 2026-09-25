"""The one-click app: launcher/shim contracts + the release-ZIP bundle rules.

Covers tools/wfm_app.py (frozen-exe entry point that doubles as the Python runtime for its
folder) and tools/build_app.py (PyInstaller build + what the release ZIP may contain).
"""
import importlib.util
import os
import subprocess
import sys
import tempfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tool(name):
    path = os.path.join(REPO, 'tools', name + '.py')
    spec = importlib.util.spec_from_file_location('tool_' + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope='module')
def app():
    return load_tool('wfm_app')


@pytest.fixture(scope='module')
def builder():
    return load_tool('build_app')


# --------------------------------------------------------------------------- launcher
def test_layout_points_at_the_repo(app):
    assert os.path.isdir(app.app_root())
    assert os.path.isfile(os.path.join(app.app_root(), 'server.py'))
    assert app.scripts_dir() == os.path.join(app.app_root(), 'scripts')
    assert app.data_dir() == os.path.join(app.app_root(), 'data')


def test_run_script_passes_argv_and_returns_zero(app):
    with tempfile.TemporaryDirectory() as td:
        probe = os.path.join(td, 'probe.py')
        out = os.path.join(td, 'out.txt')
        with open(probe, 'w', encoding='utf-8') as fh:
            fh.write('import json, os, sys\n'
                     "open(os.environ['PROBE_OUT'], 'w', encoding='utf-8').write(json.dumps(sys.argv[1:]))\n")
        os.environ['PROBE_OUT'] = out
        assert app.run_script(probe, ['--flag', '7']) == 0
        assert open(out, encoding='utf-8').read() == '["--flag", "7"]'
        os.environ.pop('PROBE_OUT', None)


def test_run_script_honours_exit_codes(app):
    with tempfile.TemporaryDirectory() as td:
        probe = os.path.join(td, 'exiter.py')
        with open(probe, 'w', encoding='utf-8') as fh:
            fh.write('import sys\nsys.exit(3)\n')
        assert app.run_script(probe) == 3


def test_run_script_missing_file_is_two(app):
    assert app.run_script(os.path.join(tempfile.gettempdir(), 'definitely-not-here-9x.py')) == 2


def test_dispatch_routes_python_style_calls(app):
    assert app.dispatch(['-c', 'raise SystemExit(5)']) == 5
    assert app.dispatch(['-c', 'pass']) == 0
    assert app.dispatch([] if False else ['-m', 'nonexistent_module_zzz']) in (1, 2)


def test_shim_runs_a_real_script_end_to_end():
    """`exe scripts/cli.py status` must behave exactly like `python scripts/cli.py status`."""
    script = os.path.join(REPO, 'scripts', 'cli.py')
    if not os.path.isfile(script):
        pytest.skip('scripts/cli.py is not in this checkout')
    shim = subprocess.run([sys.executable, os.path.join(REPO, 'tools', 'wfm_app.py'),
                           script, 'status'],
                          capture_output=True, text=True, timeout=120, cwd=REPO)
    plain = subprocess.run([sys.executable, script, 'status'],
                           capture_output=True, text=True, timeout=120, cwd=REPO)
    assert shim.returncode == plain.returncode
    assert shim.stdout.strip() != ''


def test_app_mode_without_alecaframe_explains_itself(app, monkeypatch, tmp_path):
    monkeypatch.setenv('WFM_ALECA_DIR', str(tmp_path / 'no-alecaframe-here'))
    monkeypatch.setenv('WFM_NO_MSGBOX', '1')      # a modal box would hang a headless run

    class A:
        serve_only = False
        no_browser = True
        port = None
    assert app.app(A()) == 1


def test_selftest_passes(app):
    assert app.selftest() == 0


def test_serve_only_skips_the_alecaframe_gate(app, monkeypatch):
    """--serve-only must not look at AlecaFrame at all (it would block tests/CI)."""
    monkeypatch.setenv('WFM_ALECA_DIR', str('Z:/nowhere'))
    calls = {}
    monkeypatch.setattr(app, 'serve', lambda **kw: (calls.setdefault('served', kw), 0)[1])
    monkeypatch.setattr(app, 'data_ready', lambda: False)

    class A:
        serve_only = True
        no_browser = True
        port = 8799
    assert app.app(A()) == 0
    assert calls['served']['port'] == 8799


# --------------------------------------------------------------------------- bundle rules
def test_bundle_ships_a_runnable_app(builder):
    files, _ = builder.bundle_plan(tracked=False)
    for need in ('server.py', 'README.md', 'requirements.txt',
                 'setup.bat', 'start.bat', 'stop.bat',
                 'scripts/setup.py', 'scripts/refresh.py', 'scripts/profiles.py',
                 'static/index.html', 'static/app.js', 'static/settings.html',
                 'tools/supervise.py', 'tools/wfm_app.py', 'data/.gitkeep'):
        assert need in files, need


def test_bundle_tracked_filter_drops_local_files(builder, monkeypatch):
    monkeypatch.setattr(builder, 'git_tracked', lambda root=None: {'server.py', 'data/.gitkeep'})
    files, skipped = builder.bundle_plan()
    assert sorted(files) == ['data/.gitkeep', 'server.py']
    assert [s for s in skipped if s.endswith('(untracked)')]


def test_bundle_never_ships_personal_or_dev_files(builder):
    files, skipped = builder.bundle_plan(tracked=False)
    for banned in ('secrets.json', 'static/collection_log.json', 'data/owned.json',
                   'data/prices.json', 'data/backups/x.zip', 'scripts/trader/auto.py',
                   'tests/test_profiles.py', 'static/hi/index.json',
                   'tools/preview_frames/frame_001.png'):
        assert banned not in files, banned
    assert not [f for f in files if f.startswith('scripts/trader/')]
    assert not [f for f in files if f.startswith('tests/')]
    assert not [f for f in files if f.startswith('assets/')]
    assert not [f for f in files if f.endswith('.pyc')]
    assert not [f for f in files if f.startswith('tools/preview_frames/')]
    # data/ ships empty apart from the placeholder
    assert [f for f in files if f.startswith('data/')] == ['data/.gitkeep']


def test_bundle_plan_is_small_enough_to_download(builder):
    assert builder.plan_bytes() < 60 * 1048576      # app files, runtime adds ~20 MB


def test_start_here_text_covers_the_basics(builder):
    text = builder.START_HERE.lower()
    assert 'alecaframe' in text and 'double-click' in text
    assert '20-40' in text or '20 to 40' in text


def test_build_app_selftest_passes(builder):
    assert builder.selftest() == 0


def test_readme_documents_the_one_click_app():
    readme = open(os.path.join(REPO, 'README.md'), encoding='utf-8').read()
    assert 'WFM Trader.exe' in readme or 'WFM-Trader' in readme
    assert 'setup.bat' in readme        # the Python route stays documented


# --------------------------------------------------------------------------- what the exe must contain
def test_app_imports_are_derived_from_the_source(builder):
    """The frozen exe IS the interpreter for scripts/, so everything they import must be baked
    in. The list is derived from the source, not hand-maintained."""
    mods = builder.app_imports()
    assert 'cryptography' in mods            # scripts/refresh.py
    assert 'difflib' in mods                 # scripts/cli.py (the one that broke the first build)
    assert 'json' in mods and 'http.client' in mods
    # dev-only / heavyweight / self-referential: never baked in
    for banned in ('PIL', 'numpy', 'pytest', 'PyInstaller', 'tkinter'):
        assert banned not in mods, banned
    # the app's own modules are files next to it, not imports
    for local in ('cli', 'config', 'report', 'wfm_app', 'build_app'):
        assert local not in mods, local


def test_app_imports_covers_every_dotted_import_in_the_tree(builder):
    import ast
    needed = set()
    for base, dirs, names in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in ('.git', 'build', 'dist', 'tests', '__pycache__')]
        for n in names:
            if not n.endswith('.py'):
                continue
            try:
                tree = ast.parse(open(os.path.join(base, n), encoding='utf-8').read())
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and not node.level and node.module:
                    if node.module != '__future__':
                        needed.add(node.module)
    derived = set(builder.app_imports())
    missing = {m for m in needed if m.split('.')[0] not in builder.EXCLUDE_MODULES
               and not os.path.exists(os.path.join(REPO, 'scripts', m.split('.')[0] + '.py'))
               and not os.path.exists(os.path.join(REPO, 'scripts', 'trader', m.split('.')[0] + '.py'))
               and m not in derived}
    assert not missing, sorted(missing)[:8]
