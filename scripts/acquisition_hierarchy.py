"""Acquisition hierarchy - where a drop actually is, in the game's own navigation terms.

Jay (2026-09-30): *"Never flatten a game's location hierarchy just because the source dataset
does."*  The real failure: the official drop table labels a Railjack node as
`Venus/Falling Glory (Skirmish)`, and reading the first segment as the location tells a player to
look for Falling Glory on the Venus Star Chart, where it does not exist. The honest answer is
`Railjack -> Venus Proxima -> Falling Glory`.

Sources, in the order the brief sets:

  1. Digital Extremes' own public export (the drop tables' chance numbers come from the WFCD mirror
     of DE's official drop tables; this file is DE's own region/navigation data, mirrored as plain
     JSON by the same community project).  Cached under data/dropdata/export/, so rebuilds are
     offline and idempotent.
       ExportRegions.json   one entry per node: missionType, systemName, nodeType, levelOverride
       dict.en.json         the localisation dictionary: `/Lotus/Language/...` key -> English text

  2. The Warframe Wiki, only to explain a label the export does not (never to replace a chance).

Nothing here guesses.  A node the export does not describe keeps the drop table's own label and is
returned with `unresolved` naming exactly which part could not be verified, because accuracy beats
completeness: show the verified portion, mark the rest.

Navigation systems (the game's own split, from the export's missionType + system key):

  Railjack            missionType MT_RAILJACK, system `/Lotus/Language/Locations/<X>_SPACE`
  Star Chart          everything else on a planet/moon/derelict region
  Duviri              the Duviri regions (Normal / Hard / The Circuit)
  Hollvania           the 1999 hub regions
  Zariman             the Zariman Ten Zero regions
  Sanctuary           Sanctuary Onslaught
  Open World          Cetus / Fortuna / Necralisk bounty regions

Usage
  python scripts/acquisition_hierarchy.py --selftest     offline logic + real-data checks
  python scripts/acquisition_hierarchy.py --report       what the cache resolves today
  python scripts/acquisition_hierarchy.py --fetch        refresh the cached export files
"""
import argparse
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.environ.get('WFM_DATA_DIR') or os.path.join(ROOT, 'data')
EXPORT_DIR = os.path.join(DATA, 'dropdata', 'export')

EXPORT_BASE = 'https://raw.githubusercontent.com/calamity-inc/warframe-public-export-plus/master/'
EXPORT_FILES = [
    ('ExportRegions.json', True),
    ('dict.en.json', True),
]
UA = {'User-Agent': 'WFMTrader/0.1 (local personal tool; github.com/JAYST3AM/wfm-dashboard)'}
TIMEOUT = 600

SCHEMA = 1

# missionType -> the navigation system a player would name.  Only the ones that are NOT a plain
# Star Chart region need an entry; anything absent is Star Chart, which the explicit check below
# proves rather than assumes.
RAILJACK_TYPE = 'MT_RAILJACK'
# MT_PVP is the Conclave.  MT_TERRITORY is Interception, a normal Star Chart mode - the calibration
# table below prints it, so it is not a guess.
PVP_TYPES = ('MT_PVP',)

# Region-key suffixes the export uses for the systems that are not a Star Chart planet.
SYSTEM_FOR_SUFFIX = {
    '_SPACE': 'Railjack',
}

# The drop table's own labels that are not a region the game exports, mapped to what they are.
# These are named (and cited in the report) rather than guessed: the export carries no region entry
# for an open-world bounty table, so the hub is labelled by hand.

# The drop table's own labels that name a system rather than a region.  Everything else it uses as
# a label ('Duviri', 'Void', 'Lua', 'Höllvania') is a region text in the game's export, and is read
# from there rather than listed here.
LABEL_SYSTEM = {}

# Where a rarity/source bucket comes from, so the record can say how the item is obtained and not
# only where.  The drop table's own keys drive this; nothing is inferred from a chance value.
SOURCE_FOR_MODE = {
    'Caches': 'sabotage cache',
    'The Circuit': 'circuit reward',
    'Hard': 'circuit reward',
    'Normal': 'circuit reward',
}


def _get(url):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=TIMEOUT).read()


