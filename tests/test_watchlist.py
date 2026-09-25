"""scripts/watchlist.py: config contract, status/distance math, alert feed, offline safety.

No network and no repo data are touched: every run is pointed at tmp_path (module globals
DATA / OUT_PATH / CONFIG_PATH) and the live fallback is either offline or fed a canned
urlopen response.

The alert feed is the machine-readable contract a later notifier consumes, so it gets the
strictest assertions here (keys, one-line messages, target mapping, ordering, coverage).
"""
import hashlib
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from conftest import REPO, SCRIPTS, load_script, read_json, write_json

REPO_OUT = os.path.join(REPO, 'data', 'watchlist.json')
REPO_CFG = os.path.join(REPO, 'data', 'watchlist_config.json')

PRICES = {
    'cheap_item': {'wts': 30, 'wtb': 20, 'n_sell': 5, 'n_buy': 2},     # <= max_buy 40  -> HIT_BUY
    'rich_item': {'wts': 120, 'wtb': 90, 'n_sell': 4, 'n_buy': 3},     # >= min_sell 90 -> HIT_SELL
    'mid_item': {'wts': 50, 'wtb': 44, 'n_sell': 6, 'n_buy': 1},       # inside band    -> WAIT 10p
    'both_item': {'wts': 100, 'wtb': 60, 'n_sell': 3, 'n_buy': 2},     # inverted band  -> HIT_BUY
    'cand_cached': {'wts': 22, 'wtb': 18, 'n_sell': 5, 'n_buy': 0},
    'pricey_item': {'wts': 95, 'wtb': 70, 'n_sell': 2, 'n_buy': 1},    # >= min_sell 90 -> HIT_SELL
    'null_floor': {'wts': None, 'wtb': 10, 'n_sell': 0, 'n_buy': 1},   # cached but no floor
}
STATS = {
    'cheap_item': {'vol48': 20, 'med48': 33.3333},
    'rich_item': {'vol48': 7, 'median': 118.0},
    'mid_item': {'vol48': 12, 'avg48': 51.0},
    'both_item': {'vol48': 3, 'med48': 99.9},
    'cand_cached': {'vol48': 15, 'med48': 24.0},
    'pricey_item': {'vol48': 9, 'med48': 96.5},
}
CONFIG = {
    '_comment': 'test fixture',
    'entries': [
        {'slug': 'cheap_item', 'max_buy': 40, 'min_sell': 90, 'note': 'buy the dip'},
        {'slug': 'rich_item', 'max_buy': 40, 'min_sell': 90, 'note': ''},
        {'slug': 'mid_item', 'max_buy': 40, 'min_sell': 90},
        {'slug': 'both_item', 'max_buy': 100, 'min_sell': 100, 'note': 'inverted'},
        {'slug': 'pricey_item', 'max_buy': 40, 'min_sell': 90},
        {'slug': 'null_floor', 'max_buy': 40},
        {'slug': 'missing_floor', 'max_buy': 40},
        {'slug': 'sell_only', 'min_sell': 500, 'note': 'sell side only'},
    ],
}
FLIPS = {
    'flips': [
        {'slug': 'cand_cached', 'name': 'Cand Cached', 'kind': 'undercut',
         'buy_at': 40, 'sell_at': 120, 'score': 90.0},
        {'slug': 'cand_right', 'name': 'Cand Right', 'kind': 'spread',
         'buy_at': 100, 'sell_at': 260, 'score': 80.0},
    ],
}
DEALS = {
    'deals': [
        {'slug': 'cand_cached', 'name': 'Cand Cached', 'kind': 'spread',
         'floor_sell': 20, 'target_price': 100, 'score': 300.0},
        {'slug': 'cand_deal', 'name': 'Cand Deal', 'kind': 'spread',
         'floor_sell': 60, 'target_price': 150, 'score': 500.0},
    ],
}
CATALOG = {'data': [
    {'slug': slug, 'id': 'id-%s' % slug, 'i18n': {'en': {'name': slug.replace('_', ' ').title()}}}
    for slug in list(PRICES) + ['cand_cached', 'cand_right', 'cand_deal']
]}
CANNED_TOP = {'data': {'sell': [{'platinum': 12, 'visible': True}, {'platinum': 9, 'visible': False},
                                {'platinum': 8, 'visible': True}],
                       'buy': [{'platinum': 5, 'visible': True}, {'platinum': 4, 'visible': True}]}}


