#!/usr/bin/env python3
r"""Player profile store: AlecaFrame save + local dashboard data -> data/player.json.

Inputs (read-only)
    data/lastData.dec.json                                   decrypted save (written by refresh.py)
    %LOCALAPPDATA%\AlecaFrame\lastData.dat                    decrypted here when the above is missing
    %LOCALAPPDATA%\AlecaFrame\lastUsername.txt               in-game alias, one line (UTF-8 BOM tolerated)
    %LOCALAPPDATA%\AlecaFrame\cachedData\custom\basic.json   item catalog, dict 'items':
                                                             uniqueName -> {name, pic, wiki}

Output
    data/player.json    profile store for the Player page (schema 1)

Store (keys literal; built by build_doc)
    schema, updated, updated_iso, alias,
    mastery    {rank, items_tracked, top_items[{name, xp} x5]},
    clan       {id, name_source, research_blueprints, vault_bonus {progress, week_count}|null},
    syndicates [{tag, name, standing, title, next_at}],
    intrinsics {railjack {pilotting, gunnery, engineering, tactical, command, xp},
                drifter {riding, combat, opportunity, xp}},
    focus      [{tag, name, xp}],
    stats      {achievements_tracked, last_region, items_tracked, railjack_owned,
                necramech_owned, daily_focus}

Rules
  * never invent a value - a field whose source is absent is null (a len() of a missing
    section is 0, a boolean with no evidence is false);
  * mastery rank comes from PlayerLevel; XPInfo is lifetime affinity per item and is never
    summed into a rank (it only drives items_tracked + top_items);
  * tags starting with 'RadioLegion' are Nightwave noise and never reach the store;
  * syndicate tag -> display name: SYNDICATE_NAMES, every entry verified against the game's
    own localisation strings (warframe-public-export-plus dict.en.json, looked up on the
    key ExportSyndicates.json assigns to each tag) - an unknown tag keeps the raw tag;
  * focus AP_* -> school: FOCUS_SCHOOLS, verified the same way plus the wiki Focus data
    module (polarity AP_x sits only on /Lotus/Upgrades/Focus/<x>/ abilities, and Tactic =
    Naramon / Defense = Vazarin / Power = Zenurik there) - an unverified tag keeps the raw
    tag and its row carries guess: true;
  * next_at = the next standard syndicate rung above the current standing, from the wiki's
    syndicate Tiers table (0 / 5000 / 22000 / 44000 / 70000 / 99000 upward, mirrored below
    zero for the negative ranks); null at or past the top rung (99 000) or the bottom one;
  * a missing save never raises: the store degrades to a clean empty-ish document.

Offline: stdlib only, no network.  Env overrides for the test-suite: PLAYER_SAVE,
PLAYER_CATALOG, PLAYER_ALIAS, PLAYER_OUT.

CLI: --once (default) | --out PATH | --json | --dry-run | --selftest
Exit codes: 0 ok, 2 selftest failure.
"""
import argparse
import contextlib
import io
import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
AF = os.path.expandvars(r'%LOCALAPPDATA%\AlecaFrame')

KEY = bytes([76, 69, 79, 45, 65, 76, 69, 67, 9, 69, 79, 45, 65, 76, 69, 67])
IV = bytes([49, 50, 70, 71, 66, 51, 54, 45, 76, 69, 51, 45, 113, 61, 57, 0])

SAVE = os.environ.get('PLAYER_SAVE') or os.path.join(DATA, 'lastData.dec.json')
CATALOG = os.environ.get('PLAYER_CATALOG') or os.path.join(AF, 'cachedData', 'custom', 'basic.json')
ALIAS_PATH = os.environ.get('PLAYER_ALIAS') or os.path.join(AF, 'lastUsername.txt')
OUT = os.environ.get('PLAYER_OUT') or os.path.join(DATA, 'player.json')

SCHEMA = 1
TOP_ITEMS = 5

# Standard syndicate rungs (wiki Module:Syndicates/data "Tiers"): rank 1..5 cap the standing
# at 5000 / 22000 / 44000 / 70000 / 99000, mirrored negative for ranks -1..-5.
THRESHOLDS = (-99000, -70000, -44000, -22000, -5000, 0, 5000, 22000, 44000, 70000, 99000)
TOP_RUNG = 99000

