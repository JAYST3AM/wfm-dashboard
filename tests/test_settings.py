"""scripts/trader/settings.py: the guardrail settings engine (schema + validation + atomic writes).

scripts/trader/ is private (gitignored, absent from a public checkout), so the whole module
skips when the engine is not on disk; on Jay's machine it runs for real. Every test points
WFM_TRADER_SETTINGS at tmp_path, so the repo's own scripts/trader/settings.json is never
written - the last test re-hashes it to prove that.
"""
import hashlib
import importlib.util
import itertools
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRADER = os.path.join(REPO, 'scripts', 'trader')
SETTINGS_PY = os.path.join(TRADER, 'settings.py')
SHIPPED = os.path.join(TRADER, 'settings.json')
ENGINES = ('lister.py', 'watcher.py', 'detector.py')

RANGES = {'max_new_listings_per_day': (1, 20, 20), 'undercut_platinum': (1, 5, 1),
          'min_price_platinum': (3, 100, 3), 'min_price_pct_of_median': (50, 100, 60),
          'buy_budget_cap_platinum': (0, 5000, 300), 'max_active_listings': (1, 100, 40),
          'poll_seconds': (15, 1800, 90)}
ALIASES = {'list_cap': 'max_new_listings_per_day', 'undercut_p': 'undercut_platinum',
           'min_price_p': 'min_price_platinum', 'median_floor_pct': 'min_price_pct_of_median',
           'buy_budget_p': 'buy_budget_cap_platinum'}

pytestmark = pytest.mark.skipif(
    not os.path.exists(SETTINGS_PY),
    reason='scripts/trader is private (gitignored) - not present in this checkout')

_seq = itertools.count()


def sha(p):
    try:
        return hashlib.sha256(open(p, 'rb').read()).hexdigest()
    except OSError:
        return None


REAL_HASH = sha(SHIPPED)          # captured at import; checked again by the last test


