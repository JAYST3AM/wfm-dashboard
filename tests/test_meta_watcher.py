"""scripts/meta_watcher.py: post-patch spike/sink detection, contract, cache reuse.

Every test runs off tmp_path fixtures (conftest's data_dir) with META_DATA_DIR /
META_WATCH_PATH / META_CACHE_PATH redirected there, and fetch_slug monkeypatched - the
suite never touches the network or the repo's real data/ directory, mirroring the other
public test modules. The live-run path (--fetch) is exercised with a stubbed endpoint.
"""
import argparse
import os
import time
from types import SimpleNamespace

import pytest

from conftest import load_script, read_json, write_json

DAY = 86400
NOW = int(time.time())


def boom(*a, **k):
    raise AssertionError('offline test called fetch_slug')


def args(**kw):
    base = dict(fetch=False, fetch_limit=0, refresh=False, limit=0, max_calls=50, sleep=0.35,
                selftest=False)
    base.update(kw)
    return argparse.Namespace(**base)


@pytest.fixture
def mw(tmp_path, monkeypatch, data_dir):
    out = data_dir / 'meta_watch.json'
    cache = data_dir / 'meta_stats_cache.json'
    mod = load_script('meta_watcher', monkeypatch=monkeypatch,
                      env={'META_DATA_DIR': str(data_dir), 'META_WATCH_PATH': str(out),
                           'META_CACHE_PATH': str(cache)})
    monkeypatch.setattr(mod, 'fetch_slug', boom)
    return SimpleNamespace(mod=mod, data=data_dir, out=out, cache=cache)


def seed(mw, files):
    for name, obj in files.items():
        write_json(mw.data / name, obj)


def news(posts, version='44.0.1', fetched=None):
    """gamenews.json shaped like the server warm job writes it."""
    return {'fetched': NOW - 600 if fetched is None else fetched, 'version': version,
            'items': [dict(title=t, url='https://example.invalid/%d' % i,
                           date=(NOW - d * DAY) if d is not None else None,
                           source=src, excerpt='') for i, (t, d, src) in enumerate(posts)]}


def iso_days_ago(days):
    import datetime as dt
    return (dt.datetime.fromtimestamp(NOW - days * DAY, dt.timezone.utc)).isoformat()


# ---------------------------------------------------------------- paths / JSON / time

def test_env_overrides_redirect_everything(mw):
    p = mw.mod.resolve_paths()
    assert p['data'] == str(mw.data)
    assert p['out'] == str(mw.out) and p['cache'] == str(mw.cache)
    assert p['gamenews'] == str(mw.data / 'gamenews.json')
    assert p['trends_cache'] == str(mw.data / 'trends_cache.json')
    assert str(mw.data).startswith(str(mw.data.parent))        # never the repo's data/


def test_paths_without_env_fall_back_to_repo_data(mw, monkeypatch):
    for k in ('META_DATA_DIR', 'META_WATCH_PATH', 'META_CACHE_PATH'):
        monkeypatch.delenv(k, raising=False)
    p = mw.mod.resolve_paths()
    assert p['data'] == mw.mod.DATA
    assert p['out'] == os.path.join(mw.mod.DATA, 'meta_watch.json')
    assert p['cache'] == os.path.join(mw.mod.DATA, 'meta_stats_cache.json')
    assert p['gamenews'].endswith('gamenews.json')


def test_jdump_is_atomic_and_readable(mw):
    path = str(mw.data / 'x.json')
    mw.mod.jdump(path, {'a': 1})
    assert read_json(path) == {'a': 1}
    assert not (mw.data / 'x.json.tmp').exists()


def test_jload_survives_missing_and_corrupt(mw):
    assert mw.mod.jload(str(mw.data / 'nope.json'), {'d': 1}) == {'d': 1}
    (mw.data / 'bad.json').write_text('{not json', encoding='utf-8')
    assert mw.mod.jload(str(mw.data / 'bad.json'), []) == []


# ---------------------------------------------------------------- news -> patch block

