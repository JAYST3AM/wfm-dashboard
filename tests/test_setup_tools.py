"""Onboarding surface: scripts/setup.py, setup.bat / refresh.bat / supervise.bat,
tools/supervise.py and the first-run banner.

A fresh clone depends on exactly these, so a rename, a lost step or a batch-file
mistake should fail here before a new user ever sees it.
"""
import importlib.util
import os
import sys
import threading
import http.server

from conftest import REPO, SCRIPTS, load_script


def _load_tool(name):
    path = os.path.join(REPO, 'tools', name + '.py')
    modname = 'wfm_tool_%s' % name
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- setup.py steps

def test_setup_py_steps_point_at_real_scripts():
    mod = load_script('setup')
    steps = list(mod.CORE_STEPS) + list(mod.PAGE_STEPS)
    assert steps, 'setup.py has no steps'
    for step in steps:
        script = step[0]
        assert os.path.exists(os.path.join(SCRIPTS, script)), \
            'setup.py references a missing script: %s' % script


def test_setup_py_covers_the_core_pipeline_and_the_page_data():
    mod = load_script('setup')
    core = [s[0] for s in mod.CORE_STEPS]
    pages = [s[0] for s in mod.PAGE_STEPS]
    # the required pipeline, in order
    for name in ('refresh.py', 'fetch_prices.py', 'fetch_stats.py', 'fetch_lanes.py',
                 'report.py', 'sell_advisor.py', 'snapshot_plat.py'):
        assert name in core, 'missing core step: %s' % name
    # every page that would otherwise sit empty on a fresh clone
    for name in ('collection_log.py', 'mod_cards.py', 'deal_scanner.py', 'trends.py',
                 'rivens.py', 'sets.py', 'ducats.py', 'relic_ev.py', 'craft.py',
                 'nudges.py', 'wishlist.py', 'invdiff.py', 'price_history.py',
                 'baro.py', 'meta_watcher.py', 'sell_timing.py', 'session_stats.py'):
        assert name in pages, 'missing page step: %s' % name


def test_setup_py_checks_alecaframe_and_the_dependency_first():
    src = open(os.path.join(SCRIPTS, 'setup.py'), encoding='utf-8').read()
    assert 'lastData.dat' in src                      # AlecaFrame cache check
    assert 'import cryptography' in src               # the one dependency, checked
    assert 'alecaframe.com' in src                    # tells the user where to get it
    assert 'start.bat' in src and 'refresh.bat' in src  # points at the entry points


# ---------------------------------------------------------------- the .bat files

def _bat(name):
    path = os.path.join(REPO, name)
    assert os.path.exists(path), 'missing %s' % name
    raw = open(path, 'rb').read()
    assert b'\r\n' in raw, '%s must use CRLF line endings' % name
    return raw.decode('ascii')


def test_setup_bat_is_a_one_click_installer():
    bat = _bat('setup.bat')
    assert 'py -3 --version' in bat          # prefers the py launcher
    assert 'python --version' in bat         # falls back to python on PATH
    assert 'requirements.txt' in bat         # installs the dependency
    assert r'scripts\setup.py' in bat        # runs the real setup
    assert '== "check"' not in bat and '~1"=="check"' in bat  # check mode fence
    assert 'pause' in bat                    # never closes before you can read it
    assert '8787' in bat                     # starts the dashboard at the end


def test_refresh_bat_reprices_and_rebuilds():
    bat = _bat('refresh.bat')
    for needle in (r'scripts\fetch_prices.py', r'scripts\fetch_stats.py',
                   r'scripts\fetch_lanes.py', r'scripts\report.py',
                   r'scripts\sell_advisor.py --write', r'scripts\snapshot_plat.py'):
        assert needle in bat, 'refresh.bat is missing: %s' % needle
    assert 'pause' in bat


def test_supervise_bat_runs_the_supervisor():
    bat = _bat('supervise.bat')
    assert r'tools\supervise.py' in bat
    assert 'shell:startup' in bat            # tells the user how to autostart
    assert 'pause' in bat


# ---------------------------------------------------------------- tools/supervise.py

def test_supervise_ping_sees_a_live_server_and_a_dead_port():
    mod = _load_tool('supervise')
    srv = http.server.HTTPServer(('127.0.0.1', 0), http.server.SimpleHTTPRequestHandler)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        assert mod.ping('127.0.0.1', port, timeout=3) is True
    finally:
        srv.shutdown()
        srv.server_close()
    assert mod.ping('127.0.0.1', port, timeout=2) is False


def test_supervise_cfg_port_reads_config_and_tolerates_junk(tmp_path):
    mod = _load_tool('supervise')
    import json as _json
    good = tmp_path / 'config.json'
    good.write_text(_json.dumps({'port': 9123}), encoding='utf-8')
    assert mod.cfg_port(str(good)) == 9123
    assert mod.cfg_port(str(tmp_path / 'nope.json')) is None
    broken = tmp_path / 'broken.json'
    broken.write_text('{not json', encoding='utf-8')
    assert mod.cfg_port(str(broken)) is None


def test_supervise_selftest_passes_offline():
    mod = _load_tool('supervise')
    assert mod.selftest() == 0


def test_supervise_never_starts_a_second_server_when_the_port_answers():
    src = open(os.path.join(REPO, 'tools', 'supervise.py'), encoding='utf-8').read()
    assert 'watches instead of starting a second copy' in src or \
           'watching it, not starting a second copy' in src


# ---------------------------------------------------------------- first-run banner

def test_first_run_banner_exists_and_is_guarded():
    html = open(os.path.join(REPO, 'static', 'index.html'), encoding='utf-8').read()
    assert 'id="firstRun"' in html
    js = open(os.path.join(REPO, 'static', 'app.js'), encoding='utf-8').read()
    assert 'function renderFirstRun' in js
    assert "getElementById('firstRun')" in js
    # the guard: only when setup has not produced data yet
    assert 'lastdata_mtime' in js
    # the copy points at the entry point and the prerequisite
    assert 'setup.bat' in js and 'alecaframe.com' in js
    # load() must actually call it
    assert 'renderFirstRun();' in js


# ---------------------------------------------------------------- personal data stays out

def test_generated_collection_log_is_not_tracked():
    """static/collection_log.json is regenerated from the local save: committing it
    would publish one user's collection progress and show it to every other user."""
    import subprocess
    if not os.path.isdir(os.path.join(REPO, '.git')):
        import pytest
        pytest.skip('not a git checkout')
    out = subprocess.run(['git', 'ls-files', '--error-unmatch', 'static/collection_log.json'],
                         cwd=REPO, capture_output=True, text=True)
    assert out.returncode != 0, 'static/collection_log.json must not be tracked'
    ignore = open(os.path.join(REPO, '.gitignore'), encoding='utf-8').read()
    assert 'static/collection_log.json' in ignore

