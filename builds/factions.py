#!/usr/bin/env python3
"""The Damage 3.0 faction vocabulary: who takes extra damage from what, and which faction a mod
speaks for.

Why this module exists (Phase 5, milestone 5.1). Update 36 (2024-06-18) simplified health, armour
and shield types to **one type each** and moved vulnerabilities and resistances onto the enemy
**faction**:

    "Since its predecessor Damage 2.0, all different Health, Armor, and Shield types have been
     simplified into one type for each (e.g. Grineer's Cloned Flesh and Machinery is now just
     \"Health\", Ferrite Armor and Alloy Armor is now just \"Armor\", and Shield and Proto Shield is
     now just \"Shield\"). Vulnerabilities and resistances have also been decoupled from health
     types and are now solely based on the enemy Faction (e.g. all Grineer are now exclusively
     vulnerable to Impact and Corrosive at all times, regardless of the presence of armor or
     shields, and no longer have any resistances)."

        Source: https://wiki.warframe.com/w/Damage (oldid 2812034, retrieved 2026-09-30)

    "As of Update 36, Vulnerable + = x1.5 and Resistant - = x0.5 incoming damage multiplier."

        Source: https://wiki.warframe.com/w/Damage/Overview_Table (oldid 2792179, retrieved 2026-09-30)

Each faction's entry below is the sentence from that faction's own page (retrieved 2026-09-30);
the page citations live in `FACTION_SOURCE` (per-page revision ids in `FACTION_REVISIONS`). There is deliberately **no** `health_type` or
`armor_type` table here: with one health type and one armour class, such an input would be a
fiction - the faction is the health type now.

The second table, `FACTION_DAMAGE_APPLIES`, is what a faction-damage mod ("Bane of Grineer")
covers. It is read off the Faction Damage Bonus page (oldid 2804854, retrieved 2026-09-30):

    "Grineer, Corpus, and Infested Faction Mods have no effect on their Corrupted or Narmer
     counterparts. For example, Bane of Grineer will work on Lancer but not on Corrupted Lancer or
     Narmer Lancer. Likewise, Infested Faction Mods have no effect on Techrot. Grineer, Corpus, and
     Infested Faction Mods *do* apply to Kuva Grineer, Corpus Amalgam, and Infested Deimos enemies,
     respectively."
"""

RETRIEVED = '2026-09-30'

# The canonical vocabulary: the 15 faction columns of the Damage 3.0 overview table. `tenno` is a
# real entry (players): every damage type is neutral against it, which is a stated fact, not an
# absence of data. `object` is not a faction (its overview-table entry carries no faction) and is
# not accepted here.
FACTIONS = ('tenno', 'grineer', 'kuva_grineer', 'corpus', 'corpus_amalgam', 'infested',
            'infested_deimos', 'orokin', 'sentient', 'narmer', 'murmur', 'zariman', 'scaldra',
            'techrot', 'anarchs')

# Display names (the pages' own spelling).
FACTION_LABEL = {
    'tenno': 'Tenno', 'grineer': 'Grineer', 'kuva_grineer': 'Kuva Grineer', 'corpus': 'Corpus',
    'corpus_amalgam': 'Corpus Amalgam', 'infested': 'Infested',
    'infested_deimos': 'Infested Deimos', 'orokin': 'Orokin (Corrupted)', 'sentient': 'Sentient',
    'narmer': 'Narmer', 'murmur': 'The Murmur', 'zariman': 'Zariman', 'scaldra': 'Scaldra',
    'techrot': 'Techrot', 'anarchs': 'Anarchs',
}

# What a caller may type, and what it means. Legacy/plural spellings map onto the canonical id;
# 'corrupted' is the Damage 2.0 name for what Damage 3.0 calls Orokin (the page says "Orokin refers
# to the Corrupted"). Nothing else is guessed: an unrecognised string stays unrecognised.
FACTION_ALIASES = {
    'corrupted': 'orokin',
    'the_murmur': 'murmur',
}

# The two modifier values (the overview table's own legend, quoted in the docstring).
VULNERABLE = 0.5
RESISTANT = -0.5

