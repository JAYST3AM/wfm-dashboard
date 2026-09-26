"""scripts/item_history.py: intraday per-item store contract.

Covers the store schema, same-ts de-dupe, the 2000-point cap, backfill from the daily
store, sales from the trade log (including NAME -> slug resolution), the no-fake-point
rule on HTTP failure, the 55-minute self-throttle (and --force overriding it), --dry-run,
null ask/bid surviving as JSON null, the resumable cursor, and rank-lane snapshots.

Offline throughout: the script reads ITEM_HISTORY_PATH at import time and every input
through module.DATA, so the fixture points both at tmp_path and swaps module._get for a
stub - the repo's real data/ is never read or written.
"""
from datetime import datetime
from types import SimpleNamespace

import pytest

from conftest import load_script, read_json, write_json

NAMES = {'alpha_prime': 'Alpha Prime', 'blind_rage': 'Blind Rage'}


@pytest.fixture
def ih(tmp_path, monkeypatch, data_dir):
    store = tmp_path / 'item_history.json'
    mod = load_script('item_history', monkeypatch=monkeypatch, env={'ITEM_HISTORY_PATH': str(store)})
    monkeypatch.setattr(mod, 'DATA', str(data_dir))
    monkeypatch.setattr(mod, '_get', lambda url, tries=4: {'error': 'offline-stub'})
    return SimpleNamespace(mod=mod, data=data_dir, store=store)


def catalogue(ih, *slugs):
    write_json(ih.data / 'wfm_items_v2.json', {'data': [
        {'id': 'id-' + s, 'slug': s, 'i18n': {'en': {'name': NAMES.get(s, s)}}} for s in slugs]})


def owned(ih, *slugs):
    write_json(ih.data / 'owned.json', [{'slug': s, 'name': NAMES.get(s, s)} for s in slugs])


def book(ask=None, bid=None):
    return {'data': {
        'sell': [] if ask is None else [{'type': 'sell', 'platinum': ask, 'visible': True}],
        'buy': [] if bid is None else [{'type': 'buy', 'platinum': bid, 'visible': True}]}}


def serve(ih, monkeypatch, ask=12, bid=5):
    """A healthy /orders/item/{id}/top response."""
    monkeypatch.setattr(ih.mod, '_get', lambda url, tries=4: book(ask, bid))


def noon(date_iso):
    return int(datetime.strptime(date_iso, '%Y-%m-%d').timestamp())


def seed_store(ih, slug, points, sales=(), src='top_order'):
    write_json(ih.store, {'schema': 1, 'count': 1, 'items': {slug: {
        'name': NAMES.get(slug, slug), 'first': points[0][0], 'last': points[-1][0],
        'points': points, 'sales': list(sales),
        'src': {'ask': src, 'sales': 'trade_log'}}}, 'meta': {'cursor': 0, 'tracked': 1}})


# ------------------------------------------------------------------ schema

def test_store_has_the_exact_schema(ih, monkeypatch):
    catalogue(ih, 'blind_rage')
    owned(ih, 'blind_rage')
    serve(ih, monkeypatch, ask=12, bid=5)

    assert ih.mod.main(['--once', '--force']) == 0                             # --once is the default mode

    doc = read_json(ih.store)
    assert set(doc) == {'schema', 'updated', 'updated_iso', 'count', 'fields', 'items', 'meta'}
    assert doc['schema'] == 1 and doc['fields'] == ['ts', 'ask', 'bid']
    assert isinstance(doc['updated'], int) and doc['updated'] > 1_600_000_000
    assert doc['updated_iso'].endswith('Z') and doc['updated_iso'][4] == '-'
    assert doc['count'] == len(doc['items']) == 1

    ent = doc['items']['blind_rage']
    assert set(ent) == {'name', 'first', 'last', 'points', 'sales', 'src'}
    assert ent['name'] == 'Blind Rage'                       # catalogue display name
    assert set(ent['src']) == {'ask', 'sales'} and ent['src']['sales'] == 'trade_log'
    assert ent['src']['ask'] == 'top_order'
    assert ent['points'][-1][1:] == [12, 5]
    assert ent['first'] == ent['last'] == ent['points'][-1][0]
    assert ent['sales'] == []

    meta = doc['meta']
    assert set(meta) == {'tracked', 'fetched', 'from_history', 'failures', 'rate_s', 'cursor', 'slugs'}
    assert meta['tracked'] == 1 and meta['fetched'] == 1 and meta['failures'] == 0
    assert meta['from_history'] == 0 and meta['cursor'] == 0 and meta['slugs'] == ['blind_rage']
    assert meta['rate_s'] == 0.35

    raw = ih.store.read_bytes()                              # CRLF-safe: LF, one trailing newline
    assert raw.endswith(b'\n') and not raw.endswith(b'\n\n') and b'\r' not in raw


