"""scripts/relics_panel.py: schema, refinement stripping, the uniqueName join, the three
obtain kinds, honesty rules and the CLI - all offline.

Every test builds its fixtures under tmp_path and points BOTH globals at them through the
module's env hooks (WFM_DATA_DIR for data/, WFM_STATIC_DIR for the static copy), so the
repo's real data/ and static/ are never read or written - the public CI checks out a tree
with no data/ directory at all. The CLI behaviour (--selftest, --dry-run, the static copy)
runs in a subprocess against a seeded tmp dir.
"""
import json
import os
import subprocess
import sys

import pytest

from conftest import SCRIPTS, load_script, read_json, write_json

SRC = os.path.join(SCRIPTS, 'relics_panel.py')
REFS = ['Intact', 'Exceptional', 'Flawless', 'Radiant']
DROP_LINE_KEYS = ['detail', 'label']

# ---------------------------------------------------------------- fixtures
def rare(item='Akstiletto Prime Barrel', chance=2, on_market=True):
    row = {'chance': chance, 'rarity': 'Rare',
           'item': {'name': item, 'uniqueName': '/Lotus/Types/Recipes/x/' + item.replace(' ', '')}}
    if on_market:
        row['item']['warframeMarket'] = {'id': 'x', 'urlName': item.lower().replace(' ', '_')}
    return row


def rewards(intact_chance=2, radiant_chance=10):
    """The same six-item table at two refinements, chances taken verbatim from Relics.json."""
    return [{'chance': 25.33, 'rarity': 'Uncommon',
             'item': {'name': 'Forma Blueprint',
                      'uniqueName': '/Lotus/Types/Recipes/Components/FormaBlueprint'}},
            rare('Akstiletto Prime Barrel', intact_chance)]


def entry(name, uniq, vaulted=None, locations=None, rewards_list=None, extra=None):
    row = {'name': name, 'uniqueName': uniq, 'type': 'Relic', 'tradable': True,
           'rewards': rewards() if rewards_list is None else rewards_list,
           'locations': locations or []}
    if vaulted is not None:
        row['vaulted'] = vaulted
    row.update(extra or {})
    return row


PLACES = [{'chance': 4.5, 'location': 'Earth/Cetus (Bounty), Rotation A', 'rarity': 'Rare'},
          {'chance': 0.29, 'location': 'Void/Mithra (Interception), Rotation C',
           'rarity': 'Legendary'}]

FIXTURE_RELICS = [
    entry('Lith A1 Intact', '/Lotus/Types/Game/Projections/T1VoidProjectionAABronze', False, PLACES),
    entry('Lith A1 Exceptional', '/Lotus/Types/Game/Projections/T1VoidProjectionAASilver', False, PLACES),
    entry('Lith A1 Flawless', '/Lotus/Types/Game/Projections/T1VoidProjectionAAGold', False, PLACES),
    entry('Lith A1 Radiant', '/Lotus/Types/Game/Projections/T1VoidProjectionAAPlatinum', False, PLACES,
          rewards(10, 10)),
    entry('Meso B2 Intact', '/Lotus/Types/Game/Projections/T2VoidProjectionBBBronze', True),
    entry('Meso B2 Radiant', '/Lotus/Types/Game/Projections/T2VoidProjectionBBPlatinum', True,
          rewards_list=rewards(10, 10)),
    # two internal variants of one relic (WFCD ships 'Lith G12' this way)
    entry('Lith C3 Intact', '/Lotus/Types/Game/Projections/T1VoidProjectionCCBronze', True),
    entry('Lith C3 Intact', '/Lotus/Types/Game/Projections/T1VoidProjectionCCBronzeB', True),
    # the generic placeholder: no refinement suffix, no rewards, no locations, no vaulted flag
    {'name': 'Axi Relic', 'uniqueName': '/Lotus/Types/Game/Projections/T4VoidProjection',
     'type': 'Relic', 'tradable': True, 'rewards': [], 'locations': []},
    # no refinement suffix, a real table, sources in drops[] instead of locations[]
    entry('Requiem Eterna Relic', '/Lotus/Types/Game/Projections/T5VoidProjectionImmortalOmniA',
          True, extra={'drops': [{'location': 'Kuva Flood', 'chance': 100, 'rarity': 'Common'},
                                 {'location': 'Kuva Siphon', 'chance': 50, 'rarity': 'Common'}]}),
]