def load_engine(monkeypatch, settings_path):
    """Import scripts/trader/settings.py fresh, with its path redirected into tmp_path."""
    monkeypatch.setenv('WFM_TRADER_SETTINGS', str(settings_path))
    name = 'wfm_trader_settings_%d' % next(_seq)
    spec = importlib.util.spec_from_file_location(name, SETTINGS_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def read_json(p):
    with open(str(p), encoding='utf-8') as fh:
        return json.load(fh)


def write_text(p, text):
    with open(str(p), 'w', encoding='utf-8') as fh:
        fh.write(text)


def cli(settings_path, *args):
    """Run the real CLI in a subprocess with the settings path overridden."""
    env = dict(os.environ, WFM_TRADER_SETTINGS=str(settings_path))
    return subprocess.run([sys.executable, SETTINGS_PY, *args],
                          capture_output=True, text=True, env=env, cwd=REPO)


@pytest.fixture
def engine(tmp_path, monkeypatch):
    """The engine module; its settings file does not exist yet (creation path)."""
    return load_engine(monkeypatch, tmp_path / 'settings.json')


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    """(module, path) with a copy of the shipped settings.json at the tmp path."""
    p = tmp_path / 'settings.json'
    shutil.copyfile(SHIPPED, p)
    return load_engine(monkeypatch, p), p


# ------------------------------------------------------------------ schema

def test_schema_row_contract_and_ranges(engine):
    rows = engine.schema()
    assert [r['key'] for r in rows] == engine.SPEC_KEYS
    assert all({'key', 'type', 'min', 'max', 'default', 'help'} <= set(r) for r in rows)
    assert {r['type'] for r in rows} == {'min/max', 'bool'}
    assert json.loads(json.dumps(rows))[0]['key'] == 'dry_run'      # UI-renderable
    by_key = {r['key']: r for r in rows}
    for key, (lo, hi, default) in RANGES.items():
        assert (by_key[key]['min'], by_key[key]['max'], by_key[key]['default']) == (lo, hi, default)
    assert by_key['dry_run']['type'] == 'bool'
    assert (by_key['dry_run']['min'], by_key['dry_run']['max']) == (None, None)
    assert by_key['dry_run']['default'] is True and by_key['dry_run']['locked'] is True
    assert not any(r['locked'] for r in rows if r['key'] != 'dry_run')


def test_schema_matches_the_shipped_file(engine):
    shipped = read_json(SHIPPED)
    rows = {r['key']: r for r in engine.schema()}
    assert list(shipped) == [r['key'] for r in engine.schema()]     # no key renamed or dropped
    assert all(shipped[k] == rows[k]['default'] for k in shipped)   # defaults == current values
    assert engine.audit(shipped) == []


def test_schema_cli_is_json(engine, tmp_path):
    r = cli(tmp_path / 'never-used.json', '--schema')
    assert r.returncode == 0
    assert json.loads(r.stdout) == engine.schema()


# -------------------------------------------------------------- validation

def test_bounds_are_inclusive_and_outside_is_refused(engine):
    for key, (lo, hi, _) in RANGES.items():
        for value in (lo, hi):
            ok, got, err = engine.validate(key, str(value))
            assert ok and got == value and err is None, (key, value)
        for value in (lo - 1, hi + 1):
            ok, got, err = engine.validate(key, str(value))
            assert not ok and got is None and f'{lo}..{hi}' in err, (key, value, err)


def test_non_numeric_and_boolean_values_are_refused(engine):
    for raw in ('abc', '', '1.5', 'nan', 'inf', True, False, None, '12p'):
        ok, _, err = engine.validate('min_price_platinum', raw)
        assert not ok and 'whole number' in err, raw
    ok, got, _ = engine.validate('min_price_platinum', '3.0')        # integral float text ok
    assert ok and got == 3 and isinstance(got, int)


def test_bool_toggle_coercion(engine):
    for raw in ('true', 'TRUE', 'on', '1', 'yes', True):
        assert engine.validate('dry_run', raw) == (True, True, None), raw
    for raw in ('false', 'FALSE', 'off', '0', 'no', False):
        assert engine.validate('dry_run', raw) == (True, False, None), raw
    for raw in ('maybe', '', '2', 1.5):
        ok, _, err = engine.validate('dry_run', raw)
        assert not ok and 'true/false' in err, raw
    for key in ('min_price_platinum', 'poll_seconds'):
        assert not engine.validate(key, 'true')[0]


def test_aliases_resolve_without_creating_new_keys(engine):
    for alias, real in ALIASES.items():
        assert engine.spec_for(alias)['key'] == real
    assert engine.spec_for('nope') is None


def test_set_refuses_unknown_keys(engine, tmp_path):
    res = engine.apply_changes([('list_cap_pct', '5')], p=tmp_path / 'settings.json')
    assert not res['ok'] and res['code'] == 2 and 'max_new_listings_per_day' in res['error']
    assert not os.path.exists(tmp_path / 'settings.json')


# ------------------------------------------------------- writes are atomic

def test_set_creates_missing_file_with_defaults_and_writes_atomically(engine, tmp_path):
    p = tmp_path / 'settings.json'
    res = engine.apply_changes([('list_cap', '12'), ('undercut_p', '2')], p=p)
    assert res['ok'] and res['code'] == 0 and res['created']
    doc = read_json(p)
    assert list(doc) == engine.SPEC_KEYS                             # shipped order preserved
    assert doc['max_new_listings_per_day'] == 12 and doc['undercut_platinum'] == 2
    assert 'list_cap' not in doc                                     # alias never becomes a key
    assert all(doc[k] == engine.DEFAULTS[k] for k in doc if k not in
               ('max_new_listings_per_day', 'undercut_platinum'))
    raw = open(str(p), 'rb').read()
    assert raw.endswith(b'}\n') and b'\r' not in raw                # file's own style: LF, indent 2
    assert os.listdir(str(tmp_path)) == ['settings.json']           # no tmp leftovers


def test_rewriting_an_unchanged_doc_is_byte_idempotent(seeded):
    engine, p = seeded
    engine.apply_changes([('list_cap', '17')], p=p)
    once = sha(p)
    engine.apply_changes([('list_cap', '17')], p=p)                 # same value again
    assert sha(p) == once
    assert b'\r' not in open(str(p), 'rb').read()


def test_a_crlf_file_keeps_its_line_endings(engine, tmp_path):
    p = tmp_path / 'settings.json'
    write_text(p, '{\r\n  "dry_run": true,\r\n  "poll_seconds": 90\r\n}\r\n')
    res = engine.apply_changes([('poll_seconds', '120')], p=p)
    raw = open(str(p), 'rb').read()
    assert res['ok'] and b'"poll_seconds": 120' in raw
    assert raw.count(b'\r\n') == raw.count(b'\n') > 5               # never reformatted to LF


def test_writes_keep_unknown_keys_and_file_order(seeded):
    engine, p = seeded
    doc = read_json(p)
    doc['future_knob'] = 7
    json.dump(doc, open(str(p), 'w', encoding='utf-8'), indent=2)
    res = engine.apply_changes([('poll_seconds', '120')], p=p)
    assert res['ok'] and res['preserved'] == ['future_knob']
    after = read_json(p)
    assert after['future_knob'] == 7
    assert list(after) == list(doc) == engine.SPEC_KEYS + ['future_knob']


def test_refused_writes_leave_the_file_byte_identical(seeded):
    engine, p = seeded
    before = sha(p)
    for pairs in ([('min_price_platinum', '2')], [('dry_run', 'false')],
                  [('list_cap', '15'), ('undercut_platinum', '9')], [('nonsense', '1')]):
        res = engine.apply_changes(pairs, p=p)
        assert not res['ok'] and sha(p) == before, pairs


def test_out_of_range_writes_refused_with_the_range_in_the_message(seeded):
    engine, p = seeded
    res = engine.apply_changes([('list_cap', '21')], p=p)
    assert res['code'] == 2 and '1..20' in res['error']


# ----------------------------------------------------------- dry_run lock

def test_dry_run_false_is_locked_until_jay_approves(seeded):
    engine, p = seeded
    before = sha(p)
    for raw in ('false', '0', 'no', 'off', 'FALSE'):
        res = engine.apply_changes([('dry_run', raw)], p=p)
        assert not res['ok'] and res['code'] == 3, raw
        assert 'locked' in res['error'] and 'approval' in res['error']
        assert sha(p) == before


def test_cli_dry_run_false_refused_with_exit_3(seeded):
    engine, p = seeded
    before = sha(p)
    r = cli(p, '--set', 'dry_run=false')
    assert r.returncode == 3
    assert 'locked' in r.stderr and sha(p) == before
    r2 = cli(p, '--set', 'list_cap=5', '--set', 'dry_run=false')
    assert r2.returncode == 3 and sha(p) == before                   # batch refused wholesale
    assert read_json(p)['dry_run'] is True and read_json(p)['max_new_listings_per_day'] == 20
    r3 = cli(p, '--set', 'dry_run=true', '--set', 'list_cap=5')      # true is allowed
    assert r3.returncode == 0 and read_json(p)['max_new_listings_per_day'] == 5


def test_dry_run_true_is_accepted(seeded):
    engine, p = seeded
    res = engine.apply_changes([('dry_run', 'true')], p=p)
    assert res['ok'] and res['changes']['dry_run'] == {'from': True, 'to': True, 'unchanged': True}


# -------------------------------------------------------------- CLI paths

def test_cli_set_then_show_roundtrip(seeded):
    engine, p = seeded
    r = cli(p, '--set', 'median_floor_pct=55', '--set', 'buy_budget_p=0', '--show')
    assert r.returncode == 0 and 'min_price_pct_of_median = 55 (was 60)' in r.stdout
    shown = json.loads(r.stdout[r.stdout.index('{'):])
    assert shown['min_price_pct_of_median'] == 55 and shown['buy_budget_cap_platinum'] == 0
    assert set(shown) == set(engine.SPEC_KEYS)


def test_cli_rejects_out_of_range_and_bad_syntax(seeded):
    engine, p = seeded
    before = sha(p)
    assert cli(p, '--set', 'undercut_p=9').returncode == 2
    assert cli(p, '--set', 'noequals').returncode == 2
    assert cli(p, '--set', 'future_knob=1').returncode == 2
    assert sha(p) == before
    assert list(read_json(p)) == engine.SPEC_KEYS


def test_show_and_schema_never_write(seeded):
    engine, p = seeded
    before = sha(p)
    assert json.loads(cli(p, '--show').stdout) == read_json(p)
    assert cli(p, '--schema').returncode == 0
    assert sha(p) == before


def test_corrupt_file_is_never_overwritten(engine, tmp_path):
    p = tmp_path / 'settings.json'
    write_text(p, '{"dry_run": true, "max_new_listings_per_day": 20,')
    before = sha(p)
    res = engine.apply_changes([('poll_seconds', '120')], p=p)
    assert not res['ok'] and res['code'] == 2 and 'not valid JSON' in res['error']
    assert sha(p) == before
    r = cli(p, '--set', 'poll_seconds=120')
    assert r.returncode == 2 and sha(p) == before
    r2 = cli(p, '--show')
    assert r2.returncode == 2 and 'not valid JSON' in r2.stderr and sha(p) == before


def test_selftest_cli_passes_offline(seeded):
    engine, p = seeded
    r = cli(p, '--selftest')
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'selftest: all' in r.stdout and 'checks passed' in r.stdout
    assert sha(p) is not None                                        # seed file still there


# ------------------------------------------------------- cross-engine guard

def test_every_key_the_engines_read_is_in_the_schema(engine):
    pattern = re.compile(r"\bst\s*(?:\[\s*['\"](\w+)['\"]\s*\]|\.\s*get\s*\(\s*['\"](\w+)['\"])")
    read_keys = set()
    for name in ENGINES:
        source = open(os.path.join(TRADER, name), encoding='utf-8').read()
        read_keys.update(m.group(1) or m.group(2) for m in pattern.finditer(source))
    assert {'dry_run', 'max_new_listings_per_day', 'undercut_platinum', 'min_price_platinum',
            'min_price_pct_of_median', 'poll_seconds'} <= read_keys    # the scan really found them
    assert read_keys <= set(engine.SPEC_KEYS), sorted(read_keys - set(engine.SPEC_KEYS))
    assert set(read_json(SHIPPED)) == set(engine.SPEC_KEYS)


def test_the_real_settings_file_was_never_written():
    assert sha(SHIPPED) == REAL_HASH
