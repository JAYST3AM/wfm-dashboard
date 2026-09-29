"""Trading Session, stage 5 — the canonical confirm transaction.

docs/trading-session-workflow.md §5, §11 and §13 items 13-18. One atomic, idempotent transaction
writes the trade (with an id), closes the pending row, moves the session on, and lets the derived
stores recompute from that one event. A double click, a retry or a reloaded page must never log the
same trade twice - that is what the ids are for.
"""
import json
import os
import time

import pytest

from conftest import load_script, read_json, write_json


@pytest.fixture
def ts(monkeypatch):
    return load_script('trade_session', monkeypatch=monkeypatch)


def open_session(ts, data_dir, monkeypatch=None, slug='primed_continuity', price=48, qty=3):
    plan = {'plan': [{'slug': slug, 'name': slug.replace('_', ' ').title(), 'per_trade': qty,
                      'price': price, 'lane': 'rank 0'}]}
    report = {'sell_now': [{'slug': slug, 'name': slug.title(), 'lane_rank': 0, 'sellable_count': 4,
                            'vol48': 110, 'n_buy': 5, 'lane_ask': price}]}
    out = ts.start_payload(str(data_dir), plan, {}, report, {}, limits={'plat': 1220})
    assert out['started']
    return out['session']['id']


def pending_for(ts, data_dir, slug='primed_continuity', **over):
    doc = ts.load(str(data_dir))
    p = ts.contact(doc, slug, rank=0, qty=over.get('qty', 1), price=over.get('price', 48),
                   buyer='Wombat', inv_before=4, plat_before=1220)
    ts.save(str(data_dir), doc)
    return p


def log_of(data_dir):
    return read_json(os.path.join(str(data_dir), 'trade_log.json'))


# --------------------------------------------------------------------------- the transaction
def test_confirm_writes_one_trade_with_an_id(ts, data_dir):
    open_session(ts, data_dir)
    p = pending_for(ts, data_dir)
    out, created = ts.confirm(str(data_dir), ts.trade_draft(p, plat=48))
    assert created is True and out['ok'] is True and out['already'] is False
    log = log_of(data_dir)
    assert len(log) == 1 and log[0]['id'] == out['trade']['id'] and log[0]['plat'] == 48
    assert log[0]['source'] == 'session' and log[0]['pending_id'] == p['id']
    assert not os.path.exists(os.path.join(str(data_dir), 'trade_log.json.tmp'))


def test_confirming_the_same_trade_twice_changes_nothing(ts, data_dir):
    open_session(ts, data_dir)
    p = pending_for(ts, data_dir)
    draft = ts.trade_draft(p, plat=48)
    first, created = ts.confirm(str(data_dir), draft)
    again, created2 = ts.confirm(str(data_dir), draft)
    assert created is True and created2 is False
    assert again['already'] is True and again['trade']['id'] == first['trade']['id']
    assert len(log_of(data_dir)) == 1
    assert read_json(os.path.join(str(data_dir), 'trade_session.json'))['session']['totals']['trades'] == 1


def test_confirm_closes_the_pending_row_and_moves_the_session_on(ts, data_dir):
    sid = open_session(ts, data_dir)
    p = pending_for(ts, data_dir)
    ts.confirm(str(data_dir), ts.trade_draft(p, plat=48))
    doc = ts.load(str(data_dir))
    assert doc['pending'][0]['state'] == ts.COMPLETED
    assert doc['pending'][0]['completed_trade'] == doc['session']['done'][0]['id']
    assert doc['session']['queue'][0]['state'] == ts.COMPLETED
    assert doc['session']['totals'] == {'trades': 1, 'earned_plat': 48.0, 'skipped': 0, 'held': 0}
    assert doc['session']['done'][0]['buyer'] == 'Wombat'
    assert doc['session']['id'] == sid and doc['session']['plat_start'] == 1220


def test_the_summary_follows_the_confirmation(ts, data_dir):
    open_session(ts, data_dir)
    p = pending_for(ts, data_dir)
    ts.confirm(str(data_dir), ts.trade_draft(p, plat=48))
    s = ts.summary(ts.load(str(data_dir)), limits={'plat': 1268, 'trades_left': 5})
    assert s['trades'] == 1 and s['earned_plat'] == 48.0 and s['average_plat'] == 48.0
    assert s['plat_now'] == 1268 and s['trades_left_today'] == 5


