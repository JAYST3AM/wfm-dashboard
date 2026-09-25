"""scripts/trader/runqueue.py: buyer selection, run order and the data/run_queue.json contract.

scripts/trader/ is private (gitignored), so the whole module skips cleanly on a public checkout.

Nothing here reaches the network: build()'s orderbook fetch is monkeypatched with fixtures, the
source is scanned to prove the script carries no warframe.market write path at all (no session,
no create/patch/delete), and --selftest runs in a subprocess, offline by construction.
"""
import os
import subprocess
import sys

import pytest

from conftest import SCRIPTS, load_script, read_json, write_json

RQ_PATH = os.path.join(SCRIPTS, 'trader', 'runqueue.py')
pytestmark = pytest.mark.skipif(not os.path.exists(RQ_PATH),
                                reason='scripts/trader/ is private (not in the public tree)')

PC, NEO = 'primed_continuity', 'neo_d3_relic'
PLAN_ROWS = [
    {'slug': PC, 'name': 'Primed Continuity', 'qty': 3, 'price': 47, 'lane': 'rank 0', 'subtype': None},
    {'slug': PC, 'name': 'Primed Continuity', 'qty': 1, 'price': 69, 'lane': 'rank 6', 'subtype': 'rank 6'},
    {'slug': NEO, 'name': 'Neo D3 Relic', 'qty': 18, 'price': 7, 'lane': 'intact', 'subtype': 'intact'},
]
WFM_ITEMS = {'data': [{'id': 'id_pc', 'slug': PC, 'i18n': {'en': {'name': 'Primed Continuity'}}},
                      {'id': 'id_neo', 'slug': NEO, 'i18n': {'en': {'name': 'Neo D3 Relic'}}}]}
BOOKS = {
    'id_pc': [
        {'type': 'buy', 'platinum': 47, 'quantity': 3, 'visible': True,
         'user': {'ingameName': 'IngamePc', 'status': 'ingame', 'reputation': 5}},
        {'type': 'buy', 'platinum': 90, 'quantity': 1, 'visible': True,
         'user': {'ingameName': 'RichOffline', 'status': 'offline', 'reputation': 50}},
        {'type': 'buy', 'platinum': 70, 'quantity': 1, 'visible': True, 'rank': 6,
         'user': {'ingameName': 'Rank6Buyer', 'status': 'online', 'reputation': 2}},
        {'type': 'buy', 'platinum': 20, 'quantity': 4, 'visible': True,
         'user': {'ingameName': 'UnderMyPrice', 'status': 'ingame'}},
    ],
    'id_neo': [
        {'type': 'buy', 'platinum': 8, 'quantity': 30, 'visible': True, 'subtype': 'intact',
         'user': {'ingameName': 'RelicBuyer', 'status': 'ingame', 'reputation': 7}},
        {'type': 'buy', 'platinum': 9, 'quantity': 30, 'visible': True, 'subtype': 'radiant',
         'user': {'ingameName': 'WrongLane', 'status': 'ingame'}},
    ],
}
BOOK = [
    {'type': 'buy', 'platinum': 60, 'quantity': 1, 'visible': True, 'rank': 6,
     'user': {'ingameName': 'WrongRank', 'status': 'ingame'}},
    {'type': 'buy', 'platinum': 55, 'quantity': 2, 'visible': True,
     'user': {'ingameName': 'Me', 'status': 'ingame', 'reputation': 99}},
    {'type': 'buy', 'platinum': 59, 'quantity': 1, 'visible': False,
     'user': {'ingameName': 'Hidden', 'status': 'ingame'}},
    {'type': 'sell', 'platinum': 48, 'quantity': 1, 'visible': True,
     'user': {'ingameName': 'Seller', 'status': 'ingame'}},
    {'type': 'buy', 'platinum': 46, 'quantity': 1, 'visible': True,
     'user': {'ingameName': 'TooCheap', 'status': 'ingame'}},
    {'type': 'buy', 'platinum': 47, 'quantity': 1, 'visible': True,
     'user': {'ingameName': 'OfflineHigh', 'status': 'offline', 'reputation': 1}},
    {'type': 'buy', 'platinum': 47, 'quantity': 9, 'visible': True,
     'user': {'ingameName': 'IngameTie', 'status': 'ingame', 'reputation': 3}},
    {'type': 'buy', 'platinum': 47, 'quantity': 1, 'visible': True,
     'user': {'ingameName': 'OnlineHighRep', 'status': 'online', 'reputation': 400}},
    {'type': 'buy', 'platinum': 47, 'quantity': 1, 'visible': True,
     'user': {'ingameName': 'OnlineLowRep', 'status': 'online', 'reputation': 4}},
    {'type': 'buy', 'platinum': 47, 'quantity': 1, 'visible': True,
     'user': {'ingameName': 'NoStatus'}},
]


