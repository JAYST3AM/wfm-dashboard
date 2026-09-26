"""scripts/collection_log.py: category mapping, the collected union and the log contract.

Offline by construction: DATA/STATIC/AF are redirected into tmp_path, the catalog comes from a
fixture data/wfcd_items_cache.json (fresh) or a stale one plus --offline, and the "save" is a
plaintext lastData.dec.json - which is also the decryptor's documented plaintext branch, so the
real read path is exercised without the encryption key or the AlecaFrame install.

Expected fixture numbers (8 obtainable rows):
  warframes 2 (Ash mastered / Nezha missing)   primary 2 (Braton mastered / Braton Prime owned)
  melee 1 (Ack & Brunt missing, 12p blueprint) kdrives 1 (Bad Baby missing)
  amps 1 (Mote Prism mastered via XPInfo)      other 1 (Voidrig, Necramech)
  -> overall 4/8 = 50.0%, mastered_only 3, owned_only 1, missing 4, missing_with_price 1
"""
import json
import os
import time

import pytest

from conftest import load_script, read_json, write_json

WFCD_ITEMS = [
    {'name': 'Ash', 'unique_name': '/Lotus/Powersuits/Ninja/Ninja', 'type': 'Warframe',
     'product_category': 'Suits', 'masterable': True, 'mastery_req': 0, 'image_name': 'Ash.png',
     'src': 'Warframes'},
    {'name': 'Nezha', 'unique_name': '/Lotus/Powersuits/Odalisk/Odalisk', 'type': 'Warframe',
     'product_category': 'Suits', 'masterable': True, 'mastery_req': 0, 'image_name': 'Nezha.png',
     'src': 'Warframes'},
    {'name': 'Voidrig', 'unique_name': '/Lotus/Powersuits/EntratiMech/NechroTech',
     'type': 'Warframe', 'product_category': 'MechSuits', 'masterable': True, 'mastery_req': 0,
     'image_name': 'NechroMech.png', 'src': 'Warframes'},
    {'name': 'Helminth', 'unique_name': '/Lotus/Powersuits/Helminth/Helminth', 'type': 'Warframe',
     'product_category': 'Suits', 'masterable': False, 'mastery_req': 0, 'image_name': None,
     'src': 'Warframes'},
    {'name': 'Braton', 'unique_name': '/Lotus/Weapons/Tenno/Rifle/Braton', 'type': 'Rifle',
     'product_category': 'LongGuns', 'masterable': True, 'mastery_req': 0,
     'image_name': 'Braton.png', 'src': 'Primary'},
    {'name': 'Braton Prime', 'unique_name': '/Lotus/Weapons/Tenno/Rifle/BratonPrime',
     'type': 'Rifle', 'product_category': 'LongGuns', 'masterable': True, 'mastery_req': 8,
     'image_name': 'BratonPrime.png', 'src': 'Primary'},
    {'name': 'Ack & Brunt', 'unique_name': '/Lotus/Weapons/Grineer/Melee/RegorAxeShield',
     'type': 'Melee', 'product_category': 'Melee', 'masterable': True, 'mastery_req': 3,
     'image_name': 'RegorAxeShield.png', 'src': 'Melee'},
    {'name': 'Bad Baby', 'unique_name': '/Lotus/Types/Vehicles/Hoverboard/Deck/HoverboardDeckA',
     'type': 'K-Drive Component', 'product_category': 'Pistols', 'masterable': True,
     'mastery_req': 0, 'image_name': None, 'src': 'Misc'},
    {'name': 'Mote Prism', 'unique_name': '/Lotus/Weapons/Operator/Amps/MotePrism',
     'type': 'Amp', 'product_category': 'Pistols', 'masterable': False, 'mastery_req': 0,
     'image_name': 'MotePrism.png', 'src': 'Misc'},
]
SAVE = {'PlayerLevel': 30, 'PremiumCredits': 500, 'XPInfo': [
    {'ItemType': '/Lotus/Powersuits/Ninja/Ninja', 'XP': 14116270},
    {'ItemType': '/Lotus/Weapons/Tenno/Rifle/Braton', 'XP': 900000},
    {'ItemType': '/Lotus/Weapons/Operator/Amps/MotePrism', 'XP': 12000},
    {'ItemType': '/Lotus/Types/Game/CrewShip/RailJack/DefaultHarness', 'XP': 828583},
]}
OWNED = [{'slug': 'braton_prime', 'name': 'Braton Prime', 'count': 2, 'section': 'LongGuns',
          'path': '/Lotus/Weapons/Tenno/Rifle/BratonPrime', 'match': 'ref'},
         {'slug': 'braton_prime_receiver', 'name': 'Braton Prime Receiver', 'count': 1,
          'path': '/Lotus/Types/Recipes/Weapons/WeaponParts/BratonPrimeReceiver'}]