# ------------------------------------------------------------------ points

def test_append_point_dedupes_the_same_ts_and_keeps_order(ih):
    pts = []
    assert ih.mod.append_point(pts, 200, 8, 4) == 'appended'
    assert ih.mod.append_point(pts, 100, 5, 2) == 'appended'     # an older ts lands in front
    assert ih.mod.append_point(pts, 200, 9, 6) == 'replaced'     # same ts: newest values win
    assert ih.mod.append_point(pts, 150, 6, 1) == 'appended'
    assert pts == [[100, 5, 2], [150, 6, 1], [200, 9, 6]]


def test_point_cap_trims_the_oldest(ih, monkeypatch):
    old = [[1000 + i, 1, 1] for i in range(ih.mod.CAP)]
    seed_store(ih, 'blind_rage', old)
    catalogue(ih, 'blind_rage')
    owned(ih, 'blind_rage')
    serve(ih, monkeypatch)

    assert ih.mod.main(['--once', '--force']) == 0

    points = read_json(ih.store)['items']['blind_rage']['points']
    assert len(points) == ih.mod.CAP == 2000
    assert points[0][0] == 1001                              # only the oldest was dropped
    assert points[-1][1:] == [12, 5]                         # the live point survived


def test_empty_side_of_the_book_is_stored_as_json_null(ih, monkeypatch):
    catalogue(ih, 'blind_rage')
    owned(ih, 'blind_rage')
    monkeypatch.setattr(ih.mod, '_get', lambda url, tries=4: book(ask=14))

    assert ih.mod.main(['--once', '--force']) == 0
    assert read_json(ih.store)['items']['blind_rage']['points'][-1][1:] == [14, None]
    assert 'null' in ih.store.read_text(encoding='utf-8')

    monkeypatch.setattr(ih.mod, '_get', lambda url, tries=4: {'data': {      # hidden order only
        'sell': [{'type': 'sell', 'platinum': 1, 'visible': False}], 'buy': []}})
    assert ih.mod.main(['--once', '--force']) == 0
    assert read_json(ih.store)['items']['blind_rage']['points'][-1][1:] == [None, None]


# ------------------------------------------------------------------ backfill + sales

def test_backfill_seeds_daily_rows_at_local_midnight(ih):
    # _get stays the offline stub: the daily seed must land even when the API is unreachable
    catalogue(ih, 'blind_rage')
    owned(ih, 'blind_rage')
    write_json(ih.data / 'price_history.json', {'schema': 1, 'items': {
        'blind_rage': [['2026-01-02', 12, 5, 11, 3], ['2026-01-01', 10, 4, 9, 2]]}})

    assert ih.mod.main(['--once', '--force']) == 0

    doc = read_json(ih.store)
    ent = doc['items']['blind_rage']
    assert ent['points'] == [[noon('2026-01-01'), 10, 4], [noon('2026-01-02'), 12, 5]]
    assert ent['src']['ask'] == 'history'                    # no live point exists yet
    assert ent['first'] == noon('2026-01-01') and ent['last'] == noon('2026-01-02')
    assert doc['meta']['from_history'] == 1 and doc['meta']['failures'] == 1


