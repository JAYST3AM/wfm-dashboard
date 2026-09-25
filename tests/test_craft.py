"""scripts/craft.py: slug conversion, the build-vs-buy maths and the data/craft.json contract.

craft.py keeps DATA at module level, so main() runs with module.DATA monkeypatched to tmp_path and
the WFCD recipe fetch replaced by a fixture payload - the suite never touches the network.
"""
import json
from types import SimpleNamespace

import pytest

from conftest import load_script, read_json, write_json

# a miniature market catalog: prime parts, blueprints, sets + one resource that IS catalogued
CATALOG = {'data': [
    {'id': 'id-set', 'slug': 'widget_prime_set', 'gameRef': '/Lotus/Weapons/WidgetPrime',
     'tags': ['prime', 'set'], 'i18n': {'en': {'name': 'Widget Prime Set'}}},
    {'id': 'id-bp', 'slug': 'widget_prime_blueprint',
     'gameRef': '/Lotus/Types/Recipes/Weapons/WidgetPrimeBlueprint', 'tags': ['prime', 'blueprint'],
     'i18n': {'en': {'name': 'Widget Prime Blueprint'}}},
    {'id': 'id-barrel', 'slug': 'widget_prime_barrel',
     'gameRef': '/Lotus/Types/Recipes/Weapons/WeaponParts/WidgetPrimeBarrel',
     'tags': ['prime', 'component'], 'i18n': {'en': {'name': 'Widget Prime Barrel'}}},
    {'id': 'id-handle', 'slug': 'widget_prime_handle',
     'gameRef': '/Lotus/Types/Recipes/Weapons/WeaponParts/WidgetPrimeHandle',
     'tags': ['prime', 'component'], 'i18n': {'en': {'name': 'Widget Prime Handle'}}},
    {'id': 'id-gizmo-set', 'slug': 'gizmo_prime_set', 'gameRef': '/Lotus/Powersuits/GizmoPrime',
     'tags': ['prime', 'set'], 'i18n': {'en': {'name': 'Gizmo Prime Set'}}},
    {'id': 'id-gizmo-bp', 'slug': 'gizmo_prime_blueprint',
     'gameRef': '/Lotus/Types/Recipes/WarframeRecipes/GizmoPrimeBlueprint',
     'tags': ['prime', 'blueprint'], 'i18n': {'en': {'name': 'Gizmo Prime Blueprint'}}},
    {'id': 'id-gizmo-neuro', 'slug': 'gizmo_prime_neuroptics_blueprint',
     'gameRef': '/Lotus/Types/Recipes/WarframeRecipes/GizmoPrimeHelmetBlueprint',
     'tags': ['prime', 'blueprint'], 'i18n': {'en': {'name': 'Gizmo Prime Neuroptics Blueprint'}}},
    {'id': 'id-gizmo-chassis', 'slug': 'gizmo_prime_chassis_blueprint',
     'gameRef': '/Lotus/Types/Recipes/WarframeRecipes/GizmoPrimeChassisBlueprint',
     'tags': ['prime', 'blueprint'], 'i18n': {'en': {'name': 'Gizmo Prime Chassis Blueprint'}}},
    {'id': 'id-oddball', 'slug': 'prime_bow_lower_limb',
     'gameRef': '/Lotus/Types/Recipes/Weapons/WeaponParts/BowLowerLimbGeneric',
     'tags': ['prime', 'component'], 'i18n': {'en': {'name': 'Prime Bow Lower Limb'}}},
    {'id': 'id-doohickey-set', 'slug': 'doohickey_set', 'gameRef': '/Lotus/Weapons/Doohickey',
     'tags': ['prime', 'set'], 'i18n': {'en': {'name': 'Doohickey Set'}}},
    {'id': 'id-doohickey-bp', 'slug': 'doohickey_blueprint',
     'gameRef': '/Lotus/Types/Recipes/Weapons/DoohickeyBlueprint', 'tags': ['prime', 'blueprint'],
     'i18n': {'en': {'name': 'Doohickey Blueprint'}}},
    {'id': 'id-cell', 'slug': 'orokin_cell', 'tags': ['resource'],
     'i18n': {'en': {'name': 'Orokin Cell'}}},
]}

