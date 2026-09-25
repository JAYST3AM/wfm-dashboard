"""Import regression tests for scripts/import_aleca_stats.py.

Synthetic AlecaFrame export (3 trades incl. one 2-item bundle + 2 generalDataPoints)
imported twice against tmp paths: dedupe must add 0 on the rerun and the bundle's
platinum must be prorated by largest remainder.

The script has no env-path override (DATA is derived from __file__), so the tests
monkeypatch module.DATA to tmp_path - nothing in the repo's real data/ is touched.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from conftest import load_script, read_json, write_json

PLAT = '/AF_Special/Platinum'
SALE_TS, BUNDLE_TS, BUY_TS = '2026-09-01T10:00:00Z', '2026-09-02T11:30:00Z', '2026-09-03T09:00:00Z'
POINT_TS = ['2026-09-01T00:00:00Z', '2026-09-02T00:00:00Z']


def epoch(ts):
    return int(datetime.fromisoformat(ts.replace('Z', '+00:00')).timestamp())


def _export():
    """3 trades: 1 single-item sale (20p), 1 two-item bundle sale (15p), 1 purchase (10p)."""
    return {
        'trades': [
            {'ts': SALE_TS, 'user': 'Alpha',
             'tx': [{'name': 'Item A', 'displayName': 'Item A', 'cnt': 1}],
             'rx': [{'name': PLAT, 'cnt': 20}]},
            {'ts': BUNDLE_TS, 'user': 'Beta',
             'tx': [{'name': 'Item B', 'displayName': 'Item B', 'cnt': 1},
                    {'name': 'Item C', 'displayName': 'Item C', 'cnt': 1}],
             'rx': [{'name': PLAT, 'cnt': 15}]},
            {'ts': BUY_TS, 'user': 'Gamma',
             'tx': [{'name': PLAT, 'cnt': 10}],
             'rx': [{'name': 'Item D', 'displayName': 'Item D', 'cnt': 2}]},
        ],
        'generalDataPoints': [
            {'ts': POINT_TS[0], 'plat': 100, 'credits': 1000, 'mr': 20},
            {'ts': POINT_TS[1], 'plat': 90, 'credits': 900, 'mr': 21},
        ],
    }


@pytest.fixture
def imp(tmp_path, monkeypatch, data_dir):
    mod = load_script('import_aleca_stats', monkeypatch=monkeypatch)
    monkeypatch.setattr(mod, 'DATA', str(data_dir))
    export = write_json(tmp_path / 'aleca_stats_export.json', _export())
    return SimpleNamespace(mod=mod, data=data_dir, export=export)


def _log(imp):
    return read_json(imp.data / 'trade_log.json')


def _hist(imp):
    return read_json(imp.data / 'plat_history.json')


def test_first_run_imports_all_events(imp, capsys):
    imp.mod.main(imp.export)
    out = capsys.readouterr().out

    log, hist = _log(imp), _hist(imp)
    assert len(log) == 4                       # A, B, C sale + D purchase
    assert len(hist) == 2
    assert 'trades: +4 events (3 sale, 1 purchase, 0 notes) | earned +35p | spent 10p' in out
    assert 'plat history: +2 daily points (total now 2)' in out
    assert 'trade log total now 4 events' in out


def test_bundle_plat_is_prorated_by_largest_remainder(imp):
    imp.mod.main(imp.export)
    by_name = {e['name']: e for e in _log(imp)}

    # 15p over 2 copies -> base 7, remainder 1 -> first copy 8, second 7
    assert (by_name['Item B']['total'], by_name['Item C']['total']) == (8, 7)
    assert by_name['Item B']['total'] + by_name['Item C']['total'] == 15
    for name in ('Item B', 'Item C'):
        assert by_name[name]['kind'] == 'sale' and by_name[name]['qty'] == 1
        assert by_name[name]['plat'] == by_name[name]['total']
        assert 'bundle 2 items, 15p total' in by_name[name]['note']
        assert 'with Beta' in by_name[name]['note']
    assert by_name['Item B']['src'] == 'af:%s:Item B' % BUNDLE_TS


def test_single_sale_and_purchase_math(imp):
    imp.mod.main(imp.export)
    by_name = {e['name']: e for e in _log(imp)}

    a = by_name['Item A']
    assert (a['kind'], a['qty'], a['plat'], a['total']) == ('sale', 1, 20, 20)
    assert a['ts'] == epoch(SALE_TS)
    assert a['note'] == 'with Alpha · imported (AlecaFrame)'
    assert a['src'] == 'af:%s:Item A' % SALE_TS

    d = by_name['Item D']
    assert (d['kind'], d['qty'], d['plat'], d['total']) == ('purchase', 2, 5, 10)
    assert d['ts'] == epoch(BUY_TS)
    assert 'bundle' not in d['note']            # 2 copies of ONE item is not a bundle


def test_written_files_match_server_contract(imp):
    """trade_log.json / plat_history.json entry keys are the dashboard's public shape."""
    imp.mod.main(imp.export)
    log, hist = _log(imp), _hist(imp)

    assert [e['ts'] for e in log] == sorted(e['ts'] for e in log)          # ascending
    for entry in log:
        assert set(entry) == {'ts', 'kind', 'name', 'qty', 'plat', 'total', 'note', 'src'}
        assert entry['kind'] in ('sale', 'purchase', 'note')
        assert isinstance(entry['ts'], int) and entry['ts'] > 0
        assert isinstance(entry['qty'], int) and isinstance(entry['total'], int)
    assert len({e['src'] for e in log}) == 4                               # unique dedupe keys

    assert [p['ts'] for p in hist] == sorted(p['ts'] for p in hist)
    for point in hist:
        assert set(point) == {'ts', 'plat', 'credits', 'mr', 'src'}
        assert point['src'] == 'alecaframe'
        assert isinstance(point['ts'], int)
    assert hist[0]['ts'] == epoch(POINT_TS[0]) and hist[0]['plat'] == 100
    assert hist[1]['mr'] == 21


