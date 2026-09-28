"""Trading Session, stage 3 — CONTACTED: a whisper that reached the game opens a pending trade.

The audit's front-end note was blunt about this: `ordWhisper()` is the single funnel for every
whisper click, so the session must not add a second one. Instead the side effect lives inside
`POST /api/whisper`, on the branch where the keystrokes actually landed, and it takes the one
snapshot the workflow needs (owned copies + platinum at contact time).

Pinned here: one pending row per (item, rank, buyer), copied-but-not-sent is not a contact, a
session that is not open changes nothing, and a broken session store can never fail the whisper.
"""
import json
import os
import time

import pytest

from conftest import load_script, read_json, write_json


@pytest.fixture
def ts(monkeypatch):
    return load_script('trade_session', monkeypatch=monkeypatch)


@pytest.fixture
def srv(tmp_path, monkeypatch, data_dir):
    mod = load_script('server', monkeypatch=monkeypatch, env={'WFM_PORT': '0'})
    monkeypatch.setattr(mod, 'DATA', str(data_dir))
    monkeypatch.setattr(mod, 'ROOT', str(tmp_path))
    monkeypatch.setattr(mod, '_load_whisper', lambda: (FAKE, None))
    mod._whisper_last[0] = 0.0
    mod._whisper_minute.clear()
    return mod


class FakeWhisper:
    """whisper.py, as /api/whisper sees it: builds a line, copies it, types it if asked."""

    def __init__(self, sent=True):
        self.did_send = []
        self.sent = sent

    def message(self, name, price, kind, rank=None):
        return 'Hi! I am selling: "%s" for %d platinum.' % (name, price)

    def line(self, user, name, price, kind, rank=None):
        return '/w %s %s' % (user, self.message(name, price, kind, rank))

    def copy(self, ln):
        return True

    def send(self, ln, item=None, price=None, kind=None, user=None):
        self.did_send.append((item, price, kind, user))
        return (self.sent, '' if self.sent else 'game not running')


FAKE = FakeWhisper()


@pytest.fixture(autouse=True)
def clean_fake():
    FAKE.did_send = []
    FAKE.sent = True
    yield


PLAN = {'plan': [{'slug': 'primed_continuity', 'name': 'Primed Continuity', 'per_trade': 3,
                  'price': 48, 'lane': 'rank 0'}]}
ADVISOR = {'ranked': [], 'items': {}}
REPORT = {'sell_now': [{'slug': 'primed_continuity', 'name': 'Primed Continuity', 'cat': 'mod',
                        'lane_rank': 0, 'lane_ask': 90, 'vol48': 110, 'n_buy': 5,
                        'sellable_count': 4}]}
RUNQ = {'queue': [], 'summary': {'ingame': 1}}
LIMITS = {'plat': 1220, 'account': 'Tester', 'trades_left': 6, 'trade_cap': 20}


def open_session(data_dir, monkeypatch):
    ts = load_script('trade_session', monkeypatch=monkeypatch)
    write_json(os.path.join(str(data_dir), 'report.json'), REPORT)
    write_json(os.path.join(str(data_dir), 'plat_history.json'),
               [{'ts': int(time.time()) - 600, 'plat': 1200}, {'ts': int(time.time()), 'plat': 1220}])
    out = ts.start_payload(str(data_dir), PLAN, ADVISOR, REPORT, RUNQ, limits=LIMITS)
    assert out['started']
    return ts, out['session']['id']


# --------------------------------------------------------------------------- the store
def test_contact_marks_the_row_and_opens_one_pending_trade(ts, data_dir):
    ts.start_payload(str(data_dir), PLAN, ADVISOR, REPORT, RUNQ, limits=LIMITS)
    doc = ts.load(str(data_dir))
    pend = ts.contact(doc, 'primed_continuity', rank=0, qty=3, price=48, buyer='Wombat',
                      inv_before=4, plat_before=1220)
    assert pend['state'] == ts.CONTACTED and pend['id'].startswith('p-')
    assert pend['inv_before'] == 4 and pend['plat_before'] == 1220 and pend['qty'] == 3
    assert doc['session']['queue'][0]['state'] == ts.CONTACTED


def test_contacting_the_same_buyer_again_updates_instead_of_stacking(ts, data_dir):
    ts.start_payload(str(data_dir), PLAN, ADVISOR, REPORT, RUNQ, limits=LIMITS)
    doc = ts.load(str(data_dir))
    a = ts.contact(doc, 'primed_continuity', rank=0, price=48, buyer='Wombat', inv_before=4)
    b = ts.contact(doc, 'primed_continuity', rank=0, price=48, buyer='Wombat', inv_before=4)
    assert a['id'] == b['id'] and len(doc['pending']) == 1
    c = ts.contact(doc, 'primed_continuity', rank=0, price=48, buyer='Someone Else', inv_before=4)
    assert c['id'] != a['id'] and len(doc['pending']) == 2


def test_contact_works_without_a_session_and_keeps_the_used_info(ts, data_dir):
    doc = ts.empty()
    pend = ts.contact(doc, 'shredder', rank=5, qty=6, price=8, buyer='Wombat', inv_before=None)
    assert pend['session_id'] is None and pend['inv_before'] is None
    assert pend['name'] == 'shredder' and pend['expected_plat'] == 8


