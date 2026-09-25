"""scripts/rivens.py: veiled bands, owned-riven valuation, cache + call-budget contract.

rivens.py never talks to the network inside this suite: every test monkeypatches
``mod.http_json`` with a canned warframe.market responder (catalog / statistics / top) and
points the four file paths at tmp_path through the documented env overrides
(RIVENS_OUT_PATH, RIVEN_ITEMS_CACHE, RIVEN_PRICES_CACHE, RIVENS_OWNED_PATH) - the repo's
data/ directory is never read or written.
"""
import urllib.parse
from types import SimpleNamespace

import pytest

from conftest import load_script, read_json, write_json

FAMILIES = ['rifle', 'shotgun', 'pistol', 'melee', 'zaw', 'kitgun', 'archgun', 'companion_weapon']
RIFLE = 'rifle_riven_mod_(veiled)'
MELEE = 'melee_riven_mod_(veiled)'


def veiled_slug(fam):
    return '%s_riven_mod_(veiled)' % fam


def veiled_name(fam):
    return '%s Riven Mod (Veiled)' % fam.replace('_', ' ').title()


CATALOG = {'apiVersion': '0.25.0', 'error': None, 'data': [
    {'slug': veiled_slug(f), 'tags': ['mod', 'riven_mod'], 'subtypes': ['unrevealed', 'revealed'],
     'i18n': {'en': {'name': veiled_name(f)}}} for f in FAMILIES
] + [
    {'slug': 'companion_weapon_riven_mod_(veiled)', 'tags': ['mod', 'riven'],   # companion has no veiled_riven tag
     'i18n': {'en': {'name': 'Companion Weapon Riven Mod (Veiled)'}}},
    {'slug': 'braton_riven_mod', 'tags': ['mod', 'riven_mod'],                  # weapon-specific
     'i18n': {'en': {'name': 'Braton Riven Mod'}}},
    {'slug': 'braton_prime_receiver', 'tags': ['prime'],
     'i18n': {'en': {'name': 'Braton Prime Receiver'}}},
]}


def stats_payload(buckets):
    return {'payload': {'statistics_closed': {'48hours': buckets}, 'statistics_live': []}}


def bucket(volume, median, low=None, high=None, subtype='unrevealed'):
    b = {'volume': volume, 'median': median, 'subtype': subtype}
    if low is not None:
        b['min_price'] = low
    if high is not None:
        b['max_price'] = high
    return b


# rifle: volume-weighted median (10x10 + 30x20)/40 = 17.5, plus a huge REVEALED trade to ignore
STATS = {
    RIFLE: stats_payload([bucket(10, 10.0, 8.0, 12.0), bucket(30, 20.0, 15.0, 25.0),
                          bucket(99, 500.0, 400.0, 600.0, subtype='revealed')]),
    MELEE: stats_payload([bucket(4, 8.0, 5.0, 9.0)]),
}
TOPS = {
    RIFLE: {'data': {'sell': [{'platinum': 9, 'visible': True, 'subtype': 'unrevealed'},
                              {'platinum': 5, 'visible': False, 'subtype': 'unrevealed'},
                              {'platinum': 300, 'visible': True, 'subtype': 'revealed'}],
                     'buy': [{'platinum': 6, 'visible': True, 'subtype': 'unrevealed'}]}},
    MELEE: {'data': {'sell': [{'platinum': 7, 'visible': True, 'subtype': 'unrevealed'}],
                     'buy': [{'platinum': 3, 'visible': True, 'subtype': 'unrevealed'}]}},
}


def default_payloads():
    """Every family gets a top quote; the two families above also get statistics."""
    stats = {f: STATS[f] for f in STATS}
    tops = {f: TOPS[f] for f in TOPS}
    for f in FAMILIES:
        slug = veiled_slug(f)
        stats.setdefault(slug, stats_payload([bucket(2, 12.0, 10.0, 14.0)]))
        tops.setdefault(slug, {'data': {'sell': [{'platinum': 11, 'visible': True, 'subtype': 'unrevealed'}],
                                        'buy': []}})
    return stats, tops


# ------------------------------------------------------------------ harness

@pytest.fixture
def rv(tmp_path, monkeypatch, data_dir):
    out = tmp_path / 'rivens.json'
    mod = load_script('rivens', monkeypatch=monkeypatch, env={
        'RIVENS_OUT_PATH': str(out),
        'RIVEN_ITEMS_CACHE': str(tmp_path / 'riven_items_cache.json'),
        'RIVEN_PRICES_CACHE': str(tmp_path / 'riven_prices_cache.json'),
        'RIVENS_OWNED_PATH': str(data_dir / 'owned.json'),
    })
    monkeypatch.setattr(mod, 'DATA', str(data_dir))
    monkeypatch.setattr(mod, 'SLEEP', 0)          # no politeness sleep inside tests
    return SimpleNamespace(mod=mod, data=data_dir, out=out,
                           items_cache=tmp_path / 'riven_items_cache.json',
                           price_cache=tmp_path / 'riven_prices_cache.json')


