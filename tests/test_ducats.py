"""scripts/ducats.py: aggregation/classification logic + data/ducats.json contract.

ducats.py keeps DATA at module level (no --root flag), so main() is run with
module.DATA monkeypatched to tmp_path; sys.argv is stubbed for its argparse call.
"""
import sys
from types import SimpleNamespace

import pytest

from conftest import load_script, read_json, write_json


@pytest.fixture
def duc(monkeypatch):
    return load_script('ducats', monkeypatch=monkeypatch)


def owned_row(slug, ducats, count=1, tags=('prime', 'component')):
    return {'slug': slug, 'name': slug.upper(), 'ducats': ducats, 'count': count, 'tags': list(tags)}


# ------------------------------------------------------------------ pure logic

def test_aggregate_sums_counts_and_flags_conflicts(duc):
    owned = [owned_row('a', 15), owned_row('a', 45, count=2), owned_row('b', 0), {'slug': 'c', 'name': 'C'}]
    agg = duc.aggregate(owned)

    assert set(agg) == {'a'}                       # parts without ducats are ignored
    a = agg['a']
    assert a['count'] == 3 and a['ducats'] == 45   # max wins, mismatch flagged
    assert a['conflict'] is True
    assert a['tags'] == {'prime', 'component'}     # collected as a set, sorted when classified
    assert duc.classify(a, {'wts': 10}, {}, 7.5, 4.0)['tags'] == ['component', 'prime']


def test_classify_hold_without_price(duc):
    agg = duc.aggregate([owned_row('a', 15)])
    row = duc.classify(agg['a'], None, None, 7.5, 4.0)

    assert row['verdict'] == 'HOLD' and row['wts'] is None
    assert row['sell_total'] is None and row['ducats_per_plat'] is None
    assert 'cannot price it' in row['reason']


def test_classify_burn_sell_and_hold_math(duc):
    agg = duc.aggregate([owned_row('burn', 45), owned_row('sell', 15), owned_row('junk', 15)])

    burn = duc.classify(agg['burn'], {'wts': 5, 'wtb': 4}, {'median': 6, 'vol48': 9}, 7.5, 4.0)
    assert burn['verdict'] == 'BURN'               # 45/5 = 9.0 ducats per plat >= junk rate
    assert burn['ducats_per_plat'] == 9.0 and burn['sell_total'] == 5
    assert burn['junk_cost'] == 6.0                # 45 ducats bought as junk cost 6p
    assert burn['edge_plat'] == -1.0               # selling instead would lose 1p
    assert burn['vol48'] == 9 and burn['median'] == 6

    sell = duc.classify(agg['sell'], {'wts': 10}, {}, 7.5, 4.0)
    assert sell['verdict'] == 'SELL'               # 15/10 = 1.5 d/p < junk rate, stack >= 4p
    assert sell['plat_per_ducat'] == 0.667 and sell['edge_plat'] == 8.0

    junk = duc.classify(agg['junk'], {'wts': 3}, {}, 7.5, 4.0)
    assert junk['verdict'] == 'HOLD' and 'trade slot not worth it' in junk['reason']


def test_classify_boundary_ratio_counts_as_burn(duc):
    agg = duc.aggregate([owned_row('a', 15)])
    row = duc.classify(agg['a'], {'wts': 2}, {}, 7.5, 4.0)
    assert row['ducats_per_plat'] == 7.5 and row['verdict'] == 'BURN'


# ------------------------------------------------------------------ ducats.json contract

@pytest.fixture
def duc_run(tmp_path, monkeypatch, data_dir, duc):
    monkeypatch.setattr(duc, 'DATA', str(data_dir))
    monkeypatch.setattr(sys, 'argv', ['ducats.py'])
    write_json(data_dir / 'owned.json', [
        owned_row('burn_me', 45, count=2),          # 45 d, wts 5  ->  9.0 d/p -> BURN
        owned_row('sell_me', 15, count=1),          # 15 d, wts 10 ->  1.5 d/p -> SELL
        owned_row('junk_stack', 15, count=1),       # 15 d, wts 3  ->  5.0 d/p but 3p stack -> HOLD
        owned_row('no_price', 15, count=1),         # no market price -> HOLD
    ])
    write_json(data_dir / 'prices.json', {'burn_me': {'wts': 5, 'wtb': 3, 'n_sell': 40},
                                          'sell_me': {'wts': 10, 'wtb': 8},
                                          'junk_stack': {'wts': 3}})
    write_json(data_dir / 'stats.json', {'burn_me': {'median': 6, 'vol48': 12, 'volday90': 30}})
    write_json(data_dir / 'lastData.dec.json', {'PlayerLevel': 30, 'TradesRemaining': 12})
    duc.main()
    return read_json(data_dir / 'ducats.json')


