"""Trade > Orders - the live orderbook behind GET /api/orders.

Jay (2026-09-28): *"is there a list on trade that shows real buy orders and sell orders? with
usernames"* + *"the app needs to understand values of different ranks for a mod"*.

Two layers are pinned here:

  * scripts/orders.py - the access layer: the visibility gate (visible + quantity > 0), the
    two sort orders, the ingame > online > offline tie-break, the 40-row cap, the per-rank
    ladder agreeing with fetch_lanes (the same reduction as data/price_lanes.json), and the
    45s raw cache (a fresh cache means NO network call, an expired one refetches, and a
    failed fetch falls back to the stale cache rather than emptying the tab);
  * server.py - /api/orders never 500s and never hangs (6s budget; ok:true + an error string
    + empty lists when there is nothing to serve), /api/rank_values falls back to
    data/price_lanes.json so the ladder renders offline, /api/whisper builds through
    scripts/whisper.py with a 2s / 10-a-minute local limit and a 503 when it is not installed.
"""
import json
import os
import re
import subprocess
import sys
import time
import types

import pytest

from conftest import load_script, write_json

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(REPO, rel), encoding='utf-8') as fh:
        return fh.read()


@pytest.fixture
def mod():
    """scripts/orders.py as a fresh module (its own DATA, no repo data touched)."""
    return load_script('orders')


# ------------------------------------------------------------------ the 30-order fixture

def _o(kind, plat, qty, rank, status, name, visible=True, updated='2026-09-28T02:00:00Z'):
    return {'id': '%s-%s-%s-%s' % (kind, plat, qty, name), 'type': kind, 'platinum': plat,
            'quantity': qty, 'rank': rank, 'visible': visible, 'updatedAt': updated,
            'user': {'ingameName': name, 'slug': name.lower(), 'reputation': 5,
                     'platform': 'pc', 'status': status}}


def book_fixture():
    """30 orders: both sides, ranks 0/5/10, one visible:false, one quantity:0, mixed
    statuses and tied prices on both sides (so the tie-break is what decides the order)."""
    rows = [
        # ---- sells (12; HiddenVendor is hidden)
        _o('sell', 15, 6, 0, 'online', 'Delta'),
        _o('sell', 12, 4, 0, 'ingame', 'Alpha'),          # tied at 12: ingame first
        _o('sell', 12, 1, 0, 'offline', 'Beta'),
        _o('sell', 12, 2, 0, 'online', 'Gamma'),
        _o('sell', 5, 3, 0, 'ingame', 'Lambda'),          # the cheapest sell
        _o('sell', 30, 1, 5, 'ingame', 'Epsilon'),
        _o('sell', 31, 1, 5, 'offline', 'Zeta'),
        _o('sell', 32, 1, 5, 'online', 'Eta'),
        _o('sell', 90, 1, 10, 'ingame', 'Theta'),
        _o('sell', 88, 1, 10, 'online', 'Iota'),          # the cheapest rank-10 sell
        _o('sell', 120, 1, 10, 'offline', 'Kappa'),
        _o('sell', 999, 1, 0, 'ingame', 'HiddenVendor', visible=False),
        # ---- buys (18; GhostBuyer has quantity 0 - and the highest price of all)
        _o('buy', 70, 1, 10, 'ingame', 'BuyerIngame'),    # tied at 70: ingame >= online >= offline
        _o('buy', 70, 2, 10, 'online', 'BuyerOnline'),
        _o('buy', 70, 1, 10, 'offline', 'BuyerOffline'),
        _o('buy', 65, 1, 10, 'ingame', 'BuyerFour'),
        _o('buy', 55, 1, 10, 'ingame', 'BuyerFive'),
        _o('buy', 50, 1, 5, 'ingame', 'BuyerSix'),
        _o('buy', 22, 1, 5, 'offline', 'BuyerSeven'),
        _o('buy', 20, 1, 5, 'ingame', 'BuyerEight'),
        _o('buy', 18, 1, 5, 'online', 'BuyerNine'),
        _o('buy', 8, 1, 0, 'online', 'BuyerTen'),
        _o('buy', 7, 1, 0, 'offline', 'BuyerEleven'),
        _o('buy', 6, 1, 0, 'online', 'BuyerTwelve'),
        _o('buy', 5, 1, 0, 'offline', 'BuyerThirteen'),
        _o('buy', 4, 2, 0, 'ingame', 'BuyerFourteen'),
        _o('buy', 3, 1, 0, 'ingame', 'BuyerFifteen'),
        _o('buy', 2, 1, 0, 'online', 'BuyerSixteen'),
        _o('buy', 8, 1, 0, 'ingame', 'BuyerSeventeen'),   # tied at 8: ingame before BuyerTen
        _o('buy', 999, 0, 10, 'ingame', 'GhostBuyer'),
    ]
    assert len(rows) == 30
    return rows