FIXTURE_OWNED = [
    {'slug': 'lith_a1_relic', 'name': 'Lith A1 Relic', 'count': 3, 'tags': ['relic', 'lith'],
     'path': '/Lotus/Types/Game/Projections/T1VoidProjectionAABronze', 'refinement': 'Intact'},
    {'slug': 'lith_c3_relic', 'name': 'Lith C3 Relic', 'count': 2, 'tags': ['relic', 'lith'],
     'path': '/Lotus/Types/Game/Projections/T1VoidProjectionCCBronzeB', 'refinement': 'Intact'},
    {'slug': 'requiem_eterna_relic', 'name': 'Requiem Eterna Relic', 'count': 8,
     'tags': ['relic', 'requiem'],
     'path': '/Lotus/Types/Game/Projections/T5VoidProjectionImmortalOmniA', 'refinement': 'Intact'},
    {'slug': 'meso_b2_relic', 'name': 'Meso B2 Relic', 'count': 1, 'tags': ['relic', 'meso'],
     'path': '/Lotus/Types/Game/Projections/T2VoidProjectionBBBronze', 'refinement': None},
    {'slug': 'gone_relic', 'name': 'Gone Relic', 'count': 1, 'tags': ['relic'],
     'path': '/Lotus/Types/Game/Projections/NotInTable', 'refinement': 'Intact'},
]
FIXTURE_EV = {'generated': '2026-09-26T00:00:00', 'rows': [
    {'relic': 'Lith A1 Relic', 'slug': 'lith_a1_relic', 'refinement': 'Intact', 'count': 3,
     'ev_unit_wts': 4.87, 'action': 'OPEN'},
    {'relic': 'Requiem Eterna Relic', 'slug': 'requiem_eterna_relic', 'refinement': 'Intact',
     'count': 8, 'ev_unit_wts': 5.32, 'action': 'OPEN'},
]}
FIXTURE_PRICES = {'lith_a1_relic': {'wts': 3, 'wtb': 1, 'n_sell': 3, 'n_buy': 1},
                  'meso_b2_relic': {'wts': None, 'wtb': None, 'n_sell': 0, 'n_buy': 0}}

SUMMARY_LINE = 'relics_panel: 5 relics | farmable 2 | vaulted 3 | owned 3 stacks | drop-located 1'


def seed(mod, relics=None, owned=None, ev=None, prices=None):
    """Write the fixture inputs into the module's tmp data dir (None = leave the file out)."""
    if relics is not None:
        write_json(os.path.join(mod.DATA, 'dropdata', 'items', 'Relics.json'), relics)
    if owned is not None:
        write_json(os.path.join(mod.DATA, 'owned.json'), owned)
    if ev is not None:
        write_json(os.path.join(mod.DATA, 'relic_ev.json'), ev)
    if prices is not None:
        write_json(os.path.join(mod.DATA, 'prices.json'), prices)


def seed_all(mod, relics=FIXTURE_RELICS, owned=FIXTURE_OWNED, ev=FIXTURE_EV, prices=FIXTURE_PRICES):
    """The default fixture set; pass None for ev/prices to test their absence."""
    seed(mod, relics, owned, ev, prices)


@pytest.fixture
def panel(tmp_path, monkeypatch):
    """scripts/relics_panel.py with DATA and STATIC redirected into tmp_path."""
    data, static = tmp_path / 'data', tmp_path / 'static'
    data.mkdir()
    static.mkdir()
    mod = load_script('relics_panel', monkeypatch=monkeypatch,
                      env={'WFM_DATA_DIR': str(data), 'WFM_STATIC_DIR': str(static)})
    assert str(data) == mod.DATA and str(static) == mod.STATIC
    return mod


def build(mod, now=1700000000):
    """build_store() over the files seed()ed into the module's tmp data dir."""
    entries = mod.jload(mod.dropdata_path())
    owned, _ = mod.load_owned()
    ev, _ = mod.load_ev()
    prices, pmeta = mod.load_prices()
    return mod.build_store(entries, owned, ev, prices, prices_as_of=pmeta.get('as_of'), now=now)


def relics_by_name(doc):
    return {r['name']: r for r in doc['relics']}


