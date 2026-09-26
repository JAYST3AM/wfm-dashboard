"""server.py dashboard-config API (#45): GET /api/config payload + the write path.

server.py only shells out to scripts/config.py; these tests exercise the two module-level
helpers behind the routes (dashcfg_payload / dashcfg_set). ROOT points at the real repo so
scripts/config.py is found, while WFM_CONFIG redirects every read and write into tmp_path -
the repo's own data/config.json is never touched (the last test re-hashes it to prove that).
No sockets, no network.
"""
import hashlib
import json
import os

from conftest import REPO

SHIPPED = os.path.join(REPO, 'data', 'config.json')
KEYS = ['port', 'host', 'theme', 'auto_refresh_seconds', 'currency_display', 'advanced', 'clan_name', 'gifs',
        'gamenews_cache_seconds', 'deals_shown', 'sessions_shown']


def sha(p):
    try:
        with open(p, 'rb') as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


REAL_HASH = sha(SHIPPED)          # captured at import; checked again by the last test


def read_json(p):
    with open(str(p), encoding='utf-8') as fh:
        return json.load(fh)


def wire(server_mod, monkeypatch, tmp_path):
    """server_mod with ROOT=the repo (config.py lives there) and a tmp config file."""
    monkeypatch.setattr(server_mod, 'ROOT', REPO)
    cfg = tmp_path / 'config.json'
    monkeypatch.setenv('WFM_CONFIG', str(cfg))
    return server_mod, cfg


# ------------------------------------------------------------------ GET payload

def test_config_payload_carries_values_and_schema(server_mod, monkeypatch, tmp_path):
    api, cfg = wire(server_mod, monkeypatch, tmp_path)

    body = api.dashcfg_payload()

    assert body['error'] is None
    keys = [r['key'] for r in body['schema']]
    assert keys[:len(KEYS)] == KEYS           # the #45 knobs, in spec order...
    assert set(body['values']) == set(keys)   # ...each with a value (later knobs append)
    assert body['values']['port'] == 8787 and body['values']['deals_shown'] == 60
    assert not cfg.exists()                                  # --show never creates the file


def test_schema_rows_carry_the_fields_the_ui_renders(server_mod, monkeypatch, tmp_path):
    api, _cfg = wire(server_mod, monkeypatch, tmp_path)

    rows = {r['key']: r for r in api.dashcfg_payload()['schema']}

    assert all({'key', 'type', 'min', 'max', 'default', 'choices', 'step', 'help',
                'consumed_by', 'note'} <= set(r) for r in rows.values())
    assert {r['type'] for r in rows.values()} == {'min/max', 'choice', 'bool', 'text'}
    assert rows['host']['choices'] == ['127.0.0.1', '0.0.0.0']       # JSON round-trip: list
    assert rows['currency_display']['choices'] == ['p', 'plat', 'none']
    assert (rows['port']['min'], rows['port']['max'], rows['port']['step']) == (1024, 65535, 1)
    assert (rows['deals_shown']['min'], rows['deals_shown']['max']) == (1, 200)
    assert (rows['sessions_shown']['min'], rows['sessions_shown']['max']) == (1, 60)
    assert (rows['auto_refresh_seconds']['min'], rows['auto_refresh_seconds']['max']) == (15, 3600)


def test_config_payload_degrades_when_the_engine_is_missing(server_mod, monkeypatch, tmp_path):
    monkeypatch.setattr(server_mod, 'ROOT', str(tmp_path / 'elsewhere'))
    monkeypatch.setenv('WFM_CONFIG', str(tmp_path / 'config.json'))

    body = server_mod.dashcfg_payload()

    assert body['values'] == {} and body['schema'] == [] and body['error']


# ------------------------------------------------------------------ POST write path

def test_config_set_writes_then_the_payload_reads_it_back(server_mod, monkeypatch, tmp_path):
    api, cfg = wire(server_mod, monkeypatch, tmp_path)

    code, body = api.dashcfg_set({'deals_shown': 61, 'theme': 7})

    assert code == 200 and body['ok'] is True
    assert [r['key'] for r in body['results']] == ['deals_shown', 'theme']
    assert all(r['ok'] for r in body['results'])
    assert 'deals_shown = 61' in body['results'][0]['message']       # config.py's own report
    assert body['cfg']['values']['deals_shown'] == 61                # cfg returned for the UI
    assert read_json(cfg)['deals_shown'] == 61 and read_json(cfg)['theme'] == 7
    assert api.dashcfg_payload()['values']['deals_shown'] == 61


def test_config_set_accepts_json_bool_values(server_mod, monkeypatch, tmp_path):
    api, cfg = wire(server_mod, monkeypatch, tmp_path)

    _code, body = api.dashcfg_set({'gifs': True})
    assert body['ok'] is True and read_json(cfg)['gifs'] is True

    _code, body = api.dashcfg_set({'gifs': False})
    assert body['ok'] is True and read_json(cfg)['gifs'] is False
    assert body['cfg']['values']['gifs'] is False


def test_config_set_refusal_is_reported_and_writes_nothing(server_mod, monkeypatch, tmp_path):
    api, cfg = wire(server_mod, monkeypatch, tmp_path)
    api.dashcfg_set({'deals_shown': 61})
    before = sha(cfg)

    code, body = api.dashcfg_set({'port': 80, 'theme': 3})

    assert code == 200 and body['ok'] is False
    assert body['rc'] == 2
    assert '1024..65535' in body['error']                     # config.py's own message
    assert len(body['results']) == 1                          # batch stops at the refused pair
    assert body['results'][0]['key'] == 'port' and body['results'][0]['ok'] is False
    assert sha(cfg) == before                                 # byte-identical file
    assert read_json(cfg)['theme'] != 3
    assert body['cfg']['values']['port'] == 8787              # cfg still shipped for the UI


def test_config_set_with_no_pairs_is_a_noop(server_mod, monkeypatch, tmp_path):
    api, cfg = wire(server_mod, monkeypatch, tmp_path)

    code, body = api.dashcfg_set({})

    assert code == 200 and body['ok'] is True and body['results'] == []
    assert not cfg.exists()                                   # nothing ran, nothing created


def test_repo_config_json_untouched_by_these_tests(server_mod, monkeypatch, tmp_path):
    api, _cfg = wire(server_mod, monkeypatch, tmp_path)
    api.dashcfg_set({'deals_shown': 61})

    assert sha(SHIPPED) == REAL_HASH