def test_backfill_never_duplicates_a_ts_the_series_already_has(ih, monkeypatch):
    # a second sweep must not re-seed the daily rows on top of the existing points
    seed_store(ih, 'blind_rage', [[noon('2026-01-01'), 10, 4], [noon('2026-01-02'), 12, 5]], src='history')
    catalogue(ih, 'blind_rage')
    owned(ih, 'blind_rage')
    write_json(ih.data / 'price_history.json', {'schema': 1, 'items': {
        'blind_rage': [['2026-01-01', 10, 4, 9, 2], ['2026-01-02', 12, 5, 11, 3]]}})
    serve(ih, monkeypatch, ask=99, bid=90)

    assert ih.mod.main(['--once', '--force']) == 0

    ent = read_json(ih.store)['items']['blind_rage']
    assert [p[0] for p in ent['points']] == [noon('2026-01-01'), noon('2026-01-02'), ent['last']]
    assert ent['points'][-1][1:] == [99, 90]
    assert read_json(ih.store)['meta']['from_history'] == 0


def test_live_point_after_backfill_switches_src_to_top_order(ih, monkeypatch):
    catalogue(ih, 'blind_rage')
    owned(ih, 'blind_rage')
    write_json(ih.data / 'price_history.json', {'schema': 1, 'items': {
        'blind_rage': [['2026-01-01', 10, 4, 9, 2]]}})
    serve(ih, monkeypatch, ask=12, bid=5)

    assert ih.mod.main(['--once', '--force']) == 0

    ent = read_json(ih.store)['items']['blind_rage']
    assert len(ent['points']) == 2 and ent['points'][0] == [noon('2026-01-01'), 10, 4]
    assert ent['src']['ask'] == 'top_order'
    assert read_json(ih.store)['meta']['from_history'] == 1


def test_sales_come_from_the_trade_log_with_name_resolution(ih):
    catalogue(ih, 'alpha_prime', 'blind_rage')
    write_json(ih.data / 'trade_log.json', [
        {'kind': 'sale', 'name': 'Alpha Prime', 'ts': 2000, 'qty': 1, 'plat': 12, 'total': 12},
        {'kind': 'sale', 'name': 'Alpha Prime', 'ts': 1000, 'qty': 2, 'plat': 10, 'total': 20},
        {'kind': 'sale', 'name': 'Blind Rage', 'ts': 3000, 'qty': 1, 'plat': 7},
        {'kind': 'purchase', 'name': 'Alpha Prime', 'ts': 1500, 'qty': 1, 'plat': 5, 'total': 5},
        {'kind': 'sale', 'name': 'Unknown Thing', 'ts': 4000, 'qty': 1, 'plat': 1, 'total': 1},
    ])

    assert ih.mod.main(['--once', '--force']) == 0

    doc = read_json(ih.store)
    assert set(doc['items']) == {'alpha_prime', 'blind_rage'}     # the unknown name is skipped
    alpha = doc['items']['alpha_prime']
    assert alpha['sales'] == [[1000, 20, 2], [2000, 12, 1]]       # ascending; purchase excluded
    assert alpha['first'] == 1000 and alpha['last'] == 2000       # sales-only entry still dated
    assert doc['items']['blind_rage']['sales'] == [[3000, 7, 1]]  # no total -> plat
    assert doc['meta']['tracked'] == 2


def test_sales_sync_is_idempotent_across_runs(ih, monkeypatch):
    catalogue(ih, 'alpha_prime')
    write_json(ih.data / 'trade_log.json', [
        {'kind': 'sale', 'name': 'Alpha Prime', 'ts': 1000, 'qty': 1, 'plat': 8, 'total': 8}])
    serve(ih, monkeypatch)

    assert ih.mod.main(['--once', '--force']) == 0
    assert ih.mod.main(['--once', '--force']) == 0

    assert read_json(ih.store)['items']['alpha_prime']['sales'] == [[1000, 8, 1]]


# ------------------------------------------------------------------ failure, throttle, dry-run

def test_http_failure_leaves_the_series_untouched(ih):
    seed_store(ih, 'blind_rage', [[1000, 5, 2], [2000, 6, 3]], sales=[[1500, 20, 1]])
    catalogue(ih, 'blind_rage')
    owned(ih, 'blind_rage')
    before = read_json(ih.store)['items']['blind_rage']          # _get is the failing stub

    assert ih.mod.main(['--once', '--force']) == 0

    doc = read_json(ih.store)
    assert doc['items']['blind_rage'] == before                   # no point, no src change
    assert doc['meta']['failures'] == 1 and doc['meta']['fetched'] == 0