def test_rerun_is_idempotent_and_leaves_files_unchanged(imp, capsys):
    imp.mod.main(imp.export)
    capsys.readouterr()
    before_log = (imp.data / 'trade_log.json').read_bytes()
    before_hist = (imp.data / 'plat_history.json').read_bytes()

    imp.mod.main(imp.export)                    # same export, second run
    out = capsys.readouterr().out

    assert 'trades: +0 events (0 sale, 0 purchase, 0 notes) | earned +0p | spent 0p' in out
    assert 'plat history: +0 daily points (total now 2)' in out
    assert len(_log(imp)) == 4 and len(_hist(imp)) == 2
    assert (imp.data / 'trade_log.json').read_bytes() == before_log
    assert (imp.data / 'plat_history.json').read_bytes() == before_hist


def test_rerun_merges_a_new_export_without_duplicating(imp, capsys):
    imp.mod.main(imp.export)
    capsys.readouterr()

    extra = {'trades': [{'ts': '2026-09-04T08:00:00Z', 'user': 'Delta',
                         'tx': [{'name': 'Item E', 'displayName': 'Item E', 'cnt': 1}],
                         'rx': [{'name': PLAT, 'cnt': 3}]}],
             'generalDataPoints': [{'ts': '2026-09-04T00:00:00Z', 'plat': 80}]}
    partial = write_json(imp.data.parent / 'partial_export.json', extra)

    imp.mod.main(partial)                       # second export: 1 trade, 1 point
    out = capsys.readouterr().out

    assert 'trades: +1 events (1 sale, 0 purchase, 0 notes)' in out
    assert len(_log(imp)) == 5 and len(_hist(imp)) == 3
    # rerunning the full original export again changes nothing
    imp.mod.main(imp.export)
    assert 'trades: +0 events' in capsys.readouterr().out
    assert len(_log(imp)) == 5 and len(_hist(imp)) == 3


def test_swap_and_plat_only_trades_are_not_sales(imp):
    export = {'trades': [
        {'ts': '2026-09-05T12:00:00Z', 'user': 'Echo',
         'tx': [{'name': 'Item F', 'displayName': 'Item F', 'cnt': 1}],
         'rx': [{'name': 'Item G', 'displayName': 'Item G', 'cnt': 1},
                {'name': 'Item H', 'displayName': 'Item H', 'cnt': 1}]},
        {'ts': '2026-09-06T12:00:00Z', 'user': 'Foxtrot',
         'tx': [], 'rx': [{'name': PLAT, 'cnt': 5}]},          # plat without items: skipped
    ], 'generalDataPoints': []}
    path = write_json(imp.data.parent / 'swap_export.json', export)

    imp.mod.main(path)
    log = _log(imp)

    assert len(log) == 1
    assert log[0]['kind'] == 'note' and log[0]['total'] == 0 and log[0]['plat'] == 0
    assert 'swap for Item G + Item H' in log[0]['note']


def test_bundle_of_three_and_two_copies_of_one_item(imp):
    export = {'trades': [
        {'ts': '2026-09-07T12:00:00Z', 'user': 'Golf',
         'tx': [{'name': 'P', 'displayName': 'P', 'cnt': 1}, {'name': 'Q', 'displayName': 'Q', 'cnt': 1},
                {'name': 'R', 'displayName': 'R', 'cnt': 1}],
         'rx': [{'name': PLAT, 'cnt': 10}]},
        {'ts': '2026-09-08T12:00:00Z', 'user': 'Hotel',
         'tx': [{'name': 'S', 'displayName': 'S', 'cnt': 2}],
         'rx': [{'name': PLAT, 'cnt': 15}]},
    ], 'generalDataPoints': []}
    path = write_json(imp.data.parent / 'mixed_export.json', export)

    imp.mod.main(path)
    by_name = {e['name']: e for e in _log(imp)}

    # 10p over 3 copies -> base 3, remainder 1 -> 4 + 3 + 3
    assert [by_name[n]['total'] for n in ('P', 'Q', 'R')] == [4, 3, 3]
    assert sum(by_name[n]['total'] for n in ('P', 'Q', 'R')) == 10
    assert 'bundle 3 items, 10p total' in by_name['P']['note']
    # 15p over one 2-count stack -> a single row, plat 7, total 15 (rounded down per unit)
    s = by_name['S']
    assert (s['qty'], s['plat'], s['total']) == (2, 7, 15)
    assert 'bundle 2 items, 15p total' in s['note']