class FakeResponse(object):
    """Minimal urlopen() stand-in (context manager + read())."""

    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def wl(tmp_path, monkeypatch, data_dir):
    """watchlist.py loaded with every path global pointed into tmp_path."""
    mod = load_script('watchlist', monkeypatch=monkeypatch)
    monkeypatch.setattr(mod, 'DATA', str(data_dir))
    monkeypatch.setattr(mod, 'OUT_PATH', str(data_dir / 'watchlist.json'))
    monkeypatch.setattr(mod, 'CONFIG_PATH', str(data_dir / 'watchlist_config.json'))
    return SimpleNamespace(mod=mod, data=data_dir, out=data_dir / 'watchlist.json',
                           cfg=data_dir / 'watchlist_config.json')


def seed(wl, config=CONFIG, prices=PRICES, stats=STATS, flips=FLIPS, deals=DEALS, catalog=True):
    if config is not None:
        write_json(wl.cfg, config)
    write_json(wl.data / 'prices.json', prices)
    write_json(wl.data / 'stats.json', stats)
    if flips is not None:
        write_json(wl.data / 'flip_digest.json', flips)
    if deals is not None:
        write_json(wl.data / 'deals.json', deals)
    if catalog:
        write_json(wl.data / 'wfm_items_v2.json', CATALOG)


def sha(path):
    try:
        with open(str(path), 'rb') as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def run(wl, argv=('--offline',)):
    return wl.mod.main(list(argv))


def entries_of(wl):
    return {e['slug']: e for e in read_json(wl.out)['entries']}


# ------------------------------------------------------------------ module contract

def test_paths_and_caps_are_repo_relative():
    mod = load_script('watchlist')                                  # module constants, unpatched
    assert mod.OUT_PATH.endswith(os.path.join('data', 'watchlist.json'))
    assert mod.CONFIG_PATH.endswith(os.path.join('data', 'watchlist_config.json'))
    assert mod.OUT_PATH.startswith(REPO) and mod.MAX_LIVE_FETCHES == 60 and mod.MIN_SLEEP == 0.35
    assert mod.STATUSES == ('HIT_BUY', 'HIT_SELL', 'WAIT')
    assert mod.LEVELS == ('buy', 'sell')
    assert list(mod.ENTRY_KEYS)[:4] == ['slug', 'name', 'floor', 'median']


# ------------------------------------------------------------------ config lifecycle

def test_first_run_creates_config_empty_and_keeps_it(wl):
    seed(wl, config=None)
    assert run(wl) == 0

    cfg = read_json(wl.cfg)
    assert list(cfg) == ['_comment', 'entries'] and cfg['entries'] == []
    doc = read_json(wl.out)
    assert doc['config']['created'] is True and doc['entries'] == [] and doc['alerts'] == []
    assert doc['summary']['total'] == 0
    assert 'never rewritten' in cfg['_comment'] and wl.mod.CONFIG_COMMENT in cfg['_comment']


def test_existing_config_is_never_overwritten(wl):
    seed(wl)
    before = sha(wl.cfg)

    assert run(wl) == 0
    doc = read_json(wl.out)

    assert doc['config']['created'] is False
    assert sha(wl.cfg) == before                       # byte-identical, not reformatted
    assert read_json(wl.cfg) == CONFIG
    assert doc['config']['raw_entries'] == len(CONFIG['entries'])


