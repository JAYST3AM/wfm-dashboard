"""scripts/invdiff.py: aggregation/diff logic + the data/invdiff.json contract.

invdiff.py accepts --root DIR, so the CLI runs entirely inside tmp_path
(data/owned.json + data/inventory_snapshots/ are created by the test).
"""
import time

import pytest

from conftest import load_script, read_json, write_json


@pytest.fixture
def inv(monkeypatch):
    return load_script('invdiff', monkeypatch=monkeypatch)


def run(inv, root, *extra):
    return inv.main(['invdiff.py', '--root', str(root), *extra])


def snap_path(root, day):
    return root / 'data' / 'inventory_snapshots' / ('owned_%s.json' % day)


TODAY = time.strftime('%Y-%m-%d')


# ------------------------------------------------------------------ pure logic

def test_agg_sums_stacks_and_keeps_first_ducats(inv):
    agg = inv.agg([
        {'slug': 'a', 'name': 'A', 'count': 2, 'tags': ['prime', 'component'], 'ducats': 15},
        {'slug': 'a', 'name': 'A', 'count': 1, 'tags': ['component', 'mod'], 'ducats': 45},
        {'slug': 'b', 'name': 'B'},
        {'name': 'no-slug-row'},
    ])

    assert set(agg) == {'a', 'b'}
    assert agg['a']['count'] == 3                       # stacks summed across rows
    assert agg['a']['tags'] == ['prime', 'component', 'mod']
    assert agg['a']['ducats'] == 15                     # first non-None wins
    assert agg['b']['count'] == 1 and agg['b']['ducats'] is None


def test_compare_splits_added_removed_changed(inv):
    prices = {'a': {'wts': 10}, 'd': {'wts': 2}}
    cur = inv.agg([{'slug': 'a', 'name': 'A', 'count': 3},
                   {'slug': 'b', 'name': 'B', 'count': 2},
                   {'slug': 'c', 'name': 'C', 'count': 1}])
    prev = inv.agg([{'slug': 'a', 'name': 'A', 'count': 1},
                    {'slug': 'b', 'name': 'B', 'count': 2},
                    {'slug': 'd', 'name': 'D', 'count': 4}])

    added, removed, changed, summary = inv.compare(cur, prev, prices, cap=10)

    assert summary == {'added': 1, 'removed': 1, 'changed': 1}
    assert added[0]['slug'] == 'c' and added[0]['delta'] == 1 and added[0]['prev'] == 0
    assert removed[0]['slug'] == 'd' and removed[0]['count'] == 0 and removed[0]['delta'] == -4
    assert removed[0]['value'] == 8                     # valued at the previous stack size
    assert changed[0]['slug'] == 'a' and changed[0]['delta'] == 2 and changed[0]['value'] == 30


def test_compare_caps_lists_but_summary_counts_everything(inv):
    prices = {'low': {'wts': 1}, 'high': {'wts': 99}}
    cur = inv.agg([{'slug': 'low', 'count': 1}, {'slug': 'high', 'count': 1}])

    added, removed, changed, summary = inv.compare(cur, {}, prices, cap=1)

    assert len(added) == 1 and added[0]['slug'] == 'high'      # sorted by value desc
    assert summary['added'] == 2                               # summary stays uncapped


def test_compare_unpriced_items_value_none_and_sort_last(inv):
    cur = inv.agg([{'slug': 'no_price', 'name': 'N', 'count': 5}, {'slug': 'priced', 'count': 1}])
    added, _, _, _ = inv.compare(cur, {}, {'priced': {'wts': 4}}, cap=10)
    assert [r['slug'] for r in added] == ['priced', 'no_price']
    assert added[1]['value'] is None and added[1]['wts'] is None


def test_totals_counts_stacks_and_value(inv):
    agg = inv.agg([{'slug': 'a', 'count': 3}, {'slug': 'b', 'count': 2}])
    assert inv.totals(agg, {'a': {'wts': 10}}) == {'items': 2, 'stacks': 5, 'value': 30}


# ------------------------------------------------------------------ invdiff.json contract

def test_baseline_run_writes_snapshot_and_empty_delta(inv, tmp_path):
    write_json(tmp_path / 'data' / 'owned.json',
               [{'slug': 'a', 'name': 'A', 'count': 2}, {'slug': 'b', 'name': 'B', 'count': 1}])
    write_json(tmp_path / 'data' / 'prices.json', {'a': {'wts': 10}, 'b': {'wts': 3}})

    assert run(inv, tmp_path) == 0

    doc = read_json(tmp_path / 'data' / 'invdiff.json')
    assert doc['status'] == 'baseline' and doc['reference'] is None
    assert doc['refreshed'] is True and doc['cap'] == 60
    assert doc['note'].startswith('no earlier snapshot yet')
    assert doc['snapshot'] == 'data/inventory_snapshots/owned_%s.json' % TODAY
    assert doc['summary'] == {'added': 0, 'removed': 0, 'changed': 0,
                              'net_stacks': 0, 'net_value': 0, 'net_items': 0}
    assert doc['totals']['now'] == {'items': 2, 'stacks': 3, 'value': 23}
    assert doc['totals']['previous'] == {'items': 0, 'stacks': 0, 'value': 0}
    assert doc['intraday'] == {'added': 0, 'removed': 0, 'changed': 0,
                               'added_names': [], 'removed_names': []}
    assert doc['added'] == [] and doc['removed'] == [] and doc['changed'] == []
    assert snap_path(tmp_path, TODAY).exists()
    assert len(read_json(snap_path(tmp_path, TODAY))) == 2