SYNDICATE_NAMES = {
    'ArbitersSyndicate': 'Arbiters of Hexis',
    'CephalonSudaSyndicate': 'Cephalon Suda',
    'ConclaveSyndicate': 'Conclave',
    'CetusSyndicate': 'Ostron',
    'EntratiSyndicate': 'Entrati',
    'EntratiLabSyndicate': 'Cavia',
    'HexSyndicate': 'The Hex',
    'KahlSyndicate': "Kahl's Garrison",
    'LibrarySyndicate': 'Cephalon Simaris',
    'NecraloidSyndicate': 'Necraloid',
    'NewLokaSyndicate': 'New Loka',
    'NightcapJournalSyndicate': 'Nightcap',
    'PerrinSyndicate': 'The Perrin Sequence',
    'QuillsSyndicate': 'The Quills',
    'RedVeilSyndicate': 'Red Veil',
    'SolarisSyndicate': 'Solaris United',
    'SteelMeridianSyndicate': 'Steel Meridian',
    'VentKidsSyndicate': 'Ventkids',
    'VoxSyndicate': 'Vox Solaris',
    'ZarimanSyndicate': 'The Holdfasts',
}

FOCUS_SCHOOLS = {
    'AP_ATTACK': 'Madurai',
    'AP_DEFENSE': 'Vazarin',
    'AP_POWER': 'Zenurik',
    'AP_TACTIC': 'Naramon',
    'AP_WARD': 'Unairu',
}

# schema key (literal) -> PlayerSkills tag; xp comes from the matching LPP_ lifetime pool
RAILJACK_KEYS = (('pilotting', 'LPS_PILOTING'), ('gunnery', 'LPS_GUNNERY'),
                 ('engineering', 'LPS_ENGINEERING'), ('tactical', 'LPS_TACTICAL'),
                 ('command', 'LPS_COMMAND'))
DRIFTER_KEYS = (('riding', 'LPS_DRIFT_RIDING'), ('combat', 'LPS_DRIFT_COMBAT'),
                ('opportunity', 'LPS_DRIFT_OPPORTUNITY'))
RAILJACK_XP = 'LPP_SPACE'
DRIFTER_XP = 'LPP_DRIFTER'

# Verified against the game's localisation dict (the only SolarMap*Name region keys it has).
REGION_NAMES = {
    'SolarMapDeimosName': 'Deimos',
    'SolarMapDeimosLandscapeName': 'Cambion Drift',
    'SolarMapDeimosHubName': 'Necralisk',
}
REGION_RE = re.compile(r'^SolarMap(.+)Name$')


def decrypt(p):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    raw = open(p, 'rb').read()
    if raw[:1] == b'{':
        return raw  # plaintext fallback path the app itself supports
    d = Cipher(algorithms.AES(KEY), modes.CBC(IV)).decryptor()
    pt = d.update(raw) + d.finalize()
    pad = pt[-1]
    if 1 <= pad <= 16 and pt[-pad:] == bytes([pad]) * pad:
        pt = pt[:-pad]
    return pt


def load_save(path):
    """(save, source): the decrypted copy, a local decrypt of lastData.dat, or ({}, 'missing')."""
    if path and os.path.exists(path):
        with open(path, encoding='utf-8') as fh:
            doc = json.load(fh)
        return (doc if isinstance(doc, dict) else {}), 'decrypted'
    dat = os.path.join(AF, 'lastData.dat')
    if os.path.exists(dat):
        doc = json.loads(decrypt(dat).decode('utf-8'))
        return (doc if isinstance(doc, dict) else {}), 'lastData.dat'
    return {}, 'missing'


def load_catalog(path):
    """uniqueName -> {name, pic, wiki} from basic.json; {} when absent or unreadable."""
    try:
        with open(path, encoding='utf-8') as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return {}
    items = doc.get('items') if isinstance(doc, dict) else None
    return items if isinstance(items, dict) else {}


def read_alias(path):
    """The in-game alias from lastUsername.txt, trimmed; None when absent or empty."""
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding='utf-8-sig') as fh:      # the file starts with a BOM
            value = fh.read().strip()
    except OSError:
        return None
    return value or None


