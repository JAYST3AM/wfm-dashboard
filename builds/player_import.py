"""Player build import: the game save's current loadout, translated — never guessed.

The importer is pure: it takes an already-decrypted, already-normalised save (see
`scripts/saveio.py`) plus the Phase 1 catalogue and returns a read-only `ImportedBuild` dict.
Reading files, caching and serving live in `scripts/player_loadout.py` and `server.py`.

Phase 3's rule, from the brief: **unknown is better than wrong.** Every imported field carries a
provenance label (`verified` / `derived` / `unknown`), a field this module cannot prove is reported
as unknown rather than defaulted, and a game identifier that does not resolve is kept verbatim
under `unmapped` instead of fuzzy-matched.

The audit behind these rules, with the evidence for each index and each join, is
`docs/player-build-import.md`.
"""
import json

# ------------------------------------------------------------------ provenance

OBSERVED = 'observed'      # directly present in the local source
DERIVED = 'derived'        # deterministically derived from verified data
UNKNOWN = 'unknown'        # unavailable
STALE = 'stale'            # present, but not known to represent the current loadout

# The game's rank-30 requirement. XP is monotonic, so an item at or above this with a 30 cap cannot
# be below rank 30; anything else is left unknown because no local file carries the XP→rank curve.
RANK30_XP = 900000

# ------------------------------------------------------------------ save shapes

# Section → the equipment kind we call it. Order is the order the UI shows the loadout in.
ITEM_SECTIONS = (
    ('Suits', 'warframe'),
    ('LongGuns', 'primary'),
    ('Pistols', 'secondary'),
    ('Melee', 'melee'),
    ('Sentinels', 'sentinel'),
    ('SentinelWeapons', 'sentinel_weapon'),
    ('SpaceSuits', None),          # not in the Phase 1 catalogue: reported as unmapped
    ('SpaceGuns', None),
    ('MechSuits', None),
    ('KubrowPets', None),
    ('Horses', None),
)

# Preset type + key inside the preset, per category.
PRESET_ENTRY = {
    'warframe': ('NORMAL', 's'),
    'primary': ('NORMAL', 'l'),
    'secondary': ('NORMAL', 'p'),
    'melee': ('NORMAL', 'm'),
    'companion': ('SENTINEL', 's'),
    'companion_weapon': ('SENTINEL', 'l'),
}

# Save slot index → the engine's slot kind, verified against the live save (docs/player-build-import.md
# has the evidence). None means the slot exists in the game but the Phase 1 engine does not model it.
CATEGORY_SLOTS = {
    'warframe': [(i, 'normal') for i in range(8)] + [(8, 'aura'), (9, 'exilus'),
                                                     (10, None), (11, None)],
    'primary': [(i, 'normal') for i in range(8)] + [(8, 'exilus'), (9, None)],
    'secondary': [(i, 'normal') for i in range(8)] + [(8, 'exilus'), (9, None)],
    'melee': [(i, 'normal') for i in range(8)] + [(8, 'stance'), (9, 'exilus'), (10, None)],
    'sentinel': [(i, 'normal') for i in range(8)] + [(8, None), (9, None)],
    'sentinel_weapon': [(i, 'normal') for i in range(8)],
}

# Categories whose installed-mod PLACEMENT is verified. The companion layout is not, so a companion
# imports its mods as an unordered set (the brief's own fallback, §12) with slot order unknown.
ORDERED_CATEGORIES = ('warframe', 'primary', 'secondary', 'melee')

# The save's polarity vocabulary in the engine's words. `AP_UNIVERSAL` is a real polarity (the one
# an Omni/Aura/Stance Forma grants), not "no polarity": an unlisted slot is the one with none.
# The planner's storage only accepts these names for a slot polarity (its own cleanV1 gate), so a
# polarity the page cannot store is left out of a clone and counted instead of being written as junk.
STORAGE_POLARITIES = ('madurai', 'naramon', 'vazarin', 'zenurik', 'umbral', 'penjaga', 'unairu')