def test_http_failure_on_a_fresh_slug_writes_no_point(ih):
    catalogue(ih, 'blind_rage')
    owned(ih, 'blind_rage')

    assert ih.mod.main(['--once', '--force']) == 0

    doc = read_json(ih.store)
    assert doc['items'] == {} and doc['count'] == 0               # nothing honest to store
    assert doc['meta']['failures'] == 1 and doc['meta']['fetched'] == 0


def test_a_404_on_the_id_route_is_retried_by_slug(ih, monkeypatch):
    # live, the v2 id index misses items whose slug still resolves - one retry, one outcome
    catalogue(ih, 'blind_rage')
    owned(ih, 'blind_rage')
    calls = []

    def stub(url, tries=4):
        endpoint = url.rsplit('/orders/item/', 1)[-1]
        calls.append(endpoint)
        return {'error': 'http 404'} if endpoint.startswith('id-') else book(ask=21, bid=17)

    monkeypatch.setattr(ih.mod, '_get', stub)
    assert ih.mod.main(['--once', '--force']) == 0

    doc = read_json(ih.store)
    assert calls == ['id-blind_rage/top', 'blind_rage/top']
    assert doc['items']['blind_rage']['points'][-1][1:] == [21, 17]
    assert doc['meta']['fetched'] == 1 and doc['meta']['failures'] == 0


def test_a_slug_unknown_on_both_routes_counts_exactly_one_failure(ih, monkeypatch):
    catalogue(ih, 'blind_rage')
    owned(ih, 'blind_rage')
    monkeypatch.setattr(ih.mod, '_get', lambda url, tries=4: {'error': 'http 404'})

    assert ih.mod.main(['--once', '--force']) == 0                # both routes 404

    doc = read_json(ih.store)
    assert doc['meta']['failures'] == 1 and doc['meta']['fetched'] == 0
    assert doc['items'] == {}


def test_a_slug_with_no_catalogue_row_is_fetched_by_slug(ih, monkeypatch):
    write_json(ih.data / 'owned.json', [{'slug': 'gamma', 'name': 'Gamma Prime'}])   # no WFM id
    serve(ih, monkeypatch, ask=9, bid=7)

    assert ih.mod.main(['--once', '--force']) == 0

    ent = read_json(ih.store)['items']['gamma']
    assert ent['name'] == 'Gamma Prime' and ent['points'][-1][1:] == [9, 7]
    assert ent['src']['ask'] == 'top_order'


def test_self_throttle_skips_a_fresh_store_and_force_overrides(ih, monkeypatch, capsys):
    catalogue(ih, 'blind_rage')
    owned(ih, 'blind_rage')
    serve(ih, monkeypatch)

    assert ih.mod.main(['--once', '--force']) == 0                # first sweep writes the store
    first = read_json(ih.store)
    capsys.readouterr()

    assert ih.mod.main(['--once']) == 0                           # fresh file -> no fetch
    out = capsys.readouterr().out
    assert 'skipped: fresh' in out and read_json(ih.store)['items'] == first['items']

    assert ih.mod.main(['--once', '--force']) == 0                # --force sweeps anyway
    out = capsys.readouterr().out
    assert 'skipped: fresh' not in out and 'fetched 1' in out


def test_dry_run_plans_the_changes_and_writes_nothing(ih, monkeypatch, capsys):
    catalogue(ih, 'blind_rage')
    owned(ih, 'blind_rage')
    write_json(ih.data / 'price_history.json', {'schema': 1, 'items': {
        'blind_rage': [['2026-01-01', 10, 4, 9, 2]]}})
    serve(ih, monkeypatch, ask=12, bid=5)

    assert ih.mod.main(['--once', '--force', '--dry-run']) == 0
    assert not ih.store.exists()                                  # no store, no tmp file
    out = capsys.readouterr().out
    assert 'dry run' in out and 'blind_rage' in out
    assert 'backfill 1' in out and 'live' in out

    assert ih.mod.main(['--once', '--force']) == 0                 # a real store now
    before = ih.store.read_bytes()
    assert ih.mod.main(['--once', '--force', '--dry-run']) == 0
    assert ih.store.read_bytes() == before                        # dry run left it alone