RECIPES = {
    '/Lotus/Types/Recipes/Weapons/WidgetPrimeBlueprint': {
        'resultType': '/Lotus/Weapons/WidgetPrime', 'num': 1, 'tradable': True, 'ingredients': [
            {'ItemType': '/Lotus/Types/Recipes/Weapons/WeaponParts/WidgetPrimeBarrel', 'ItemCount': 1},
            {'ItemType': '/Lotus/Types/Recipes/Weapons/WeaponParts/WidgetPrimeHandle', 'ItemCount': 2},
            {'ItemType': '/Lotus/Types/Items/MiscItems/OrokinCell', 'ItemCount': 10}]},
    '/Lotus/Types/Recipes/WarframeRecipes/GizmoPrimeBlueprint': {
        'resultType': '/Lotus/Powersuits/GizmoPrime', 'num': 1, 'tradable': True, 'ingredients': [
            {'ItemType': '/Lotus/Types/Recipes/WarframeRecipes/GizmoPrimeHelmetComponent', 'ItemCount': 1},
            {'ItemType': '/Lotus/Types/Recipes/WarframeRecipes/GizmoPrimeChassisComponent', 'ItemCount': 1},
            {'ItemType': '/Lotus/Types/Items/MiscItems/Plastids', 'ItemCount': 500}]},
    # component recipe: Rubedo only, so its row can never be priced
    '/Lotus/Types/Recipes/WarframeRecipes/GizmoPrimeChassisBlueprint': {
        'resultType': '/Lotus/Types/Recipes/WarframeRecipes/GizmoPrimeChassisComponent', 'num': 1,
        'tradable': True, 'ingredients': [
            {'ItemType': '/Lotus/Types/Items/MiscItems/Rubedo', 'ItemCount': 400}]},
    '/Lotus/Types/Recipes/WarframeRecipes/GizmoPrimeHelmetBlueprint': {
        'resultType': '/Lotus/Types/Recipes/WarframeRecipes/GizmoPrimeHelmetComponent', 'num': 1,
        'tradable': True, 'ingredients': [
            {'ItemType': '/Lotus/Types/Items/MiscItems/Rubedo', 'ItemCount': 750}]},
    # a part the catalog only knows by a generic Lotus tail (name-derived slug has to resolve it)
    '/Lotus/Types/Recipes/Weapons/DoohickeyBlueprint': {
        'resultType': '/Lotus/Weapons/Doohickey', 'num': 1, 'tradable': True, 'ingredients': [
            {'ItemType': '/Lotus/Types/Recipes/Weapons/WeaponParts/PrimeBowLowerLimb', 'ItemCount': 1}]},
    # nothing owned anywhere in here: must never surface
    '/Lotus/Types/Recipes/Weapons/UntouchedBlueprint': {
        'resultType': '/Lotus/Weapons/Untouched', 'num': 1, 'tradable': True, 'ingredients': [
            {'ItemType': '/Lotus/Types/Items/MiscItems/Ferrite', 'ItemCount': 100}]},
}

OWNED = [
    {'slug': 'widget_prime_blueprint', 'name': 'Widget Prime Blueprint', 'count': 1,
     'path': '/Lotus/Types/Recipes/Weapons/WidgetPrimeBlueprint'},
    {'slug': 'widget_prime_barrel', 'name': 'Widget Prime Barrel', 'count': 1,
     'path': '/Lotus/Types/Recipes/Weapons/WeaponParts/WidgetPrimeBarrel'},
    {'slug': 'gizmo_prime_blueprint', 'name': 'Gizmo Prime Blueprint', 'count': 1,
     'path': '/Lotus/Types/Recipes/WarframeRecipes/GizmoPrimeBlueprint'},
    {'slug': 'gizmo_prime_chassis_blueprint', 'name': 'Gizmo Prime Chassis Blueprint', 'count': 1,
     'path': '/Lotus/Types/Recipes/WarframeRecipes/GizmoPrimeChassisBlueprint'},
    {'slug': 'doohickey_blueprint', 'name': 'Doohickey Blueprint', 'count': 1,
     'path': '/Lotus/Types/Recipes/Weapons/DoohickeyBlueprint'},
]

# prices.json only knows what the account owns (that is how fetch_prices.py builds it)
PRICES = {'widget_prime_barrel': {'wts': 4, 'wtb': 2, 'n_sell': 12},
          'gizmo_prime_chassis_blueprint': {'wts': 7},
          'gizmo_prime_blueprint': {'wts': 2}}