PRICES = {'ack_and_brunt_blueprint': {'wts': 12, 'wtb': None, 'n_sell': 4, 'n_buy': 0},
          'ash_set': {'wts': 40, 'wtb': None, 'n_sell': 3, 'n_buy': 1}}
MARKET_CATALOG = {'data': [
    {'id': 'x', 'slug': 'braton_prime', 'gameRef': '/Lotus/Weapons/Tenno/Rifle/BratonPrime',
     'tags': ['prime'], 'i18n': {'en': {'name': 'Braton Prime',
                                        'icon': 'items/images/en/braton_prime.png'}}},
    {'id': 'y', 'slug': 'bad_baby', 'gameRef': '/Lotus/Types/Vehicles/Hoverboard/Deck/HoverboardDeckA',
     'tags': ['kdrive'], 'i18n': {'en': {'name': 'Bad Baby',
                                         'icon': 'items/images/en/bad_baby.png'}}},
]}


def catalog_cache(fetched):
    return {'schema': 1, 'source': 'wfcd-json',
            'source_url': 'https://raw.githubusercontent.com/WFCD/warframe-items/master/data/json/',
            'files': ['Warframes', 'Primary', 'Melee', 'Misc'], 'urls': [], 'partial': False,
            'fetched': fetched, 'fetched_iso': '2026-09-25T00:00:00Z', 'count': len(WFCD_ITEMS),
            'items': WFCD_ITEMS}


@pytest.fixture
def log_mod(monkeypatch):
    return load_script('collection_log', monkeypatch=monkeypatch)


@pytest.fixture
def staged(tmp_path, monkeypatch, data_dir, log_mod):
    """A throwaway data/ + static/ + AlecaFrame dir with every fixture in place."""
    static = tmp_path / 'static'
    static.mkdir()
    af = tmp_path / 'aleaframe'
    af.mkdir()
    monkeypatch.setattr(log_mod, 'DATA', str(data_dir))
    monkeypatch.setattr(log_mod, 'STATIC', str(static))
    monkeypatch.setattr(log_mod, 'AF', str(af))
    write_json(data_dir / 'lastData.dec.json', SAVE)
    write_json(data_dir / 'owned.json', OWNED)
    write_json(data_dir / 'prices.json', PRICES)
    write_json(data_dir / 'wfm_items_v2.json', MARKET_CATALOG)
    write_json(data_dir / 'wfcd_items_cache.json', catalog_cache(int(time.time())))
    return {'data': data_dir, 'static': static, 'af': af, 'mod': log_mod}


def run(staged, argv=('--no-static-copy',)):
    assert staged['mod'].main(list(argv)) == 0
    return read_json(staged['data'] / 'collection_log.json')


def by_key(doc):
    return {c['key']: c for c in doc['categories']}


