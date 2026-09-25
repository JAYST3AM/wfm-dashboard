"""scripts/mod_cards.py: card build, rank resolution, price join, CLI + idempotency.

The public repo ships NO data/ folder (CI checks out a clean tree), so every test here
builds its own inputs under tmp_path and monkeypatches the module's path globals:
no repo file is read and nothing in the repo is written. The offline catalogue is an
embedded fixture, so no test touches the network (the one live GET lives behind
--refresh-catalog, which the tests only exercise with a monkeypatched fetch).

Fixture shape mirrors the real data:
  * WFCD catalog rows are keyed by uniqueName and carry rarity/polarity/fusionLimit;
  * WFM items carry gameRef -> slug (the join that saves "Hell's Chamber");
  * owned.json rows are per-section (RawUpgrades = unranked stacks, Upgrades = ranked);
  * lastData.dec.json holds the per-copy ranks as UpgradeFingerprint JSON.
"""
import os
from types import SimpleNamespace

import pytest

from conftest import REPO, load_script, read_json, write_json

CARD_KEYS = {'slug', 'name', 'rarity', 'type', 'polarity', 'base_drain', 'max_rank',
             'is_prime', 'owned_copies', 'owned_rank', 'floor', 'median', 'stats_text', 'icon',
             'lane_rank', 'lane_ask', 'lane_bid'}

CATALOG = {'source_url': 'https://example.invalid/Mods.json', 'fetched': 1700000000,
           'fetched_iso': '2023-11-14T22:13:20Z', 'fields': ['name', 'uniqueName'],
           'mods': [
               {'uniqueName': '/Lotus/Upgrades/Mods/Warframe/AvatarHealthMaxMod',
                'name': 'Vitality', 'type': 'Warframe Mod', 'compatName': 'WARFRAME',
                'rarity': 'Common', 'polarity': 'vazarin', 'baseDrain': 2, 'fusionLimit': 10,
                'isPrime': False,
                'levelStats': [{'stats': ['+9% Health']}, {'stats': ['+100% Health']}]},
               {'uniqueName': '/Lotus/Upgrades/Mods/Shotgun/WeaponFireIterationsMod',
                'name': "Hell's Chamber", 'type': 'Shotgun Mod', 'compatName': 'Shotgun',
                'rarity': 'Rare', 'polarity': 'madurai', 'baseDrain': 4, 'fusionLimit': 5,
                'levelStats': [{'stats': ['+120% Multishot']}]},
               {'uniqueName': '/Lotus/Upgrades/Mods/Warframe/Expert/AvatarAbilityDurationModExpert',
                'name': 'Primed Continuity', 'type': 'Warframe Mod', 'compatName': 'WARFRAME',
                'rarity': 'Legendary', 'polarity': 'madurai', 'baseDrain': 4, 'fusionLimit': 10,
                'isPrime': True,
                'levelStats': [{'stats': ['+50% Ability Duration']},
                               {'stats': ['+55% Ability Duration',
                                          'Kills grant <DT_FIRE_COLOR>Heat damage.']}]},
               {'uniqueName': '/Lotus/Upgrades/Mods/Melee/WeaponArmorPiercingDamageMod',
                'name': 'Sundering Strike', 'type': 'Melee Mod', 'compatName': 'Melee',
                'rarity': 'Rare', 'polarity': 'naramon', 'baseDrain': 4, 'fusionLimit': 5},
           ]}
