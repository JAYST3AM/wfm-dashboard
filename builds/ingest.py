#!/usr/bin/env python3
"""Build-data ingestion: authoritative sources -> data/build_data.json.

WHAT IT BUILDS (brief sections 1, 2, 3, 16)
  One deterministic, versioned database the engine loads once:

      {schema_version, generated, generated_iso, game_data:{...}, sources:{...},
       equipment:{<uniqueName>: row}, mods:{<uniqueName>: row}, summary:{...},
       notes:[...]}

  * Identity is DE's `uniqueName` (what the save, the WFCD catalog and the local caches
    all join on). `slug` (warframe.market) rides along for market joins only.
  * Equipment rows carry rank-0 base stats exactly as the export ships them, the slot
    polarities, and the damage/trigger facts the engine reads. Rank-30 values are
    derived by the engine from documented rank-up rules, not baked in here.
  * Mod rows carry the parsed per-rank effect tables (builds/effects.py) so no formula
    ever re-parses a game string at calculation time.
  * Every row records the file, URL and fetch stamp it came from, and the database
    carries a source block - "where did this value come from?" is always answerable.

SOURCES
  mods       data/wfcd_mods_cache.json (WFCD Mods.json projection; --refresh-mods
             re-fetches it exactly like scripts/mod_cards.py does, so the two consumers
             share one cache)
  equipment  WFCD per-category files (Warframes, Primary, Secondary, Melee, Sentinels,
             SentinelWeapons) - raw.githubusercontent, jsdelivr fallback
  slugs      data/wfm_items_v2.json (warframe.market item list, gameRef -> slug)
  offline    --no-fetch reads the local AlecaFrame mirror
             (%LOCALAPPDATA%\\AlecaFrame\\cachedData\\json) when the network is down

RUN
  python builds/ingest.py                 # fetch equipment, reuse the mod cache
  python builds/ingest.py --refresh-mods  # also re-fetch the WFCD mod catalog
  python builds/ingest.py --no-fetch      # never touch the network (local mirror)
  python builds/ingest.py --selftest      # offline fixtures, writes nothing

Deterministic: rows are sorted, floats are rounded once, stamps come from the inputs,
and the write is atomic (tmp + os.replace). Stdlib only.
"""
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

if __package__ in (None, ''):                     # `python builds/ingest.py`
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from builds import effects as effects_mod
    from builds import schema
else:
    from . import effects as effects_mod
    from . import schema

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, 'data')
OUT = os.path.join(DATA, 'build_data.json')
MODS_CACHE = os.path.join(DATA, 'wfcd_mods_cache.json')
WFM_ITEMS = os.path.join(DATA, 'wfm_items_v2.json')
MIRROR = os.path.join(os.path.expandvars(r'%LOCALAPPDATA%'), 'AlecaFrame', 'cachedData',
                      'json')

WFCD_BASE = 'https://raw.githubusercontent.com/WFCD/warframe-items/master/data/json/'
WFCD_MIRROR_BASE = 'https://cdn.jsdelivr.net/gh/WFCD/warframe-items@master/data/json/'
MODS_URL = WFCD_BASE + 'Mods.json'
UA = 'WFMTrader/0.1 (local personal tool; github.com/JAYST3AM/wfm-dashboard)'
STAMP_ISO = '%Y-%m-%dT%H:%M:%SZ'
SCHEMA_VERSION = 1

# WFCD file -> equipment kind. Archwing / Arch-Gun / Arch-Melee / Misc are deliberately
# not ingested yet (registry: archwing_necramech).
EQUIPMENT_FILES = (
    ('Warframes', schema.EQUIP_WARFRAME),
    ('Primary', schema.EQUIP_PRIMARY),
    ('Secondary', schema.EQUIP_SECONDARY),
    ('Melee', schema.EQUIP_MELEE),
    ('Sentinels', schema.EQUIP_SENTINEL),
    ('SentinelWeapons', schema.EQUIP_SENTINEL_WEAPON),
)