def wire(rv, monkeypatch, catalog=CATALOG, stats=None, tops=None, calls=None, errors=()):
    """Serve canned warframe.market payloads; unknown URLs fail loudly (a leak would show)."""
    stats, tops = (stats if stats is not None else {}), (tops if tops is not None else {})
    if not stats and not tops:
        stats, tops = default_payloads()
    made = []

    def _slug(url, marker):
        return urllib.parse.unquote(url.split(marker, 1)[1].split('/')[0])

    def _http(url, tries=4):
        made.append(url)
        if calls is not None:
            calls.append(url)
        if url in errors or any(e in url for e in errors):
            return {'__error': 'stub: offline %s' % url}
        if '/v2/items' in url:
            return catalog
        if '/statistics' in url:
            slug = _slug(url, '/v1/items/')
            return stats.get(slug, {'__error': 'stub: no statistics for %s' % slug})
        if '/top' in url:
            slug = _slug(url, '/v2/orders/item/')
            return tops.get(slug, {'__error': 'stub: no top for %s' % slug})
        raise AssertionError('unexpected url: %s' % url)

    monkeypatch.setattr(rv.mod, 'http_json', _http)
    return made


OWNED = [
    {'slug': MELEE, 'name': 'Melee Riven Mod (Veiled)', 'count': 2, 'tags': ['mod', 'riven_mod']},
    {'slug': MELEE, 'name': 'Melee Riven Mod (Veiled)', 'count': 1, 'tags': ['mod', 'veiled_riven']},
    {'slug': MELEE, 'name': 'Melee Riven Mod (Veiled)', 'count': 1, 'rank': 8, 'tags': ['mod', 'riven_mod']},
    {'slug': RIFLE, 'name': 'Rifle Riven Mod (Veiled)', 'count': 3, 'tags': ['mod', 'riven_mod']},
    {'slug': 'braton_riven_mod', 'name': 'Braton Riven Mod', 'count': 1, 'tags': ['mod', 'riven_mod']},
    {'slug': 'riven_sliver', 'name': 'Riven Sliver', 'count': 5, 'tags': ['resource']},
]


# ------------------------------------------------------------------ env + CLI

def test_env_paths_override_repo_data(rv):
    assert rv.mod.OUTP == str(rv.out)
    assert rv.mod.ITEMSC == str(rv.items_cache)
    assert rv.mod.PRICEC == str(rv.price_cache)
    assert rv.mod.OWNEDP == str(rv.data / 'owned.json')


def test_selftest_flag_runs_offline_and_passes(rv, capsys):
    assert rv.mod.main(['--selftest']) == 0
    out = capsys.readouterr().out
    assert 'selftest: PASS' in out
    assert not rv.out.exists() and not rv.price_cache.exists()


# ------------------------------------------------------------------ pure logic

def test_riven_family_from_slug_and_name(rv):
    assert rv.mod.riven_type_from_slug(veiled_slug('kitgun')) == 'kitgun'
    assert rv.mod.riven_type_from_slug('companion_weapon_riven_mod_(veiled)') == 'companion_weapon'
    assert rv.mod.riven_type_from_slug('braton_riven_mod') is None          # specific weapon
    assert rv.mod.riven_type_from_name('Rifle Riven Mod') == 'rifle'
    assert rv.mod.riven_type_from_name('Braton Riven Mod') is None
    assert rv.mod.riven_type_from_name('Riven Mod (Veiled)') is None        # generic veiled


def test_stats_48h_drops_revealed_and_weights_by_volume(rv):
    med, vol, low, high, buckets = rv.mod.stats_48h(STATS[RIFLE])
    assert (med, vol, buckets) == (17.5, 40, 2)          # the 99-volume revealed trade is gone
    assert (low, high) == (8.0, 25.0)
    assert rv.mod.stats_48h({'payload': {}}) == (None, None, None, None, 0)


def test_top_orders_skips_hidden_and_revealed(rv):
    assert rv.mod.top_orders(TOPS[RIFLE]) == (9, 6, 1)
    assert rv.mod.top_orders({'data': {'sell': [], 'buy': []}}) == (None, None, 0)


def test_band_row_and_no_quote(rv):
    item = {'slug': MELEE, 'name': 'Melee Riven Mod (Veiled)', 'type': 'melee'}
    assert rv.mod.band_for(item, {'sell_floor': 7, 'median': 8.0, 'vol48': 4}) == {
        'slug': MELEE, 'name': 'Melee Riven Mod (Veiled)', 'type': 'melee',
        'floor': 7.0, 'median': 8.0, 'vol48': 4}
    # /top down: the 48h trade low becomes the floor rather than an empty band
    assert rv.mod.band_for(item, {'median': 8, 'min48': 5.5, 'vol48': 1})['floor'] == 5.5
    assert rv.mod.band_for(item, None) is None


