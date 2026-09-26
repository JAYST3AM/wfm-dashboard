"""scripts/player.py: schema contract, RadioLegion exclusion, next_at maths, alias, CLI.

player.py reads PLAYER_SAVE / PLAYER_CATALOG / PLAYER_ALIAS / PLAYER_OUT from the environment
at import time, so the fixture loads it through those overrides (proving the documented env
hook works) and every path lands under tmp_path - the repo's real data/ directory is never
read or written, no network and no AlecaFrame file is ever touched.
"""
import json
import os
import re
import subprocess
import sys
from types import SimpleNamespace

import pytest

from conftest import load_script, read_json, write_json

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), 'scripts', 'player.py')

STORE_KEYS = ['schema', 'updated', 'updated_iso', 'alias', 'mastery', 'clan', 'syndicates',
              'intrinsics', 'focus', 'stats']
MASTERY_KEYS = {'rank', 'items_tracked', 'top_items'}
CLAN_KEYS = {'id', 'name_source', 'research_blueprints', 'vault_bonus'}
SYNDICATE_KEYS = {'tag', 'name', 'standing', 'title', 'next_at'}
STATS_KEYS = {'achievements_tracked', 'last_region', 'items_tracked', 'railjack_owned',
              'necramech_owned', 'daily_focus'}
SUMMARY_RE = re.compile(
    r'^player : MR (\d+|\?) \| clan (\w{8}|\?) \| syndicates \d+ \| intrinsics \d+ \| focus \d+$')

ALIAS_NAME = 'RoyalSpartanIIX'

BASE_CATALOG = {
    '/Lotus/Powersuits/Excalibur/Excalibur': {'name': 'Excalibur', 'pic': 'Excalibur.png'},
    '/Lotus/Weapons/Grineer/GrineerPistol/GrnScopedPistolPlayer': {'name': 'Kraken'},
    '/Lotus/Types/Sentinels/SentinelWeapons/PrimeLaserRifle': {'name': 'Prime Laser Rifle'},
}


@pytest.fixture
def pl(tmp_path, monkeypatch):
    """player.py loaded with every path redirected into tmp_path."""
    data = tmp_path / 'data'
    af = tmp_path / 'af'
    mod = load_script('player', monkeypatch=monkeypatch, env={
        'PLAYER_SAVE': str(data / 'lastData.dec.json'),
        'PLAYER_CATALOG': str(af / 'cachedData' / 'custom' / 'basic.json'),
        'PLAYER_ALIAS': str(af / 'lastUsername.txt'),
        'PLAYER_OUT': str(data / 'player.json')})
    monkeypatch.setattr(mod, 'AF', str(tmp_path / 'no_such_alecaframe'))
    return SimpleNamespace(mod=mod, tmp=tmp_path, save=data / 'lastData.dec.json',
                           out=data / 'player.json', catalog=af / 'cachedData' / 'custom' / 'basic.json',
                           alias=af / 'lastUsername.txt', af=af)