def test_main_writes_ducats_contract(duc_run):
    assert set(duc_run) == {'generated', 'params', 'account', 'summary', 'buckets', 'rows'}
    assert duc_run['params']['burn_ratio'] == 7.5
    assert duc_run['params']['min_sell_plat'] == 4.0
    assert duc_run['params']['rank_key'].startswith('ducats_per_plat')
    assert duc_run['account'] == {'mr': 30, 'trades_available': 12}
    assert [r['slug'] for r in duc_run['rows']] == ['burn_me', 'junk_stack', 'sell_me', 'no_price']
    ranks = [(r['ducats_per_plat'] or 0) for r in duc_run['rows']]
    assert ranks == [9.0, 5.0, 1.5, 0]
    assert ranks == sorted(ranks, reverse=True)


def test_ducats_buckets_and_summary_agree_with_rows(duc_run):
    rows, summary, buckets = duc_run['rows'], duc_run['summary'], duc_run['buckets']

    assert buckets == {
        'sell': [r['slug'] for r in rows if r['verdict'] == 'SELL'],
        'burn': [r['slug'] for r in rows if r['verdict'] == 'BURN'],
        'hold': [r['slug'] for r in rows if r['verdict'] == 'HOLD'],
    }
    assert buckets['burn'] == ['burn_me']
    assert buckets['sell'] == ['sell_me']
    assert sorted(buckets['hold']) == ['junk_stack', 'no_price']

    assert summary['slugs'] == 4
    assert (summary['sell_count'], summary['burn_count'], summary['hold_count']) == (1, 1, 2)
    assert summary['total_burn_ducats'] == 90            # 45 d x 2 copies
    assert summary['total_sell_plat'] == 10
    assert summary['burn_plat_forgone'] == 10            # 5p x 2 copies given up by burning
    assert summary['junk_cost_to_match'] == 12.0         # 90 / 7.5
    assert summary['burn_is_cheaper_by'] == 2.0
    assert summary['ducats_owned'] == 90 + 15 + 15 + 15
    assert summary['plat_if_all_sold'] == 10 + 10 + 3     # burn stack 10p + sell 10p + junk 3p


def test_ducats_rows_expose_the_documented_columns(duc_run):
    row = {r['slug']: r for r in duc_run['rows']}['burn_me']
    for key in ('slug', 'name', 'count', 'ducats', 'ducats_total', 'tags', 'conflict', 'wts',
                'wtb', 'n_sell', 'median', 'vol48', 'volday', 'sell_total', 'ducats_per_plat',
                'plat_per_ducat', 'junk_cost', 'edge_plat', 'verdict', 'reason'):
        assert key in row, key
    assert row['count'] == 2 and row['ducats_total'] == 90
    assert row['sell_total'] == 10 and row['wts'] == 5 and row['n_sell'] == 40
    assert row['volday'] == 30 and row['vol48'] == 12
    assert row['reason'].startswith('ducat-dense')


def test_ducats_ratio_and_min_sell_flags_are_honoured(tmp_path, monkeypatch, data_dir, duc):
    monkeypatch.setattr(duc, 'DATA', str(data_dir))
    monkeypatch.setattr(sys, 'argv', ['ducats.py', '--ratio', '3', '--min-sell', '50'])
    write_json(data_dir / 'owned.json', [owned_row('a', 15, count=1)])
    write_json(data_dir / 'prices.json', {'a': {'wts': 10}})
    duc.main()

    doc = read_json(data_dir / 'ducats.json')
    assert doc['params']['burn_ratio'] == 3.0 and doc['params']['min_sell_plat'] == 50.0
    assert doc['rows'][0]['ducats_per_plat'] == 1.5
    assert doc['rows'][0]['verdict'] == 'HOLD'           # 10p stack < the raised 50p floor
