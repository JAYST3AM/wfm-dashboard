"""Shared helpers for the wfm-dashboard public test-suite (stdlib + pytest only).

The public repo ships NO data/ folder (CI checks out a clean tree), so every test
builds its own fixtures under tmp_path and points the script's path globals at them.

Rules honoured here:
  * never import scripts/trader/* (private, gitignored - not on GitHub);
  * never touch the network (scripts that fetch at import are tested via AST-extracted
    pure helpers or a subprocess fail-fast run - see test_relic_ev.py);
  * never read or write the repo's real data/ directory;
  * load scripts by file path (scripts/ has no __init__.py, and a fresh module object
    per test keeps monkeypatched globals from leaking between tests).
"""
import importlib.util
import itertools
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, 'scripts')

_seq = itertools.count()


def load_script(name, monkeypatch=None, env=None):
    """Import scripts/<name>.py (or the repo-root server.py) as a fresh module object.

    ``env`` is applied BEFORE the module is exec'd, so module-level os.environ reads
    (price_history's PRICE_HISTORY_PATH / PRICE_MOVERS_PATH) are exercised for real.
    """
    if env:
        assert monkeypatch is not None, 'load_script(env=...) needs the monkeypatch fixture'
        for key, value in env.items():
            monkeypatch.setenv(key, str(value))
    candidates = [os.path.join(SCRIPTS, name + '.py'), os.path.join(REPO, name + '.py')]
    path = next((p for p in candidates if os.path.exists(p)), candidates[0])
    modname = 'wfm_%s_%d' % (name, next(_seq))
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(modname, None)
        raise
    return mod


def write_json(path, obj):
    """Dump obj as JSON, creating parent dirs; returns the path as a string."""
    path = str(path)
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, indent=1)
    return path


def read_json(path):
    with open(str(path), encoding='utf-8') as fh:
        return json.load(fh)


@pytest.fixture
def data_dir(tmp_path):
    """Throwaway stand-in for the repo's data/ directory."""
    d = tmp_path / 'data'
    d.mkdir()
    return d


@pytest.fixture
def server_mod(tmp_path, monkeypatch, data_dir):
    """server.py imported without ever starting the HTTP server.

    DATA/ROOT are redirected into tmp_path so no repo data is read and no repo file
    is written; the handler class is never instantiated (no socket is opened).
    """
    mod = load_script('server', monkeypatch=monkeypatch, env={'WFM_PORT': '0'})
    monkeypatch.setattr(mod, 'DATA', str(data_dir))
    monkeypatch.setattr(mod, 'ROOT', str(tmp_path))
    return mod