# results the account does not hold, so craft.py has to fetch them live (that is what /top is for)
LIVE = {'widget_prime_set': 40.0, 'widget_prime_handle': 51.0, 'gizmo_prime_set': 25.0,
        'gizmo_prime_neuroptics_blueprint': 3.0, 'doohickey_set': 9.0, 'prime_bow_lower_limb': 4.0}


@pytest.fixture
def craft(monkeypatch):
    return load_script('craft', monkeypatch=monkeypatch)


@pytest.fixture
def craft_fetch(monkeypatch, craft):
    """Recipe payload as it would come off the wire, no network involved."""
    calls = []

    def fake_fetch(url, tries=3):
        calls.append(url)
        return json.dumps(RECIPES).encode('utf-8'), None

    monkeypatch.setattr(craft, 'fetch_bytes', fake_fetch)
    return SimpleNamespace(mod=craft, calls=calls)


@pytest.fixture
def craft_run(monkeypatch, tmp_path, data_dir, craft_fetch):
    """main() against tmp data/ with prices.json only (no live prices at all)."""
    mod = craft_fetch.mod
    monkeypatch.setattr(mod, 'DATA', str(data_dir))
    write_json(data_dir / 'wfm_items_v2.json', CATALOG)
    write_json(data_dir / 'owned.json', OWNED)
    write_json(data_dir / 'prices.json', PRICES)
    monkeypatch.setattr(mod, 'fetch_top_floor',
                        lambda item_id: (None, 'no live pricing in this test'))
    assert mod.main([]) == 0
    return SimpleNamespace(doc=read_json(data_dir / 'craft.json'), mod=mod, data_dir=data_dir,
                           cache=read_json(data_dir / 'recipes_cache.json'))


@pytest.fixture
def craft_live(monkeypatch, tmp_path, data_dir, craft_fetch):
    mod = craft_fetch.mod
    monkeypatch.setattr(mod, 'DATA', str(data_dir))
    write_json(data_dir / 'wfm_items_v2.json', CATALOG)
    write_json(data_dir / 'owned.json', OWNED)
    write_json(data_dir / 'prices.json', PRICES)
    # the live /top stub answers by catalog id -> floor, mirroring the real endpoint's shape
    ids = {i['id']: i['slug'] for i in CATALOG['data']}
    monkeypatch.setattr(mod, 'fetch_top_floor',
                        lambda item_id: (LIVE.get(ids.get(item_id)), None))
    assert mod.main(['--live', '--sleep', '0']) == 0
    return SimpleNamespace(doc=read_json(data_dir / 'craft.json'), mod=mod, data_dir=data_dir,
                           ids=ids)


# ------------------------------------------------------------------ pure helpers

def test_slugify_matches_wfm_slug_form(craft):
    assert craft.slugify('Orokin Cell') == 'orokin_cell'
    assert craft.slugify('MK1-Braton') == 'mk1_braton'
    assert craft.slugify('Cobra & Crane Prime') == 'cobra_crane_prime'   # '&' collapses, not 'and'
    assert craft.slugify('  ') == '' and craft.slugify(None) == ''


def test_name_from_path_splits_camel_case(craft):
    assert craft.name_from_path('/Lotus/Types/Recipes/Weapons/WeaponParts/BurstonPrimeStock') \
        == 'Burston Prime Stock'
    assert craft.name_from_path('/Lotus/Types/Recipes/Weapons/WeaponParts/PrimeBowLowerLimb') \
        == 'Prime Bow Lower Limb'
    assert craft.name_from_path('MK1Braton') == 'MK1 Braton'
    assert craft.name_from_path('/Lotus/Types/Items/MiscItems/Orokin_Cell') == 'Orokin Cell'


def test_part_slug_prefers_paths_then_names(craft):
    index = craft.build_indexes(CATALOG['data'], OWNED)
    recipes, _ = craft.normalize_recipes(RECIPES)
    res2slug = craft.result2slug_index(recipes, index)

    # catalog gameRef, then component recipe key, then a name-derived slug, then nothing
    assert craft.part_slug('/Lotus/Types/Recipes/Weapons/WeaponParts/WidgetPrimeBarrel',
                           index, res2slug) == 'widget_prime_barrel'
    assert craft.part_slug('/Lotus/Types/Recipes/WarframeRecipes/GizmoPrimeHelmetComponent',
                           index, res2slug) == 'gizmo_prime_neuroptics_blueprint'
    assert craft.part_slug('/Lotus/Types/Recipes/Weapons/WeaponParts/PrimeBowLowerLimb',
                           index, res2slug) == 'prime_bow_lower_limb'
    assert craft.part_slug('/Lotus/Types/Items/MiscItems/Ferrite', index, res2slug) is None