def run_cli(tmp_path, *args):
    """Run the script in a subprocess with both dirs pointed at tmp_path."""
    env = dict(os.environ)
    env['WFM_DATA_DIR'] = str(tmp_path / 'data')
    env['WFM_STATIC_DIR'] = str(tmp_path / 'static')
    return subprocess.run([sys.executable, SRC, *args], cwd=str(tmp_path), env=env,
                          capture_output=True, text=True, timeout=120)


def seed_cli(tmp_path):
    """A subprocess has no module globals: write the fixtures by path and hand back the dirs."""
    data, static = tmp_path / 'data', tmp_path / 'static'
    (data / 'dropdata' / 'items').mkdir(parents=True)
    static.mkdir()
    write_json(data / 'dropdata' / 'items' / 'Relics.json', FIXTURE_RELICS)
    write_json(data / 'owned.json', FIXTURE_OWNED)
    write_json(data / 'relic_ev.json', FIXTURE_EV)
    write_json(data / 'prices.json', FIXTURE_PRICES)
    return data, static


# ---------------------------------------------------------------- schema
def test_schema_keys(panel):
    seed_all(panel)
    doc, stats = build(panel)

    assert sorted(doc) == ['count', 'generated_from', 'relics', 'schema', 'source', 'summary',
                           'tiers', 'updated', 'updated_iso']
    assert doc['schema'] == 1
    assert isinstance(doc['updated'], int) and doc['updated_iso'].endswith('Z')
    assert doc['count'] == len(doc['relics']) == 5
    assert isinstance(doc['source'], str) and doc['source']
    assert isinstance(doc['generated_from'], dict)
    assert sorted(doc['summary']) == ['farmable', 'owned_distinct', 'owned_stacks', 'refinements',
                                      'vaulted']
    assert doc['summary']['refinements'] == REFS
    assert doc['summary'] == {'farmable': 2, 'vaulted': 3, 'owned_distinct': 3, 'owned_stacks': 3,
                              'refinements': REFS}
    assert all(isinstance(k, str) and isinstance(v, int) for k, v in doc['tiers'].items())

    for relic in doc['relics']:
        assert sorted(relic) == ['best_reward', 'ev', 'market', 'name', 'obtain', 'owned',
                                 'owned_total', 'rewards', 'slug', 'tier', 'uniqueNames', 'vaulted']
        assert isinstance(relic['vaulted'], bool) and isinstance(relic['owned_total'], int)
        assert sorted(relic['obtain']) == ['complete', 'kind', 'lines', 'note']
        assert relic['obtain']['kind'] in ('drop', 'vaulted', 'unknown')
        assert all(sorted(line) == DROP_LINE_KEYS for line in relic['obtain']['lines'])
        for refinement, rows in relic['rewards'].items():
            assert refinement in REFS
            assert all(sorted(row) == ['chance', 'item', 'rarity', 'slug'] for row in rows)
        if relic['best_reward'] is not None:
            assert sorted(relic['best_reward']) == ['chance_radiant', 'item', 'rarity', 'slug']
        if relic['market'] is not None:
            assert sorted(relic['market']) == ['as_of', 'median', 'slug', 'wtb', 'wts']
        for value in relic['ev'].values():
            assert value is None or sorted(value) == ['ev', 'verdict']
    assert stats['count'] == doc['count']


def test_summary_line_format(panel):
    seed_all(panel)
    _doc, stats = build(panel)
    assert panel.summary_line(stats) == SUMMARY_LINE


def test_tiers_and_sort_order(panel):
    seed_all(panel)
    doc, _stats = build(panel)

    assert doc['tiers'] == {'Lith': 2, 'Meso': 1, 'Axi': 1, 'Requiem': 1}
    assert [r['name'] for r in doc['relics']] == ['Lith A1', 'Lith C3', 'Meso B2', 'Axi Relic',
                                                  'Requiem Eterna Relic']
    # Lith before Meso before Axi before Requiem - the tier order, not the alphabet
    assert list(doc['tiers'])[:4] == ['Lith', 'Meso', 'Axi', 'Requiem']


