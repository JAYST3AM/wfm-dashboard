#!/usr/bin/env python3
"""Mod effects: WFCD stat strings -> structured, per-rank, source-tagged values.

Why this exists (brief sections 5, 11, 16)
  * "Do not assume every mod effect can be represented by one naive linear formula
    unless verified." The authoritative shape is the per-rank table WFCD ships in
    `levelStats` (rank 0..fusionLimit, straight from DE's export): this module reads
    that table as the truth and only *also* reports whether the progression happens to
    be linear (useful for verifying formulas and for spotting data drift).
  * "Never silently approximate." A stat line this module cannot map to a canonical
    stat is preserved verbatim as an unmodelled effect, and the mod is flagged, so the
    engine can refuse rather than invent a number.
  * Every effect carries the line it came from, so a wrong number can be traced back to
    the data, not to a guess.

Nothing here reads files or the network; it is string -> structure.
"""
import re

from . import schema

# WFCD markup in stat strings: <DT_FIRE_COLOR>, <DT_SLASH>, <LINE_SEPARATOR>, literal \n.
MARKUP_RE = re.compile(r'<[^>]{0,64}>')
ESCAPED_NL_RE = re.compile(r'\\n')

# A stat line is "<optional prefix> <signed number><%?> <tail>" (or prose with no number).
NUMBER_RE = re.compile(r'([+-]?\d+(?:\.\d+)?)\s*(%)?')
# Words that make an effect conditional (it does not apply to the base calculation).
# Kept narrow on purpose: Phase 1 must not refuse a plain stat because it happens to
# contain a filler word. "for 20s"-style timers are matched separately below.
HARD_MARKERS = (
    'on kill', 'on hit', 'on reload', 'on headshot', 'on status', 'on critical',
    'on slam', 'on roll', 'on dodge', 'stacks up to', 'stack up to', 'per status',
    'per stack', 'for each', 'each time', 'when ', 'while ', 'after ', 'upon ',
    'during ',
)
SECONDS_RE = re.compile(r'\bfor \d+(?:\.\d+)?\s*s\b')
# Prefixes that mark a non-self (squad/enemy) effect: parsed for display, never
# applied to the owner's stats. Corrosive Projection's "-18% Armor" is an enemy debuff.
NON_SELF_PREFIXES = ('squad', 'allies', 'allies gain', 'enemies', 'enemy', 'teammates',
                     'companions', 'summons', 'for each ally')

# How each canonical stat stacks (brief: stacking category, additive/multiplicative).
# 'base'      additive with other base-damage bonuses, multiplied into total damage
# 'physical'  additive among themselves, applied to the modded base of that type
# 'elemental' additive among themselves, applied to the modded base damage
# 'faction'   a separate multiplier, applied after everything (not shown in-arsenal)
# 'flat'      a flat value or percentage-point addition, never a multiplier
STAT_CATEGORY = {
    'damage': 'base', 'damage_on_first_shot': 'base',
    'impact': 'physical', 'puncture': 'physical', 'slash': 'physical',
    'heat': 'elemental', 'cold': 'elemental', 'electricity': 'elemental',
    'toxin': 'elemental', 'blast': 'elemental', 'radiation': 'elemental',
    'gas': 'elemental', 'magnetic': 'elemental', 'viral': 'elemental',
    'corrosive': 'elemental',
    'faction_grineer': 'faction', 'faction_corpus': 'faction',
    'faction_infested': 'faction', 'faction_corrupted': 'faction',
    'faction_murmur': 'faction', 'faction_orokin': 'faction',
    'faction_sentient': 'faction',
    'punch_through': 'flat', 'range': 'flat', 'combo_duration': 'flat',
    'energy_regen': 'flat', 'enemy_radar': 'flat', 'loot_radar': 'flat',
    'blast_range': 'flat',
}

# Mod names that carry a faction bonus, so "Bane of Grineer" maps to a faction stat
# instead of a generic unmodelled line. WFCD exposes faction mods as "+30% Damage to
# Grineer"-style prose; the tail vocabulary below handles the common spellings.
FACTION_TAIL = {
    'grineer': 'faction_grineer', 'corpus': 'faction_corpus',
    'infested': 'faction_infested', 'corrupted': 'faction_corrupted',
    'orokin': 'faction_corrupted', 'murmur': 'faction_murmur',
    'sentient': 'faction_sentient', 'hunhow': 'faction_sentient',
    'narmer': 'faction_narmer', 'the grineer': 'faction_grineer',
}

