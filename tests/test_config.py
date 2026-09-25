"""scripts/config.py: the dashboard config engine (schema + validation + create-once writes).

Everything runs against a tmp copy of the config (WFM_CONFIG points into tmp_path), so the
repo's own data/config.json is never written - the last test re-hashes it to prove that.
The engine is public (scripts/config.py ships), so no test skips.
"""
import hashlib
import importlib.util
import itertools
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PY = os.path.join(REPO, 'scripts', 'config.py')
TRADER_SETTINGS = os.path.join(REPO, 'scripts', 'trader', 'settings.json')
SHIPPED = os.path.join(REPO, 'data', 'config.json')

RANGES = {'port': (1024, 65535, 8787), 'auto_refresh_seconds': (15, 3600, 60),
          'theme': (0, 29, 0), 'gamenews_cache_seconds': (60, 86400, 1800),
          'deals_shown': (1, 200, 60), 'sessions_shown': (1, 60, 12)}
CHOICES = {'host': ('127.0.0.1', '0.0.0.0'), 'currency_display': ('p', 'plat', 'none')}

_seq = itertools.count()


def sha(p):
    try:
        return hashlib.sha256(open(p, 'rb').read()).hexdigest()
    except OSError:
        return None


REAL_HASH = sha(SHIPPED)          # captured at import; checked again by the last test


def load_config(monkeypatch, config_path):
    """Import scripts/config.py fresh, with WFM_CONFIG already pointing at tmp_path."""
    monkeypatch.setenv('WFM_CONFIG', str(config_path))
    name = 'wfm_config_%d' % next(_seq)
    spec = importlib.util.spec_from_file_location(name, CONFIG_PY)
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


def cli(config_path, *args):
    """Run the real CLI in a subprocess with the config path overridden."""
    env = dict(os.environ, WFM_CONFIG=str(config_path))
    return subprocess.run([sys.executable, CONFIG_PY, *args],
                          capture_output=True, text=True, env=env, cwd=REPO)


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """The engine module; its config file does not exist yet (creation path)."""
    return load_config(monkeypatch, tmp_path / 'config.json')


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    """(module, path) with a real engine-created config file (defaults + notes)."""
    p = tmp_path / 'config.json'
    mod = load_config(monkeypatch, p)
    res = mod.ensure()
    assert res['ok'] and res['created'], res
    return mod, p


# ------------------------------------------------------------------ schema

def test_schema_row_contract_and_ranges(cfg):
    rows = cfg.schema()
    assert [r['key'] for r in rows] == cfg.SPEC_KEYS
    assert all({'key', 'type', 'min', 'max', 'default', 'choices', 'step', 'help',
                'consumed_by', 'note'} <= set(r) for r in rows)
    assert {r['type'] for r in rows} == {'min/max', 'choice', 'bool'}
    assert json.loads(json.dumps(rows))[0]['key'] == 'port'          # UI-renderable
    by_key = {r['key']: r for r in rows}
    for key, (lo, hi, default) in RANGES.items():
        assert (by_key[key]['min'], by_key[key]['max'], by_key[key]['default']) == (lo, hi, default)
    for key, allowed in CHOICES.items():
        assert by_key[key]['choices'] == allowed
        assert (by_key[key]['min'], by_key[key]['max']) == (None, None)
    assert by_key['gifs']['type'] == 'bool' and by_key['gifs']['default'] is False
    assert all(r['consumed_by'] for r in rows)                       # nothing is a dead knob


def test_no_key_overlaps_the_trader_guardrails(cfg):
    """YOUR file must not shadow scripts/trader/settings.py keys (it owns the guardrails)."""
    if not os.path.exists(TRADER_SETTINGS):
        pytest.skip('scripts/trader is private (gitignored) - not present in this checkout')
    assert not (set(cfg.SPEC_KEYS) & set(read_json(TRADER_SETTINGS)))


def test_spec_does_not_own_trader_knob_names(cfg):
    for name in ('dry_run', 'max_new_listings_per_day', 'undercut_platinum',
                 'min_price_platinum', 'min_price_pct_of_median', 'max_active_listings',
                 'buy_budget_cap_platinum', 'poll_seconds'):
        assert cfg.spec_for(name) is None, name


def test_spec_for_is_case_insensitive(cfg):
    assert cfg.spec_for('PORT')['key'] == 'port'
    assert cfg.spec_for('nope') is None


# -------------------------------------------------------------- validation

