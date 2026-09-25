"""scripts/deal_scanner.py: pure lane/deal logic + offline run of the deals.json contract.

fetch() is monkeypatched (the module only touches the network inside it), so main()
runs end-to-end against tmp fixtures - no live warframe.market calls.
"""
import sys
import time
from types import SimpleNamespace

from conftest import load_script, read_json, write_json

SLUG, ITEM_ID = 'braton_prime_barrel', 'iid-1'
CATALOG = [{'slug': SLUG, 'id': ITEM_ID, 'ducats': 15, 'tags': ['prime', 'component'],
            'i18n': {'en': {'name': 'Braton Prime Barrel'}}}]
BOOK = [
    {'type': 'sell', 'platinum': 10, 'quantity': 2, 'rank': None, 'subtype': None, 'visible': True,
     'user': {'status': 'ingame', 'ingameName': 'Seller1'}, 'updatedAt': None},
    {'type': 'buy', 'platinum': 20, 'quantity': 1, 'rank': None, 'subtype': None, 'visible': True,
     'user': {'status': 'online', 'ingameName': 'Buyer1'}, 'updatedAt': None},
]
DEAL_KEYS = {
    'slug', 'name', 'item_id', 'kind', 'url', 'lane', 'floor_sell', 'floor_sell_any',
    'floor_qty', 'floor_seller', 'floor_status', 'floor_age_days', 'top_buy', 'top_buy_any',
    'buy_qty', 'top_buyer', 'top_buy_status', 'buy_age_days', 'ref', 'ref_src', 'lane_median',
    'lane_max_sell', 'prev_wts', 'n_sell', 'n_buy', 'n_sell_online', 'n_buy_online',
    'target_price', 'profit', 'profit_pct', 'flip_qty', 'vol48', 'owned', 'stale', 'score',
    'first_seen', 'last_seen',
}


def scan_args(**kw):
    base = dict(min_profit=3.0, min_spread_pct=5.0, undercut_pct=25.0, min_lane=3, single_rank=True)
    base.update(kw)
    return SimpleNamespace(**base)


def order(kind, plat, status='ingame', qty=1, rank=None, subtype=None, visible=True, age_days=0.0):
    """One synthetic warframe.market order; age_days back-dates updatedAt."""
    updated = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() - age_days * 86400))
    return {'type': kind, 'platinum': plat, 'quantity': qty, 'rank': rank, 'subtype': subtype,
            'visible': visible, 'user': {'status': status, 'ingameName': '%s-%s' % (kind, plat)},
            'updatedAt': updated}


def item(vol48=30, own=0):
    return {'slug': SLUG, 'name': 'Braton Prime Barrel', 'id': ITEM_ID, 'vol48': vol48, 'own': own}


# ------------------------------------------------------------------ pure logic

def test_lanes_of_filters_unusable_orders(monkeypatch):
    mod = load_script('deal_scanner')
    orders = [
        order('sell', 10), order('sell', 20, visible=False), order('sell', 30, qty=0),
        order('sell', 0), order('buy', 5),
        {'type': 'auction', 'platinum': 4, 'visible': True, 'quantity': 1},
    ]
    lanes = mod.lanes_of(orders)
    assert list(lanes) == [(None, None)]
    assert [o['platinum'] for o in lanes[(None, None)]['sell']] == [10]
    assert [o['platinum'] for o in lanes[(None, None)]['buy']] == [5]


def test_lanes_of_groups_by_rank_and_subtype(monkeypatch):
    mod = load_script('deal_scanner')
    lanes = mod.lanes_of([order('sell', 10, rank=0), order('sell', 90, rank=5),
                          order('sell', 12, rank=0, subtype='max')])
    assert sorted(lanes, key=lambda k: (k[0], k[1] or '')) == [(0, None), (0, 'max'), (5, None)]


def test_pick_prefers_online_then_price(monkeypatch):
    mod = load_script('deal_scanner')
    cheap_offline = order('sell', 5, status='offline')
    online_9 = order('sell', 9, status='online')
    ingame_12 = order('sell', 12, status='ingame')
    # a visible online seller beats a cheaper offline one
    assert mod.pick([cheap_offline, ingame_12, online_9], cheapest=True) is online_9
    buys_top = order('buy', 80, status='ingame')
    assert mod.pick([order('buy', 100, status='offline'), order('buy', 70, status='online'), buys_top],
                    cheapest=False) is buys_top
    assert mod.pick([], cheapest=True) is None


