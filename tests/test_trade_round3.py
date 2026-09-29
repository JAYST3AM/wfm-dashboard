"""Round 3: the counterexamples the outside review asked for.

Nine cases, each one a way the loop could have double-counted, over-claimed or confused two lanes:
an evicted id, two simultaneous confirms, a record written without its money, a legacy record, two
ranks of one item, two refinements of one relic, an unverifiable buyer, whole-item evidence for a
narrow lane, and one movement watched by two pending trades.
"""
import io
import json
import os
import threading
import time

import pytest

from conftest import load_script, read_json, write_json


@pytest.fixture
def ts(monkeypatch):
    return load_script('trade_session', monkeypatch=monkeypatch)


def session_with(ts, data_dir, plan=None, report=None, runqueue=None):
    plan = plan or {'plan': [{'slug': 'primed_continuity', 'name': 'Primed Continuity',
                              'per_trade': 3, 'price': 48, 'lane': 'rank 0'}]}
    report = report or {'sell_now': [{'slug': 'primed_continuity', 'lane_rank': 0,
                                      'sellable_count': 4, 'vol48': 110, 'n_buy': 5, 'lane_ask': 48}]}
    out = ts.start_payload(str(data_dir), plan, {}, report, runqueue or {}, limits={'plat': 1220})
    assert out['started']
    return out


def contact(ts, data_dir, **over):
    doc = ts.load(str(data_dir))
    p = ts.contact(doc, over.pop('slug', 'primed_continuity'), rank=over.pop('rank', 0),
                   qty=over.pop('qty', 1), price=over.pop('price', 48), buyer='Wombat',
                   inv_before=over.pop('inv_before', 4), plat_before=over.pop('plat_before', 1220),
                   lane=over.pop('lane', None), **over)
    ts.save(str(data_dir), doc)
    return p


# --------------------------------------------------------------- 1. an evicted id
def test_an_id_evicted_from_the_visible_list_cannot_settle_twice(ts, data_dir):
    """The capped `confirmed` list is for display; idempotency may not depend on it.

    `settled` is uncapped, so a retry of a trade whose id has fallen out of the visible list still
    settles once. Without it the retry would append nothing (the id is in the log) and then run the
    tail again - counting the sale, moving the cursor and closing the pending row a second time.
    """
    session_with(ts, data_dir)
    p = contact(ts, data_dir, qty=3, inv_before=6)
    rec = ts.trade_draft(p, plat=48)
    out, created = ts.confirm(str(data_dir), rec)
    assert created and out['ok']

    doc = ts.load(str(data_dir))
    first = dict(doc['session']['totals'])
    assert first['trades'] == 1 and first['earned_plat'] == 144
    # the visible list forgets the id (this is what the cap does)
    doc['confirmed'] = []
    ts.save(str(data_dir), doc)
    assert ts.load(str(data_dir))['settled'], 'the idempotency key must survive a save'

    again, created_again = ts.confirm(str(data_dir), rec)
    assert created_again is False and again.get('already') is True
    after = ts.load(str(data_dir))['session']['totals']
    assert after == first, 'a retry must not count the trade a second time'
    assert len(read_json(os.path.join(str(data_dir), 'trade_log.json'))) == 1


# --------------------------------------------------------------- 2. concurrent confirms
def test_two_simultaneous_confirms_settle_exactly_once(ts, data_dir):
    """The server is a ThreadingHTTPServer: two Confirm clicks arrive together."""
    session_with(ts, data_dir)
    p = contact(ts, data_dir, qty=3, inv_before=6)
    rec = ts.trade_draft(p, plat=48)
    results, errors = [], []

    def run():
        try:
            results.append(ts.confirm(str(data_dir), dict(rec)))
        except Exception as e:                       # pragma: no cover - a failure to report
            errors.append(repr(e))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert not errors, errors
    assert len(results) == 2
    log = read_json(os.path.join(str(data_dir), 'trade_log.json'))
    assert len(log) == 1, 'one trade, not two'
    doc = ts.load(str(data_dir))
    assert doc['session']['totals']['trades'] == 1
    assert doc['session']['totals']['earned_plat'] == 144
    assert len(doc['session']['done']) == 1
    assert [r for r in doc['session']['queue'] if r['state'] == ts.COMPLETED]
    assert len([x for x in doc['settled']]) == 1