def test_unreadable_config_is_reported_not_clobbered(wl):
    seed(wl)
    wl.cfg.write_text('{ not json at all', encoding='utf-8')
    before = sha(wl.cfg)

    assert run(wl) == 0
    doc = read_json(wl.out)

    assert sha(wl.cfg) == before                       # left exactly as it was
    assert doc['config']['entries'] == 0 and doc['config']['warnings'] == []
    assert doc['entries'] == [] and doc['summary']['total'] == 0


# ------------------------------------------------------------------ statuses

def test_status_and_distance_per_row(wl):
    seed(wl)
    run(wl)
    entry = entries_of(wl)

    assert entry['cheap_item']['status'] == 'HIT_BUY'
    assert entry['cheap_item']['distance_p'] == 10           # 40 - 30 headroom under the cap
    assert entry['rich_item']['status'] == 'HIT_SELL'
    assert entry['rich_item']['distance_p'] == 30            # 120 - 90 over the target
    assert entry['pricey_item']['status'] == 'HIT_SELL' and entry['pricey_item']['distance_p'] == 5
    assert entry['mid_item']['status'] == 'WAIT' and entry['mid_item']['distance_p'] == 10
    assert entry['both_item']['status'] == 'HIT_BUY'         # buy precedence on an inverted band
    assert entry['both_item']['distance_p'] == 0
    assert entry['sell_only']['status'] == 'WAIT' and entry['sell_only']['max_buy'] is None
    assert {e['status'] for e in entry.values()} <= set(wl.mod.STATUSES)


def test_floor_comes_from_prices_json_with_provenance(wl):
    seed(wl)
    run(wl)
    entry = entries_of(wl)

    assert entry['cheap_item']['floor'] == 30 and entry['cheap_item']['floor_src'] == 'prices_json'
    assert entry['cheap_item']['n_sell'] == 5 and entry['cheap_item']['floor_note'] is None
    assert entry['cheap_item']['cache_note'] == 'cached'
    assert entry['cheap_item']['median'] == 33.3             # med48 preferred, rounded
    assert entry['rich_item']['median'] == 118.0             # falls back to median
    assert entry['mid_item']['median'] == 51.0               # falls back to avg48
    assert entry['mid_item']['vol48'] == 12


def test_missing_floor_stays_wait_and_is_noted(wl):
    seed(wl, config={'entries': [{'slug': 'null_floor', 'max_buy': 40},
                                 {'slug': 'never_priced', 'max_buy': 40}]})
    run(wl)
    entry = entries_of(wl)

    for slug, cache_note in (('null_floor', 'cached_floor_null'), ('never_priced', 'not_cached')):
        assert entry[slug]['status'] == 'WAIT'
        assert entry[slug]['floor'] is None and entry[slug]['distance_p'] is None
        assert entry[slug]['floor_src'] == 'none' and entry[slug]['alerts'] == []
        assert entry[slug]['cache_note'] == cache_note         # snapshot state
        assert entry[slug]['floor_note'] == 'offline'          # why the live retry did not happen


def test_config_warnings_skip_junk_but_keep_valid_rows(wl):
    seed(wl, config={'entries': [
        {'slug': 'cheap_item', 'max_buy': 40},
        {'slug': '  ', 'max_buy': 10},
        {'max_buy': 10},
        {'slug': 'nope', 'max_buy': 0, 'min_sell': -3},
        {'slug': 'cheap_item', 'max_buy': 999},
        'not-an-object',
        {'slug': 'both_item', 'max_buy': 100, 'min_sell': 100},
    ]})
    run(wl)
    doc = read_json(wl.out)
    warns = ' ; '.join(doc['config']['warnings'])

    assert doc['summary']['total'] == 2 and doc['config']['entries'] == 2
    assert doc['config']['raw_entries'] == 7
    assert 'no usable slug' in warns and 'both missing or <= 0' in warns
    assert 'duplicate config row' in warns and 'expected an object' in warns
    assert 'inverted band' in warns
    assert entries_of(wl)['cheap_item']['max_buy'] == 40      # first row wins, not 999