def int_or_none(value):
    """The value when it is a real int (bools are not), else None."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def tup_or_none(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def section_has_item(save, section):
    """True when a save section holds at least one entry with an ItemType."""
    rows = save.get(section)
    return any(isinstance(e, dict) and isinstance(e.get('ItemType'), str) and e['ItemType']
               for e in rows) if isinstance(rows, list) else False


def next_threshold(standing):
    """The next standard rung above the standing; None when unknown or already maxed."""
    if standing is None:
        return None
    if standing >= TOP_RUNG or standing <= -TOP_RUNG:
        return None
    for rung in THRESHOLDS:
        if rung > standing:
            return rung
    return None


def region_label(raw):
    """'SolarMapDeimosName' -> 'Deimos'; verified map first, then a camel-case split."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    value = raw.strip()
    if value in REGION_NAMES:
        return REGION_NAMES[value]
    m = REGION_RE.match(value)
    if m:
        return re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', m.group(1)) or value
    return value


def build_mastery(save, items):
    """{rank, items_tracked, top_items} - PlayerLevel for the rank, XPInfo for the rest."""
    rows = save.get('XPInfo') if isinstance(save.get('XPInfo'), list) else []
    xp = [e for e in rows if isinstance(e, dict) and isinstance(e.get('ItemType'), str)
          and tup_or_none(e.get('XP')) is not None]
    top_items = []
    for e in sorted(xp, key=lambda e: (-e['XP'], e['ItemType']))[:TOP_ITEMS]:
        entry = items.get(e['ItemType'])
        top_items.append(dict(name=entry.get('name') or None if isinstance(entry, dict) else None,
                              xp=e['XP']))
    return dict(rank=int_or_none(save.get('PlayerLevel')), items_tracked=len(rows),
                top_items=top_items)


def build_clan(save):
    """{id, name_source, research_blueprints, vault_bonus}; the name itself lives in config."""
    guild = save.get('GuildId')
    if isinstance(guild, dict):
        guild = guild.get('$oid')
    clan_id = guild if isinstance(guild, str) and guild else None
    recipes = save.get('Recipes')
    research = None
    if isinstance(recipes, list):
        research = sum(1 for e in recipes if isinstance(e, dict)
                       and 'ClanTech' in str(e.get('ItemType') or ''))
    vault = None
    rows = save.get('WeeklyGuildVaultBonusProgress')
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        vault = dict(progress=int_or_none(rows[0].get('Progress')),
                     week_count=int_or_none(rows[0].get('WeekCount')))
    return dict(id=clan_id, name_source='config', research_blueprints=research, vault_bonus=vault)


def build_syndicates(save):
    """[{tag, name, standing, title, next_at}] - Nightwave (RadioLegion*) rows excluded."""
    rows = save.get('Affiliations') if isinstance(save.get('Affiliations'), list) else []
    out = []
    for e in rows:
        if not isinstance(e, dict):
            continue
        tag = e.get('Tag')
        if not isinstance(tag, str) or not tag or tag.startswith('RadioLegion'):
            continue
        standing = int_or_none(e.get('Standing'))
        out.append(dict(tag=tag, name=SYNDICATE_NAMES.get(tag, tag), standing=standing,
                        title=int_or_none(e.get('Title')), next_at=next_threshold(standing)))
    return out


def build_intrinsics(save):
    """{railjack, drifter} - rank per PlayerSkills LPS_* tag, xp from the LPP_* pools."""
    skills = save.get('PlayerSkills') if isinstance(save.get('PlayerSkills'), dict) else {}

    def level(tag):
        return int_or_none(skills.get(tag))

    railjack = {name: level(tag) for name, tag in RAILJACK_KEYS}
    railjack['xp'] = level(RAILJACK_XP)
    drifter = {name: level(tag) for name, tag in DRIFTER_KEYS}
    drifter['xp'] = level(DRIFTER_XP)
    return dict(railjack=railjack, drifter=drifter)


def build_focus(save):
    """[{tag, name, xp}] sorted by xp desc; unverified tags carry guess: true."""
    xp = save.get('FocusXP') if isinstance(save.get('FocusXP'), dict) else {}
    rows = []
    for tag, value in xp.items():
        if not isinstance(tag, str) or not tag:
            continue
        row = dict(tag=tag, name=FOCUS_SCHOOLS.get(tag, tag), xp=tup_or_none(value))
        if tag not in FOCUS_SCHOOLS:
            row['guess'] = True
        rows.append(row)
    rows.sort(key=lambda r: (r['xp'] is None, -(r['xp'] or 0), r['tag']))
    return rows