# faction -> {damage type: modifier}. Only vulnerabilities and resistances are listed; every other
# damage type is 0 (neutral) for that faction. Damage-type ids are the engine's canonical ones
# (schema.DAMAGE_* / ELEMENTAL_TYPES / void).
FACTION_MODIFIERS = {
    'tenno': {},
    'grineer': {'impact': VULNERABLE, 'corrosive': VULNERABLE},
    'kuva_grineer': {'impact': VULNERABLE, 'corrosive': VULNERABLE, 'heat': RESISTANT},
    'corpus': {'puncture': VULNERABLE, 'magnetic': VULNERABLE},
    'corpus_amalgam': {'electricity': VULNERABLE, 'magnetic': VULNERABLE, 'blast': RESISTANT},
    'infested': {'slash': VULNERABLE, 'heat': VULNERABLE},
    'infested_deimos': {'blast': VULNERABLE, 'gas': VULNERABLE, 'viral': RESISTANT},
    'orokin': {'puncture': VULNERABLE, 'viral': VULNERABLE, 'radiation': RESISTANT},
    'sentient': {'cold': VULNERABLE, 'radiation': VULNERABLE, 'corrosive': RESISTANT},
    'narmer': {'slash': VULNERABLE, 'toxin': VULNERABLE, 'magnetic': RESISTANT},
    'murmur': {'electricity': VULNERABLE, 'radiation': VULNERABLE, 'viral': RESISTANT},
    'zariman': {'void': VULNERABLE},
    'scaldra': {'impact': VULNERABLE, 'corrosive': VULNERABLE, 'gas': RESISTANT},
    'techrot': {'magnetic': VULNERABLE, 'gas': VULNERABLE, 'cold': RESISTANT},
    'anarchs': {'impact': VULNERABLE, 'electricity': VULNERABLE, 'radiation': RESISTANT},
}

SOURCE_TABLE = ('https://wiki.warframe.com/w/Damage/Overview_Table '
                '(oldid 2792179, retrieved %s)' % RETRIEVED)
SOURCE_RULE = ('https://wiki.warframe.com/w/Damage (oldid 2812034, retrieved %s)' % RETRIEVED)
SOURCE_FACTION_DAMAGE_MODS = ('https://wiki.warframe.com/w/Faction_Damage_Bonus '
                              '(oldid 2804854, retrieved %s)' % RETRIEVED)
# One row per faction page, so every vulnerability/resistance above has a citation.
FACTION_REVISIONS = {
    'grineer': 2722033, 'kuva_grineer': 2722027, 'corpus': 2722034, 'corpus_amalgam': 2722025,
    'infested': 2722036, 'infested_deimos': 2722035, 'orokin': 2722023, 'sentient': 2722024,
    'narmer': 2722028, 'murmur': 2722029, 'zariman': 2722030, 'scaldra': 2722020,
    'techrot': 2722022, 'anarchs': 2722026, 'tenno': 2722021,
}
FACTION_SOURCE = {name: ('https://wiki.warframe.com/w/Damage/%s (oldid %s, retrieved %s)'
                         % (FACTION_LABEL[name].replace(' (Corrupted)', '').replace(' ', '_'),
                            FACTION_REVISIONS.get(name, 'unpinned'), RETRIEVED))
                  for name in FACTIONS}
FACTION_SOURCE['orokin'] = ('https://wiki.warframe.com/w/Damage/Orokin '
                            '(oldid 2722023, retrieved %s)' % RETRIEVED)

# Which target factions a faction-damage mod's faction reaches (see the docstring quote).
# Mods that name a faction the vocabulary does not know fall back to an exact-name match.
FACTION_DAMAGE_APPLIES = {
    'grineer': ('grineer', 'kuva_grineer'),
    'corpus': ('corpus', 'corpus_amalgam'),
    'infested': ('infested', 'infested_deimos'),
    'corrupted': ('orokin',),                # "Bane of Orokin" ships as faction_corrupted
    'orokin': ('orokin',),
    'murmur': ('murmur',),
    'sentient': ('sentient',),
    'narmer': ('narmer',),
}


def normalise_faction(value):
    """A stated faction -> (canonical id, known). Unknown strings come back as-is, known=False.

    Normalisation is case/space tolerant ('Kuva Grineer' -> 'kuva_grineer') and applies the alias
    table; it never guesses. A caller that states something outside the vocabulary gets its string
    back so the refusal can quote exactly what was stated.
    """
    if value is None:
        return None, False
    raw = str(value).strip().lower()
    if not raw:
        return None, False
    key = raw.replace('-', '_').replace(' ', '_')
    while '__' in key:
        key = key.replace('__', '_')
    if key in FACTIONS:
        return key, True
    if key in FACTION_ALIASES:
        return FACTION_ALIASES[key], True
    return raw, False


def modifier(faction, damage_type):
    """The damage-type modifier for one faction and type: +0.5, -0.5 or 0.0.

    Returns (value, reason) where reason is 'vulnerable' / 'resistant' / None, so a trace can say
    why a type gained or lost damage. An unknown faction has no table: the caller must refuse
    rather than treat it as neutral.
    """
    row = FACTION_MODIFIERS.get(faction)
    if row is None:
        return None, 'the faction is not in the Damage 3.0 vocabulary'
    value = row.get(damage_type)
    if value is None:
        return 0.0, None
    return value, ('vulnerable' if value > 0 else 'resistant')