def test_is_market_part_rejects_catalogued_resources(craft):
    index = craft.build_indexes(CATALOG['data'], OWNED)
    assert craft.is_market_part('widget_prime_barrel', index) is True
    assert craft.is_market_part('orokin_cell', index) is False        # tagged 'resource'
    assert craft.is_market_part('never_heard_of_it', index) is True   # unknown slugs stay candidates


def test_result2slug_only_maps_consumed_component_paths(craft):
    index = craft.build_indexes(CATALOG['data'], OWNED)
    recipes, _ = craft.normalize_recipes(RECIPES)
    res2slug = craft.result2slug_index(recipes, index)

    assert res2slug['/Lotus/Types/Recipes/WarframeRecipes/GizmoPrimeHelmetComponent'] \
        == 'gizmo_prime_neuroptics_blueprint'
    # the assembled weapon path is nobody's ingredient, so it must not map back to its own blueprint
    assert '/Lotus/Weapons/WidgetPrime' not in res2slug
    assert '/Lotus/Weapons/Doohickey' not in res2slug


def test_normalize_recipes_export_and_items_shapes(craft):
    recipes, dropped = craft.normalize_recipes(RECIPES)
    assert dropped == 0 and len(recipes) == len(RECIPES)
    assert recipes['/Lotus/Types/Recipes/Weapons/WidgetPrimeBlueprint']['result'] \
        == '/Lotus/Weapons/WidgetPrime'
    assert ['/Lotus/Types/Recipes/Weapons/WeaponParts/WidgetPrimeHandle', 2] in \
        recipes['/Lotus/Types/Recipes/Weapons/WidgetPrimeBlueprint']['ingredients']

    items_style, dropped = craft.normalize_recipes([
        {'uniqueName': '/Lotus/W/A', 'components': [{'uniqueName': '/Lotus/I/B', 'itemCount': 3}]},
        {'uniqueName': '/Lotus/W/Empty', 'components': []},          # dropped: nothing to build from
        'not a dict'])
    assert dropped == 2 and items_style == {'/Lotus/W/A': {
        'result': '/Lotus/W/A', 'num': 1, 'tradable': False, 'ingredients': [['/Lotus/I/B', 3]]}}


def test_missing_units_is_count_aware(craft):
    assert craft.missing_units({'a': 2, 'b': 1}, {'a': 1, 'b': 1}) == {'a': 1}
    assert craft.missing_units({'a': 2}, {'a': 5}) == {}
    assert craft.missing_units({'a': 1}, {}) == {'a': 1}


def test_floor_of_reads_wts_and_tolerates_junk(craft):
    assert craft.floor_of({'wts': 7, 'wtb': 3}) == 7.0
    assert craft.floor_of({'wts': None}) is None and craft.floor_of(None) is None
    assert craft.floor_of({}) is None


# ------------------------------------------------------------------ the maths

@pytest.fixture
def fixture_states(craft):
    """The in-script selftest fixtures: rows keyed by result_slug."""
    f = craft._fixture_run()
    return SimpleNamespace(by=f['by'], rows=f['rows'], skipped=f['skipped'], ignored=f['ignored'],
                           detail=f['detail'], index=f['index'], recipes=f['recipes'],
                           res2slug=f['res2slug'], owned=f['owned_counts'], mod=craft)


def test_buy_when_parts_cost_more_than_the_assembled(fixture_states):
    row = fixture_states.by['widget_prime_set']
    assert row['verdict'] == 'BUY'
    assert (row['built_floor'], row['buy_cost'], row['profit']) == (40.0, 50.0, -10.0)
    assert row['missing_parts'] == [{'slug': 'widget_prime_handle', 'floor': 50.0}]
    assert row['owned_parts'] == ['widget_prime_barrel']


