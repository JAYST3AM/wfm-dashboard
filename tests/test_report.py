"""scripts/report.py: sell_now must never price a copy that is slotted in a build.

data/inuse.json (copies equipped in any loadout config, built by scripts/trader/inuse.py) is
subtracted from every row: count stays "everything owned" for the dashboard, sellable_count /
value / the totals price the sellable side only, and a fully equipped row is kept in sell_now
with in_use_only: true and a zero value instead of being silently dropped. Every test stages
owned/prices/stats/inuse under tmp_path and points DATA at it - no repo data/ is read or
written, no network.
"""
import pytest

from conftest import load_script, read_json, write_json

OWNED = [
    {'slug': 'plain_prime', 'name': 'Plain Prime Blueprint', 'count': 4,
     'tags': ['prime', 'component']},
    {'slug': 'partly_mod', 'name': 'Partly Mod', 'count': 3, 'tags': ['mod'], 'refinement': 5},
    {'slug': 'partly_mod', 'name': 'Partly Mod', 'count': 2, 'tags': ['mod'], 'refinement': 5},
    {'slug': 'allused_mod', 'name': 'Allused Mod', 'count': 2, 'tags': ['mod'], 'refinement': 5},
    {'slug': 'patient_mod', 'name': 'Patient Mod', 'count': 3, 'tags': ['mod']},
    {'slug': 'junk_a', 'name': 'Junk A', 'count': 5, 'tags': ['mod']},
    {'slug': 'junk_b', 'name': 'Junk B', 'count': 5, 'tags': ['mod']},
    {'slug': 'unpriced_relic', 'name': 'Unpriced Relic', 'count': 1, 'tags': ['relic']},
]

PRICES = {
    'plain_prime': {'wts': 20, 'wtb': 15, 'n_sell': 9, 'n_buy': 4},
    'partly_mod': {'wts': 10, 'wtb': 7, 'n_sell': 5, 'n_buy': 3},
    'allused_mod': {'wts': 30, 'wtb': 25, 'n_sell': 2, 'n_buy': 1},
    'patient_mod': {'wts': 20, 'wtb': 18, 'n_sell': 2, 'n_buy': 1},
    'junk_a': {'wts': 2, 'wtb': 1, 'n_sell': 50, 'n_buy': 10},
    'junk_b': {'wts': 2, 'wtb': 1, 'n_sell': 50, 'n_buy': 10},
}

STATS = {
    'plain_prime': {'vol48': 10, 'volday90': 2.5, 'med48': 19.4, 'min48': 18, 'max48': 21},
    'partly_mod': {'vol48': 8, 'volday90': 1.0, 'med48': 9.7},
    'allused_mod': {'vol48': 5, 'volday90': 0.5},
    'patient_mod': {'vol48': 1, 'volday90': 0.1},
    'junk_a': {'vol48': 1, 'volday90': 4.0},
    'junk_b': {'vol48': 1, 'volday90': 4.0},
}

# inuse.py output. a1 appears twice (one copy slotted in two configs of the same item),
# ghost_mod is not owned, the last row cannot be attributed to a stack at all.
INUSE = {'generated': 1790339727, 'equipped_oids': 12, 'matched_upgrades': 11, 'items': [
    {'item_id': 'p1', 'path': '/Lotus/Mods/Partly', 'rank': 5, 'slug': 'partly_mod', 'name': 'Partly Mod'},
    {'item_id': 'a1', 'path': '/Lotus/Mods/Allused', 'rank': 5, 'slug': 'allused_mod', 'name': 'Allused Mod'},
    {'item_id': 'a1', 'path': '/Lotus/Mods/Allused', 'rank': 5, 'slug': 'allused_mod', 'name': 'Allused Mod'},
    {'item_id': 'a2', 'path': '/Lotus/Mods/Allused', 'rank': 0, 'slug': 'allused_mod', 'name': 'Allused Mod'},
    {'item_id': 'pa1', 'path': '/Lotus/Mods/Patient', 'rank': 0, 'slug': 'patient_mod', 'name': 'Patient Mod'},
    {'item_id': 'pa2', 'path': '/Lotus/Mods/Patient', 'rank': 0, 'slug': 'patient_mod', 'name': 'Patient Mod'},
    {'item_id': 'pa3', 'path': '/Lotus/Mods/Patient', 'rank': 0, 'slug': 'patient_mod', 'name': 'Patient Mod'},
    {'item_id': 'ja1', 'path': '/Lotus/Mods/JunkA', 'rank': 0, 'slug': 'junk_a', 'name': 'Junk A'},
    {'item_id': 'ja2', 'path': '/Lotus/Mods/JunkA', 'rank': 0, 'slug': 'junk_a', 'name': 'Junk A'},
    {'item_id': 'jb1', 'path': '/Lotus/Mods/JunkB', 'rank': 0, 'slug': 'junk_b', 'name': 'Junk B'},
    {'item_id': 'jb2', 'path': '/Lotus/Mods/JunkB', 'rank': 0, 'slug': 'junk_b', 'name': 'Junk B'},
    {'item_id': 'jb3', 'path': '/Lotus/Mods/JunkB', 'rank': 0, 'slug': 'junk_b', 'name': 'Junk B'},
    {'item_id': 'g1', 'path': '/Lotus/Mods/Ghost', 'rank': 0, 'slug': 'ghost_mod', 'name': 'Ghost Mod'},
    {'item_id': None, 'path': '/Lotus/Mods/Unknown', 'rank': 0, 'slug': None, 'name': None},
]}