def test_owned_rows_sum_qty_apply_rank_and_flag_unknown_family(rv):
    band = {'slug': MELEE, 'name': 'Melee Riven Mod (Veiled)', 'type': 'melee',
            'floor': 7.0, 'median': 8.0, 'vol48': 4}
    rows = rv.mod.owned_rows(OWNED, {'melee': band})

    assert [(r['name'], r['qty'], r['est_low'], r['est_high'], r['basis']) for r in rows] == [
        ('Melee Riven Mod (Veiled)', 1, 9.8, 11.2, 'veiled_band:melee;rank:8'),  # +5%/rank x8
        ('Melee Riven Mod (Veiled)', 3, 7.0, 8.0, 'veiled_band:melee'),
        ('Braton Riven Mod', 1, None, None, 'veiled_band_type_unknown'),
        ('Rifle Riven Mod (Veiled)', 3, None, None, 'veiled_band_missing'),      # no rifle band here
    ]
    assert all('riven_sliver' != r['name'].lower() for r in rows)               # resource, not a riven
    assert all(set(r) == {'name', 'qty', 'est_low', 'est_high', 'basis'} for r in rows)


# ------------------------------------------------------------------ offline end-to-end

def test_run_writes_contract_and_caches(rv, monkeypatch):
    write_json(rv.data / 'owned.json', OWNED)
    calls = wire(rv, monkeypatch, calls=[])

    assert rv.mod.main([]) == 0

    doc = read_json(rv.out)
    assert sorted(doc) == ['generated', 'owned_rivens', 'summary', 'veiled_bands']
    assert isinstance(doc['generated'], str) and doc['generated'][:2] == '20'
    assert sorted(doc['summary']) == ['band_count', 'note', 'owned_count']
    assert doc['summary']['band_count'] == len(FAMILIES) == len(doc['veiled_bands'])
    assert doc['summary']['owned_count'] == 4
    assert 'veiled_band_type_unknown' in doc['summary']['note']

    bands = {b['type']: b for b in doc['veiled_bands']}
    assert list(bands) == FAMILIES                                             # TYPE_ORDER, stable
    assert all(sorted(b) == ['floor', 'median', 'name', 'slug', 'type', 'vol48']
               for b in doc['veiled_bands'])
    assert bands['rifle'] == {'slug': RIFLE, 'name': 'Rifle Riven Mod (Veiled)', 'type': 'rifle',
                              'floor': 9.0, 'median': 17.5, 'vol48': 40}
    assert bands['melee']['floor'] == 7.0 and bands['melee']['median'] == 8.0
    assert bands['zaw']['vol48'] == 2

    rivens = {r['basis']: r for r in doc['owned_rivens']}
    melee = [r for r in doc['owned_rivens'] if r['name'] == 'Melee Riven Mod (Veiled)']
    assert sorted((r['qty'], r['est_low'], r['basis']) for r in melee) == [
        (1, 9.8, 'veiled_band:melee;rank:8'), (3, 7.0, 'veiled_band:melee')]
    assert rivens['veiled_band:rifle']['est_low'] == 9.0
    assert rivens['veiled_band:rifle']['est_high'] == 17.5
    assert rivens['veiled_band:rifle']['qty'] == 3
    assert rivens['veiled_band_type_unknown'] == {'name': 'Braton Riven Mod', 'qty': 1,
                                                  'est_low': None, 'est_high': None,
                                                  'basis': 'veiled_band_type_unknown'}
    assert all(r['name'] != 'Riven Sliver' for r in doc['owned_rivens'])

    items = read_json(rv.items_cache)
    assert items['count'] == len(FAMILIES) and items['source'] == rv.mod.ITEMS_URL
    assert [i['slug'] for i in items['items']] == [veiled_slug(f) for f in FAMILIES]
    assert rv.mod.age_hours(items['fetched']) < 1.0

    prices = read_json(rv.price_cache)
    assert prices['schema'] == 1 and rv.mod.age_hours(prices['updated']) < 1.0
    assert sorted(prices['items']) == sorted(veiled_slug(f) for f in FAMILIES)
    assert prices['items'][RIFLE] == {'median': 17.5, 'vol48': 40, 'min48': 8.0, 'max48': 25.0,
                                      'buckets': 2, 'sell_floor': 9, 'buy_top': 6, 'sells': 1,
                                      'ts': prices['items'][RIFLE]['ts'], 'src': 'live',
                                      'failed': None}

    assert len(calls) == 1 + 2 * len(FAMILIES)                                  # catalog + 2 per family
    assert len(calls) <= rv.mod.MAX_CALLS