def test_a_multi_copy_confirmation_earns_the_total(ts, data_dir):
    open_session(ts, data_dir, qty=3)
    p = pending_for(ts, data_dir, qty=3)
    out, _ = ts.confirm(str(data_dir), ts.trade_draft(p, plat=48))
    assert out['trade']['qty'] == 3
    assert log_of(data_dir)[0]['plat'] == 48, 'plat is the price per copy'
    assert log_of(data_dir)[0]['total'] == 144, 'total is the money for the trade'
    assert ts.summary(ts.load(str(data_dir)))['earned_plat'] == 144.0


def test_a_manual_sale_with_no_session_and_no_pending_still_logs(ts, data_dir):
    out, created = ts.confirm(str(data_dir), {'slug': 'shredder', 'rank': 5, 'qty': 2, 'plat': 16,
                                              'user': 'Wombat', 'source': 'manual'})
    assert created is True and out['ok'] is True
    log = log_of(data_dir)
    assert len(log) == 1 and log[0]['slug'] == 'shredder' and log[0]['kind'] == 'sale'
    stored = read_json(os.path.join(str(data_dir), 'trade_session.json'))
    assert stored['session'] is None                 # no session to move
    assert stored['confirmed'] == [log[0]['id']]     # the id is remembered, so a retry is a no-op


def test_a_purchase_is_logged_as_a_purchase(ts, data_dir):
    out, _ = ts.confirm(str(data_dir), {'slug': 'shredder', 'kind': 'purchase', 'qty': 1, 'plat': 8})
    assert log_of(data_dir)[0]['kind'] == 'purchase'


def test_a_bad_kind_falls_back_to_sale_never_to_a_500(ts, data_dir):
    out, _ = ts.confirm(str(data_dir), {'slug': 'shredder', 'kind': 'shouting', 'plat': 8})
    assert out['ok'] is True and log_of(data_dir)[0]['kind'] == 'sale'


# --------------------------------------------------------------------------- refusals
def test_confirm_refuses_bad_input_and_writes_nothing(ts, data_dir):
    for rec in ({}, {'slug': ''}, {'slug': 'x', 'qty': 'lots'}, {'slug': 'x', 'plat': 'free'},
                {'slug': 'x', 'plat': -5}):
        out, created = ts.confirm(str(data_dir), rec)
        assert out['ok'] is False and created is False
    assert not os.path.exists(os.path.join(str(data_dir), 'trade_log.json'))


def test_a_confirmed_id_is_never_written_twice_even_after_a_reload(ts, data_dir, monkeypatch):
    open_session(ts, data_dir)
    p = pending_for(ts, data_dir)
    draft = ts.trade_draft(p, plat=48)
    ts.confirm(str(data_dir), draft)
    fresh = load_script('trade_session', monkeypatch=monkeypatch)
    again, created = fresh.confirm(str(data_dir), draft)
    assert created is False and again['already'] is True
    assert len(log_of(data_dir)) == 1


def test_an_explicit_id_is_respected(ts, data_dir):
    out, _ = ts.confirm(str(data_dir), {'id': 't-mine-123456', 'slug': 'x', 'plat': 5})
    assert out['trade']['id'] == 't-mine-123456'


# --------------------------------------------------------------------------- data safety
def test_a_corrupt_trade_log_is_quarantined_not_clobbered(ts, data_dir):
    path = os.path.join(str(data_dir), 'trade_log.json')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('[{"slug": "half')
    out, created = ts.confirm(str(data_dir), {'slug': 'x', 'plat': 5})
    assert created is True and log_of(data_dir)[0]['slug'] == 'x'
    assert any(p.startswith('trade_log.json.corrupt-') for p in os.listdir(str(data_dir)))


def test_append_event_is_the_single_writer_and_dedupes(ts, data_dir):
    rec, created = ts.append_event(str(data_dir), {'slug': 'x', 'plat': 5, 'ts': 1000})
    same, created2 = ts.append_event(str(data_dir), {'slug': 'x', 'plat': 5, 'ts': 1000})
    assert created is True and created2 is False and same['id'] == rec['id']
    assert len(log_of(data_dir)) == 1


def test_the_confirm_result_is_json_safe(ts, data_dir):
    open_session(ts, data_dir)
    p = pending_for(ts, data_dir)
    out, _ = ts.confirm(str(data_dir), ts.trade_draft(p, plat=48))
    json.dumps(out)                                  # the route serialises this