SELLABLE_VALUE = 130        # 4x20 + 4x10 + 0 + 0 + 3x2 + 2x2
OWNED_VALUE = 270           # every owned copy, equipped ones included
IN_USE_COPIES = 11          # 1 partly + 2 allused + 3 patient + 2 junk_a + 3 junk_b
VALUE_BY_SLUG = {'plain_prime': 80, 'partly_mod': 40, 'allused_mod': 0,
                 'patient_mod': 0, 'junk_a': 6, 'junk_b': 4}


@pytest.fixture
def rep(monkeypatch):
    """Fresh module object per test; DATA is redirected at staging time."""
    return load_script('report', monkeypatch=monkeypatch)


def stage(rep, monkeypatch, tmp_path, owned=OWNED, prices=PRICES, stats=STATS, inuse=INUSE):
    """Write the inputs into a throwaway data/, run the real main(), return report.json."""
    d = tmp_path / 'data'
    d.mkdir(exist_ok=True)
    write_json(d / 'owned.json', owned)
    write_json(d / 'prices.json', prices)
    write_json(d / 'stats.json', stats)
    if inuse is not None:
        write_json(d / 'inuse.json', inuse)
    monkeypatch.setattr(rep, 'DATA', str(d))
    rep.main()
    return read_json(d / 'report.json')


def by_slug(doc, key):
    return {r['slug']: r for r in doc[key]}


def all_rows(doc):
    """Every row the report publishes, whatever list it landed in."""
    return doc['sell_now'] + doc['patient'] + doc['flips'] + doc['junk']['rows']


def only(doc, key, slug):
    return by_slug(doc, key).get(slug)


# ------------------------------------------------------- quantity per row

def test_plain_row_is_untouched_by_in_use_data(rep, monkeypatch, tmp_path):
    doc = stage(rep, monkeypatch, tmp_path)
    r = only(doc, 'sell_now', 'plain_prime')
    assert (r['count'], r['sellable_count'], r['in_use_count']) == (4, 4, 0)
    assert r['in_use_only'] is False and r['value'] == 80 and r['est_days'] == 1.6


def test_partly_in_use_row_prices_only_the_sellable_copies(rep, monkeypatch, tmp_path):
    doc = stage(rep, monkeypatch, tmp_path)
    r = only(doc, 'sell_now', 'partly_mod')
    assert r['count'] == 5                       # two owned stacks, dashboard keeps showing 5
    assert (r['sellable_count'], r['in_use_count']) == (4, 1)
    assert r['in_use_only'] is False and r['value'] == 40 and r['est_days'] == 4.0


def test_fully_in_use_row_is_kept_zeroed_and_flagged(rep, monkeypatch, tmp_path):
    doc = stage(rep, monkeypatch, tmp_path)
    r = only(doc, 'sell_now', 'allused_mod')
    assert r is not None                         # kept, not dropped from the picks list
    assert (r['count'], r['sellable_count'], r['in_use_count']) == (2, 0, 2)
    assert r['in_use_only'] is True and r['value'] == 0 and r['est_days'] is None


def test_in_use_only_rows_are_kept_but_sort_behind_every_pick(rep, monkeypatch, tmp_path):
    doc = stage(rep, monkeypatch, tmp_path)
    slugs = [r['slug'] for r in doc['sell_now']]
    assert slugs == ['plain_prime', 'partly_mod', 'allused_mod']
    assert [r['in_use_only'] for r in doc['sell_now']] == [False, False, True]


def test_duplicate_item_ids_count_as_one_equipped_copy(rep, monkeypatch, tmp_path):
    """a1 is slotted in two configs of the same item: two owned copies, not three."""
    doc = stage(rep, monkeypatch, tmp_path)
    assert only(doc, 'sell_now', 'allused_mod')['in_use_count'] == 2
    assert only(doc, 'sell_now', 'partly_mod')['in_use_count'] == 1


def test_more_equipped_than_owned_is_clamped_never_negative(rep, monkeypatch, tmp_path):
    inuse = {'items': [{'item_id': 'x%d' % i, 'slug': 'allused_mod'} for i in range(5)]}
    doc = stage(rep, monkeypatch, tmp_path, inuse=inuse)
    r = only(doc, 'sell_now', 'allused_mod')
    assert (r['count'], r['in_use_count'], r['sellable_count']) == (2, 2, 0)
    assert r['value'] == 0 and r['in_use_only'] is True
    assert all(x['sellable_count'] >= 0 for x in doc['sell_now'])