CLASS_FLAGS = {
    'primed': ('primed ',),
    'umbral': ('umbral ',),
    'galvanized': ('galvanized ',),
    'archon': ('archon ',),
    'amalgam': ('amalgam ',),
    'flawed': ('flawed ',),
    'riven': ('riven', 'veiled'),
    'sacrificial': ('sacrificial ',),
}


def clean_stat_text(line):
    """Strip WFCD markup from a stat string; keep signs and words intact."""
    out = ESCAPED_NL_RE.sub(' ', str(line or ''))
    out = MARKUP_RE.sub('', out)
    out = out.replace('\r', ' ').replace('\n', ' ')
    return re.sub(r'\s+', ' ', out).strip()


def is_conditional(text):
    """Does this stat line only apply under a condition? (Galvanized stacks, "on kill")"""
    low = ' ' + text.strip().lower()
    if any(marker in low for marker in HARD_MARKERS):
        return True
    return bool(SECONDS_RE.search(low))


SIGNED_NUMBER_RE = re.compile(r'[-+]?\d+(?:\.\d+)?')


def stat_signature(text):
    """Collapse a stat line to the shape of the stat it names.

    The same unmodelled stat appears once per rank with a different number
    ("+5% Rifle Damage" ... "+30% Rifle Damage"); without collapsing them a mod would
    report one refusal per rank. Numbers become '#', so all six collapse to one
    signature and therefore one marker.
    """
    out = clean_stat_text(text).lower()
    out = SIGNED_NUMBER_RE.sub('#', out)
    return re.sub(r'\s+', ' ', out).strip()


def _canonical_stat(tail, prefix=''):
    """Map a stat-line tail (and any non-self prefix) to (stat_id, unit) or (None, None).

    The tail is matched case-insensitively against schema.STAT_VOCABULARY. A tail with a
    non-self prefix ("Squad receives ...", "Enemies lose ...") parses its value but never
    becomes an owner stat: it is info, not math.
    """
    key = tail.strip().strip('.').lower()
    key = re.sub(r'\s+', ' ', key)
    if prefix:
        return None, None
    if key in schema.STAT_VOCABULARY:
        return schema.STAT_VOCABULARY[key]
    # "+X% Damage to Grineer" / "Damage to Grineer" spellings.
    m = re.match(r'^damage to ([a-z\- ]+)$', key)
    if m and m.group(1).strip() in FACTION_TAIL:
        return FACTION_TAIL[m.group(1).strip()], 'percent'
    m = re.match(r'^([a-z\- ]+) damage bonus$', key)
    if m and m.group(1).strip() in FACTION_TAIL:
        return FACTION_TAIL[m.group(1).strip()], 'percent'
    return None, None


def parse_stat_line(line):
    """One WFCD stat string -> an effect dict (or None for an empty line).

    Shape:
        {'text': 'cleaned line', 'stat': canonical id or None, 'value': float,
         'unit': 'percent'|'flat', 'modelled': bool, 'conditional': bool,
         'scope': 'self'|'other', 'prefix': str, 'tail': str}

    `modelled` means the engine has a rule for this stat; `conditional` means it only
    applies under a condition (Galvanized stacks and friends), which Phase 1 refuses to
    apply silently - those land in the unsupported registry instead.
    """
    text = clean_stat_text(line)
    if not text:
        return None
    raw = text
    negative_lead = raw.startswith('-')
    m = NUMBER_RE.search(raw)
    effect = {'text': raw, 'stat': None, 'value': None, 'unit': None, 'modelled': False,
              'conditional': False, 'scope': 'self', 'prefix': '', 'tail': raw}
    if not m:
        effect['conditional'] = is_conditional(raw)
        return effect
    value = float(m.group(1))
    unit = 'percent' if m.group(2) else 'flat'
    prefix = raw[:m.start()].strip(' ,:;')
    # A trailing '%' may also appear as "% (x2 for bows)" - keep the whole tail minus
    # the number, then trim a leading "%" that belongs to the number itself.
    tail = raw[m.end():].strip(' ,:;')
    tail = re.sub(r'^%?\s*', '', tail)
    if negative_lead and value > 0:
        value = -value
    stat, canon_unit = _canonical_stat(tail, prefix=prefix)
    effect.update({'value': _tidy(value), 'unit': canon_unit or unit, 'stat': stat,
                   'modelled': stat is not None,
                   'conditional': is_conditional(raw),
                   'scope': 'other' if prefix else 'self',
                   'prefix': prefix, 'tail': tail})
    return effect