# Which source owns which kind of data (the machine-readable twin of
# docs/build-data-sources.md).
SOURCE_OWNERSHIP = {
    'equipment_stats': {'source': 'WFCD warframe-items (DE Public Export projection)',
                        'url': WFCD_BASE + '<Category>.json',
                        'owns': 'rank-0 base stats, damage distribution, crit/status, '
                                'fire rate, magazine, reload, trigger, polarities, '
                                'mastery requirement'},
    'mod_catalog': {'source': 'WFCD warframe-items Mods.json',
                    'url': MODS_URL,
                    'owns': 'mod name/type/compat/rarity/polarity/base drain/max rank '
                            'and the per-rank stat table (levelStats)'},
    'mod_effects_parsing': {'source': 'builds/effects.py (this repo)',
                            'owns': 'which stat each catalog line means, the stacking '
                                    'category, and the refusal list'},
    'slug_join': {'source': 'warframe.market item list',
                  'url': 'data/wfm_items_v2.json (gameRef -> slug)',
                  'owns': 'market slug only - never identity, never math'},
    'rules': {'source': 'WARFRAME Wiki (Damage, Damage/Calculation, Calculating '
                        'Bonuses, Critical Hit, Status Effect, Multishot, Reload, '
                        'Mods, Polarity, Aura, Warframes, Abilities)',
              'url': 'https://wiki.warframe.com',
              'owns': 'every formula: drain/polarity rounding, aura bonus, element '
                      'combination order, crit tiers, status, reload time, rank-up '
                      'scaling, ability caps'},
    'market': {'source': 'warframe.market', 'owns': 'prices only - not part of this '
                                                    'database and never used by math'},
}


# ---------------------------------------------------------------- helpers
def ascii_s(value):
    return str(value).encode('ascii', 'replace').decode('ascii')


def iso_utc(epoch=None):
    return time.strftime(STAMP_ISO, time.gmtime(epoch if epoch else time.time()))


def atomic_write(path, doc):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, indent=1, sort_keys=False)
    os.replace(tmp, path)


def trim_float(value, digits=4):
    if value is None or isinstance(value, bool):
        return value
    if not isinstance(value, (int, float)):
        return value
    out = round(float(value), digits)
    return int(out) if float(out).is_integer() else out


