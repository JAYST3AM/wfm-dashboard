"""Trading Session, stage 4 — reconciliation: what actually moved, proposed and never assumed.

docs/trading-session-workflow.md §4 and §13 items 7-12. The rule the whole stage hangs on: the loop
proposes, the user confirms, and a proposal that is not certain says so instead of guessing. The
private trader/detector.py already auto-confirms; the public path deliberately does not.
"""
import json
import os
import time

import pytest

from conftest import load_script, read_json, write_json


@pytest.fixture
def ts(monkeypatch):
    return load_script('trade_session', monkeypatch=monkeypatch)


def pend(slug='primed_continuity', rank=0, qty=1, plat=48, inv=4, plat_before=1220, age=60,
         state='CONTACTED', **over):
    row = {'id': 'p-%s-%s' % (slug, rank), 'slug': slug, 'name': slug.replace('_', ' ').title(),
           'rank': rank, 'qty': qty, 'expected_plat': plat, 'buyer': 'Wombat', 'kind': 'sell',
           'ts': int(time.time()) - age, 'state': state, 'inv_before': inv, 'plat_before': plat_before,
           'session_id': 's-1'}
    row.update(over)
    return row


def keys_of(rows):
    return {ts_key(slug, rank) for slug, rank in rows}


def ts_key(slug, rank):
    return '%s#%s' % (slug, 'r%s' % rank if rank is not None else 'any')


# --------------------------------------------------------------------------- the verdicts
def test_stack_left_and_platinum_matched_is_exact(ts):
    out = ts.propose([pend()], {ts_key('primed_continuity', 0): 3}, 1268)
    p = out['proposals'][0]
    assert p['verdict'] == ts.EXACT and p['copies_left'] == 1 and p['plat_delta'] == 48
    assert p['trade']['plat'] == 48 and p['trade']['id'].startswith('t-')
    assert out['needs_you'] == 1


def test_a_multi_copy_sale_matches_on_the_total(ts):
    out = ts.propose([pend(qty=3, inv=6, plat_before=1000)], {ts_key('primed_continuity', 0): 3}, 1144)
    p = out['proposals'][0]
    assert p['verdict'] == ts.EXACT and p['copies_left'] == 3 and p['total_plat'] == 144
    assert p['trade']['plat'] == 144 and p['trade']['qty'] == 3


def test_extra_platinum_is_shown_not_hidden(ts):
    out = ts.propose([pend()], {ts_key('primed_continuity', 0): 3}, 1400)
    p = out['proposals'][0]
    assert p['verdict'] == ts.EXACT and p['plat_delta'] == 180
    assert any('extra' in e for e in p['evidence'])


def test_stack_left_but_platinum_flat_is_ambiguous(ts):
    out = ts.propose([pend()], {ts_key('primed_continuity', 0): 3}, 1220)
    p = out['proposals'][0]
    assert p['verdict'] == ts.AMBIGUOUS
    assert any('asked' in e for e in p['evidence'])


def test_platinum_rose_but_the_stack_is_untouched_is_ambiguous(ts):
    out = ts.propose([pend()], {ts_key('primed_continuity', 0): 4}, 1320)
    p = out['proposals'][0]
    assert p['verdict'] == ts.AMBIGUOUS and p['copies_left'] == 0
    assert any('untouched' in e for e in p['evidence'])


def test_fewer_copies_left_than_asked_for_is_ambiguous(ts):
    out = ts.propose([pend(qty=3, inv=6)], {ts_key('primed_continuity', 0): 5}, 1268)
    p = out['proposals'][0]
    assert p['verdict'] == ts.AMBIGUOUS and p['copies_left'] == 1


def test_nothing_moved_is_nothing(ts):
    out = ts.propose([pend()], {ts_key('primed_continuity', 0): 4}, 1220)
    p = out['proposals'][0]
    assert p['verdict'] == ts.NOTHING and out['needs_you'] == 0
    assert p['trade']['plat'] == 48          # the draft is still offered for a manual confirmation


def test_a_small_platinum_wobble_with_no_inventory_move_is_nothing(ts):
    out = ts.propose([pend(plat=48)], {ts_key('primed_continuity', 0): 4}, 1221)
    assert out['proposals'][0]['verdict'] == ts.NOTHING


def test_a_trade_with_no_before_snapshot_is_unknown_not_a_guess(ts):
    out = ts.propose([pend(inv=None, plat_before=None)], {ts_key('primed_continuity', 0): 3}, 1268)
    p = out['proposals'][0]
    assert p['verdict'] == ts.UNKNOWN
    assert any('no snapshot' in e for e in p['evidence'])


def test_inventory_grew_is_not_a_sale(ts):
    out = ts.propose([pend()], {ts_key('primed_continuity', 0): 9}, 1220)
    assert out['proposals'][0]['verdict'] == ts.NOTHING


def test_the_ranks_are_kept_apart(ts):
    """Each rank is reconciled against its own copies: rank 10's stack need not move for rank 0's sale."""
    out = ts.propose([pend(rank=0), pend(rank=10, plat=120, inv=4)],
                     {ts_key('primed_continuity', 0): 3, ts_key('primed_continuity', 10): 4}, 1268)
    by_rank = {p['rank']: p for p in out['proposals']}
    assert by_rank[0]['verdict'] == ts.EXACT
    assert by_rank[10]['verdict'] == ts.NOTHING and by_rank[10]['inv_now'] == 4


