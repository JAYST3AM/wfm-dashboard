"""scripts/price_history.py: same-day idempotency, movers math, price_movers.json contract.

price_history.py reads PRICE_HISTORY_PATH / PRICE_MOVERS_PATH from the environment at
import time, so the fixture loads it through those overrides (proving the documented
env hook works) and points module.DATA at tmp_path for its inputs.
"""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from conftest import load_script, read_json, write_json

TODAY = date.today().isoformat()


@pytest.fixture
def ph(tmp_path, monkeypatch, data_dir):
    store = tmp_path / 'price_history.json'
    movers = tmp_path / 'price_movers.json'
    mod = load_script('price_history', monkeypatch=monkeypatch,
                      env={'PRICE_HISTORY_PATH': str(store), 'PRICE_MOVERS_PATH': str(movers)})
    monkeypatch.setattr(mod, 'DATA', str(data_dir))
    return SimpleNamespace(mod=mod, data=data_dir, store=store, movers=movers)


def seed(ph, prices, stats):
    write_json(ph.data / 'prices.json', prices)
    write_json(ph.data / 'stats.json', stats)


# ------------------------------------------------------------------ env override

def test_env_paths_override_repo_data(ph):
    assert ph.mod.HISTP == str(ph.store)
    assert ph.mod.MOVERP == str(ph.movers)
    assert str(ph.store).startswith(str(ph.data.parent))       # nothing points at the repo data/


# ------------------------------------------------------------------ pure logic

def test_make_point_prefers_med48_and_rounds(ph):
    assert ph.mod.make_point('d', 'a', {'a': {'wts': 10, 'wtb': 4}},
                             {'a': {'med48': 12.3456, 'vol48': 3}}) == ['d', 10, 4, 12.35, 3]
    assert ph.mod.make_point('d', 'b', {'b': {'wts': 1}}, {'b': {'median': 2.5}}) == ['d', 1, None, 2.5, None]
    assert ph.mod.make_point('d', 'c', {}, {}) == ['d', None, None, None, None]


def test_find_movers_ranks_abs_pct_and_filters_noise(ph):
    hist = {
        'up': [['2026-09-01', 10, 5, 9, 1], ['2026-09-02', 20, 5, 9, 1]],     # +100%
        'down': [['2026-09-01', 20, 5, 9, 1], ['2026-09-02', 10, 5, 9, 1]],   # -50%
        'tiny': [['2026-09-01', 2, 5, 9, 1], ['2026-09-02', 9, 5, 9, 1]],     # prev < MIN_PREV
        'fresh': [['2026-09-02', 5, 5, 9, 1]],                                # no earlier day
        'stale': [['2026-09-01', 10, 5, 9, 1]],                               # no point today
        'unpriced': [['2026-09-01', None, 5, 9, 1], ['2026-09-02', 9, 5, 9, 1]],
    }
    rows = ph.mod.find_movers(hist, {'up': 'Up Item'}, '2026-09-02')

    assert [r['slug'] for r in rows] == ['up', 'down']          # sorted by |pct| desc
    assert rows[0] == dict(slug='up', name='Up Item', prev=10, now=20, delta=10.0, pct=100.0,
                           vol48=1, median=9)
    assert rows[1]['name'] == 'down' and rows[1]['delta'] == -10.0 and rows[1]['pct'] == -50.0


def test_fallback_uses_widest_sell_vs_median_gap(ph):
    hist = {
        'wide': [['d', 10, 5, 4, 1]],        # +150%
        'narrow': [['d', 5, 5, 4.5, 1]],     # +11.1%
        'unpriced': [['d', None, 5, 4, 1]],
        'cheap': [['d', 3, 5, 2, 1]],        # median below MIN_PREV
        'other_day': [['z', 100, 5, 4, 1]],
    }
    rows = ph.mod.fallback(hist, {'wide': 'Wide'}, 'd')

    assert [r['slug'] for r in rows] == ['wide', 'narrow']
    assert rows[0]['gap_pct'] == 150.0 and rows[0]['name'] == 'Wide' and rows[0]['wts'] == 10
    assert rows[1]['gap_pct'] == 11.1


# ------------------------------------------------------------------ store contract

