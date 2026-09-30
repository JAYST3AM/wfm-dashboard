#!/usr/bin/env python3
"""Status mechanics: one precisely defined piece of one status effect (Phase 4, milestone 4.4).

Scope, stated as narrowly as it was asked for: the **Viral** status effect's damage amplification
against a target, and nothing else. Not "status effects", not the proc timeline, not the DoTs.
Milestone 4.4 exists to prove the condition machinery can carry a real mechanic end to end; it is
not the start of building the status system (Phase 5's problem, and only if the model holds).

The rule, quoted from the WARFRAME Wiki (retrieved 2026-09-29, oldid 2805913):

    "It amplifies damage to the health of the afflicted target by 100% for 6 seconds. Subsequent
     procs add 25% increased damage to health up to 325% in total after 10 stacks, with each stack
     having their own duration. Any stacks applied after the 10th will replace the oldest stack.
     This effect will work even when the health is protected by armor ("yellow health"); only
     shields and overguards are not affected."

        Resultant Damage to Health = Modded Damage x [2 + (0.25 x (Number of Viral Stacks - 1))]

    Source: https://wiki.warframe.com/w/Damage/Viral_Damage (oldid 2805913)

Inputs (exactly these; both live under the evaluation context - `options['context']` in api.compute):

    context.target.viral_stacks   1..10   the number of Viral procs currently on the target
    context.target.protection     'health' | 'armor' | 'shields' | 'overguard'
                                          what that damage lands on (the wiki's own distinction:
                                          the amplification reaches health, including health under
                                          armour, and does not reach shields or overguard)
    context.target.immune_to      list    a target the caller already knows to be immune to this
                                          damage type (the wiki's Deimos note)

Outputs: a condition-shaped result (the same four states as `builds.conditions`) carrying

    amplifier    the multiplier to apply to damage dealt to health, or None when it is withheld
    formula      the formula text above, so a UI can show the rule it used rather than the number
    state        satisfied | not_satisfied | unknown | unsupported

Deliberately NOT here: the 6-second duration, stack decay, stack replacement over time, whether a
given build can apply a proc, any other status effect, and any enemy health/shield/armour model.
Those are refusals, not omissions: a caller that needs them is told so by the condition state.
"""
from . import conditions

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


def evaluate(ctx):
    """The Viral mechanic against the supplied target state -> a condition-shaped result.

    Every branch ends in one of the four states; none of them ends in a silent multiplier of 1.
    """
    stack_state = _stacks_result(ctx)
    if stack_state is not None:
        return stack_state
    stacks = conditions.get(ctx, 'target', 'viral_stacks')
    protection = conditions.get(ctx, 'target', 'protection')
    immune = conditions.get(ctx, 'target', 'immune_to') or []
    if isinstance(immune, str):
        immune = [immune]
    if any(str(x).strip().lower() == STATUS for x in immune if isinstance(x, (str, int))):
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

    print('\nstatuses selftest %s (%d checks, %d failed) - nothing written'
          % ('OK' if not failures else 'FAILED', counter[0], len(failures)))
    return 0 if not failures else 1


if __name__ == '__main__':
    import sys
    sys.exit(selftest())
