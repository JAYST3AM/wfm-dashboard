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


def _boot(monkeypatch, tmp_path, data_dir):
    """A real server on 127.0.0.1:<ephemeral>, DATA/ROOT/STATIC redirected into tmp_path."""
    mod = load_script('server', monkeypatch=monkeypatch, env={'WFM_PORT': '0'})
    monkeypatch.setattr(mod, 'DATA', str(data_dir))
    monkeypatch.setattr(mod, 'ROOT', str(tmp_path))
    monkeypatch.setattr(mod, 'STATIC', os.path.join(str(tmp_path), 'static'))
    srv = ThreadingHTTPServer(('127.0.0.1', 0), mod.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return mod, srv, 'http://127.0.0.1:%d' % srv.server_address[1]


@pytest.fixture
def live(monkeypatch, tmp_path, data_dir):
    """(base url, data dir). The module object is not needed by most tests - see live_mod."""
    mod, srv, base = _boot(monkeypatch, tmp_path, data_dir)
    try:
        yield base, str(data_dir)
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.fixture
def live_mod(monkeypatch, tmp_path, data_dir):
    """(base url, data dir, module) for tests that must watch what the routes call."""
    mod, srv, base = _boot(monkeypatch, tmp_path, data_dir)
    try:
        yield base, str(data_dir), mod
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


# --------------------------------------------------------------------------- stage 4: the check
def test_the_check_rides_the_session_payload(live, seeded):
    base, _ = live
    call(base, '/api/session/start', {})
    call(base, '/api/session/contact', {'slug': 'primed_continuity', 'rank': 0, 'qty': 3,
                                        'price': 48, 'user': 'Wombat'})
    # the stack went from 4 to 1 and platinum from 1220 to 1364: exactly the 3 x 48 that was asked
    write_json(os.path.join(base and live[1], 'report.json'),
               {'sell_now': [{'slug': 'primed_continuity', 'lane_rank': 0, 'sellable_count': 1}]})
    write_json(os.path.join(live[1], 'plat_history.json'), [{'ts': 1, 'plat': 1364}])
    body = call(base, '/api/session')[1]
    assert body['needs_you'] == 1 and body['checks']['exact'] == 1
    p = body['proposals'][0]
    assert p['verdict'] == 'exact' and p['copies_left'] == 3 and p['plat_delta'] == 144
    assert p['trade']['plat'] == 48 and p['trade']['total'] == 144
    assert p['trade']['pending_id'] == body['pending'][0]['id']


def test_the_reconcile_route_answers_and_writes_nothing(live, seeded):
    base, d = live
    call(base, '/api/session/start', {})
    call(base, '/api/session/contact', {'slug': 'primed_continuity', 'rank': 0, 'qty': 3,
                                        'price': 48, 'user': 'Wombat'})
    store = os.path.join(d, 'trade_session.json')
    before = open(store, 'rb').read()
    code, body = call(base, '/api/session/reconcile', {})
    assert code == 200 and body['ok'] is True
    assert body['proposals'][0]['verdict'] in ('none', 'unknown')
    assert open(store, 'rb').read() == before
    assert not os.path.exists(os.path.join(d, 'trade_log.json'))


# --------------------------------------------------------------------------- stage 5: the confirm
def test_the_confirm_route_logs_one_trade_and_moves_the_session(live_mod, seeded):
    base, d, mod = live_mod
    kicked = []
    mod._kick_sync = lambda *a, **k: kicked.append(a)
    call(base, '/api/session/start', {})
    call(base, '/api/session/contact', {'slug': 'primed_continuity', 'rank': 0, 'qty': 3,
                                        'price': 48, 'user': 'Wombat'})
    code, body = call(base, '/api/session/confirm',
                      {'slug': 'primed_continuity', 'rank': 0, 'qty': 3, 'plat': 48,
                       'total': 144, 'user': 'Wombat'})
    assert code == 200 and body['created'] is True and body['ok'] is True
    log = json.loads(open(os.path.join(d, 'trade_log.json'), encoding='utf-8').read())
    # plat is the price per copy and total the money for the trade: everything downstream sums
    # `total`, so both numbers have to be there and mean what the rest of the repo means by them
    assert len(log) == 1 and log[0]['id'] == body['trade']['id']
    assert log[0]['plat'] == 48 and log[0]['total'] == 144
    assert body['session_payload']['summary']['earned_plat'] == 144.0
    assert body['session_payload']['summary']['trades'] == 1
    assert body['session_payload']['pending'] == []
    assert kicked, 'a confirmation must set the local pipeline going'


def test_confirming_twice_over_http_logs_one_trade(live, seeded):
    base, d = live
    call(base, '/api/session/start', {})
    call(base, '/api/session/contact', {'slug': 'primed_continuity', 'rank': 0, 'qty': 3,
                                        'price': 48, 'user': 'Wombat'})
    rec = {'slug': 'primed_continuity', 'rank': 0, 'qty': 3, 'plat': 48, 'total': 144,
           'user': 'Wombat'}
    first = call(base, '/api/session/confirm', rec)[1]
    again = call(base, '/api/session/confirm', first['trade'])[1]
    assert again['already'] is True and again['trade']['id'] == first['trade']['id']
    log = json.loads(open(os.path.join(d, 'trade_log.json'), encoding='utf-8').read())
    assert len(log) == 1


def test_a_bad_confirmation_is_refused_not_500(live, seeded):
    base, d = live
    code, body = call(base, '/api/session/confirm', {'slug': ''})
    assert code == 400 and body['ok'] is False
    assert not os.path.exists(os.path.join(d, 'trade_log.json'))


def test_the_event_route_uses_the_same_writer(live, seeded):
    base, d = live
    code, body = call(base, '/api/trades', {'kind': 'listing', 'slug': 'x', 'qty': 1, 'plat': 5})
    assert code == 200 and body['ok'] is True and body['created'] is True and body['id']
    log = json.loads(open(os.path.join(d, 'trade_log.json'), encoding='utf-8').read())
    assert len(log) == 1 and log[0]['id'] == body['id']
    assert call(base, '/api/trades', {'kind': 'shouting', 'slug': 'x'})[1]['ok'] is False


def test_the_event_route_never_double_logs_the_same_event(live, seeded):
    base, d = live
    rec = {'kind': 'sale', 'slug': 'x', 'qty': 1, 'plat': 5, 'ts': 1000}
    first = call(base, '/api/trades', rec)[1]
    again = call(base, '/api/trades', rec)[1]
    assert first['created'] is True and again['created'] is False
    assert json.loads(open(os.path.join(d, 'trade_log.json'), encoding='utf-8').read())[0]['id'] \
        == first['id']


def test_the_trades_route_stores_the_money_a_sale_omits(live):
    """The writer boundary, through the route: {kind: sale, qty: 3, plat: 48} has no `total`, and
    every reader sums `total` - so the route must store one rather than an unsummable record."""
    base, d = live
    out = call(base, '/api/trades', {'kind': 'sale', 'slug': 'x', 'qty': 3, 'plat': 48})[1]
    assert out['ok'] is True
    stored = json.loads(open(os.path.join(d, 'trade_log.json'), encoding='utf-8').read())[0]
    assert stored['plat'] == 48 and stored['total'] == 144


def test_the_trades_route_refuses_a_sale_with_no_price(live):
    base, d = live
    code, out = call(base, '/api/trades', {'kind': 'sale', 'slug': 'x', 'qty': 3})
    assert code == 400 and out['ok'] is False and 'price' in out['error']
    assert not os.path.exists(os.path.join(d, 'trade_log.json'))


def test_a_lane_the_report_does_not_carry_still_gets_a_count(live, seeded):
    """Found on the live store, not in a fixture: the plan sells an unranked lane (rank 0) while
    report.json only carries the maxed lane (rank 10) for that item. The old lookup took the exact
    lane or nothing, so the contact snapshotted inv_before=None and that trade could never be more
    than UNKNOWN. Now the item's total across lanes is used, labelled as an item count."""
    base, d = live
    write_json(os.path.join(d, 'report.json'),
               {'sell_now': [{'slug': 'primed_continuity', 'lane_rank': 10, 'sellable_count': 4}]})
    call(base, '/api/session/start', {})
    body = call(base, '/api/session/contact', {'slug': 'primed_continuity', 'rank': 0, 'qty': 3,
                                               'price': 48, 'user': 'Wombat'})[1]
    p = body['pending']
    assert p['inv_before'] == 4 and p['inv_basis'] == 'item', p
    assert p['plat_before'] == 1220

    # the stacks really went down, so the check is a proposal now instead of a permanent unknown -
    # and it is AMBIGUOUS, not exact: the evidence is the whole item's count while the trade is for
    # one rank of it, so a copy of another rank selling would look the same (review round 3)
    write_json(os.path.join(d, 'report.json'),
               {'sell_now': [{'slug': 'primed_continuity', 'lane_rank': 10, 'sellable_count': 1}]})
    write_json(os.path.join(d, 'plat_history.json'), [{'ts': 1, 'plat': 1364}])
    check = call(base, '/api/session')[1]['proposals'][0]
    assert check['verdict'] == 'ambiguous' and check['copies_left'] == 3
    assert 'basis: item total' in check['evidence']
    assert any('the whole item, not this lane' in x for x in check['evidence'])


def test_a_lane_the_report_does_carry_is_counted_as_that_lane(live, seeded):
    base, d = live
    call(base, '/api/session/start', {})
    call(base, '/api/session/contact', {'slug': 'primed_continuity', 'rank': 0, 'qty': 3,
                                        'price': 48, 'user': 'Wombat'})
    store = json.loads(open(os.path.join(d, 'trade_session.json'), encoding='utf-8').read())
    assert store['pending'][0]['inv_basis'] == 'lane'
    assert store['pending'][0]['inv_before'] == 4