def names(rows):
    return [r['user'] for r in rows]


# ------------------------------------------------------------------ the access layer

def test_live_drops_hidden_and_empty_orders(mod):
    live = mod.live(book_fixture())
    assert len(live) == 28, '30 fetched: one hidden, one quantity 0'
    who = [o['user']['ingameName'] for o in live]
    assert 'HiddenVendor' not in who and 'GhostBuyer' not in who


def test_book_never_shows_a_hidden_or_empty_order(mod):
    b = mod.book(book_fixture())
    assert 'HiddenVendor' not in names(b['sell'])
    assert 'GhostBuyer' not in names(b['buy']), 'a quantity-0 buy must not sit at the top'


def test_sell_ascends_and_buy_descends_by_platinum(mod):
    b = mod.book(book_fixture())
    assert [r['platinum'] for r in b['sell']] == [5, 12, 12, 12, 15, 30, 31, 32, 88, 90, 120]
    assert [r['platinum'] for r in b['buy']] == [70, 70, 70, 65, 55, 50, 22, 20, 18,
                                                 8, 8, 7, 6, 5, 4, 3, 2]


def test_status_breaks_a_price_tie(mod):
    b = mod.book(book_fixture())
    assert names(b['sell'])[1:4] == ['Alpha', 'Gamma', 'Beta'], 'ingame > online > offline'
    assert names(b['buy'])[:3] == ['BuyerIngame', 'BuyerOnline', 'BuyerOffline']
    assert names(b['buy'])[9:11] == ['BuyerSeventeen', 'BuyerTen'], 'ingame before online at 8'


def test_row_shape_carries_the_username(mod):
    r = mod.book(book_fixture())['sell'][0]
    assert set(r) == {'platinum', 'quantity', 'rank', 'user', 'reputation', 'status', 'updated_ts'}
    assert r == {'platinum': 5, 'quantity': 3, 'rank': 0, 'user': 'Lambda', 'reputation': 5,
                 'status': 'ingame', 'updated_ts': 1790560800}
    assert isinstance(mod.book(book_fixture())['buy'][0]['updated_ts'], int)


def test_rank_filter_follows_the_lane_rule(mod):
    b = mod.book(book_fixture(), rank=0)
    assert [r['platinum'] for r in b['sell']] == [5, 12, 12, 12, 15]
    assert [r['platinum'] for r in b['buy']] == [8, 8, 7, 6, 5, 4, 3, 2]
    assert [r['platinum'] for r in mod.book(book_fixture(), rank=10)['sell']] == [88, 90, 120]
    null_rank = _o('sell', 9, 1, None, 'ingame', 'NullRank')
    assert mod.rank_of(null_rank) == 0
    assert [r['platinum'] for r in mod.book([null_rank], rank=0)['sell']] == [9], \
        'a missing rank is rank 0 (the fetch_lanes rule)'


def test_counts_and_ranks_describe_the_live_book(mod):
    f = book_fixture()
    assert mod.counts(f) == {'sell': 11, 'buy': 17}
    assert mod.counts(f, rank=10) == {'sell': 3, 'buy': 5}
    assert mod.counts(f, rank=5) == {'sell': 3, 'buy': 4}
    assert mod.ranks(f) == [0, 5, 10]