# --------------------------------------------------------------- 3. the writer boundary
def test_a_sale_written_without_its_money_gets_one(ts, data_dir):
    """`append_event` is the single writer of trade_log: a caller that hands it a unit price and no
    money gets the money stored, so no reader ever sees an unsummable sale."""
    rec, created = ts.append_event(str(data_dir), {'kind': 'sale', 'slug': 'x', 'qty': 3, 'plat': 48})
    assert created and rec['plat'] == 48 and rec['total'] == 144 and rec['id']
    stored = read_json(os.path.join(str(data_dir), 'trade_log.json'))[0]
    assert stored['total'] == 144


def test_the_writer_refuses_a_sale_with_no_price_at_all(ts, data_dir):
    with pytest.raises(ValueError):
        ts.append_event(str(data_dir), {'kind': 'sale', 'slug': 'x', 'qty': 3})
    assert not os.path.exists(os.path.join(str(data_dir), 'trade_log.json'))


def test_a_legacy_record_still_reads_as_money_through_the_session(ts, data_dir):
    """Old-record compatibility: a pre-canonical sale (unit price in `plat`, no `total`) is still
    summed by the app's own readers, so historical money cannot disappear from a total."""
    write_json(os.path.join(str(data_dir), 'trade_log.json'),
               [{'ts': 1, 'kind': 'sale', 'name': 'Adaptation', 'qty': 4, 'plat': 15},
                {'ts': 2, 'kind': 'sale', 'name': 'Adaptation', 'qty': 1, 'plat': 15, 'total': 15}])
    assert ts.money_of({'kind': 'sale', 'qty': 4, 'plat': 15}) == 60
    events = read_json(os.path.join(str(data_dir), 'trade_log.json'))
    assert sum(ts.money_of(e) for e in events if e['kind'] == 'sale') == 75


# --------------------------------------------------------------- 4. two ranks, one slug
def test_two_ranks_of_one_item_never_share_a_buyer(ts, data_dir):
    """rank 0 and rank 6 of the same mod are two rows and two buyers."""
    plan = {'plan': [{'slug': 'primed_continuity', 'name': 'Primed Continuity', 'per_trade': 1,
                      'price': 48, 'lane': 'rank 0'},
                     {'slug': 'primed_continuity', 'name': 'Primed Continuity', 'per_trade': 1,
                      'price': 120, 'lane': 'rank 6'}]}
    report = {'sell_now': [{'slug': 'primed_continuity', 'lane_rank': 0, 'sellable_count': 4},
                           {'slug': 'primed_continuity', 'lane_rank': 6, 'sellable_count': 2}]}
    runqueue = {'summary': {'ingame': 1},
                'queue': [{'slug': 'primed_continuity', 'lane': 'rank 0', 'buyer': 'RankZero',
                           'buyer_status': 'ingame', 'buy_price': 48, 'qty': 1},
                          {'slug': 'primed_continuity', 'lane': 'rank 6', 'buyer': 'RankSix',
                           'buyer_status': 'ingame', 'buy_price': 120, 'qty': 1}]}
    q = ts.build_queue(plan, {}, report, runqueue)
    assert len(q) == 2, 'two lanes, two rows'
    assert q[0]['lane'] == 'rank 0' and q[0]['buyer']['user'] == 'RankZero'
    assert q[1]['lane'] == 'rank 6' and q[1]['buyer']['user'] == 'RankSix'
    assert ts.key_of(q[0]) != ts.key_of(q[1])