WFM_ITEMS = [
    {'slug': 'vitality', 'gameRef': '/Lotus/Upgrades/Mods/Warframe/AvatarHealthMaxMod',
     'maxRank': 10, 'tags': ['mod', 'common', 'warframe'], 'i18n': {'en': {'name': 'Vitality'}}},
    {'slug': 'hells_chamber', 'gameRef': '/Lotus/Upgrades/Mods/Shotgun/WeaponFireIterationsMod',
     'maxRank': 5, 'tags': ['mod', 'rare', 'shotgun'], 'i18n': {'en': {'name': "Hell's Chamber"}}},
    {'slug': 'primed_continuity',
     'gameRef': '/Lotus/Upgrades/Mods/Warframe/Expert/AvatarAbilityDurationModExpert',
     'maxRank': 10, 'tags': ['mod', 'legendary', 'warframe'],
     'i18n': {'en': {'name': 'Primed Continuity'}}},
    {'slug': 'sundering_strike', 'gameRef': '/Lotus/Upgrades/Mods/Melee/WeaponArmorPiercingDamageMod',
     'maxRank': 5, 'tags': ['mod', 'rare', 'melee'], 'i18n': {'en': {'name': 'Sundering Strike'}}},
    {'slug': 'arcane_energize', 'gameRef': '/Lotus/Upgrades/CosmeticEnhancers/Utility/EnergyPickup',
     'maxRank': 5, 'tags': ['arcane_enhancement', 'rare'],
     'i18n': {'en': {'name': 'Arcane Energize'}}},
]
OWNED = [
    # stack of unranked copies (RawUpgrades) + one fully ranked copy (Upgrades)
    {'slug': 'vitality', 'name': 'Vitality', 'count': 30, 'tags': ['mod', 'common', 'warframe'],
     'section': 'RawUpgrades', 'path': '/Lotus/Upgrades/Mods/Warframe/AvatarHealthMaxMod'},
    {'slug': 'vitality', 'name': 'Vitality', 'count': 1, 'tags': ['mod', 'common', 'warframe'],
     'section': 'Upgrades', 'path': '/Lotus/Upgrades/Mods/Warframe/AvatarHealthMaxMod'},
    {'slug': 'primed_continuity', 'name': 'Primed Continuity', 'count': 2,
     'tags': ['mod', 'legendary', 'warframe'], 'section': 'Upgrades',
     'path': '/Lotus/Upgrades/Mods/Warframe/Expert/AvatarAbilityDurationModExpert'},
    {'slug': 'arcane_energize', 'name': 'Arcane Energize', 'count': 4,
     'tags': ['arcane_enhancement', 'rare'], 'section': 'RawUpgrades',
     'path': '/Lotus/Upgrades/CosmeticEnhancers/Utility/EnergyPickup'},
]
SAVE = {'Upgrades': [
    {'ItemType': '/Lotus/Upgrades/Mods/Warframe/AvatarHealthMaxMod', 'UpgradeFingerprint': '{"lvl":10}'},
    {'ItemType': '/Lotus/Upgrades/Mods/Warframe/Expert/AvatarAbilityDurationModExpert',
     'UpgradeFingerprint': '{"lvl":4}'},
    {'ItemType': '/Lotus/Upgrades/Mods/Warframe/Expert/AvatarAbilityDurationModExpert',
     'UpgradeFingerprint': '{"lvl":2}'},
    {'ItemType': '/Lotus/Upgrades/Mods/Melee/WeaponArmorPiercingDamageMod',
     'UpgradeFingerprint': 'not json at all'},
]}
PRICES = {'vitality': {'wts': 2, 'wtb': 5, 'n_sell': 9, 'n_buy': 2},
          'primed_continuity': {'wts': 85, 'wtb': None},
          'hells_chamber': {'wts': None, 'wtb': None}}
STATS = {'vitality': {'med48': 2.5, 'vol48': 40},
         'primed_continuity': {'med48': 85.538461},
         'sundering_strike': {'median': 12.34}}


@pytest.fixture
def mc(monkeypatch):
    return load_script('mod_cards', monkeypatch=monkeypatch)


@pytest.fixture
def built(mc):
    """The pure build over the fixture inputs (no I/O anywhere)."""
    cards, diag = mc.build_cards(CATALOG['mods'], WFM_ITEMS, OWNED, SAVE, PRICES, STATS)
    return SimpleNamespace(mod=mc, cards={c['slug']: c for c in cards}, rows=cards, diag=diag)


@pytest.fixture
def mc_run(mc, monkeypatch, data_dir):
    """main() end to end against tmp_path: no network (cache present), no repo writes."""
    monkeypatch.setattr(mc, 'DATA', str(data_dir))
    monkeypatch.setattr(mc, 'OUT', str(data_dir / 'mod_cards.json'))
    monkeypatch.setattr(mc, 'CACHE', str(data_dir / 'wfcd_mods_cache.json'))
    write_json(data_dir / 'wfcd_mods_cache.json', CATALOG)
    write_json(data_dir / 'wfm_items_v2.json', {'data': WFM_ITEMS})
    write_json(data_dir / 'owned.json', OWNED)
    write_json(data_dir / 'lastData.dec.json', SAVE)
    write_json(data_dir / 'prices.json', PRICES)
    write_json(data_dir / 'stats.json', STATS)
    mc.main(['--no-fetch', '--quiet', '--top', '0'])
    return SimpleNamespace(mod=mc, data_dir=data_dir, doc=read_json(data_dir / 'mod_cards.json'))


