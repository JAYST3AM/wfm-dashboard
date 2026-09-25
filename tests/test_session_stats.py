"""scripts/session_stats.py: clustering/session math + the data/session_stats.json contract.

session_stats.py takes --root DIR, so the CLI runs inside tmp_path with synthetic
trade_log.json / plat_history.json fixtures.
"""
import time

import pytest

from conftest import load_script, read_json, write_json


@pytest.fixture
def ss(monkeypatch):
    return load_script('session_stats', monkeypatch=monkeypatch)


def write_inputs(root, events, points=None, prices=None):
    write_json(root / 'data' / 'trade_log.json', events)
    write_json(root / 'data' / 'plat_history.json', points or [])
    write_json(root / 'data' / 'prices.json', prices or {})


def run(ss, root, *extra):
    return ss.main(['session_stats.py', '--root', str(root), *extra])


# ------------------------------------------------------------------ pure logic

def test_clusters_splits_on_gap_threshold(ss):
    assert ss.clusters([0, 2700], 2700) == [[0, 2700]]          # exactly gap -> same session
    assert ss.clusters([0, 2701], 2700) == [[0], [2701]]        # one second over -> split
    assert ss.clusters([5, 1, 5], 10) == [[1, 5]]               # sorted + de-duplicated
    assert ss.clusters([0, 100, 1000], 200) == [[0, 100], [1000]]
    assert ss.clusters([], 60) == []


def test_session_aggregates_trades_points_and_plat_delta(ss):
    events = [
        {'ts': 1100, 'kind': 'sale', 'name': 'A', 'slug': 'a', 'qty': 2, 'plat': 5, 'total': 10},
        {'ts': 1200, 'kind': 'purchase', 'name': 'B', 'qty': 1, 'total': 4},
        {'ts': 1300, 'kind': 'listing', 'slug': 'c'},
        {'ts': 5000, 'kind': 'sale', 'name': 'Z', 'qty': 9, 'total': 900},   # outside the window
    ]
    points = [{'ts': 1000, 'plat': 100, 'credits': 50}, {'ts': 2000, 'plat': 130, 'credits': 20}]

    s = ss.session([1000, 2000], events, points, {'c': {'wts': 7}})

    assert s['date'] == time.strftime('%Y-%m-%d', time.localtime(1000))
    assert (s['start'], s['end'], s['dur_min']) == (1000, 2000, round(1000 / 60.0, 1))
    assert s['kind'] == 'trade'
    assert (s['events'], s['points'], s['kinds']) == (3, 2, {'sale': 1, 'purchase': 1, 'listing': 1})
    assert (s['sales'], s['units_sold'], s['gross']) == (1, 2, 10.0)
    assert (s['purchases'], s['units_bought'], s['spent']) == (1, 1, 4.0)
    assert s['net'] == 6.0 and s['plat_per_hour'] == 21.6
    assert (s['plat_from'], s['plat_to'], s['plat_delta']) == (100, 130, 30)
    assert s['credits_delta'] == -30
    assert s['items'] == ['A', 'B']                 # listing has no name, sale Z is outside
    assert s['touched_slugs'] == 2                  # 'a' from the sale, 'c' from the listing
    assert s['best_sale'] == {'name': 'A', 'qty': 2, 'plat': 5, 'total': 10}


def test_session_kinds_and_empty_points(ss):
    listing = ss.session([100, 200], [{'ts': 150, 'kind': 'reprice', 'slug': 'x'}], [], {})
    assert listing['kind'] == 'listing' and listing['gross'] == 0
    assert listing['plat_from'] is None and listing['plat_to'] is None
    assert listing['plat_delta'] is None and listing['credits_delta'] is None
    assert listing['best_sale'] is None and listing['items'] == []

    idle = ss.session([100, 200], [], [{'ts': 150, 'plat': 9}], {})
    assert idle['kind'] == 'idle' and idle['events'] == 0 and idle['points'] == 1
    assert idle['plat_delta'] == 0                   # single point: no delta to report
    assert idle['plat_per_hour'] == 0.0


# ------------------------------------------------------------------ session_stats.json contract