def fetch(offline=False):
    """Cache the export files under data/dropdata/export/.  Returns {name: bytes}."""
    os.makedirs(EXPORT_DIR, exist_ok=True)
    out = {}
    for name, required in EXPORT_FILES:
        path = os.path.join(EXPORT_DIR, name)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            with open(path, 'rb') as fh:
                out[name] = fh.read()
            continue
        if offline:
            if required:
                raise RuntimeError('%s is not cached and --offline was given' % name)
            continue
        try:
            raw = _get(EXPORT_BASE + name)
        except Exception:
            if required:
                raise
            continue
        tmp = path + '.tmp'
        with open(tmp, 'wb') as fh:
            fh.write(raw)
        os.replace(tmp, path)
        out[name] = raw
    return out


def _english(dictionary, key):
    """The English text for a `/Lotus/Language/...` key, or None.  No fallback guess."""
    if not isinstance(key, str):
        return None
    text = dictionary.get(key)
    return text if isinstance(text, str) and text.strip() else None


# A region key is a Star Chart place when it lives under the Locations tree (or the Deimos planet
# key) and is not one of the special families below.  Taken from the export's own keys, so the list
# is never out of date with the data it is used against.
STAR_CHART_KEY_PREFIXES = ('/Lotus/Language/Locations/', '/Lotus/Language/InfestedMicroplanet/')
STAR_CHART_KEY_EXCLUDE = ('_SPACE', 'RelayStationSanctuary')

# The systems that are not the Star Chart, by the region key family the export puts them in.
SPECIAL_SYSTEMS = (
    ('/Lotus/Language/1999/', 'Hollvania'),
    ('/Lotus/Language/Locations/Duviri', 'Duviri'),
    ('/Lotus/Language/Locations/RelayStationSanctuary', 'Sanctuary Onslaught'),
    ('/Lotus/Language/Zariman/', 'Zariman Ten Zero'),
)

# Region texts the export spells one way and a player reads another.  One entry, one reason.
REGION_ALIAS = {'Zariman': 'Zariman Ten Zero'}


def is_railjack(entry):
    return str(entry.get('missionType') or '').upper() == RAILJACK_TYPE


def system_for(entry, dictionary):
    """The navigation system for one export region entry, or None when it cannot be named.

    Railjack is decided by the export's own mission type, never by a name that looks spacey; the
    special systems are decided by the region key family the export files them under; everything
    else under the Locations tree is the Star Chart.  A key family this does not know returns None
    and the caller reports the system as unresolved instead of calling it the Star Chart.
    """
    if is_railjack(entry):
        return 'Railjack'
    system_key = str(entry.get('systemName') or '')
    for suffix, system in SYSTEM_FOR_SUFFIX.items():
        if system_key.endswith(suffix):
            return system
    for needle, system in SPECIAL_SYSTEMS:
        if needle in system_key:
            return system
    if str(entry.get('missionType') or '').upper() in PVP_TYPES:
        # A Conclave map carries a Star Chart node's name; for a player it is the Conclave.
        return 'Conclave'
    if any(system_key.startswith(prefix) for prefix in STAR_CHART_KEY_PREFIXES) \
            and not any(bad in system_key for bad in STAR_CHART_KEY_EXCLUDE):
        return 'Star Chart'
    return None


def region_for(entry, dictionary):
    """The region a player would name: the export's own system text ("Venus Proxima", "Venus")."""
    text = _english(dictionary, entry.get('systemName'))
    if text:
        return REGION_ALIAS.get(text, text)
    if is_railjack(entry):
        # The export carries no localised system text for this one; the key is the only fact.
        key = str(entry.get('systemName') or '').rsplit('/', 1)[-1]
        if key.endswith('_SPACE'):
            return key[:-len('_SPACE')] + ' Proxima'
    return None


def build_index(regions_doc, dictionary):
    """{node display name: [hierarchy records]} from the export + the English dictionary."""
    index = {}
    for key, entry in (regions_doc or {}).items():
        if not isinstance(entry, dict):
            continue
        name = _english(dictionary, entry.get('name'))
        if not name:
            continue
        rec = {
            'node': name,
            'region': region_for(entry, dictionary),
            'system': system_for(entry, dictionary),
            'mission_type': entry.get('missionType'),
            'node_type': entry.get('nodeType'),
            'region_key': key,
            'region_name_key': entry.get('name'),
            'system_name_key': entry.get('systemName'),
        }
        index.setdefault(name, []).append(rec)
    return index