def test_unowned_equipped_slug_changes_nothing(rep, monkeypatch, tmp_path):
    doc = stage(rep, monkeypatch, tmp_path)
    assert 'ghost_mod' not in by_slug(doc, 'sell_now')
    assert 'ghost_mod' not in doc['totals']['by_cat']
    assert doc['totals']['value'] == SELLABLE_VALUE


# ------------------------------------------------------------- the totals

def test_totals_price_sellable_copies_only(rep, monkeypatch, tmp_path):
    doc = stage(rep, monkeypatch, tmp_path)
    t = doc['totals']
    values = {r['slug']: r['value'] for r in all_rows(doc) if r['slug'] in VALUE_BY_SLUG}
    assert values == VALUE_BY_SLUG                      # in-use copies priced at zero, row by row
    assert t['value'] == sum(VALUE_BY_SLUG.values()) == SELLABLE_VALUE   # 130p, not the 270p owned
    assert t['value_owned'] == OWNED_VALUE              # the pre-fix basis stays visible
    assert t['by_cat'] == {'prime_part': 80, 'mod': 50}
    assert sum(t['by_cat'].values()) == t['value']
    assert (t['sellable_slugs'], t['stacks']) == (4, 13)   # allused/patient hold 0 sellable
    assert doc['in_use'] == {'available': True, 'copies': IN_USE_COPIES,
                             'value': OWNED_VALUE - SELLABLE_VALUE}


def test_patient_and_junk_also_stop_counting_equipped_copies(rep, monkeypatch, tmp_path):
    doc = stage(rep, monkeypatch, tmp_path)
    assert doc['patient'] == []                          # was 60p of patient stock, all equipped
    assert (doc['junk']['count'], doc['junk']['value']) == (1, 6)   # junk_b: 2 sellable < 3


def test_legacy_field_names_still_ride_along(rep, monkeypatch, tmp_path):
    """static/app.js + export.js read these; they must keep working (count = owned)."""
    doc = stage(rep, monkeypatch, tmp_path)
    for r in doc['sell_now']:
        for key in ('slug', 'name', 'cat', 'count', 'wts', 'med', 'mn48', 'mx48', 'vol48',
                    'volday', 'n_sell', 'n_buy', 'value', 'spread',
                    'sellable_count', 'in_use_count', 'in_use_only'):
            assert key in r, key
        assert r['count'] >= r['sellable_count'] >= 0
        assert r['in_use_only'] is (r['sellable_count'] == 0)


# ------------------------------------------------- missing / torn in-use data

def test_missing_inuse_json_degrades_to_plain_ownership(rep, monkeypatch, tmp_path):
    doc = stage(rep, monkeypatch, tmp_path, inuse=None)
    assert doc['in_use'] == {'available': False, 'copies': 0, 'value': 0}
    assert doc['totals']['value'] == doc['totals']['value_owned'] == OWNED_VALUE
    for r in doc['sell_now']:
        assert r['in_use_count'] == 0 and r['sellable_count'] == r['count']
        assert r['in_use_only'] is False
    assert only(doc, 'sell_now', 'allused_mod')['value'] == 60      # old behaviour, unchanged
    assert [r['slug'] for r in doc['sell_now']] == ['plain_prime', 'allused_mod', 'partly_mod']
    assert [r['slug'] for r in doc['patient']] == ['patient_mod']
    assert (doc['junk']['count'], doc['junk']['value']) == (2, 20)


@pytest.mark.parametrize('doc', [
    None, [], 'plain ownership', {}, {'items': 'nope'}, {'items': []},
    {'items': [None, 7, 'x', {'slug': ''}, {}]}, {'generated': 1, 'equipped_oids': 296},
])
def test_unusable_in_use_documents_count_nothing(rep, doc):
    assert rep.in_use_counts(doc) == {}


def test_in_use_counts_dedupes_and_skips_unattributable_rows(rep):
    counts = rep.in_use_counts(INUSE)
    assert counts['allused_mod'] == 2 and counts['partly_mod'] == 1
    assert counts['ghost_mod'] == 1                  # owned? no - the caller only looks up its rows
    # 14 fixture rows: one duplicate item_id + one row with no slug = 12 equipped copies
    assert sum(counts.values()) == 12


def test_a_torn_document_with_unattributable_rows_degrades(rep, monkeypatch, tmp_path):
    """items rows without slugs/ids are unusable data, not equipped copies."""
    doc = stage(rep, monkeypatch, tmp_path,
                inuse={'items': [None, 'x', {'rank': 5}, {'slug': ''}]})
    assert doc['in_use']['available'] is False
    assert doc['totals']['value'] == OWNED_VALUE
    assert all(r['in_use_only'] is False for r in doc['sell_now'])