def test_craft_when_the_assembled_costs_more(fixture_states):
    row = fixture_states.by['gizmo_prime_set']
    assert row['verdict'] == 'CRAFT' and row['profit'] == 22.0
    # the in-game 'Helmet' component is bought as the market's neuroptics blueprint
    assert row['missing_parts'] == [{'slug': 'gizmo_prime_neuroptics_blueprint', 'floor': 3.0}]
    assert row['owned_parts'] == ['gizmo_prime_chassis_blueprint']


def test_skip_paths_are_documented(fixture_states):
    reasons = {s['result_slug']: s['reason'] for s in fixture_states.skipped}
    assert set(reasons) >= {'thingamajig_set', 'whatsit_set', 'gizmo_prime_chassis_blueprint',
                            'ghosted_blueprint'}
    assert all(reasons.values())                       # never a bare SKIP without a reason


def test_skip_when_the_assembled_result_has_no_price(fixture_states):
    row = fixture_states.by['thingamajig_set']
    assert row['verdict'] == 'SKIP' and row['built_floor'] is None and row['profit'] is None
    assert row['buy_cost'] == 9.0                            # what the parts would cost, reported anyway
    reason = {s['result_slug']: s['reason'] for s in fixture_states.skipped}['thingamajig_set']
    assert reason.startswith('no price for the assembled')


def test_skip_when_a_missing_part_has_no_price(fixture_states):
    row = fixture_states.by['whatsit_set']
    assert row['verdict'] == 'SKIP' and row['profit'] is None
    assert row['missing_parts'] == [{'slug': 'whatsit_stock', 'floor': None}]
    assert row['owned_parts'] == ['whatsit_barrel']
    skipped = {s['result_slug']: s for s in fixture_states.skipped}['whatsit_set']
    assert skipped['unpriced'] == ['whatsit_stock']


def test_resource_only_recipe_skips_with_a_note(fixture_states):
    row = fixture_states.by['gizmo_prime_chassis_blueprint']
    assert row['verdict'] == 'SKIP' and row['missing_parts'] == [] and row['buy_cost'] == 0.0
    reason = {s['result_slug']: s['reason'] for s in fixture_states.skipped}
    assert reason['gizmo_prime_chassis_blueprint'].startswith('resource-only')
    assert fixture_states.ignored.get('Rubedo') == 1         # ...and the resource is still counted


def test_resource_ingredients_are_never_priced(fixture_states):
    assert fixture_states.ignored.get('Orokin Cell') == 2 and fixture_states.ignored.get('Plastids') == 2
    assert fixture_states.ignored.get('Alloy Plate') == 1
    assert 'orokin_cell' not in {p['slug'] for r in fixture_states.rows for p in r['missing_parts']}


def test_unowned_recipes_never_surface(fixture_states):
    assert not any('Untouched' in d['key'] for d in fixture_states.detail.values())
    assert not any('Untouched' in s['recipe'] for s in fixture_states.skipped)


def test_a_component_alone_triggers_a_row(fixture_states):
    row = fixture_states.by['whatchamacallit_set']
    assert row['verdict'] == 'CRAFT' and row['missing_parts'] == []
    assert row['owned_parts'] == ['whatchamacallit_barrel'] and row['profit'] == 12.0


def test_part_needed_twice_is_charged_twice(craft):
    f = craft._fixture_run()
    owned = {k: v for k, v in f['owned_counts'].items() if k != 'widget_prime_set'}
    rows = {r['result_slug']: r for r in craft.analyse(
        f['recipes'], f['index'], f['res2slug'], owned, craft.FLOORS)[0]}
    row = rows['gadget_prime_set']                                 # recipe eats 2x Widget Prime
    assert row['buy_cost'] == 80.0 and row['profit'] == -65.0
    assert row['missing_parts'] == [{'slug': 'widget_prime_set', 'floor': 40.0}]


def test_price_targets_cover_missing_parts_and_results(fixture_states):
    targets = fixture_states.mod.price_targets(fixture_states.recipes, fixture_states.index,
                                               fixture_states.res2slug, fixture_states.owned,
                                               fixture_states.mod.FLOORS)
    assert targets == ['thingamajig_set', 'whatsit_stock']


def test_self_check_flags_a_tampered_row(fixture_states):
    rows = [dict(r) for r in fixture_states.rows]
    rows[0] = dict(rows[0], buy_cost=rows[0]['buy_cost'] + 1)
    summary = dict(craft=1, buy=1, skip=len(rows) - 2, total=len(rows))
    assert fixture_states.mod.self_check(rows, [], summary,
                                         fixture_states.detail)['buy_cost_matches_parts'] is False