def known_regions(regions_doc, dictionary):
    """{English region name: its navigation system or None} for every region the game exports.

    Used to decide whether a drop-table label is a place a player can actually select, and which
    system it belongs to, without hard-coding a planet list: 'Mercury' -> Star Chart, 'Veil Proxima'
    -> Railjack, 'Dark Refractory, Deimos' -> None (the export files it under a family this module
    does not claim to know), 'Nowhere' -> not present at all.
    """
    names = {}
    for entry in (regions_doc or {}).values():
        if not isinstance(entry, dict):
            continue
        text = _english(dictionary, entry.get('systemName'))
        if not text:
            continue
        text = REGION_ALIAS.get(text, text)
        system = system_for(entry, dictionary)
        if text not in names or (names[text] is None and system):
            names[text] = system
    return names


def load_all(offline=True):
    """(index, dictionary, region names) from the cached export files."""
    files = fetch(offline=offline)
    regions = json.loads(files['ExportRegions.json'].decode('utf-8', 'replace')) \
        if 'ExportRegions.json' in files else {}
    dictionary = json.loads(files['dict.en.json'].decode('utf-8', 'replace')) \
        if 'dict.en.json' in files else {}
    return build_index(regions, dictionary), dictionary, known_regions(regions, dictionary)


def load_index(offline=True):
    """(index, dictionary) - kept for callers that do not need the region names."""
    index, dictionary, _known = load_all(offline=offline)
    return index, dictionary


def _candidates(index, node, mode):
    """Every export record whose display name matches, best first.  No fuzzy matching."""
    wanted = [r for r in index.get(node, []) if r.get('system')]
    if not wanted:
        return []
    if mode and mode != 'Caches':
        railjack = [r for r in wanted if r.get('system') == 'Railjack']
        if railjack and str(mode).lower() in ('skirmish', 'volatile', 'orphix', 'defense',
                                              'exterminate', 'survival', 'sabotage', 'spy'):
            # A Railjack node and a Star Chart node can share a display name; the drop table's
            # game mode is the tiebreaker, and only between the two systems we can name.
            return railjack + [r for r in wanted if r not in railjack]
    return wanted


def _candidates_ci(index, node):
    """Case-insensitive fallback: DE's two datasets spell a few nodes differently
    ('Kala-Azar' in the drop table, 'Kala-azar' in the region export).  A case-only difference is
    recorded as such rather than passed off as an exact match."""
    lowered = str(node or '').strip().lower()
    out = []
    for name, recs in index.items():
        if name.lower() == lowered and name != node:
            out.extend(r for r in recs if r.get('system'))
    return out


# The drop table puts the reward-table variant inside the node key, not in the gameMode field:
# `Falling Glory (Caches)` / `Bifrost Echo (Extra)`.  The node is the same node.
VARIANT_IN_KEY = re.compile(r'\s*\((caches|extra)\)\s*$', re.I)


def split_key(node):
    """(node name, variant) - the node key with its reward-table suffix removed."""
    match = VARIANT_IN_KEY.search(str(node or ''))
    if not match:
        return str(node or '').strip(), None
    return VARIANT_IN_KEY.sub('', str(node or '')).strip(), match.group(1).lower()


def edit_system(planet):
    """The drop table's own label, as a system name when it is one ('Veil Proxima' -> Railjack)."""
    text = str(planet or '').strip()
    if text.endswith(' Proxima'):
        return 'Railjack', text
    return None, None


def calibrate(missions, index):
    """mode -> missionType, voted by the rows that are unambiguous.  Derived from DE's own export,
    so a mode that the export does not carry simply gets no entry and matching falls back to the
    region consistency check rather than to a guess."""
    votes = {}
    for planet, nodes in (missions or {}).items():
        for key, row in (nodes or {}).items():
            if not isinstance(row, dict):
                continue
            base, _variant = split_key(key)
            mode = str(row.get('gameMode') or '').strip()
            if not base or not mode or mode in ('Caches',):
                continue
            cands = [r for r in index.get(base, []) if r.get('system')]
            if len(cands) != 1:
                continue
            rec = cands[0]
            # Only trust the vote when the single candidate sits in a region that matches the
            # drop-table label: planet -> planet, or planet -> "<planet> Proxima".
            regions = {str(rec.get('region') or '')}
            if not (regions & {str(planet), '%s Proxima' % planet}):
                continue
            votes.setdefault(mode, {})
            votes[mode][rec.get('mission_type')] = votes[mode].get(rec.get('mission_type'), 0) + 1
    return {mode: max(counts.items(), key=lambda kv: kv[1])[0] for mode, counts in votes.items()}


