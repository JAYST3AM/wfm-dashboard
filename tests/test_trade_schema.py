"""The shared trade record and lane identity (scripts/trade_schema.py).

Outside review, round 3: canonicalisation has to happen at the single writer boundary, and a lane —
not a slug, and not a rank on its own — is what identifies a row.
"""
import pytest

from conftest import load_script


@pytest.fixture
def schema(monkeypatch):
    return load_script('trade_schema', monkeypatch=monkeypatch)


# --------------------------------------------------------------------------- the lane
def test_a_rank_lane_keeps_the_spelling_the_state_already_used(schema):
    assert schema.lane_key('primed_continuity', 'rank 0') == 'primed_continuity#r0'
    assert schema.lane_key('primed_continuity', 'rank 10') == 'primed_continuity#r10'
    assert schema.norm_lane('rank 0') == 'r0' and schema.norm_lane(6) == 'r6'


def test_two_lanes_of_one_slug_are_two_identities(schema):
    """The bug this exists for: Intact and Radiant versions of one relic share a slug and have no
    rank at all, so a slug alone (or a rank alone, which is None for both) cannot tell them apart."""
    intact = {'slug': 'neo_d3_relic', 'lane': 'intact'}
    radiant = {'slug': 'neo_d3_relic', 'lane': 'radiant'}
    assert schema.key_of(intact) != schema.key_of(radiant)
    assert schema.key_of(intact) == schema.lane_key('neo_d3_relic', 'intact')
    assert schema.key_of({'slug': 'x', 'lane': ''}) != schema.key_of({'slug': 'x', 'lane': 'intact'})


def test_a_lane_is_read_from_the_lane_or_derived_from_the_rank(schema):
    assert schema.lane_of({'lane': 'rank 6'}) == 'rank 6'
    assert schema.lane_of({'rank': 6}) == 'rank 6'
    assert schema.lane_of({'lane_rank': 6}) == 'rank 6'
    assert schema.lane_of({'lane': ''}) == '' and schema.lane_of({}) == ''
    assert schema.rank_of({'lane': 'rank 6'}) == 6 and schema.rank_of({'lane': 'intact'}) is None


def test_a_lane_name_is_never_silently_mangled(schema):
    assert schema.norm_lane(' Radiant ') == 'radiant'
    assert schema.norm_lane('Intact') == 'intact'
    assert schema.norm_lane('') == schema.LANE_NONE
    assert schema.norm_lane('intac') == 'intac'      # not a refinement: kept, not guessed at


# --------------------------------------------------------------------------- the record
def test_canonical_stores_the_unit_and_the_money(schema):
    rec = schema.canonical({'kind': 'sale', 'slug': 'X', 'qty': 3, 'plat': 48}, now=1000)
    assert rec['slug'] == 'x' and rec['item'] == 'x'
    assert rec['plat'] == 48 and rec['total'] == 144
    assert rec['kind'] == 'sale' and rec['ts'] == 1000 and rec['id'].startswith('t-')
    assert rec['source'] and rec['src']


def test_canonical_accepts_the_money_instead_and_derives_the_unit(schema):
    rec = schema.canonical({'kind': 'sale', 'slug': 'x', 'qty': 3, 'total': 144}, now=1)
    assert rec['plat'] == 48 and rec['total'] == 144
    rec = schema.canonical({'kind': 'purchase', 'slug': 'x', 'qty': 5, 'price': 9}, now=1)
    assert rec['plat'] == 9 and rec['total'] == 45


def test_canonical_refuses_a_trade_that_carries_no_price(schema):
    """A record nothing can sum is worse than a rejected one: this is the writer boundary."""
    with pytest.raises(ValueError):
        schema.canonical({'kind': 'sale', 'slug': 'x', 'qty': 3})
    with pytest.raises(ValueError):
        schema.canonical({'kind': 'sale', 'slug': 'x', 'qty': 1, 'plat': -5})
    with pytest.raises(ValueError):
        schema.canonical({'kind': 'barter', 'slug': 'x', 'qty': 1, 'plat': 5})


def test_canonical_leaves_a_note_alone(schema):
    """A note is not a trade: no price, no qty, and no money invented for it."""
    rec = schema.canonical({'kind': 'note', 'name': 'History tracking started', 'ts': 5}, now=1)
    assert rec['kind'] == 'note' and 'total' not in rec and rec['ts'] == 5


def test_a_record_without_a_total_still_reads_as_money(schema):
    """Old-record compatibility: the pre-canonical shape carried a unit price in `plat` and no
    `total` at all, and every reader sums `total`. money_of() must not let that money disappear."""
    assert schema.money_of({'kind': 'sale', 'qty': 1, 'plat': 15}) == 15
    assert schema.money_of({'kind': 'sale', 'qty': 4, 'plat': 15}) == 60
    assert schema.money_of({'kind': 'sale', 'qty': 1, 'plat': 15, 'total': 15}) == 15
    assert schema.money_of({'kind': 'sale', 'qty': 2, 'plat': 9, 'total': 18}) == 18
    assert schema.money_of({'kind': 'note'}) == 0 and schema.money_of(None) == 0
    assert schema.unit_of({'qty': 2, 'total': 18}) == 9


def test_a_stable_id_is_the_same_for_the_same_trade(schema):
    a = schema.canonical({'kind': 'sale', 'slug': 'x', 'qty': 1, 'plat': 5, 'user': 'w'}, now=99)
    b = schema.canonical({'kind': 'sale', 'slug': 'x', 'qty': 1, 'plat': 5, 'user': 'w'}, now=99)
    c = schema.canonical({'kind': 'sale', 'slug': 'x', 'qty': 2, 'plat': 5, 'user': 'w'}, now=99)
    assert a['id'] == b['id'] and a['id'] != c['id']
    kept = schema.canonical({'kind': 'sale', 'slug': 'x', 'qty': 1, 'plat': 5, 'id': 't-kept'}, now=1)
    assert kept['id'] == 't-kept'