# ------------------------------------------------------------------ live pricing plumbing

def test_live_floors_reuses_cache_and_caps_calls(craft):
    calls = []
    craft.fetch_top_floor = lambda item_id: (calls.append(item_id), (99, None))[1]
    out, stats = craft.live_floors(['a', 'b'], {'b': {'id': 'id-b'}},
                                   cached={'a': {'wts': 5, 'at': 'then'}}, max_calls=1, sleep=0,
                                   log=lambda *a: None)
    assert out == {'a': 5.0, 'b': 99.0} and stats['cache_hits'] == 1 and stats['calls'] == 1
    assert calls == ['id-b'] and stats['known'] == 2


def test_fetch_top_floor_reads_the_lowest_visible_sell(craft, monkeypatch):
    payload = {'data': {'sell': [{'platinum': 9, 'visible': True}, {'platinum': 4, 'visible': True},
                                 {'platinum': 1, 'visible': False}], 'buy': [{'platinum': 20}]}}
    monkeypatch.setattr(craft, 'fetch_bytes',
                        lambda url, tries=3: (json.dumps(payload).encode(), None))
    assert craft.fetch_top_floor('abc') == (4, None)
    monkeypatch.setattr(craft, 'fetch_bytes', lambda url, tries=3: (json.dumps({'data': {'sell': []}}).encode(), None))
    assert craft.fetch_top_floor('abc') == (None, 'no visible sellers')
    monkeypatch.setattr(craft, 'fetch_bytes', lambda url, tries=3: (None, 'http 404'))
    assert craft.fetch_top_floor('abc') == (None, 'http 404')


# ------------------------------------------------------------------ recipes cache + failsafes

def test_main_writes_the_recipe_cache_and_the_row_contract(craft_run):
    doc, cache = craft_run.doc, craft_run.cache
    assert cache['count'] == len(RECIPES) and cache['source_url'] == craft_run.mod.RECIPE_URLS[0]
    assert cache['fetched_utc'].endswith(' UTC') and 'recipes' in cache

    assert set(doc) == {'generated', 'source', 'params', 'assumptions', 'summary', 'self_check',
                        'skipped', 'ignored_ingredients', 'live_prices', 'rows'}
    assert doc['generated'].endswith(' UTC') and doc['source'].startswith('WFCD recipes')
    assert doc['params']['recipe_urls'] == list(craft_run.mod.RECIPE_URLS)
    assert len(doc['assumptions']) >= 5
    row = doc['rows'][0]
    assert set(row) == {'result_name', 'result_slug', 'built_floor', 'buy_cost', 'profit',
                        'missing_parts', 'owned_parts', 'verdict'}
    assert set(doc['summary']) >= {'craft', 'buy', 'skip', 'total', 'note'}
    assert doc['summary']['note'].startswith('%d rows' % doc['summary']['total'])


def test_offline_run_skips_unpriced_rows_and_says_so(craft_run):
    # prices.json knows only what the account owns, so the assembled floors are missing here
    rows = {r['result_slug']: r for r in craft_run.doc['rows']}
    assert rows['widget_prime_set']['verdict'] == 'SKIP'
    assert rows['widget_prime_set']['built_floor'] is None
    assert rows['widget_prime_set']['buy_cost'] == 0.0            # handle only, and nothing prices it
    assert craft_run.doc['summary']['prices'].startswith('off (no live prices cached')
    assert all(r['verdict'] == 'SKIP' for r in craft_run.doc['rows'])


def test_live_run_prices_parts_and_results(craft_live):
    doc = craft_live.doc
    rows = {r['result_slug']: r for r in doc['rows']}
    assert doc['summary']['craft'] == 2 and doc['summary']['buy'] == 1 and doc['summary']['skip'] == 1

    buy = rows['widget_prime_set']                    # 40p assembled vs 2x51p of handles
    assert buy['verdict'] == 'BUY' and buy['buy_cost'] == 102.0 and buy['profit'] == -62.0
    assert buy['missing_parts'] == [{'slug': 'widget_prime_handle', 'floor': 51.0}]

    craft_row = rows['doohickey_set']                  # 9p assembled vs 4p part
    assert craft_row['verdict'] == 'CRAFT' and craft_row['profit'] == 5.0
    assert craft_row['missing_parts'] == [{'slug': 'prime_bow_lower_limb', 'floor': 4.0}]

    assert rows['gizmo_prime_chassis_blueprint']['verdict'] == 'SKIP'   # resource-only
    assert all(doc['self_check'].values()), doc['self_check']
    assert set(doc['live_prices']) == {'widget_prime_set', 'widget_prime_handle', 'gizmo_prime_set',
                                       'gizmo_prime_neuroptics_blueprint', 'doohickey_set',
                                       'prime_bow_lower_limb'}
    assert doc['summary']['prices'].startswith('/top:')