# --------------------------------------------------------------- 5. two refinements, one relic
def test_intact_and_radiant_relics_stay_distinct_end_to_end(ts, data_dir):
    """A relic's refinement is its lane: the queue, the pending trade, the check and the tail must
    all keep the two apart, or a Radiant sale closes the Intact row."""
    plan = {'plan': [{'slug': 'meso_i1_relic', 'name': 'Meso I1 Relic', 'per_trade': 6, 'price': 9,
                      'lane': 'intact', 'qty': 12},
                     {'slug': 'meso_i1_relic', 'name': 'Meso I1 Relic', 'per_trade': 1, 'price': 35,
                      'lane': 'radiant', 'qty': 3}]}
    report = {'sell_now': [{'slug': 'meso_i1_relic', 'sellable_count': 15}]}
    q = ts.build_queue(plan, {}, report, {})
    assert [r['lane'] for r in q] == ['intact', 'radiant']
    assert q[0]['rank'] is None and q[1]['rank'] is None
    assert ts.key_of(q[0]) == 'meso_i1_relic#intact'
    assert ts.key_of(q[1]) == 'meso_i1_relic#radiant'

    out = ts.start_payload(str(data_dir), plan, {}, report, {}, limits={'plat': 1220})
    assert out['started']
    p_i = contact(ts, data_dir, slug='meso_i1_relic', rank=None, qty=6, price=9, lane='intact',
                  inv_before=15)
    p_r = contact(ts, data_dir, slug='meso_i1_relic', rank=None, qty=1, price=35, lane='radiant',
                  inv_before=15)
    assert p_i['lane'] == 'intact' and p_r['lane'] == 'radiant'
    assert p_i['id'] != p_r['id']

    # only the radiant copy moved: 15 -> 14 copies, +35p against the radiant ask
    checks = ts.propose([p_i, p_r], {ts.key_of(p_i): 15, ts.key_of(p_r): 14}, 1255)
    verdicts = {c['pending_id']: c['verdict'] for c in checks['proposals']}
    assert verdicts[p_r['id']] in (ts.EXACT, ts.AMBIGUOUS)
    assert verdicts[p_i['id']] in (ts.NOTHING, ts.AMBIGUOUS, ts.UNKNOWN)
    assert verdicts[p_r['id']] != verdicts.get(p_i['id']) or verdicts[p_i['id']] == ts.AMBIGUOUS

    # confirming the radiant one closes only the radiant row
    rec = ts.trade_draft(p_r, plat=35)
    assert rec['lane'] == 'radiant'
    ts.confirm(str(data_dir), rec)
    doc = ts.load(str(data_dir))
    rows = {r['lane']: r['state'] for r in doc['session']['queue']}
    assert rows['radiant'] == ts.COMPLETED and rows['intact'] != ts.COMPLETED
    pend = {p['lane']: p['state'] for p in doc['pending']}
    assert pend['radiant'] == ts.COMPLETED and pend['intact'] == ts.CONTACTED


# --------------------------------------------------------------- 6. whole-item evidence
def test_a_narrow_lane_with_only_whole_item_evidence_is_ambiguous(ts):
    plan_lane_rank = {'lane': 'rank 0'}
    p = {'id': 'p-1', 'slug': 'primed_continuity', 'name': 'Primed Continuity', 'rank': 0,
         'qty': 3, 'expected_plat': 48, 'buyer': 'Wombat', 'kind': 'sell',
         'ts': int(time.time()) - 60, 'state': ts.CONTACTED, 'inv_before': 4, 'plat_before': 1220}
    key = ts.key_of(p)
    exact_shape = ts.propose([p], {key: 1}, 1364, inv_basis={key: 'lane'})
    assert exact_shape['proposals'][0]['verdict'] == ts.EXACT
    whole_item = ts.propose([p], {key: 1}, 1364, inv_basis={key: 'item'})
    got = whole_item['proposals'][0]
    assert got['verdict'] == ts.AMBIGUOUS, 'a rank lane cannot be verified from the item total'
    assert any('the whole item, not this lane' in x for x in got['evidence'])
    # a row with no lane and no rank is the item itself, so whole-item evidence is its own evidence
    plain = {k: v for k, v in p.items() if k not in ('rank', 'lane')}
    plain_key = ts.key_of(plain)
    assert ts.propose([plain], {plain_key: 1}, 1364,
                      inv_basis={plain_key: 'item'})['proposals'][0]['verdict'] == ts.EXACT