# ------------------------------------------------------------------ cursor

def test_cursor_advances_and_wraps_to_zero(ih, monkeypatch):
    catalogue(ih, 'a', 'b', 'c', 'd', 'e')
    owned(ih, 'a', 'b', 'c', 'd', 'e')
    serve(ih, monkeypatch)

    assert ih.mod.main(['--once', '--force', '--limit', '3']) == 0
    meta = read_json(ih.store)['meta']
    assert meta['tracked'] == 5 and meta['slugs'] == ['a', 'b', 'c'] and meta['cursor'] == 3
    assert set(read_json(ih.store)['items']) == {'a', 'b', 'c'}

    assert ih.mod.main(['--once', '--force', '--limit', '3']) == 0
    meta = read_json(ih.store)['meta']
    assert meta['slugs'] == ['d', 'e'] and meta['cursor'] == 0     # wrapped, no slug re-fetched
    assert set(read_json(ih.store)['items']) == {'a', 'b', 'c', 'd', 'e'}


def test_slugs_flag_sweeps_only_the_named_slugs_and_keeps_the_cursor(ih, monkeypatch):
    catalogue(ih, 'a', 'b', 'c')
    owned(ih, 'a', 'b', 'c')
    serve(ih, monkeypatch)

    assert ih.mod.main(['--once', '--force', '--limit', '2']) == 0
    assert read_json(ih.store)['meta']['cursor'] == 2

    assert ih.mod.main(['--once', '--force', '--slugs', 'c']) == 0
    meta = read_json(ih.store)['meta']
    assert meta['slugs'] == ['c'] and meta['cursor'] == 2          # an explicit list never moves it
    assert set(read_json(ih.store)['items']) == {'a', 'b', 'c'}


# ------------------------------------------------------------------ rank lanes

def test_rank_lane_snapshot_appends_at_its_real_timestamp(ih, monkeypatch):
    old = 1000
    seed_store(ih, 'blind_rage', [[old, 500, 400]])
    catalogue(ih, 'blind_rage')
    owned(ih, 'blind_rage')
    write_json(ih.data / 'price_lanes.json', {'items': {'blind_rage': {
        'max_rank': 10, 'fetched': old + 100,
        'lanes': {'10': {'ask': 30, 'bid': 20}, '0': {'ask': 12, 'bid': 4}}}}})
    serve(ih, monkeypatch, ask=25, bid=18)

    assert ih.mod.main(['--once', '--force']) == 0

    points = read_json(ih.store)['items']['blind_rage']['points']
    assert points[0] == [old, 500, 400]
    assert points[1] == [old + 100, 30, 20]                        # the max_rank lane, real ts
    assert points[-1][1:] == [25, 18]                              # then the live top-order point
    assert [p[0] for p in points] == sorted(p[0] for p in points)  # still ascending


def test_stale_or_priceless_lane_data_is_not_appended(ih, monkeypatch):
    seed_store(ih, 'blind_rage', [[2000, 5, 2]])                   # last point is newer
    catalogue(ih, 'blind_rage')
    owned(ih, 'blind_rage')
    write_json(ih.data / 'price_lanes.json', {'items': {'blind_rage': {
        'max_rank': 10, 'fetched': 1500, 'lanes': {'10': {'ask': 30, 'bid': 20}}}}})
    serve(ih, monkeypatch)

    assert ih.mod.main(['--once', '--force']) == 0
    points = read_json(ih.store)['items']['blind_rage']['points']
    assert len(points) == 2 and points[0] == [2000, 5, 2]          # stale lane ignored

    write_json(ih.data / 'price_lanes.json', {'items': {'blind_rage': {   # no prices in the lane
        'max_rank': 10, 'fetched': 9000, 'lanes': {'10': {'n_ask': 3, 'n_bid': 0}}}}})
    assert ih.mod.main(['--once', '--force']) == 0
    points = read_json(ih.store)['items']['blind_rage']['points']
    assert points[0] == [2000, 5, 2]
    assert 9000 not in [p[0] for p in points]                      # priceless lane added nothing
    assert all(p[1:] == [12, 5] for p in points[1:])               # only live points after the seed
    assert [p[0] for p in points] == sorted(p[0] for p in points)