def test_update_posts_keeps_updates_and_update_titles_newest_first(mw):
    posts = mw.mod.update_posts(news([('Iceblade of Narin: Hotfix 44.0.1', 3, 'updates'),
                                      ('Devstream 197 Overview', 5, 'news'),
                                      ('Update 44: Iceblade of Narin', 12, 'updates'),
                                      ('Patch 44.1.2: hotfixes', 20, 'news'),
                                      ('No date here', None, 'updates')]))
    assert [p['title'] for p in posts] == ['Iceblade of Narin: Hotfix 44.0.1',
                                          'Update 44: Iceblade of Narin', 'Patch 44.1.2: hotfixes']
    # same extractor as server.py: only dotted numbers are a version
    assert posts[0]['version'] == '44.0.1' and posts[1]['version'] is None
    assert posts[2]['version'] == '44.1.2'


def test_patch_block_window_boundaries(mw):
    inside = mw.mod.patch_block(news([('Hotfix 44.0.1', 3, 'updates')]), NOW)
    assert inside['latest_version'] == '44.0.1'
    assert inside['latest_date'] == NOW - 3 * DAY and inside['latest_date_iso'] is not None
    assert inside['post_patch_active'] is True and inside['post_count_window'] == 1
    assert inside['days_since_latest'] == 3.0 and inside['window_days'] == 10
    assert inside['source'] == 'data/gamenews.json'

    assert mw.mod.patch_block(news([('Update 44', 10, 'updates')]), NOW)['post_patch_active'] is True
    assert mw.mod.patch_block(news([('Update 44', 11, 'updates')]), NOW)['post_patch_active'] is False


def test_patch_block_degrades_without_updates(mw):
    only_news = mw.mod.patch_block(news([('Citrine Prime Access Available Now', 2, 'news')],
                                       version=None), NOW)
    assert only_news['latest_version'] is None and only_news['latest_date'] is None
    assert only_news['post_patch_active'] is False and only_news['days_since_latest'] is None

    empty = mw.mod.patch_block({}, NOW)
    assert empty['post_patch_active'] is False and empty['latest_version'] is None
    assert empty['news_fetched_iso'] is None


def test_patch_block_version_falls_back_to_title_regex(mw):
    assert mw.mod.patch_block(news([('Hotfix 44.0.2', 1, 'updates')], version=None),
                              NOW)['latest_version'] == '44.0.2'


# ---------------------------------------------------------------- metric math

def test_ratio_normalises_the_48h_window_to_a_daily_rate(mw):
    assert mw.mod.ratio_of(60, 10) == 3.0        # 30/day vs 10/day
    assert mw.mod.ratio_of(20, 10) == 1.0       # exactly average
    assert mw.mod.ratio_of(4, 10) == 0.2
    assert mw.mod.ratio_of(50, 0) is None and mw.mod.ratio_of(50, None) is None


def test_verdict_thresholds_are_inclusive(mw):
    assert mw.mod.verdict(2.0) == 'spike' and mw.mod.verdict(9.9) == 'spike'
    assert mw.mod.verdict(0.5) == 'sink' and mw.mod.verdict(0.0) == 'sink'
    assert mw.mod.verdict(1.99) == 'steady' and mw.mod.verdict(0.51) == 'steady'
    assert mw.mod.verdict(None) is None


def test_days30_total_ignores_rows_older_than_30_days(mw):
    import datetime as dt
    now = dt.datetime.fromtimestamp(NOW, dt.timezone.utc)
    days = [{'datetime': iso_days_ago(5), 'volume': 7}, {'datetime': iso_days_ago(29), 'volume': 3},
            {'datetime': iso_days_ago(31), 'volume': 999}, {'datetime': 'garbage', 'volume': 5}]
    assert mw.mod.days30_total(days, now) == (10, 2)
    assert mw.mod.days30_total([], now) == (0, 0)


def test_select_slugs_deals_first_then_liquid_owned(mw):
    deals = [{'slug': 'd1', 'name': 'Deal One', 'vol48': 5}, {'slug': 'd2', 'vol48': 9},
             {'slug': 'd2', 'vol48': 4}]
    owned = [{'slug': 'o1', 'name': 'Owned One', 'count': 3}, {'slug': 'o2', 'count': 1},
             {'slug': 'o3', 'name': 'Owned Three', 'count': 0}]
    sel, names = mw.mod.select_slugs(deals, owned, {'o1': {'wts': 50}, 'o2': {'wts': 99}}, cap=3)
    assert sel == ['d2', 'd1', 'o2']              # deals by vol48 desc, then the richest owned
    assert names['d2'] == 'd2' and names['o1'] == 'Owned One'