# ---------------------------------------------------------------- pure helpers
def test_categorize_table(log_mod):
    def cat(name, src, typ, pcat='Suits'):
        return log_mod.categorize({'name': name, 'src': src, 'type': typ,
                                   'product_category': pcat})
    assert cat('Ash', 'Warframes', 'Warframe') == 'warframes'
    assert cat('Voidrig', 'Warframes', 'Warframe', 'MechSuits') == 'other'
    assert cat('Braton', 'Primary', 'Rifle') == 'primary'
    assert cat('Ack & Brunt', 'Melee', 'Melee') == 'melee'
    assert cat('Carrier', 'Sentinels', 'Sentinel') == 'sentinels'
    assert cat('Deth Machine Rifle', 'SentinelWeapons', 'Companion Weapon') == 'sentinel_weapons'
    assert cat('Smeeta Kavat', 'Pets', 'Pets') == 'companions'
    assert cat('Itzal', 'Archwing', 'Archwing') == 'archwing'
    assert cat('Imperator', 'Arch-Gun', 'Arch-Gun') == 'archgun'
    assert cat('Veritux', 'Arch-Melee', 'Arch-Melee') == 'archmelee'
    assert cat('Bad Baby', 'Misc', 'K-Drive Component') == 'kdrives'
    assert cat('Mote Prism', 'Misc', 'Amp') == 'amps'
    assert cat('Catchmoon', 'Misc', 'Kitgun Component') == 'secondary'
    assert cat('Something', 'Unknown', 'Whatever') == 'other'


def test_obtainable_rule(log_mod):
    xp = {'/Lotus/Weapons/Operator/Amps/MotePrism'}
    assert log_mod.is_obtainable({'masterable': True, 'type': 'Warframe',
                                  'unique_name': '/x'}, set())
    assert log_mod.is_obtainable({'masterable': False, 'type': 'Amp', 'unique_name': '/x'}, set())
    assert log_mod.is_obtainable({'masterable': False, 'type': 'K-Drive Component',
                                  'unique_name': '/x'}, xp | {'/x'})
    assert not log_mod.is_obtainable({'masterable': False, 'type': 'Warframe',
                                      'unique_name': '/x'}, xp)


def test_slugify_and_floor(log_mod):
    assert log_mod.slugify('Braton Prime') == 'braton_prime'
    assert log_mod.slugify('Ack & Brunt') == 'ack_and_brunt'
    assert log_mod.slugify('MK1-Bo') == 'mk1_bo'
    assert log_mod.price_floor('Braton Prime', {}) == (None, None)
    assert log_mod.price_floor('Braton Prime', {'braton_prime': {'wts': 5}}) == (5, 'item')
    assert log_mod.price_floor('Ash', {'ash_set': {'wts': 40}}) == (40, 'set')
    assert log_mod.price_floor('Ack & Brunt', PRICES) == (12, 'blueprint')
    assert log_mod.price_floor('Ash', {'ash': {'wts': 0}, 'ash_set': {'wts': None}}) == (None, None)


def test_icon_urls(log_mod):
    entry = {'image_name': 'Ash.png', 'unique_name': '/x'}
    assert log_mod.icon_for(entry, {}) == 'https://cdn.warframestat.us/img/Ash.png'
    assert log_mod.icon_for({'image_name': None, 'unique_name': '/x'},
                            {'/x': 'items/images/en/x.png'}) == \
        'https://warframe.market/static/assets/items/images/en/x.png'
    assert log_mod.icon_for({'image_name': '../../etc/passwd', 'unique_name': '/x'}, {}) is None
    assert log_mod.icon_for({'image_name': None, 'unique_name': '/x'}, {}) is None


def test_xpinfo_names_tolerates_junk(log_mod):
    assert log_mod.xpinfo_names({'XPInfo': [{'ItemType': '/a'}, None, {'XP': 1}, 'x']}) == {'/a'}
    assert log_mod.xpinfo_names({}) == set()