def test_lane_metrics_floor_top_buy_and_median(monkeypatch):
    mod = load_script('deal_scanner')
    bucket = {'sell': [order('sell', 4, status='offline'), order('sell', 9), order('sell', 15)],
              'buy': [order('buy', 7), order('buy', 12, status='offline')]}
    m = mod.lane_metrics((0, None), bucket, int(time.time()))

    assert m['rank'] == 0 and m['subtype'] is None
    assert m['n_sell'] == 3 and m['n_buy'] == 2
    assert m['n_sell_online'] == 2 and m['n_buy_online'] == 1
    assert m['floor_sell'] == 9 and m['floor_sell_any'] == 4      # online preferred over raw min
    assert m['lane_max_sell'] == 15 and m['lane_median'] == 9
    assert m['top_buy'] == 7 and m['top_buy_any'] == 12
    assert m['floor_seller'] == 'sell-9' and m['floor_status'] == 'ingame'
    assert m['floor_age'] is not None


def test_evaluate_spread_deal(monkeypatch):
    mod = load_script('deal_scanner')
    now = int(time.time())
    bucket = {'sell': [order('sell', 10, qty=2, age_days=1)], 'buy': [order('buy', 20, age_days=2)]}
    metrics = [mod.lane_metrics((None, None), bucket, now)]
    deals = mod.evaluate(item(vol48=30), metrics, 12, 'stats48', 11, scan_args(), now)

    assert len(deals) == 1
    d = deals[0]
    assert set(d) == DEAL_KEYS
    assert d['kind'] == 'spread' and d['profit'] == 10 and d['profit_pct'] == 100.0
    assert d['floor_sell'] == 10 and d['target_price'] == 20 and d['top_buy'] == 20
    assert d['flip_qty'] == 1                       # min(floor qty 2, buy qty 1)
    assert d['ref'] == 12 and d['ref_src'] == 'stats48' and d['prev_wts'] == 11
    assert d['stale'] is False and d['score'] > 0
    assert d['first_seen'] == now and d['last_seen'] == now
    assert d['url'].endswith('/' + SLUG)


def test_evaluate_undercut_uses_lane_median_and_lane_size(monkeypatch):
    mod = load_script('deal_scanner')
    now = int(time.time())
    bucket = {'sell': [order('sell', 7), order('sell', 12), order('sell', 40)], 'buy': []}
    metrics = [mod.lane_metrics((0, None), bucket, now)]

    deals = mod.evaluate(item(), metrics, 10, 'stats48', None, scan_args(single_rank=False), now)

    assert len(deals) == 1
    d = deals[0]
    # floor 7 is >25% below the lane median (12) and the lane has the 3 required sellers
    assert d['kind'] == 'undercut' and d['ref'] == 12 and d['ref_src'] == 'lane_median'
    assert d['profit'] == 5 and d['target_price'] == 12


def test_evaluate_skips_thin_or_shallow_lanes(monkeypatch):
    mod = load_script('deal_scanner')
    now = int(time.time())
    # spread of 2p is below min_profit and only 2 sellers -> no undercut either
    thin = [mod.lane_metrics((None, None), {'sell': [order('sell', 10), order('sell', 30)],
                                            'buy': [order('buy', 12)]}, now)]
    assert mod.evaluate(item(), thin, 12, 'stats48', None, scan_args(single_rank=False), now) == []
    # no sell orders at all
    assert mod.evaluate(item(), [mod.lane_metrics((None, None), {'sell': [], 'buy': []}, now)],
                        12, 'stats48', None, scan_args(), now) == []
    # a sell order priced at 0 plat cannot be flipped
    zero = [mod.lane_metrics((None, None), {'sell': [order('sell', 0)], 'buy': [order('buy', 50)]}, now)]
    assert mod.evaluate(item(), zero, 12, 'stats48', None, scan_args(), now) == []


def test_evaluate_flags_stale_orders(monkeypatch):
    mod = load_script('deal_scanner')
    now = int(time.time())
    bucket = {'sell': [order('sell', 10, age_days=60)], 'buy': [order('buy', 40, age_days=60)]}
    metrics = [mod.lane_metrics((None, None), bucket, now)]
    deals = mod.evaluate(item(), metrics, 12, 'stats48', None, scan_args(), now)
    assert deals[0]['stale'] is True                # older than STALE_DAYS (45)


# ------------------------------------------------------------------ deals.json contract