def test_price_trend_reuses_trends_then_price_history(mw):
    tmap = {'a': {'price_trend_pct': 12.5}, 'b': {'price_trend_pct': None}}
    phist = {'b': [['2026-09-01', 10, 4, 9.0, 4], ['2026-09-25', 20, 4, 9.5, 4]],
             'c': [['2026-09-25', 7, 4, 9.5, 4]]}
    assert mw.mod.price_trend('a', tmap, phist) == 12.5
    assert mw.mod.price_trend('b', tmap, phist) == 100.0
    assert mw.mod.price_trend('c', tmap, phist) is None      # single point
    assert mw.mod.price_trend('zz', tmap, {}) is None


# ---------------------------------------------------------------- end-to-end, offline

FIXTURES = {
    'gamenews.json': news([('Iceblade of Narin: Hotfix 44.0.1', 3, 'updates'),
                           ('Update 44: Iceblade of Narin', 12, 'updates')]),
    'stats.json': {'alpha': {'vol48': 90, 'volday90': 20.0},
                   'beta': {'volday90': 12.0},
                   'epsilon': {'vol48': 40, 'volday90': 5.0},
                   'eta': {'vol48': 1, 'volday90': 0.4}},
    'deals.json': {'deals': [{'slug': s, 'name': s.title(), 'vol48': v} for s, v in
                             (('alpha', 90), ('beta', 4), ('gamma', 100), ('epsilon', 40),
                              ('zeta', 30), ('eta', 1))]},
    'trends.json': {'rows': [{'slug': 'alpha', 'name': 'Alpha', 'vol30': 900, 'vol90': 3000,
                              'ratio': 0.9, 'badge': 'steady', 'price_trend_pct': 12.5}]},
    'trends_cache.json': {'entries': {
        'beta': {'fetched': NOW - 3600, 'days': [{'datetime': iso_days_ago(5), 'volume': 200,
                                                  'median': 5.0, 'mod_rank': None},
                                                 {'datetime': iso_days_ago(40), 'volume': 999,
                                                  'median': 5.0, 'mod_rank': None}]}}},
    'price_history.json': {'items': {'beta': [['2026-09-01', 10, 4, 9.0, 4],
                                             ['2026-09-25', 20, 4, 9.5, 4]],
                                     'alpha': [['2026-09-25', 40, 4, 39.0, 90]]}},
    'meta_stats_cache.json': {'version': 1, 'updated': NOW - 600, 'updated_iso': 'x',
                              'ttl_seconds': 43200,
                              'entries': {'gamma': {'fetched': NOW - 600, 'vol30': 600,
                                                    'vol48': 100, 'error': None}}},
    'prices.json': {},
}


def test_offline_run_writes_the_documented_contract(mw):
    seed(mw, FIXTURES)
    assert mw.mod.run(args()) == 0

    doc = read_json(mw.out)
    assert set(doc) >= {'version', 'generated', 'generated_iso', 'patch', 'spike', 'sink',
                        'rows', 'summary', 'baseline_sources', 'skipped', 'method'}
    assert doc['version'] == mw.mod.VERSION and isinstance(doc['generated'], int)
    assert doc['patch']['latest_version'] == '44.0.1'
    assert doc['patch']['latest_date'] == NOW - 3 * DAY
    assert doc['patch']['post_patch_active'] is True
    assert 'ratio = (vol48/2) / vol30_baseline' in doc['method']

    rows = {r['slug']: r for r in doc['rows']}
    assert set(rows) == {'alpha', 'beta', 'gamma', 'epsilon'}          # eta/zeta unusable
    for r in doc['rows']:
        assert set(r) == {'slug', 'name', 'vol48', 'vol48_per_day', 'vol30_baseline', 'ratio',
                          'price_trend_pct', 'post_patch'}
        assert r['post_patch'] is True
    assert rows['alpha'] == dict(slug='alpha', name='Alpha', vol48=90, vol48_per_day=45.0,
                                 vol30_baseline=30.0, ratio=1.5, price_trend_pct=12.5,
                                 post_patch=True)
    assert rows['beta']['vol48'] == 4 and rows['beta']['ratio'] == 0.3
    assert rows['beta']['price_trend_pct'] == 100.0
    assert rows['gamma']['vol30_baseline'] == 20.0 and rows['gamma']['ratio'] == 2.5
    assert rows['epsilon']['vol30_baseline'] == 5.0 and rows['epsilon']['ratio'] == 4.0

    assert [r['slug'] for r in doc['spike']] == ['epsilon', 'gamma']    # ratio desc
    assert [r['slug'] for r in doc['sink']] == ['beta']                 # ratio asc
    assert doc['summary'] == {'spike': 2, 'sink': 1, 'tracked': 4}
    assert doc['skipped'] == 2                                          # zeta + eta
    assert doc['baseline_sources'] == {'trends.json': 1, 'trends_cache': 1,
                                       'stats_endpoint': 1, 'stats.json:90d': 1}