def test_notes_and_bands_are_kept_and_flattened(wl):
    seed(wl, config={'entries': [
        {'slug': 'cheap_item', 'max_buy': 40, 'min_sell': 90, 'note': 'watch\nthis one'},
        {'slug': 'rich_item', 'max_buy': 40, 'min_sell': 90},
    ]})
    run(wl)
    entry = entries_of(wl)

    assert entry['cheap_item']['note'] == 'watch this one'    # one line for the UI/feed
    assert entry['cheap_item']['band'] == 'buy at or below 40p / sell at or above 90p'
    assert entry['rich_item']['note'] == '' and entry['rich_item']['band'].startswith('buy at or below')


# ------------------------------------------------------------------ alert feed

def test_alert_feed_shape_targets_and_order(wl):
    seed(wl)
    run(wl)
    doc = read_json(wl.out)
    alerts = doc['alerts']
    entry = entries_of(wl)

    for alert in alerts:
        assert list(alert) == list(wl.mod.ALERT_KEYS)
        assert alert['level'] in wl.mod.LEVELS
        assert alert['name'] == entry[alert['slug']]['name']
        assert alert['floor'] == entry[alert['slug']]['floor']
        assert alert['target'] == (entry[alert['slug']]['max_buy'] if alert['level'] == 'buy'
                                   else entry[alert['slug']]['min_sell'])
        assert '\n' not in alert['message'] and 0 < len(alert['message']) <= wl.mod.MAX_MSG
        assert alert['message'] in entry[alert['slug']]['alerts']

    assert [a['level'] for a in alerts] == ['buy', 'buy', 'sell', 'sell', 'sell']
    assert [a['floor'] for a in alerts] == [30, 100, 120, 100, 95]     # buys asc, sells desc
    assert alerts == wl.mod.sort_alerts(alerts)                       # deterministic re-sort
    assert alerts[0]['message'] == ('BUY Cheap Item: floor 30p <= max_buy 40p (10p under your cap) '
                                    '| med48 33.3p | vol48 20')
    assert doc['summary']['alerts_total'] == len(alerts) == 5
    assert all(e['alerts'] == [] for e in doc['entries'] if e['floor'] is None)


def test_inverted_band_emits_both_alerts(wl):
    seed(wl, config={'entries': [{'slug': 'both_item', 'max_buy': 100, 'min_sell': 100}]})
    run(wl)
    doc = read_json(wl.out)

    assert [a['level'] for a in doc['alerts']] == ['buy', 'sell']
    assert [a['target'] for a in doc['alerts']] == [100, 100]
    assert doc['entries'][0]['status'] == 'HIT_BUY' and len(doc['entries'][0]['alerts']) == 2
    assert doc['summary']['hit_buy'] == 1 and doc['summary']['hit_sell'] == 0


def test_summary_and_self_check_are_consistent(wl):
    seed(wl, config={'entries': [{'slug': 'cheap_item', 'max_buy': 40},
                                 {'slug': 'mid_item', 'max_buy': 40, 'min_sell': 90},
                                 {'slug': 'never_priced', 'max_buy': 40}]})
    run(wl)
    doc = read_json(wl.out)

    assert doc['summary']['hit_buy'] == 1 and doc['summary']['hit_sell'] == 0
    assert doc['summary']['wait'] == 2 and doc['summary']['total'] == 3
    assert doc['summary']['unknown_floor'] == 1
    assert doc['self_check'] and all(doc['self_check'].values()), doc['self_check']
    assert doc['generated_iso'].endswith('Z') and len(doc['generated']) == 16


# ------------------------------------------------------------------ suggestions