def test_at_most_40_rows_a_side(mod):
    sells = [_o('sell', 100 + i, 1, 0, 'ingame', 'S%02d' % i) for i in range(45)]
    buys = [_o('buy', 200 + i, 1, 10, 'ingame', 'B%02d' % i) for i in range(45)]
    b = mod.book(sells + buys)
    assert len(b['sell']) == 40 and len(b['buy']) == 40
    assert names(b['sell'])[0] == 'S00' and names(b['sell'])[-1] == 'S39', 'the cheapest 40'
    assert names(b['buy'])[0] == 'B44' and names(b['buy'])[-1] == 'B05', 'the dearest 40'
    assert len(mod.book(sells, limit=9)['sell']) == 9
    assert len(mod.book(sells, limit=999)['sell']) == 40, 'limit cannot beat the cap'
    assert len(mod.book(sells, limit=0)['sell']) == 1, 'limit is clamped, never empty'


def test_values_is_the_same_ladder_fetch_lanes_writes(mod):
    fl = load_script('fetch_lanes')
    f = book_fixture()
    assert mod.values(f) == {str(k): v for k, v in sorted(fl.lane_summary(f).items())}
    vals = mod.values(f)
    assert vals['10'] == {'n_ask': 3, 'n_bid': 6, 'ask': 88, 'bid': 999, 'bid_low': 55}
    assert vals['0'] == {'n_ask': 5, 'n_bid': 8, 'ask': 5, 'bid': 8, 'bid_low': 2}
    # lane_summary keeps a visible quantity-0 row (the price_lanes.json rule) while book()
    # hides it - the ladder can never disagree with the stored lanes, the rows are honest
    assert 'GhostBuyer' not in names(mod.book(f)['buy'])


def test_a_junk_book_never_raises(mod):
    assert mod.live(None) == [] and mod.book(None) == {'sell': [], 'buy': []}
    assert mod.values(None) == {} and mod.counts(None) == {'sell': 0, 'buy': 0}
    junk = [None, 'junk', {'type': 'contract', 'visible': True, 'quantity': 1, 'platinum': 5},
            {'type': 'sell', 'visible': True, 'quantity': 1, 'platinum': 'x'},
            {'type': 'buy', 'visible': True, 'quantity': 2, 'platinum': 3, 'user': None}]
    b = mod.book(junk)
    assert b['sell'] == [] and [r['platinum'] for r in b['buy']] == [3]
    assert b['buy'][0]['user'] == '' and b['buy'][0]['status'] == 'offline'


# ------------------------------------------------------------------ the 45s cache

@pytest.fixture
def wired(mod, monkeypatch, tmp_path):
    """orders.py pointed at a throwaway data dir, with the network replaced by a counter."""
    d = tmp_path / 'data'
    monkeypatch.setattr(mod, 'DATA', str(d))
    calls = []

    def stub(slug, budget=mod.TIMEOUT):
        calls.append(slug)
        return book_fixture(), None

    monkeypatch.setattr(mod, 'fetch_book', stub)
    return mod, calls, d


def test_first_read_is_live_and_writes_the_raw_cache(wired):
    mod, calls, d = wired
    orders, ts = mod.fetch('primed_continuity')
    assert len(orders) == 30 and calls == ['primed_continuity'] and ts
    path = os.path.join(str(d), 'orders_cache', 'primed_continuity.json')
    assert os.path.isfile(path), 'raw cache lives in data/orders_cache/<slug>.json'
    with open(path, encoding='utf-8') as fh:
        doc = json.load(fh)
    assert doc['slug'] == 'primed_continuity' and doc['count'] == 30 and doc['orders'] == orders
    assert abs(doc['fetched'] - ts) <= 1 and doc['ua'].startswith('WFMTrader/')


def test_a_second_read_inside_the_ttl_does_not_refetch(wired):
    mod, calls, _ = wired
    first = mod.snapshot('primed_continuity')
    second = mod.snapshot('primed_continuity')
    assert first['source'] == 'live' and first['age_s'] == 0
    assert second['source'] == 'cache' and second['orders'] == first['orders']
    assert calls == ['primed_continuity'], 'no second network call inside the TTL'
    assert second['age_s'] is not None and second['age_s'] < mod.TTL
    assert mod.age_s(time.time() - 10) == 10 and mod.age_s(None) is None