def score(rec, planet, mode, types):
    """How well one export record fits a drop-table row.  Higher is better; ties are ambiguity."""
    score = 0
    region = str(rec.get('region') or '')
    label = str(planet or '').strip()
    if region and region == label:
        score += 8
    elif region and region == '%s Proxima' % label:
        score += 8
    elif region:
        score += 1
    want = types.get(mode)
    if want and rec.get('mission_type') == want:
        score += 4
    if rec.get('system') == 'Conclave' and mode and mode != 'Conclave':
        score -= 6
    if rec.get('system') == 'Railjack' and not want:
        # Skirmish/Volatile/Orphix only exist in Railjack; the export says so by mission type.
        if str(mode).lower() in ('skirmish', 'volatile', 'orphix'):
            score += 6
    return score


def resolve(planet_label, node, mode=None, index=None, dictionary=None, types=None, known=None):
    """One drop-table mission row -> the hierarchy a player can navigate to.

    Returns a dict with `system` / `region` / `node` / `mode` / `variant` and, when something could
    not be verified, `unresolved` naming exactly which part.  `planet_label` is kept as
    `drop_table_label` (provenance), never used as the region unless the game's own export uses it
    as a region name too.
    """
    if index is None:
        index, _dictionary, known = load_all()
    known = known if known is not None else {}
    base, variant = split_key(node)
    mode = str(mode or '').strip() or None
    types = types or {}
    match = 'exact'
    cands = _candidates(index, base, mode)
    if not cands:
        cands = _candidates_ci(index, base)
        if cands:
            match = 'case-insensitive'
    ranked = sorted(cands, key=lambda r: -score(r, planet_label, mode, types))
    label = str(planet_label or '').strip()
    label_system, label_region = edit_system(label)
    label_system = label_system or LABEL_SYSTEM.get(label)
    if not label_system and label in known:
        # The label is a region the game's own export lists, so it is a place a player can pick -
        # with the system the export gives that region, which may be None when the export files it
        # under a family this module does not know.
        label_system, label_region = known.get(label), label
    rec = {
        'drop_table_label': planet_label,
        'node_key': node,
        'node': base,
        'variant': variant,
        'mode': mode,
        'match': match,
        'system': None,
        'region': None,
        'region_source': None,
        'unresolved': [],
    }
    if not ranked:
        # The node is not in the game's export.  Show the part that IS verified - the system and
        # region the drop table's own label names, when that label is a region the export knows -
        # and say plainly that the node could not be confirmed.
        rec['system'] = label_system
        rec['region'] = label_region or (label if label_system else None)
        if rec['system'] and rec['region']:
            rec['region_source'] = 'drop table label (%s)' % label
            rec['unresolved'].append('node not in the game export (may be retired or renamed)')
        elif rec['region']:
            rec['region_source'] = 'drop table label (%s)' % label
            rec['unresolved'].append('navigation system not confirmed for this region')
        else:
            rec['unresolved'].append('node not in the game export')
        return rec
    best = ranked[0]
    tied = [r for r in ranked
            if score(r, planet_label, mode, types) == score(best, planet_label, mode, types)
            and r.get('region') != best.get('region')]
    rec['system'] = best.get('system') or label_system
    rec['region'] = best.get('region')
    rec['node'] = best.get('node') or base
    if match == 'case-insensitive':
        rec['node'] = base
    rec['region_source'] = 'game export: %s' % (best.get('system_name_key') or '')
    if not rec['region']:
        rec['region'] = label_region or (label if label_system else None)
        rec['unresolved'].append('region text not in the export dictionary')
    if best.get('system') and label_system and best['system'] != label_system:
        # The drop table's label and the export's system disagree (Venus vs Railjack): the export
        # wins, and the disagreement is recorded rather than hidden.
        rec['label_system'] = label_system
    if tied:
        rec['unresolved'].append('node name appears in more than one region (%s)'
                                 % ', '.join(sorted({str(r.get('region')) for r in ranked})))
    return rec


def label(rec):
    """The one-line answer a card shows: `Railjack -> Venus Proxima -> Falling Glory`.

    When the region and the system are the same place (Duviri, Hollvania) it is named once: the
    hierarchy still reads in order, it just does not stutter.
    """
    system, region, node = rec.get('system'), rec.get('region'), rec.get('node')
    parts = [system]
    if region and region != system:
        parts.append(region)
    parts.append(node)
    return ' \u2192 '.join([p for p in parts if p])