def base_save():
    """A small but complete save: every section the store reads."""
    return {
        'PlayerLevel': 22,
        'XPInfo': [
            {'ItemType': '/Lotus/Powersuits/Excalibur/Excalibur', 'XP': 14116270},
            {'ItemType': '/Lotus/Weapons/Grineer/GrineerPistol/GrnScopedPistolPlayer', 'XP': 3616611},
            {'ItemType': '/Lotus/Types/Sentinels/SentinelWeapons/PrimeLaserRifle', 'XP': 259862011},
            {'ItemType': '/Lotus/Types/Unknown/NotInCatalog', 'XP': 999},
        ],
        'ChallengeProgress': [{'Progress': 1, 'Name': 'Apply4Mods'},
                              {'Progress': 5, 'Name': 'BladeMastery1'}],
        'PlayerSkills': {'LPS_TACTICAL': 1, 'LPS_PILOTING': 2, 'LPS_GUNNERY': 2,
                         'LPS_ENGINEERING': 3, 'LPS_COMMAND': 5, 'LPP_SPACE': 82360,
                         'LPS_DRIFT_RIDING': 2, 'LPS_DRIFT_COMBAT': 4,
                         'LPS_DRIFT_OPPORTUNITY': 8, 'LPP_DRIFTER': 272000},
        'FocusXP': {'AP_TACTIC': 6273, 'AP_POWER': 166820, 'AP_DEFENSE': 168856},
        'DailyFocus': 348389,
        'GuildId': {'$oid': '60d1ec9db8459d6656697a46'},
        'WeeklyGuildVaultBonusProgress': [{'Progress': 399, 'WeekCount': 658}],
        'LastRegionPlayed': 'SolarMapDeimosName',
        'Recipes': [{'ItemCount': 1, 'ItemType': '/Lotus/Weapons/ClanTech/Energy/CrpBFGBlueprint'},
                    {'ItemCount': 1, 'ItemType': '/Lotus/Weapons/ClanTech/Bio/InfestedWhipWeaponBlueprint'},
                    {'ItemCount': 1, 'ItemType': '/Lotus/Types/Recipes/WarframeRecipes/AshBlueprint'}],
        'Affiliations': [
            {'Tag': 'RedVeilSyndicate', 'Standing': 88991, 'Title': 3, 'Initiated': True},
            {'Tag': 'ArbitersSyndicate', 'Standing': -71000, 'Title': -2},
            {'Tag': 'CetusSyndicate', 'Standing': 43676, 'Title': 2},
            {'Tag': 'ConclaveSyndicate', 'Standing': 5000, 'Title': 1, 'Initiated': True},
            {'Tag': 'NewLokaSyndicate', 'Standing': 372000, 'Title': 5, 'Initiated': True},
            {'Tag': 'RadioLegionSyndicate', 'Standing': 8450},
            {'Tag': 'RadioLegion3Syndicate', 'Standing': 5650},
            {'Tag': 'RadioLegionIntermission11Syndicate', 'Standing': 155500, 'Title': 14},
            {'Tag': 'MadeUpSyndicate', 'Standing': 10},
        ],
        'CrewShips': [{'ItemType': '/Lotus/Types/Game/CrewShip/Ships/RailJack'}],
        'MechSuits': [{'ItemType': '/Lotus/Powersuits/EntratiMech/NechroTech'}],
    }


def seed(pl, save=None, catalog=None, alias=ALIAS_NAME):
    """Fixture save + catalog (+ alias file); returns the save for convenience."""
    save = base_save() if save is None else save
    write_json(pl.save, save)
    write_json(pl.catalog, {'items': BASE_CATALOG if catalog is None else catalog})
    if alias is not None:
        pl.alias.parent.mkdir(parents=True, exist_ok=True)
        with open(pl.alias, 'w', encoding='utf-8') as fh:
            fh.write('\ufeff' + alias + '\n')          # the real file starts with a BOM
    return save


def run(pl, argv=None):
    return pl.mod.main(argv or [])


def doc_of(pl, argv=None):
    assert run(pl, argv) == 0
    return read_json(pl.out)


# ------------------------------------------------------------------ env override / loading

def test_env_paths_override_repo_data(pl):
    assert pl.mod.SAVE == str(pl.save)
    assert pl.mod.CATALOG == str(pl.catalog)
    assert pl.mod.ALIAS_PATH == str(pl.alias)
    assert pl.mod.OUT == str(pl.out)
    for p in (pl.mod.SAVE, pl.mod.CATALOG, pl.mod.ALIAS_PATH, pl.mod.OUT):
        assert p.startswith(str(pl.tmp))          # nothing points at the repo's real data/