def test_an_expired_cache_refetches(wired):
    mod, calls, _ = wired
    mod.write_cache('primed_continuity', book_fixture(), int(time.time()) - (mod.TTL + 1))
    snap = mod.snapshot('primed_continuity')
    assert calls == ['primed_continuity'], 'expired -> the network again'
    assert snap['source'] == 'live' and snap['age_s'] == 0
    assert mod.read_cache('primed_continuity')[1] > int(time.time()) - mod.TTL, 'cache refreshed'


def test_the_ttl_boundary(wired):
    mod, calls, _ = wired
    now = int(time.time())
    mod.write_cache('edge', book_fixture(), now - (mod.TTL - 1))
    assert mod.snapshot('edge')['source'] == 'cache' and calls == []
    mod.write_cache('edge', book_fixture(), now - (mod.TTL + 1))
    assert mod.snapshot('edge')['source'] == 'live' and calls == ['edge']


def test_a_failed_fetch_falls_back_to_the_stale_cache(wired, monkeypatch):
    mod, calls, _ = wired
    mod.write_cache('primed_continuity', book_fixture(), int(time.time()) - (mod.TTL + 5))
    monkeypatch.setattr(mod, 'fetch_book', lambda slug, budget=mod.TIMEOUT: (None, 'timeout'))
    snap = mod.snapshot('primed_continuity')
    assert calls == [] and snap['source'] == 'cache' and len(snap['orders']) == 30
    assert 'timeout' in snap['error'], 'the staleness is reported, not hidden'
    assert snap['age_s'] > mod.TTL


def test_total_failure_is_empty_with_an_error(wired, monkeypatch):
    mod, calls, _ = wired
    monkeypatch.setattr(mod, 'fetch_book', lambda slug, budget=mod.TIMEOUT: (None, 'http 500'))
    snap = mod.snapshot('primed_continuity')
    assert snap == {'orders': [], 'fetched_ts': None, 'age_s': None, 'source': None,
                    'error': 'http 500'}
    assert mod.fetch('primed_continuity') == ([], None)
    assert mod.snapshot('../etc/passwd')['error'] == 'bad slug'
    assert mod.snapshot('')['error'] == 'bad slug'
    assert calls == [], 'bad slugs never reach the network'


def test_retries_are_capped_at_two(mod, monkeypatch):
    monkeypatch.setattr(mod, 'SLEEP', 0.0)
    monkeypatch.setattr(mod, 'BACKOFF', 0.0)
    for code, want in ((404, 1), (503, 3)):
        calls = []

        def boom(url, timeout=None, code=code):
            calls.append(url)
            raise mod.urllib.error.HTTPError(url, code, 'nope', {}, None)

        monkeypatch.setattr(mod.urllib.request, 'urlopen', boom)
        data, err = mod._get('https://example.invalid/x', budget=10)
        assert data is None and err == 'http %d' % code and len(calls) == want, \
            'a 404 is permanent, a retryable status gets one try + two retries'


def test_the_network_budget_bounds_the_read(mod, monkeypatch):
    monkeypatch.setattr(mod, 'SLEEP', 0.0)
    monkeypatch.setattr(mod, 'BACKOFF', 0.0)

    def slow(url, timeout=None):
        time.sleep(0.15)
        raise OSError('no route to host')

    monkeypatch.setattr(mod.urllib.request, 'urlopen', slow)
    t0 = time.time()
    data, err = mod._get('https://example.invalid/x', budget=0.4)
    assert data is None and err and (time.time() - t0) < 1.2, 'the budget caps the whole read'


def test_the_cli_selftest_passes_offline():
    r = subprocess.run([sys.executable, os.path.join(REPO, 'scripts', 'orders.py'), '--selftest'],
                       capture_output=True, text=True, timeout=120, cwd=REPO)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'selftest: PASS' in r.stdout


# ------------------------------------------------------------------ GET /api/orders