# ---------------------------------------------------------------- the written log
def test_log_contract_and_counts(staged):
    doc = run(staged)
    assert set(doc) == {'version', 'generated', 'generated_iso', 'overall', 'categories',
                        'sources', 'notes', 'content_hash'}
    assert isinstance(doc['generated'], int) and doc['generated_iso'].endswith('Z')
    assert doc['overall'] == {'obtained': 4, 'total': 8, 'pct': 50.0, 'mastered_only': 3,
                              'owned_only': 1, 'missing': 4, 'missing_with_price': 1}
    cats = by_key(doc)
    assert sorted(cats) == ['amps', 'kdrives', 'melee', 'other', 'primary', 'warframes']
    assert [(c['obtained'], c['total']) for c in doc['categories']] == [(1, 2), (2, 2), (0, 1),
                                                                        (0, 1), (1, 1), (0, 1)]
    for cat in doc['categories']:
        assert cat['name'] and cat['total'] > 0
        assert cat['pct'] == round(100.0 * cat['obtained'] / cat['total'], 1)
        assert all(r['name'] and r['unique_name'] and r['slug'] for r in cat['items'])
        assert all(set(r) == {'name', 'slug', 'unique_name', 'icon', 'owned', 'mastered',
                              'floor', 'floor_kind', 'mastery_req', 'obtain'} for r in cat['items'])


def test_collected_union_and_flags(staged):
    cats = by_key(run(staged))
    ash = cats['warframes']['items'][0]
    assert (ash['name'], ash['mastered'], ash['owned']) == ('Ash', True, False)
    nezha = next(r for r in cats['warframes']['items'] if r['name'] == 'Nezha')
    assert (nezha['mastered'], nezha['owned'], nezha['floor']) == (False, False, None)
    braton_prime = next(r for r in cats['primary']['items'] if r['name'] == 'Braton Prime')
    assert (braton_prime['owned'], braton_prime['mastered']) == (True, False)   # inventory only
    assert braton_prime['mastery_req'] == 8
    mote = cats['amps']['items'][0]
    assert mote['mastered'] is True                 # non-masterable Amp, proven by XPInfo
    assert all(not (r['owned'] or r['mastered']) for r in cats['melee']['items'])


def test_missing_tradeable_carries_floor(staged):
    cats = by_key(run(staged))
    melee = cats['melee']['items'][0]
    assert (melee['name'], melee['floor'], melee['floor_kind']) == ('Ack & Brunt', 12, 'blueprint')
    assert all(r['floor'] is None for cat in ('warframes', 'primary', 'amps')
               for r in cats[cat]['items'] if r['owned'] or r['mastered'])


def test_helminth_excluded_and_helps_icons(staged):
    doc = run(staged)
    names = [r['name'] for c in doc['categories'] for r in c['items']]
    assert 'Helminth' not in names                       # masterable=False, not in XPInfo
    assert 'Voidrig' in names                            # Necramech -> other
    cats = by_key(doc)
    # Ack & Brunt / Mote Prism use their WFCD imageName; Bad Baby has none in the fixture, so it
    # falls back to the market CDN path from data/wfm_items_v2.json.
    assert cats['melee']['items'][0]['icon'] == 'https://cdn.warframestat.us/img/RegorAxeShield.png'
    assert cats['kdrives']['items'][0]['icon'] == \
        'https://warframe.market/static/assets/items/images/en/bad_baby.png'


def test_sources_and_notes(staged):
    doc = read_json(staged['data'] / 'wfcd_items_cache.json')
    log = run(staged)
    src = log['sources']
    assert src['catalog_source'] == 'wfcd-json'
    assert src['catalog_url'] == doc['source_url']
    assert src['catalog_count'] == log['overall']['total'] == 8
    assert src['catalog_rows_fetched'] == len(WFCD_ITEMS)
    assert src['save_xpinfo_count'] == 4              # the Railjack harness row counts in XPInfo
    assert src['save_source'] == 'cached'             # only lastData.dec.json exists in the fixture
    assert src['owned_rows'] == len(OWNED) and src['prices_quotes'] == len(PRICES)
    assert any('Collected = save XPInfo mastery UNION' in n for n in log['notes'])
    assert any('catalog from cache' in n for n in log['notes'])
    assert src['catalog_files'] == ['Warframes', 'Primary', 'Melee', 'Misc']


