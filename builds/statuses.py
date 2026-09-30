#!/usr/bin/env python3
"""Status mechanics: one precisely defined piece of one status effect at a time.

Phase 4 added the **Viral** status effect's damage amplification against a target (milestone 4.4).
Phase 5 adds the **Corrosive** status effect's armour reduction (milestone 5.5), chosen because it
exercises a different architecture: it does not multiply damage, it changes the *target's armour
value*, which the Phase 5 mitigation stage consumes. Still not "status effects": not the proc
timeline, not the DoTs, not the other nine types.

The rule, quoted from the WARFRAME Wiki (retrieved 2026-09-30, oldid 2804597):

    "The status effect of Corrosive damage is Corrosion. It temporarily degrades the armor of the
     afflicted target by 26% for 8 seconds. Subsequent procs further reduce armor by 6%, culminating
     in a total armor reduction of 80% at 10 stacks, with each stack having its own duration. Any
     stacks applied after the 10th will replace the oldest stack."

        Armor after reduction = Armor x (1 - (0.20 + 0.06 x Corrosive stacks))

    (The 26% first proc is 20% + 6% x 1; the wiki's own combined formula writes the reduction as
     "20% + 6% x Number of Corrosive stacks", capped at 80% with 10 stacks.)

    Source: https://wiki.warframe.com/w/Damage/Corrosive_Damage (oldid 2804597)

Inputs (exactly this; it lives under the evaluation context - `options['context']['target']`):

    context.target.corrosive_stacks   0..10   the number of Corrosive procs currently on the target

Outputs: a condition-shaped result (the same four states as `builds.conditions`) carrying

    armor_multiplier   the factor to apply to the target's armour, or None when it is withheld
    formula            the formula text above, so a UI can show the rule it used
    state              satisfied | not_satisfied | unknown | unsupported

Deliberately NOT here: the 8-second duration, stack replacement over time, the Emerald Archon Shard
that raises the cap, Heat's 50% armour strip, Corrosive Projection, Terrify and every other armour
source. Those are refusals, not omissions: a caller that needs them is told so by the state.
"""
from . import conditions

# --- viral (Phase 4) -------------------------------------------------------------------------
SOURCE = 'https://wiki.warframe.com/w/Damage/Viral_Damage (oldid 2805913, retrieved 2026-09-29)'
STATUS = 'viral'
MAX_STACKS = 10
PER_STACK = 0.25
BASE_AMPLIFIER = 2.0            # +100% at one stack
FORMULA = 'damage_to_health = modded_damage x [2 + (0.25 x (viral_stacks - 1))]'

# The wiki's split, kept as data so the refusal can quote it.
REACHES = ('health', 'armor')            # armour is not a barrier to this amplification
DOES_NOT_REACH = ('shields', 'overguard')


def amplifier(stacks):
    """The viral multiplier for a stack count, or None when the count is not modellable.

    Pure and total: 0 stacks -> 1.0 (no amplification, no error), 1..10 -> the wiki formula,
    anything else (11+, negative, non-integer) -> None. A caller must never read None as 1.0.
    """
    if isinstance(stacks, bool) or not isinstance(stacks, int):
        return None
    if stacks < 0 or stacks > MAX_STACKS:
        return None
    if stacks == 0:
        return 1.0
    return round(BASE_AMPLIFIER + PER_STACK * (stacks - 1), 4)


def _immune_names(ctx):
    """`target.immune_to` -> a list of lowercased status names, or a refusal row (never a raise).

    A string is one name; a list/tuple must hold only strings; anything else - a number, a bool, a
    dict, a list with junk in it - is a stated value this engine cannot interpret, and it says so.
    """
    raw = conditions.get(ctx, 'target', 'immune_to')
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw.strip().lower()]
    if isinstance(raw, (list, tuple)):
        if all(isinstance(x, str) for x in raw):
            return [x.strip().lower() for x in raw]
        return conditions.result(
            STATUS, conditions.UNKNOWN,
            'target.immune_to %r carries entries that are not status names' % (list(raw),),
            reason_code='condition_unknown', inputs={'immune_to': repr(list(raw))},
            missing=['target.immune_to as a status name or a list of names'],
            source=SOURCE, formula=FORMULA)
    return conditions.result(
        STATUS, conditions.UNKNOWN,
        'target.immune_to %r is not a status name or a list of names' % (raw,),
        reason_code='condition_unknown', inputs={'immune_to': repr(raw)},
        missing=['target.immune_to as a status name or a list of names'],
        source=SOURCE, formula=FORMULA)


