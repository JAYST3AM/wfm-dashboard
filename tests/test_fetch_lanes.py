"""scripts/fetch_lanes.py: rank-lane reduction of a WFM orderbook (data/price_lanes.json).

The whole point of lanes: an item-level "sell 15p / buy 55p" pair is usually a rank-0
listing next to a rank-10 bid, so neither number prices the copy actually held. Every
consumer prices a copy from the lane of the rank the save proves is owned, which makes
the reduction exact:

  * visible orders only (hidden rows never quote);
  * rank null counts as rank 0 (WFM omits the field for unranked tradeables);
  * ask = cheapest sell at that rank, bid = highest buy, bid_low = lowest buy;
  * a rank with no orders on a side keeps its counts but no price on that side.
"""
import os

from conftest import load_script, write_json


def test_lane_summary_reduces_both_sides_per_rank():
    fl = load_script('fetch_lanes')
    lanes = fl.lane_summary([
        {'type': 'sell', 'visible': True, 'platinum': 15, 'rank': 0},
        {'type': 'sell', 'visible': True, 'platinum': 12, 'rank': 0},
        {'type': 'buy', 'visible': True, 'platinum': 4, 'rank': 0},
        {'type': 'buy', 'visible': True, 'platinum': 18, 'rank': 0},
        {'type': 'sell', 'visible': True, 'platinum': 74, 'rank': 10},
        {'type': 'sell', 'visible': True, 'platinum': 90, 'rank': 10},
        {'type': 'buy', 'visible': True, 'platinum': 30, 'rank': 10},
        {'type': 'buy', 'visible': True, 'platinum': 75, 'rank': 10},
        {'type': 'sell', 'visible': True, 'platinum': 55, 'rank': 9},
    ])
    assert lanes[0] == {'n_ask': 2, 'n_bid': 2, 'ask': 12, 'bid': 18, 'bid_low': 4}
    assert lanes[10] == {'n_ask': 2, 'n_bid': 2, 'ask': 74, 'bid': 75, 'bid_low': 30}
    assert lanes[9] == {'n_ask': 1, 'n_bid': 0, 'ask': 55}   # zero bids at rank 9


def test_lane_summary_ignores_hidden_and_junk_orders():
    fl = load_script('fetch_lanes')
    lanes = fl.lane_summary([
        {'type': 'sell', 'visible': False, 'platinum': 1, 'rank': 0},      # hidden
        {'type': 'sell', 'visible': True, 'platinum': None, 'rank': 0},    # no price
        {'type': 'contract', 'visible': True, 'platinum': 5, 'rank': 0},   # not a side
        {'type': 'sell', 'visible': True, 'platinum': 10, 'rank': None},   # null rank -> 0
        None, 'junk',
    ])
    assert lanes == {0: {'n_ask': 1, 'n_bid': 0, 'ask': 10}}


def test_lane_summary_of_an_empty_book():
    fl = load_script('fetch_lanes')
    assert fl.lane_summary([]) == {}
    assert fl.lane_summary(None) == {}


def test_ranked_slugs_keeps_owned_ranked_items_once(data_dir, monkeypatch):
    fl = load_script('fetch_lanes')
    monkeypatch.setattr(fl, 'DATA', str(data_dir))
    write_json(os.path.join(str(data_dir), 'owned.json'), [
        {'slug': 'blind_rage'}, {'slug': 'some_prime_part'}, {'slug': 'blind_rage'},
    ])
    write_json(os.path.join(str(data_dir), 'wfm_items_v2.json'), {'data': [
        {'slug': 'blind_rage', 'id': 'abc', 'maxRank': 10},
        {'slug': 'some_prime_part', 'id': 'def'},
    ]})
    pairs, byslug = fl.ranked_slugs()
    assert pairs == [('blind_rage', 10)]          # deduped, unranked items skipped
    assert byslug['blind_rage']['id'] == 'abc'


def test_ranked_slugs_with_nothing_ranked(data_dir, monkeypatch):
    fl = load_script('fetch_lanes')
    monkeypatch.setattr(fl, 'DATA', str(data_dir))
    write_json(os.path.join(str(data_dir), 'owned.json'), [{'slug': 'some_prime_part'}])
    write_json(os.path.join(str(data_dir), 'wfm_items_v2.json'), {'data': [
        {'slug': 'some_prime_part', 'id': 'def'},
    ]})
    pairs, _ = fl.ranked_slugs()
    assert pairs == []