@pytest.fixture
def offline_orders(server_mod, monkeypatch, tmp_path):
    """server_mod with the orderbook pointed at a throwaway data dir and the network dead."""
    ob = server_mod.orderbook
    assert ob is not None, 'server.py must find scripts/orders.py'
    monkeypatch.setattr(ob, 'DATA', str(tmp_path / 'orders_data'))
    monkeypatch.setattr(ob, 'fetch_book', lambda slug, budget=ob.TIMEOUT: (None, 'offline'))
    return server_mod


def test_orders_payload_serves_the_book_with_rows_users_and_values(offline_orders):
    api = offline_orders
    api.orderbook.write_cache('primed_continuity', book_fixture(), int(time.time()))
    p = api.orders_payload({'item': ['primed_continuity'], 'rank': ['10'], 'limit': ['3']})
    assert p['ok'] is True and p['item'] == 'primed_continuity'
    assert p['source'] == 'cache' and p['age_s'] < api.orderbook.TTL
    assert p['counts'] == {'sell': 3, 'buy': 5}, 'counts follow the rank filter'
    assert p['ranks'] == [0, 5, 10]
    assert [r['platinum'] for r in p['sell']] == [88, 90, 120], 'sell ascends, limit 3'
    assert [r['platinum'] for r in p['buy']] == [70, 70, 70], 'buy descends, limit 3'
    assert p['sell'][0]['user'] == 'Iota' and p['buy'][0]['user'] == 'BuyerIngame'
    assert p['values']['10']['ask'] == 88 and set(p['values']) == {'0', '5', '10'}
    assert 'error' not in p
    json.dumps(p)                                        # the route must always be serialisable


def test_orders_payload_defaults_to_the_whole_book(offline_orders):
    api = offline_orders
    api.orderbook.write_cache('primed_continuity', book_fixture(), int(time.time()))
    p = api.orders_payload({'item': ['primed_continuity']})
    assert p['counts'] == {'sell': 11, 'buy': 17}
    assert len(p['sell']) == 11 and len(p['buy']) == 17, '30 fetched, the hidden/empty are gone'
    assert api._limit_arg('999') == (api.ORDERS_MAX, None) == (40, None)
    assert api._limit_arg('3')[0] == 3 and api._rank_arg('all') == (None, None)


def test_orders_payload_total_failure_is_ok_true_with_empty_lists(offline_orders):
    p = offline_orders.orders_payload({'item': ['primed_continuity']})
    assert p['ok'] is True, 'an outage is not an HTTP failure'
    assert p['error'] == 'offline' and p['sell'] == [] and p['buy'] == []
    assert p['source'] is None and p['age_s'] is None and p['values'] == {}
    assert p['counts'] == {'sell': 0, 'buy': 0} and p['ranks'] == []
    json.dumps(p)


def test_orders_payload_bad_input_is_ok_false_never_a_raise(offline_orders):
    api = offline_orders
    assert api.orders_payload({}) == {'ok': False, 'error': 'item required'}
    assert api.orders_payload({'item': ['  ']})['ok'] is False
    assert api.orders_payload({'item': ['Not A Slug']})['ok'] is False
    assert api.orders_payload({'item': ['x'], 'rank': ['nine']})['ok'] is False
    assert api.orders_payload({'item': ['x'], 'limit': ['lots']})['ok'] is False
    assert api._limit_arg('-5') == (1, None), 'a numeric limit is clamped into 1..40'


def test_orders_payload_unknown_item_is_not_an_empty_book(offline_orders, monkeypatch):
    ob = offline_orders.orderbook
    monkeypatch.setattr(ob, 'fetch_book', lambda slug, budget=ob.TIMEOUT: (None, 'http 404'))
    p = offline_orders.orders_payload({'item': ['not_a_real_slug']})
    assert p == {'ok': False, 'item': 'not_a_real_slug', 'error': 'unknown item'}