def test_rerun_reuses_both_caches_without_any_call(rv, monkeypatch):
    write_json(rv.data / 'owned.json', OWNED)
    calls = wire(rv, monkeypatch, calls=[])
    rv.mod.main([])
    first = read_json(rv.out)
    assert len(calls) > 0

    calls.clear()
    assert rv.mod.main([]) == 0

    assert calls == []                                                          # nothing refetched
    assert read_json(rv.out)['veiled_bands'] == first['veiled_bands']
    assert read_json(rv.items_cache)['fetched'] == read_json(rv.items_cache)['fetched']


def test_stale_caches_are_refetched(rv, monkeypatch):
    write_json(rv.data / 'owned.json', OWNED)
    wire(rv, monkeypatch, calls=[])
    rv.mod.main([])
    before = read_json(rv.out)['veiled_bands']

    old = (rv.mod.datetime.datetime.now() - rv.mod.datetime.timedelta(hours=20)).isoformat(timespec='seconds')
    items = read_json(rv.items_cache)
    items['fetched'] = old                                                     # catalog TTL is 12h
    write_json(rv.items_cache, items)
    prices = read_json(rv.price_cache)
    for ent in prices['items'].values():
        ent['ts'] = old                                                        # quote TTL is 6h
    write_json(rv.price_cache, prices)

    calls = wire(rv, monkeypatch, calls=[])
    assert rv.mod.main([]) == 0

    assert sum(1 for u in calls if '/v2/items' in u) == 1                      # stale catalog re-read
    assert sum(1 for u in calls if '/statistics' in u) == len(FAMILIES)        # every family re-priced
    assert read_json(rv.out)['veiled_bands'] == before                         # same market, same bands
    assert rv.mod.age_hours(read_json(rv.items_cache)['fetched']) < 1.0
    assert rv.mod.age_hours(read_json(rv.price_cache)['items'][RIFLE]['ts']) < 1.0


def test_refresh_flag_ignores_fresh_caches(rv, monkeypatch):
    write_json(rv.data / 'owned.json', OWNED)
    wire(rv, monkeypatch, calls=[])
    rv.mod.main([])

    calls = wire(rv, monkeypatch, calls=[])
    assert rv.mod.main(['--refresh']) == 0

    assert sum(1 for u in calls if '/v2/items' in u) == 1                      # catalog re-read
    assert sum(1 for u in calls if '/statistics' in u) == len(FAMILIES)


def test_call_cap_stops_live_calls_but_still_writes(rv, monkeypatch):
    write_json(rv.data / 'owned.json', OWNED)
    monkeypatch.setattr(rv.mod, 'MAX_CALLS', 5)
    calls = wire(rv, monkeypatch, calls=[])

    assert rv.mod.main([]) == 0

    assert len(calls) == 5                                                     # catalog + 2 families
    doc = read_json(rv.out)
    assert doc['summary']['band_count'] == 2
    # families the cap skipped are reported, never invented
    assert {r['basis'] for r in doc['owned_rivens']} == {'veiled_band:rifle', 'veiled_band_missing',
                                                         'veiled_band_type_unknown'}
    assert read_json(rv.price_cache)['items'][RIFLE]['sell_floor'] == 9


def test_catalog_failure_falls_back_to_stale_cache(rv, monkeypatch):
    write_json(rv.data / 'owned.json', OWNED)
    wire(rv, monkeypatch, calls=[])
    rv.mod.main([])                                                            # seed the caches
    old = (rv.mod.datetime.datetime.now() - rv.mod.datetime.timedelta(hours=20)).isoformat(timespec='seconds')
    items = read_json(rv.items_cache)
    items['fetched'] = old
    write_json(rv.items_cache, items)

    wire(rv, monkeypatch, calls=[], errors=['/v2/items'])                      # API down this run
    assert rv.mod.main([]) == 0

    doc = read_json(rv.out)
    assert doc['summary']['band_count'] == len(FAMILIES)                       # stale catalog still bands
    assert doc['generated'] > items['fetched']


def test_no_catalog_and_no_cache_returns_1_without_writing(rv, monkeypatch):
    write_json(rv.data / 'owned.json', OWNED)
    wire(rv, monkeypatch, calls=[], errors=['/v2/items'])

    assert rv.mod.main([]) == 1

    assert not rv.out.exists()
    assert not rv.items_cache.exists()


def test_owned_json_missing_still_bands_and_reports_zero_owned(rv, monkeypatch):
    wire(rv, monkeypatch, calls=[])                                            # no owned.json at all

    assert rv.mod.main([]) == 0

    doc = read_json(rv.out)
    assert doc['owned_rivens'] == []
    assert doc['summary']['owned_count'] == 0
    assert doc['summary']['band_count'] == len(FAMILIES)