def build_stats(save):
    """{achievements_tracked, last_region, items_tracked, railjack_owned, necramech_owned,
    daily_focus} - lengths of a missing section are 0, bools with no evidence are false."""
    challenges = save.get('ChallengeProgress')
    xp = save.get('XPInfo')
    return dict(achievements_tracked=len(challenges) if isinstance(challenges, list) else 0,
                last_region=region_label(save.get('LastRegionPlayed')),
                items_tracked=len(xp) if isinstance(xp, list) else 0,
                railjack_owned=section_has_item(save, 'CrewShips'),
                necramech_owned=section_has_item(save, 'MechSuits'),
                daily_focus=int_or_none(save.get('DailyFocus')))


def build_doc(save, items=None, alias=None, now=None):
    """The whole data/player.json document (keys literal, in the documented order)."""
    items = items or {}
    now = int(time.time()) if now is None else int(now)
    return dict(schema=SCHEMA,
                updated=now,
                updated_iso=datetime.fromtimestamp(now, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                alias=alias,
                mastery=build_mastery(save, items),
                clan=build_clan(save),
                syndicates=build_syndicates(save),
                intrinsics=build_intrinsics(save),
                focus=build_focus(save),
                stats=build_stats(save))


def rel(p):
    """Repo-relative display path; absolute when the store lives on another drive."""
    try:
        return os.path.relpath(p, ROOT).replace('\\', '/')
    except ValueError:
        return p.replace('\\', '/')


def save_json(path, obj):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, separators=(',', ':'))
    os.replace(tmp, path)


def intrinsic_count(doc):
    """Ranked intrinsic skills held (xp pools excluded) - the summary line's number."""
    intr = doc['intrinsics']
    return sum(1 for section in ('railjack', 'drifter')
               for key, value in intr[section].items() if key != 'xp' and value is not None)


def summary_line(doc):
    """'player : MR 22 | clan 60d1ec9d | syndicates 18 | intrinsics 8 | focus 3'."""
    rank = doc['mastery']['rank']
    clan_id = doc['clan']['id'] or ''
    return ('player : MR %s | clan %s | syndicates %d | intrinsics %d | focus %d'
            % (rank if rank is not None else '?', clan_id[:8] or '?',
               len(doc['syndicates']), intrinsic_count(doc), len(doc['focus'])))


# ------------------------------------------------------------------ selftest

SELFTEST_ALIAS = 'TestTenno'
SELFTEST_SAVE = dict(
    PlayerLevel=22,
    XPInfo=[dict(ItemType='/Lotus/Powersuits/Excalibur/Excalibur', XP=14116270),
            dict(ItemType='/Lotus/Weapons/Grineer/GrineerPistol/GrnScopedPistolPlayer', XP=3616611),
            dict(ItemType='/Lotus/Types/Unknown/NotInCatalog', XP=999)],
    ChallengeProgress=[dict(Progress=1, Name='Apply4Mods')] * 3,
    PlayerSkills=dict(LPS_TACTICAL=1, LPS_PILOTING=2, LPS_GUNNERY=2, LPS_ENGINEERING=3,
                      LPS_COMMAND=5, LPP_SPACE=82360, LPS_DRIFT_RIDING=2, LPS_DRIFT_COMBAT=4,
                      LPS_DRIFT_OPPORTUNITY=8, LPP_DRIFTER=272000),
    FocusXP=dict(AP_TACTIC=6273, AP_POWER=166820, AP_DEFENSE=168856),
    DailyFocus=348389,
    GuildId=dict({'$oid': '60d1ec9db8459d6656697a46'}),
    WeeklyGuildVaultBonusProgress=[dict(Progress=399, WeekCount=658)],
    LastRegionPlayed='SolarMapDeimosName',
    Recipes=[dict(ItemCount=1, ItemType='/Lotus/Weapons/ClanTech/Energy/CrpBFGBlueprint'),
             dict(ItemCount=1, ItemType='/Lotus/Types/Recipes/WarframeRecipes/AshBlueprint')],
    Affiliations=[dict(Tag='RedVeilSyndicate', Standing=88991, Title=3),
                  dict(Tag='ArbitersSyndicate', Standing=-71000, Title=-2),
                  dict(Tag='RadioLegionSyndicate', Standing=8450),
                  dict(Tag='RadioLegionIntermission3Syndicate', Standing=117500, Title=11)],
    CrewShips=[dict(ItemType='/Lotus/Types/Game/CrewShip/Ships/RailJack')],
    MechSuits=[dict(ItemType='/Lotus/Powersuits/EntratiMech/NechroTech')],
)
SELFTEST_CATALOG = dict(items={
    '/Lotus/Powersuits/Excalibur/Excalibur': dict(name='Excalibur', pic='Excalibur.png'),
    '/Lotus/Weapons/Grineer/GrineerPistol/GrnScopedPistolPlayer': dict(name='Kraken'),
})