def _tidy(value):
    """Float -> int when integral, so 15.0 prints as 15 (JSON stays small and stable)."""
    f = float(value)
    return int(f) if f.is_integer() else round(f, 4)


def rank_lines(mod_row):
    """The per-rank stat lines of a WFCD mod row -> [[line, ...], ...] indexed by rank."""
    levels = mod_row.get('levelStats')
    if not isinstance(levels, list):
        return []
    out = []
    for entry in levels:
        stats = entry.get('stats') if isinstance(entry, dict) else None
        out.append([s for s in (stats or []) if str(s or '').strip()])
    return out


def max_rank_of(mod_row, cap=schema.MAX_MOD_RANK):
    """The mod's legal rank cap: the catalog fusionLimit when sane, else the levelStats
    length, else None (never invented)."""
    fusion = mod_row.get('fusionLimit')
    if isinstance(fusion, bool) or not isinstance(fusion, (int, float)):
        fusion = None
    if fusion is not None and 0 <= int(fusion) <= cap and int(fusion) == fusion:
        return int(fusion)
    rows = rank_lines(mod_row)
    if rows:
        return len(rows) - 1
    return None


def linear_check(values):
    """(is_linear, step, note) for a rank progression - reporting only, never maths.

    A non-linear progression (`.5` rounding in Primed mods, Galvanized two-part
    effects) is a fact about the data, not an error: the engine reads the table.
    """
    if len(values) < 2:
        return True, None, 'single rank'
    first = values[0]
    step = None
    diffs = []
    for i in range(1, len(values)):
        diffs.append(round(float(values[i]) - float(values[i - 1]), 6))
    if len(set(diffs)) <= 1:
        step = diffs[0]
        return True, step, 'linear: %s per rank' % _tidy(step)
    # Linear-with-rounding: values match first + step*rank after rounding to integers.
    approx = None
    span = float(values[-1]) - float(first)
    if span:
        guess = round(span / (len(values) - 1), 4)
        if all(abs(round(float(first) + guess * i) - float(values[i])) <= 1
               for i in range(len(values))):
            approx = guess
    if approx is not None:
        return False, approx, 'non-linear: rounds a %.4g per-rank step' % approx
    return False, None, 'non-linear rank progression'