POLARITY_MAP = {
    'AP_ATTACK': 'madurai',
    'AP_DEFENSE': 'vazarin',
    'AP_TACTIC': 'naramon',
    'AP_POWER': 'zenurik',
    'AP_UNIVERSAL': 'universal',
    'AP_WARD': 'penjaga',
    'AP_PRECEPT': 'penjaga',
    'AP_UMBRA': 'umbral',          # the page's spelling; the engine's catalogue says 'umbra'
    'AP_UNAIRU': 'unairu',
}

# The three configs the game keeps per item.
CONFIG_LABELS = ('A', 'B', 'C')


# ------------------------------------------------------------------ small helpers

def _oid(value):
    """The save nests ids as {'$oid': '...'}; accept a bare string too."""
    if isinstance(value, dict):
        return value.get('$oid')
    if isinstance(value, str):
        return value
    return None


def _entry_count(value):
    if isinstance(value, int):
        return value
    if isinstance(value, dict):
        return value.get('$count')
    return None


def _provenanced(value, confidence, note=None, **extra):
    out = {'value': value, 'confidence': confidence}
    if note:
        out['note'] = note
    out.update(extra)
    return out


def _slug_for(db, unique_name):
    row = (db.get('equipment') or {}).get(unique_name)
    return row


# ------------------------------------------------------------------ the index

def build_index(save):
    """Index the save once: owned items by id, and every mod copy by the id a config points at.

    A config's `Upgrades` array holds either an owned copy's id (resolvable to its mod and rank via
    the top-level `Upgrades` table) or, occasionally, a mod path with no owned copy behind it. Both
    are indexed here, and the second kind is imported with rank unknown.
    """
    items = {}
    for section, category in ITEM_SECTIONS:
        for item in save.get(section) or []:
            if not isinstance(item, dict):
                continue
            oid = _oid(item.get('ItemId'))
            if oid:
                items[oid] = {'section': section, 'category': category, 'item': item}

    copies = {}
    for row in save.get('Upgrades') or []:
        if not isinstance(row, dict):
            continue
        oid = _oid(row.get('ItemId'))
        if not oid:
            continue
        level = None
        fingerprint = row.get('UpgradeFingerprint')
        if isinstance(fingerprint, str):
            try:
                parsed = json.loads(fingerprint)
            except ValueError:
                parsed = {}
            if isinstance(parsed, dict):
                level = parsed.get('lvl')
        copies[oid] = {'unique_name': row.get('ItemType'), 'rank': level, 'source': 'Upgrades'}

    raw_paths = {}
    for row in save.get('RawUpgrades') or []:
        if isinstance(row, dict) and row.get('ItemType'):
            raw_paths[row['ItemType']] = _entry_count(row.get('ItemCount'))

    presets = save.get('LoadOutPresets') or {}
    return {'items': items, 'copies': copies, 'raw_paths': raw_paths, 'presets': presets}


def _preset_entry(index, category):
    preset_type, key = PRESET_ENTRY.get(category, (None, None))
    if not preset_type:
        return None
    presets = index['presets'].get(preset_type) or []
    if not presets:
        return None
    preset = presets[0]
    if not isinstance(preset, dict):
        return None
    entry = preset.get(key)
    return entry if isinstance(entry, dict) else None


# ------------------------------------------------------------------ mods

