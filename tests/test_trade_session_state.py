"""Trading Session, stage 2 — the persisted session, its queue and its lifecycle.

The store carries money and inventory history, so these tests pin the boring guarantees: the queue
is built from the payloads the app already produces, ranks are never crossed, a skip moves the
session on while a hold does not, nothing is written by a read, and a half-written state file is
quarantined instead of clobbered (docs/trading-session-workflow.md §11, §13 items 1, 2, 5, 19, 21).
"""
import json
import os
import time

import pytest

from conftest import load_script, read_json, write_json


@pytest.fixture
def ts(monkeypatch):
    return load_script('trade_session', monkeypatch=monkeypatch)


def plan_doc(**rows):
    base = {'generated': int(time.time()), 'dry_run': True, 'account': 'Tester',
            'plan': [{'slug': 'primed_continuity', 'name': 'Primed Continuity', 'qty': 3,
                      'per_trade': 3, 'price': 48, 'lane': 'rank 0', 'vol48': 110,
                      'med': 85.5, 'note': 'rank 0 · 1 in use'},
                     {'slug': 'shredder', 'name': 'Shredder', 'qty': 6, 'per_trade': 6,
                      'price': 8, 'lane': 'rank 5', 'vol48': 0, 'med': None}]}
    base.update(rows)
    return base


def advisor_doc():
    return {'generated': '2026-09-26 12:53', 'ranked': ['enhanced_vitality', 'shredder'],
            'counts': {'list': 2}, 'top': [],
            'items': {'enhanced_vitality': {'item': 'enhanced_vitality', 'name': 'Enhanced Vitality',
                                            'cat': 'mod', 'owned': 41, 'equipped': 1, 'reserved': 1,
                                            'sellable': 39, 'market_price': 25.0, 'median': 3.0,
                                            'lane_rank': 8, 'vol48': 2, 'price_trend_pct': 8.0,
                                            'liquidity': 'low', 'recommendation': 'list',
                                            'recommended_quantity': 1, 'recommended_price': 25.0,
                                            'reasons': ['keep 1 for collection']},
                      'shredder': {'item': 'shredder', 'name': 'Shredder', 'cat': 'mod', 'owned': 88,
                                   'sellable': 87, 'lane_rank': 5, 'vol48': 0,
                                   'recommendation': 'hold', 'recommended_price': 8}}}


def report_doc():
    return {'generated': '2026-09-26 02:39', 'sell_now': [
        {'slug': 'primed_continuity', 'name': 'Primed Continuity', 'cat': 'mod', 'count': 5,
         'wts': 90, 'wtb': 100, 'med': 85.5, 'lane_rank': 0, 'lane_ask': 90, 'lane_bid': 100,
         'mn48': 48.0, 'mx48': 120.0, 'n_sell': 5, 'n_buy': 5, 'vol48': 110,
         'sellable_count': 4, 'in_use_count': 1},
        {'slug': 'shredder', 'name': 'Shredder', 'cat': 'mod', 'count': 88, 'wts': 8, 'wtb': None,
         'lane_rank': 5, 'lane_ask': 8, 'n_sell': 5, 'n_buy': 0, 'vol48': 0,
         'sellable_count': 87, 'in_use_count': 1}]}


def runqueue_doc(**over):
    row = {'slug': 'primed_continuity', 'name': 'Primed Continuity', 'qty': 3, 'my_price': 48,
           'buyer': 'WouldYouMeowBack', 'buyer_status': 'ingame', 'buy_price': 71,
           'why': 'ingame · pays 71p'}
    row.update(over.pop('row', {}))
    base = {'generated': int(time.time()), 'queue': [row],
            'summary': {'ingame': 4, 'online': 0, 'offline': 5, 'total': 9}}
    base.update(over)
    return base


# --------------------------------------------------------------------------- the queue
def test_queue_follows_the_plan_order_then_the_advisor(ts):
    q = ts.build_queue(plan_doc(), advisor_doc(), report_doc(), runqueue_doc())
    assert [r['slug'] for r in q] == ['primed_continuity', 'shredder', 'enhanced_vitality']
    assert q[0]['source'] == 'plan' and q[2]['source'] == 'advisor'
    assert q[0]['name'] == 'Primed Continuity' and q[0]['qty'] == 3 and q[0]['price'] == 48