# --------------------------------------------------------------------------- the whisper funnel
def test_a_sent_whisper_opens_the_pending_trade(srv, data_dir, monkeypatch):
    ts, sid = open_session(data_dir, monkeypatch)
    code, out = srv.whisper_post({'item': 'primed_continuity', 'user': 'Wombat', 'price': 48,
                                  'kind': 'sell', 'mode': 'send', 'rank': 0})
    assert code == 200 and out['ok'] and out['sent'] is True
    assert out['contact']['buyer'] == 'Wombat' and out['contact']['session_id'] == sid
    assert out['contact']['inv_before'] == 4 and out['contact']['plat_before'] == 1220
    stored = read_json(os.path.join(str(data_dir), 'trade_session.json'))
    assert len(stored['pending']) == 1
    assert stored['pending'][0]['slug'] == 'primed_continuity'
    assert stored['session']['queue'][0]['state'] == 'CONTACTED'


def test_the_whisper_contract_is_untouched(srv, data_dir, monkeypatch):
    open_session(data_dir, monkeypatch)
    code, out = srv.whisper_post({'item': 'primed_continuity', 'user': 'Wombat', 'price': 48,
                                  'kind': 'sell', 'mode': 'send', 'rank': 0})
    for key in ('ok', 'message', 'line', 'copied', 'sent', 'reason'):
        assert key in out


def test_a_copied_whisper_is_not_a_contact(srv, data_dir, monkeypatch):
    open_session(data_dir, monkeypatch)
    code, out = srv.whisper_post({'item': 'primed_continuity', 'user': 'Wombat', 'price': 48,
                                  'kind': 'sell', 'mode': 'copy', 'rank': 0})
    assert code == 200 and out['copied'] is True
    assert 'contact' not in out
    assert read_json(os.path.join(str(data_dir), 'trade_session.json'))['pending'] == []


def test_a_whisper_that_never_reached_the_game_is_not_a_contact(srv, data_dir, monkeypatch):
    open_session(data_dir, monkeypatch)
    FAKE.sent = False
    code, out = srv.whisper_post({'item': 'primed_continuity', 'user': 'Wombat', 'price': 48,
                                  'kind': 'sell', 'mode': 'send', 'rank': 0})
    assert code == 200 and out['sent'] is False and out['reason'] == 'game not running'
    assert 'contact' not in out
    assert read_json(os.path.join(str(data_dir), 'trade_session.json'))['pending'] == []


def test_with_no_session_open_nothing_is_recorded(srv, data_dir):
    code, out = srv.whisper_post({'item': 'primed_continuity', 'user': 'Wombat', 'price': 48,
                                  'kind': 'sell', 'mode': 'send', 'rank': 0})
    assert code == 200 and out['sent'] is True and 'contact' not in out
    assert not os.path.exists(os.path.join(str(data_dir), 'trade_session.json'))


def test_a_broken_session_store_never_fails_the_whisper(srv, data_dir, monkeypatch):
    open_session(data_dir, monkeypatch)
    with open(os.path.join(str(data_dir), 'trade_session.json'), 'w', encoding='utf-8') as fh:
        fh.write('{ not json at all')
    code, out = srv.whisper_post({'item': 'primed_continuity', 'user': 'Wombat', 'price': 48,
                                  'kind': 'sell', 'mode': 'send', 'rank': 0})
    assert code == 200 and out['ok'] is True and out['sent'] is True


def test_whisper_refusals_are_unchanged(srv, data_dir, monkeypatch):
    open_session(data_dir, monkeypatch)
    code, out = srv.whisper_post({'item': 'primed_continuity', 'user': '', 'price': 48,
                                  'kind': 'sell', 'mode': 'send'})
    assert code == 400 and out['ok'] is False
    code, out = srv.whisper_post({'item': 'primed_continuity', 'user': 'Wombat', 'price': 0,
                                  'kind': 'sell', 'mode': 'send'})
    assert code == 400
    code, out = srv.whisper_post({'item': 'primed_continuity', 'user': 'Wombat', 'price': 48,
                                  'kind': 'sell', 'mode': 'send'})
    assert code == 200
    code, out = srv.whisper_post({'item': 'primed_continuity', 'user': 'Wombat', 'price': 48,
                                  'kind': 'sell', 'mode': 'send'})
    assert code == 429 and 'reason' in out


# --------------------------------------------------------------------------- the explicit route
def test_the_contact_route_takes_a_queue_row_to_contacted(srv, data_dir, monkeypatch):
    open_session(data_dir, monkeypatch)
    code, out = srv.session_post('contact', {'slug': 'primed_continuity', 'rank': 0, 'qty': 3,
                                             'price': 48, 'user': 'Wombat'})
    assert code == 200 and out['pending']['state'] == 'CONTACTED'
    assert out['pending']['inv_before'] == 4
    assert out['session_payload']['pending'][0]['id'] == out['pending']['id']
    assert out['session_payload']['focus']['state'] == 'CONTACTED'


def test_the_contact_route_refuses_nonsense(srv, data_dir, monkeypatch):
    open_session(data_dir, monkeypatch)
    assert srv.session_post('contact', {})[0] == 400
    assert srv.session_post('contact', {'slug': 'x', 'rank': 'ten'})[0] == 400


def test_pending_shows_up_on_the_session_payload_and_survives_a_reload(srv, data_dir, monkeypatch):
    open_session(data_dir, monkeypatch)
    srv.session_post('contact', {'slug': 'primed_continuity', 'rank': 0, 'user': 'Wombat'})
    first = srv.session_payload()
    fresh = load_script('server', monkeypatch=monkeypatch, env={'WFM_PORT': '0'})
    monkeypatch.setattr(fresh, 'DATA', str(data_dir))
    assert first['pending'][0]['buyer'] == 'Wombat'
    assert fresh.session_payload()['pending'][0]['id'] == first['pending'][0]['id']