def resolve_mod(index, db, copy_id):
    """One config entry → (mod row, unique name, rank, provenance, reason) — never a guess.

    The catalogue is keyed BY unique name and its rows do not carry one, so the key travels back
    with the row. Returns `(None, None, None, UNKNOWN, reason)` when the entry cannot be resolved,
    so callers keep the raw id for the `unmapped` list instead of inventing a mod.
    """
    if copy_id in index['copies']:
        row = index['copies'][copy_id]
        unique_name = row['unique_name']
        mod = (db.get('mods') or {}).get(unique_name)
        if not mod:
            return None, None, None, UNKNOWN, 'mod not in the catalogue: ' + str(unique_name)
        return mod, unique_name, row['rank'], OBSERVED, None
    # a bare mod path: the mod is known, the copy (and therefore the rank) is not
    if isinstance(copy_id, str) and copy_id.startswith('/Lotus/'):
        mod = (db.get('mods') or {}).get(copy_id)
        if mod:
            return mod, copy_id, None, UNKNOWN, 'owned copy not in Upgrades: rank unknown'
        return None, None, None, UNKNOWN, 'mod not in the catalogue: ' + copy_id
    return None, None, None, UNKNOWN, 'mod copy not found: ' + str(copy_id)


def _config_slots(index, db, category, config, polarities, unmapped=None, config_index=None):
    """A config's `Upgrades` array → slot entries in save order, plus unsupported entries."""
    upgrades = config.get('Upgrades') if isinstance(config, dict) else None
    if not isinstance(upgrades, list):
        return [], [], False
    layout = dict(CATEGORY_SLOTS.get(category) or [])
    ordered = category in ORDERED_CATEGORIES
    slots, unsupported = [], []
    next_normal = 0
    for save_index, entry_raw in enumerate(upgrades):
        copy_id = entry_raw
        if isinstance(entry_raw, dict):          # some writers keep the whole entry here
            copy_id = _oid(entry_raw.get('ItemId')) or entry_raw.get('ItemType')
        if copy_id in ('', None, '-1'):
            continue
        if isinstance(copy_id, dict):            # still not an id: an empty placeholder slot
            continue
        kind = layout.get(save_index) if ordered else 'normal'
        if ordered and save_index not in layout:
            kind = None
        mod, unique_name, rank, confidence, reason = resolve_mod(index, db, copy_id)
        entry = {
            'save_index': save_index,
            'kind': kind,
            'index': (save_index if kind == 'normal' else 0) if (ordered and kind) else None,
            'mod': None if not mod else {'uniqueName': unique_name, 'name': mod.get('name'),
                                         'slug': mod.get('slug'),
                                         'max_rank': mod.get('max_rank')},
            'mod_rank': rank,
            'polarity': polarities.get(save_index),   # already in the engine's words
            'confidence': confidence if mod else UNKNOWN,
            'raw': None if mod else copy_id,
        }
        if not ordered:
            entry['index'] = next_normal
            next_normal += 1
        if reason:
            entry['reason'] = reason
            if unmapped is not None and not mod:
                letter = (CONFIG_LABELS[config_index]
                          if isinstance(config_index, int) and 0 <= config_index < len(CONFIG_LABELS)
                          else '?')
                where = '%s.config%s.slot%s' % (category, letter, save_index)
                if not any(u.get('raw') == copy_id and u.get('where') == where for u in unmapped):
                    unmapped.append({'raw': copy_id, 'where': where})
        if kind is None:
            entry['unsupported'] = ('the engine does not model this slot'
                                    if mod else 'unresolved entry in an unsupported slot')
            unsupported.append(entry)
        else:
            slots.append(entry)
    return slots, unsupported, True


def _rank_from_xp(xp, max_rank):
    """Only the safe case: at or above the rank-30 requirement on a 30-capped item."""
    if xp is None:
        # GPT review (2026-09-29): an ABSENT field is not a zero. Only a recorded value may be
        # read as one - "I cannot derive anything but 0" is not "the rank is 0".
        if max_rank:
            return None, UNKNOWN, 'the save records no XP for this item'
        return None, UNKNOWN, 'no XP for this item in the save'
    if xp == 0 and max_rank:
        return 0, DERIVED, 'the save records zero XP, so the item has never ranked'
    if not max_rank:
        return None, UNKNOWN, 'no XP for this item in the save'
    if max_rank <= 30 and xp >= RANK30_XP:
        return max_rank, DERIVED, 'XP at or above the rank-30 requirement (%d)' % RANK30_XP
    if max_rank > 30:
        return None, UNKNOWN, 'a %d-rank item has no curve in any local file' % max_rank
    return None, UNKNOWN, 'below the rank-30 requirement, so the exact rank is not derivable'