def parse_mod_effects(mod_row):
    """A WFCD mod row -> the structured effect table the engine consumes.

    Returns:
        {'max_rank': int|None,
         'per_rank': [rank0_lines, rank1_lines, ...],                # raw, cleaned
         'rank_table': {stat: [value at rank 0, ...]},
         'units': {stat: 'percent'|'flat'},
         'categories': {stat: stacking category},
         'linear': {stat: {'linear': bool, 'step': float|None, 'note': str}},
         'unmodelled': {stat_text: [rank, ...]},                     # never dropped
         'conditional': [stat ids or text that only apply under a condition],
         'notes': [...]}
    """
    per_rank = rank_lines(mod_row)
    rank_table, units, linear, unmodelled = {}, {}, {}, {}
    unmodelled_examples = {}
    conditional_order, conditional_examples = [], {}
    notes = []

    def bucket(text, rank):
        key = stat_signature(text)
        if not key:
            return
        unmodelled.setdefault(key, [])
        if rank not in unmodelled[key]:
            unmodelled[key].append(rank)
        unmodelled_examples.setdefault(key, clean_stat_text(text))

    def bucket_conditional(text):
        key = stat_signature(text)
        if not key:
            return
        if key not in conditional_examples:
            conditional_order.append(key)
        conditional_examples[key] = clean_stat_text(text)   # keep the highest-rank text

    for rank, lines in enumerate(per_rank):
        for line in lines:
            eff = parse_stat_line(line)
            if eff is None:
                continue
            if eff['conditional']:
                # Conditional effects are refused, not approximated: the base value of
                # a Galvanized mod lives on its own (unconditional) line, and the
                # "On Kill: ..." rider belongs to a later phase (unsupported registry).
                bucket_conditional(eff['text'])
                if not eff['modelled']:
                    bucket(eff['text'], rank)
                continue
            if not eff['modelled']:
                bucket(eff['text'], rank)
                continue
            rank_table.setdefault(eff['stat'], [None] * len(per_rank))
            rank_table[eff['stat']][rank] = eff['value']
            units[eff['stat']] = eff['unit']
    for stat, values in list(rank_table.items()):
        filled = [v for v in values if v is not None]
        if len(filled) != len(values):
            # A sparse table is data we do not understand - drop it loudly instead of
            # interpolating ("never silently approximate").
            notes.append('%s: rank table is sparse (%d of %d ranks) - treated as '
                         'unmodelled' % (stat, len(filled), len(values)))
            unmodelled.setdefault('sparse: %s' % stat, [i for i, v in enumerate(values)
                                                        if v is None])
            rank_table.pop(stat)
            units.pop(stat, None)
            continue
        is_lin, step, note = linear_check(values)
        linear[stat] = {'linear': is_lin, 'step': _tidy(step) if step is not None else None,
                        'note': note}
    categories = {stat: STAT_CATEGORY.get(stat, 'percent') for stat in rank_table}
    return {
        'max_rank': max_rank_of(mod_row),
        'per_rank': per_rank,
        'rank_table': rank_table,
        'units': units,
        'categories': categories,
        'linear': linear,
        'unmodelled': {k: sorted(v) for k, v in unmodelled.items()},
        'unmodelled_examples': dict(unmodelled_examples),
        'conditional': [conditional_examples[k] for k in conditional_order],
        'notes': notes,
    }


def rank_value(effects, stat, rank):
    """The value of `stat` at `rank` from a parse_mod_effects() result, or None.

    Reads the per-rank table - never extrapolates, so a partially ranked copy is exact
    and a rank past the table is None (the caller reports it, not guesses).
    """
    table = effects.get('rank_table') or {}
    values = table.get(stat)
    if not values or rank is None or rank < 0 or rank >= len(values):
        return None
    return values[rank]


def effect_rows(effects, rank, include_conditional=False):
    """Flat list of {stat, value, unit, category, conditional, text} at `rank`.

    This is the shape the weapon/frame engines consume, built straight from the tables.
    """
    rows = []
    if rank is None:
        return rows
    for stat, values in (effects.get('rank_table') or {}).items():
        if rank >= len(values):
            continue
        rows.append({'stat': stat, 'value': values[rank],
                     'unit': (effects.get('units') or {}).get(stat, 'percent'),
                     'category': (effects.get('categories') or {}).get(stat, 'percent'),
                     'conditional': False})
    if include_conditional:
        for text in effects.get('conditional') or []:
            rows.append({'stat': None, 'value': None, 'unit': None, 'category': None,
                         'conditional': True, 'text': text})
    return rows


def _rank_list(ranks):
    """'0, 3-5, 10' - a compact rendering of the ranks a refusal covers."""
    ranks = sorted(int(r) for r in (ranks or []))
    if not ranks:
        return ''
    parts, start, prev = [], ranks[0], ranks[0]
    for rank in ranks[1:]:
        if rank == prev + 1:
            prev = rank
            continue
        parts.append('%d-%d' % (start, prev) if prev > start else '%d' % start)
        start = prev = rank
    parts.append('%d-%d' % (start, prev) if prev > start else '%d' % start)
    return ', '.join(parts)