def lookup_region(name, index=None):
    """(system, region) for a bare name the drop table uses as a *node* name, or None.

    Key/quest reward tables are named after the mission they open ("Mutalist Alad V Assassinate"),
    so the name can be resolved the same way a node is - and when it cannot, the caller says so
    instead of guessing a system.
    """
    if not name:
        return None
    if index is None:
        index, _dictionary, _known = load_all()
    for rec in (index.get(str(name)) or []):
        if rec.get('system') and rec.get('region'):
            return rec['system'], rec['region']
    return None


def reward_source(mode, rotation=None, bucket=None, variant=None, system=None):
    """How the item is obtained (mission completion, cache, bounty stage, ...), not just where."""
    if bucket in ('bounty', 'bounties'):
        return 'bounty stage'
    if bucket == 'vendor':
        return 'vendor'
    if bucket == 'quest':
        return 'quest'
    if bucket == 'enemy':
        return 'enemy drop'
    if bucket == 'relic':
        return 'relic reward'
    if variant == 'caches':
        # The same node carries a second table for its caches; Railjack names them its own way.
        return 'railjack cache' if system == 'Railjack' else 'sabotage cache'
    if variant == 'extra':
        return 'bonus reward table'
    key = str(mode or '').strip()
    if key in SOURCE_FOR_MODE:
        return SOURCE_FOR_MODE[key]
    if key:
        return 'mission completion'
    return None


def load_index(offline=True):
    """(index, dictionary) from the cached export files.  Missing files are not an error: the
    caller gets an empty index and every lookup reports itself unresolved."""
    files = fetch(offline=offline)
    regions = json.loads(files['ExportRegions.json'].decode('utf-8', 'replace')) \
        if 'ExportRegions.json' in files else {}
    dictionary = json.loads(files['dict.en.json'].decode('utf-8', 'replace')) \
        if 'dict.en.json' in files else {}
    return build_index(regions, dictionary), dictionary


def report(files=None):
    """What the cache resolves today, including the mode -> missionType calibration."""
    index, dictionary = load_index()
    missions = _missions()
    types = calibrate(missions, index) if missions else {}
    systems = {}
    for name, recs in index.items():
        for rec in recs:
            systems[rec.get('system')] = systems.get(rec.get('system'), 0) + 1
    print('export regions cached: %d display names, %d records'
          % (len(index), sum(len(v) for v in index.values())))
    print('dictionary entries: %d' % len(dictionary))
    for system, n in sorted(systems.items(), key=lambda kv: -(kv[1] or 0)):
        print('  %-22s %4d' % (system, n))
    print('mode -> missionType, voted from the export:')
    for mode in sorted(types):
        print('  %-16s %s' % (mode, types[mode]))
    for planet, node, mode in (('Venus', 'Falling Glory', 'Skirmish'),
                               ('Venus', 'Luckless Expanse (Caches)', 'Caches'),
                               ('Venus', 'Malva', 'Survival'),
                               ('Veil Proxima', 'Arc Silver', 'Skirmish'),
                               ('Duviri', 'The Circuit', 'The Circuit')):
        rec = resolve(planet, node, mode, index=index, types=types)
        print('%-34s -> %s%s' % ('%s/%s' % (planet, node), label(rec),
                                 ('  [unresolved: %s]' % '; '.join(rec['unresolved']))
                                 if rec['unresolved'] else ''))


def _missions():
    path = os.path.join(DATA, 'dropdata', 'missionRewards.json')
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as fh:
        doc = json.load(fh)
    root = doc.get('missionRewards') if isinstance(doc, dict) else doc
    return root if isinstance(root, dict) else {}


def coverage():
    """How many drop-table mission rows the export can place, and why the rest cannot be."""
    import collections
    index, _dictionary, known = load_all()
    missions = _missions()
    types = calibrate(missions, index)
    rows = placed = unconfirmed = systemless = 0
    reasons = collections.Counter()
    systems = collections.Counter()
    for planet, nodes in missions.items():
        for key, row in (nodes or {}).items():
            if not isinstance(row, dict):
                continue
            rows += 1
            rec = resolve(planet, key, row.get('gameMode'), index=index, types=types, known=known)
            for reason in rec['unresolved']:
                reasons[re.split(r'\s*\(', reason)[0]] += 1
            if 'node not in the game export (may be retired or renamed)' in rec['unresolved']:
                unconfirmed += 1          # system + region named from the label, node unconfirmed
            elif not rec['unresolved']:
                placed += 1               # the node itself is in the game export
            elif not rec['system']:
                systemless += 1           # nothing but the drop-table label
            systems[rec['system']] += 1
    return {'rows': rows, 'nodes_placed_from_the_export': placed,
            'nodes_unconfirmed': unconfirmed, 'system_unknown': systemless,
            'reasons': dict(reasons), 'systems': {str(k): v for k, v in systems.items()},
            'types': types}