def test_missing_save_degrades_to_empty_document_not_a_traceback(pl, capsys):
    """No save at all: still a clean, complete document - never a traceback."""
    assert run(pl) == 0
    out = capsys.readouterr().out
    assert SUMMARY_RE.match(out.splitlines()[0])
    doc = read_json(pl.out)                        # written, not skipped
    assert list(doc) == STORE_KEYS and doc['schema'] == 1
    assert doc['alias'] is None
    assert doc['mastery'] == {'rank': None, 'items_tracked': 0, 'top_items': []}
    assert doc['clan'] == {'id': None, 'name_source': 'config', 'research_blueprints': None,
                           'vault_bonus': None}
    assert doc['syndicates'] == [] and doc['focus'] == []
    assert doc['intrinsics'] == {'railjack': {'pilotting': None, 'gunnery': None,
                                              'engineering': None, 'tactical': None,
                                              'command': None, 'xp': None},
                                 'drifter': {'riding': None, 'combat': None, 'opportunity': None,
                                             'xp': None}}
    assert doc['stats'] == {'achievements_tracked': 0, 'last_region': None, 'items_tracked': 0,
                            'railjack_owned': False, 'necramech_owned': False, 'daily_focus': None}
    assert 'MR ?' in out.splitlines()[0]


# ------------------------------------------------------------------ store contract

def test_store_schema_keys_exact_and_row_types(pl):
    seed(pl)
    doc = doc_of(pl)
    assert list(doc) == STORE_KEYS and set(doc) == set(STORE_KEYS)
    assert doc['schema'] == 1
    assert isinstance(doc['updated'], int) and doc['updated'] > 1_600_000_000
    assert doc['updated_iso'].endswith('Z') and 'T' in doc['updated_iso']
    assert doc['alias'] == ALIAS_NAME
    assert list(doc['mastery']) == ['rank', 'items_tracked', 'top_items']
    assert set(doc['clan']) == CLAN_KEYS
    for row in doc['syndicates']:
        assert set(row) == SYNDICATE_KEYS
        assert isinstance(row['tag'], str) and isinstance(row['name'], str)
        assert row['standing'] is None or isinstance(row['standing'], int)
        assert row['title'] is None or isinstance(row['title'], int)
        assert row['next_at'] is None or isinstance(row['next_at'], int)
    assert list(doc['intrinsics']) == ['railjack', 'drifter']
    assert list(doc['intrinsics']['railjack']) == ['pilotting', 'gunnery', 'engineering',
                                                   'tactical', 'command', 'xp']
    assert list(doc['intrinsics']['drifter']) == ['riding', 'combat', 'opportunity', 'xp']
    for row in doc['focus']:
        assert row['tag'] in ('AP_TACTIC', 'AP_POWER', 'AP_DEFENSE')
        assert isinstance(row['name'], str) and isinstance(row['xp'], int)
        assert 'guess' not in row                # every school mapping is verified
    assert set(doc['stats']) == STATS_KEYS


# ------------------------------------------------------------------ syndicates

def test_radiolegion_rows_excluded(pl):
    seed(pl)
    doc = doc_of(pl)
    tags = [r['tag'] for r in doc['syndicates']]
    assert not any(t.startswith('RadioLegion') for t in tags)
    assert tags == ['RedVeilSyndicate', 'ArbitersSyndicate', 'CetusSyndicate',
                    'ConclaveSyndicate', 'NewLokaSyndicate', 'MadeUpSyndicate']
    assert len(tags) == len(base_save()['Affiliations']) - 3          # 3 RadioLegion rows dropped


def test_syndicate_names_verified_and_unknown_tag_kept_raw(pl):
    seed(pl)
    names = {r['tag']: r['name'] for r in doc_of(pl)['syndicates']}
    assert names['RedVeilSyndicate'] == 'Red Veil'
    assert names['ArbitersSyndicate'] == 'Arbiters of Hexis'
    assert names['CetusSyndicate'] == 'Ostron'
    assert names['ConclaveSyndicate'] == 'Conclave'
    assert names['NewLokaSyndicate'] == 'New Loka'
    assert names['MadeUpSyndicate'] == 'MadeUpSyndicate'   # never guesses a name