def test_queue_dedupes_by_slug_and_rank(ts):
    plan = plan_doc()
    plan['plan'] = plan['plan'] + [{'slug': 'primed_continuity', 'name': 'Primed Continuity',
                                    'per_trade': 1, 'price': 48, 'lane': 'rank 0'}]
    q = ts.build_queue(plan, advisor_doc(), report_doc(), runqueue_doc())
    assert [r['slug'] for r in q].count('primed_continuity') == 1


def test_queue_keeps_both_ranks_of_one_item_apart(ts):
    plan = plan_doc()
    plan['plan'] = [{'slug': 'primed_continuity', 'name': 'Primed Continuity', 'per_trade': 1,
                     'price': 48, 'lane': 'rank 0'},
                    {'slug': 'primed_continuity', 'name': 'Primed Continuity', 'per_trade': 1,
                     'price': 120, 'lane': 'rank 10'}]
    q = ts.build_queue(plan, advisor_doc(), report_doc(), runqueue_doc())
    assert [(r['slug'], r['rank']) for r in q][:2] == [('primed_continuity', 0),
                                                       ('primed_continuity', 10)]
    assert q[0]['price'] == 48 and q[1]['price'] == 120
    assert ts.row_key(*[q[0]['slug'], q[0]['rank']]) != ts.row_key(*[q[1]['slug'], q[1]['rank']])


def test_a_rank_10_stack_never_gets_a_rank_0_buyer(ts):
    plan = plan_doc()
    plan['plan'] = [{'slug': 'primed_continuity', 'name': 'Primed Continuity', 'per_trade': 1,
                     'price': 120, 'lane': 'rank 10'}]
    q = ts.build_queue(plan, advisor_doc(), report_doc(), runqueue_doc(row={'rank': 0}))
    assert q[0]['rank'] == 10
    assert q[0]['buyer'] is None
    assert 'rank 0' in q[0]['why']['rank_mismatch']


def test_a_matching_rank_keeps_the_buyer(ts):
    plan = plan_doc()
    plan['plan'] = [{'slug': 'primed_continuity', 'name': 'Primed Continuity', 'per_trade': 1,
                     'price': 48, 'lane': 'rank 0'}]
    q = ts.build_queue(plan, advisor_doc(), report_doc(), runqueue_doc(row={'rank': 0}))
    assert q[0]['buyer']['user'] == 'WouldYouMeowBack'
    assert q[0]['buyer']['status'] == 'ingame'
    assert q[0]['confidence']['level'] == 'high'
    assert any('buyer' in r for r in q[0]['confidence']['reasons'])


def test_rows_without_a_price_or_a_sellable_copy_are_not_queued(ts):
    plan = {'plan': [{'slug': 'no_price', 'name': 'No Price', 'per_trade': 1, 'lane': 'rank 0'},
                     {'slug': 'nothing_to_sell', 'name': 'Nothing', 'per_trade': 4, 'price': 5,
                      'lane': 'rank 0'}]}
    report = {'sell_now': [{'slug': 'nothing_to_sell', 'name': 'Nothing', 'lane_rank': 0,
                            'sellable_count': 0, 'vol48': 0}]}
    q = ts.build_queue(plan, {}, report, {})
    assert q == []


def test_why_only_carries_facts_that_exist(ts):
    q = ts.build_queue(plan_doc(), advisor_doc(), report_doc(), runqueue_doc())
    why = q[0]['why']
    assert why['safe_copies'] == 4 and why['sales_48h'] == 110 and why['buyers_online'] == 4
    assert 'week_pct' not in why          # no trend in this fixture -> omitted, never guessed


# --------------------------------------------------------------------------- lifecycle
def test_start_opens_a_session_with_a_stable_id(ts, data_dir):
    out = ts.start_payload(str(data_dir), plan_doc(), advisor_doc(), report_doc(), runqueue_doc(),
                           limits={'plat': 1220, 'account': 'Tester', 'trades_left': 6,
                                   'trade_cap': 20})
    assert out['ok'] and out['started']
    s = out['session']
    assert s['id'].startswith('s-') and s['plat_start'] == 1220 and s['account'] == 'Tester'
    assert len(s['queue']) == 3 and s['cursor'] == 0 and s['ended_ts'] is None
    assert read_json(os.path.join(str(data_dir), 'trade_session.json'))['session']['id'] == s['id']