# --------------------------------------------------------------- 7. shared evidence
def test_two_pending_trades_cannot_both_claim_one_movement(ts):
    now = int(time.time())
    a = {'id': 'p-a', 'slug': 'primed_continuity', 'rank': 0, 'lane': 'rank 0', 'qty': 3,
         'expected_plat': 48, 'buyer': 'Wombat', 'ts': now - 60, 'state': ts.CONTACTED,
         'inv_before': 4, 'plat_before': 1220}
    b = dict(a, id='p-b')
    key = ts.key_of(a)
    out = ts.propose([a, b], {key: 1}, 1364, inv_basis={key: 'lane'})
    verdicts = [p['verdict'] for p in out['proposals']]
    assert verdicts == [ts.AMBIGUOUS, ts.AMBIGUOUS], 'one movement cannot satisfy two trades'
    assert all(any('cannot be split' in x for x in p['evidence']) for p in out['proposals'])

    # with only one watcher the same numbers are exact
    alone = ts.propose([a], {key: 1}, 1364, inv_basis={key: 'lane'})
    assert alone['proposals'][0]['verdict'] == ts.EXACT


# --------------------------------------------------------------- readers of a legacy record
def test_the_ledger_still_counts_a_record_written_before_the_canonical_shape(ts):
    """Old-record compatibility through a real reader: plat_ledger sums `total` and a pre-canonical
    sale has none - its unit price in `plat` is the money it moved. If the reader kept summing only
    `total`, that platinum would simply disappear from the ledger's totals."""
    ledger = load_script('plat_ledger')
    events = [{'ts': 1, 'kind': 'sale', 'name': 'Adaptation', 'qty': 4, 'plat': 15},
              {'ts': 2, 'kind': 'sale', 'name': 'Adaptation', 'qty': 1, 'plat': 15, 'total': 15},
              {'ts': 3, 'kind': 'purchase', 'name': 'Adaptation', 'qty': 2, 'plat': 9}]
    tot = ledger.trade_totals(events)
    assert tot['earned'] == 75 and tot['spent'] == 18


# --------------------------------------------------------------- the route, not just the function
def test_a_lane_rides_the_contact_route(ts, data_dir):
    """The panel posts the lane it is showing: two refinements of one relic share a slug, so without
    it the second contact would land on the first one's pending row."""
    plan = {'plan': [{'slug': 'meso_i1_relic', 'name': 'Meso I1 Relic', 'per_trade': 6, 'price': 9,
                      'lane': 'intact', 'qty': 12},
                     {'slug': 'meso_i1_relic', 'name': 'Meso I1 Relic', 'per_trade': 1, 'price': 35,
                      'lane': 'radiant', 'qty': 3}]}
    report = {'sell_now': [{'slug': 'meso_i1_relic', 'sellable_count': 15}]}
    assert ts.start_payload(str(data_dir), plan, {}, report, {}, limits={'plat': 1220})['started']
    doc = ts.load(str(data_dir))
    first = ts.contact(doc, 'meso_i1_relic', rank=None, qty=6, price=9, buyer='Wombat',
                       inv_before=15, plat_before=1220, lane='intact')
    second = ts.contact(doc, 'meso_i1_relic', rank=None, qty=1, price=35, buyer='Mesa',
                        inv_before=15, plat_before=1220, lane='radiant')
    ts.save(str(data_dir), doc)
    assert first['lane'] == 'intact' and second['lane'] == 'radiant'
    assert first['id'] != second['id'], 'the lane is part of a pending id'
    stored = ts.load(str(data_dir))
    assert len(stored['pending']) == 2, 'a second lane is a second contact, not an update of the first'
    rows = {r['lane']: r['state'] for r in stored['session']['queue']}
    assert rows == {'intact': ts.CONTACTED, 'radiant': ts.CONTACTED}