# ---------------------------------------------------------------- stripping
@pytest.mark.parametrize('name,base,refinement', [
    ('Axi A1 Intact', 'Axi A1', 'Intact'),
    ('Axi A1 Exceptional', 'Axi A1', 'Exceptional'),
    ('Lith G12 Flawless', 'Lith G12', 'Flawless'),
    ('Meso N14 Radiant', 'Meso N14', 'Radiant'),
    ('Axi Relic', 'Axi Relic', None),                       # the placeholders keep their name
    ('Requiem Eterna Relic', 'Requiem Eterna Relic', None),  # 'Relic' is not a refinement
])
def test_refinement_stripping(panel, name, base, refinement):
    assert panel.strip_refinement(name) == (base, refinement)


@pytest.mark.parametrize('base,slug', [
    ('Lith F1', 'lith_f1_relic'),
    ('Axi A1', 'axi_a1_relic'),
    ('Requiem Eterna Relic', 'requiem_eterna_relic'),
    ('Void Relic', 'void_relic'),
])
def test_relic_slug_rule(panel, base, slug):
    assert panel.relic_slug(base) == slug


# ---------------------------------------------------------------- the join
def test_owned_join_is_by_unique_name(panel):
    seed_all(panel)
    doc, _stats = build(panel)
    by = relics_by_name(doc)
    a1 = by['Lith A1']

    assert a1['uniqueNames'] == {
        'Intact': '/Lotus/Types/Game/Projections/T1VoidProjectionAABronze',
        'Exceptional': '/Lotus/Types/Game/Projections/T1VoidProjectionAASilver',
        'Flawless': '/Lotus/Types/Game/Projections/T1VoidProjectionAAGold',
        'Radiant': '/Lotus/Types/Game/Projections/T1VoidProjectionAAPlatinum'}
    assert a1['owned'] == {'Intact': 3, 'Exceptional': 0, 'Flawless': 0, 'Radiant': 0}
    assert a1['owned_total'] == 3
    assert doc['generated_from']['owned']['matched'] == 3


def test_every_variant_of_a_duplicated_relic_counts(panel):
    seed_all(panel)
    by = relics_by_name(build(panel)[0])

    # owned.json holds the SECOND variant's uniqueName; the store publishes the first
    assert by['Lith C3']['uniqueNames'] == {
        'Intact': '/Lotus/Types/Game/Projections/T1VoidProjectionCCBronze'}
    assert by['Lith C3']['owned'] == {'Intact': 2}
    assert by['Lith C3']['owned_total'] == 2


def test_an_unowned_refinement_stays_zero_and_the_relic_is_still_listed(panel):
    seed_all(panel)
    by = relics_by_name(build(panel)[0])

    meso = by['Meso B2']                     # the owned row carries no refinement label
    assert meso['owned'] == {'Intact': 0, 'Radiant': 0}
    assert meso['owned_total'] == 0
    assert meso['rewards']['Intact']         # listed with its tables anyway
    assert any('no refinement label' in note for note in
               build(panel)[0]['generated_from']['notes'])


def test_an_owned_row_outside_the_table_is_reported_not_silently_dropped(panel):
    seed_all(panel)
    doc, _stats = build(panel)
    assert doc['generated_from']['owned']['unmatched'] == ['gone_relic']


def test_a_relic_with_no_refinement_suffix_keeps_its_owned_label(panel):
    seed_all(panel)
    by = relics_by_name(build(panel)[0])

    eterna = by['Requiem Eterna Relic']
    assert eterna['uniqueNames'] == {} and eterna['rewards'] == {}
    assert eterna['owned'] == {'Intact': 8}          # from owned.json's own refinement label
    assert eterna['owned_total'] == 8
    assert eterna['ev']['Intact'] == {'ev': 5.32, 'verdict': 'OPEN'}


# ---------------------------------------------------------------- the three obtain kinds
def test_drop_relic_lines_carry_location_chance_and_rarity(panel):
    seed_all(panel)
    a1 = relics_by_name(build(panel)[0])['Lith A1']

    assert a1['obtain']['kind'] == 'drop'
    assert a1['obtain']['complete'] is True
    assert a1['obtain']['note'] is None
    assert a1['obtain']['lines'] == [
        {'label': 'Earth/Cetus (Bounty), Rotation A', 'detail': '4.5% \u00b7 Rare'},
        {'label': 'Void/Mithra (Interception), Rotation C', 'detail': '0.29% \u00b7 Legendary'}]
    # the same location list on all four refinements collapses to one line each
    assert len(a1['obtain']['lines']) == 2