def test_first_run_baselines_store_and_movers(ph):
    seed(ph, {'a': {'wts': 10, 'wtb': 4}, 'b': {'wts': 100}},
         {'a': {'med48': 12.5, 'vol48': 3}, 'b': {'median': 90, 'vol48': 1}})

    assert ph.mod.main() == 0

    doc = read_json(ph.store)
    assert doc['schema'] == 1 and isinstance(doc['updated'], str)
    assert doc['fields'] == ['date', 'wts', 'wtb', 'median', 'vol48']
    assert doc['items']['a'] == [[TODAY, 10, 4, 12.5, 3]]
    assert doc['items']['b'] == [[TODAY, 100, None, 90, 1]]

    movers = read_json(ph.movers)
    assert set(movers) == {'generated', 'day', 'prev_day', 'mode', 'ranked', 'movers'}
    assert movers['day'] == TODAY and movers['prev_day'] is None
    assert movers['mode'] == 'baseline-gaps' and movers['ranked'] == 2
    assert [m['slug'] for m in movers['movers']] == ['a', 'b']     # widest gap first
    assert movers['movers'][0]['gap_pct'] == -20.0                # (10 - 12.5) / 12.5
    assert movers['movers'][1]['gap_pct'] == 11.1


def test_same_day_rerun_is_idempotent(ph, capsys):
    seed(ph, {'a': {'wts': 10}}, {'a': {'med48': 12.5, 'vol48': 3}})
    ph.mod.main()
    capsys.readouterr()
    first = read_json(ph.store)

    assert ph.mod.main() == 0
    out = capsys.readouterr().out
    second = read_json(ph.store)

    assert second['items'] == first['items']                      # no new point, no edits
    assert second['schema'] == first['schema'] == ph.mod.SCHEMA
    assert len(second['items']['a']) == 1
    assert 'new day: 0' in out and 'unchanged: 1' in out
    assert read_json(ph.movers)['ranked'] == 1


def test_same_day_rerun_replaces_the_days_point(ph, capsys):
    seed(ph, {'a': {'wts': 10}}, {'a': {'med48': 12.5, 'vol48': 3}})
    ph.mod.main()
    seed(ph, {'a': {'wts': 15}}, {'a': {'med48': 12.5, 'vol48': 3}})

    ph.mod.main()
    out = capsys.readouterr().out
    doc = read_json(ph.store)

    assert doc['items']['a'] == [[TODAY, 15, None, 12.5, 3]]       # replaced, not duplicated
    assert 'new day: 0' in out and 'same-day updated: 1' in out


def test_second_day_produces_24h_movers(ph):
    earlier = (date.today() - timedelta(days=1)).isoformat()
    write_json(ph.store, {'schema': 1, 'items': {'a': [[earlier, 10, 4, 11, 2]]}})
    seed(ph, {'a': {'wts': 20, 'wtb': 6}}, {'a': {'med48': 21, 'vol48': 4}})
    write_json(ph.data / 'wfm_items_v2.json',
               {'data': [{'slug': 'a', 'i18n': {'en': {'name': 'Alpha Prime'}}}]})

    ph.mod.main()

    doc = read_json(ph.store)
    assert [p[0] for p in doc['items']['a']] == [earlier, TODAY]   # history accumulates
    movers = read_json(ph.movers)
    assert movers['mode'] == '24h-movers' and movers['prev_day'] == earlier
    assert movers['ranked'] == 1
    assert movers['movers'][0] == dict(slug='a', name='Alpha Prime', prev=10, now=20, delta=10.0,
                                       pct=100.0, vol48=4, median=21)


def test_history_retention_caps_points_per_item(ph):
    old_days = [(date.today() - timedelta(days=n)).isoformat() for n in range(400, 0, -1)]
    write_json(ph.store, {'schema': 1, 'items': {'a': [[d, 1, 1, 1, 1] for d in old_days]}})
    seed(ph, {'a': {'wts': 10}}, {'a': {'med48': 9, 'vol48': 1}})

    ph.mod.main()

    points = read_json(ph.store)['items']['a']
    assert len(points) == ph.mod.KEEP == 400
    assert points[-1][0] == TODAY and points[0][0] != old_days[0]   # oldest point dropped


def test_missing_prices_writes_nothing_and_returns_1(ph):
    write_json(ph.data / 'stats.json', {})
    assert ph.mod.main() == 1
    assert not ph.store.exists() and not ph.movers.exists()