def test_live_save_preferred_over_cached(staged):
    """A live plaintext lastData.dat wins; the mastery count comes from that file."""
    live = staged['af'] / 'lastData.dat'
    with open(live, 'w', encoding='utf-8') as fh:
        json.dump({'XPInfo': [{'ItemType': '/Lotus/Weapons/Tenno/Rifle/Braton', 'XP': 1}]}, fh)
    doc = run(staged, argv=('--no-static-copy',))
    assert doc['sources']['save_source'] == 'live'
    assert doc['sources']['save_xpinfo_count'] == 1
    # Braton is on that mastery list and Braton Prime is still owned via owned.json
    assert doc['overall']['obtained'] == 2


def test_missing_save_still_writes_a_log(staged):
    os.remove(str(staged['data'] / 'lastData.dec.json'))
    doc = run(staged)
    assert doc['sources']['save_source'] is None and doc['sources']['save_xpinfo_count'] == 0
    assert doc['overall']['obtained'] == 1           # Braton Prime is still owned via owned.json
    assert any(n.startswith('save note:') for n in doc['notes'])


def test_stale_cache_is_used_offline(staged):
    write_json(staged['data'] / 'wfcd_items_cache.json', catalog_cache(0))
    doc = run(staged, argv=('--offline', '--no-static-copy'))
    assert doc['overall']['total'] == 8
    assert doc['sources']['catalog_from_cache'] is True
    assert any('catalog from cache' in n for n in doc['notes'])


def test_no_catalog_exits_nonzero(staged, capsys):
    os.remove(str(staged['data'] / 'wfcd_items_cache.json'))
    assert staged['mod'].main(['--offline', '--no-static-copy']) == 1
    assert 'ERROR no catalog available' in capsys.readouterr().out
    assert not os.path.exists(str(staged['data'] / 'collection_log.json'))


def test_static_copy_written_unless_disabled(staged):
    run(staged, argv=())                                    # default: keep the static copy
    assert os.path.exists(str(staged['static'] / 'collection_log.json'))
    assert read_json(staged['static'] / 'collection_log.json')['overall']['total'] == 8
    os.remove(str(staged['static'] / 'collection_log.json'))
    run(staged, argv=('--no-static-copy',))
    assert not os.path.exists(str(staged['static'] / 'collection_log.json'))


def test_rewrite_is_idempotent(staged):
    first = run(staged)
    second = run(staged)
    assert first['content_hash'] == second['content_hash']
    assert (first['generated'], first['generated_iso']) == (second['generated'],
                                                            second['generated_iso'])


def test_changed_input_changes_the_payload(staged):
    first = run(staged)
    write_json(staged['data'] / 'owned.json', OWNED + [
        {'slug': 'nezha', 'name': 'Nezha', 'count': 1, 'path': '/Lotus/Powersuits/Odalisk/Odalisk'}])
    second = run(staged)
    assert second['overall']['obtained'] == first['overall']['obtained'] + 1
    assert second['content_hash'] != first['content_hash']


def test_owned_index_skips_junk_rows(staged):
    write_json(staged['data'] / 'owned.json', OWNED + [None, 'x', {'count': 3}, {'slug': 'relic'}])
    paths, slugs, count = staged['mod'].owned_index()
    assert slugs == {'braton_prime', 'braton_prime_receiver', 'relic'}
    assert '/Lotus/Weapons/Tenno/Rifle/BratonPrime' in paths
    assert count == len(OWNED) + 4


def test_atomic_write_leaves_no_tmp_file(staged):
    run(staged)
    out = staged['data'] / 'collection_log.json'
    assert os.path.exists(str(out)) and not os.path.exists(str(out) + '.tmp')


def test_selftest_passes_offline(staged, capsys):
    assert staged['mod'].selftest() == 0
    assert '0 failed' in capsys.readouterr().out