def test_main_writes_session_stats_contract(ss, tmp_path):
    t0 = 1700000000
    write_inputs(
        tmp_path,
        events=[{'ts': t0, 'kind': 'sale', 'name': 'A', 'slug': 'a', 'qty': 1, 'plat': 10, 'total': 10},
                {'ts': t0 + 600, 'kind': 'purchase', 'name': 'B', 'qty': 1, 'total': 4},
                {'ts': t0 + 1200, 'kind': 'listing', 'slug': 'c'}],
        points=[{'ts': t0, 'plat': 100, 'credits': 1000}, {'ts': t0 + 1200, 'plat': 118, 'credits': 900}])

    assert run(ss, tmp_path) == 0

    doc = read_json(tmp_path / 'data' / 'session_stats.json')
    assert set(doc) == {'generated', 'gap_min', 'totals', 'sessions', 'shown'}
    assert doc['gap_min'] == 45 and doc['shown'] == 1 and len(doc['sessions']) == 1

    s = doc['sessions'][0]
    assert (s['start'], s['end'], s['dur_min']) == (t0, t0 + 1200, 20.0)
    assert s['kind'] == 'trade' and s['events'] == 3 and s['points'] == 2
    assert (s['gross'], s['spent'], s['net']) == (10.0, 4.0, 6.0)
    assert (s['plat_from'], s['plat_to'], s['plat_delta']) == (100, 118, 18)
    assert s['start_at'].startswith(time.strftime('%Y-%m-%d', time.localtime(t0)))

    totals = doc['totals']
    assert totals['sessions'] == 1 and totals['trade_sessions'] == 1 and totals['days'] == 1
    assert totals['in_game_hours'] == 0.33
    assert (totals['gross'], totals['spent'], totals['net']) == (10.0, 4.0, 6.0)
    assert totals['units_sold'] == 1 and totals['events'] == 3 and totals['points'] == 2
    assert totals['best_session'] == s['start_at'] and totals['best_net'] == 6
    assert totals['busiest_session'] == s['start_at']
    assert totals['first_at'] == time.strftime('%Y-%m-%d %H:%M', time.localtime(t0))
    assert totals['last_at'] == time.strftime('%Y-%m-%d %H:%M', time.localtime(t0 + 1200))


def test_gap_flag_changes_session_split(ss, tmp_path):
    t0 = 1700000000
    write_inputs(tmp_path,
                 events=[{'ts': t0, 'kind': 'sale', 'name': 'A', 'qty': 1, 'total': 5},
                         {'ts': t0 + 1800, 'kind': 'sale', 'name': 'B', 'qty': 1, 'total': 6}])

    assert run(ss, tmp_path) == 0                                   # default 45 min: one session
    doc = read_json(tmp_path / 'data' / 'session_stats.json')
    assert doc['gap_min'] == 45 and doc['totals']['sessions'] == 1

    assert run(ss, tmp_path, '--gap', '10') == 0                    # 30 min apart, gap 10 -> two
    doc = read_json(tmp_path / 'data' / 'session_stats.json')
    assert doc['gap_min'] == 10.0 and doc['totals']['sessions'] == 2
    assert [s['start'] for s in doc['sessions']] == [t0 + 1800, t0]  # newest first
    assert doc['totals']['gross'] == 11.0 and doc['totals']['net'] == 11.0


def test_last_flag_caps_rows_but_not_totals(ss, tmp_path):
    t0 = 1700000000
    write_inputs(tmp_path,
                 events=[{'ts': t0, 'kind': 'sale', 'name': 'A', 'qty': 1, 'total': 3},
                         {'ts': t0 + 3600, 'kind': 'sale', 'name': 'B', 'qty': 1, 'total': 4},
                         {'ts': t0 + 7200, 'kind': 'sale', 'name': 'C', 'qty': 1, 'total': 5}])

    assert run(ss, tmp_path, '--last', '2') == 0

    doc = read_json(tmp_path / 'data' / 'session_stats.json')
    assert doc['totals']['sessions'] == 3 and doc['shown'] == 2 and len(doc['sessions']) == 2
    assert [s['start'] for s in doc['sessions']] == [t0 + 7200, t0 + 3600]
    assert doc['totals']['gross'] == 12.0


def test_no_history_returns_1(ss, tmp_path):
    (tmp_path / 'data').mkdir()
    assert run(ss, tmp_path) == 1
    assert not (tmp_path / 'data' / 'session_stats.json').exists()


def test_bad_flag_prints_usage_and_returns_2(ss, tmp_path):
    assert ss.main(['session_stats.py', '--nope']) == 2