def selftest():
    """Offline checks over the cached export, plus the logic checks that need no data at all."""
    out = []

    def check(name, ok, detail=''):
        out.append((name, bool(ok), detail))

    # logic: no data needed
    rec = resolve('Nowhere', 'Missing Node', 'Survival', index={}, dictionary={})
    check('a node the export does not describe keeps the drop table wording', rec['node'] == 'Missing Node')
    check('and it says what could not be verified', 'node not in the game export' in rec['unresolved'])
    check('an unresolved record has no invented system', rec['system'] is None)
    check('a reward-table suffix is not part of the node name',
          split_key('Falling Glory (Caches)') == ('Falling Glory', 'caches')
          and split_key('Bifrost Echo (Extra)') == ('Bifrost Echo', 'extra')
          and split_key('Malva') == ('Malva', None))
    check('a proxima label is a Railjack region, not a planet',
          edit_system('Veil Proxima') == ('Railjack', 'Veil Proxima')
          and edit_system('Venus') == (None, None))
    check('a reward source is named, not inferred from a number',
          reward_source('Caches') == 'sabotage cache' and reward_source('Survival') == 'mission completion'
          and reward_source(None, bucket='bounty') == 'bounty stage')
    check('the label is the game hierarchy, joined',
          label({'system': 'Railjack', 'region': 'Venus Proxima', 'node': 'Falling Glory'})
          == 'Railjack \u2192 Venus Proxima \u2192 Falling Glory')

    # real data, from the cached export
    try:
        index, dictionary = load_index()
    except Exception as exc:                                     # pragma: no cover - no cache
        check('export cache is readable', False, str(exc))
        index, dictionary = {}, {}
    if index:
        types = calibrate(_missions(), index)
        rec = resolve('Venus', 'Falling Glory', 'Skirmish', index=index, types=types)
        check('Falling Glory is Railjack, in Venus Proxima',
              (rec['system'], rec['region'], rec['node']) == ('Railjack', 'Venus Proxima', 'Falling Glory'),
              json.dumps(rec))
        check('and the drop table label is kept as provenance, not as the region',
              rec['region'] != 'Venus' and rec['drop_table_label'] == 'Venus')
        rec = resolve('Venus', 'Falling Glory (Caches)', 'Caches', index=index, types=types)
        check('the cache table is the same node, named as the variant it is',
              (rec['region'], rec['node'], rec['variant']) == ('Venus Proxima', 'Falling Glory', 'caches'),
              json.dumps(rec))
        rec = resolve('Venus', 'Malva', 'Survival', index=index, types=types)
        check('a real Star Chart node stays Star Chart / Venus',
              (rec['system'], rec['region']) == ('Star Chart', 'Venus'), json.dumps(rec))
        rec = resolve('Veil Proxima', 'Arc Silver', 'Skirmish', index=index, types=types)
        check('a Veil Proxima node resolves to Railjack -> Veil Proxima',
              (rec['system'], rec['region']) == ('Railjack', 'Veil Proxima'), json.dumps(rec))
        check('a Conclave map never stands in for the Star Chart node of the same name',
              resolve('Venus', 'Cytherean', 'Interception', index=index, types=types)['system']
              != 'Conclave')
        check('the mode -> missionType table is voted from the export, not typed in',
              types.get('Survival') == 'MT_SURVIVAL' and types.get('Skirmish') == 'MT_RAILJACK',
              json.dumps(types))

    for name, ok, detail in out:
        print('%s %s%s' % ('PASS' if ok else 'FAIL', name, ('  <- ' + detail) if (detail and not ok) else ''))
    failed = [n for n, ok, _ in out if not ok]
    print('%d checks, %d failed' % (len(out), len(failed)))
    return 0 if not failed else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--coverage', action='store_true')
    ap.add_argument('--fetch', action='store_true')
    args = ap.parse_args()
    if args.fetch:
        fetch(offline=False)
        print('export cached in %s' % EXPORT_DIR)
        return 0
    if args.report:
        report()
        return 0
    if args.coverage:
        print(json.dumps(coverage(), indent=1, sort_keys=True))
        return 0
    return selftest()


if __name__ == '__main__':
    sys.exit(main())