def selftest():
    """Offline fixture run in a scratch dir: no AlecaFrame, no network, tmp files only."""
    checks = []

    def ok(cond, what):
        if not cond:
            raise AssertionError(what)
        checks.append(what)

    try:
        with tempfile.TemporaryDirectory(prefix='player_selftest_') as td:
            save_path = os.path.join(td, 'lastData.dec.json')
            catalog_path = os.path.join(td, 'basic.json')
            alias_path = os.path.join(td, 'lastUsername.txt')
            out_path = os.path.join(td, 'player.json')
            save_json(save_path, SELFTEST_SAVE)
            save_json(catalog_path, SELFTEST_CATALOG)
            open(alias_path, 'w', encoding='utf-8').write('\ufeff  ' + SELFTEST_ALIAS + '  \n')

            save, source = load_save(save_path)
            ok(source == 'decrypted' and save['PlayerLevel'] == 22, 'fixture save loaded')

            # decrypt() plaintext fallback + AES round-trip via the refresh.py KEY/IV
            plain = os.path.join(td, 'plain.dat')
            open(plain, 'wb').write(b'{"PlayerLevel": 22}')
            ok(decrypt(plain) == b'{"PlayerLevel": 22}', 'decrypt() passes plaintext through')
            try:
                from cryptography.hazmat.primitives import padding
                from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
                enc = os.path.join(td, 'lastData.dat')
                pad = padding.PKCS7(128).padder()
                body = pad.update(json.dumps(SELFTEST_SAVE).encode('utf-8')) + pad.finalize()
                e = Cipher(algorithms.AES(KEY), modes.CBC(IV)).encryptor()
                open(enc, 'wb').write(e.update(body) + e.finalize())
                ok(json.loads(decrypt(enc).decode('utf-8')) == SELFTEST_SAVE,
                   'decrypt() AES-128-CBC round-trip with the refresh.py KEY/IV')
            except ImportError:
                pass  # cryptography absent: the plaintext fallback above still ran

            items = load_catalog(catalog_path)
            alias = read_alias(alias_path)
            ok(alias == SELFTEST_ALIAS, 'alias trimmed (BOM + trailing whitespace)')
            ok(read_alias(os.path.join(td, 'missing.txt')) is None, 'missing alias file -> null')

            doc = build_doc(save, items, alias, now=1700000000)
            ok(list(doc) == ['schema', 'updated', 'updated_iso', 'alias', 'mastery', 'clan',
                             'syndicates', 'intrinsics', 'focus', 'stats'], 'store keys exact')
            ok(doc['schema'] == 1 and doc['updated'] == 1700000000
               and doc['updated_iso'].endswith('Z'), 'timestamps')
            ok(doc['alias'] == SELFTEST_ALIAS, 'alias carried into the store')
            ok(doc['mastery']['rank'] == 22 and doc['mastery']['items_tracked'] == 3,
               'mastery rank + items_tracked from the save')
            ok([r['name'] for r in doc['mastery']['top_items']] == ['Excalibur', 'Kraken', None],
               'top_items sorted by xp, uncatalogued name -> null')
            ok(doc['mastery']['top_items'][0]['xp'] == 14116270, 'top item xp kept')
            ok(doc['clan'] == dict(id='60d1ec9db8459d6656697a46', name_source='config',
                                   research_blueprints=1,
                                   vault_bonus=dict(progress=399, week_count=658)),
               'clan block (id, ClanTech count, vault bonus)')
            ok([r['tag'] for r in doc['syndicates']] == ['RedVeilSyndicate', 'ArbitersSyndicate'],
               'RadioLegion rows excluded')
            ok(doc['syndicates'][0]['next_at'] == 99000, 'next_at between rungs (88991 -> 99000)')
            ok(doc['syndicates'][1]['next_at'] == -70000, 'next_at for a negative standing')
            ok(doc['intrinsics']['railjack'] == dict(pilotting=2, gunnery=2, engineering=3,
                                                     tactical=1, command=5, xp=82360),
               'railjack intrinsics mapped from PlayerSkills')
            ok(doc['intrinsics']['drifter'] == dict(riding=2, combat=4, opportunity=8, xp=272000),
               'drifter intrinsics mapped from PlayerSkills')
            ok([r['name'] for r in doc['focus']] == ['Vazarin', 'Zenurik', 'Naramon'],
               'focus sorted by xp with verified school names')
            ok(all('guess' not in r for r in doc['focus']), 'no guess flag on verified schools')
            ok(doc['stats'] == dict(achievements_tracked=3, last_region='Deimos', items_tracked=3,
                                    railjack_owned=True, necramech_owned=True, daily_focus=348389),
               'stats block (region label, ownership bools)')
            ok(summary_line(doc) == 'player : MR 22 | clan 60d1ec9d | syndicates 2'
               ' | intrinsics 8 | focus 3', 'summary line format')

            save_json(out_path, doc)
            ok(json.load(open(out_path, encoding='utf-8')) == doc, 'store written to the tmp dir only')

            # CLI contract: dry-run writes nothing even with fixtures wired up
            globals_ = globals()
            keep = {k: globals_[k] for k in ('SAVE', 'CATALOG', 'ALIAS_PATH', 'OUT')}
            try:
                globals_.update(SAVE=save_path, CATALOG=catalog_path, ALIAS_PATH=alias_path,
                                OUT=out_path)
                os.remove(out_path)
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = main(['--dry-run'])
                ok(rc == 0 and not os.path.exists(out_path), '--dry-run writes nothing')
                ok(buf.getvalue().splitlines()[0] == summary_line(doc), 'summary line printed first')
                with contextlib.redirect_stdout(io.StringIO()):
                    rc = main([])
                written = json.load(open(out_path, encoding='utf-8'))
                ok(rc == 0 and list(written) == list(doc) and written['mastery']['rank'] == 22
                   and written['alias'] == SELFTEST_ALIAS and isinstance(written['updated'], int),
                   '--once (default) writes the store')
            finally:
                globals_.update(keep)
    except AssertionError as e:
        print(f'selftest : FAILED - {e}')
        return 2
    print(f'selftest : ok ({len(checks)} checks) offline - no AlecaFrame, no network')
    return 0