def test_start_twice_never_replaces_the_live_session(ts, data_dir):
    first = ts.start_payload(str(data_dir), plan_doc(), advisor_doc(), report_doc(), runqueue_doc())
    again = ts.start_payload(str(data_dir), plan_doc(), advisor_doc(), report_doc(), runqueue_doc())
    assert again['ok'] and again['started'] is False
    assert again['session']['id'] == first['session']['id']
    assert 'already open' in again['reason']


def test_start_with_nothing_to_sell_answers_cleanly(ts, data_dir):
    out = ts.start_payload(str(data_dir), {}, {}, {}, {})
    assert out['ok'] is False and 'nothing to sell' in out['error']
    assert not os.path.exists(os.path.join(str(data_dir), 'trade_session.json'))


def test_skip_moves_on_and_hold_stays(ts, data_dir):
    ts.start_payload(str(data_dir), plan_doc(), advisor_doc(), report_doc(), runqueue_doc())
    doc = ts.load(str(data_dir))
    assert ts.set_state(doc, 'primed_continuity', rank=0, state=ts.SKIPPED)['state'] == ts.SKIPPED
    assert doc['session']['cursor'] == 1
    assert doc['session']['totals']['skipped'] == 1
    assert ts.set_state(doc, 'shredder', rank=5, state=ts.HELD)['state'] == ts.HELD
    assert doc['session']['cursor'] == 1        # a hold does not advance
    assert doc['session']['totals']['held'] == 1
    ts.save(str(data_dir), doc)
    assert ts.load(str(data_dir))['session']['totals'] == {'trades': 0, 'earned_plat': 0,
                                                          'skipped': 1, 'held': 1}


def test_focus_by_index_and_by_slug(ts, data_dir):
    ts.start_payload(str(data_dir), plan_doc(), advisor_doc(), report_doc(), runqueue_doc())
    doc = ts.load(str(data_dir))
    assert ts.focus(doc, index=2)['slug'] == 'enhanced_vitality'
    assert ts.focus(doc, slug='shredder')['slug'] == 'shredder'
    assert doc['session']['cursor'] == 1


def test_summary_counts_only_what_happened(ts, data_dir):
    ts.start_payload(str(data_dir), plan_doc(), advisor_doc(), report_doc(), runqueue_doc())
    doc = ts.load(str(data_dir))
    s = doc['session']
    s['done'] = [{'id': 't-1', 'slug': 'primed_continuity', 'plat': 48, 'qty': 1}]
    s['queue'][0]['state'] = ts.COMPLETED
    s['totals'] = {'trades': 1, 'earned_plat': 48, 'skipped': 0, 'held': 0}
    out = ts.summary(doc, limits={'trades_left': 5, 'trade_cap': 20, 'plat': 1268})
    assert out['trades'] == 1 and out['earned_plat'] == 48 and out['average_plat'] == 48.0
    assert out['queue_remaining'] == 2 and out['trades_left_today'] == 5
    assert out['best']['plat'] == 48 and out['complete'] is False


def test_end_keeps_the_session_as_history(ts, data_dir):
    ts.start_payload(str(data_dir), plan_doc(), advisor_doc(), report_doc(), runqueue_doc())
    doc = ts.load(str(data_dir))
    ts.end(doc, now=doc['session']['started_ts'] + 4320)
    ts.save(str(data_dir), doc)
    s = ts.load(str(data_dir))['session']
    assert s['ended_ts'] and s['queue']           # closed, queue intact
    assert ts.summary(ts.load(str(data_dir)))['active'] is False
    assert ts.summary(ts.load(str(data_dir)))['seconds'] == 4320