# ------------------------------------------------------------------ selftest / CLI
def test_selftest_passes_offline_and_writes_nothing(mc, capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(mc, 'OUT', str(tmp_path / 'mod_cards.json'))
    monkeypatch.setattr(mc, 'CACHE', str(tmp_path / 'wfcd_mods_cache.json'))
    assert mc.main(['--selftest']) == 0
    out = capsys.readouterr().out
    assert 'selftest: PASS' in out and 'FAIL' not in out
    assert not list(tmp_path.iterdir())              # fixtures only: nothing written


def test_selftest_standalone_entry_point(mc):
    assert mc.selftest() == 0


def test_no_cache_and_no_fetch_fails_loudly(mc, monkeypatch, data_dir, capsys):
    monkeypatch.setattr(mc, 'DATA', str(data_dir))
    monkeypatch.setattr(mc, 'OUT', str(data_dir / 'mod_cards.json'))
    monkeypatch.setattr(mc, 'CACHE', str(data_dir / 'wfcd_mods_cache.json'))
    assert mc.main(['--no-fetch']) == 2
    assert 'ERROR' in capsys.readouterr().out
    assert not (data_dir / 'mod_cards.json').exists()


# ------------------------------------------------------------------ output contract
def test_document_contract(mc_run):
    doc = mc_run.doc
    assert set(doc) == {'generated', 'generated_iso', 'cards', 'summary', 'sources', 'notes'}
    assert set(doc['summary']) == {'cards', 'owned', 'missing', 'dupes', 'rarities'}
    assert all(set(card) == CARD_KEYS for card in doc['cards'])
    assert isinstance(doc['generated'], int) and doc['generated_iso'].endswith('Z')
    assert doc['sources']['catalog']['source_url'].startswith('https://')
    assert doc['sources']['ranks']['file'] == 'data/lastData.dec.json'


def test_summary_counts_owned_missing_dupes(mc_run):
    summary = mc_run.doc['summary']
    assert summary['cards'] == 4                     # arcane row is not a mod card
    assert summary['owned'] == 2                     # vitality + primed continuity
    assert summary['missing'] == 2                   # hell's chamber + sundering strike
    assert summary['dupes'] == 2                     # vitality stack + primed continuity x2
    assert summary['rarities']['Legendary'] == {'total': 1, 'owned': 1}
    assert list(summary['rarities'])[0] == 'Legendary'


def test_write_is_atomic_and_leaves_no_temp_file(mc_run):
    assert not list(mc_run.data_dir.glob('*.tmp'))


def test_second_run_is_byte_identical(mc_run):
    first = (mc_run.data_dir / 'mod_cards.json').read_bytes()
    mc_run.mod.main(['--no-fetch', '--quiet', '--top', '0'])
    assert (mc_run.data_dir / 'mod_cards.json').read_bytes() == first
    assert read_json(mc_run.data_dir / 'mod_cards.json')['generated'] == mc_run.doc['generated']


# ------------------------------------------------------------------ joins
def test_slug_comes_from_gameRef_not_slugify(built):
    assert "hell's chamber" and 'hells_chamber' in built.cards
    assert 'hell_s_chamber' not in built.cards
    assert built.cards['hells_chamber']['name'] == "Hell's Chamber"


def test_arcanes_are_not_cards(built):
    assert 'arcane_energize' not in built.cards


def test_owned_only_mod_becomes_a_card(mc):
    owned = OWNED + [{'slug': 'clashing_forest', 'name': 'Clashing Forest', 'count': 3,
                      'tags': ['mod', 'uncommon', 'stance'], 'section': 'RawUpgrades',
                      'path': '/Lotus/Weapons/Tenno/Melee/MeleeTrees/StaffCmbOneMeleeTree'}]
    wfm = WFM_ITEMS + [{'slug': 'clashing_forest',
                        'gameRef': '/Lotus/Weapons/Tenno/Melee/MeleeTrees/StaffCmbOneMeleeTree',
                        'maxRank': 3, 'tags': ['mod', 'uncommon', 'stance'],
                        'i18n': {'en': {'name': 'Clashing Forest'}}}]
    cards, diag = mc.build_cards(CATALOG['mods'], wfm, owned, SAVE, PRICES, STATS)
    card = {c['slug']: c for c in cards}['clashing_forest']
    assert diag['owned_slugs_not_in_catalog'] == 1
    assert card['rarity'] == 'Uncommon' and card['type'] == 'Stance'
    assert card['max_rank'] == 3 and card['owned_rank'] == 0 and card['polarity'] is None


# ------------------------------------------------------------------ card fields
def test_owned_copies_sum_every_section_and_rank_is_the_best_copy(built):
    card = built.cards['vitality']
    assert card['owned_copies'] == 31                  # 30 raw + 1 ranked
    assert card['owned_rank'] == 10                    # best fingerprint wins
    assert built.cards['primed_continuity']['owned_rank'] == 4


def test_raw_only_stack_is_rank_zero(built):
    assert built.cards['hells_chamber']['owned_copies'] == 0
    assert built.cards['hells_chamber']['owned_rank'] is None


def test_unmatched_fingerprint_leaves_rank_null(mc):
    owned = [{'slug': 'sundering_strike', 'name': 'Sundering Strike', 'count': 1,
              'tags': ['mod', 'rare', 'melee'], 'section': 'Upgrades',
              'path': '/Lotus/Upgrades/Mods/Melee/WeaponArmorPiercingDamageMod'}]
    cards, _ = mc.build_cards(CATALOG['mods'], WFM_ITEMS, owned, {'Upgrades': [
        {'ItemType': '/Lotus/Upgrades/Mods/Melee/WeaponArmorPiercingDamageMod',
         'UpgradeFingerprint': 'not json at all'}]}, {}, {})
    card = {c['slug']: c for c in cards}['sundering_strike']
    assert card['owned_rank'] is None


def test_rarity_polarity_type_and_prime_flags(built):
    card = built.cards['primed_continuity']
    assert (card['rarity'], card['polarity'], card['type']) == ('Legendary', 'madurai', 'Warframe')
    assert card['is_prime'] is True and card['max_rank'] == 10 and card['base_drain'] == 4
    assert built.cards['vitality']['is_prime'] is False
    assert built.cards['hells_chamber']['type'] == 'Shotgun'


def test_aura_compat_becomes_aura_type(mc):
    mod = {'uniqueName': '/Lotus/Upgrades/Mods/Warframe/Aura/EnergySiphon', 'name': 'Energy Siphon',
           'type': 'Warframe Mod', 'compatName': 'AURA', 'rarity': 'Uncommon',
           'polarity': 'aura', 'baseDrain': 4, 'fusionLimit': 5}
    cards, _ = mc.build_cards([mod], [], [], {}, {}, {})
    card = cards[0]
    assert card['type'] == 'Aura' and card['polarity'] == 'aura'


def test_missing_mod_has_no_fake_owned_numbers(built):
    card = built.cards['sundering_strike']
    assert (card['owned_copies'], card['owned_rank']) == (0, None)
    assert card['floor'] is None                     # no sell listing in the snapshot
    assert card['median'] == 12.3                    # a quote can exist without ownership
    unquoted = built.cards['hells_chamber']
    assert unquoted['floor'] is None and unquoted['median'] is None


def test_lanes_price_the_rank_owned_not_rank_zero(mc):
    """An any-rank floor is a rank-0 price; the lane is the copy's real price."""
    owned = [{'slug': 'primed_continuity', 'name': 'Primed Continuity', 'count': 1,
              'tags': ['mod', 'prime'], 'section': 'Upgrades',
              'path': '/Lotus/Upgrades/Mods/Warframe/Expert/AvatarAbilityDurationModExpert'}]
    save = {'Upgrades': [
        {'ItemType': '/Lotus/Upgrades/Mods/Warframe/Expert/AvatarAbilityDurationModExpert',
         'UpgradeFingerprint': '{"lvl":7}'}]}
    lanes = {'primed_continuity': {'max_rank': 10, 'lanes': {
        '0': {'ask': 15, 'n_ask': 4, 'bid': 4, 'bid_low': 4, 'n_bid': 2},
        '7': {'ask': 90, 'n_ask': 3, 'bid': 61, 'bid_low': 55, 'n_bid': 2}}}}
    cards, _ = mc.build_cards(CATALOG['mods'], WFM_ITEMS, owned, save,
                              {'primed_continuity': {'wts': 15}}, {}, lanes)
    card = {c['slug']: c for c in cards}['primed_continuity']
    assert card['floor'] == 15                        # snapshot floor stays untouched...
    assert (card['lane_rank'], card['lane_ask'], card['lane_bid']) == (7, 90, 61)


def test_lane_row_without_orders_keeps_rank_and_null_sides(mc):
    """A rank you own with no orders gets lane fields with null sides - never a rank-0 price."""
    owned = [{'slug': 'primed_continuity', 'name': 'Primed Continuity', 'count': 1,
              'tags': ['mod', 'prime'], 'section': 'Upgrades',
              'path': '/Lotus/Upgrades/Mods/Warframe/Expert/AvatarAbilityDurationModExpert'}]
    save = {'Upgrades': [
        {'ItemType': '/Lotus/Upgrades/Mods/Warframe/Expert/AvatarAbilityDurationModExpert',
         'UpgradeFingerprint': '{"lvl":7}'}]}
    lanes = {'primed_continuity': {'max_rank': 10, 'lanes': {'7': {'n_ask': 0, 'n_bid': 0}}}}
    cards, _ = mc.build_cards(CATALOG['mods'], WFM_ITEMS, owned, save,
                              {'primed_continuity': {'wts': 15}}, {}, lanes)
    card = {c['slug']: c for c in cards}['primed_continuity']
    assert (card['lane_rank'], card['lane_ask'], card['lane_bid']) == (7, None, None)


# ------------------------------------------------------------------ stats_text + prices
def test_stats_text_is_the_full_clean_card_text(built):
    assert built.cards['vitality']['stats_text'] == '+100% Health'
    # every max-rank line survives — stat line AND effect prose (the in-game card text),
    # markup stripped, one line each
    assert built.cards['primed_continuity']['stats_text'] == \
        '+55% Ability Duration\nKills grant Heat damage.'


def test_clean_stat_keeps_negative_stats(mc):
    assert mc.clean_stat('-55% Ability Efficiency') == '-55% Ability Efficiency'
    assert mc.clean_stat('<DT_FREEZE_COLOR>Cold Abilities') == 'Cold Abilities'


def test_stats_text_never_exceeds_the_cap(mc):
    mod = {'name': 'Wordy', 'uniqueName': '/Lotus/Upgrades/Mods/Wordy',
           'levelStats': [{'stats': ['x' * 400]}]}
    cards, _ = mc.build_cards([mod], [], [], {}, {}, {})
    assert len(cards[0]['stats_text']) <= mc.STATS_MAX
    # several long lines: all kept, the whole multi-line string still within the cap
    mod['levelStats'] = [{'stats': ['y' * 300, 'z' * 300]}]
    cards, _ = mc.build_cards([mod], [], [], {}, {}, {})
    text = cards[0]['stats_text']
    assert text.startswith('yyy') and '\n' in text and len(text) <= mc.STATS_MAX


def test_variant_rows_do_not_cap_the_card(mc):
    """A Beginner row caps at 3; the real card caps higher — the higher sane cap wins."""
    mod = {'name': 'Quick Learner',
           'uniqueName': '/Lotus/Upgrades/Mods/Warframe/Beginner/QuickLearnerBeginner',
           'type': 'Warframe Mod', 'compatName': 'WARFRAME', 'rarity': 'Rare',
           'polarity': 'madurai', 'baseDrain': 4, 'fusionLimit': 3,
           'levelStats': [{'stats': ['+50% Thing']}]}
    item = {'slug': 'quick_learner', 'gameRef': mod['uniqueName'], 'maxRank': 5,
            'tags': ['mod', 'rare', 'warframe'], 'i18n': {'en': {'name': 'Quick Learner'}}}
    cards, _ = mc.build_cards([mod], [item], [], {}, {}, {})
    assert cards[0]['max_rank'] == 5


def test_stats_text_falls_back_to_description(mc):
    mod = {'name': 'Described', 'uniqueName': '/Lotus/Upgrades/Mods/Described',
           'description': 'Spectral Scream Augment: launch an elemental projectile.'}
    cards, _ = mc.build_cards([mod], [], [], {}, {}, {})
    assert cards[0]['stats_text'].startswith('Spectral Scream Augment')


def test_price_join_uses_wts_and_med48(built):
    assert built.cards['vitality']['floor'] == 2 and built.cards['vitality']['median'] == 2.5
    assert built.cards['primed_continuity']['floor'] == 85
    assert built.cards['primed_continuity']['median'] == 85.5      # rounded to 1 decimal
    assert built.cards['sundering_strike']['median'] == 12.3       # legacy 'median' key


def test_zero_and_null_quotes_never_become_zero_prices(mc):
    owned = [{'slug': 'vitality', 'name': 'Vitality', 'count': 1, 'tags': ['mod', 'common'],
              'section': 'RawUpgrades', 'path': '/p'}]
    cards, _ = mc.build_cards(CATALOG['mods'][:1], WFM_ITEMS[:1], owned, {},
                              {'vitality': {'wts': 0}}, {'vitality': {'med48': 0}})
    assert cards[0]['floor'] is None and cards[0]['median'] is None


# ------------------------------------------------------------------ catalog cache
def test_trim_mod_keeps_only_the_fields_the_cards_need(mc):
    raw = {'name': 'Serration', 'uniqueName': '/u', 'type': 'Primary Mod', 'compatName': 'Rifle',
           'rarity': 'Uncommon', 'polarity': 'madurai', 'baseDrain': 2, 'fusionLimit': 3,
           'isPrime': False, 'drops': [{'location': 'x'}], 'imageName': 'y.jpg',
           'wikiaUrl': 'https://wiki', 'transmutable': False,
           'levelStats': [{'stats': ['+10% Damage']}, {'stats': []}]}
    trimmed = mc.trim_mod(raw)
    assert 'drops' not in trimmed and 'imageName' not in trimmed and 'wikiaUrl' not in trimmed
    assert trimmed['levelStats'] == [{'stats': ['+10% Damage']}]
    assert trimmed['name'] == 'Serration'


def test_load_catalog_falls_back_to_the_cache_when_the_fetch_fails(mc, monkeypatch, data_dir):
    monkeypatch.setattr(mc, 'CACHE', str(data_dir / 'wfcd_mods_cache.json'))
    write_json(data_dir / 'wfcd_mods_cache.json', CATALOG)

    def boom(*_a, **_k):
        raise mc.urllib.error.URLError('offline')

    monkeypatch.setattr(mc, 'fetch_catalog', boom)
    mods, source = mc.load_catalog(refresh=True, log=lambda *_: None)
    assert len(mods) == len(CATALOG['mods'])
    assert source['from_cache'] is True and 'fetch_error' in source


def test_load_catalog_without_cache_and_a_dead_fetch_raises(mc, monkeypatch, data_dir):
    def dead_fetch(*_a, **_k):
        raise mc.urllib.error.URLError('offline')

    monkeypatch.setattr(mc, 'CACHE', str(data_dir / 'nope.json'))
    monkeypatch.setattr(mc, 'fetch_catalog', dead_fetch)
    with pytest.raises(RuntimeError):
        mc.load_catalog(refresh=True, log=lambda *_: None)


# ------------------------------------------------------------------ ranking order
def test_cards_sort_owned_first_then_rarity(built):
    owned_flags = [c['owned_copies'] > 0 for c in built.rows]
    assert owned_flags == sorted(owned_flags, reverse=True)
    rank = built.mod.RARITY_RANK
    owned_rarities = [rank[c['rarity'] or 'Unknown'] for c in built.rows if c['owned_copies']]
    assert owned_rarities == sorted(owned_rarities, reverse=True)


def test_variant_score_prefers_the_canonical_row(mc):
    canonical = {'rarity': 'Common', 'polarity': 'vazarin', 'fusionLimit': 10}
    beginner = {'rarity': 'Common', 'polarity': 'vazarin', 'fusionLimit': 3}
    assert mc.variant_score(canonical, '/Lotus/Upgrades/Mods/Melee/X') > \
        mc.variant_score(beginner, '/Lotus/Upgrades/Mods/Melee/Beginner/XBeginner')


def test_sane_rank_guards_the_pip_cap(mc):
    assert mc.sane_rank(592) is None and mc.sane_rank(0) == 0 and mc.sane_rank(10) == 10
    assert mc.sane_rank('5') is None and mc.sane_rank(None) is None


# ------------------------------------------------------------------ cards page contract
# The page is static, so these are source-level checks: nav/theme wiring must match the
# lookup page, the JS must consume exactly the card fields the script emits, and no
# fetched data may be injected as HTML.
PAGE = os.path.join(REPO, 'static', 'cards.html')
SCRIPT = os.path.join(REPO, 'static', 'cards.js')
NAV_PILLS = [('/#home', 'Dashboard'), ('/#inventory', 'Inventory'), ('/#history', 'History'),
             ('/#trader', 'Trader'), ('/#market', 'Market'), ('/collection.html', 'Collection'),
             ('/cards.html', 'Cards'), ('/lookup.html', 'Lookup')]


def test_page_exists_and_reuses_the_shared_shell():
    html = open(PAGE, encoding='utf-8').read()
    assert '<script src="/theme.js"></script>' in html
    assert 'wfmInitThemeUI()' in html
    assert '<link rel="stylesheet" href="/style.css">' in html
    assert 'id="themePanel"' in html and 'id="themeGrid"' in html and 'id="chips"' in html


def test_nav_has_every_pill_with_cards_active():
    html = open(PAGE, encoding='utf-8').read()
    nav = html.split('<nav class="mainnav"', 1)[1].split('</nav>', 1)[0]
    for href, label in NAV_PILLS:
        assert 'href="%s"' % href in nav, href
        assert '>%s</a>' % label in nav, label
    assert 'href="/cards.html" class="navpill active">Cards</a>' in nav
    assert nav.count('navpill active') == 1


def test_page_has_the_grid_and_every_filter_control():
    html = open(PAGE, encoding='utf-8').read()
    for element_id in ('q', 'clearBtn', 'typeSel', 'sortSel', 'rarityRow', 'stateRow', 'resetBtn',
                       'meta', 'grid', 'moreBtn', 'empty'):
        assert 'id="%s"' % element_id in html, element_id
    # the sort control offers the modes the JS implements
    for mode in ('owned', 'name', 'rarity', 'copies', 'value'):
        assert '<option value="%s"' % mode in html, mode


def test_js_never_injects_data_as_html():
    js = open(SCRIPT, encoding='utf-8').read()
    assert '.innerHTML' not in js and 'insertAdjacentHTML' not in js
    assert 'textContent' in js


def test_js_consumes_every_card_field_the_script_emits():
    js = open(SCRIPT, encoding='utf-8').read()
    for key in CARD_KEYS:
        assert key in js, key                      # read from the JSON and normalised
    assert 'function normalize' in js


def test_js_can_find_the_build_on_this_machine():
    js = open(SCRIPT, encoding='utf-8').read()
    assert "'/api/feature/cards'" in js          # route the dashboard server exposes
    assert "'/data/mod_cards.json'" in js         # repo-root serving
    assert "'/mod_cards.json'" in js              # static/ copy


def test_js_renders_the_card_mechanics_the_page_promises():
    js = open(SCRIPT, encoding='utf-8').read()
    for token in ('rarityClass', "'r-'", 'is-prime', 'missing', 'mcd-dup', 'mcd-pips', 'flipped',
                  'mcd-pol', 'mcd-type', 'mcd-desc', 'mcd-price', 'mcd-rank',
                  'floor ', 'med ', 'no local quote', 'not owned', '\u00d7'):
        assert token in js, token
    for polarity in ('madurai', 'vazarin', 'naramon', 'zenurik', 'unairu', 'penjaga', 'umbra',
                     'universal', 'aura'):
        assert polarity in js, polarity


def test_back_is_the_universal_card_back_and_details_render_in_the_panel():
    """Card spec: one shared back design for every card; details live in the inspect panel."""
    js = open(SCRIPT, encoding='utf-8').read()
    html = open(PAGE, encoding='utf-8').read()
    for banned in ('mcd-stats', 'mcd-back-meta', 'mcd-back-name', 'mcd-back-slug', 'cardbacks/',
                   'mcd-back-crest'):
        assert banned not in js, banned                       # old back-info systems fully gone
    assert 'mcd-back-crest' not in html
    assert "url('/cardback.webp')" in html                    # the universal back art
    assert "I.info.appendChild(gradeLine(card))" in js        # grade reason moved to the panel
    assert "ins-stats" in js and "stats_text" in js           # stat line + rows feed the panel
    # full-art fronts: manifest-driven, front face, standard cards untouched
    assert "cardart/index.json" in js
    assert "has-fullart" in js and "'data-art'" in js and "state.cardart" in js
    # foil is wired but disabled by default (Jay builds the selective-mask version himself)
    assert 'HOLO_ENABLED = false' in js
    assert 'foilFor' in js and 'FOILS' in js and 'mcd-foil' in js


def test_grid_never_flips_on_hover():
    """Jay: hovering a grid card must never flip it, and the full-art face keeps only the
    art + name + mod text (no type label, silver polarity seal top-right, no rank/price row)."""
    html = open(PAGE, encoding='utf-8').read()
    assert ':hover .mcd-inner' not in html and ':focus-visible .mcd-inner' not in html
    assert '.mcd-card.flipped .mcd-inner' in html             # flip still exists, explicit only
    assert '.mcd-front.has-fullart .mcd-art > *' not in html  # no blanket hide of the wording
    assert '.mcd-front.has-fullart .mcd-art > .mcd-type { display: none; }' in html
    assert '.mcd-front.has-fullart .mcd-art > .mcd-pol {' in html
    assert 'background-clip: text' in html                    # brushed-silver polarity seal
    js = open(SCRIPT, encoding='utf-8').read()
    assert 'body.appendChild(pips(card))' not in js           # no rank/price rows on faces
    assert 'body.appendChild(priceLine(card))' not in js      # (they live in the panel right)
    assert 'if (fa && card.stats_text)' in js                 # mod text ONLY on full-art faces
    # pointer capture retargets the follow-up click to the tilt, so the viewer flips on
    # pointerup instead of relying on the card's own click handler
    assert "e.type === 'pointerup'" in js and 'elementFromPoint' in js


def test_local_hi_res_set_backs_card_and_lookup_art():
    """Art priority: the local 4x upscaled set (static/hi/index.json) beats the WFM CDN."""
    cards = open(SCRIPT, encoding='utf-8').read()
    look = open(os.path.join(REPO, 'static', 'lookup.js'), encoding='utf-8').read()
    lookhtml = open(os.path.join(REPO, 'static', 'lookup.html'), encoding='utf-8').read()
    assert "fetch('hi/index.json'" in cards and "fetch('/hi/index.json'" in look
    assert "state.hi && state.hi[card.slug]" in cards and "'/hi/' + card.slug + '.webp'" in cards
    assert "'/hi/' + it.slug + '.webp'" in look
    assert 'max-width: min(92vw, 720px)' in lookhtml              # zoom shows the big render


def test_interaction_never_reads_a_transformed_rect():
    """The jitter bug: hover math read its own transformed rect and oscillated."""
    js = open(SCRIPT, encoding='utf-8').read()
    assert 'card._gr' in js                                   # grid reads the cached rect
    assert 'stage.getBoundingClientRect()' in js              # viewer reads the stable stage
    assert "tilt.getBoundingClientRect()" not in js           # never the tilted element itself
    assert "ins.mode === 'settled'" in js                     # drag owns rotation after release


def test_page_css_defines_every_state_the_js_sets():
    html = open(PAGE, encoding='utf-8').read()
    for cls in ('.mcd-card.r-common', '.mcd-card.r-uncommon', '.mcd-card.r-rare',
                '.mcd-card.r-legendary', '.mcd-card.is-prime', '.mcd-card.missing',
                '.mcd-dup', '.mcd-pips i.on', '.mcd-pips i.avail', '.mcd-back', '.mcd-card.flipped'):
        assert cls in html, cls
    assert 'rotateY(180deg)' in html                     # the flip is a real 3D transform
    assert '--accent' in html and '--panel' in html      # colours come from theme vars


def test_baked_card_faces_and_the_art_probe_cannot_overwrite_them():
    """Full-art regression fix (2026-09-26): after the local hi-res probe succeeds,
    upgradeArt() used to inject the upscaled BASE card image into every card - including
    full-art faces, which made Archon Continuity render as its base card. addArt() now
    refuses any card with a cardart entry. The manifest also gained the baked form:
    {file, baked: true} = the file already IS the finished card face (its own frame,
    title, stats and polarity), so nothing is drawn over it and it shows edge-to-edge."""
    import json
    js = open(SCRIPT, encoding='utf-8').read()
    html = open(PAGE, encoding='utf-8').read()
    assert 'function artEntry(card)' in js
    assert "typeof v === 'string'" in js and 'baked: !!v.baked' in js
    assert 'if (artEntry(card)) return;' in js              # addArt refuses full-art cards
    assert "front.classList.add('art-baked')" in js
    assert '.mcd-front.has-fullart.art-baked {' in html
    assert 'background-size: 100% 100%;' in html            # whole file, no crop
    assert '.mcd-front.has-fullart.art-baked::before { display: none; }' in html
    assert '.mcd-front.has-fullart.art-baked .mcd-name,' in html
    man = json.load(open(os.path.join(REPO, 'static', 'cardart', 'index.json'), encoding='utf-8'))
    for slug in ('archon_continuity', 'archon_flow'):
        entry = man.get(slug)
        assert isinstance(entry, dict) and entry.get('baked') is True, slug
        assert str(entry.get('file', '')).endswith('.webp'), slug
        assert os.path.exists(os.path.join(REPO, 'static', 'cardart', entry['file'])), slug


def test_icon_cards_never_print_the_title_twice():
    """Jay (2026-09-26): "these cards already have the title they don't need it twice,
    remove the bottom one." The WFM icon IS the complete in-game card - title, stat text
    and type banner are baked into the image - so the drawn nameplate below it is a
    duplicate title. One structural CSS rule (art sibling -> body) drops the nameplate
    whenever an art image is present, whichever build path added the class (grid build,
    hi-res probe, or the inspect big card, which gets its art before entering the DOM).
    No-art cards and raw full-art cards (no baked title in the artwork) keep the name."""
    js = open(SCRIPT, encoding='utf-8').read()
    html = open(PAGE, encoding='utf-8').read()
    assert "art.classList.add('has-art');" in js
    assert '.mcd-front .mcd-art.has-art ~ .mcd-body { display: none; }' in html
    # not keyed on has-fullart: raw-art full-art faces still draw their name + wording
    assert '.mcd-front.has-fullart .mcd-name {' in html
    assert '.mcd-front.has-fullart.art-baked .mcd-name,' in html   # baked faces hide it