def test_bounds_are_inclusive_and_outside_is_refused(cfg):
    for key, (lo, hi, _) in RANGES.items():
        for value in (lo, hi):
            ok, got, err = cfg.validate(key, str(value))
            assert ok and got == value and err is None, (key, value)
        for value in (lo - 1, hi + 1):
            ok, got, err = cfg.validate(key, str(value))
            assert not ok and got is None and f'{lo}..{hi}' in err, (key, value, err)


def test_non_numeric_and_boolean_values_are_refused(cfg):
    for raw in ('abc', '', '1.5', 'nan', 'inf', True, False, None, '8787p'):
        ok, _, err = cfg.validate('port', raw)
        assert not ok and 'whole number' in err, raw
    ok, got, _ = cfg.validate('port', '8787.0')                      # integral float text ok
    assert ok and got == 8787 and isinstance(got, int)


def test_choice_values_are_trimmed_lowercased_and_checked(cfg):
    assert cfg.validate('host', '127.0.0.1') == (True, '127.0.0.1', None)
    assert cfg.validate('host', ' 0.0.0.0 ') == (True, '0.0.0.0', None)
    assert cfg.validate('currency_display', 'PLAT') == (True, 'plat', None)
    for key, raw in (('host', 'localhost'), ('host', '8.8.8.8'), ('host', '::1'),
                     ('host', True), ('host', 1), ('currency_display', 'gold'),
                     ('currency_display', ''), ('currency_display', 1)):
        ok, got, err = cfg.validate(key, raw)
        assert not ok and got is None, (key, raw)
        assert 'expects one of' in err, (key, raw, err)


def test_bool_coercion_for_gifs(cfg):
    for raw in ('true', 'TRUE', 'on', '1', 'yes', True):
        assert cfg.validate('gifs', raw) == (True, True, None), raw
    for raw in ('false', 'FALSE', 'off', '0', 'no', False):
        assert cfg.validate('gifs', raw) == (True, False, None), raw
    for raw in ('maybe', '', '2', 1.5, None):
        ok, _, err = cfg.validate('gifs', raw)
        assert not ok and 'true/false' in err, raw
    for key in ('port', 'theme', 'auto_refresh_seconds'):
        assert not cfg.validate(key, 'true')[0]


def test_unknown_and_note_keys_are_refused(cfg, tmp_path):
    res = cfg.apply_changes([('list_cap', '5')], p=tmp_path / 'config.json')
    assert not res['ok'] and res['code'] == 2 and 'port' in res['error']
    assert not cfg.validate('_comment', 'x')[0]
    assert not cfg.validate('_comment_port', 'x')[0]
    assert not os.path.exists(tmp_path / 'config.json')


# --------------------------------------------------- create once, then never

def test_first_use_creates_the_file_with_defaults_and_notes(cfg, tmp_path):
    p = tmp_path / 'config.json'
    assert cfg.SPEC_KEYS[0] == 'port'                                # sanity: documented order
    res = cfg.ensure(p=p)
    assert res['ok'] and res['created'] and res['code'] == 0
    doc = read_json(p)
    assert all(doc[k] == cfg.DEFAULTS[k] for k in cfg.SPEC_KEYS)     # defaults on disk
    assert doc[cfg.NOTE] == cfg.HEADER
    assert all(doc[cfg.NOTE_PREFIX + k] == cfg.spec_for(k)['note'] for k in cfg.SPEC_KEYS)
    assert len(doc) == 2 * len(cfg.SPEC_KEYS) + 1
    raw = open(str(p), 'rb').read()
    assert raw.endswith(b'}\n') and b'\r' not in raw                 # LF, indent 2, newline
    assert cfg.audit(doc) == []
    assert os.listdir(str(tmp_path)) == ['config.json']              # no tmp leftovers


def test_second_use_never_rewrites(cfg, tmp_path):
    p = tmp_path / 'config.json'
    cfg.ensure(p=p)
    once = sha(p)
    res = cfg.ensure(p=p)
    assert res['ok'] and res['created'] is False and sha(p) == once


def test_creation_makes_missing_parent_dirs(cfg, tmp_path):
    p = tmp_path / 'deep' / 'data' / 'config.json'
    assert cfg.ensure(p=p)['created'] and os.path.exists(str(p))


def test_first_set_creates_then_later_sets_merge_without_regenerating(cfg, tmp_path):
    p = tmp_path / 'config.json'
    res = cfg.apply_changes([('theme', '7')], p=p)
    assert res['ok'] and res['created'] and read_json(p)['theme'] == 7
    assert all(read_json(p)[k] == cfg.DEFAULTS[k] for k in cfg.SPEC_KEYS if k != 'theme')
    assert len(res['notes']) == len(cfg.SPEC_KEYS) + 1               # notes kept, not dropped
    res = cfg.apply_changes([('host', '0.0.0.0')], p=p)
    assert res['created'] is False and res['changes']['host'] == {
        'from': '127.0.0.1', 'to': '0.0.0.0', 'unchanged': False}
    assert read_json(p)['theme'] == 7                                # earlier edit survived


