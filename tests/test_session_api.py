"""Trading Session, stage 2 — the routes, against a real socket.

The audit that opened this work found that pytest had no live-HTTP route test at all, so the
read-only promise of §13 ("changing a control never writes history") had nothing to lean on.
server.py now honours WFM_ROOT/WFM_DATA, which lets these tests bind the real handler on an
ephemeral port, point it at a tmp data dir and drive it with urllib: the session route answers,
a GET writes nothing, and every POST that should refuse does.

The autosync thread is never started here (only __main__ starts it), so nothing runs a pipeline
inside the test.
"""
import json
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from conftest import load_script, write_json


@pytest.fixture
def live(monkeypatch, tmp_path, data_dir):
    """A real server on 127.0.0.1:<ephemeral>, DATA/ROOT redirected into tmp_path."""
    mod = load_script('server', monkeypatch=monkeypatch, env={'WFM_PORT': '0'})
    monkeypatch.setattr(mod, 'DATA', str(data_dir))
    monkeypatch.setattr(mod, 'ROOT', str(tmp_path))
    monkeypatch.setattr(mod, 'STATIC', os.path.join(str(tmp_path), 'static'))
    srv = ThreadingHTTPServer(('127.0.0.1', 0), mod.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = 'http://127.0.0.1:%d' % srv.server_address[1]
    try:
        yield base, str(data_dir)
    finally:
        srv.shutdown()
        srv.server_close()


def call(base, path, body=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method or ('POST' if data else 'GET'),
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode('utf-8'))


@pytest.fixture
def seeded(data_dir):
    """The recommendation payloads the queue is built from, on disk where the server reads them."""
    d = str(data_dir)
    write_json(os.path.join(d, 'trader_plan.json'),
               {'plan': [{'slug': 'primed_continuity', 'name': 'Primed Continuity', 'per_trade': 3,
                          'price': 48, 'lane': 'rank 0'},
                         {'slug': 'shredder', 'name': 'Shredder', 'per_trade': 6, 'price': 8,
                          'lane': 'rank 5'}]})
    write_json(os.path.join(d, 'report.json'),
               {'sell_now': [{'slug': 'primed_continuity', 'name': 'Primed Continuity', 'cat': 'mod',
                              'lane_rank': 0, 'lane_ask': 90, 'vol48': 110, 'n_buy': 5,
                              'sellable_count': 4},
                             {'slug': 'shredder', 'name': 'Shredder', 'cat': 'mod', 'lane_rank': 5,
                              'lane_ask': 8, 'vol48': 0, 'n_buy': 0, 'sellable_count': 87}]})
    write_json(os.path.join(d, 'run_queue.json'),
               {'queue': [{'slug': 'primed_continuity', 'qty': 3, 'my_price': 48, 'buyer': 'Wombat',
                           'buyer_status': 'ingame', 'buy_price': 71}],
                'summary': {'ingame': 2, 'online': 1, 'total': 9}})
    write_json(os.path.join(d, 'trader_limits.json'),
               {'plat': 1220, 'account': 'Tester', 'trades_left': 6, 'trade_cap': 20})
    return d


# --------------------------------------------------------------------------- GET
def test_get_session_answers_empty_before_a_session_exists(live):
    base, _ = live
    code, body = call(base, '/api/session')
    assert code == 200 and body['ok'] is True
    assert body['session'] is None and body['summary']['active'] is False
    assert body['pending'] == [] and body['suggested'] == []


def test_get_session_never_writes(live):
    base, d = live
    call(base, '/api/session')
    call(base, '/api/feature/session')
    assert not os.path.exists(os.path.join(d, 'trade_session.json'))
    assert sorted(os.listdir(d)) == []


def test_the_feature_route_and_the_route_agree(live, seeded):
    base, _ = live
    call(base, '/api/session/start', {})
    a = call(base, '/api/session')[1]
    b = call(base, '/api/feature/session')[1]
    assert a['session']['id'] == b['session']['id']
    assert [r['slug'] for r in a['queue']] == [r['slug'] for r in b['queue']]


# --------------------------------------------------------------------------- POST
def test_start_then_focus_then_skip_then_end(live, seeded):
    base, _ = live
    code, body = call(base, '/api/session/start', {})
    assert code == 200 and body['started'] is True
    assert [r['slug'] for r in body['session']['queue']] == ['primed_continuity', 'shredder']
    assert body['summary']['plat_start'] == 1220

    code, body = call(base, '/api/session/focus', {'slug': 'shredder'})
    assert code == 200 and body['session_payload']['focus']['slug'] == 'shredder'

    code, body = call(base, '/api/session/state', {'slug': 'shredder', 'rank': 5,
                                                   'state': 'SKIPPED', 'note': 'no buyers'})
    assert code == 200 and body['row']['state'] == 'SKIPPED'
    assert body['session_payload']['summary']['skipped'] == 1

    code, body = call(base, '/api/session/end', {})
    assert code == 200 and body['session_payload']['summary']['active'] is False
    assert body['session_payload']['summary']['seconds'] >= 0


def test_starting_again_returns_the_live_session_instead_of_replacing_it(live, seeded):
    """Double-clicking Start Trading must never throw the open session away."""
    base, _ = live
    first = call(base, '/api/session/start', {})[1]['session']['id']
    code, body = call(base, '/api/session/start', {})
    assert code == 200 and body['started'] is False
    assert body['session']['id'] == first
    assert 'already open' in body['reason']
    assert call(base, '/api/session')[1]['session']['id'] == first


def test_bad_state_and_unknown_action_are_refused(live, seeded):
    base, _ = live
    call(base, '/api/session/start', {})
    code, body = call(base, '/api/session/state', {'slug': 'primed_continuity', 'state': 'SOLD'})
    assert code == 400 and 'SKIPPED' in body['states']
    code, body = call(base, '/api/session/state', {'slug': 'not-in-the-queue', 'state': 'SKIPPED'})
    assert code == 404
    code, body = call(base, '/api/session/nope', {})
    assert code == 404 and 'unknown session action' in body['error']
    assert 'trade_session.json' in sorted(os.listdir(live[1]))


def test_wrong_typed_body_is_not_a_500(live, seeded):
    base, _ = live
    code, body = call(base, '/api/session/start', body='not-a-dict-object')
    assert code in (200, 409) and 'ok' in body


def test_a_read_of_a_broken_store_does_not_500_or_clobber(live):
    base, d = live
    with open(os.path.join(d, 'trade_session.json'), 'w', encoding='utf-8') as fh:
        fh.write('{"session": {"queue": [')
    code, body = call(base, '/api/session')
    assert code == 200 and body['session'] is None
    assert not os.path.exists(os.path.join(d, 'trade_session.json'))
    assert any(p.startswith('trade_session.json.corrupt-') for p in os.listdir(d))


def test_a_session_survives_a_server_restart(live, seeded, monkeypatch, tmp_path, data_dir):
    """Stop the server, start a new one on the same data dir: the session is still there."""
    base, d = live
    started = call(base, '/api/session/start', {})[1]['session']
    call(base, '/api/session/state', {'slug': 'primed_continuity', 'rank': 0, 'state': 'HELD'})

    mod = load_script('server', monkeypatch=monkeypatch, env={'WFM_PORT': '0'})
    monkeypatch.setattr(mod, 'DATA', d)
    monkeypatch.setattr(mod, 'ROOT', str(tmp_path))
    srv = ThreadingHTTPServer(('127.0.0.1', 0), mod.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        again = call('http://127.0.0.1:%d' % srv.server_address[1], '/api/session')[1]
    finally:
        srv.shutdown()
        srv.server_close()
    assert again['session']['id'] == started['id']
    assert again['session']['started_ts'] == started['started_ts']
    assert again['session']['totals']['held'] == 1
    assert len(again['queue']) == 2
    assert time.time() - again['session']['started_ts'] < 60