def test_vaulted_relic_has_no_source_and_says_so(panel):
    seed_all(panel)
    by = relics_by_name(build(panel)[0])

    meso = by['Meso B2']
    assert meso['obtain']['kind'] == 'vaulted'
    assert meso['obtain']['lines'] == []
    assert meso['obtain']['complete'] is True
    assert meso['obtain']['note'] == panel.VAULTED_NOTE
    assert meso['obtain']['note'] == 'Vaulted', 'the note is a label, not a sentence'


def test_placeholder_entry_stays_unknown(panel):
    seed_all(panel)
    by = relics_by_name(build(panel)[0])

    placeholder = by['Axi Relic']
    assert placeholder['obtain'] == {'kind': 'unknown', 'lines': [], 'complete': False,
                                     'note': panel.PLACEHOLDER_NOTE}
    assert placeholder['uniqueNames'] == {} and placeholder['owned'] == {}
    assert placeholder['best_reward'] is None
    assert placeholder['rewards'] == {} and placeholder['owned_total'] == 0
    assert 'placeholder' in placeholder['obtain']['note']


def test_a_named_relic_without_locations_or_a_vaulted_flag_is_not_invented_for(panel):
    """A relic the table knows nothing about gets 'unknown' - never a made-up source."""
    seed_all(panel, relics=FIXTURE_RELICS + [
        entry('Neo Z9 Intact', '/Lotus/Types/Game/Projections/T3VoidProjectionZZBronze',
              vaulted=None, locations=[])])
    by = relics_by_name(build(panel)[0])

    assert by['Neo Z9']['obtain']['kind'] == 'unknown'
    assert by['Neo Z9']['obtain']['lines'] == []
    assert by['Neo Z9']['obtain']['complete'] is False


# ---------------------------------------------------------------- honesty
def test_no_relic_claims_a_location_unless_the_data_has_one(panel):
    seed_all(panel)
    doc, _stats = build(panel)

    droppers = [r for r in doc['relics'] if r['obtain']['kind'] == 'drop']
    assert [r['name'] for r in droppers] == ['Lith A1']
    for relic in doc['relics']:
        if relic['obtain']['kind'] != 'drop':
            assert relic['obtain']['lines'] == [], relic['name']
        else:
            assert relic['obtain']['lines'], relic['name']
            assert relic['vaulted'] is False


def test_reward_chances_are_taken_verbatim_never_rescaled(panel):
    seed_all(panel)
    a1 = relics_by_name(build(panel)[0])['Lith A1']

    assert [r['chance'] for r in a1['rewards']['Intact']] == [25.33, 2]
    assert [r['chance'] for r in a1['rewards']['Radiant']] == [25.33, 10]
    assert a1['best_reward'] == {'item': 'Akstiletto Prime Barrel', 'slug': 'akstiletto_prime_barrel',
                                 'rarity': 'Rare', 'chance_radiant': 10}
    # a reward the market does not carry keeps slug null rather than a slug that would 404
    assert a1['rewards']['Intact'][0]['slug'] is None


def test_market_block_labels_the_snapshot(panel):
    seed_all(panel)
    by = relics_by_name(build(panel)[0])

    prices_mtime = panel.iso_z(os.path.getmtime(panel.prices_path()))
    assert by['Lith A1']['market'] == {'slug': 'lith_a1_relic', 'wts': 3, 'wtb': 1, 'median': 2,
                                       'as_of': prices_mtime}
    assert by['Meso B2']['market'] == {'slug': 'meso_b2_relic', 'wts': None, 'wtb': None,
                                       'median': None, 'as_of': prices_mtime}
    assert by['Axi Relic']['market'] is None          # no snapshot row -> no market block


def test_ev_is_reused_from_relic_ev_never_recomputed(panel):
    seed_all(panel)
    a1 = relics_by_name(build(panel)[0])['Lith A1']

    assert a1['ev']['Intact'] == {'ev': 4.87, 'verdict': 'OPEN'}
    assert a1['ev']['Radiant'] is None
    assert all(v is None for v in relics_by_name(build(panel)[0])['Meso B2']['ev'].values())