# ------------------------------------------------------------------ one category

def import_category(index, db, category, *, unmapped):
    """The imported build for one category, or None when the category is not in the loadout."""
    entry = _preset_entry(index, category)
    if not entry:
        return None
    oid = _oid(entry.get('ItemId'))
    owned = index['items'].get(oid)
    item = owned['item'] if owned else None
    unique_name = item.get('ItemType') if item else None
    row = _slug_for(db, unique_name) if unique_name else None

    unknown_fields = []
    out = {'category': category}

    if not unique_name:
        out['equipment'] = _provenanced(None, UNKNOWN, 'no item id in the preset entry')
        out['unknown_fields'] = ['equipment']
        out['unmapped'] = [{'raw': oid, 'where': category + '.equipment'}]
        return out
    if not row:
        unmapped.append({'raw': unique_name, 'where': category + '.equipment'})
        out['equipment'] = {'value': {'uniqueName': unique_name}, 'confidence': UNKNOWN,
                            'note': 'not in the Phase 1 catalogue'}
        out['config'] = _provenanced(None, UNKNOWN)
        out['configs'] = []
        out['unknown_fields'] = ['equipment', 'config', 'configs']
        return out

    out['equipment'] = _provenanced({'uniqueName': unique_name, 'id': row.get('id'),
                                     'slug': row.get('slug'), 'name': row.get('name'),
                                     'kind': row.get('kind')}, OBSERVED)

    rank, rank_conf, rank_note = _rank_from_xp(item.get('XP'), row.get('max_rank'))
    out['equipment_rank'] = _provenanced(rank, rank_conf, rank_note, max_rank=row.get('max_rank'),
                                         xp=item.get('XP'))
    if rank_conf == UNKNOWN:
        unknown_fields.append('equipment_rank')

    config_index = entry.get('mod')
    if isinstance(config_index, int) and 0 <= config_index < len(CONFIG_LABELS):
        out['config'] = _provenanced(config_index, OBSERVED, label=CONFIG_LABELS[config_index])
    else:
        out['config'] = _provenanced(None, UNKNOWN, 'the preset entry carries no config index')
        unknown_fields.append('config')

    # polarities: the save keeps one map per item and does not attribute it to a config. The
    # positions corroborate the ACTIVE config's layout (each installed mod sits in a slot whose
    # polarity has that mod's own type), so the active config gets them and the others are unknown.
    polarities = {}
    for p in item.get('Polarity') or []:
        if isinstance(p, dict) and isinstance(p.get('Slot'), int):
            mapped = POLARITY_MAP.get(p.get('Value'))
            if mapped:
                polarities[p['Slot']] = mapped
    unknown_pol = {p.get('Value') for p in item.get('Polarity') or []
                   if isinstance(p, dict) and p.get('Value') not in POLARITY_MAP}

    configs = item.get('Configs') or []
    out['configs'] = []
    for i, config in enumerate(configs):
        active = out['config']['value'] == i
        slots, unsupported, has_key = _config_slots(index, db, category, config,
                                                    polarities if active else {},
                                                    unmapped=unmapped, config_index=i)
        cfg = {'index': i, 'label': CONFIG_LABELS[i] if i < len(CONFIG_LABELS) else None,
               'slots': slots, 'unsupported': unsupported,
               'polarities': (_provenanced(polarities, OBSERVED) if active and polarities
                              else _provenanced({}, UNKNOWN,
                                                'the save attributes its polarity map to no '
                                                'single config'))}
        if not has_key:
            cfg['mods_available'] = False
            cfg['note'] = 'no mods are installed in this config'
        if not active and polarities:
            cfg['polarity_note'] = 'polarity map shown for the active config only'
        out['configs'].append(cfg)
    if not configs:
        out['configs_available'] = False
        unknown_fields.append('configs')

    out['forma_count'] = _provenanced(item.get('Polarized'), DERIVED,
                                      'the save counter of applied Forma; slot history is not '
                                      'reconstructed')
    out['features_bitmask'] = _provenanced(item.get('Features'), OBSERVED,
                                           'not decoded: no local source documents the bits')
    unknown_fields.append('catalyst_reactor')
    unknown_fields.append('exilus_unlocked')
    if unknown_pol:
        out['polarity_unmapped'] = sorted(x for x in unknown_pol if x)
        unknown_fields.append('polarity_unmapped')
    out['unknown_fields'] = unknown_fields
    return out