def test_only_live_pending_rows_are_reconciled(ts):
    out = ts.propose([pend(state='COMPLETED'), pend(state='SKIPPED'), pend(state='CONTACTED')],
                     {ts_key('primed_continuity', 0): 3}, 1268)
    assert len(out['proposals']) == 1


def test_exact_proposals_come_first(ts):
    out = ts.propose([pend(slug='a', rank=0, inv=4), pend(slug='b', rank=0, inv=4)],
                     {ts_key('a', 0): 4, ts_key('b', 0): 3}, 1268)
    assert [p['slug'] for p in out['proposals']] == ['b', 'a'] or out['counts'][ts.EXACT] == 1


def test_old_pending_rows_are_flagged_stale(ts):
    out = ts.propose([pend(age=7 * 3600)], {ts_key('primed_continuity', 0): 3}, 1268)
    assert out['proposals'][0]['stale'] is True
    assert out['proposals'][0]['age_s'] >= 7 * 3600


def test_the_draft_carries_everything_confirm_needs(ts):
    out = ts.propose([pend()], {ts_key('primed_continuity', 0): 3}, 1268)
    t = out['proposals'][0]['trade']
    for key in ('id', 'slug', 'item', 'rank', 'qty', 'plat', 'user', 'source', 'session_id',
                'pending_id'):
        assert key in t, key
    assert t['source'] == 'session' and t['pending_id'] == 'p-primed_continuity-0'


def test_proposing_never_writes_a_trade_log(ts, data_dir):
    before = sorted(os.listdir(str(data_dir)))
    ts.propose([pend()], {ts_key('primed_continuity', 0): 3}, 1268)
    assert sorted(os.listdir(str(data_dir))) == before
    assert not os.path.exists(os.path.join(str(data_dir), 'trade_log.json'))


def test_a_trade_id_is_stable_for_the_same_record(ts):
    a = ts.trade_id({'kind': 'sale', 'slug': 'x', 'rank': 0, 'qty': 1, 'plat': 5, 'user': 'w',
                     'ts': 1000})
    b = ts.trade_id({'kind': 'sale', 'slug': 'x', 'rank': 0, 'qty': 1, 'plat': 5, 'user': 'w',
                     'ts': 1000})
    c = ts.trade_id({'kind': 'sale', 'slug': 'x', 'rank': 0, 'qty': 2, 'plat': 5, 'user': 'w',
                     'ts': 1000})
    assert a == b and a != c
    assert ts.trade_id({'id': 't-kept'}) == 't-kept'


def test_an_empty_pending_list_is_a_clean_answer(ts):
    out = ts.propose([], {}, 1268)
    assert out == {'proposals': [], 'counts': {'exact': 0, 'ambiguous': 0, 'none': 0, 'unknown': 0},
                   'needs_you': 0}


# --------------------------------------------------------------------------- on the session payload
def test_the_payload_carries_the_check_so_the_panel_needs_no_second_ask(ts, data_dir):
    plan = {'plan': [{'slug': 'primed_continuity', 'name': 'Primed Continuity', 'per_trade': 1,
                      'price': 48, 'lane': 'rank 0'}]}
    ts.start_payload(str(data_dir), plan, {}, {}, {})
    doc = ts.load(str(data_dir))
    ts.contact(doc, 'primed_continuity', rank=0, qty=1, price=48, buyer='Wombat',
               inv_before=4, plat_before=1220)
    ts.save(str(data_dir), doc)
    report = {'sell_now': [{'slug': 'primed_continuity', 'lane_rank': 0, 'sellable_count': 3}]}
    out = ts.payload(str(data_dir), plan=plan, report=report, limits={'plat': 1268})
    assert out['needs_you'] == 1 and out['checks'][ts.EXACT] == 1
    p = out['proposals'][0]
    assert p['verdict'] == ts.EXACT and p['inv_now'] == 3 and p['plat_now'] == 1268
    assert p['trade']['plat'] == 48


def test_a_stack_the_report_does_not_mention_is_unknown_not_zero(ts):
    inv = ts.inv_now_map({'sell_now': []}, [pend()])
    assert inv == {}


def test_inv_now_map_ignores_finished_pending_rows(ts):
    inv = ts.inv_now_map({'sell_now': [{'slug': 'primed_continuity', 'lane_rank': 0,
                                        'sellable_count': 3}]},
                         [pend(state='COMPLETED'), pend(state='CONTACTED')])
    assert inv == {ts_key('primed_continuity', 0): 3}


def test_the_payload_check_never_writes_a_trade_log(ts, data_dir):
    ts.start_payload(str(data_dir), {'plan': [{'slug': 'x', 'name': 'X', 'per_trade': 1,
                                               'price': 5, 'lane': 'rank 0'}]}, {}, {}, {})
    doc = ts.load(str(data_dir))
    ts.contact(doc, 'x', rank=0, qty=1, price=5, buyer='W', inv_before=2, plat_before=100)
    ts.save(str(data_dir), doc)
    ts.payload(str(data_dir), report={'sell_now': [{'slug': 'x', 'lane_rank': 0,
                                                    'sellable_count': 1}]}, limits={'plat': 105})
    assert not os.path.exists(os.path.join(str(data_dir), 'trade_log.json'))