@pytest.fixture
def rq(monkeypatch):
    return load_script('trader/runqueue', monkeypatch=monkeypatch)


def write_inputs(root, plan=None, state=None, items=None):
    data = root / 'data'
    data.mkdir(exist_ok=True)
    write_json(data / 'trader_plan.json', plan if plan is not None else {'plan': PLAN_ROWS})
    write_json(data / 'trader_state.json', state if state is not None else {'account': 'SampleTennoIX', 'orders': {}})
    write_json(data / 'wfm_items_v2.json', items if items is not None else WFM_ITEMS)
    return data


def run_main(rq, root, *extra):
    return rq.main(['runqueue.py', '--root', str(root), *extra])


# ------------------------------------------------------------------ offline, no write path

def test_selftest_runs_offline_and_passes(tmp_path):
    proc = subprocess.run([sys.executable, RQ_PATH, '--selftest'],
                          capture_output=True, text=True, cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.startswith('selftest: PASS'), proc.stdout
    assert 'FAIL' not in proc.stdout
    assert not (tmp_path / 'data').exists()          # selftest writes nothing


def test_script_has_no_market_write_path(rq):
    with open(RQ_PATH, encoding='utf-8') as fh:
        src = fh.read()
    for token in ("'POST'", "'PATCH'", "'DELETE'", 'signin', 'create_order', 'patch_order',
                  'delete_order', 'close_order', 'secrets.json', 'csrf'):
        assert token not in src, f'runqueue must never write/post: found {token!r}'
    assert not hasattr(rq, 'signin')                 # no session object exists at all


# ------------------------------------------------------------------ pure logic

def test_lane_match_mod_rank_relic_refinement_and_plain(rq):
    assert rq.lane_match('rank 6', {'rank': 6}) and not rq.lane_match('rank 6', {'rank': 0})
    assert rq.lane_match('rank 0', {})                       # unranked buyer order
    assert rq.lane_match('intact', {'subtype': 'intact'}) and not rq.lane_match('intact', {'subtype': 'Radiant'})
    assert rq.lane_match('radiant', {'subtype': 'Radiant'})
    assert rq.lane_match('', {}) and not rq.lane_match('', {'rank': 6}) and not rq.lane_match('', {'subtype': 'intact'})


def test_lane_of_prefers_plan_lane_then_subtype(rq):
    assert rq.lane_of({'lane': 'rank 6', 'subtype': None}) == 'rank 6'
    assert rq.lane_of({'lane': '', 'subtype': 'Radiant'}) == 'radiant'
    assert rq.lane_of({}) == ''


def test_buyers_for_filters_and_runs_online_first_then_price(rq):
    bs = rq.buyers_for(BOOK, 'rank 0', 47, my_name='Me')
    assert [b['buyer'] for b in bs] == ['IngameTie', 'OnlineHighRep', 'OnlineLowRep',
                                        'OfflineHigh', 'NoStatus']
    assert [b['buyer_status'] for b in bs] == ['ingame', 'online', 'online', 'offline', 'offline']
    assert [b['buy_price'] for b in bs] == [47, 47, 47, 47, 47]
    assert 'TooCheap' not in [b['buyer'] for b in bs]        # 46p < my 47p
    assert all(b['buyer'] not in ('Hidden', 'Me', 'Seller', 'WrongRank') for b in bs)
    assert bs[0]['want'] == 9 and bs[0]['rep'] == 3
    assert rq.buyers_for([], 'rank 0', 10) == []


def test_buyers_for_price_floor_is_inclusive_and_picks_the_highest_offer(rq):
    book = [{'type': 'buy', 'platinum': 47, 'quantity': 1, 'visible': True,
             'user': {'ingameName': 'Same', 'status': 'ingame'}},
            {'type': 'buy', 'platinum': 51, 'quantity': 1, 'visible': True,
             'user': {'ingameName': 'Higher', 'status': 'ingame'}},
            {'type': 'buy', 'platinum': 80, 'quantity': 1, 'visible': True,
             'user': {'ingameName': 'HighestOffline', 'status': 'offline'}}]
    bs = rq.buyers_for(book, '', 47)
    assert [b['buyer'] for b in bs] == ['Higher', 'Same', 'HighestOffline']
    assert len(rq.buyers_for(book, '', 47)) == 3             # exact-price buyer still counts


def test_offer_qty_is_one_trade_worth(rq):
    assert rq.offer_qty(18, 0) == 6                          # whole stack, 6-copy trade cap
    assert rq.offer_qty(18, 18) == 6
    assert rq.offer_qty(18, 2) == 2                          # buyer asked for fewer
    assert rq.offer_qty(6, 9) == 6
    assert rq.offer_qty(1, 0) == 1 and rq.offer_qty(None, None) == 1


def test_whisper_line_is_copy_paste_ready(rq):
    assert rq.whisper_for('Neo D3 Relic', 6, 7, 'SampleTennoIX') == \
        'Hi! I have Neo D3 Relic x6 at 7p \u2014 invite SampleTennoIX if you want it.'


def test_my_listings_prefers_live_orders_and_borrows_the_lane(rq):
    plan = {'plan': PLAN_ROWS}
    live = {'account': 'SampleTennoIX', 'orders': {
        'o1': {'slug': PC, 'name': 'Primed Continuity', 'type': 'sell', 'qty': 3, 'plat': 47, 'visible': True},
        'o2': {'slug': NEO, 'name': 'Neo D3 Relic', 'type': 'sell', 'qty': 18, 'plat': 7, 'visible': True},
        'o3': {'slug': PC, 'name': 'Primed Continuity', 'type': 'buy', 'qty': 1, 'plat': 30},
        'o4': {'slug': PC, 'name': 'Primed Continuity', 'type': 'sell', 'qty': 1, 'plat': 69, 'visible': False},
    }}
    rows, src = rq.my_listings(plan, live)
    assert src == 'trader_state.json (live orders)' and len(rows) == 2
    assert rows[0]['lane'] == 'rank 0'                       # borrowed from the matching plan row
    assert rows[1]['my_price'] == 7 and rows[1]['lane'] == 'intact'
    rows2, src2 = rq.my_listings(plan, {'orders': {}})
    assert src2 == 'trader_plan.json (planned listings)' and len(rows2) == 3
    assert rq.my_listings({}, {}) == ([], 'trader_plan.json (planned listings)')


def test_plan_queue_orders_rows_online_first_then_price(rq):
    listings, _ = rq.my_listings({'plan': PLAN_ROWS}, {})
    queue, no_buyer, skipped = rq.plan_queue(listings, {'primed_continuity': BOOKS['id_pc'],
                                                        'neo_d3_relic': BOOKS['id_neo']},
                                             'SampleTennoIX')
    assert [(q['buyer'], q['buyer_status']) for q in queue] == \
        [('IngamePc', 'ingame'), ('RelicBuyer', 'ingame'), ('Rank6Buyer', 'online')]
    assert [q['slug'] for q in queue] == [PC, NEO, PC]       # ingame cluster, price desc inside it
    assert no_buyer == [] and skipped == []
    assert rq.queue_summary(queue) == {'ingame': 2, 'online': 1, 'offline': 0, 'total': 3}
    assert rq.queue_summary([]) == {'ingame': 0, 'online': 0, 'offline': 0, 'total': 0}
    q = queue[0]
    assert sorted(q) == ['buy_price', 'buyer', 'buyer_status', 'my_price', 'name', 'qty', 'slug',
                         'whisper', 'why']
    assert q['qty'] == 3 and q['buy_price'] == 47 and q['my_price'] == 47
    assert q['whisper'] == 'Hi! I have Primed Continuity x3 at 47p \u2014 invite SampleTennoIX if you want it.'
    assert queue[1]['qty'] == 6                              # 18 relic copies -> 6/trade


def test_plan_queue_notes_the_trade_cap_only_when_it_bites(rq):
    small = rq.queue_row(dict(slug='x', name='X', qty=6, my_price=5, lane=''),
                         dict(buyer='B', buyer_status='ingame', buy_price=9, want=1, rep=0), 'A')
    assert small['qty'] == 1 and 'stack' not in small['why']
    big = rq.queue_row(dict(slug='x', name='X', qty=18, my_price=5, lane=''),
                       dict(buyer='B', buyer_status='ingame', buy_price=9, want=30, rep=0), 'A')
    assert big['qty'] == 6 and big['why'].endswith('stack 18 -> 6/trade')
    assert big['whisper'].endswith('invite A if you want it.')


def test_plan_queue_reports_no_buyer_and_missing_orders(rq):
    listings, _ = rq.my_listings({'plan': PLAN_ROWS}, {})
    queue, no_buyer, skipped = rq.plan_queue(listings, {'primed_continuity': [], 'neo_d3_relic': []}, 'A')
    assert queue == []
    assert no_buyer == [('Primed Continuity', 47), ('Primed Continuity', 69), ('Neo D3 Relic', 7)]
    assert rq.plan_queue(listings, {}, 'A')[2] == \
        [('Primed Continuity', 'orderbook unavailable'), ('Primed Continuity', 'orderbook unavailable'),
         ('Neo D3 Relic', 'orderbook unavailable')]


# ------------------------------------------------------------------ run_queue.json contract

def test_main_writes_run_queue_contract_without_touching_the_network(rq, tmp_path, monkeypatch):
    data = write_inputs(tmp_path)
    calls = []

    def fake_fetch(item_id):
        calls.append(item_id)
        return BOOKS[item_id]

    monkeypatch.setattr(rq, 'fetch_book', fake_fetch)

    assert run_main(rq, tmp_path) == 0
    assert sorted(calls) == ['id_neo', 'id_pc']              # one fetch per item, not per plan row
    assert sorted(os.listdir(data)) == ['run_queue.json', 'trader_plan.json', 'trader_state.json',
                                        'wfm_items_v2.json']  # no .tmp leftovers, nothing else written

    doc = read_json(data / 'run_queue.json')
    assert sorted(doc) == ['generated', 'queue', 'summary']
    assert isinstance(doc['generated'], int) and doc['generated'] > 0
    assert doc['summary'] == {'ingame': 2, 'online': 1, 'offline': 0, 'total': 3}

    q = doc['queue'][0]
    assert q == {'slug': PC, 'name': 'Primed Continuity', 'qty': 3, 'my_price': 47,
                 'buyer': 'IngamePc', 'buyer_status': 'ingame', 'buy_price': 47,
                 'whisper': 'Hi! I have Primed Continuity x3 at 47p \u2014 invite SampleTennoIX if you want it.',
                 'why': 'ingame \u00b7 pays 47p vs your 47p \u00b7 wants 3 \u00b7 rep 5 \u00b7 rank 0'}
    assert doc['queue'][1]['why'].startswith('ingame \u00b7 pays 8p vs your 7p')
    why3 = doc['queue'][2]['why']
    assert why3.startswith('online \u00b7 pays 70p vs your 69p') and why3.endswith('\u00b7 rank 6')


def test_main_uses_live_orders_when_the_state_has_them(rq, tmp_path, monkeypatch):
    state = {'account': 'SampleTennoIX', 'orders': {
        'o1': {'slug': NEO, 'name': 'Neo D3 Relic', 'type': 'sell', 'qty': 18, 'plat': 7, 'visible': True}}}
    data = write_inputs(tmp_path, state=state)
    monkeypatch.setattr(rq, 'fetch_book', lambda iid: BOOKS[iid])

    assert run_main(rq, tmp_path) == 0
    doc = read_json(data / 'run_queue.json')
    assert [(q['slug'], q['name'], q['my_price'], q['qty'], q['buyer']) for q in doc['queue']] == \
        [(NEO, 'Neo D3 Relic', 7, 6, 'RelicBuyer')]


def test_main_caps_the_orderbook_calls(rq, tmp_path, monkeypatch):
    data = write_inputs(tmp_path)
    calls = []

    def fake_fetch(item_id):
        calls.append(item_id)
        return BOOKS[item_id]

    monkeypatch.setattr(rq, 'fetch_book', fake_fetch)

    assert run_main(rq, tmp_path, '--max-calls', '1') == 0
    assert calls == ['id_pc']                                # 1 call covers both PC lanes, neo unfetched
    doc = read_json(data / 'run_queue.json')
    assert doc['summary']['total'] == 2 and [q['slug'] for q in doc['queue']] == [PC, PC]


def test_main_limit_flag_caps_listings(rq, tmp_path, monkeypatch):
    write_inputs(tmp_path)
    monkeypatch.setattr(rq, 'fetch_book', lambda iid: BOOKS[iid])
    assert run_main(rq, tmp_path, '--limit', '1') == 0
    doc = read_json(tmp_path / 'data' / 'run_queue.json')
    assert [q['slug'] for q in doc['queue']] == [PC]         # only the first listing is planned


def test_main_per_item_queues_alternate_buyers(rq, tmp_path, monkeypatch):
    write_inputs(tmp_path)
    monkeypatch.setattr(rq, 'fetch_book', lambda iid: BOOKS[iid])
    assert run_main(rq, tmp_path, '--per-item', '2') == 0
    doc = read_json(tmp_path / 'data' / 'run_queue.json')
    assert [q['buyer'] for q in doc['queue']] == ['IngamePc', 'RelicBuyer', 'Rank6Buyer', 'RichOffline']


def test_main_without_listings_returns_1_and_writes_nothing(rq, tmp_path, monkeypatch):
    data = write_inputs(tmp_path, plan={'plan': []}, state={'orders': {}})
    monkeypatch.setattr(rq, 'fetch_book', lambda iid: pytest.fail('must not fetch without listings'))
    assert run_main(rq, tmp_path) == 1
    assert not (data / 'run_queue.json').exists()


def test_main_without_the_item_map_returns_1(rq, tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    write_json(data / 'wfm_items_v2.json', {})
    assert run_main(rq, tmp_path) == 1
    assert not (data / 'run_queue.json').exists()