def test_suggested_rows_come_from_local_data_and_never_alert(wl):
    seed(wl)
    run(wl)
    doc = read_json(wl.out)
    suggested = {s['slug']: s for s in doc['suggested']}

    assert [s['slug'] for s in doc['suggested']] == ['cand_cached', 'cand_right', 'cand_deal']
    assert suggested['cand_cached']['suggested_from'] == 'flip_digest'
    assert suggested['cand_deal']['suggested_from'] == 'deals'
    assert suggested['cand_cached']['status'] == 'HIT_BUY'     # floor 22 <= 40 from the flip
    assert all(s['alerts'] == [] for s in doc['suggested'])
    assert doc['summary']['suggested_total'] == 3
    assert doc['config']['overrides'] == 0                     # cand_cached is not in the config
    assert 'cand_cached' not in [a['slug'] for a in doc['alerts']]


def test_config_row_overrides_the_suggested_row(wl):
    seed(wl, config={'entries': [{'slug': 'cand_cached', 'max_buy': 15, 'min_sell': 200,
                                  'note': 'mine'}]})
    run(wl)
    doc = read_json(wl.out)
    suggested = {s['slug']: s for s in doc['suggested']}

    assert doc['config']['overrides'] == 1
    assert doc['entries'][0]['source'] == 'config' and doc['entries'][0]['max_buy'] == 15
    assert doc['entries'][0]['note'] == 'mine'
    assert suggested['cand_cached']['overridden_by_config'] is True
    assert suggested['cand_cached']['max_buy'] == 40            # the flip's own band, kept visible


def test_suggested_limit_and_unusable_rows(wl):
    seed(wl, flips={'flips': [{'slug': 'cand_right', 'buy_at': 0, 'sell_at': 0},
                              {'slug': 'cand_cached', 'buy_at': 300, 'sell_at': 100},
                              {'slug': 'cand_right', 'buy_at': 50, 'sell_at': 150}]})
    run(wl, argv=('--offline', '--suggested-limit', '0'))
    assert read_json(wl.out)['suggested'] == []

    run(wl, argv=('--offline', '--suggested-limit', '1'))
    doc = read_json(wl.out)
    assert [s['slug'] for s in doc['suggested']] == ['cand_right']
    assert doc['suggested'][0]['max_buy'] == 50 and doc['suggested'][0]['min_sell'] == 150


def test_suggested_rows_below_a_missing_floor_stay_honest(wl):
    seed(wl)
    run(wl)
    doc = read_json(wl.out)
    cand = [s for s in doc['suggested'] if s['slug'] == 'cand_right'][0]

    assert cand['floor'] is None and cand['floor_src'] == 'none'
    assert cand['cache_note'].endswith('_suggested')            # cache-only, no live probing
    assert cand['floor_note'] is None                           # no live attempt for candidates
    assert cand['status'] == 'WAIT' and cand['alerts'] == []


# ------------------------------------------------------------------ network safety

def test_offline_mode_never_touches_the_network(wl, monkeypatch):
    def boom(*a, **k):
        raise AssertionError('offline run must not call urlopen')

    monkeypatch.setattr(wl.mod.urllib.request, 'urlopen', boom)
    seed(wl, config={'entries': [{'slug': 'never_priced', 'max_buy': 40}]})

    assert run(wl, argv=('--offline',)) == 0
    doc = read_json(wl.out)

    assert doc['network']['offline'] is True and doc['network']['live_calls'] == 0
    assert doc['entries'][0]['floor_note'] == 'offline'


def test_live_fallback_uses_visible_sell_floor_with_spacing(wl, monkeypatch):
    seen = {'calls': 0, 'sleeps': []}
    clock = {'t': 1000.0}
    monkeypatch.setattr(wl.mod.urllib.request, 'urlopen',
                        lambda req, timeout=None: (seen.__setitem__('calls', seen['calls'] + 1)
                                                   or FakeResponse(CANNED_TOP)))
    monkeypatch.setattr(wl.mod.time, 'sleep', lambda s: seen['sleeps'].append(s))
    monkeypatch.setattr(wl.mod.time, 'time', lambda: clock['t'])
    seed(wl, config={'entries': [{'slug': 'never_priced', 'max_buy': 10},
                                 {'slug': 'also_unpriced', 'max_buy': 10}]})

    assert run(wl, argv=()) == 0                 # no --offline
    doc = read_json(wl.out)
    entry = {e['slug']: e for e in doc['entries']}['never_priced']

    assert seen['calls'] == 2 and doc['network']['live_calls'] == 2
    assert entry['floor'] == 8 and entry['floor_src'] == 'live' and entry['n_sell'] == 2
    assert entry['floor_note'] is None                      # live floor needs no excuse
    assert entry['status'] == 'HIT_BUY' and entry['distance_p'] == 2
    assert seen['sleeps'] == [wl.mod.DEFAULT_SLEEP]         # one gap between the two calls
    assert doc['network']['sleep_s'] >= wl.mod.MIN_SLEEP