# ------------------------------------------------------------------ the build

def import_loadout(save, db, *, source=None, source_timestamp=None, imported_timestamp=None,
                   now=None):
    """The whole current loadout, read-only, with provenance and an explicit unknown list."""
    index = build_index(save)
    unmapped = []
    categories = {}
    for category in ('warframe', 'primary', 'secondary', 'melee', 'companion',
                     'companion_weapon'):
        imported = import_category(index, db, category, unmapped=unmapped)
        if imported:
            categories[category] = imported

    unknown_fields = []
    for category, imported in sorted(categories.items()):
        for field in imported.get('unknown_fields') or []:
            unknown_fields.append(category + '.' + field)
    if not categories:
        unknown_fields.append('loadout')

    return {
        'kind': 'imported_build',
        'source': source or 'alecaframe-save',
        'source_timestamp': source_timestamp,
        'imported_timestamp': imported_timestamp,
        'freshness': freshness(source_timestamp, imported_timestamp, now=now),
        'preset': _provenanced('NORMAL', DERIVED,
                               'the save carries exactly one preset per type, so there is no '
                               'other candidate; no explicit active-preset index exists'),
        'categories': categories,
        'unknown_fields': unknown_fields,
        'unmapped': unmapped,
        'unknown_fields_note': 'unknown is better than wrong: these fields are absent from the '
                               'local source, not zero',
    }


def freshness(source_timestamp, imported_timestamp=None, now=None, stale_after_s=86400):
    """Freshness of the snapshot. Stale is a claim about the SOURCE, not about the import."""
    if source_timestamp is None:
        return {'source_age_s': None, 'stale': None, 'warning': None,
                'label': 'Source timestamp unavailable.'}
    reference = now if now is not None else imported_timestamp
    age = None if reference is None else max(0, int(reference - source_timestamp))
    stale = None if age is None else age > stale_after_s
    if age is None:
        label = 'Import time unknown.'
    elif age < 90:
        label = 'Last seen just now' if age < 5 else 'Last seen %d seconds ago' % age
    elif age < 5400:
        minutes = age // 60
        label = 'Last seen 1 minute ago' if minutes == 1 else 'Last seen %d minutes ago' % minutes
    elif age < 172800:
        hours = age // 3600
        label = 'Last seen 1 hour ago' if hours == 1 else 'Last seen %d hours ago' % hours
    else:
        days = age // 86400
        label = 'Last seen 1 day ago' if days == 1 else 'Last seen %d days ago' % days
    # The label is a label; the warning is its own field so a caller cannot be tempted to glue
    # them into one long string (the copy budget is per text node: 8 words).
    warning = 'Current loadout could not be verified as live.' if stale else None
    return {'source_age_s': age, 'stale': stale, 'label': label, 'warning': warning,
            'stale_after_s': stale_after_s}


# ------------------------------------------------------------------ clone