# ------------------------------------------------------------------ CLI

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='player.py', description='Build data/player.json from the AlecaFrame save.',
        epilog='Exit codes: 0 ok, 2 selftest failure.')
    ap.add_argument('--once', action='store_true', help='single pass (default; kept for cron lines)')
    ap.add_argument('--out', metavar='PATH', help='store path to write (default data/player.json)')
    ap.add_argument('--json', action='store_true', help='also print the store JSON to stdout')
    ap.add_argument('--dry-run', action='store_true', help='print the plan and write nothing')
    ap.add_argument('--selftest', action='store_true',
                    help='offline fixture run in a temp dir (no AlecaFrame, no network)')
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    t0 = time.time()
    out_path = args.out or OUT
    source = 'missing'
    try:
        save, source = load_save(SAVE)
    except (OSError, ValueError) as e:                     # corrupt/undecryptable: degrade
        print(f'player : save unreadable ({e}) - writing a degraded document (run scripts/refresh.py)')
        save = {}
    doc = build_doc(save, load_catalog(CATALOG), read_alias(ALIAS_PATH))
    print(summary_line(doc))                               # summary line FIRST
    if source == 'missing':
        print(f'player : no decrypted save at {rel(SAVE)} - run scripts/refresh.py '
              '(degraded document)')

    if args.dry_run:
        print(f'plan : write {rel(out_path)} ({len(doc["syndicates"])} syndicates,'
              f' {len(doc["focus"])} focus rows)')
        print('plan : dry-run - nothing written')
        if args.json:
            print(json.dumps(doc, separators=(',', ':')))
        return 0

    save_json(out_path, doc)
    print(f'store : {rel(out_path)} ({os.path.getsize(out_path) / 1024.0:.1f} KB)')
    if args.json:
        print(json.dumps(doc, separators=(',', ':')))
    print(f'runtime : {time.time() - t0:.2f}s')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