def faction_damage_applies(mod_faction, target_faction):
    """Does a faction-damage mod's faction reach a stated target faction? (see the docstring)"""
    want = str(mod_faction or '').strip().lower().replace(' ', '_')
    got, known = normalise_faction(target_faction)
    if not known or got is None:
        return None                              # cannot answer without a known target faction
    applies = FACTION_DAMAGE_APPLIES.get(want)
    if applies is None:
        return want == got                       # a faction the table does not know: exact match
    return got in applies


def vulnerable_to(faction):
    """The faction's vulnerabilities, sorted (for docs/UI: 'Grineer: vulnerable to Impact')."""
    row = FACTION_MODIFIERS.get(faction) or {}
    return sorted(t for t, v in row.items() if v > 0)


def resistant_to(faction):
    row = FACTION_MODIFIERS.get(faction) or {}
    return sorted(t for t, v in row.items() if v < 0)


# ------------------------------------------------------------------ selftest
def selftest():
    failures, counter = [], [0]

    def check(label, ok, detail=''):
        counter[0] += 1
        print('%s  %s%s' % ('PASS' if ok else 'FAIL', label, '' if ok else ' -- %s' % detail))
        if not ok:
            failures.append(label)

    check('15 factions, no duplicates', len(FACTIONS) == 15 and len(set(FACTIONS)) == 15)
    check('every faction has a modifier row and a source',
          set(FACTION_MODIFIERS) == set(FACTIONS)
          and all(FACTION_SOURCE.get(f) for f in FACTIONS))
    check('every modifier is +0.5, -0.5 or 0.0 within its row',
          all(v in (VULNERABLE, RESISTANT) for row in FACTION_MODIFIERS.values()
              for v in row.values()))
    check('every damage type in the table is a canonical engine type',
          all(t in ('impact', 'puncture', 'slash', 'heat', 'cold', 'electricity', 'toxin',
                    'blast', 'corrosive', 'gas', 'magnetic', 'radiation', 'viral', 'void')
              for row in FACTION_MODIFIERS.values() for t in row))
    check('the wiki sentences: Grineer impact+corrosive, no resistance',
          vulnerable_to('grineer') == ['corrosive', 'impact'] and resistant_to('grineer') == [])
    check('Kuva Grineer resists heat; Deimos resists viral; Sentient resists corrosive',
          resistant_to('kuva_grineer') == ['heat']
          and resistant_to('infested_deimos') == ['viral']
          and resistant_to('sentient') == ['corrosive'])
    check('Tenno is neutral everywhere', FACTION_MODIFIERS['tenno'] == {})
    check('Zariman is vulnerable to Void only', vulnerable_to('zariman') == ['void']
          and resistant_to('zariman') == [])
    check('modifier() names why: +0.5 vulnerable, -0.5 resistant, 0 neutral',
          modifier('grineer', 'impact') == (0.5, 'vulnerable')
          and modifier('kuva_grineer', 'heat') == (-0.5, 'resistant')
          and modifier('grineer', 'slash') == (0.0, None))
    check('an unknown faction has no modifier row at all - never neutral',
          modifier('the_sentients', 'impact')[0] is None)
    check('normalise: case, spaces, aliases',
          normalise_faction('Kuva Grineer') == ('kuva_grineer', True)
          and normalise_faction('Corrupted') == ('orokin', True)
          and normalise_faction('The Murmur') == ('murmur', True)
          and normalise_faction('') == (None, False))
    check('normalise: an unknown faction comes back as stated, known=False',
          normalise_faction('Wally') == ('wally', False))
    check('faction mods: Bane of Grineer reaches Grineer and Kuva Grineer, not Narmer',
          faction_damage_applies('grineer', 'grineer') is True
          and faction_damage_applies('grineer', 'kuva_grineer') is True
          and faction_damage_applies('grineer', 'narmer') is False
          and faction_damage_applies('grineer', 'corpus') is False)
    check('faction mods: Corrupted=Bane of Orokin vs Orokin; Infested not vs Techrot',
          faction_damage_applies('corrupted', 'orokin') is True
          and faction_damage_applies('infested', 'infested_deimos') is True
          and faction_damage_applies('infested', 'techrot') is False)
    check('faction mods: an unknown target faction cannot be answered',
          faction_damage_applies('grineer', 'wally') is None)
    check('faction mods: a mod faction outside the table falls back to exact matching',
          faction_damage_applies('hunhow', 'sentient') is False
          and faction_damage_applies('hunhow', 'hunhow') is None,
          'a target outside the vocabulary cannot be matched (None), and a mod faction outside '
          'the table only matches its own name')

    print('\nfactions selftest %s (%d checks, %d failed) - nothing written'
          % ('OK' if not failures else 'FAILED', counter[0], len(failures)))
    return 0 if not failures else 1


if __name__ == '__main__':
    import sys
    sys.exit(selftest())