def test_hand_edits_survive_a_write(cfg, tmp_path):
    p = tmp_path / 'config.json'
    write_text(p, '{"theme": 11, "future_knob": 7, "port": 8080}')
    res = cfg.apply_changes([('auto_refresh_seconds', '120')], p=p)
    doc = read_json(p)
    assert res['ok'] and res['preserved'] == ['future_knob']
    assert (doc['theme'], doc['future_knob'], doc['port']) == (11, 7, 8080)
    assert doc['auto_refresh_seconds'] == 120 and doc['host'] == '127.0.0.1'
    assert list(doc)[:3] == ['theme', 'future_knob', 'port']         # user key order kept
    assert not any(cfg.is_note(k) for k in doc)                      # deleted notes stay gone
    assert all(k in doc for k in cfg.SPEC_KEYS)                      # every knob still present


def test_rewriting_an_unchanged_doc_is_byte_idempotent(seeded):
    cfg, p = seeded
    cfg.apply_changes([('theme', '9')], p=p)
    once = sha(p)
    cfg.apply_changes([('theme', '9')], p=p)
    assert sha(p) == once
    assert b'\r' not in open(str(p), 'rb').read()


def test_a_crlf_file_keeps_its_line_endings(cfg, tmp_path):
    p = tmp_path / 'config.json'
    write_text(p, '{\r\n  "port": 9000,\r\n  "theme": 2\r\n}\r\n')
    res = cfg.apply_changes([('theme', '3')], p=p)
    raw = open(str(p), 'rb').read()
    assert res['ok'] and b'"theme": 3' in raw and b'"port": 9000' in raw
    assert raw.count(b'\r\n') == raw.count(b'\n') > 4                # never reformatted to LF


# ------------------------------------------------------- refused writes

def test_refused_writes_leave_the_file_byte_identical(seeded):
    cfg, p = seeded
    before = sha(p)
    for pairs in ([('port', '80')], [('port', '65536')], [('host', 'localhost')],
                  [('theme', '30')], [('auto_refresh_seconds', '5')], [('gifs', 'maybe')],
                  [('nonsense', '1')], [('port', 'abc')]):
        res = cfg.apply_changes(pairs, p=p)
        assert not res['ok'] and res['code'] == 2, pairs
        assert sha(p) == before, pairs


def test_out_of_range_and_choice_refusals_explain_themselves(seeded):
    cfg, p = seeded
    assert '1024..65535' in cfg.apply_changes([('port', '99')], p=p)['error']
    err = cfg.apply_changes([('host', 'localhost')], p=p)['error']
    assert '127.0.0.1' in err and '0.0.0.0' in err


def test_one_bad_value_refuses_the_whole_batch(seeded):
    cfg, p = seeded
    before = sha(p)
    res = cfg.apply_changes([('theme', '5'), ('port', '99')], p=p)
    assert not res['ok'] and sha(p) == before and read_json(p)['theme'] == 0


def test_corrupt_file_is_never_overwritten(seeded):
    cfg, p = seeded
    write_text(p, '{"port": 8787, "theme": 3,')
    bad = sha(p)
    res = cfg.apply_changes([('theme', '4')], p=p)
    assert not res['ok'] and res['code'] == 2 and 'not valid JSON' in res['error']
    assert sha(p) == bad
    res = cfg.ensure(p=p)
    assert not res['ok'] and res['code'] == 2 and sha(p) == bad
    r = cli(p, '--set', 'theme=4')
    assert r.returncode == 2 and sha(p) == bad
    r = cli(p, '--init')
    assert r.returncode == 2 and sha(p) == bad
    r = cli(p, '--show')
    assert r.returncode == 2 and 'not valid JSON' in r.stderr and sha(p) == bad
    assert cli(p, '--get', 'theme').returncode == 2 and sha(p) == bad


# ----------------------------------------------------------------- read()

def test_read_never_raises_and_always_returns_every_knob(cfg, tmp_path):
    p = tmp_path / 'config.json'
    assert cfg.read(p=p) == cfg.DEFAULTS                             # absent file
    write_text(p, '{"port": "not a number", "theme": 99, "host": "0.0.0.0"}')
    eff = cfg.read(p=p)
    assert set(eff) == set(cfg.SPEC_KEYS)                            # consumers never KeyError
    assert eff['host'] == '0.0.0.0'                                  # valid values survive
    assert eff['port'] == 8787 and eff['theme'] == 0                 # bad values -> defaults
    write_text(p, '{"port":')
    assert cfg.read(p=p) == cfg.DEFAULTS                             # corrupt file
    assert cfg.audit({'nonsense': 1}) == [] and cfg.audit({}) == []  # only real problems