def test_live_budget_is_capped_and_connection_errors_trip_offline(wl, monkeypatch):
    seed(wl, config={'entries': [{'slug': 'never_priced', 'max_buy': 10},
                                 {'slug': 'also_unpriced', 'max_buy': 10}]},
         prices={'other_item': {'wts': 5}})
    monkeypatch.setattr(wl.mod.time, 'sleep', lambda s: None)
    monkeypatch.setattr(wl.mod.urllib.request, 'urlopen',
                        lambda req, timeout=None: (_ for _ in ()).throw(OSError('no dns')))

    assert run(wl, argv=('--sleep', '0.35', '--max-live', '1')) == 0
    doc = read_json(wl.out)
    notes = [e['floor_note'] for e in doc['entries']]

    assert doc['network']['live_calls'] == 1                    # trip-switch: no second probe
    assert doc['network']['offline'] is True
    assert sorted(notes) == ['network_error', 'offline']        # honest notes, never guessed
    assert all(e['floor'] is None for e in doc['entries'])
    assert doc['self_check']['live_calls_within_cap'] is True


def test_max_live_cannot_exceed_the_hard_ceiling(wl, monkeypatch):
    monkeypatch.setattr(wl.mod.time, 'sleep', lambda s: None)
    assert wl.mod.Fetcher(True, {}, max_live=9999).max_live == wl.mod.MAX_LIVE_FETCHES
    assert wl.mod.Fetcher(True, {}, sleep=0.0).sleep_s == wl.mod.MIN_SLEEP


def test_fetcher_offline_and_cap_short_circuit(wl):
    fetcher = wl.mod.Fetcher(True, {'a': 'id-a'})
    assert fetcher.floor('a') is None and fetcher.calls == 0 and fetcher.status['a'] == 'offline'

    capped = wl.mod.Fetcher(False, {}, sleep=0.0, max_live=0)
    assert capped.floor('b') is None and capped.calls == 0 and capped.status['b'] == 'fetch_cap'


# ------------------------------------------------------------------ degenerate inputs

def test_missing_prices_json_degrades_to_all_wait_and_returns_1(wl):
    seed(wl)
    os.unlink(str(wl.data / 'prices.json'))

    assert run(wl) == 1
    doc = read_json(wl.out)

    assert doc['summary']['total'] == 8 and doc['summary']['wait'] == 8
    assert doc['alerts'] == [] and all(e['floor'] is None for e in doc['entries'])
    assert all(doc['self_check'].values())


def test_no_temp_file_is_left_behind(wl):
    seed(wl)
    run(wl)
    leftovers = [p for p in os.listdir(str(wl.data)) if p.endswith('.tmp')]
    assert leftovers == [] and read_json(wl.out)['version'] == 1


def test_main_prints_a_summary_and_reports_warnings(wl, capsys):
    seed(wl, config={'entries': [{'slug': 'cheap_item', 'max_buy': 40, 'min_sell': 90},
                                 {'slug': 'bogus', 'max_buy': 0}]})
    assert run(wl) == 0
    out = capsys.readouterr().out

    assert 'watchlist.py -> data/watchlist.json' in out
    assert 'config: data/watchlist_config.json existing, untouched' in out
    assert 'status: HIT_BUY 1 | HIT_SELL 0 | WAIT 0 | alerts 1' in out
    assert '[BUY] BUY Cheap Item' in out
    assert 'self-check: OK' in out and 'bogus' in out


