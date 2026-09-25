"""scripts/trader/flipper.py: buy-order planner logic + the data/flipper_plan.json contract.

scripts/trader/ is private (gitignored - not in the public checkout), so this module skips
itself when that folder is missing. Nothing here touches the network: the only live path (the
read-only orderbook re-check) is exercised with an injected fake fetch_book, and every CLI run
happens inside tmp_path via --root.
"""
import importlib.util
import os
import sys

import pytest

from conftest import read_json, write_json

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLIPPER_PY = os.path.join(REPO, 'scripts', 'trader', 'flipper.py')

pytestmark = pytest.mark.skipif(not os.path.exists(FLIPPER_PY),
                                reason='scripts/trader/ is private (not in the public checkout)')


def load_flipper():
    """Fresh module object for scripts/trader/flipper.py (it puts its own dir on sys.path)."""
    if not os.path.exists(FLIPPER_PY):
        pytest.skip('scripts/trader/flipper.py is private (not in the public checkout)')
    spec = importlib.util.spec_from_file_location('wfm_flipper_under_test', FLIPPER_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def fl_raw(monkeypatch):
    mod = load_flipper()
    monkeypatch.setattr(mod, '_killswitch_blocked', lambda: False)   # never read the repo's flag
    return mod


@pytest.fixture
def fl(fl_raw, monkeypatch):
    monkeypatch.setattr(fl_raw, 'SLEEP', 0)                          # no real rate-limit pauses
    return fl_raw


# --------------------------------------------------------------------- fixtures

def digest_row(slug, buy, sell, sales_day=50.0, queue_ahead=1, kind='undercut',
               score=100.0, safe_score=500.0, profit=None, name=None):
    return {'slug': slug, 'name': name or slug.replace('_', ' ').title(), 'kind': kind,
            'buy_at': buy, 'sell_at': sell, 'sales_day': sales_day, 'queue_ahead': queue_ahead,
            'score': score, 'safe_score': safe_score,
            'profit': (sell - buy) if profit is None else profit}


def deal_row(slug, item_id=None, rank=None, subtype=None, stale=False):
    return {'slug': slug, 'item_id': item_id or ('i-' + slug), 'stale': stale,
            'lane': {'rank': rank, 'subtype': subtype}}


def make_root(root, flips, safe_flips=(), deals=(), owned=(), settings=None):
    """tmp_path root with data/ + scripts/trader/settings.json, mirroring the repo layout."""
    root = str(root)
    write_json(os.path.join(root, 'data', 'flip_digest.json'),
               {'generated_iso': '2026-01-01T00:00:00Z', 'flips': list(flips),
                'safe_flips': list(safe_flips)})
    write_json(os.path.join(root, 'data', 'deals.json'),
               {'generated_iso': '2026-01-01T00:00:00Z', 'deals': list(deals)})
    write_json(os.path.join(root, 'data', 'owned.json'), list(owned))
    if settings is not None:
        write_json(os.path.join(root, 'scripts', 'trader', 'settings.json'), settings)
    return root


CANON_FLIPS = [digest_row('lane_a', 175, 299, sales_day=52.5, queue_ahead=2),
               digest_row('lane_b', 60, 120, sales_day=64.5, queue_ahead=0, kind='spread'),
               digest_row('thin', 10, 15, sales_day=9.0)]
CANON_SAFE = [digest_row('lane_b', 60, 120, sales_day=64.5, queue_ahead=0, kind='spread'),
              digest_row('deep', 10, 40, sales_day=4.0)]
CANON_DEALS = [deal_row('lane_a', rank=0), deal_row('lane_b'), deal_row('thin', rank=0),
               deal_row('deep')]
CANON_OWNED = [{'slug': 'deep', 'count': 12}, {'slug': 'lane_a', 'count': 2}]


def canon_root(root, settings=None):
    return make_root(root, CANON_FLIPS, CANON_SAFE, CANON_DEALS, CANON_OWNED,
                     settings={'buy_budget_p': 300} if settings is None else settings)


def book(*offers, rank=None):
    """Fake orderbook: offers are platinum prices from online+ingame sellers."""
    return [{'type': 'sell', 'platinum': p, 'visible': True, 'rank': rank,
             'user': {'status': 'ingame'}} for p in offers]


def fake_fetch(prices_by_item, calls=None):
    def fetch(item_id):
        if calls is not None:
            calls.append(item_id)
        offers = prices_by_item.get(item_id) or []
        return book(*offers) if offers else []
    return fetch


# ------------------------------------------------------------- pure logic: settings

@pytest.mark.parametrize('settings, override, want', [
    ({'buy_budget_p': 250}, None, 250),
    ({'buy_budget_p': 250, 'buy_budget_cap_platinum': 100}, None, 250),
    ({'buy_budget_cap_platinum': 100}, None, 100),
    ({}, None, 300),
    (None, None, 300),
    ({'buy_budget_p': 'nope', 'buy_budget_cap_platinum': None}, None, 300),
    ({'buy_budget_p': 0}, None, 300),
    ({'buy_budget_p': 250}, 900, 900),
])
def test_budget_of_precedence_and_defaults(fl, settings, override, want):
    assert fl.budget_of(settings, override) == want


def test_load_settings_survives_missing_and_mid_write_files(fl, tmp_path):
    assert fl.load_settings(str(tmp_path / 'nope.json')) == {}
    broken = tmp_path / 'settings.json'
    broken.write_text('{"buy_budget_p": 300', encoding='utf-8')
    assert fl.load_settings(str(broken)) == {}


# ------------------------------------------------------------- pure logic: inputs

def test_owned_qty_sums_duplicate_rows(fl):
    assert fl.owned_qty([{'slug': 'a', 'count': 2}, {'slug': 'a'}, {'slug': 'b', 'count': 5},
                         {'name': 'no slug'}]) == {'a': 3, 'b': 5}
    assert fl.owned_qty(None) == {}


def test_deals_index_prefers_a_fresh_row(fl):
    idx = fl.deals_index([{'slug': 'a', 'stale': True}, {'slug': 'a'}])
    assert idx['a'].get('stale') is None
    assert fl.deals_index([{'slug': 'a', 'stale': True}])['a']['stale'] is True
    assert fl.deals_index(None) == {}


def test_digest_rows_rank_flips_first_then_safe_only(fl):
    dg = {'flips': [{'slug': 'a'}, {'slug': 'b'}], 'safe_flips': [{'slug': 'b'}, {'slug': 'c'}]}
    assert [r['slug'] for r in fl.digest_rows(dg)] == ['a', 'b', 'c']
    assert fl.digest_rows({}) == []


def test_lane_of_locks_rank_subtype_or_whole_lane(fl):
    label, fn = fl.lane_of({'lane': {'rank': 5, 'subtype': None}})
    assert (label, fn({'rank': 5}), fn({'rank': 0})) == ('rank 5', True, False)
    label, fn = fl.lane_of({'lane': {'rank': None, 'subtype': 'Intact'}})
    assert (label, fn({'subtype': 'Intact'}), fn({'subtype': 'Radiant'})) == ('intact', True, False)
    label, fn = fl.lane_of({'lane': {}})
    assert (label, fn({'rank': 3})) == ('', True)
    assert fl.lane_of(None)[0] == ''


def test_lane_floor_steps_past_a_bait_listing(fl):
    assert fl.lane_floor([10, 12, 14]) == (10, None)
    price, note = fl.lane_floor([1, 50, 60])
    assert price == 50 and 'bait' in note
    assert fl.lane_floor([1, 50]) == (1, None)            # too short to call bait
    assert fl.lane_floor([]) == (None, 'no listings in this lane')


@pytest.mark.parametrize('buy, sell, sales_day, owned, want', [
    (100, 109, 5, 0, 'profit 9p < 10p'),
    (100, 140, 1.5, 0, 'sales/day 1.5 < 2'),
    (100, 140, 5, 11, 'owned 11 > 10 copies'),
    (100, 140, 5, 10, None),
    (None, 140, 5, 0, 'no usable buy price'),
    (0, 140, 5, 0, 'no usable buy price'),
    (100, None, 5, 0, 'no relist target'),
    (100, 140, None, 0, 'no sales/day figure'),
])
def test_exit_reason_gates(fl, buy, sell, sales_day, owned, want):
    assert fl.exit_reason(buy, sell, sales_day, owned, 2.0, 10) == want


def test_roi_pct(fl):
    assert fl.roi_pct(40, 100) == 40.0
    assert fl.roi_pct(124, 175) == 70.9
    assert fl.roi_pct(10, 0) == 0.0


# ------------------------------------------------------------- pure logic: packing

def cand(slug, buy, sell, roi=None):
    return {'slug': slug, 'name': slug.upper(), 'kind': 'undercut', 'buy_at': buy, 'qty': 1,
            'relist_at': sell, 'profit_each': sell - buy,
            'roi_pct': fl_roi(buy, sell) if roi is None else roi, 'sales_day': 9.0,
            'queue_ahead': 0, 'live': False, 'score': 1.0, 'safe_score': 2.0, 'note': ''}


def fl_roi(buy, sell):
    return round((sell - buy) * 100.0 / buy, 1)


ROW_KEYS = ['slug', 'name', 'kind', 'buy_at', 'qty', 'relist_at', 'profit_each', 'roi_pct',
            'sales_day', 'why']


def test_pack_sorts_by_roi_and_emits_the_row_contract(fl):
    orders, skipped, spend = fl.pack([cand('lo', 100, 120), cand('hi', 20, 60), cand('mid', 50, 80)],
                                     1000, 5)
    assert [o['slug'] for o in orders] == ['hi', 'mid', 'lo']
    assert skipped == [] and spend == 170
    assert sorted(orders[0]) == sorted(ROW_KEYS)
    assert orders[0]['qty'] == 1 and orders[0]['profit_each'] == 40 and orders[0]['roi_pct'] == 200.0
    assert 'relist 60p' in orders[0]['why'] and 'digest floor' in orders[0]['why']


def test_pack_respects_the_order_cap(fl):
    cands = [cand('c%d' % i, 100, 140) for i in range(6)]
    orders, skipped, spend = fl.pack(cands, 1000, 5)
    assert (len(orders), spend) == (5, 500)
    assert skipped == [{'slug': 'c5', 'reason': 'order cap reached (5 orders)'}]


def test_pack_never_exceeds_the_budget(fl):
    orders, skipped, spend = fl.pack([cand('big', 400, 900), cand('small', 100, 140)], 300, 5)
    assert [o['slug'] for o in orders] == ['small'] and spend == 100
    assert skipped == [{'slug': 'big', 'reason': 'budget: 400p does not fit 300p left'}]


def test_pack_empty_candidates(fl):
    assert fl.pack([], 300, 5) == ([], [], 0)


# ------------------------------------------------------------- offline plan build

def test_build_plan_offline_filters_ranks_and_packs(fl):
    digest = {'flips': CANON_FLIPS, 'safe_flips': CANON_SAFE}
    orders, skipped, stats = fl.build_plan(digest, fl.deals_index(CANON_DEALS),
                                           fl.owned_qty(CANON_OWNED), 300)
    assert [o['slug'] for o in orders] == ['lane_b', 'lane_a']       # roi desc
    assert stats['planned_spend'] == 235
    assert {s['slug']: s['reason'] for s in skipped} == {
        'thin': 'profit 5p < 10p', 'deep': 'owned 12 > 10 copies'}
    assert stats['live_checked'] == 0 and stats['candidates'] == 4


def test_build_plan_offline_caps_orders_and_reports_every_skip(fl):
    flips = [digest_row('r%d' % i, 50, 100, sales_day=10.0) for i in range(8)]
    deals = [deal_row('r%d' % i) for i in range(8)]
    orders, skipped, stats = fl.build_plan({'flips': flips}, fl.deals_index(deals), {}, 1000)
    assert len(orders) == 5
    assert {s['reason'] for s in skipped} == {'order cap reached (5 orders)'}
    assert len(skipped) == 3
    assert stats['buyable'] == 8


def test_build_plan_offline_skips_stale_and_missing_deal_rows(fl):
    digest = {'flips': [digest_row('gone', 10, 60), digest_row('old', 10, 60)]}
    deals = fl.deals_index([deal_row('old', stale=True)])
    orders, skipped, _ = fl.build_plan(digest, deals, {}, 300)
    assert orders == []
    assert {s['slug']: s['reason'] for s in skipped} == {
        'gone': 'no deal row in deals.json (re-run deal_scanner.py)',
        'old': 'stale lane in deals.json (re-run deal_scanner.py + flip_digest.py)'}


# ------------------------------------------------------------- live (read-only) re-check

def test_build_plan_live_uses_the_live_floor(fl):
    digest = {'flips': CANON_FLIPS[:2], 'safe_flips': []}
    calls = []
    fetch = fake_fetch({'i-lane_a': [55, 90, 95], 'i-lane_b': [70, 80, 90]}, calls)
    orders, skipped, stats = fl.build_plan(digest, fl.deals_index(CANON_DEALS), {}, 300,
                                           fetch=fetch)
    assert calls == ['i-lane_a', 'i-lane_b']          # one GET per surviving candidate
    assert stats['live_checked'] == 2 and stats['live_floor_changed'] == 2
    assert [o['buy_at'] for o in orders] == [55, 70]
    assert all('live floor' in o['why'] for o in orders)


def test_build_plan_live_drops_a_lane_whose_floor_killed_the_profit(fl):
    digest = {'flips': [digest_row('lane_b', 60, 120, sales_day=64.5)]}
    orders, skipped, _ = fl.build_plan(digest, fl.deals_index(CANON_DEALS), {}, 300,
                                       fetch=fake_fetch({'i-lane_b': [115, 118, 120]}))
    assert orders == []
    assert skipped == [{'slug': 'lane_b', 'reason': 'live floor 115p: profit 5p < 10p'}]


def test_build_plan_live_steps_over_a_bait_floor_and_counts_it(fl):
    digest = {'flips': [digest_row('lane_b', 60, 120, sales_day=64.5)]}
    orders, skipped, stats = fl.build_plan(digest, fl.deals_index(CANON_DEALS), {}, 300,
                                           fetch=fake_fetch({'i-lane_b': [1, 50, 60]}))
    assert stats['bait_floors'] == 1
    assert orders[0]['buy_at'] == 50 and 'bait' in orders[0]['why']


def test_build_plan_live_is_bounded_by_max_fetch(fl):
    digest = {'flips': CANON_FLIPS[:2]}
    calls = []
    fl.build_plan(digest, fl.deals_index(CANON_DEALS), {}, 300,
                  fetch=fake_fetch({'i-lane_a': [55], 'i-lane_b': [55]}, calls), max_fetch=1)
    assert calls == ['i-lane_a']
    assert len(calls) <= 1                             # never more GETs than allowed


def test_build_plan_live_never_calls_the_network_offline(fl, monkeypatch):
    monkeypatch.setattr(fl, 'fetch_book', lambda item_id: pytest.fail('network on the offline path'))
    orders, _, _ = fl.build_plan({'flips': CANON_FLIPS[:2]}, fl.deals_index(CANON_DEALS), {}, 300)
    assert [o['slug'] for o in orders] == ['lane_b', 'lane_a']


# ------------------------------------------------------------- CLI / file contract

def test_cli_offline_writes_the_plan_contract(fl, tmp_path, capsys):
    root = canon_root(tmp_path)
    assert fl.main(['flipper.py', '--root', root]) == 0
    out = capsys.readouterr().out
    assert 'PLAN ONLY' in out and 'spend 235p of 300p budget' in out

    doc = read_json(os.path.join(root, 'data', 'flipper_plan.json'))
    assert isinstance(doc['generated'], int) and doc['generated'] > 0
    assert doc['generated_iso'].endswith('Z')
    assert doc['plan_only'] is True and doc['writes_to_wfm'] is False
    assert doc['mode'].startswith('offline')
    assert doc['budget'] == {'buy_budget_p': 300, 'planned_spend_p': 235, 'remaining_p': 65,
                             'max_orders': 5}
    assert [o['slug'] for o in doc['orders']] == ['lane_b', 'lane_a']
    assert sorted(doc['orders'][0]) == sorted(ROW_KEYS)
    assert doc['orders'][0]['name'] == 'Lane B' and doc['orders'][0]['qty'] == 1
    assert doc['orders'][0]['relist_at'] == 120 and doc['orders'][0]['profit_each'] == 60
    assert doc['orders'][0]['roi_pct'] == 100.0 and doc['orders'][0]['sales_day'] == 64.5
    assert doc['skipped'] == [{'slug': 'thin', 'reason': 'profit 5p < 10p'},
                              {'slug': 'deep', 'reason': 'owned 12 > 10 copies'}]
    assert doc['counts']['candidates'] == 4 and doc['counts']['orders'] == 2
    assert sum(o['buy_at'] for o in doc['orders']) == doc['budget']['planned_spend_p']
    assert doc['budget']['planned_spend_p'] <= doc['budget']['buy_budget_p']


def test_cli_orders_are_sorted_by_roi_desc(fl, tmp_path):
    root = make_root(tmp_path, [digest_row('a', 100, 140), digest_row('b', 50, 120),
                                digest_row('c', 20, 60)],
                     deals=[deal_row('a'), deal_row('b'), deal_row('c')],
                     settings={'buy_budget_p': 1000})
    assert fl.main(['flipper.py', '--root', root]) == 0
    doc = read_json(os.path.join(root, 'data', 'flipper_plan.json'))
    rois = [o['roi_pct'] for o in doc['orders']]
    assert rois == sorted(rois, reverse=True) and [o['slug'] for o in doc['orders']] == ['c', 'b', 'a']


def test_cli_budget_override_and_flag_echo(fl, tmp_path):
    root = canon_root(tmp_path)
    assert fl.main(['flipper.py', '--root', root, '--budget', '70']) == 0
    doc = read_json(os.path.join(root, 'data', 'flipper_plan.json'))
    assert doc['budget']['buy_budget_p'] == 70
    assert [o['slug'] for o in doc['orders']] == ['lane_b']       # 60p fits, 175p never will
    assert {'slug': 'lane_a', 'reason': 'budget: 175p does not fit 10p left'} in doc['skipped']


def test_cli_max_orders_override(fl, tmp_path):
    root = canon_root(tmp_path)
    assert fl.main(['flipper.py', '--root', root, '--max-orders', '1']) == 0
    doc = read_json(os.path.join(root, 'data', 'flipper_plan.json'))
    assert [o['slug'] for o in doc['orders']] == ['lane_b']
    assert doc['budget']['max_orders'] == 1
    assert {'slug': 'lane_a', 'reason': 'order cap reached (1 orders)'} in doc['skipped']


def test_cli_settings_missing_falls_back_to_300(fl, tmp_path):
    root = make_root(tmp_path, CANON_FLIPS[:2], deals=CANON_DEALS)      # no settings.json at all
    assert fl.main(['flipper.py', '--root', root]) == 0
    doc = read_json(os.path.join(root, 'data', 'flipper_plan.json'))
    assert doc['budget']['buy_budget_p'] == 300
    assert [o['slug'] for o in doc['orders']] == ['lane_b', 'lane_a']


def test_cli_settings_mid_write_falls_back_to_300(fl, tmp_path):
    root = make_root(tmp_path, CANON_FLIPS[:2], deals=CANON_DEALS)
    settings_dir = tmp_path / 'scripts' / 'trader'
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / 'settings.json').write_text('{"buy_budget_p": 3', encoding='utf-8')
    assert fl.main(['flipper.py', '--root', root]) == 0
    assert read_json(os.path.join(root, 'data', 'flipper_plan.json'))['budget']['buy_budget_p'] == 300