def test_second_run_reuses_cached_live_prices_without_a_call(monkeypatch, craft_live, data_dir):
    mod, calls = craft_live.mod, []
    monkeypatch.setattr(mod, 'fetch_top_floor', lambda item_id: (calls.append(item_id), (None, 'x'))[1])
    assert mod.main(['--live', '--sleep', '0']) == 0
    assert calls == []                                  # everything came out of craft.json
    doc = read_json(data_dir / 'craft.json')
    assert doc['summary']['prices'].startswith('/top:') and doc['summary']['craft'] == 2


def test_refresh_live_refetches(monkeypatch, craft_live, data_dir):
    mod, calls = craft_live.mod, []
    ids, by_slug = craft_live.ids, {v: k for k, v in craft_live.ids.items()}
    monkeypatch.setattr(mod, 'fetch_top_floor',
                        lambda item_id: (calls.append(item_id), (LIVE.get(ids.get(item_id)), None))[1])
    assert mod.main(['--live', '--refresh-live', '--sleep', '0']) == 0
    assert sorted(calls) == sorted(by_slug[s] for s in LIVE)  # every target re-fetched, cache ignored
    assert len(calls) == 6


def test_prices_json_beats_the_live_cache(craft_live, data_dir):
    doc = read_json(data_dir / 'craft.json')
    doc['live_prices']['gizmo_prime_chassis_blueprint'] = {'wts': 999, 'at': 'then'}
    write_json(data_dir / 'craft.json', doc)
    assert craft_live.mod.main(['--sleep', '0']) == 0
    fresh = read_json(data_dir / 'craft.json')
    row = {r['result_slug']: r for r in fresh['rows']}['gizmo_prime_set']
    assert row['buy_cost'] == 3.0                      # 7p from prices.json, never the 999p cache


def test_missing_recipes_and_a_dead_source_write_nothing(monkeypatch, craft, tmp_path, data_dir):
    monkeypatch.setattr(craft, 'DATA', str(data_dir))
    write_json(data_dir / 'wfm_items_v2.json', CATALOG)
    write_json(data_dir / 'owned.json', OWNED)
    monkeypatch.setattr(craft, 'fetch_bytes', lambda url, tries=3: (None, 'http 404'))
    assert craft.main([]) == 0
    assert not (data_dir / 'craft.json').exists()
    assert not (data_dir / 'recipes_cache.json').exists()
    assert not [p for p in data_dir.iterdir() if p.name.endswith('.tmp')]


def test_missing_owned_data_exits_cleanly(monkeypatch, craft, capsys, data_dir):
    monkeypatch.setattr(craft, 'DATA', str(data_dir))
    assert craft.main([]) == 0
    assert 'wfm_items_v2.json and data/owned.json are required' in capsys.readouterr().out
    assert not (data_dir / 'craft.json').exists()


def test_offline_flag_never_fetches(monkeypatch, craft, capsys, data_dir):
    hits = []
    monkeypatch.setattr(craft, 'DATA', str(data_dir))
    monkeypatch.setattr(craft, 'fetch_bytes', lambda url, tries=3: (hits.append(url), (None, 'x'))[1])
    write_json(data_dir / 'wfm_items_v2.json', CATALOG)
    write_json(data_dir / 'owned.json', OWNED)
    assert craft.main(['--offline']) == 0
    assert hits == [] and 'no crafting recipes available' in capsys.readouterr().out


def test_main_returns_zero_on_selftest_and_writes_nothing(monkeypatch, craft, capsys, data_dir):
    monkeypatch.setattr(craft, 'DATA', str(data_dir))
    assert craft.main(['--selftest']) == 0
    out = capsys.readouterr().out
    assert 'selftest OK' in out and 'FAIL' not in out
    assert not (data_dir / 'craft.json').exists()