def clone_to_planner(imported, category, config_name='A', master=None):
    """Translate ONE imported category into a planner storage document.

    Only known fields are written. Anything unknown is left out rather than defaulted, and the
    caller shows the returned `unknown_fields` beside the clone button. The imported snapshot is
    never referenced by the result: the clone is plain data from the start.
    """
    cfg = (imported.get('categories') or {}).get(category)
    if not cfg:
        return {'ok': False, 'error': 'nothing imported for ' + category}
    equipment = (cfg.get('equipment') or {}).get('value') or {}
    if not equipment.get('slug'):
        return {'ok': False, 'error': 'the imported item is not in the catalogue',
                'unmapped': (cfg.get('equipment') or {}).get('value')}

    source_config = cfg.get('config') or {}
    want_index = CONFIG_LABELS.index(config_name) if config_name in CONFIG_LABELS else None
    if want_index is None:
        return {'ok': False, 'error': 'unknown config name'}
    source_cfg = next((c for c in cfg.get('configs') or [] if c.get('index') == want_index), None)
    if source_cfg is None:
        return {'ok': False, 'error': 'the source does not carry config ' + config_name}

    slots = {}
    unknown_mods = []
    for entry in source_cfg.get('slots') or []:
        mod = entry.get('mod') or {}
        if not mod.get('uniqueName'):
            unknown_mods.append(entry)
            continue
        kind = entry.get('kind') or 'normal'
        # the page's storage vocabulary: normal slots carry their index, everything else is bare
        key = ('normal:%s' % entry.get('index')) if kind == 'normal' else kind
        slot = {'id': mod['uniqueName']}
        if entry.get('mod_rank') is not None:
            slot['rank'] = entry['mod_rank']
        # never max a mod: with no rank in the source the field is left out entirely (the planner
        # reads an absent rank as the mod's base value) and the count is reported to the UI
        slots[key] = slot

    polarities = {}
    pol_block = source_cfg.get('polarities') or {}
    dropped_polarities = []
    if pol_block.get('confidence') == OBSERVED:
        for save_index, name in (pol_block.get('value') or {}).items():
            try:
                save_index = int(save_index)
            except (TypeError, ValueError):
                continue
            kind = dict(CATEGORY_SLOTS.get(category) or []).get(save_index)
            if name not in STORAGE_POLARITIES:
                dropped_polarities.append(name)
                continue
            if kind == 'normal':
                polarities['normal:%s' % save_index] = name
            elif kind:
                polarities[kind] = name          # the page's storage keys aura/exilus/stance bare

    equipment_id = equipment.get('id') or equipment.get('uniqueName')
    doc = {'version': 1, 'equipment_id': equipment_id, 'active_config': config_name,
           'configs': {name: {'slots': {}, 'polarities': {}}
                       for name in CONFIG_LABELS},
           'library': {'q': '', 'polarity': '', 'slot': '', 'sort': 'name',
                       'hide_refused': False},
           'ui': {'trace': None}}
    if master is not None:
        doc['mastery_rank'] = master
    rank_block = cfg.get('equipment_rank') or {}
    if rank_block.get('value') is not None:
        doc['equipment_rank'] = rank_block['value']
    doc['configs'][config_name]['slots'] = slots
    doc['configs'][config_name]['polarities'] = polarities

    unknown = ['equipment_rank', 'mastery_rank', 'catalyst_reactor', 'exilus_unlocked']
    if rank_block.get('value') is not None:
        unknown.remove('equipment_rank')
    if master is not None:
        unknown.remove('mastery_rank')
    return {
        'ok': True,
        'doc': doc,
        'from_config': source_config.get('label'),
        'unknown_fields': unknown,
        'unknown_mods': len(unknown_mods),
        'dropped_polarities': sorted(set(dropped_polarities)),
        'rank_unknown_mods': sum(1 for s in slots.values() if 'rank' not in s),
        'note': 'clone of the imported snapshot; the snapshot itself is never modified',
    }