def evaluate(ctx):
    """The Viral mechanic against the supplied target state -> a condition-shaped result.

    Every branch ends in one of the four states; none of them ends in a silent multiplier of 1.
    """
    stack_state = _stacks_result(ctx)
    if stack_state is not None:
        return stack_state
    stacks = conditions.get(ctx, 'target', 'viral_stacks')
    protection = conditions.get(ctx, 'target', 'protection')
    immune = _immune_names(ctx)
    if isinstance(immune, dict):
        # `_immune_names` returns a refusal row when the stated value is not a name or a list of
        # names: iterating it (the old shape) raised TypeError on a number, and silently reading a
        # list of junk as "no immunity" was the same class of bug with a quieter symptom.
        return immune
    if STATUS in immune:
        return conditions.result(
            STATUS, conditions.UNSUPPORTED,
            'the caller states this target is immune to viral damage; the wiki notes some Deimos '
            'units are outright immune, and that special case is not modelled',
            reason_code='mechanic_unsupported', inputs={'viral_stacks': stacks,
                                                        'protection': protection},
            source=SOURCE, formula=FORMULA,
            unsupported_code='viral_immune_target')
    if not conditions.has(ctx, 'target', 'protection'):
        return conditions.result(
            STATUS, conditions.UNKNOWN,
            'the target state does not say what the damage lands on (health/armour vs shields/'
            'overguard); the amplification reaches health and not shields',
            reason_code='condition_unknown', inputs={'viral_stacks': stacks},
            missing=['target.protection'], source=SOURCE, formula=FORMULA)
    if not isinstance(protection, str) or protection.strip().lower() not in \
            REACHES + DOES_NOT_REACH:
        return conditions.result(
            STATUS, conditions.UNSUPPORTED,
            'target.protection %r is not one of %s' % (protection, ', '.join(REACHES
                                                                             + DOES_NOT_REACH)),
            reason_code='mechanic_unsupported', inputs={'viral_stacks': stacks,
                                                        'protection': protection},
            source=SOURCE, formula=FORMULA)
    mult = amplifier(stacks)
    if mult is None:                                   # unreachable: _stacks_result ran first
        return conditions.result(STATUS, conditions.UNSUPPORTED, 'viral stacks not modellable',
                                 reason_code='mechanic_unsupported', source=SOURCE,
                                 formula=FORMULA)
    if protection.strip().lower() in DOES_NOT_REACH:
        return conditions.result(
            STATUS, conditions.NOT_SATISFIED,
            'the damage lands on %s, which the viral amplification does not reach'
            % protection.strip().lower(),
            reason_code='condition_not_satisfied', inputs={'viral_stacks': stacks,
                                                           'protection': protection},
            source=SOURCE, formula=FORMULA, amplifier=1.0)
    if stacks == 0:
        return conditions.result(
            STATUS, conditions.NOT_SATISFIED,
            'the target carries no viral procs, so there is nothing to amplify',
            reason_code='condition_not_satisfied',
            inputs={'viral_stacks': 0, 'protection': protection},
            source=SOURCE, formula=FORMULA, amplifier=1.0)
    return conditions.result(
        STATUS, conditions.SATISFIED,
        '%d viral proc%s on a target whose damage lands on %s'
        % (stacks, '' if stacks == 1 else 's', protection.strip().lower()),
        inputs={'viral_stacks': stacks, 'protection': protection},
        source=SOURCE, formula=FORMULA, amplifier=mult, stacks=stacks)


def _stacks_result(ctx):
    """None when the stack count is usable; otherwise the result that refuses it."""
    if not conditions.has(ctx, 'target', 'viral_stacks'):
        return conditions.result(
            STATUS, conditions.UNKNOWN,
            'the target state does not carry viral_stacks, so the amplification is unknown',
            reason_code='condition_unknown', missing=['target.viral_stacks'],
            source=SOURCE, formula=FORMULA)
    stacks = conditions.get(ctx, 'target', 'viral_stacks')
    if isinstance(stacks, bool) or not isinstance(stacks, int):
        return conditions.result(
            STATUS, conditions.UNKNOWN,
            'viral_stacks %r is not a stack count this engine will interpret' % (stacks,),
            reason_code='condition_unknown', inputs={'viral_stacks': stacks},
            missing=['an integer target.viral_stacks'], source=SOURCE, formula=FORMULA)
    if stacks < 0:
        return conditions.result(
            STATUS, conditions.UNKNOWN,
            'viral_stacks %d is negative, which is not a target state' % stacks,
            reason_code='condition_unknown', inputs={'viral_stacks': stacks},
            missing=['a non-negative target.viral_stacks'], source=SOURCE, formula=FORMULA)
    if stacks > MAX_STACKS:
        return conditions.result(
            STATUS, conditions.UNSUPPORTED,
            'viral_stacks %d is above the 10-stack cap: the wiki replaces the oldest stack, which '
            'is a timeline this engine does not model' % stacks,
            reason_code='mechanic_unsupported', inputs={'viral_stacks': stacks},
            source=SOURCE, formula=FORMULA, unsupported_code='viral_stack_timeline')
    return None