def test_read_does_not_write(cfg):
    doc_before = sha(SHIPPED)
    cfg.read()
    assert sha(SHIPPED) == doc_before


def test_import_never_creates_the_file(tmp_path, monkeypatch):
    p = tmp_path / 'config.json'
    load_config(monkeypatch, p)
    assert not os.path.exists(str(p))
    assert not os.path.exists(str(tmp_path / 'config.json'))


def test_env_override_drives_path(cfg, tmp_path):
    assert cfg.path() == str(tmp_path / 'config.json')


# -------------------------------------------------------------------- CLI

def test_cli_show_get_set_roundtrip(seeded):
    cfg, p = seeded
    r = cli(p, '--set', 'theme=9', '--set', 'auto_refresh_seconds=120', '--show')
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'theme = 9 (was 0)' in r.stdout
    shown = json.loads(r.stdout[r.stdout.index('{'):])
    assert set(shown) == set(cfg.SPEC_KEYS)                          # notes never leak into --show
    assert shown['theme'] == 9 and shown['auto_refresh_seconds'] == 120
    assert cli(p, '--get', 'theme').stdout.strip() == '9'
    assert cli(p, '--get', 'host').stdout.strip() == '127.0.0.1'     # bare, no quotes
    assert cli(p, '--get', 'gifs').stdout.strip() == 'false'


def test_cli_init_is_create_once(seeded):
    cfg, p = seeded
    before = sha(p)
    r = cli(p, '--init')
    assert r.returncode == 0 and 'left unchanged' in r.stdout and sha(p) == before
    fresh = os.path.join(os.path.dirname(str(p)), 'fresh.json')
    r = cli(fresh, '--init')
    assert r.returncode == 0 and 'created with defaults' in r.stdout
    assert read_json(fresh)['port'] == 8787
    once = sha(fresh)
    assert cli(fresh, '--init').returncode == 0 and sha(fresh) == once


def test_cli_rejects_bad_syntax_and_unknown_keys(seeded):
    cfg, p = seeded
    before = sha(p)
    assert cli(p, '--set', 'port=80').returncode == 2
    assert cli(p, '--set', 'noequals').returncode == 2
    assert cli(p, '--set', 'future_knob=1').returncode == 2
    assert cli(p, '--set', 'host=localhost').returncode == 2
    assert cli(p, '--get', 'nope').returncode == 2
    assert cli(p, '--get', '_comment').returncode == 2
    assert sha(p) == before and read_json(p) == read_json(p)


def test_cli_show_and_get_never_write(seeded):
    cfg, p = seeded
    before = sha(p)
    shown = json.loads(cli(p, '--show').stdout)                      # notes hidden, knobs shown
    on_disk = read_json(p)
    assert set(shown) == set(cfg.SPEC_KEYS)
    assert all(shown[k] == on_disk[k] for k in cfg.SPEC_KEYS)
    assert cli(p, '--schema').returncode == 0
    assert json.loads(cli(p, '--schema').stdout)[0]['key'] == 'port'
    assert cli(p, '--get', 'port').returncode == 0
    assert sha(p) == before


def test_selftest_cli_passes_offline(seeded):
    cfg, p = seeded
    r = cli(p, '--selftest')
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'selftest: all' in r.stdout and 'checks passed' in r.stdout
    assert sha(p) is not None


# --------------------------------------------------------- guard on the repo file

def test_shipped_config_is_clean_when_present(cfg):
    if not os.path.exists(SHIPPED):
        pytest.skip('data/ is gitignored - no local config.json in this checkout')
    doc = read_json(SHIPPED)
    assert not cfg.audit(doc)                                        # no out-of-range value
    # create-once: the file is never regenerated, so a knob added by a newer engine is
    # legitimately absent from a file created earlier - it applies at its default until the
    # user sets it. What must hold is that every key on disk is a known knob (no strays) and
    # that the consumer read() still fills every knob.
    assert {k for k in doc if not cfg.is_note(k)} <= set(cfg.SPEC_KEYS)
    assert set(cfg.read()) == set(cfg.SPEC_KEYS)
    assert json.loads(json.dumps(doc)) == doc


def test_the_real_config_file_was_never_written():
    assert sha(SHIPPED) == REAL_HASH