def collect_mod_effects(mod_slots):
    """Sum every mod's effects by stat, keeping the provenance of each contribution.

    Shared by the weapon and Warframe engines. Returns
    ({stat: {'value': total, 'unit', 'category', 'rows': [{mod, mod_name, rank, value,
    unit, category}]}}, [unsupported markers], [notes]).

    A mod effect whose stat the engine does not model never lands here - it is returned
    as an unsupported marker instead, so no number silently disappears.
    """
    totals, unsupported, notes = {}, [], []
    for slot in mod_slots or []:
        mod = slot.get('mod') or {}
        if not mod:
            continue
        rank = slot.get('rank')
        if rank is None:
            rank = mod.get('max_rank')
        eff = mod.get('effects') or {}
        name = mod.get('name') or mod.get('id')
        if rank is None or (mod.get('max_rank') is not None and rank > mod['max_rank']):
            unsupported.append(unsupported_marker(
                'mod_rank_out_of_range',
                '%s is equipped at rank %s but its max rank is %s'
                % (name, rank, mod.get('max_rank')), mod=mod.get('id'),
                slot=slot.get('index')))
            continue
        for stat, values in (eff.get('rank_table') or {}).items():
            if rank >= len(values) or values[rank] is None:
                continue
            value = values[rank]
            unit = (eff.get('units') or {}).get(stat, 'percent')
            category = (eff.get('categories') or {}).get(stat, 'percent')
            bucket = totals.setdefault(stat, {'value': 0.0, 'unit': unit,
                                              'category': category, 'rows': []})
            bucket['value'] += float(value)
            bucket['rows'].append({'mod': mod.get('id'), 'mod_name': name, 'rank': rank,
                                   'value': value, 'unit': unit, 'category': category})
        for text in eff.get('conditional') or []:
            unsupported.append(unsupported_marker(
                'conditional_effect',
                '%s carries a conditional effect that Phase 1 does not model: %s'
                % (name, text), mod=mod.get('id'), slot=slot.get('index'), text=text))
        for text in (eff.get('unmodelled') or {}):
            example = (eff.get('unmodelled_examples') or {}).get(text, text)
            ranks = (eff.get('unmodelled') or {}).get(text) or []
            unsupported.append(unsupported_marker(
                'unmodelled_effect',
                '%s carries a stat Phase 1 does not model: %s'
                % (name, example) + (' (ranks %s)' % _rank_list(ranks) if ranks else ''),
                mod=mod.get('id'), slot=slot.get('index'), stat=text, example=example,
                ranks=ranks))
        flags = mod.get('flags') or {}
        if flags.get('set'):
            unsupported.append(unsupported_marker(
                'set_bonus', '%s is part of a mod set; set bonuses are not modelled'
                % name, mod=mod.get('id')))
        if flags.get('riven'):
            unsupported.append(unsupported_marker(
                'riven', '%s is a Riven mod; Riven stats are not modelled' % name,
                mod=mod.get('id')))
        if flags.get('galvanized'):
            notes.append('%s is a Galvanized mod: only its unconditional values are '
                         'applied' % name)
    return totals, unsupported, notes


def unsupported_marker(code, reason, **extra):
    """The brief's marker shape (section 11): {"supported": false, "reason": ...}."""
    out = {'supported': False, 'code': code, 'reason': reason}
    out.update(extra)
    return out


def summed_percent(effect_totals, stat):
    """The summed percentage of a stat from collect_mod_effects output (0.0 if absent)."""
    row = (effect_totals or {}).get(stat)
    return float(row['value']) if row else 0.0


def effect_rows_of(effect_totals, stat):
    """The individual contributions to one stat (for traces)."""
    row = (effect_totals or {}).get(stat)
    return list(row['rows']) if row else []


def effect_text(effects, rank=None, include_unmodelled=True):
    """Readable one-line-per-effect rendering of a parse_mod_effects() result.

    Used by the debug surface (and any future UI) so a mod's parsed meaning is visible
    without reading JSON: which stat each catalog line became, what it stacks as, what
    was refused - and, where the export table is not linear, what the progression is.
    """
    effects = effects or {}
    out = []
    table = effects.get('rank_table') or {}
    if rank is None:
        rank = effects.get('max_rank')
    rank = min(int(rank), len(next(iter(table.values()))) - 1) if table and rank is not None \
        else rank
    for stat in sorted(table):
        values = table[stat]
        value = values[rank] if rank is not None and 0 <= rank < len(values) else None
        if value is None:
            continue
        unit = (effects.get('units') or {}).get(stat) or 'percent'
        category = (effects.get('categories') or {}).get(stat) or 'percent'
        progression = (effects.get('linear') or {}).get(stat) or {}
        note = '' if progression.get('linear', True) else '  (%s)' % (
            progression.get('note') or 'non-linear')
        out.append('%s  %-22s %-10s [%s]%s'
                   % (_format_value(value, unit), stat, unit, category, note))
    for stat, values in sorted((effects.get('unmodelled') or {}).items()):
        if not include_unmodelled:
            continue
        example = (effects.get('unmodelled_examples') or {}).get(stat, stat)
        out.append('REFUSED  %s  (ranks %s)' % (example, _rank_list(values)))
    for text in effects.get('conditional') or []:
        out.append('REFUSED  conditional: %s' % text)
    for note in effects.get('notes') or []:
        out.append('note: %s' % note)
    return out