def trace_rows(row):
    """One trace-modifier row for a viral result (feeds builds.trace / the page's tooltip)."""
    if not row or row.get('amplifier') is None or row.get('state') != conditions.SATISFIED:
        return None
    return {'source': 'Viral', 'category': 'status', 'value': row['amplifier'], 'unit': 'ratio',
            'condition': STATUS, 'state': row['state'], 'stacks': row.get('stacks'),
            'note': row.get('formula')}


# ------------------------------------------------------------------ corrosive (Phase 5, 5.5)
CORROSIVE = 'corrosive'
CORROSIVE_SOURCE = ('https://wiki.warframe.com/w/Damage/Corrosive_Damage '
                    '(oldid 2804597, retrieved 2026-09-30)')
CORROSIVE_BASE = 0.20                 # the flat part of the reduction (26% at one stack = 20+6)
CORROSIVE_PER_STACK = 0.06
CORROSIVE_MAX_REDUCTION = 0.80        # 80% at ten stacks
CORROSIVE_MAX_STACKS = 10
CORROSIVE_FORMULA = 'armor_after = armor x (1 - (0.20 + 0.06 x corrosive_stacks))'
CORROSIVE_TRACE_LABEL = 'Corrosive armour reduction'


def corrosive_reduction(stacks):
    """The fraction of armour this many Corrosive stacks removes, or None when not modellable.

    Pure and total: 0 stacks -> 0.0 (no reduction, no error), 1..10 -> the wiki formula capped at
    80%, anything else (11+, negative, non-integer) -> None. A caller must never read None as 0.0.
    """
    if isinstance(stacks, bool) or not isinstance(stacks, int):
        return None
    if stacks < 0 or stacks > CORROSIVE_MAX_STACKS:
        return None
    if stacks == 0:
        return 0.0
    return round(min(CORROSIVE_MAX_REDUCTION, CORROSIVE_BASE + CORROSIVE_PER_STACK * stacks), 4)


HEAT = 'heat'
# (the values the strip can hold are listed in evaluate_heat's refusal text)
# The values the wiki's ramp actually passes through (percent), and the maximum.
HEAT_STRIP_PLATEAUS = (15.0, 30.0, 40.0, 50.0)
HEAT_MAX_STRIP = 0.50
SOURCE_HEAT = ('https://wiki.warframe.com/w/Damage/Heat_Damage (oldid 2807948, '
               'retrieved 2026-09-30)')
HEAT_FORMULA = ("Heat status armour strip: armour x (1 - strip), where strip is the stated state "
                "(one of the ramp's values, 15%/30%/40%/50%). Multiplicative with corrosive.")
HEAT_TIMELINE = ("the strip ramps in over ~2 seconds and the Ignite tick deals damage for 6 more; "
                 "both are timelines (status duration is not modelled), so this engine applies a "
                 "stated strip and refuses nothing else")