def test_scan_writes_full_deal_contract(tmp_path, monkeypatch, data_dir):
    mod = load_script('deal_scanner', monkeypatch=monkeypatch)
    monkeypatch.setattr(mod, 'DATA', str(data_dir))
    monkeypatch.setattr(mod, 'DEALS_P', str(data_dir / 'deals.json'))
    monkeypatch.setattr(mod, 'STATE_P', str(data_dir / 'market_scan_state.json'))
    monkeypatch.setattr(mod, 'fetch', lambda item_id, tries=3: (BOOK, None))
    monkeypatch.setattr(sys, 'argv', ['deal_scanner.py', '--max-items', '1'])

    write_json(data_dir / 'wfm_items_v2.json', {'data': CATALOG})
    write_json(data_dir / 'owned.json', [])
    write_json(data_dir / 'prices.json', {SLUG: {'wts': 11, 'wtb': 8}})
    write_json(data_dir / 'stats.json', {SLUG: {'median': 12, 'vol48': 30}})

    mod.main()

    doc = read_json(data_dir / 'deals.json')
    assert doc['version'] == 1 and doc['window_hours'] == 12.0
    assert isinstance(doc['generated'], int) and doc['generated_iso'].endswith('Z')
    assert doc['params'] == {'min_profit': 3.0, 'min_spread_pct': 5.0, 'stale_days': 45,
                             'undercut_pct': 25.0, 'min_lane': 3}
    assert doc['scan']['pool_size'] == 1 and doc['scan']['items_scanned'] == 1
    assert doc['scan']['cursor_start'] == 0 and doc['scan']['cursor_end'] == 0
    assert doc['scan']['errors'] == 0
    assert doc['counts']['run_deals'] == 1 and doc['counts']['total'] == 1
    assert doc['counts']['by_kind'] == {'spread': 1}
    assert len(doc['deals']) == 1
    deal = doc['deals'][0]
    assert set(deal) == DEAL_KEYS
    assert (deal['slug'], deal['item_id'], deal['kind']) == (SLUG, ITEM_ID, 'spread')
    assert deal['profit'] == 10 and deal['floor_sell'] == 10 and deal['target_price'] == 20
    assert deal['prev_wts'] == 11 and deal['ref'] == 12 and deal['ref_src'] == 'stats48'
    assert deal['lane'] == {'rank': None, 'subtype': None}
    assert deal['owned'] == 0 and deal['vol48'] == 30 and deal['stale'] is False

    state = read_json(data_dir / 'market_scan_state.json')
    assert state['version'] == 1 and state['pool_size'] == 1 and len(state['pool_hash']) == 12
    assert state['cursor'] == 0 and state['runs'] == 1 and state['scanned_total'] == 1
    assert state['last_run']['deals'] == 1 and state['last_run']['errors'] == 0
    assert state['seen'][SLUG] == doc['generated']


def test_deal_window_keeps_last_seen_rows(tmp_path, monkeypatch, data_dir):
    """A later scan that finds nothing must keep the previous run's row (12h window)."""
    mod = load_script('deal_scanner', monkeypatch=monkeypatch)
    monkeypatch.setattr(mod, 'DATA', str(data_dir))
    monkeypatch.setattr(mod, 'DEALS_P', str(data_dir / 'deals.json'))
    monkeypatch.setattr(mod, 'STATE_P', str(data_dir / 'market_scan_state.json'))
    write_json(data_dir / 'wfm_items_v2.json', {'data': CATALOG})
    write_json(data_dir / 'owned.json', [])
    write_json(data_dir / 'prices.json', {})
    write_json(data_dir / 'stats.json', {})
    monkeypatch.setattr(sys, 'argv', ['deal_scanner.py', '--max-items', '1'])

    monkeypatch.setattr(mod, 'fetch', lambda item_id, tries=3: (BOOK, None))
    mod.main()
    first = read_json(data_dir / 'deals.json')['deals'][0]

    monkeypatch.setattr(mod, 'fetch', lambda item_id, tries=3: ([], None))
    mod.main()
    doc = read_json(data_dir / 'deals.json')

    assert doc['counts']['run_deals'] == 0
    assert doc['counts']['total'] == 1                       # kept from the earlier run
    assert doc['deals'][0]['first_seen'] == first['first_seen']
    assert read_json(data_dir / 'market_scan_state.json')['runs'] == 2


def test_scan_errors_are_counted_not_raised(tmp_path, monkeypatch, data_dir):
    mod = load_script('deal_scanner', monkeypatch=monkeypatch)
    monkeypatch.setattr(mod, 'DATA', str(data_dir))
    monkeypatch.setattr(mod, 'DEALS_P', str(data_dir / 'deals.json'))
    monkeypatch.setattr(mod, 'STATE_P', str(data_dir / 'market_scan_state.json'))
    monkeypatch.setattr(mod, 'fetch', lambda item_id, tries=3: (None, 'http 500'))
    monkeypatch.setattr(sys, 'argv', ['deal_scanner.py', '--max-items', '1'])
    write_json(data_dir / 'wfm_items_v2.json', {'data': CATALOG})

    mod.main()

    doc = read_json(data_dir / 'deals.json')
    assert doc['scan']['errors'] == 1 and doc['deals'] == []
    assert read_json(data_dir / 'market_scan_state.json')['errors_total'] == 1