# ------------------------------------------------------------------- the record's downstream
def test_the_record_is_the_shape_every_reader_already_reads(ts, data_dir, monkeypatch):
    """server.trades_payload, session_stats and plat_ledger all sum `total`. A session trade that
    only carried `plat` (as the money) vanished from every earnings figure in the app."""
    open_session(ts, data_dir, qty=3)
    p = pending_for(ts, data_dir, qty=3)
    ts.confirm(str(data_dir), ts.trade_draft(p, plat=48))
    row = log_of(data_dir)[0]
    for k in ('id', 'ts', 'kind', 'name', 'qty', 'plat', 'total', 'src'):
        assert k in row, 'trade_log rows must carry %s' % k
    assert row['kind'] == 'sale' and row['qty'] == 3
    assert row['plat'] == 48 and row['total'] == 144

    ledger = load_script('plat_ledger', monkeypatch=monkeypatch)
    assert ledger.trade_totals(log_of(data_dir))['earned'] == 144
    srv = load_script('server', monkeypatch=monkeypatch)
    monkeypatch.setattr(srv, 'DATA', str(data_dir))
    assert srv.trades_payload()['totals']['earned'] == 144


def test_a_record_that_gives_only_the_total_is_normalised(ts, data_dir):
    """Callers may send the money; the stored record still carries both numbers."""
    out, created = ts.confirm(str(data_dir), {'slug': 'shredder', 'qty': 4, 'total': 100})
    assert created is True
    row = log_of(data_dir)[0]
    assert row['total'] == 100 and row['plat'] == 25


# ------------------------------------------------------------------- the recoverable confirm
def test_the_intent_is_durable_before_the_trade_is_written(ts, data_dir, monkeypatch):
    """The two files cannot be written together, so the intent goes first: if the append never
    lands, the next load sees an intent with no trade and claims nothing."""
    open_session(ts, data_dir)
    p = pending_for(ts, data_dir)
    draft = ts.trade_draft(p, plat=48)
    original = ts.append_event

    def boom(*a, **k):
        raise OSError('disk full')

    monkeypatch.setattr(ts, 'append_event', boom)
    with pytest.raises(OSError):
        ts.confirm(str(data_dir), draft)
    raw = read_json(os.path.join(str(data_dir), 'trade_session.json'))
    assert raw['confirming']['id'] == draft['id'], 'the intent must be durable before the append'
    assert not os.path.exists(os.path.join(str(data_dir), 'trade_log.json')), 'no trade was written'

    monkeypatch.setattr(ts, 'append_event', original)
    doc = ts.load(str(data_dir))
    assert doc['recovered']['result'] == 'rolled back'
    assert doc['pending'][0]['state'] == ts.CONTACTED
    out, created = ts.confirm(str(data_dir), draft)         # and it still works afterwards
    assert created is True and len(log_of(data_dir)) == 1


def test_a_confirm_that_died_after_the_trade_landed_finishes_itself(ts, data_dir):
    """The other half of the window: the sale is in the log, the session never heard about it."""
    open_session(ts, data_dir)
    p = pending_for(ts, data_dir)
    draft = ts.trade_draft(p, plat=48)
    ts.append_event(str(data_dir), draft)
    doc = ts.load(str(data_dir))
    doc['confirming'] = {'id': draft['id'], 'rec': draft, 'ts': int(time.time())}
    ts.save(str(data_dir), doc)

    doc2 = ts.load(str(data_dir))
    assert doc2['recovered']['result'] == 'finished'
    assert doc2.get('confirming') is None
    assert doc2['pending'][0]['state'] == ts.COMPLETED
    assert doc2['session']['totals']['trades'] == 1
    assert doc2['session']['totals']['earned_plat'] == 48.0
    assert draft['id'] in doc2['confirmed']

    again, created = ts.confirm(str(data_dir), draft)        # a replay settles nothing twice
    assert created is False and again['already'] is True
    assert ts.load(str(data_dir))['session']['totals']['trades'] == 1
    assert len(log_of(data_dir)) == 1


def test_recovery_only_touches_the_side_that_did_not_happen(ts, data_dir):
    """A rolled-back intent leaves the pending row and the queue exactly as they were."""
    open_session(ts, data_dir)
    p = pending_for(ts, data_dir)
    draft = ts.trade_draft(p, plat=48)
    before = ts.load(str(data_dir))
    before['confirming'] = {'id': draft['id'], 'rec': draft, 'ts': int(time.time())}
    ts.save(str(data_dir), before)
    after = ts.load(str(data_dir))
    assert after['pending'][0]['state'] == before['pending'][0]['state'] == ts.CONTACTED
    assert after['session']['queue'][0]['state'] == before['session']['queue'][0]['state']
    assert after['session']['totals']['trades'] == 0
    assert after['session']['cursor'] == before['session']['cursor']