def test_offline_default_never_calls_the_endpoint(mw):
    seed(mw, FIXTURES)
    mw.mod.run(args(fetch=False, fetch_limit=0))       # fetch_slug is monkeypatched to raise
    # the pre-seeded endpoint entry survives untouched: no gap was ever fetched
    assert set(read_json(mw.cache)['entries']) == {'gamma'}


def test_post_patch_is_false_when_the_last_update_is_old(mw):
    files = dict(FIXTURES)
    files['gamenews.json'] = news([('Update 43: Old News', 21, 'updates')])
    seed(mw, files)
    mw.mod.run(args())
    doc = read_json(mw.out)
    assert doc['patch']['post_patch_active'] is False
    assert all(r['post_patch'] is False for r in doc['rows'])
    assert doc['summary']['spike'] == 2 and doc['summary']['tracked'] == 4   # metrics unaffected


def test_limit_and_missing_inputs_are_survivable(mw):
    seed(mw, {'gamenews.json': news([('Hotfix 44.0.1', 2, 'updates')]),
              'deals.json': {'deals': [{'slug': 'alpha', 'name': 'Alpha', 'vol48': 40},
                                       {'slug': 'beta', 'name': 'Beta', 'vol48': 10}]},
              'stats.json': {'alpha': {'vol48': 40, 'volday90': 4.0},
                             'beta': {'vol48': 10, 'volday90': 4.0}}})
    mw.mod.run(args(limit=1))
    doc = read_json(mw.out)
    assert [r['slug'] for r in doc['rows']] == ['alpha']
    assert doc['rows'][0]['vol30_baseline'] == 4.0      # stats.json 90d proxy
    assert doc['rows'][0]['ratio'] == 5.0               # (40/2) / 4.0
    assert doc['summary'] == {'spike': 1, 'sink': 0, 'tracked': 1}


def test_low_baseline_and_missing_vol48_are_skipped(mw):
    seed(mw, {'gamenews.json': news([('Hotfix 44.0.1', 2, 'updates')]),
              'deals.json': {'deals': [{'slug': 'tiny', 'name': 'Tiny', 'vol48': 9},
                                       {'slug': 'nov48', 'name': 'NoV48', 'vol48': 24}]},
              'stats.json': {'tiny': {'vol48': 9, 'volday90': 0.4},
                             'nov48': {'volday90': 12.0}}})
    mw.mod.run(args())
    doc = read_json(mw.out)
    assert doc['rows'] == [] and doc['spike'] == [] and doc['sink'] == []
    assert doc['summary'] == {'spike': 0, 'sink': 0, 'tracked': 0} and doc['skipped'] == 2


# ---------------------------------------------------------------- fetch path (stubbed)