# --------------------------------------------------------------------------- persistence + safety
def test_state_survives_a_reload_and_a_restart(ts, data_dir, monkeypatch):
    started = ts.start_payload(str(data_dir), plan_doc(), advisor_doc(), report_doc(),
                               runqueue_doc())['session']
    doc = ts.load(str(data_dir))
    ts.set_state(doc, 'primed_continuity', rank=0, state=ts.SKIPPED)
    ts.save(str(data_dir), doc)
    fresh = load_script('trade_session', monkeypatch=monkeypatch)      # a new process, same disk
    again = fresh.load(str(data_dir))
    assert again['session']['id'] == started['id']
    assert again['session']['started_ts'] == started['started_ts']
    assert again['session']['cursor'] == 1 and again['session']['totals']['skipped'] == 1
    assert len(again['session']['queue']) == 3


def test_a_half_written_state_file_is_quarantined_not_clobbered(ts, data_dir):
    path = os.path.join(str(data_dir), 'trade_session.json')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('{"session": {"id": "s-broken", "queue": [')
    doc = ts.load(str(data_dir))
    assert doc['session'] is None and doc['pending'] == []
    assert not os.path.exists(path)                       # moved aside
    kept = [p for p in os.listdir(str(data_dir)) if p.startswith('trade_session.json.corrupt-')]
    assert len(kept) == 1
    assert 's-broken' in open(os.path.join(str(data_dir), kept[0]), encoding='utf-8').read()


def test_a_partly_shaped_file_still_loads(ts, data_dir):
    write_json(os.path.join(str(data_dir), 'trade_session.json'),
               {'session': {'started_ts': 100, 'queue': [{'slug': 'a', 'name': 'A', 'qty': '3',
                                                          'price': 5, 'state': 'nonsense'},
                                                         {'name': 'no slug'}]}})
    doc = ts.load(str(data_dir))
    s = doc['session']
    assert s['id'].startswith('s-') and s['cursor'] == 0
    assert len(s['queue']) == 1 and s['queue'][0]['state'] == ts.READY
    assert s['queue'][0]['qty'] == 3
    assert s['totals'] == {'trades': 0, 'earned_plat': 0, 'skipped': 0, 'held': 0}


def test_reading_the_session_writes_nothing(ts, data_dir):
    ts.start_payload(str(data_dir), plan_doc(), advisor_doc(), report_doc(), runqueue_doc())
    path = os.path.join(str(data_dir), 'trade_session.json')
    before = open(path, 'rb').read()
    listing = sorted(os.listdir(str(data_dir)))
    ts.payload(str(data_dir), plan_doc(), advisor_doc(), report_doc(), runqueue_doc(),
               limits={'plat': 1200})
    assert open(path, 'rb').read() == before
    assert sorted(os.listdir(str(data_dir))) == listing


def test_a_corrupt_file_from_an_unknown_writer_is_kept(ts, data_dir):
    path = os.path.join(str(data_dir), 'trade_session.json')
    write_json(path, ['not', 'a', 'dict'])
    doc = ts.load(str(data_dir))
    assert doc == ts.empty() or doc['session'] is None
    assert not os.path.exists(path)
    assert any(p.startswith('trade_session.json.corrupt-') for p in os.listdir(str(data_dir)))


def test_payload_offers_a_queue_only_while_no_session_is_open(ts, data_dir):
    fresh = ts.payload(str(data_dir), plan_doc(), advisor_doc(), report_doc(), runqueue_doc())
    assert fresh['session'] is None and [r['slug'] for r in fresh['suggested']][0] == 'primed_continuity'
    ts.start_payload(str(data_dir), plan_doc(), advisor_doc(), report_doc(), runqueue_doc())
    live = ts.payload(str(data_dir), plan_doc(), advisor_doc(), report_doc(), runqueue_doc())
    assert live['suggested'] == [] and live['focus']['slug'] == 'primed_continuity'
    assert live['states'] == list(ts.STATES)