def test_next_at_between_thresholds_and_negative(pl):
    nt = pl.mod.next_threshold
    assert nt(43676) == 44000                 # Cetus: between 22000 and 44000
    assert nt(88991) == 99000                 # Red Veil: between 70000 and 99000
    assert nt(0) == 5000 and nt(5000) == 22000
    assert nt(99000) is None and nt(372000) is None     # maxed at the top rung
    assert nt(-71000) == -70000               # negative standing -> next rung above
    assert nt(-3000) == 0 and nt(-22000) == -5000
    assert nt(-99000) is None and nt(-150000) is None   # maxed at the bottom rung
    assert nt(None) is None

    seed(pl)
    rows = {r['tag']: r for r in doc_of(pl)['syndicates']}
    assert rows['CetusSyndicate']['next_at'] == 44000
    assert rows['RedVeilSyndicate']['next_at'] == 99000
    assert rows['ArbitersSyndicate'] == {'tag': 'ArbitersSyndicate', 'name': 'Arbiters of Hexis',
                                         'standing': -71000, 'title': -2, 'next_at': -70000}
    assert rows['NewLokaSyndicate']['next_at'] is None and rows['NewLokaSyndicate']['standing'] == 372000
    assert rows['MadeUpSyndicate']['next_at'] == 5000      # standing 10 -> next rung is 5000


def test_syndicates_empty_when_the_save_has_none(pl):
    seed(pl, save={})
    assert doc_of(pl)['syndicates'] == []


# ------------------------------------------------------------------ intrinsics / focus

def test_intrinsics_mapping_from_player_skills(pl):
    seed(pl)
    doc = doc_of(pl)
    assert doc['intrinsics'] == {
        'railjack': {'pilotting': 2, 'gunnery': 2, 'engineering': 3, 'tactical': 1,
                     'command': 5, 'xp': 82360},
        'drifter': {'riding': 2, 'combat': 4, 'opportunity': 8, 'xp': 272000}}
    # a skill the save does not carry stays null, never 0
    seed(pl, save=dict(base_save(), PlayerSkills={'LPS_PILOTING': 7, 'LPP_SPACE': 1234}))
    doc = doc_of(pl)
    assert doc['intrinsics']['railjack']['pilotting'] == 7
    assert doc['intrinsics']['railjack']['xp'] == 1234
    assert doc['intrinsics']['railjack']['gunnery'] is None
    assert doc['intrinsics']['drifter'] == {'riding': None, 'combat': None, 'opportunity': None,
                                            'xp': None}


def test_focus_rows_sorted_desc_with_verified_school_names(pl):
    seed(pl)
    doc = doc_of(pl)
    assert [(r['tag'], r['name'], r['xp']) for r in doc['focus']] == [
        ('AP_DEFENSE', 'Vazarin', 168856),
        ('AP_POWER', 'Zenurik', 166820),
        ('AP_TACTIC', 'Naramon', 6273)]
    # an unmapped tag keeps the raw tag and is flagged as a guess
    seed(pl, save=dict(base_save(), FocusXP={'AP_TACTIC': 10, 'AP_MYSTERY': 99}))
    doc = doc_of(pl)
    assert doc['focus'][0] == {'tag': 'AP_MYSTERY', 'name': 'AP_MYSTERY', 'xp': 99, 'guess': True}
    assert doc['focus'][1] == {'tag': 'AP_TACTIC', 'name': 'Naramon', 'xp': 10}


# ------------------------------------------------------------------ mastery

def test_mastery_items_tracked_and_top_items(pl):
    seed(pl)
    doc = doc_of(pl)
    assert doc['mastery']['rank'] == 22 and doc['mastery']['items_tracked'] == 4
    assert doc['mastery']['items_tracked'] == len(base_save()['XPInfo'])
    assert doc['mastery']['top_items'] == [
        {'name': 'Prime Laser Rifle', 'xp': 259862011},
        {'name': 'Excalibur', 'xp': 14116270},
        {'name': 'Kraken', 'xp': 3616611},
        {'name': None, 'xp': 999}]            # not in basic.json -> null, never invented
    assert doc['stats']['items_tracked'] == doc['mastery']['items_tracked']