def _format_value(value, unit):
    if unit == 'percent':
        return '%+.4g%%' % float(value)
    return '%+.4g' % float(value) if float(value) < 0 else '%g' % float(value)


def is_augment(mod_row, effects=None):
    """Is this an augment card? Decided by the card's own text, not the export's flag.

    WFCD's `isAugment` marks 400 of 1809 mods (Adaptation, Agility Drift, ... are not
    augments); the game's augment cards say so themselves - every real augment's text
    contains "<Ability> Augment:", and no non-augment does. The export's value is kept
    on the row as `augment_export` for provenance.
    """
    lines = []
    for rank_lines in (effects or {}).get('per_rank') or []:
        lines.extend(rank_lines)
    if not lines:
        for entry in (mod_row or {}).get('levelStats') or []:
            lines.extend(entry.get('stats') or [])
    return any(AUGMENT_TEXT_MARKER in str(line).lower() for line in lines)


def derive_flags(name, mod_row, effects=None):
    """Mod classification flags (brief section 3): primed / umbral / galvanized / ...
    plus the slot and Exilus facts the validator needs."""
    low = str(name or '').lower()
    flags = {}
    for flag, prefixes in CLASS_FLAGS.items():
        flags[flag] = any(low.startswith(p) for p in prefixes)
    row = mod_row or {}
    flags['prime'] = bool(row.get('isPrime'))
    flags['augment'] = is_augment(row, effects)
    flags['exilus'] = bool(row.get('isExilus')) or bool(row.get('isUtility'))
    compat = str(row.get('compatName') or '').strip().lower()
    kind = str(row.get('type') or '').strip().lower()
    flags['aura'] = compat == 'aura' or kind.startswith('aura')
    flags['stance'] = 'stance' in kind or compat == 'stance'
    flags['set'] = any(low.startswith(s) for s in SET_MOD_SETS)
    return flags


# The marker the game's own augment cards carry ("Link Augment: ..."). WFCD's isAugment
# flag is not usable for this (400 mods flagged, ~219 real), so the text decides.
AUGMENT_TEXT_MARKER = 'augment:'

# Mod-set families (their set bonuses are conditional on how many set mods are
# equipped - recorded, refused, and listed in the unsupported registry).
SET_MOD_SETS = ('umbral', 'sacrificial', 'augur', 'gladiator', 'vigilante', 'hunter',
                'carnis', 'motek', 'tek', 'mecha', 'synth', 'aero', 'proton', 'kavat',
                'helminth', 'bond', 'strain', 'tennocon', 'amalgam')


def lows_in(low, words):
    return any(w in low for w in words)


def slot_class(mod_row):
    """Where the mod may be installed: 'aura', 'stance' or 'normal'.

    Aura and Stance mods are capacity *sources*, not drains, and they only fit their
    dedicated slot - the validator rejects an aura in a normal slot and vice versa.

    The engine sees two shapes of the same mod: the raw export row (`compatName`, `type`)
    and the ingested row (`slot`, `class`, `compat`). Both must classify, or an ingested
    Aura silently becomes a normal mod the moment it is validated.
    """
    row = mod_row or {}
    ingested = str(row.get('slot') or '').strip().lower()
    if ingested in (schema.SLOT_AURA, schema.SLOT_STANCE):
        return ingested
    class_name = str(row.get('class') or '').strip().lower()
    if class_name in (schema.SLOT_AURA, schema.SLOT_STANCE):
        return class_name
    compat = str(row.get('compatName') or row.get('compat') or '').strip().lower()
    kind = str(row.get('type') or '').strip().lower()
    if compat == 'aura' or kind.startswith('aura'):
        return schema.SLOT_AURA
    if 'stance' in kind or compat == 'stance':
        return schema.SLOT_STANCE
    return schema.SLOT_NORMAL