def test_orders_payload_serves_a_stale_cache_with_the_reason(offline_orders, monkeypatch):
    api = offline_orders
    api.orderbook.write_cache('primed_continuity', book_fixture(),
                              int(time.time()) - (api.orderbook.TTL + 30))
    p = api.orders_payload({'item': ['primed_continuity']})
    assert p['ok'] is True and p['source'] == 'cache' and len(p['sell']) == 11
    assert 'offline' in p['error'], 'the tab can say the live read failed'


# ------------------------------------------------------------------ GET /api/rank_values

def test_rank_values_prefers_the_live_book(offline_orders):
    api = offline_orders
    api.orderbook.write_cache('primed_continuity', book_fixture(), int(time.time()))
    p = api.rank_values_payload({'item': ['primed_continuity']})
    assert p['ok'] is True and p['source'] == 'orders'
    assert p['values']['10']['ask'] == 88 and p['values']['0']['bid'] == 8
    json.dumps(p)


def test_rank_values_falls_back_to_price_lanes(offline_orders):
    api = offline_orders
    write_json(os.path.join(api.DATA, 'price_lanes.json'), {'version': 1, 'items': {
        'primed_continuity': {'max_rank': 10, 'lanes': {'10': {'n_ask': 575, 'n_bid': 67,
                                                              'ask': 90, 'bid': 100, 'bid_low': 1}}}}})
    p = api.rank_values_payload({'item': ['primed_continuity']})
    assert p['ok'] is True and p['source'] == 'price_lanes'
    assert p['values'] == {'10': {'n_ask': 575, 'n_bid': 67, 'ask': 90, 'bid': 100, 'bid_low': 1}}


def test_rank_values_for_an_item_in_neither_store(offline_orders, monkeypatch):
    api = offline_orders
    monkeypatch.setattr(api.orderbook, 'fetch_book',
                        lambda slug, budget=api.orderbook.TIMEOUT: (None, 'http 404'))
    p = api.rank_values_payload({'item': ['not_a_real_slug']})
    assert p['ok'] is False and p['values'] == {} and p['error'] == 'http 404'
    assert api.rank_values_payload({}) == {'ok': False, 'error': 'item required'}
    assert api.rank_values_payload({'item': ['Bad Slug!']})['ok'] is False


# ------------------------------------------------------------------ POST /api/whisper

def _install_whisper(monkeypatch, sent=(True, 'sent to SampleTennoIX'), copied=True, with_line=True):
    """A stand-in scripts/whisper.py that records exactly how the route calls it.

    with_line=False models an older module without line(): the route must fall back to the bare
    message rather than blow up.
    """
    rec = {'message': [], 'copy': [], 'send': [], 'line': []}
    fake = types.ModuleType('whisper')

    def message(item, price, kind, rank):
        rec['message'].append((item, price, kind, rank))
        return '%s %s for %sp' % (kind.upper(), item, price)

    def line(user, item, price, kind, rank=None):
        rec['line'].append((user, item, price, kind, rank))
        # built here, not via message(): the route calls both and each call is recorded once
        return '/w %s %s %s for %sp' % (user, kind.upper(), item, price)

    def copy(text):
        rec['copy'].append(text)
        return copied

    def send(text, item=None, price=None, kind=None, user=None):
        rec['send'].append((text, user))
        return sent

    fake.message, fake.copy, fake.send = message, copy, send
    if with_line:
        fake.line = line
    monkeypatch.setitem(sys.modules, 'whisper', fake)
    return rec


@pytest.fixture
def quiet_whisper(server_mod):
    """The local limiter is process state - start every whisper test from a clean slate.

    _NAME_BY_SLUG is pinned empty so the route tests pin the passthrough (a caller that already
    sends a display name keeps it) instead of depending on data/wfm_items_v2.json being on disk.
    """
    server_mod._whisper_last[0] = 0.0
    server_mod._whisper_minute.clear()
    server_mod._NAME_BY_SLUG = {}
    return server_mod


BODY = {'item': 'primed_continuity', 'user': 'SampleTennoIX', 'price': 40, 'kind': 'sell',
        'rank': 10}