def test_top_items_capped_at_five(pl):
    save = dict(base_save(), XPInfo=[{'ItemType': '/x/%d' % i, 'XP': i} for i in range(9)])
    seed(pl, save=save, catalog={'/x/%d' % i: {'name': 'Thing %d' % i} for i in range(9)})
    doc = doc_of(pl)
    assert len(doc['mastery']['top_items']) == 5
    assert [r['name'] for r in doc['mastery']['top_items']] == [
        'Thing 8', 'Thing 7', 'Thing 6', 'Thing 5', 'Thing 4']
    assert doc['mastery']['items_tracked'] == 9


def test_mastery_rank_is_playerlevel_not_lifetime_xp(pl):
    """XPInfo sums are absurd next to the rank - rank must come from PlayerLevel only."""
    seed(pl)
    doc = doc_of(pl)
    total_xp = sum(r['xp'] for r in doc['mastery']['top_items'])
    assert doc['mastery']['rank'] == 22 and total_xp > 22
    seed(pl, save=dict(base_save(), PlayerLevel=None))
    assert doc_of(pl)['mastery']['rank'] is None


# ------------------------------------------------------------------ clan / stats

def test_clan_block(pl):
    seed(pl)
    clan = doc_of(pl)['clan']
    assert clan['id'] == '60d1ec9db8459d6656697a46'
    assert clan['name_source'] == 'config'          # the UI reads the name from config
    assert clan['research_blueprints'] == 2         # the two ClanTech recipes
    assert clan['vault_bonus'] == {'progress': 399, 'week_count': 658}
    # plain-string guild ids and missing vault rows are handled without inventing fields
    seed(pl, save=dict(base_save(), GuildId='abc123', WeeklyGuildVaultBonusProgress=[]))
    clan = doc_of(pl)['clan']
    assert clan['id'] == 'abc123' and clan['vault_bonus'] is None


def test_stats_block(pl):
    seed(pl)
    stats = doc_of(pl)['stats']
    assert stats['achievements_tracked'] == 2 == len(base_save()['ChallengeProgress'])
    assert stats['last_region'] == 'Deimos'
    assert stats['railjack_owned'] is True and stats['necramech_owned'] is True
    assert stats['daily_focus'] == 348389
    # regions the verified map lacks fall back to a camel-case split, then the raw string
    assert pl.mod.region_label('SolarMapKuvaFortressName') == 'Kuva Fortress'
    assert pl.mod.region_label('CambionDrift') == 'CambionDrift'
    assert pl.mod.region_label(None) is None and pl.mod.region_label('  ') is None
    # ownership booleans need evidence: empty or absent sections are false, not null
    seed(pl, save=dict(base_save(), CrewShips=[], MechSuits=[]))
    stats = doc_of(pl)['stats']
    assert stats['railjack_owned'] is False and stats['necramech_owned'] is False


# ------------------------------------------------------------------ alias

def test_alias_is_trimmed_and_null_when_missing(pl):
    assert pl.mod.read_alias(str(pl.alias)) is None                 # file absent
    pl.alias.parent.mkdir(parents=True, exist_ok=True)
    with open(pl.alias, 'w', encoding='utf-8') as fh:
        fh.write('\ufeff  RoyalSpartanIIX  \n')                    # BOM + padding, like the real file
    assert pl.mod.read_alias(str(pl.alias)) == 'RoyalSpartanIIX'
    with open(pl.alias, 'w', encoding='utf-8') as fh:
        fh.write('   \n')                                          # whitespace only -> null
    assert pl.mod.read_alias(str(pl.alias)) is None
    seed(pl)                                                       # absent file: doc alias is null
    os.remove(str(pl.alias))
    assert doc_of(pl)['alias'] is None
    seed(pl)                                                       # present: trimmed name in the doc
    assert doc_of(pl)['alias'] == ALIAS_NAME