def exilus_ok(mod_row):
    """Can this mod sit in an Exilus slot? Exilus/utility mods and nothing else.

    Reads both shapes: the exporter's rows carry `isExilus`/`isUtility`, and the ingested
    rows carry the same fact as `flags.exilus` (ingest.py folds the two keys into one).
    Validating an ingested row through the export keys alone said "not an Exilus mod" for
    every Exilus mod, while the library listed the very same rows as Exilus-capable.

    The game is stricter than the flag for some items (a few "utility" mods are
    normal-slot only); Phase 1 follows these flags and marks the residual doubt in the
    docs rather than guessing per-mod.
    """
    row = mod_row or {}
    if row.get('isExilus') or row.get('isUtility'):
        return True
    flags = row.get('flags') or {}
    return bool(flags.get('exilus')) if isinstance(flags, dict) else False


# ------------------------------------------------------------------ selftest
def _fixture_mod(name, lines_by_rank, compat='Rifle', mtype='Primary Mod',
                 polarity='madurai', base_drain=4):
    return {'name': name, 'uniqueName': '/fixture/' + name, 'type': mtype,
            'compatName': compat, 'polarity': polarity, 'baseDrain': base_drain,
            'fusionLimit': len(lines_by_rank) - 1,
            'levelStats': [{'stats': lines} for lines in lines_by_rank]}