def test_delta_against_previous_day_snapshot(inv, tmp_path):
    write_json(tmp_path / 'data' / 'inventory_snapshots' / 'owned_2020-01-01.json',
               [{'slug': 'b', 'name': 'Beta', 'count': 2}])
    write_json(tmp_path / 'data' / 'owned.json',
               [{'slug': 'a', 'name': 'Alpha', 'count': 1}, {'slug': 'c', 'name': 'Gamma', 'count': 1}])
    write_json(tmp_path / 'data' / 'prices.json',
               {'a': {'wts': 10}, 'b': {'wts': 5}, 'c': {'wts': 4}})

    assert run(inv, tmp_path) == 0

    doc = read_json(tmp_path / 'data' / 'invdiff.json')
    assert doc['status'] == 'ok'
    assert doc['reference'] == 'data/inventory_snapshots/owned_2020-01-01.json'
    assert doc['note'] == 'delta vs owned_2020-01-01.json'
    assert doc['summary'] == {'added': 2, 'removed': 1, 'changed': 0,
                              'net_stacks': 0, 'net_value': 4, 'net_items': 1}
    assert [r['slug'] for r in doc['added']] == ['a', 'c']       # value desc
    assert [r['value'] for r in doc['added']] == [10, 4]
    assert doc['removed'][0]['slug'] == 'b' and doc['removed'][0]['value'] == 10
    assert doc['totals']['now']['value'] == 14 and doc['totals']['previous']['value'] == 10


def test_removed_and_changed_rows_and_cap_flag(inv, tmp_path):
    write_json(tmp_path / 'data' / 'inventory_snapshots' / 'owned_2020-01-01.json',
               [{'slug': 'gone', 'name': 'Gone', 'count': 3}, {'slug': 'shrink', 'name': 'Shrink', 'count': 5}])
    write_json(tmp_path / 'data' / 'owned.json',
               [{'slug': 'shrink', 'name': 'Shrink', 'count': 2},
                {'slug': 'new1', 'name': 'New One', 'count': 1}, {'slug': 'new2', 'name': 'New Two', 'count': 1}])
    write_json(tmp_path / 'data' / 'prices.json', {'gone': {'wts': 6}, 'new1': {'wts': 1}})

    assert run(inv, tmp_path, '--cap', '1') == 0

    doc = read_json(tmp_path / 'data' / 'invdiff.json')
    assert doc['cap'] == 1
    assert [r['slug'] for r in doc['added']] == ['new1'] and doc['summary']['added'] == 2
    assert [r['slug'] for r in doc['removed']] == ['gone'] and doc['removed'][0]['value'] == 18
    assert [r['slug'] for r in doc['changed']] == ['shrink']
    assert doc['changed'][0]['delta'] == -3 and doc['changed'][0]['prev'] == 5


def test_intraday_tracking_and_unchanged_rerun(inv, tmp_path):
    write_json(tmp_path / 'data' / 'owned.json', [{'slug': 'a', 'name': 'Alpha', 'count': 1}])
    write_json(tmp_path / 'data' / 'prices.json', {'a': {'wts': 2}, 'd': {'wts': 7}})

    assert run(inv, tmp_path) == 0                                   # writes today's baseline copy
    write_json(tmp_path / 'data' / 'owned.json',
               [{'slug': 'a', 'name': 'Alpha', 'count': 1}, {'slug': 'd', 'name': 'Delta', 'count': 1}])
    assert run(inv, tmp_path) == 0

    doc = read_json(tmp_path / 'data' / 'invdiff.json')
    assert doc['refreshed'] is True and doc['status'] == 'baseline'
    assert doc['intraday']['added'] == 1 and doc['intraday']['added_names'] == ['Delta']
    assert doc['intraday']['removed'] == 0 and doc['intraday']['removed_names'] == []
    assert len(read_json(snap_path(tmp_path, TODAY))) == 2            # snapshot refreshed in place

    assert run(inv, tmp_path) == 0                                   # third run, nothing changed
    doc = read_json(tmp_path / 'data' / 'invdiff.json')
    assert doc['refreshed'] is False
    assert doc['intraday'] == {'added': 0, 'removed': 0, 'changed': 0,
                               'added_names': [], 'removed_names': []}


def test_no_owned_json_returns_1(inv, tmp_path):
    (tmp_path / 'data').mkdir()
    assert run(inv, tmp_path) == 1
    assert not (tmp_path / 'data' / 'invdiff.json').exists()


def test_bad_flag_prints_usage_and_returns_2(inv, tmp_path):
    assert inv.main(['invdiff.py', '--nope']) == 2