def test_stale_pending_is_reported_but_never_resolved(ts, data_dir):
    doc = ts.load(str(data_dir))
    doc['pending'] = [{'id': 'p-1', 'slug': 'primed_continuity', 'state': ts.CONTACTED,
                       'ts': int(time.time()) - 7 * 3600, 'expected_plat': 48, 'qty': 1},
                      {'id': 'p-2', 'slug': 'shredder', 'state': ts.CONTACTED,
                       'ts': int(time.time()), 'expected_plat': 8, 'qty': 1}]
    ts.save(str(data_dir), doc)
    out = ts.payload(str(data_dir))
    assert [p['id'] for p in out['pending']] == ['p-2']
    assert [p['id'] for p in out['stale_pending']] == ['p-1']
    assert ts.load(str(data_dir))['pending'][0]['state'] == ts.CONTACTED


def test_why_carries_the_two_order_book_numbers(ts):
    """Spec §1's price block: what you list at, the lowest live sell, the highest live buy."""
    report = report_doc()
    report['sell_now'][0]['wts'] = 90
    report['sell_now'][0]['wtb'] = 100
    q = ts.build_queue(plan_doc(), advisor_doc(), report, runqueue_doc())
    why = q[0]['why']
    assert why['lowest_sell'] == 90 and why['highest_buy'] == 100
    assert why['sell_orders'] == 5 and why['buy_orders'] == 5


def test_why_omits_the_order_book_numbers_when_there_are_none(ts):
    report = report_doc()
    report['sell_now'][0].pop('wtb')
    report['sell_now'][0].pop('wts')
    q = ts.build_queue(plan_doc(), advisor_doc(), report, runqueue_doc())
    why = q[0]['why']
    assert 'lowest_sell' not in why and 'highest_buy' not in why


# --------------------------------------------------- rank evidence on the buyer (spec §2/§3)
def row_for(q, slug):
    return [r for r in q if r['slug'] == slug][0]


def test_a_buyer_with_no_rank_evidence_on_a_ranked_lane_says_so(ts):
    """The run queue picks buyers per lane, but the row it writes used to carry no rank, so a
    ranked-lane sale showed a buyer nothing could check. It still shows the buyer - it is the best
    one for that lane - and states that the rank could not be verified from the data."""
    q = ts.build_queue(plan_doc(), advisor_doc(), report_doc(), runqueue_doc())
    row = row_for(q, 'primed_continuity')
    assert row['rank'] == 0 and row['buyer'] is not None
    assert row['why']['rank_unverified'] in (True, 'queue row names no rank for this buyer')


def test_a_buyer_whose_rank_disagrees_can_never_land_on_the_row(ts):
    q = ts.build_queue(plan_doc(), advisor_doc(), report_doc(),
                       runqueue_doc(row={'lane': 'rank 6'}))
    row = row_for(q, 'primed_continuity')
    assert row['buyer'] is None, 'never pair a rank-6 order with a rank-0 stack'
    assert 'rank 6' in row['why']['rank_mismatch']


def test_a_buyer_whose_rank_agrees_lands_with_no_caveat(ts):
    q = ts.build_queue(plan_doc(), advisor_doc(), report_doc(),
                       runqueue_doc(row={'lane': 'rank 0'}))
    row = row_for(q, 'primed_continuity')
    assert row['buyer'] is not None
    assert 'rank_unverified' not in row['why'] and 'rank_mismatch' not in row['why']


def test_an_item_with_no_rank_dimension_never_asks_for_rank_evidence(ts):
    """A relic is 'intact' or nothing - there is no rank to verify, so no caveat either."""
    plan = {'plan': [{'slug': 'neo_d3_relic', 'name': 'Neo D3 Relic', 'qty': 6, 'per_trade': 6,
                      'price': 35, 'lane': ''}]}
    report = {'sell_now': [{'slug': 'neo_d3_relic', 'name': 'Neo D3 Relic', 'cat': 'relic',
                            'lane_rank': None, 'lane_ask': 35, 'vol48': 20, 'n_buy': 2,
                            'sellable_count': 6}]}
    rq = runqueue_doc(row={'slug': 'neo_d3_relic', 'name': 'Neo D3 Relic', 'lane': 'intact',
                           'qty': 6, 'my_price': 35, 'buy_price': 35})
    row = row_for(ts.build_queue(plan, {}, report, rq), 'neo_d3_relic')
    assert row['rank'] is None and row['buyer'] is not None
    assert 'rank_unverified' not in row['why']