def selftest():
    """The parser on WFCD-shaped fixtures. Offline, writes nothing."""
    failures = []

    counter = [0]

    def check(label, ok, detail=''):
        counter[0] += 1
        print('%s  %s%s' % ('PASS' if ok else 'FAIL', label,
                            '' if ok else ' -- %s' % detail))
        if not ok:
            failures.append(label)

    serration = _fixture_mod('Serration', [['+%d%% Damage' % (15 * (i + 1))]
                                           for i in range(11)])
    eff = parse_mod_effects(serration)
    check('per-rank table straight from the export',
          eff['rank_table']['damage'] == [15 * (i + 1) for i in range(11)])
    check('max rank from the export rank count', eff['max_rank'] == 10)
    check('linear progression detected', eff['linear']['damage']['linear'] is True
          and eff['linear']['damage']['step'] == 15)
    check('rank_value reads the table', rank_value(eff, 'damage', 10) == 165)

    exponential = _fixture_mod('Stretch', [['+%d%% Ability Range' % (5 * (i + 1))] +
                                           ['+%d%% Ability Duration' % (10 * (i + 1))]
                                           for i in range(6)])
    eff2 = parse_mod_effects(exponential)
    check('two stats on one line pair parse separately',
          eff2['rank_table']['ability_range'] == [5 * (i + 1) for i in range(6)]
          and eff2['rank_table']['ability_duration'] == [10 * (i + 1) for i in range(6)])

    heat = _fixture_mod('Hellfire', [['+%d%% <DT_FIRE_COLOR>Heat' % (15 * (i + 1))]
                                     for i in range(6)], polarity='naramon')
    eff3 = parse_mod_effects(heat)
    check('markup stripped and element canonicalised',
          eff3['rank_table']['heat'] == [15 * (i + 1) for i in range(6)],
          str(sorted(eff3['rank_table'])))

    galv = _fixture_mod('Galvanized Chamber', [
        ['+%.1f%% Multishot' % (7.3 * (i + 1)),
         'On Kill:\\n+%d%% Multishot for 20s. Stacks up to 5x.' % (2 + 3 * i)]
        for i in range(11)], base_drain=6)
    eff4 = parse_mod_effects(galv)
    check('a Galvanized rider is refused as conditional',
          len(eff4['conditional']) == 1
          and 'On Kill' in eff4['conditional'][0], str(eff4['conditional']))
    check('a conditional line never enters the rank table',
          'multishot' in eff4['rank_table']
          and eff4['rank_table']['multishot'][0] == 7.3
          and eff4['rank_table']['multishot'][10] == 80.3,
          str(eff4['rank_table'].get('multishot')))

    odd = _fixture_mod('Odd Mod', [['+%d%% Damage' % (5 * (i + 1)),
                                    '+%d%% Rifle Damage' % (10 * (i + 1))]
                                   for i in range(6)])
    eff5 = parse_mod_effects(odd)
    check('an unmodelled stat is refused once per stat shape, not once per rank',
          len(eff5['unmodelled']) == 1, str(list(eff5['unmodelled'])))
    check('stat_signature collapses ranks of the same stat',
          stat_signature('+5% Rifle Damage') == stat_signature('+30% Rifle Damage')
          == '#% rifle damage', str(stat_signature('+30% Rifle Damage')))
    check('an unmodelled stat keeps an example and its ranks',
          'Rifle Damage' in list((eff5.get('unmodelled_examples') or {}).values())[0]
          and list(eff5['unmodelled'].values())[0] == list(range(6)),
          str(eff5.get('unmodelled_examples')))
    check('a modelled stat next to an unmodelled one still parses',
          eff5['rank_table'].get('damage') == [5 * (i + 1) for i in range(6)],
          str(sorted(eff5['rank_table'])))

    dmg = _fixture_mod('Damage to Grineer', [['+%d%% Damage to Grineer' % (5 * (i + 1))]
                                             for i in range(6)])
    eff6 = parse_mod_effects(dmg)
    check('"Damage to <faction>" maps to a faction stat',
          any(str(k).startswith('faction') for k in eff6['rank_table']),
          str(sorted(eff6['rank_table'])))

    aura = _fixture_mod('Rifle Amp', [['+%d%% Rifle Damage' % (5 * (i + 1))]
                                      for i in range(6)], compat='Aura', mtype='Aura',
                        polarity='madurai', base_drain=4)
    check('slot_class: aura', slot_class(aura) == schema.SLOT_AURA)
    # The exporter's shape and the ingested shape must classify the same, or an Aura becomes
    # a normal mod the moment validation sees it (ingest stores it as `slot`, not compatName).
    check('slot_class: aura and stance survive ingestion',
          slot_class({'slot': 'aura', 'class': 'aura', 'compat': 'AURA',
                      'type': 'Warframe Mod'}) == schema.SLOT_AURA
          and slot_class({'slot': 'stance', 'class': 'stance', 'compat': 'STANCE',
                          'type': 'Melee Mod'}) == schema.SLOT_STANCE
          and slot_class({'slot': 'normal', 'class': 'rifle', 'compat': 'Rifle',
                          'type': 'Primary Mod'}) == schema.SLOT_NORMAL,
          'an ingested aura/stance must not fall through to normal')
    check('derive_flags: aura + name flags', derive_flags('Rifle Amp', aura)['aura'] is True)
    check('derive_flags: galvanized/primed/umbral by name',
          derive_flags('Galvanized Chamber', galv)['galvanized'] is True
          and derive_flags('Primed Continuity', galv)['primed'] is True
          and derive_flags('Umbral Vitality', galv)['umbral'] is True)
    check('exilus_ok follows the export flags',
          exilus_ok({'isExilus': True}) and not exilus_ok({}))
    check('exilus_ok follows the ingested row shape too',
          exilus_ok({'flags': {'exilus': True}}) and not exilus_ok({'flags': {'exilus': False}})
          and not exilus_ok({'flags': 'not a dict'}))

    totals, markers, notes = collect_mod_effects(
        [{'kind': 'normal', 'index': 0, 'rank': 10, 'mod': _as_row(serration)},
         {'kind': 'normal', 'index': 1, 'rank': 5, 'mod': _as_row(heat)}])
    check('collect sums by stat and keeps every contribution',
          totals['damage']['value'] == 165 and totals['heat']['value'] == 90
          and len(totals['damage']['rows']) == 1, str(sorted(totals)))
    check('collect refuses an out-of-range rank',
          any(m['code'] == 'mod_rank_out_of_range' for m in collect_mod_effects(
              [{'kind': 'normal', 'index': 0, 'rank': 11,
                'mod': _as_row(serration)}])[1]))
    print('\neffects selftest %s (%d checks, %d failed) - nothing written'
          % ('OK' if not failures else 'FAILED', counter[0], len(failures)))
    return 0 if not failures else 1


def _as_row(fixture):
    """Fixture mod -> ingested row shape (effects parsed, flags derived)."""
    eff = parse_mod_effects(fixture)
    return {'id': fixture['uniqueName'], 'name': fixture['name'],
            'max_rank': eff['max_rank'], 'effects': eff,
            'polarity': schema.norm_polarity(fixture.get('polarity')),
            'base_drain': fixture.get('baseDrain'),
            'flags': derive_flags(fixture['name'], fixture, eff)}