def test_fetch_fills_baseline_gaps_and_caches(mw):
    seed(mw, FIXTURES)
    calls = []

    def stub(slug, tries=3):
        calls.append(slug)
        return 300, 20, None

    mw.mod.fetch_slug = stub
    assert mw.mod.run(args(fetch=True)) == 0

    assert calls == ['epsilon', 'zeta', 'eta']          # the three slugs with no 30d baseline
    doc = read_json(mw.out)
    rows = {r['slug']: r for r in doc['rows']}
    assert set(rows) == {'alpha', 'beta', 'gamma', 'epsilon', 'zeta', 'eta'}
    assert rows['zeta']['vol30_baseline'] == 10.0 and rows['zeta']['ratio'] == 1.0
    assert rows['eta']['ratio'] == 0.05                 # (1/2) / 10.0
    assert doc['summary']['tracked'] == 6 and doc['skipped'] == 0
    assert doc['baseline_sources']['stats_endpoint'] == 4

    cache = read_json(mw.cache)
    z = cache['entries']['zeta']
    assert set(z) == {'fetched', 'vol30', 'vol48', 'error'}
    assert z['vol30'] == 300 and z['vol48'] == 20 and z['error'] is None
    assert NOW - 60 <= z['fetched'] <= NOW + 60
    assert cache['ttl_seconds'] == mw.mod.CACHE_TTL and cache['ua'] == mw.mod.UA
    assert isinstance(cache['updated'], int) and cache['updated_iso'].endswith('Z')


def test_fetch_reuses_a_fresh_cache_entry_and_refetches_after_the_ttl(mw):
    seed(mw, FIXTURES)
    calls = []

    def stub(slug, tries=3):
        calls.append(slug)
        return 120, 8, None

    mw.mod.fetch_slug = stub
    mw.mod.run(args(fetch=True))
    first = list(calls)
    assert first

    mw.mod.fetch_slug = boom                            # fresh cache must satisfy the next run
    mw.mod.run(args(fetch=True))
    assert calls == first

    cache = read_json(mw.cache)
    cache['entries']['zeta']['fetched'] = NOW - mw.mod.CACHE_TTL - 60
    write_json(mw.cache, cache)
    mw.mod.fetch_slug = stub
    mw.mod.run(args(fetch=True))
    assert calls[len(first):] == ['zeta']               # only the expired entry is refetched


def test_fetch_limit_refreshes_tracked_slugs_and_respects_max_calls(mw):
    seed(mw, FIXTURES)
    calls = []

    def stub(slug, tries=3):
        calls.append(slug)
        return 300, 20, None

    mw.mod.fetch_slug = stub
    # baseline gaps (epsilon, zeta, eta) come first, then the top --fetch-limit slugs
    mw.mod.run(args(fetch=False, fetch_limit=3, refresh=True, max_calls=2))
    assert calls == ['epsilon', 'zeta']                  # hard cap honoured

    calls.clear()
    mw.mod.run(args(fetch=False, fetch_limit=3, refresh=True))
    # epsilon/zeta are fresh now, so eta (the remaining gap) leads, then the top --fetch-limit slugs
    assert calls == ['eta', 'gamma', 'alpha', 'epsilon']


def test_fetch_errors_are_cached_and_costs_are_bounded(mw):
    seed(mw, FIXTURES)

    def stub(slug, tries=3):
        return None, None, 'http 404'

    mw.mod.fetch_slug = stub
    mw.mod.run(args(fetch=True))
    cache = read_json(mw.cache)
    assert cache['entries']['epsilon']['error'] == 'http 404'
    assert cache['entries']['epsilon']['vol30'] is None
    doc = read_json(mw.out)
    rows = {r['slug']: r for r in doc['rows']}
    assert rows['epsilon']['vol30_baseline'] == 5.0     # falls back to the stats.json proxy
    assert 'zeta' not in rows                           # no vol48, no baseline -> not guessed
    assert doc['skipped'] == 2


# ---------------------------------------------------------------- cli

def test_main_selftest_passes_offline(mw, capsys):
    assert mw.mod.main(['--selftest']) == 0
    out = capsys.readouterr().out
    assert 'checks passed' in out and 'FAIL' not in out


def test_main_defaults_to_offline_run(mw):
    seed(mw, FIXTURES)
    assert mw.mod.main([]) == 0
    assert read_json(mw.out)['summary']['tracked'] == 4
    assert set(read_json(mw.cache)['entries']) == {'gamma'}     # no endpoint call was made