def test_cli_offline_never_touches_the_network(fl, tmp_path, monkeypatch):
    monkeypatch.setattr(fl, 'fetch_book', lambda item_id: pytest.fail('offline run hit the network'))
    root = canon_root(tmp_path)
    assert fl.main(['flipper.py', '--root', root]) == 0
    assert read_json(os.path.join(root, 'data', 'flipper_plan.json'))['counts']['live_checked'] == 0


def test_cli_live_uses_the_injected_fetch_book(fl, tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(fl, 'fetch_book',
                        fake_fetch({'i-lane_a': [55, 90, 95], 'i-lane_b': [70, 80, 90]}, calls))
    root = canon_root(tmp_path)
    assert fl.main(['flipper.py', '--root', root, '--live']) == 0
    assert calls == ['i-lane_a', 'i-lane_b']            # one read-only GET per candidate
    out = capsys.readouterr().out
    assert 'live: 2 floors re-checked' in out and 'PLAN ONLY' in out

    doc = read_json(os.path.join(root, 'data', 'flipper_plan.json'))
    assert doc['mode'].startswith('live')
    assert (doc['counts']['live_checked'], doc['counts']['live_floor_changed']) == (2, 2)
    assert [o['buy_at'] for o in doc['orders']] == [55, 70]
    assert all('live floor' in o['why'] for o in doc['orders'])


def test_cli_live_max_fetch_caps_the_calls(fl, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(fl, 'fetch_book',
                        fake_fetch({'i-lane_a': [55], 'i-lane_b': [55]}, calls))
    root = canon_root(tmp_path)
    assert fl.main(['flipper.py', '--root', root, '--live', '--max-fetch', '1']) == 0
    doc = read_json(os.path.join(root, 'data', 'flipper_plan.json'))
    assert calls == ['i-lane_a'] and doc['counts']['live_checked'] == 1
    assert {'slug': 'lane_b', 'reason': 'live re-check budget spent (max 1 calls)'} in doc['skipped']


def test_cli_live_survives_a_failed_book_fetch(fl, tmp_path, monkeypatch):
    def boom(item_id):
        raise OSError('connection reset by peer')
    monkeypatch.setattr(fl, 'fetch_book', boom)
    root = canon_root(tmp_path)
    assert fl.main(['flipper.py', '--root', root, '--live']) == 0
    doc = read_json(os.path.join(root, 'data', 'flipper_plan.json'))
    assert doc['orders'] == []
    reasons = {s['slug']: s['reason'] for s in doc['skipped']}
    assert 'book fetch failed' in reasons['lane_a'] and 'book fetch failed' in reasons['lane_b']
    assert reasons['thin'] == 'profit 5p < 10p'          # cheap filters still reported
    assert doc['counts']['live_checked'] == 0


def test_cli_writes_only_inside_the_given_root(fl, tmp_path):
    repo_plan = os.path.join(REPO, 'data', 'flipper_plan.json')
    before = os.path.getmtime(repo_plan) if os.path.exists(repo_plan) else None
    root = canon_root(tmp_path)
    assert fl.main(['flipper.py', '--root', root]) == 0
    assert os.path.exists(os.path.join(root, 'data', 'flipper_plan.json'))
    assert not os.path.exists(os.path.join(root, 'data', 'flipper_plan.json.tmp'))
    after = os.path.getmtime(repo_plan) if os.path.exists(repo_plan) else None
    assert before == after                                 # repo data/ untouched


def test_build_is_idempotent_for_unchanged_inputs(fl, tmp_path):
    root = canon_root(tmp_path)
    doc1 = fl.build(root)
    doc2 = fl.build(root)
    for doc in (doc1, doc2):
        doc.pop('generated')
        doc.pop('generated_iso')
    assert doc1 == doc2


def test_cli_missing_digest_exits_with_the_fix(fl, tmp_path):
    empty = tmp_path / 'empty'
    (empty / 'data').mkdir(parents=True)
    with pytest.raises(SystemExit) as e:
        fl.main(['flipper.py', '--root', str(empty)])
    assert 'flip_digest.json' in str(e.value) and 'deal_scanner' in str(e.value)


def test_cli_selftest_does_not_touch_the_repo_data(fl_raw):
    assert fl_raw.main(['flipper.py', '--selftest']) == 0


def test_selftest_returns_zero(fl_raw):
    assert fl_raw.selftest() == 0


def test_module_has_no_wfm_write_path(fl_raw):
    with open(FLIPPER_PY, encoding='utf-8') as fh:
        src = fh.read()
    assert fl_raw.write_paths(src) == []                # no signin, no POST, no order writes
    assert fl_raw.write_paths('s.create_order({})') == ['create_order']
    assert fl_raw.write_paths("Request(u, method='POST', data=b'')") == ['method=POST']
    assert fl_raw.write_paths("Request(u, method='GET')") == []
    assert fl_raw.write_paths('from wfm_session import signin') == ['import wfm_session']
