"""scripts/trader/riven_lister.py - the veiled-riven listing planner (plans only, never posts).

scripts/trader/ is private and gitignored, so this file skips itself when the script is not
present (clean CI checkout). riven_lister.py is stdlib-only and import-safe by design - no
wfm_session, no HTTP, no work at import - so it can be loaded directly here.

Covered: the output contract, lane pricing off the data/rivens.json family bands (floor minus
the settings undercut, clamped up to the min price), equipped copies subtracted before pricing
(a fully equipped stack is held, never listed), revealed rivens held for a manual price, every
hold reason, the daily listing cap, the settings fallbacks, the killswitch gate, and one real
CLI run against a copied harness proving the tool writes its plan and nothing else.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

from conftest import SCRIPTS, load_script, read_json, write_json

SRC = os.path.join(SCRIPTS, 'trader', 'riven_lister.py')
pytestmark = pytest.mark.skipif(not os.path.exists(SRC),
                                reason='scripts/trader is private (gitignored) - nothing to test')

NOW = 1790341352
SETTINGS = {'dry_run': True, 'max_new_listings_per_day': 20, 'max_active_listings': 40,
            'undercut_platinum': 1, 'min_price_pct_of_median': 60, 'min_price_platinum': 3,
            'buy_budget_cap_platinum': 300, 'poll_seconds': 90}

# veiled family bands, the shape scripts/rivens.py leaves in data/rivens.json
BANDS = [
    {'slug': 'rifle_riven_mod_(veiled)', 'name': 'Rifle Riven Mod (Veiled)', 'type': 'rifle',
     'floor': 10.0, 'median': 10.26, 'vol48': 912},
    {'slug': 'melee_riven_mod_(veiled)', 'name': 'Melee Riven Mod (Veiled)', 'type': 'melee',
     'floor': 8.0, 'median': 7.23, 'vol48': 1376},
    {'slug': 'kitgun_riven_mod_(veiled)', 'name': 'Kitgun Riven Mod (Veiled)', 'type': 'kitgun',
     'floor': 2.0, 'median': 1.93, 'vol48': 14},          # floor below min -> clamp
    {'slug': 'zaw_riven_mod_(veiled)', 'name': 'Zaw Riven Mod (Veiled)', 'type': 'zaw',
     'floor': None, 'median': 2.98, 'vol48': 48},        # band exists, no quoted floor
]
ESTS = [{'name': 'Braton Riven Mod', 'qty': 1, 'est_low': 250.0, 'est_high': 400.0,
         'basis': 'veiled_band:rifle'}]

# owned.json rows (one row = one stack): veiled stacks keep their family in slug AND path
OWNED = [
    {'slug': 'melee_riven_mod_(veiled)', 'name': 'Melee Riven Mod (Veiled)', 'count': 10,
     'tags': ['mod', 'riven_mod', 'veiled_riven'], 'section': 'Upgrades', 'refinement': None,
     'path': '/Lotus/Upgrades/Mods/Randomized/PlayerMeleeWeaponRandomModRare'},
    {'slug': 'rifle_riven_mod_(veiled)', 'name': 'Rifle Riven Mod (Veiled)', 'count': 1,
     'tags': ['mod', 'riven_mod', 'veiled_riven'], 'section': 'Upgrades', 'refinement': None,
     'path': '/Lotus/Upgrades/Mods/Randomized/LotusRifleRandomModRare'},
    {'slug': 'kitgun_riven_mod_(veiled)', 'name': 'Kitgun Riven Mod (Veiled)', 'count': 1,
     'tags': ['mod', 'riven_mod', 'veiled_riven'], 'section': 'Upgrades', 'refinement': None,
     'path': '/Lotus/Upgrades/Mods/Randomized/LotusKitgunRandomModRare'},
    {'slug': 'zaw_riven_mod_(veiled)', 'name': 'Zaw Riven Mod (Veiled)', 'count': 1,
     'tags': ['mod', 'riven_mod', 'veiled_riven'], 'section': 'Upgrades', 'refinement': None,
     'path': '/Lotus/Upgrades/Mods/Randomized/LotusZawRandomModRare'},
    {'slug': 'shotgun_riven_mod_(veiled)', 'name': 'Shotgun Riven Mod (Veiled)', 'count': 2,
     'tags': ['mod', 'riven_mod', 'veiled_riven'], 'section': 'Upgrades', 'refinement': None,
     'path': '/Lotus/Upgrades/Mods/Randomized/LotusShotgunRandomModRare'},
    {'slug': 'mystery_riven_mod_(veiled)', 'name': 'Mystery Riven Mod (Veiled)', 'count': 2,
     'tags': ['mod', 'riven_mod', 'veiled_riven'], 'section': 'Upgrades', 'refinement': None,
     'path': None},
    {'slug': 'braton_riven_mod', 'name': 'Braton Riven Mod', 'count': 1,
     'tags': ['mod', 'riven_mod'], 'section': 'Upgrades', 'refinement': None,
     'path': '/Lotus/Upgrades/Mods/Randomized/LotusRifleRandomModRare'},
    {'slug': 'vectis_riven_mod', 'name': 'Vectis Riven Mod', 'count': 2,
     'tags': ['mod', 'riven_mod'], 'section': 'Upgrades', 'refinement': None,
     'path': '/Lotus/Upgrades/Mods/Randomized/LotusRifleRandomModRare'},
]

# data/inuse.json (inuse.py output): the same item_id twice counts once
INUSE = {'generated': NOW - 600, 'equipped_oids': 296, 'matched_upgrades': 4, 'items': [
    {'item_id': 'a', 'path': '.../PlayerMeleeWeaponRandomModRare', 'rank': 8,
     'slug': 'melee_riven_mod_(veiled)', 'name': 'Melee Riven Mod (Veiled)'},
    {'item_id': 'a', 'path': '.../PlayerMeleeWeaponRandomModRare', 'rank': 8,
     'slug': 'melee_riven_mod_(veiled)', 'name': 'Melee Riven Mod (Veiled)'},
    {'item_id': 'b', 'path': '.../PlayerMeleeWeaponRandomModRare', 'rank': 0,
     'slug': 'melee_riven_mod_(veiled)', 'name': 'Melee Riven Mod (Veiled)'},
    {'item_id': 'c', 'path': '.../LotusRifleRandomModRare', 'rank': 8,
     'slug': 'rifle_riven_mod_(veiled)', 'name': 'Rifle Riven Mod (Veiled)'},
    {'item_id': 'd', 'path': '.../AvatarHealthMaxMod', 'rank': 9, 'slug': 'vitality',
     'name': 'Vitality'},
]}


@pytest.fixture
def rl(monkeypatch):
    """Fresh module object per test, so monkeypatched path globals cannot leak."""
    monkeypatch.delenv('WFM_RIVEN_LISTER_DATA', raising=False)   # ignore ambient overrides
    return load_script('trader/riven_lister')


def plan(rl, settings=None, bands=None, owned=None, in_use=None, ests=ESTS, **kw):
    """build_plan over the fixtures - pure: no files, no network."""
    return rl.build_plan({'veiled_bands': BANDS if bands is None else bands,
                          'owned_rivens': ests},
                         OWNED if owned is None else owned,
                         INUSE if in_use is None else in_use,
                         SETTINGS if settings is None else settings, now=NOW, **kw)


def by_slug(doc):
    return {o['slug']: o for o in doc['orders']}


def hold_of(doc, name):
    return next(h for h in doc['holds'] if h['name'] == name)


def run_cli(rl, monkeypatch, tmp_path, argv=('--plan',), settings=None, files=True, kill=False):
    """Drive the real CLI in-process against throwaway files (never the repo's data/)."""
    data = tmp_path / 'data'
    data.mkdir(exist_ok=True)
    monkeypatch.setattr(rl, 'DATA', str(data))
    monkeypatch.setattr(rl, 'SETTINGS', str(tmp_path / 'settings.json'))
    monkeypatch.setenv('WFM_TRADER_SETTINGS', str(tmp_path / 'settings.json'))
    if files:
        write_json(data / 'rivens.json',
                   {'generated': '2026-09-25T23:31:39', 'veiled_bands': BANDS,
                    'owned_rivens': ESTS, 'summary': {'band_count': 4}})
        write_json(data / 'owned.json', OWNED)
        write_json(data / 'inuse.json', INUSE)
    write_json(tmp_path / 'settings.json', SETTINGS if settings is None else settings)
    if kill:
        write_json(data / 'kill_switch.json', {'active': True, 'note': 'test'})
    monkeypatch.setattr(sys, 'argv', ['riven_lister.py'] + list(argv))
    return rl.main(), data


# ---------------------------------------------------------------- contract / safety
def test_planner_has_no_network_or_session_code():
    """Reads local JSON and nothing else: no HTTP, no sign-in, no shells, no writes elsewhere."""
    with open(SRC, encoding='utf-8') as fh:
        src = fh.read().lower()
    for banned in ('urllib', 'requests.', 'socket', 'subprocess', 'wfm_session', 'signin',
                   'api.warframe.market'):
        assert banned not in src, 'riven_lister.py must stay offline - found %r' % banned
    assert 'os.replace' in src, 'atomic write (tmp + os.replace) is house style'


def test_document_contract(rl):
    """Exactly the documented keys - orders, holds, summary and the settings echo."""
    doc = plan(rl)
    assert tuple(doc) == ('generated', 'mode', 'orders', 'holds', 'summary', 'settings_echo')
    assert doc['mode'] == 'dry-run'
    assert doc['generated'] == NOW
    assert doc['settings_echo'] == {'undercut': 1, 'min_price': 3, 'cap': 20}
    assert doc['summary'] == {'orders': 2, 'copies': 9, 'plan_plat': 59}
    for o in doc['orders']:
        assert sorted(o) == ['family', 'floor', 'lane', 'name', 'note', 'price', 'qty', 'slug']
        assert o['lane'] == 'veiled'
        assert isinstance(o['price'], int) and isinstance(o['qty'], int)
        assert o['price'] >= doc['settings_echo']['min_price']
        assert o['qty'] > 0
    for h in doc['holds']:
        assert sorted(h) in (['name', 'reason'], ['est_high', 'est_low', 'name', 'reason'])


def test_prices_are_band_floor_minus_undercut(rl):
    """price = floor - undercut_platinum, and a higher undercut moves every order down."""
    doc = plan(rl, dict(SETTINGS, undercut_platinum=2))
    got = {s: (o['price'], o['floor']) for s, o in by_slug(doc).items()}
    assert got == {'melee_riven_mod_(veiled)': (6, 8.0), 'kitgun_riven_mod_(veiled)': (3, 2.0)}
    assert hold_of(doc, 'Rifle Riven Mod (Veiled)')['reason'] == 'all copies in use (equipped)'
    assert by_slug(doc)['melee_riven_mod_(veiled)']['note'] == 'floor 8p -2 undercut (+2 in use)'


def test_floor_below_min_price_clamps_to_min(rl):
    """A band floor under the min price is clamped up, not dropped and never rounded down."""
    doc = plan(rl)
    kit = by_slug(doc)['kitgun_riven_mod_(veiled)']
    assert (kit['floor'], kit['price']) == (2.0, 3)
    assert kit['note'] == 'floor 2p -1 undercut clamped to min 3p'
    assert all(o['price'] >= SETTINGS['min_price_platinum'] for o in doc['orders'])
    low = plan(rl, dict(SETTINGS, min_price_platinum=5))
    assert by_slug(low)['kitgun_riven_mod_(veiled)']['price'] == 5


def test_equipped_copies_are_subtracted(rl):
    """10 owned melee rivens, 2 distinct equipped (the duplicate item_id counts once) -> 8."""
    doc = plan(rl)
    melee = by_slug(doc)['melee_riven_mod_(veiled)']
    assert melee['qty'] == 8
    assert melee['note'] == 'floor 8p -1 undercut (+2 in use)'
    assert rl.in_use_counts(INUSE)[0]['melee_riven_mod_(veiled)'] == 2
    assert rl.in_use_counts({'items': [{'item_id': 'x', 'rank': 1}]}) == ({}, True)


def test_equipped_only_stack_is_never_listed(rl):
    """The rifle stack is 1 owned / 1 equipped: a hold, and absent from the orders."""
    doc = plan(rl)
    assert 'rifle_riven_mod_(veiled)' not in by_slug(doc)
    assert hold_of(doc, 'Rifle Riven Mod (Veiled)')['reason'] == 'all copies in use (equipped)'
    assert 'Rifle Riven Mod (Veiled)' not in [o['name'] for o in doc['orders']]


def test_equipped_copies_never_exceed_owned(rl):
    """Junk in inuse.json (more equipped than owned) holds the stack instead of going negative."""
    over = {'items': [{'item_id': 'z%d' % i, 'slug': 'kitgun_riven_mod_(veiled)', 'rank': 0}
                      for i in range(3)]}
    doc = plan(rl, in_use=over)
    assert 'kitgun_riven_mod_(veiled)' not in by_slug(doc)
    assert hold_of(doc, 'Kitgun Riven Mod (Veiled)')['reason'] == 'all copies in use (equipped)'


def test_missing_in_use_document_holds_everything(rl):
    """data/inuse.json unreadable = no order at all (never list a copy that might be equipped)."""
    doc = plan(rl, in_use={}, in_use_ok=False)
    assert doc['orders'] == []
    assert doc['summary'] == {'orders': 0, 'copies': 0, 'plan_plat': 0}
    reasons = {h['reason'] for h in doc['holds']}
    assert 'in-use data unavailable (data/inuse.json)' in reasons
    assert hold_of(doc, 'Braton Riven Mod')['reason'] == 'manual price (roll-dependent)'
    assert rl.in_use_counts(None) == ({}, False)
    assert rl.in_use_counts({'items': 'junk'}) == ({}, False)


def test_selfcheck_of_equipped_copies(rl):
    """The raw inuse.json document may be passed by mistake - it is normalised, not trusted."""
    doc = plan(rl)
    assert plan(rl, in_use=INUSE)['orders'] == doc['orders']


# ---------------------------------------------------------------- holds
def test_family_without_a_band_is_held(rl):
    """Shotgun has no row in veiled_bands -> hold, never a guessed price."""
    doc = plan(rl)
    assert hold_of(doc, 'Shotgun Riven Mod (Veiled)')['reason'] == 'veiled band floor missing (shotgun)'


def test_band_without_a_floor_is_held(rl):
    """zaw_riven_mod_(veiled) exists but its floor is null -> hold."""
    doc = plan(rl)
    assert hold_of(doc, 'Zaw Riven Mod (Veiled)')['reason'] == 'veiled band floor missing (zaw)'
    no_bands = plan(rl, bands=[])
    assert hold_of(no_bands, 'Melee Riven Mod (Veiled)')['reason'] == 'veiled band floor missing (melee)'
    assert no_bands['orders'] == []


def test_unidentifiable_veiled_family_is_held_not_guessed(rl):
    """No family in slug, path or name -> the documented 'not identifiable' hold."""
    doc = plan(rl)
    assert hold_of(doc, 'Mystery Riven Mod (Veiled)')['reason'] == 'veiled family not identifiable from save'
    assert 'mystery_riven_mod_(veiled)' not in by_slug(doc)


def test_revealed_rivens_are_manual_price_holds(rl):
    """Revealed / mounted rivens are roll-dependent: held, with the rivens.json estimate only."""
    doc = plan(rl)
    assert 'braton_riven_mod' not in by_slug(doc) and 'vectis_riven_mod' not in by_slug(doc)
    braton = hold_of(doc, 'Braton Riven Mod')
    assert braton == {'name': 'Braton Riven Mod', 'reason': 'manual price (roll-dependent)',
                      'est_low': 250.0, 'est_high': 400.0}
    vectis = hold_of(doc, 'Vectis Riven Mod x2')
    assert vectis == {'name': 'Vectis Riven Mod x2', 'reason': 'manual price (roll-dependent)'}


def test_estimates_need_a_usable_band_value(rl):
    """A rivens.json row without est_low/est_high adds no estimate to the hold."""
    doc = plan(rl, ests=[{'name': 'Braton Riven Mod', 'qty': 1, 'est_low': None, 'est_high': None,
                          'basis': 'veiled_band_type_unknown'}])
    assert sorted(hold_of(doc, 'Braton Riven Mod')) == ['name', 'reason']
    assert rl.est_for('vectis riven mod', {'owned_rivens': ESTS}) == (None, None)


# ---------------------------------------------------------------- cap + settings
def test_daily_listing_cap_is_respected(rl):
    """cap 1 keeps the highest expected value (8 x 7p) and holds the rest, deterministically."""
    doc = plan(rl, dict(SETTINGS, max_new_listings_per_day=1))
    assert [o['slug'] for o in doc['orders']] == ['melee_riven_mod_(veiled)']
    assert doc['summary'] == {'orders': 1, 'copies': 8, 'plan_plat': 56}
    assert doc['settings_echo']['cap'] == 1
    assert hold_of(doc, 'Kitgun Riven Mod (Veiled)')['reason'] == 'daily listing cap reached'


def test_cap_zero_plans_nothing(rl):
    doc = plan(rl, dict(SETTINGS, max_new_listings_per_day=0))
    assert doc['orders'] == [] and doc['summary']['plan_plat'] == 0


def test_junk_settings_fall_back_to_the_engine_defaults(rl):
    doc = plan(rl, {'undercut_platinum': 'junk', 'min_price_platinum': None,
                    'max_new_listings_per_day': 1.5})
    assert doc['settings_echo'] == {'undercut': 1, 'min_price': 3, 'cap': 20}
    assert rl.whole('4', 9) == 4 and rl.whole(True, 9) == 9 and rl.whole(None, 9) == 9


def test_settings_read_paths_never_raise(tmp_path, rl, monkeypatch):
    """settings.py when present (honours WFM_TRADER_SETTINGS), else the file next to the script."""
    monkeypatch.setenv('WFM_TRADER_SETTINGS', str(tmp_path / 'settings.json'))
    eff, err, exists = rl.load_settings()                     # missing file -> spec defaults
    assert (err, exists) == (None, False)
    assert eff['undercut_platinum'] == 1 and eff['max_new_listings_per_day'] == 20

    write_json(tmp_path / 'settings.json', dict(SETTINGS, max_new_listings_per_day=7))
    eff, err, exists = rl.load_settings()
    assert (eff['max_new_listings_per_day'], err, exists) == (7, None, True)

    monkeypatch.setattr(rl, '_SETTINGS_MOD', None)             # no settings.py -> direct read
    monkeypatch.setattr(rl, 'SETTINGS', str(tmp_path / 'settings.json'))
    assert rl.load_settings()[0]['max_new_listings_per_day'] == 7
    monkeypatch.setattr(rl, 'SETTINGS', str(tmp_path / 'nope.json'))
    assert rl.load_settings()[0] == rl.SETTINGS_DEFAULTS


def test_bare_and_junk_inputs_degrade(rl):
    """Empty / torn inputs give a valid dry-run document instead of raising."""
    doc = rl.build_plan({}, [], {}, {}, now=NOW)
    assert doc['orders'] == [] and doc['holds'] == []
    assert doc['settings_echo'] == {'undercut': 1, 'min_price': 3, 'cap': 20}
    assert rl.build_plan(None, None, None, None, now=NOW)['summary']['orders'] == 0


def test_selftest_passes(rl):
    """The module's own offline fixture checks stay green."""
    assert rl.selftest() == 0


# ---------------------------------------------------------------- run modes
def test_cli_writes_only_the_plan(tmp_path, rl, monkeypatch, capsys):
    """--plan writes data/riven_plan.json and touches nothing else; the table is printed."""
    code, data = run_cli(rl, monkeypatch, tmp_path)
    out = capsys.readouterr().out
    assert code == 0
    assert sorted(os.listdir(data)) == ['inuse.json', 'owned.json', 'riven_plan.json', 'rivens.json']
    doc = read_json(data / 'riven_plan.json')
    assert doc['mode'] == 'dry-run' and doc['summary'] == {'orders': 2, 'copies': 9, 'plan_plat': 59}
    assert {h['name']: h['reason'] for h in doc['holds']}['Rifle Riven Mod (Veiled)'] == \
        'all copies in use (equipped)'
    assert doc['settings_echo'] == {'undercut': 1, 'min_price': 3, 'cap': 20}
    assert 'riven listing plan' in out and 'summary: 2 orders | 9 copies | 59p plan value' in out
    assert 'plan written ->' in out and 'guardrails: undercut 1p, min 3p, cap 20' in out
    assert 'riven_plan.json.tmp' not in os.listdir(data)


def test_cli_bare_run_is_the_plan_action(tmp_path, rl, monkeypatch, capsys):
    code, data = run_cli(rl, monkeypatch, tmp_path, argv=[])
    assert code == 0 and (data / 'riven_plan.json').exists()
    assert 'summary: 2 orders' in capsys.readouterr().out


def test_cli_json_prints_json_only(tmp_path, rl, monkeypatch, capsys):
    """--json alone prints the document and writes nothing; --plan --json writes + prints JSON."""
    code, data = run_cli(rl, monkeypatch, tmp_path, argv=['--json'])
    out = capsys.readouterr().out
    assert code == 0
    assert sorted(os.listdir(data)) == ['inuse.json', 'owned.json', 'rivens.json']
    payload = out[out.index('{'):out.rindex('}') + 1]
    assert json.loads(payload)['summary'] == {'orders': 2, 'copies': 9, 'plan_plat': 59}
    assert 'riven listing plan' not in out and 'summary: 2 orders' not in out

    code, data = run_cli(rl, monkeypatch, tmp_path, argv=['--plan', '--json'])
    out = capsys.readouterr().out
    assert code == 0 and json.loads(out[out.index('{'):out.rindex('}') + 1])['mode'] == 'dry-run'
    assert read_json(data / 'riven_plan.json')['summary']['copies'] == 9
    assert 'plan written' not in out


def test_cli_missing_inputs_still_write_a_plan(tmp_path, rl, monkeypatch, capsys):
    """A data-less run reports the missing inputs and holds everything, without raising."""
    code, data = run_cli(rl, monkeypatch, tmp_path, files=False)
    out = capsys.readouterr().out
    assert code == 0
    doc = read_json(data / 'riven_plan.json')
    assert doc['orders'] == [] and doc['summary']['orders'] == 0
    assert 'rivens.json missing or unreadable' in out
    assert 'in-use data missing or unreadable' in out
    assert 'no order planned' in out


def test_killswitch_blocks_the_run(tmp_path, rl, monkeypatch, capsys):
    """Fail-open guard: an armed data/kill_switch.json stops the plan before anything is written."""
    assert rl._switch_engaged({'active': True}) is True
    assert rl._switch_engaged({'active': False}) is False
    assert rl._switch_engaged(None) is False and rl._switch_engaged('junk') is False
    code, data = run_cli(rl, monkeypatch, tmp_path, kill=True)
    out = capsys.readouterr().out
    assert code == 2 and 'kill switch engaged' in out
    assert not (data / 'riven_plan.json').exists()


def test_cli_end_to_end_in_subprocess(tmp_path):
    """A private copy of the script with its own scripts/trader + data (source never touched)."""
    root = tmp_path / 'harness'
    (root / 'scripts' / 'trader').mkdir(parents=True)
    shutil.copyfile(SRC, root / 'scripts' / 'trader' / 'riven_lister.py')   # no settings.py here
    write_json(root / 'scripts' / 'trader' / 'settings.json',
               dict(SETTINGS, max_new_listings_per_day=3))
    write_json(root / 'data' / 'rivens.json', {'veiled_bands': BANDS, 'owned_rivens': ESTS})
    write_json(root / 'data' / 'owned.json', OWNED)
    write_json(root / 'data' / 'inuse.json', INUSE)
    env = {k: v for k, v in os.environ.items() if not k.startswith('WFM_')}   # no ambient overrides
    res = subprocess.run([sys.executable, str(root / 'scripts' / 'trader' / 'riven_lister.py'),
                          '--plan'], cwd=str(root), env=env, capture_output=True, text=True,
                         timeout=120)
    assert res.returncode == 0, res.stderr
    assert 'guardrails: undercut 1p, min 3p, cap 3' in res.stdout
    assert sorted(os.listdir(root / 'data')) == ['inuse.json', 'owned.json', 'riven_plan.json',
                                                 'rivens.json']
    doc = read_json(root / 'data' / 'riven_plan.json')
    assert doc['settings_echo'] == {'undercut': 1, 'min_price': 3, 'cap': 3}
    assert doc['summary'] == {'orders': 2, 'copies': 9, 'plan_plat': 59}
    assert 'Rifle Riven Mod (Veiled)' not in [h['name'] for h in doc['orders']]