def test_whisper_missing_is_a_503(quiet_whisper, monkeypatch):
    monkeypatch.setitem(sys.modules, 'whisper', None)      # import whisper -> ImportError
    code, out = quiet_whisper.whisper_post(dict(BODY))
    assert code == 503 and out == {'ok': False, 'error': 'whisper not installed'}


def test_whisper_copy_mode_builds_and_copies_only(quiet_whisper, monkeypatch):
    rec = _install_whisper(monkeypatch)
    code, out = quiet_whisper.whisper_post(dict(BODY, mode='copy'))
    assert code == 200 and out == {'ok': True, 'message': 'SELL primed_continuity for 40p',
                                   'line': '/w SampleTennoIX SELL primed_continuity for 40p',
                                   'copied': True, 'sent': False, 'reason': ''}
    assert rec['message'] == [('primed_continuity', 40, 'sell', 10)]
    # the clipboard gets the whole paste (whisper command included), like the site's copy button
    assert rec['copy'] == ['/w SampleTennoIX SELL primed_continuity for 40p'] and rec['send'] == []
    assert rec['line'] == [('SampleTennoIX', 'primed_continuity', 40, 'sell', 10)]


def test_a_slug_is_named_the_way_the_site_names_it(quiet_whisper, monkeypatch):
    """The tab sends the slug; the paste has to read 'Primed Continuity (rank 10)', not the slug."""
    monkeypatch.setattr(quiet_whisper, '_NAME_BY_SLUG',
                        {'primed_continuity': 'Primed Continuity'})
    _install_whisper(monkeypatch)
    code, out = quiet_whisper.whisper_post(dict(BODY, mode='copy'))
    assert code == 200
    assert out['line'] == '/w SampleTennoIX SELL Primed Continuity for 40p'


def test_an_older_whisper_module_without_line_still_works(quiet_whisper, monkeypatch):
    """A stale module on disk has no line(): the route falls back to the bare message, never 500s."""
    rec = _install_whisper(monkeypatch, with_line=False)
    code, out = quiet_whisper.whisper_post(dict(BODY, mode='copy'))
    assert code == 200 and out['line'] == out['message'] == 'SELL primed_continuity for 40p'
    assert rec['copy'] == ['SELL primed_continuity for 40p']


def test_whisper_send_mode_sends_once_and_reports_the_reason(quiet_whisper, monkeypatch):
    rec = _install_whisper(monkeypatch)
    code, out = quiet_whisper.whisper_post(dict(BODY, mode='send'))
    assert code == 200 and out['sent'] is True and out['copied'] is True
    assert out['reason'] == 'sent to SampleTennoIX'
    assert out['line'] == rec['copy'][0] and out['line'] == rec['send'][0][0]
    assert out['line'].startswith('/w SampleTennoIX ')
    assert len(rec['send']) == 1, 'send is called once, not once per field'
    assert rec['send'][0][1] == 'SampleTennoIX', 'the ledger row carries the user'


def test_whisper_send_failure_is_reported_not_raised(quiet_whisper, monkeypatch):
    _install_whisper(monkeypatch, sent=(False, 'wfm is not signed in'), copied=False)
    code, out = quiet_whisper.whisper_post(dict(BODY, mode='send'))
    assert code == 200 and out['ok'] is True and out['sent'] is False and out['copied'] is False
    assert out['reason'] == 'wfm is not signed in'


def test_whisper_mode_defaults_to_copy_and_rank_is_optional(quiet_whisper, monkeypatch):
    rec = _install_whisper(monkeypatch)
    code, out = quiet_whisper.whisper_post({'item': 'primed_continuity', 'user': 'Someone',
                                            'price': '40', 'kind': 'BUY'})
    assert code == 200 and out['sent'] is False
    assert rec['message'] == [('primed_continuity', 40, 'buy', None)]