# ---------------------------------------------------------------- degradation
def test_missing_optional_inputs_are_noted_and_never_fatal(panel):
    seed_all(panel, ev=None, prices=None)
    doc, stats = build(panel)

    assert stats['count'] == 5
    assert stats['owned_stacks'] == 3
    assert all(r['market'] is None for r in doc['relics'])
    assert all(v is None for r in doc['relics'] for v in r['ev'].values())
    notes = ' '.join(doc['generated_from']['notes'])
    assert 'relic_ev.py' in notes and 'fetch_prices.py' in notes


def test_a_cached_run_never_touches_the_network(panel, monkeypatch):
    seed_all(panel)

    def no_network(*args, **kwargs):
        raise AssertionError('the network was contacted although the cache was complete')

    monkeypatch.setattr(panel.urllib.request, 'urlopen', no_network)
    assert panel.main(['--once']) == 0
    assert read_json(panel.out_path())['count'] == 5
    assert read_json(panel.static_copy_path())['count'] == 5


def test_a_junk_cache_is_reported_honestly_offline(panel):
    write_json(os.path.join(panel.DATA, 'dropdata', 'items', 'Relics.json'), {'not': 'a list'})
    assert panel.main(['--once', '--offline']) == 1
    assert not os.path.exists(panel.out_path())


# ---------------------------------------------------------------- CLI (subprocess)
def test_cli_selftest_exits_zero_and_writes_nothing(tmp_path):
    result = run_cli(tmp_path, '--selftest')

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith('selftest: ok (')
    assert list(tmp_path.rglob('relics_panel.json')) == []
    assert list(tmp_path.rglob('Relics.json')) == []


def test_cli_dry_run_prints_the_plan_and_writes_nothing(tmp_path):
    data, static = seed_cli(tmp_path)
    before = sorted(str(p) for p in tmp_path.rglob('*'))

    result = run_cli(tmp_path, '--dry-run', '--offline')

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0] == SUMMARY_LINE
    assert 'dry-run - nothing written' in result.stdout
    assert not (data / 'relics_panel.json').exists()
    assert not (static / 'relics_panel.json').exists()
    assert sorted(str(p) for p in tmp_path.rglob('*')) == before


def test_cli_once_writes_the_store_and_the_static_copy(tmp_path):
    data, static = seed_cli(tmp_path)

    result = run_cli(tmp_path, '--once', '--offline')

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0] == SUMMARY_LINE
    store = read_json(data / 'relics_panel.json')
    copy = read_json(static / 'relics_panel.json')          # the page loads static/ directly
    assert store == copy
    assert store['count'] == 5
    assert sorted(store) == ['count', 'generated_from', 'relics', 'schema', 'source', 'summary',
                             'tiers', 'updated', 'updated_iso']
    assert 'static copy ->' in result.stdout


def test_cli_out_path_override(tmp_path):
    seed_cli(tmp_path)
    target = tmp_path / 'elsewhere' / 'relics.json'

    result = run_cli(tmp_path, '--out', str(target), '--offline')

    assert result.returncode == 0, result.stderr
    assert read_json(target)['count'] == 5


def test_cli_no_static_copy_flag(tmp_path):
    data, static = seed_cli(tmp_path)

    result = run_cli(tmp_path, '--once', '--offline', '--no-static-copy')

    assert result.returncode == 0, result.stderr
    assert (data / 'relics_panel.json').exists()
    assert not (static / 'relics_panel.json').exists()


def test_cli_json_keeps_stdout_parseable(tmp_path):
    seed_cli(tmp_path)

    result = run_cli(tmp_path, '--json', '--offline')

    assert result.returncode == 0, result.stderr
    doc = json.loads(result.stdout)
    assert doc['count'] == 5
    assert SUMMARY_LINE in result.stderr             # the summary line moved off stdout


def test_cli_missing_relic_table_is_honest_and_writes_nothing(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    (tmp_path / 'static').mkdir()

    result = run_cli(tmp_path, '--once', '--offline')

    assert result.returncode == 1
    assert result.stdout.startswith('relics_panel: no relic table')
    assert 'obtain_index.py' in result.stdout
    assert not (data / 'relics_panel.json').exists()
    assert list(tmp_path.rglob('relics_panel.json')) == []


def test_static_copy_lives_next_to_the_other_page_data(panel):
    assert panel.static_copy_path() == os.path.join(panel.STATIC, 'relics_panel.json')