def heat_strip_percent(value):
    """A stated strip -> one of the ramp's percentages, `0`, or None when it is not that at all."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    if number != number or number in (float('inf'), float('-inf')):
        return None
    if number == 0.0:
        return 0.0
    if number in HEAT_STRIP_PLATEAUS:
        return number
    return None


def evaluate_heat(ctx):
    """The stated Heat strip -> a four-state row (Phase 6, 6.4).

    The strip is a *state*, not an event: the caller states the value the target currently carries,
    and a value the ramp cannot hold (35%) is refused by name rather than rounded to a plateau.
    """
    if not conditions.has(ctx, 'target', 'heat_strip'):
        return conditions.result(
            HEAT, conditions.UNKNOWN,
            'no Heat state was supplied: the armour strip is a stated target state, and this engine '
            'will not guess whether the target is burning',
            reason_code='condition_unknown', missing=['target.heat_strip'],
            source=SOURCE_HEAT, formula=HEAT_FORMULA)
    stated = conditions.get(ctx, 'target', 'heat_strip')
    percent = heat_strip_percent(stated)
    if percent is None:
        return conditions.result(
            HEAT, conditions.UNSUPPORTED,
            'Heat armour strip %r is not one of the values the strip can hold (15, 30, 40 or 50 '
            'percent, or 0 for none)' % (stated,),
            reason_code='mechanic_unsupported', unsupported_code='heat_strip_value',
            inputs={'heat_strip': conditions.safe_input(stated)
                    if isinstance(stated, (int, float, str)) else repr(stated)},
            source=SOURCE_HEAT, formula=HEAT_FORMULA)
    if percent == 0.0:
        return conditions.result(
            HEAT, conditions.NOT_SATISFIED,
            'the target carries no Heat strip (a reported zero), so the armour is unchanged',
            reason_code='condition_not_satisfied',
            inputs={'heat_strip': conditions.safe_input(stated)},
            source=SOURCE_HEAT, formula=HEAT_FORMULA, strip=0.0)
    strip = percent / 100.0
    return conditions.result(
        HEAT, conditions.SATISFIED,
        'the target carries a stated Heat strip of %g%%, so its armour is multiplied by %g '
        '(multiplicative with the corrosive reduction, wiki)'
        % (percent, 1.0 - strip),
        inputs={'heat_strip': conditions.safe_input(stated)},
        source=SOURCE_HEAT, formula=HEAT_FORMULA, strip=strip)


def heat_armour_transform(armor, row):
    """The armour after the stated strip (a plain multiplication; the wiki's own form)."""
    strip = float(row.get('strip') or 0.0)
    return float(armor) * (1.0 - strip)


def heat_trace_row(armor, effective, row):
    """The trace row for an applied Heat strip: an input transform, like corrosive's."""
    if not row or row.get('state') != conditions.SATISFIED or not armor:
        return None
    return {'source': 'Heat strip (%g%%)' % (float(row.get('strip') or 0.0) * 100.0),
            'category': 'mitigation_input', 'value': round(float(effective) - float(armor), 6),
            'unit': 'flat', 'condition': HEAT, 'state': row['state'],
            'strip': float(row.get('strip') or 0.0),
            'formula': row.get('formula'),
            'note': '%s; armour %s -> %s (multiplicative with corrosive), and the Armor row below '
                    'applies the DR to that value' % (row.get('formula'), armor, effective)}


def corrosive_armour_transform(armor, row):
    """The armour after the stated corrosive reduction (kept bit-identical to the Phase 5 form)."""
    return float(armor) * float(row.get('armor_multiplier') or 1.0)


def evaluate_corrosive(ctx):
    """The Corrosive armour reduction against the supplied target state -> a condition result.

    Every branch ends in one of the four states; none of them ends in a silent multiplier of 1.
    """
    if not conditions.has(ctx, 'target', 'corrosive_stacks'):
        return conditions.result(
            CORROSIVE, conditions.UNKNOWN,
            'the target state does not carry corrosive_stacks, so the armour reduction is unknown',
            reason_code='condition_unknown', missing=['target.corrosive_stacks'],
            source=CORROSIVE_SOURCE, formula=CORROSIVE_FORMULA)
    stacks = conditions.get(ctx, 'target', 'corrosive_stacks')
    if isinstance(stacks, bool) or not isinstance(stacks, int):
        return conditions.result(
            CORROSIVE, conditions.UNKNOWN,
            'corrosive_stacks %r is not a stack count this engine will interpret' % (stacks,),
            reason_code='condition_unknown', inputs={'corrosive_stacks': stacks},
            missing=['an integer target.corrosive_stacks'],
            source=CORROSIVE_SOURCE, formula=CORROSIVE_FORMULA)
    if stacks < 0:
        return conditions.result(
            CORROSIVE, conditions.UNKNOWN,
            'corrosive_stacks %d is negative, which is not a target state' % stacks,
            reason_code='condition_unknown', inputs={'corrosive_stacks': stacks},
            missing=['a non-negative target.corrosive_stacks'],
            source=CORROSIVE_SOURCE, formula=CORROSIVE_FORMULA)
    if stacks > CORROSIVE_MAX_STACKS:
        return conditions.result(
            CORROSIVE, conditions.UNSUPPORTED,
            'corrosive_stacks %d is above the 10-stack cap: the Emerald Archon Shard raises the '
            'cap and stacks beyond it replace the oldest, which is a timeline this engine does '
            'not model' % stacks,
            reason_code='mechanic_unsupported', inputs={'corrosive_stacks': stacks},
            source=CORROSIVE_SOURCE, formula=CORROSIVE_FORMULA,
            unsupported_code='corrosive_stack_timeline')
    reduction = corrosive_reduction(stacks)
    if stacks == 0:
        return conditions.result(
            CORROSIVE, conditions.NOT_SATISFIED,
            'the target carries no corrosive procs, so its armour is not degraded',
            reason_code='condition_not_satisfied', inputs={'corrosive_stacks': 0},
            source=CORROSIVE_SOURCE, formula=CORROSIVE_FORMULA,
            reduction=0.0, armor_multiplier=1.0)
    return conditions.result(
        CORROSIVE, conditions.SATISFIED,
        '%d corrosive proc%s degrade %s%% of the target armour'
        % (stacks, '' if stacks == 1 else 's', round(reduction * 100, 4)),
        inputs={'corrosive_stacks': stacks},
        source=CORROSIVE_SOURCE, formula=CORROSIVE_FORMULA,
        reduction=reduction, armor_multiplier=round(1.0 - reduction, 4), stacks=stacks)


def corrosive_trace_row(armor, effective, row):
    """One trace-modifier row for an applied corrosive reduction (or None when nothing applied).

    It is an INPUT to the mitigation, not a damage factor: the row records what the procs did to
    the armour value (900 -> 504), and the Armor row that follows carries the ratio the damage is
    actually multiplied by. Recording the reduction as a ratio of its own made the trace
    non-composable - the product of its rows no longer matched the applied multiplier (found by the
    architecture review, which executed the armour-900 + 4-proc case).
    """
    if not row or row.get('state') != conditions.SATISFIED or not armor:
        return None
    return {'source': 'Corrosive (%d stack%s)' % (row['stacks'], '' if row['stacks'] == 1 else 's'),
            'category': 'mitigation_input', 'value': round(float(effective) - float(armor), 6),
            'unit': 'flat', 'condition': CORROSIVE, 'state': row['state'], 'stacks': row['stacks'],
            'formula': row.get('formula'),
            'note': '%s; armour %s -> %s, and the Armor row below applies the DR to that value'
                    % (row.get('formula'), armor, effective)}



# ------------------------------------------------------------------ selftest
def selftest():
    failures, counter = [], [0]

    def check(label, ok, detail=''):
        counter[0] += 1
        print('%s  %s%s' % ('PASS' if ok else 'FAIL', label, '' if ok else ' -- %s' % detail))
        if not ok:
            failures.append(label)

    def ctx(**target_extra):
        return conditions.normalise_context({'target': target_extra})

    # the formula, against the wiki's own numbers
    check('the wiki formula: 1 stack = +100% (x2)',
          amplifier(1) == 2.0 and amplifier(1) - 1.0 == 1.0)
    check('the wiki formula: 10 stacks = +325% (x4.25)', amplifier(10) == 4.25)
    check('each stack adds 25%', [amplifier(n) for n in (1, 2, 3)] == [2.0, 2.25, 2.5])
    check('0 stacks is a multiplier of 1, not an error', amplifier(0) == 1.0)
    check('11 stacks and non-integers are not modellable', amplifier(11) is None
          and amplifier(-1) is None and amplifier(2.5) is None and amplifier(True) is None)

    # satisfied
    ok = evaluate(ctx(viral_stacks=6, protection='health'))
    check('6 stacks on health -> satisfied with the wiki multiplier',
          ok['state'] == 'satisfied' and ok['amplifier'] == 3.25 and ok['applied'] is True, str(ok))
    check('the result carries the formula and its source',
          ok['formula'] == FORMULA and 'wiki.warframe.com' in ok['source'])
    arm = evaluate(ctx(viral_stacks=6, protection='armor'))
    check('armour ("yellow health") is reached too', arm['state'] == 'satisfied')

    # not_satisfied: two distinct, reported zeros
    none = evaluate(ctx(viral_stacks=0, protection='health'))
    check('0 stacks -> not_satisfied, amplitude 1.0, reason named',
          none['state'] == 'not_satisfied' and none['amplifier'] == 1.0
          and none['reason_code'] == 'condition_not_satisfied', str(none))
    shield = evaluate(ctx(viral_stacks=6, protection='shields'))
    check('shields -> not_satisfied (the wiki excludes them)',
          shield['state'] == 'not_satisfied' and shield['amplifier'] == 1.0)
    over = evaluate(ctx(viral_stacks=6, protection='overguard'))
    check('overguard -> not_satisfied', over['state'] == 'not_satisfied')

    # unknown: the missing input refuses instead of guessing
    miss = evaluate(conditions.normalise_context({'target': {'protection': 'health'}}))
    check('no viral_stacks -> unknown', miss['state'] == 'unknown'
          and miss['reason_code'] == 'condition_unknown')
    no_prot = evaluate(ctx(viral_stacks=4))
    check('no protection -> unknown (health is not assumed)', no_prot['state'] == 'unknown'
          and no_prot.get('amplifier') is None)
    # A refusal carries no number AT ALL - not a null to be defaulted, not a 1.0 to be multiplied
    # by. The absence of the key is the guarantee (`is None` would still allow a consumer to
    # treat a present-but-null value as 0).
    check('an unknown carries no amplifier key at all', 'amplifier' not in no_prot)
    check('an unsupported refusal carries no amplifier key either',
          'amplifier' not in evaluate(ctx(viral_stacks=12, protection='health')))
    check('a non-integer stack count is unknown',
          evaluate(ctx(viral_stacks='6', protection='health'))['state'] == 'unknown')

    # unsupported: the mechanic cannot answer, in any context
    over_cap = evaluate(ctx(viral_stacks=12, protection='health'))
    check('12 stacks -> unsupported with the timeline named',
          over_cap['state'] == 'unsupported'
          and over_cap['unsupported_code'] == 'viral_stack_timeline', str(over_cap))
    immune = evaluate(ctx(viral_stacks=6, protection='health', immune_to=['viral']))
    check('an immune target -> unsupported (the Deimos note is not modelled)',
          immune['state'] == 'unsupported' and 'amplifier' not in immune)
    weird = evaluate(ctx(viral_stacks=6, protection='hull'))
    check('an unknown protection value -> unsupported',
          weird['state'] == 'unsupported')

    # the trace row only exists for a real, applied value
    check('a satisfied result traces', trace_rows(ok)['value'] == 3.25)
    check('a refused result traces nothing', trace_rows(no_prot) is None
          and trace_rows(none) is None)

    # --- corrosive (5.5): the wiki values, the cap, and all four states
    check('the wiki formula: 1 stack = 26% off (20% + 6%)',
          corrosive_reduction(1) == 0.26)
    check('the wiki formula: 10 stacks = the 80% cap', corrosive_reduction(10) == 0.80)
    check('0 stacks is no reduction, not an error', corrosive_reduction(0) == 0.0)
    check('11 stacks and non-integers are not modellable',
          corrosive_reduction(11) is None and corrosive_reduction(2.5) is None
          and corrosive_reduction(-1) is None and corrosive_reduction(True) is None)
    cor = evaluate_corrosive(ctx(corrosive_stacks=2))
    check('2 stacks -> satisfied, armour x0.68', cor['state'] == 'satisfied'
          and cor['armor_multiplier'] == 0.68 and cor['reduction'] == 0.32, str(cor))
    check('the corrosive result carries its formula and source',
          cor['formula'] == CORROSIVE_FORMULA and 'wiki.warframe.com' in cor['source'])
    cor0 = evaluate_corrosive(ctx(corrosive_stacks=0))
    check('0 stacks -> not_satisfied with a x1.0 multiplier (a reported fact)',
          cor0['state'] == 'not_satisfied' and cor0['armor_multiplier'] == 1.0)
    cor_missing = evaluate_corrosive(conditions.normalise_context({'target': {}}))
    check('no corrosive_stacks -> unknown, and no multiplier key at all',
          cor_missing['state'] == 'unknown' and 'armor_multiplier' not in cor_missing
          and cor_missing['missing'] == ['target.corrosive_stacks'])
    cor_over = evaluate_corrosive(ctx(corrosive_stacks=12))
    check('12 stacks -> unsupported with the shard/timeline named',
          cor_over['state'] == 'unsupported'
          and cor_over['unsupported_code'] == 'corrosive_stack_timeline')
    check('a non-integer corrosive count is unknown',
          evaluate_corrosive(ctx(corrosive_stacks='3'))['state'] == 'unknown'
          and evaluate_corrosive(ctx(corrosive_stacks=-2))['state'] == 'unknown')

    print('\nstatuses selftest %s (%d checks, %d failed) - nothing written'
          % ('OK' if not failures else 'FAILED', counter[0], len(failures)))
    return 0 if not failures else 1


if __name__ == '__main__':
    import sys
    sys.exit(selftest())