def fetch_json(url, timeout=90):
    """ONE GET of a JSON document, with the jsdelivr mirror as a fallback."""
    last = None
    for candidate in (url, url.replace(WFCD_BASE, WFCD_MIRROR_BASE)):
        try:
            req = urllib.request.Request(candidate, headers={'User-Agent': UA,
                                                             'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except (urllib.error.URLError, ValueError, OSError) as exc:   # pragma: no cover
            last = exc
    raise RuntimeError('cannot fetch %s: %r' % (url, last))


def load_json(path, default=None):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


# ---------------------------------------------------------------- normalising
def slug_index(wfm_items_doc):
    """WFM item list -> ({gameRef: slug}, {gameRef: maxRank})."""
    by_ref, max_rank = {}, {}
    items = (wfm_items_doc or {}).get('data') or []
    for item in items:
        ref = str(item.get('gameRef') or '').strip()
        slug = str(item.get('slug') or '').strip()
        if not ref or not slug:
            continue
        by_ref.setdefault(ref, slug)
        if isinstance(item.get('maxRank'), int):
            max_rank.setdefault(ref, item['maxRank'])
    return by_ref, max_rank


def slugify(name):
    """Fallback slug for rows warframe.market does not carry (documented as a fallback:
    the market slug is the only slug that may be used for market lookups)."""
    import re
    return re.sub(r'[^a-z0-9]+', '_', str(name or '').lower()).strip('_')


def mod_class(row):
    """WFCD type/compatName -> the class key schema.MOD_TARGETS speaks."""
    compat = str(row.get('compatName') or '').strip().lower()
    kind = str(row.get('type') or '').strip().lower()
    if compat == 'aura' or kind.startswith('aura'):
        return 'aura'
    if compat == 'stance' or 'stance' in kind:
        return 'stance'
    if compat == 'warframe' or kind.startswith('warframe'):
        return 'warframe'
    if compat in ('rifle', 'shotgun', 'bow', 'sniper', 'speargun', 'primary') \
            or kind.startswith('primary'):
        return 'primary'
    if compat in ('pistol', 'secondary') or kind.startswith('secondary'):
        return 'secondary'
    if compat in ('melee',) or kind.startswith('melee'):
        return 'melee'
    if compat in ('sentinel', 'robotic'):
        return 'sentinel'
    if compat in ('sentinelweapon', 'sentinel weapon'):
        return 'sentinel_weapon'
    if compat in ('companion', 'beast', 'kubrow', 'kavat'):
        return 'companion'
    if 'archwing' in kind or compat in ('archwing',):
        return 'archwing'
    if compat in ('archgun', 'arch-gun') or 'arch-gun' in kind or 'archgun' in kind:
        return 'arch-gun'
    if compat in ('archmelee', 'arch-melee') or 'arch-melee' in kind:
        return 'arch-melee'
    if 'necramech' in kind or compat == 'necramech':
        return 'necramech'
    if 'parazon' in kind or compat == 'parazon':
        return 'parazon'
    if 'railjack' in kind or compat == 'railjack':
        return 'railjack'
    if 'k-drive' in kind or 'kdrive' in kind:
        return 'k-drive'
    return compat or kind or 'unknown'


def normalise_mod(row, slug_by_ref, source):
    """One WFCD Mods.json row -> the ingested mod row (effect tables included)."""
    name = str(row.get('name') or '').strip()
    unique = str(row.get('uniqueName') or '').strip()
    if not unique or not name:
        return None
    cls = mod_class(row)
    targets = list(schema.MOD_TARGETS.get(cls, ()))
    effects = effects_mod.parse_mod_effects(row)
    flags = effects_mod.derive_flags(name, row, effects)
    polarity = schema.norm_polarity(row.get('polarity'))
    max_rank = effects['max_rank']
    mod_targets = targets
    if flags['aura']:
        mod_targets = [schema.EQUIP_WARFRAME]
    elif flags['stance']:
        mod_targets = [schema.EQUIP_MELEE]
    row_out = {
        'id': unique,
        'name': name,
        'slug': slug_by_ref.get(unique) or slugify(name),
        'type': row.get('type'),
        'compat': row.get('compatName'),
        'class': cls,
        'targets': mod_targets,
        'variant': variant_of(unique),
        'rarity': row.get('rarity'),
        'polarity': polarity,
        'base_drain': row.get('baseDrain'),
        'max_rank': max_rank,
        'slot': effects_mod.slot_class(row),
        'exilus_ok': effects_mod.exilus_ok(row),
        'flags': flags,
        'augment_export': bool(row.get('isAugment')),
        'effects': effects,
        'source': source,
    }
    return row_out


def variant_of(unique_name):
    """'beginner' / 'intermediate' / None: the catalog ships starter copies of several
    mods under the same display name (Serration exists at 3, 5 and 10 ranks), so the
    variant has to be carried explicitly or a name lookup picks the wrong one."""
    low = str(unique_name or '').lower()
    if '/beginner/' in low or low.endswith('beginner'):
        return 'beginner'
    if '/intermediate/' in low or low.endswith('intermediate'):
        return 'intermediate'
    return None


def normalise_equipment(row, kind, slug_by_ref, max_rank_by_ref, source):
    """One WFCD equipment row -> the ingested equipment row the engines read."""
    unique = str(row.get('uniqueName') or '').strip()
    name = str(row.get('name') or '').strip()
    if not unique or not name:
        return None
    product = str(row.get('productCategory') or '')
    subtype = str(row.get('type') or '')
    max_rank = schema.MAX_RANK_WEAPON
    if kind == schema.EQUIP_WARFRAME:
        max_rank = schema.MAX_RANK_FRAME
        if product == 'MechSuits':
            return None                        # necramechs are a later phase
    damage = {}
    for key, value in (row.get('damage') or {}).items():
        if key in schema.ALL_DAMAGE_TYPES and value:
            damage[key] = trim_float(value)
    attacks = [a.get('name') for a in (row.get('attacks') or []) if isinstance(a, dict)]
    incarnon = any('incarnon' in str(a).lower() for a in attacks)
    traits = [str(t) for t in (row.get('traits') or []) if t]
    stats = {}
    if kind == schema.EQUIP_WARFRAME:
        stats = {'health': trim_float(row.get('health')),
                 'shield': trim_float(row.get('shield')),
                 'armor': trim_float(row.get('armor')),
                 'energy': trim_float(row.get('power')),
                 'sprint_speed': trim_float(row.get('sprintSpeed'))}
    out = {
        'id': unique,
        'name': name,
        'slug': slug_by_ref.get(unique) or slugify(name),
        'kind': kind,
        'subtype': subtype,
        'category': row.get('category'),
        'product_category': product,
        'mastery_req': row.get('masteryReq'),
        'max_rank': max_rank,
        'polarities': [p for p in (schema.norm_polarity(x) for x in
                                   (row.get('polarities') or [])) if p],
        'aura_polarity': schema.norm_polarity(row.get('aura')),
        'stance_polarity': schema.norm_polarity(row.get('stancePolarity')),
        'exilus_polarity': schema.norm_polarity(row.get('exilusPolarity')),
        'stats': stats,
        'damage': damage,
        'damage_total': trim_float((row.get('damage') or {}).get('total')
                                   or sum(damage.values())),
        'crit_chance': trim_float(_pct(row.get('criticalChance'))),
        'crit_multiplier': trim_float(row.get('criticalMultiplier')),
        'status_chance': trim_float(_pct(row.get('procChance'))),
        'fire_rate': trim_float(row.get('fireRate')),
        'multishot': trim_float(row.get('multishot')),
        'magazine': trim_float(row.get('magazineSize')),
        'reload': trim_float(row.get('reloadTime')),
        'trigger': row.get('trigger'),
        'range': trim_float(row.get('range')),
        'combo_duration': trim_float(row.get('comboDuration')),
        'image_name': row.get('imageName'),
        'attacks': [str(a) for a in attacks][:6],
        'incarnon': incarnon,
        'traits': traits,
        'is_prime': bool(row.get('isPrime')),
        'source': source,
    }
    return out


def _pct(value):
    """WFCD stores 0..1 fractions; the arsenal speaks percent."""
    if value is None:
        return None
    return float(value) * 100.0


def build_database(mod_rows, equipment_rows, meta):
    """Normalised rows -> the database document (pure; the tests exercise this)."""
    equipment, mods, notes = {}, {}, []
    for row in equipment_rows:
        if row is None:
            continue
        if row['id'] in equipment:
            notes.append('duplicate equipment row dropped: %s' % row['id'])
            continue
        equipment[row['id']] = row
    for row in mod_rows:
        if row is None:
            continue
        if row['id'] in mods:
            notes.append('duplicate mod row dropped: %s' % row['id'])
            continue
        mods[row['id']] = row
    unmodelled = sum(1 for r in mods.values()
                     if (r.get('effects') or {}).get('unmodelled'))
    conditional = sum(1 for r in mods.values()
                      if (r.get('effects') or {}).get('conditional'))
    by_kind = {}
    for row in equipment.values():
        by_kind[row['kind']] = by_kind.get(row['kind'], 0) + 1
    no_targets = sum(1 for r in mods.values() if not r.get('targets'))
    db = {
        'schema_version': SCHEMA_VERSION,
        'generated': meta.get('generated'),
        'generated_iso': meta.get('generated_iso'),
        'content_hash': None,
        'game_data': {'source_version': meta.get('mods_fetched_iso'),
                      'equipment_files': meta.get('equipment_files'),
                      'equipment_fetched_iso': meta.get('fetched'),
                      'mods_fetched_iso': meta.get('mods_fetched_iso')},
        'sources': SOURCE_OWNERSHIP,
        'equipment': equipment,
        'mods': mods,
        'summary': {'equipment': len(equipment), 'equipment_by_kind': by_kind,
                    'mods': len(mods), 'mods_with_unmodelled_stats': unmodelled,
                    'mods_with_conditional_effects': conditional,
                    'mods_without_targets': no_targets},
        'notes': notes,
    }
    db['content_hash'] = content_hash(db)
    return db


# Fields that record *when* something was read rather than *what* was read. The content
# hash ignores them, so a re-run over unchanged sources is a no-op on disk.
STAMP_FIELDS = ('generated', 'generated_iso')
STAMP_FIELDS_IN_GAME_DATA = ('source_version', 'equipment_fetched_iso', 'mods_fetched_iso')


def content_hash(db):
    """sha256 of everything in the database except the fetch/generation timestamps.

    This is the database's identity: the same sources produce the same hash, and any real
    change (a new mod, a moved number) moves it. `python builds/debug.py summary` prints
    it so two databases can be compared without diffing 2,600 rows.
    """
    payload = {k: v for k, v in (db or {}).items()
               if k not in STAMP_FIELDS + ('content_hash',)}
    game_data = dict(payload.get('game_data') or {})
    for key in STAMP_FIELDS_IN_GAME_DATA:
        game_data.pop(key, None)
    if game_data:
        payload['game_data'] = game_data
    else:
        payload.pop('game_data', None)
    blob = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


def carry_stamps(new_db, old_db):
    """Keep the old database's timestamps when nothing but those timestamps changed.

    A run over unchanged sources must not rewrite the file's identity: the generated
    stamps and the per-source fetch stamps are carried over, so the output is byte-for-byte
    the file that was already there. Returns True when that happened.
    """
    if not old_db or old_db.get('content_hash') != new_db.get('content_hash'):
        return False
    for key in STAMP_FIELDS:
        if old_db.get(key) is not None:
            new_db[key] = old_db[key]
    old_game = old_db.get('game_data') or {}
    for key in STAMP_FIELDS_IN_GAME_DATA:
        if old_game.get(key) is not None:
            new_db['game_data'][key] = old_game[key]
    return True


# ---------------------------------------------------------------- the run
def gather(mods_doc, equipment_docs, wfm_doc, fetched, offline=False):
    """Raw source documents -> (mod rows, equipment rows, meta). Pure enough to test."""
    slug_by_ref, max_rank_by_ref = slug_index(wfm_doc)
    mod_source = {'file': 'data/wfcd_mods_cache.json', 'url': MODS_URL,
                  'fields': (mods_doc or {}).get('fields')}
    mod_rows = [normalise_mod(m, slug_by_ref, mod_source)
                for m in (mods_doc or {}).get('mods') or []]
    equipment_rows = []
    for (filename, kind), doc in zip(EQUIPMENT_FILES, equipment_docs):
        source = {'file': '%s.json' % filename, 'url': WFCD_BASE + '%s.json' % filename}
        for raw in doc or []:
            equipment_rows.append(normalise_equipment(raw, kind, slug_by_ref,
                                                      max_rank_by_ref, source))
    meta = {'generated': fetched, 'generated_iso': fetched,
            'mods_fetched_iso': (mods_doc or {}).get('fetched_iso'),
            'equipment_files': [f for f, _ in EQUIPMENT_FILES],
            'fetched': fetched, 'offline': offline}
    return mod_rows, equipment_rows, meta


def load_equipment_docs(no_fetch=False, fetch=fetch_json):
    """Fetch (or read from the local AlecaFrame mirror) the equipment files."""
    docs = []
    for filename, _kind in EQUIPMENT_FILES:
        if no_fetch:
            path = os.path.join(MIRROR, '%s.json' % filename)
            doc = load_json(path)
            if doc is None:
                raise RuntimeError('--no-fetch needs the AlecaFrame mirror at %s' % path)
        else:
            doc = fetch(WFCD_BASE + '%s.json' % filename)
        docs.append(doc)
    return docs


def refresh_mods_cache(write=True, fetch=fetch_json):
    """Re-fetch the WFCD mod catalog into data/wfcd_mods_cache.json.

    Same fields scripts/mod_cards.py keeps, so both consumers share one cache.
    """
    raw = fetch(MODS_URL)
    mods = raw.get('data') if isinstance(raw, dict) else raw
    fields = ('name', 'uniqueName', 'type', 'compatName', 'rarity', 'polarity',
              'baseDrain', 'fusionLimit', 'tradable', 'isPrime', 'isAugment', 'isExilus',
              'isUtility', 'description', 'levelStats')
    trimmed = []
    for mod in mods or []:
        row = {}
        for key in fields:
            value = mod.get(key)
            if key == 'levelStats' and isinstance(value, list):
                value = [{'stats': [str(s) for s in (e.get('stats') or [])]}
                         for e in value if isinstance(e, dict) and e.get('stats')]
            if key == 'description':
                value = str(value or '')[:300] or None
            if value not in (None, '', [], {}):
                row[key] = value
        if row.get('name') and row.get('uniqueName'):
            trimmed.append(row)
    doc = {'source_url': MODS_URL, 'fetched': int(time.time()),
           'fetched_iso': iso_utc(), 'count': len(trimmed), 'fields': list(fields),
           'raw_count': len(mods or []), 'mods': trimmed}
    if write:
        atomic_write(MODS_CACHE, doc)
    return doc


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build data/build_data.json')
    parser.add_argument('--refresh-mods', action='store_true',
                        help='re-fetch the WFCD mod catalog first')
    parser.add_argument('--no-fetch', action='store_true',
                        help='never touch the network; read the local AlecaFrame mirror')
    parser.add_argument('--out', default=OUT)
    parser.add_argument('--quiet', action='store_true')
    parser.add_argument('--selftest', action='store_true')
    args = parser.parse_args(argv)
    if args.selftest:
        return selftest()

    def say(text):
        if not args.quiet:
            print(ascii_s(text))

    if args.refresh_mods:
        say('refreshing the WFCD mod catalog...')
        mods_doc = refresh_mods_cache()
    else:
        mods_doc = load_json(MODS_CACHE)
    if not mods_doc:
        say('no mod cache at %s - run with --refresh-mods once' % MODS_CACHE)
        return 1
    say('mods: %d rows (cache %s)' % (len(mods_doc.get('mods') or []),
                                      mods_doc.get('fetched_iso')))
    equipment_docs = load_equipment_docs(no_fetch=args.no_fetch)
    say('equipment files: %s' % ', '.join(f for f, _ in EQUIPMENT_FILES))
    wfm_doc = load_json(WFM_ITEMS, {})
    fetched = iso_utc()
    mod_rows, equipment_rows, meta = gather(mods_doc, equipment_docs, wfm_doc, fetched,
                                            offline=args.no_fetch)
    db = build_database(mod_rows, equipment_rows, meta)
    unchanged = carry_stamps(db, load_json(args.out))
    atomic_write(args.out, db)
    say('wrote %s%s' % (args.out, ' (unchanged: content hash matches)' if unchanged
                        else ''))
    say('  content hash %s' % db['content_hash'])
    say('  equipment %d %s' % (db['summary']['equipment'],
                               db['summary']['equipment_by_kind']))
    say('  mods %d (%d carry stats we do not model, %d carry conditional effects)'
        % (db['summary']['mods'], db['summary']['mods_with_unmodelled_stats'],
           db['summary']['mods_with_conditional_effects']))
    return 0


# ---------------------------------------------------------------- selftest
FIXTURE_MODS = [
    {'name': 'Serration', 'uniqueName': '/Lotus/Upgrades/Mods/Rifle/WeaponDamageAmountMod',
     'type': 'Primary Mod', 'compatName': 'Rifle', 'rarity': 'Uncommon',
     'polarity': 'madurai', 'baseDrain': 4, 'fusionLimit': 10, 'tradable': True,
     'levelStats': [{'stats': ['+%d%% Damage' % (15 * (i + 1))]} for i in range(11)]},
    {'name': 'Hellfire', 'uniqueName': '/Lotus/Upgrades/Mods/Rifle/ElementalDamageHeatMod',
     'type': 'Primary Mod', 'compatName': 'Rifle', 'rarity': 'Uncommon',
     'polarity': 'naramon', 'baseDrain': 6, 'fusionLimit': 5,
     'levelStats': [{'stats': ['+%d%% <DT_FIRE_COLOR>Heat' % (15 * (i + 1))]}
                    for i in range(6)]},
    {'name': 'Galvanized Chamber',
     'uniqueName': '/Lotus/Upgrades/Mods/Rifle/WeaponEventRiflePunchThroughMod',
     'type': 'Primary Mod', 'compatName': 'Rifle', 'rarity': 'Rare',
     'polarity': 'madurai', 'baseDrain': 6, 'fusionLimit': 10,
     'levelStats': [{'stats': ['+7.3%% Multishot', 'On Kill:\\n+2.7%% Multishot for 20s.']},
                    {'stats': ['+80%% Multishot', 'On Kill:\\n+30%% Multishot for 20s.']}]},
]

FIXTURE_EQUIPMENT = [
    {'uniqueName': '/Lotus/Weapons/Tenno/Rifle/BratonPrime', 'name': 'Braton Prime',
     'type': 'Rifle', 'category': 'Primary', 'masteryReq': 8, 'maxRank': 30,
     'damage': {'total': 35, 'impact': 1.75, 'puncture': 12.25, 'slash': 21},
     'criticalChance': 0.12, 'criticalMultiplier': 2, 'procChance': 0.26,
     'fireRate': 9.583334, 'multishot': 1, 'magazineSize': 75, 'reloadTime': 2.15,
     'trigger': 'Auto', 'polarities': None, 'exilusPolarity': 'naramon'},
    {'uniqueName': '/Lotus/Powersuits/Excalibur/Excalibur', 'name': 'Excalibur',
     'type': 'Warframe', 'category': 'Warframes', 'productCategory': 'Suits',
     'masteryReq': 0, 'health': 270, 'shield': 270, 'armor': 240, 'power': 100,
     'sprintSpeed': 1, 'aura': None, 'polarities': ['vazarin', 'madurai']},
]


def selftest():
    """The whole pipeline on embedded fixtures, offline; writes nothing."""
    failures = []

    counter = [0]

    def check(label, ok, detail=''):
        counter[0] += 1
        print('%s  %s%s' % ('PASS' if ok else 'FAIL', label,
                            '' if ok else ' -- %s' % detail))
        if not ok:
            failures.append(label)

    slug_by_ref = {'/Lotus/Weapons/Tenno/Rifle/BratonPrime': 'braton_prime'}
    mod_rows = [normalise_mod(m, slug_by_ref, {'file': 'fixture'}) for m in FIXTURE_MODS]
    equip_rows = [normalise_equipment(r, schema.EQUIP_PRIMARY, slug_by_ref, {},
                                      {'file': 'fixture'}) for r in FIXTURE_EQUIPMENT[:1]]
    frame_rows = [normalise_equipment(FIXTURE_EQUIPMENT[1], schema.EQUIP_WARFRAME,
                                      slug_by_ref, {}, {'file': 'fixture'})]
    db = build_database(mod_rows, equip_rows + frame_rows, {'generated_iso': 'fixture'})

    serration = mod_rows[0]
    check('mod: identity is the uniqueName', serration['id'].endswith('WeaponDamageAmountMod'))
    check('mod: class + targets', serration['class'] == 'primary'
          and serration['targets'] == [schema.EQUIP_PRIMARY], str(serration['targets']))
    check('mod: base drain and max rank', serration['base_drain'] == 4
          and serration['max_rank'] == 10)
    check('mod: rank table is the export table',
          serration['effects']['rank_table']['damage'] == [15 * (i + 1) for i in range(11)])
    check('mod: progression reported linear', serration['effects']['linear']['damage']['linear'])
    heat = mod_rows[1]
    check('mod: element line parses to a canonical stat',
          heat['effects']['rank_table'].get('heat') == [15 * (i + 1) for i in range(6)])
    galv = mod_rows[2]
    check('mod: conditional rider refused, base value kept',
          galv['effects']['rank_table']['multishot'] == [7.3, 80]
          and any('On Kill' in c for c in galv['effects']['conditional']))
    check('mod: galvanized flag', galv['flags']['galvanized'])
    braton = db['equipment']['/Lotus/Weapons/Tenno/Rifle/BratonPrime']
    check('equipment: damage kept per type', braton['damage'] == {'impact': 1.75,
                                                                 'puncture': 12.25,
                                                                 'slash': 21})
    check('equipment: fractions became percent',
          braton['crit_chance'] == 12 and braton['status_chance'] == 26)
    check('equipment: slug from the market join', braton['slug'] == 'braton_prime')
    exca = db['equipment']['/Lotus/Powersuits/Excalibur/Excalibur']
    check('equipment: frame stats kept rank-0', exca['stats']['health'] == 270
          and exca['stats']['energy'] == 100)
    check('database: provenance block present', 'equipment_stats' in db['sources'])
    check('database: deterministic (same input -> same summary)',
          build_database(mod_rows, equip_rows, {'generated_iso': 'fixture'})['summary']
          == build_database(mod_rows, equip_rows, {'generated_iso': 'fixture'})['summary'])
    # The content hash is the database's identity: stamps must not move it, data must.
    db_a = build_database(mod_rows, equip_rows, {'generated_iso': '2026-01-01T00:00:00Z'})
    db_b = build_database(mod_rows, equip_rows, {'generated_iso': '2027-06-30T12:34:56Z'})
    check('database: the content hash ignores fetch/generation stamps',
          db_a['content_hash'] == db_b['content_hash'], db_a['content_hash'])
    moved = json.loads(json.dumps(db_a))
    first_id = sorted(moved['mods'])[0]
    moved['mods'][first_id]['effects']['rank_table'] = {'damage': [1]}
    check('database: the content hash moves when a number moves',
          content_hash(moved) != db_a['content_hash'])
    check('database: no per-row fetch stamps (they would break reproducibility)',
          all('fetched_iso' not in (row.get('source') or {})
              for row in list(db_a['mods'].values()) + list(db_a['equipment'].values())))
    old = json.loads(json.dumps(db_a))
    old['generated_iso'] = '2026-09-29T09:00:00Z'
    fresh = build_database(mod_rows, equip_rows, {'generated_iso': '2026-09-29T10:00:00Z'})
    carried = carry_stamps(fresh, old)
    check('database: a no-change re-run keeps the file\'s own stamps',
          carried and fresh['generated_iso'] == '2026-09-29T09:00:00Z',
          str(fresh.get('generated_iso')))
    changed = build_database(mod_rows, equip_rows, {'generated_iso': '2026-09-29T10:00:00Z'})
    changed['mods'][first_id]['effects']['rank_table'] = {'damage': [1]}
    changed['content_hash'] = content_hash(changed)
    check('database: a real change takes the new stamps',
          carry_stamps(changed, old) is False)
    print('\nselftest %s (%d checks, %d failed) - nothing written'
          % ('OK' if not failures else 'FAILED', counter[0], len(failures)))
    return 0 if not failures else 1


if __name__ == '__main__':
    sys.exit(main())