# ------------------------------------------------------------------ decrypt path

def test_save_is_decrypted_from_lastdata_dat_when_absent(pl, monkeypatch):
    pytest.importorskip('cryptography')
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    af = pl.tmp / 'fake_af'
    af.mkdir()
    payload = json.dumps(base_save()).encode('utf-8')
    pad = padding.PKCS7(128).padder()
    body = pad.update(payload) + pad.finalize()
    enc = Cipher(algorithms.AES(pl.mod.KEY), modes.CBC(pl.mod.IV)).encryptor()
    (af / 'lastData.dat').write_bytes(enc.update(body) + enc.finalize())
    monkeypatch.setattr(pl.mod, 'AF', str(af))
    write_json(pl.catalog, {'items': BASE_CATALOG})

    assert run(pl) == 0                                        # no lastData.dec.json exists
    doc = read_json(pl.out)
    assert doc['mastery']['rank'] == 22 and doc['syndicates'][0]['tag'] == 'RedVeilSyndicate'
    assert pl.mod.KEY == bytes([76, 69, 79, 45, 65, 76, 69, 67, 9, 69, 79, 45, 65, 76, 69, 67])
    assert pl.mod.IV == bytes([49, 50, 70, 71, 66, 51, 54, 45, 76, 69, 51, 45, 113, 61, 57, 0])


# ------------------------------------------------------------------ CLI

def test_summary_line_first(pl, capsys):
    seed(pl)
    assert run(pl) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == 'player : MR 22 | clan 60d1ec9d | syndicates 6 | intrinsics 8 | focus 3'
    assert lines[1].startswith('store : ')


def test_dry_run_prints_the_plan_and_writes_nothing(pl, capsys):
    seed(pl)
    assert run(pl, ['--dry-run']) == 0
    out = capsys.readouterr().out
    assert SUMMARY_RE.match(out.splitlines()[0])
    assert 'plan :' in out and 'dry-run' in out
    assert not pl.out.exists()                                 # nothing written


def test_out_flag_writes_elsewhere(pl, capsys):
    seed(pl)
    custom = pl.tmp / 'elsewhere' / 'profile.json'
    assert run(pl, ['--out', str(custom)]) == 0
    assert read_json(custom)['mastery']['rank'] == 22
    assert not pl.out.exists()                                 # default store untouched
    assert f'store : {pl.mod.rel(str(custom))}' in capsys.readouterr().out


def test_json_flag_prints_the_store(pl, capsys):
    seed(pl)
    assert run(pl, ['--json']) == 0
    payload = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith('{')]
    assert len(payload) == 1
    assert json.loads(payload[0]) == read_json(pl.out)


def test_selftest_is_offline_and_exits_zero(tmp_path, monkeypatch, capsys):
    mod = load_script('player', monkeypatch=monkeypatch, env={
        'PLAYER_SAVE': str(tmp_path / 'nope' / 'lastData.dec.json'),
        'PLAYER_CATALOG': str(tmp_path / 'nope' / 'basic.json'),
        'PLAYER_ALIAS': str(tmp_path / 'nope' / 'lastUsername.txt'),
        'PLAYER_OUT': str(tmp_path / 'nope' / 'player.json')})
    assert mod.main(['--selftest']) == 0                       # no save, no catalog, still fine
    out = capsys.readouterr().out
    assert 'selftest : ok' in out and 'no network' in out
    assert os.listdir(str(tmp_path)) == []                     # everything lived in its own tmp dir


def test_selftest_subprocess_without_alecaframe(tmp_path):
    env = dict(os.environ, LOCALAPPDATA=str(tmp_path / 'empty_af'))
    r = subprocess.run([sys.executable, SCRIPT, '--selftest'], cwd=str(tmp_path), env=env,
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'selftest : ok' in r.stdout