# ------------------------------------------------------------------ pure helpers

def test_status_for_is_pure_and_buy_first(wl):
    status_for = wl.mod.status_for
    assert status_for(40, 40, 90) == ('HIT_BUY', 0)
    assert status_for(39, 40, 90) == ('HIT_BUY', 1)
    assert status_for(90, 40, 90) == ('HIT_SELL', 0)
    assert status_for(95, None, 90) == ('HIT_SELL', 5)
    assert status_for(50, 40, 90) == ('WAIT', 10)
    assert status_for(150, None, 90) == ('HIT_SELL', 60)
    assert status_for(10, 40, None) == ('HIT_BUY', 30)
    assert status_for(None, 40, 90) == ('WAIT', None)
    assert status_for(100, 100, 100) == ('HIT_BUY', 0)
    assert status_for(70, 80, None) == ('HIT_BUY', 10)


def test_numeric_helpers_never_trust_junk(wl):
    mod = wl.mod
    assert mod.pos_num(0) is None and mod.pos_num(-4) is None and mod.pos_num(True) is None
    assert mod.pos_num('12.5') == 12.5 and mod.pos_num('junk') is None and mod.pos_num(None) is None
    assert mod.as_plat(12.6) == 13 and mod.as_plat(None) is None and mod.as_plat('7') == 7
    assert mod.r1(33.3333) == 33.3 and mod.r1(None) is None
    assert mod.med_of({'med48': 2.0, 'median': 9.0}) == 2.0
    assert mod.med_of({'median': 9.0}) == 9.0 and mod.med_of({'avg48': 4.0}) == 4.0
    assert mod.med_of({}) is None and mod.med_of('nope') is None
    assert mod.vol_of({'vol48': 3.9}) == 3 and mod.vol_of(None) is None
    assert mod.one_line('a\nb  c') == 'a b c' and mod.one_line(None) == ''
    assert mod.pretty('arcane_energize') == 'Arcane Energize'
    assert mod.band_text(40, 90).startswith('buy at or below 40p')
    assert mod.band_text(None, 90) == 'sell at or above 90p'
    assert mod.band_text(40, None) == 'buy at or below 40p'
    assert mod.band_text(None, None) == 'no band'


def test_alert_first_names_fall_back_to_a_readable_slug(wl):
    entry = {'slug': 'arcane_energize', 'name': wl.mod.pretty('arcane_energize'), 'floor': 8,
             'median': None, 'vol48': 389, 'max_buy': 10, 'min_sell': None}
    alert = wl.mod.entry_alerts(entry)[0]
    assert alert['level'] == 'buy' and alert['name'] == 'Arcane Energize'
    assert 'no med48' in alert['message'] and 'vol48 389' in alert['message']


# ------------------------------------------------------------------ selftest + CLI

def test_inproc_selftest_passes_and_leaves_repo_data_alone(wl, capsys):
    before = (sha(REPO_OUT), sha(REPO_CFG))
    assert wl.mod.selftest() is True
    out = capsys.readouterr().out

    assert 'selftest: ' in out and '0 failed' in out and 'FAIL:' not in out
    assert (sha(REPO_OUT), sha(REPO_CFG)) == before


def test_cli_selftest_runs_offline_from_a_clean_checkout():
    before = (sha(REPO_OUT), sha(REPO_CFG))
    proc = subprocess.run([sys.executable, os.path.join(SCRIPTS, 'watchlist.py'), '--selftest'],
                          cwd=REPO, capture_output=True, text=True, timeout=120)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert 'selftest: ' in proc.stdout and '0 failed' in proc.stdout
    assert 'FAIL:' not in proc.stdout
    assert (sha(REPO_OUT), sha(REPO_CFG)) == before        # --selftest writes no repo data
