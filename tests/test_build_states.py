"""Trading Session, stage 7 — first-run build progress, told truthfully.

docs/trading-session-workflow.md §9: the first build takes a while and the app must not look dead,
but the scripts cannot report a percentage, so the states are Waiting / Running / Complete / Failed.
No fabricated percentages, no invented ETAs - and the route is a read, so it never starts a build.
"""
import json
import os
import time

import pytest

from conftest import load_script, read_static, write_json


@pytest.fixture
def srv(tmp_path, monkeypatch, data_dir):
    mod = load_script('server', monkeypatch=monkeypatch, env={'WFM_PORT': '0'})
    monkeypatch.setattr(mod, 'DATA', str(data_dir))
    monkeypatch.setattr(mod, 'ROOT', str(tmp_path))
    return mod


def rows(mod):
    return {r['key']: r for r in mod.build_payload()['rows']}


# --------------------------------------------------------------------------- the states
def test_with_nothing_built_every_artifact_waits(srv):
    out = srv.build_payload()
    assert out['ok'] is True and out['complete'] == 0 and out['total'] == len(srv.BUILD_ARTIFACTS)
    assert {r['state'] for r in out['rows']} == {'waiting'}
    assert all(r['age_s'] is None for r in out['rows'])


def test_an_artifact_that_exists_is_complete_with_its_age(srv, data_dir):
    write_json(os.path.join(str(data_dir), 'owned.json'), [])
    r = rows(srv)['inventory']
    assert r['state'] == 'complete' and r['age_s'] is not None and r['age_s'] < 60
    assert rows(srv)['player']['state'] == 'waiting'


def test_a_running_pipeline_shows_running(srv, monkeypatch):
    monkeypatch.setitem(srv.SYNC, 'running', True)
    assert {r['state'] for r in srv.build_payload()['rows']} == {'running'}


def test_a_failed_run_says_so_and_repeats_the_reason(srv, monkeypatch):
    monkeypatch.setitem(srv.SYNC, 'last_ok', False)
    monkeypatch.setitem(srv.SYNC, 'error', 'refresh.py rc=1')
    out = srv.build_payload()
    assert out['last_ok'] is False and out['error'] == 'refresh.py rc=1'
    assert {r['state'] for r in out['rows']} == {'failed'}
    assert all(r['detail'] == 'refresh.py rc=1' for r in out['rows'])


def test_a_built_artifact_stays_complete_even_after_a_failed_run(srv, data_dir, monkeypatch):
    write_json(os.path.join(str(data_dir), 'prices.json'), {})
    monkeypatch.setitem(srv.SYNC, 'last_ok', False)
    monkeypatch.setitem(srv.SYNC, 'error', 'fetch_prices.py rc=1')
    r = rows(srv)['prices']
    assert r['state'] == 'complete', 'what landed stays landed; the failure is the pipeline own state'


def test_the_payload_never_invents_a_percentage(srv):
    out = srv.build_payload()
    for row in out['rows']:
        for key in row:
            assert 'percent' not in key and 'pct' not in key
    assert 'seconds' in out, 'the sync cadence, which is a real number'


def test_reading_the_build_state_writes_nothing(srv, data_dir):
    before = sorted(os.listdir(str(data_dir)))
    srv.build_payload()
    assert sorted(os.listdir(str(data_dir))) == before


def test_the_build_route_answers_over_http(srv):
    """The route itself, over a real socket (the same shape test_session_api.py uses)."""
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), srv.H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        url = 'http://127.0.0.1:%d/api/build' % httpd.server_address[1]
        with urllib.request.urlopen(url, timeout=10) as r:
            body = json.loads(r.read().decode('utf-8'))
        assert r.status == 200 and body['ok'] is True and len(body['rows']) == 8
    finally:
        httpd.shutdown()
        httpd.server_close()


# --------------------------------------------------------------------------- the front end
def test_the_first_run_card_asks_for_the_states_and_polls_nothing():
    app = read_static('app.js')
    build = read_static('build.js')
    assert 'id="buildList"' in app and 'renderBuildStates();' in app
    assert 'id="buildMeta"' in app
    assert "fetch('/api/build')" in build
    assert 'setInterval' not in build and 'setTimeout' not in build, 'no timer: Refresh re-reads it'
    idx = read_static('index.html')
    assert '"/build.js"' in idx and idx.index('"/build.js"') < idx.index('"/app.js"'), \
        'renderFirstRun calls it while app.js is still parsing'


def test_the_states_are_worded_the_way_the_spec_words_them():
    build = read_static('build.js')
    for state in ('complete', 'running', 'failed', 'waiting'):
        assert state in build, state
    assert 'just now' in build and "'m ago'" in build and "'h ago'" in build
    assert 'pct' not in build.lower() and '%' not in build, 'no invented percentages, ever'