def test_whisper_bad_input_never_500s(quiet_whisper, monkeypatch):
    _install_whisper(monkeypatch)
    bad = [({}, 'item and user required'),
           ({'item': 'x'}, 'item and user required'),
           ({'item': 'x', 'user': 'y'}, "kind must be 'buy' or 'sell'"),
           ({'item': 'x', 'user': 'y', 'kind': 'sell'}, 'price must be a number'),
           ({'item': 'x', 'user': 'y', 'kind': 'sell', 'price': True}, 'price must be a number'),
           ({'item': 'x', 'user': 'y', 'kind': 'sell', 'price': 0}, 'price must be at least 1'),
           ({'item': 'x', 'user': 'y', 'kind': 'sell', 'price': 5, 'rank': 'ten'},
            'rank must be a number'),
           ({'item': 'x', 'user': 'y', 'kind': 'sell', 'price': 5, 'mode': 'shout'},
            "mode must be 'copy' or 'send'")]
    for body, err in bad:
        code, out = quiet_whisper.whisper_post(body)
        assert code == 400 and out['ok'] is False and out['error'] == err, body
    assert quiet_whisper.whisper_post(None)[0] == 400 and quiet_whisper.whisper_post('junk')[0] == 400
    assert quiet_whisper._whisper_minute == [], 'a refused call does not spend the budget'


def test_whisper_is_rate_limited_two_seconds(quiet_whisper, monkeypatch):
    _install_whisper(monkeypatch)
    assert quiet_whisper.whisper_post(dict(BODY))[0] == 200
    code, out = quiet_whisper.whisper_post(dict(BODY))
    assert code == 429 and out['ok'] is False and 'one whisper every 2s' in out['reason']
    assert out['error'] == out['reason']
    quiet_whisper._whisper_last[0] = 0.0                   # the 2s elapse
    assert quiet_whisper.whisper_post(dict(BODY))[0] == 200


def test_whisper_is_rate_limited_ten_a_minute(quiet_whisper, monkeypatch):
    _install_whisper(monkeypatch)
    for i in range(quiet_whisper.WHISPER_PER_MIN):
        quiet_whisper._whisper_last[0] = 0.0                # the 2s elapse; the minute does not
        assert quiet_whisper.whisper_post(dict(BODY))[0] == 200, 'call %d' % i
    quiet_whisper._whisper_last[0] = 0.0
    code, out = quiet_whisper.whisper_post(dict(BODY))
    assert code == 429 and 'minute' in out['reason'] and len(quiet_whisper._whisper_minute) == 10
    quiet_whisper._whisper_minute[:] = [time.time() - 61]   # the window rolls over
    assert quiet_whisper.whisper_post(dict(BODY))[0] == 200


# ------------------------------------------------------------------ wiring

def test_the_new_routes_are_wired_and_the_old_ones_are_untouched():
    src = read('server.py')
    assert "if p == '/api/orders': return self._send(200, orders_payload(parse_qs(urlparse(self.path).query)))" in src
    assert "if p == '/api/rank_values': return self._send(200, rank_values_payload(parse_qs(urlparse(self.path).query)))" in src
    assert re.search(r"if p == '/api/whisper':\s*\n\s*try:\s*\n\s*ln = int\(self\.headers\.get\('Content-Length'\)", src)
    assert 'import orders as orderbook' in src and 'def orders_payload(query=None):' in src
    assert 'def rank_values_payload(query=None):' in src and 'def whisper_post(body):' in src
    assert 'ORDERS_TIMEOUT = 6.0' in src and 'ORDERS_MAX = 40' in src
    assert 'WHISPER_GAP = 2.0' in src and 'WHISPER_PER_MIN = 10' in src
    for line in ("if p == '/api/summary': return self._send(200, summary_payload())",
                 "if p == '/api/chat': return self._send(200, chat_payload())",
                 "if p == '/api/profiles': return self._send(200, profiles_payload())",
                 "if p == '/api/trader': return self._send(200, trader_payload())",
                 "if p == '/api/report': return self._send(200, jload(os.path.join(DATA, 'report.json')) or {})"):
        assert line in src, 'an existing route changed: ' + line


def test_the_whisper_module_is_imported_lazily():
    src = read('server.py')
    m = re.search(r'def _load_whisper\(\):\n(.*?)\n\n', src, re.S)
    assert m and 'import whisper' in m.group(1), 'whisper is imported on use, not at startup'
    assert re.search(r'whisper, err = _load_whisper\(\)', src)
