#!/usr/bin/env python3
"""Condition states: the four-state result space for conditional effects (Phase 4, milestone 4.1).

The governing rule of Phase 4: every conditional thing in this engine must be able to end in a
refusal, and a refusal must stay distinguishable from zero, from `False`, from a missing input and
from a validation failure. This module is that distinction.

The four states, and exactly what each one means for a calculation:

    satisfied       the condition holds for this evaluation. The contribution MAY be applied
                    (whether it is applied is the effect's business, not the condition's).
    not_satisfied   the condition is known false. The contribution is deterministically absent -
                    and that zero is a *result*, not a default. It is reported, never assumed.
    unknown         the condition is of a kind this engine can resolve, but the supplied context
                    does not carry the input it needs. The affected calculation is refused, unless
                    the caller asks for a strict/hypothetical evaluation (see `options` in api.py).
    unsupported     the mechanic behind the condition has no model at all (Galvanized stack riders,
                    mod-set bonuses, Rivens, Incarnon evolutions). Refused with its named reason.

`unknown` and `unsupported` are both refusals; they are not the same refusal. `unknown` says "ask a
better question" (supply the context); `unsupported` says "this engine does not know how to answer
that question at all, in any context". The UI prints whichever it gets; it never chooses.

Two things this module deliberately does NOT do:
  * it never maps a state to a boolean. There is no `truthy()` here; a caller that wants a number
    must look at the state and decide, which is what forces the refusal to surface;
  * it never invents a context field. The context carries only what a caller supplied (`target`,
    `attack`) plus what the build itself already knows (`target_faction` was a preprint of it).

Condition ids implemented in Phase 4 (the rest of the corpus stays refused, see 4.2):

    target_faction      the mod's bonus applies against one faction (Bane of Grineer, ...);
                        resolved from context['target_faction'] - an *evaluation* input, because the
                        same build against a different faction is a different answer.
    first_shot          the mod's bonus applies to a shot other than the first
                        (damage_on_first_shot); resolved from context['attack']['shot_index'].
"""
from . import factions, schema

SATISFIED = 'satisfied'
NOT_SATISFIED = 'not_satisfied'
UNKNOWN = 'unknown'
UNSUPPORTED = 'unsupported'
STATES = (SATISFIED, NOT_SATISFIED, UNKNOWN, UNSUPPORTED)

# What each state means for a calculation - the table the tests and the docs both point at.
MEANING = {
    SATISFIED: 'the condition holds: the contribution may be applied',
    NOT_SATISFIED: 'the condition is known false: the contribution is deterministically absent '
                   '(a reported zero, not a default)',
    UNKNOWN: 'the condition cannot be resolved from the supplied context: the affected '
             'calculation is refused unless the caller asked for a hypothetical evaluation',
    UNSUPPORTED: 'the mechanic behind the condition is not modelled: refused with its named reason',
}

# The condition codes a caller/UI sees. One per state, so a consumer can branch on the code
# without re-deriving the state machine.
STATE_CODES = {
    SATISFIED: 'condition_satisfied',
    NOT_SATISFIED: 'condition_not_satisfied',
    UNKNOWN: 'condition_unknown',
    UNSUPPORTED: 'condition_unsupported',
}

# The four refusal *reasons* milestone 4.2 asks for (a mod that refuses must say which one it is).
# The four the plan names, kept apart from the extra one so a check can pin them by name.
CONDITION_REASON_CODES = ('condition_unknown', 'condition_not_satisfied',
                          'condition_effect_unimplemented', 'mechanic_unsupported')

REASON_CODES = {
    'condition_unknown': 'the condition is resolvable but the context does not carry its input',
    'condition_not_satisfied': 'the condition is known to be false for this evaluation',
    'condition_effect_unimplemented': 'the condition is known true, but its effect is not modelled',
    'mechanic_unsupported': 'the mechanic behind the condition has no model at all',
    'context_unused': 'the caller stated an input this engine has no model for',
}

# Values that are NOT states. A caller passing one of these must be told, not accommodated: the
# whole point of Phase 4 is that `False`, `0`, `None` and '' cannot stand in for a condition state.
NOT_A_STATE = (True, False, None, 0, 1, '', 'false', 'true', 'none', [])

# Which conditions this engine can actually resolve today, and what each needs from the context.
RESOLVABLE = {
    'target_faction': {'context': ('target_faction',),
                       'reason': 'no target faction was supplied for this evaluation'},
    'first_shot': {'context': ('attack', 'shot_index'),
                   'reason': 'no attack context was supplied for this evaluation'},
}


def result(condition_id, state, reason, **extra):
    """One condition result: the shape every consumer reads.

        {'condition': 'target_faction', 'state': 'not_satisfied', 'code': ...,
         'reason': '...', 'reason_code': 'condition_not_satisfied', 'inputs': {...},
         'hypothetical': False}

    Raises on a state outside STATES: a malformed condition is a programming error here, and
    silently coercing it to one of the four states is exactly the bug class Phase 4 exists to stop.
    """
    if state not in STATES:
        raise ValueError('condition state %r is not one of %s' % (state, ', '.join(STATES)))
    out = {'condition': condition_id, 'state': state, 'code': STATE_CODES[state],
           'reason_code': _reason_code(state, extra.pop('reason_code', None)),
           'reason': str(reason), 'hypothetical': bool(extra.pop('hypothetical', False)),
           'inputs': extra.pop('inputs', {})}
    out.update(extra)
    out['applied'] = state == SATISFIED and not out['hypothetical']
    return out


def _reason_code(state, explicit):
    if explicit:
        if explicit not in REASON_CODES:
            raise ValueError('unknown condition reason code %r' % (explicit,))
        return explicit
    return {SATISFIED: None, NOT_SATISFIED: 'condition_not_satisfied',
            UNKNOWN: 'condition_unknown', UNSUPPORTED: 'mechanic_unsupported'}[state]


def is_refusal(row):
    """Is this condition result a refusal? (true for unknown and unsupported, not for a false)"""
    return (row or {}).get('state') in (UNKNOWN, UNSUPPORTED)


def withholds(row):
    """Does this condition result forbid its contribution from being applied?"""
    return (row or {}).get('state') != SATISFIED


def blocks(row):
    """Does this condition result have to stop the affected calculation?

    `unknown` and `unsupported` do; `not_satisfied` does not - a known-false condition is an
    answer ("this build does not get that bonus against that faction"), not a hole.
    """
    return is_refusal(row)


def text(row):
    """One line for a UI/log: 'target_faction: not_satisfied - ...' (never interprets)."""
    row = row or {}
    return '%s: %s - %s' % (row.get('condition'), row.get('state'), row.get('reason'))


# ------------------------------------------------------------------ the evaluation context
# Only fields a caller may supply. Anything else is reported back as `ignored` rather than
# quietly kept: an unused field would look supported.
CONTEXT_FIELDS = ('target_faction', 'target', 'attack', 'name', 'buffs')
# Phase 5 extended the target block with the enemy model's typed fields (`armor`, the stated net
# armour the mitigation is computed from; `corrosive_stacks`, a target state the armour stage
# consumes). Pool sizes (`health`, `shields`) are carried so their refusal can be precise - they
# are read, found to have no consumer, and named: "an unused field would look supported".
TARGET_FIELDS = ('viral_stacks', 'protection', 'immune_to', 'armor', 'corrosive_stacks',
                 'health', 'shields',
                 # Phase 5: fields whose *names* describe a damage-type model Damage 3.0 removed.
                 # They live here so their refusal is a named `unused` (a stated value with no
                 # consumer) rather than a typo-shaped silence - the honest answer to
                 # `health_type: "ferrite"` is "this engine does not model that", not "ignored".
                 'health_type', 'armor_type')
# Spellings a caller may use for the canonical field ids (the wiki is American: armor).
TARGET_ALIASES = {'armour': 'armor'}
ATTACK_FIELDS = ('shot_index',)


def normalise_context(raw):
    """A caller-supplied evaluation context -> the engine's context shape (never raises).

        {'target_faction': 'grineer'|None, 'target': {...}, 'attack': {...},
         'buffs': {...}, 'supplied': bool, 'ignored': ['...']}

    `supplied` is False when the caller passed nothing at all, which is what makes
    'no context' distinguishable from 'a context that says nothing'. Values are carried as
    stated - type validation belongs to the evaluator that consumes them, so a malformed value
    ends in a named refusal instead of a coerced one (Phase 5: inputs must match their declared
    type).
    """
    raw = raw if isinstance(raw, dict) else {}
    ctx = {'target_faction': None, 'target': {}, 'attack': {}, 'buffs': {},
           'supplied': bool(raw), 'ignored': []}
    for key in raw:
        if key not in CONTEXT_FIELDS:
            ctx['ignored'].append(str(key))
    faction = raw.get('target_faction')
    if isinstance(faction, str) and faction.strip():
        ctx['target_faction'] = faction.strip().lower()
    elif faction is not None:
        # stated, but not something this engine can read: named, not dropped - the condition then
        # answers `unknown` and the caller can see why in context_ignored.
        ctx['ignored'].append('target_faction (not a faction name)')
    target = raw.get('target')
    if isinstance(target, dict):
        ctx['target'] = {}
        for key, value in target.items():
            canonical = TARGET_ALIASES.get(str(key), key)
            if canonical not in TARGET_FIELDS:
                ctx['ignored'].append('target.' + str(key))
            elif canonical in ctx['target'] and ctx['target'][canonical] != value:
                # Two spellings of one field, stated differently: the canonical field keeps the
                # value and the losing spelling is named, because a silently-picked winner is the
                # same failure mode as a silently-picked default.
                ctx['ignored'].append(
                    'target.%s (a second spelling of %s; target.%s was used)'
                    % (str(key), canonical, canonical))
            else:
                ctx['target'][canonical] = value
    elif target is not None:
        ctx['ignored'].append('target (not an object)')
    attack = raw.get('attack')
    if isinstance(attack, dict):
        ctx['attack'] = {k: v for k, v in attack.items() if k in ATTACK_FIELDS}
        for key in attack:
            if key not in ATTACK_FIELDS:
                ctx['ignored'].append('attack.' + str(key))
    elif attack is not None:
        ctx['ignored'].append('attack (not an object)')
    buffs = raw.get('buffs')
    if isinstance(buffs, dict):
        # The trigger states are validated by builds/buffs.py, which owns their vocabulary; here
        # the block is only carried (a non-dict is named, never coerced).
        ctx['buffs'] = dict(buffs)
    elif buffs is not None:
        ctx['ignored'].append('buffs (not an object)')
    return ctx


def has(ctx, *path):
    """Is a dotted path present in the context? ('attack', 'shot_index')"""
    node = ctx or {}
    for key in path:
        if not isinstance(node, dict) or key not in node or node.get(key) is None:
            return False
        node = node[key]
    return True


def get(ctx, *path, **kw):
    """A dotted-path read with a default; never raises on a malformed context."""
    node = ctx or {}
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return kw.get('default')
        node = node[key]
    return node


# ------------------------------------------------------------------ the condition evaluators
def target_faction(faction, ctx):
    """Is this faction-scoped bonus on target? (Bane of Grineer vs the target's faction)

    `faction` is the faction the mod's stat is scoped to ('grineer', ...). The answer is only
    knowable against a stated target faction, so an evaluation without one is `unknown` - the
    bonus is NOT silently dropped, and it is not applied either.

    Phase 5: the stated faction is interpreted through the Damage 3.0 vocabulary
    (`builds/factions.py`), and a faction-damage mod reaches the sub-factions its own page says it
    reaches (Bane of Grineer applies to Grineer and Kuva Grineer, not to Narmer; Bane of Infested
    applies to Infested and Deimos Infested, not to Techrot). A stated faction the vocabulary does
    not know cannot be matched: that is `unknown`, not a guessed `not_satisfied`.
    """
    want = str(faction or '').strip().lower()
    if not want:
        return result('target_faction', UNSUPPORTED,
                      'the mod names no faction to check', reason_code='mechanic_unsupported')
    if not has(ctx, 'target_faction'):
        return result('target_faction', UNKNOWN,
                      'no target faction was supplied for this evaluation',
                      inputs={'mod_faction': want},
                      missing=['target_faction'],
                      reason_code='condition_unknown')
    stated = str(get(ctx, 'target_faction', default='')).strip().lower()
    applies = factions.faction_damage_applies(want, stated)
    if applies is None:
        return result('target_faction', UNKNOWN,
                      'the stated target faction %r is not in the Damage 3.0 faction vocabulary, '
                      'so this bonus cannot be matched against it' % (stated,),
                      inputs={'mod_faction': want, 'target_faction': stated},
                      missing=['a recognised target_faction'],
                      reason_code='condition_unknown')
    if applies:
        return result('target_faction', SATISFIED,
                      'the target is %s, which is a faction this %s bonus applies to'
                      % (stated, want),
                      inputs={'mod_faction': want, 'target_faction': stated})
    return result('target_faction', NOT_SATISFIED,
                  'the target is %s, which is not %s: this bonus does not apply'
                  % (stated, want),
                  inputs={'mod_faction': want, 'target_faction': stated},
                  reason_code='condition_not_satisfied')


def first_shot(ctx):
    """Does this shot count as "not the first"? (damage_on_first_shot mods)

    The wiki's own wording for these mods is 'on the first shot' / 'after the first shot'; the
    engine needs the shot's ordinal, which only the attacker knows. `shot_index` 1 = the first
    shot, 2+ = a later one. Anything else (a string, a zero, a negative) is not an ordinal this
    engine will interpret, so it is `unknown` rather than a guess.
    """
    if not has(ctx, 'attack', 'shot_index'):
        return result('first_shot', UNKNOWN,
                      'no attack context was supplied for this evaluation',
                      missing=['attack.shot_index'], reason_code='condition_unknown')
    index = get(ctx, 'attack', 'shot_index')
    if isinstance(index, bool) or not isinstance(index, int) or index < 1:
        return result('first_shot', UNKNOWN,
                      'shot_index %r is not a shot ordinal this engine will interpret' % (index,),
                      inputs={'shot_index': index}, missing=['a valid attack.shot_index'],
                      reason_code='condition_unknown')
    if index == 1:
        return result('first_shot', SATISFIED, 'this is the first shot',
                      inputs={'shot_index': index})
    return result('first_shot', NOT_SATISFIED,
                  'this is shot %d, not the first shot' % index,
                  inputs={'shot_index': index}, reason_code='condition_not_satisfied')


EVALUATORS = {'target_faction': target_faction, 'first_shot': first_shot}


def stated_fields(ctx):
    """Every input the caller actually stated, as dotted paths (what must not be dropped)."""
    out = []
    if not ctx or not ctx.get('supplied'):
        return out
    if ctx.get('target_faction'):
        out.append('target_faction')
    for key in ('viral_stacks', 'protection', 'immune_to', 'armor', 'corrosive_stacks',
                'health', 'shields', 'health_type', 'armor_type'):
        if has(ctx, 'target', key):
            out.append('target.' + key)
    if has(ctx, 'attack', 'shot_index'):
        out.append('attack.shot_index')
    for trigger in (ctx.get('buffs') or {}):
        out.append('buffs.' + str(trigger))
    return out


def unused_fields(ctx, consumed):
    """The stated fields no model consumed. Empty is the only acceptable answer for a field."""
    consumed = set(consumed or ())
    return [f for f in stated_fields(ctx) if f not in consumed]


def context_unused_result(fields, kind, consumed=()):
    """A stated-but-unmodelled input, in the same four-state vocabulary as everything else."""
    return result('context.' + (fields[0] if fields else 'unknown'), UNSUPPORTED,
                  'the stated %s is not modelled for %s, so it was not used'
                  % (' and '.join(fields), kind or 'this equipment'),
                  inputs={'fields': list(fields), 'kind': kind},
                  consumed=list(consumed or ()), source='engine capability',
                  reason_code='context_unused')


def evaluate(condition_id, ctx, **spec):
    """Run one condition evaluator. Unknown ids are `unsupported` with the id named, never a guess."""
    fn = EVALUATORS.get(condition_id)
    if fn is None:
        return result(condition_id, UNSUPPORTED,
                      'condition %r has no evaluator in this engine' % (condition_id,),
                      reason_code='mechanic_unsupported')
    return fn(ctx=ctx, **spec)


# ------------------------------------------------------------------ the corpus classifier (4.2)
# Condition kinds the text of a mod's stat line can name. These are the *recognisable* clauses;
# a clause this table does not know is `unspecified`, which is still a structured refusal.
CONDITION_VOCABULARY = (
    ('on kill', 'on_kill'), ('on hit', 'on_hit'), ('on reload', 'on_reload'),
    ('on headshot', 'on_headshot'), ('on critical', 'on_crit'), ('on status', 'target_status'),
    ('on slam', 'on_slam'), ('on roll', 'on_move'), ('on dodge', 'on_move'),
    ('per status', 'target_status'), ('per stack', 'stacks'), ('stacks up to', 'stacks'),
    ('for each', 'per_unit'), ('for ', 'timer'), ('each time', 'per_event'), ('when ', 'state_clause'),
    ('while ', 'state_clause'), ('during ', 'state_clause'), ('after ', 'sequence_clause'),
    ('upon ', 'sequence_clause'),
)

# Condition kinds whose mechanic has no model at all - refused as `unsupported`, with the reason.
UNMODELLED_CONDITIONS = {
    'on_kill': 'on-kill stack behaviour (Galvanized riders) is not modelled',
    'on_hit': 'on-hit stack behaviour is not modelled',
    'on_reload': 'reload-triggered effects are not modelled',
    'on_headshot': 'headshot-triggered effects are not modelled (no target model)',
    'on_crit': 'critical-hit-triggered effects are not modelled',
    'on_slam': 'slam-attack effects are not modelled',
    'on_move': 'movement-triggered effects are not modelled',
    'target_status': 'per-status-on-target scaling is not modelled (no target status state)',
    'stacks': 'stack accumulation over time is not modelled (no combat timeline)',
    'per_unit': 'per-unit scaling is not modelled',
    'per_event': 'event-count scaling is not modelled',
    'state_clause': 'state clauses (while/during) are not modelled',
    'timer': 'timed windows (for Ns) are not modelled (no combat timeline)',
    'sequence_clause': 'sequence clauses (after/upon) are not modelled',
    'unspecified': 'the engine cannot classify this clause yet',
}


def classify_conditional_text(text):
    """A conditional stat line -> (condition_id, state, reason, reason_code).

    Every conditional line in the corpus lands here. The clause is named when the vocabulary
    recognises it, and the *state* says why nothing was applied:

        unsupported   the mechanic behind the clause has no model (the common case today)
        unknown       reserved for conditions the engine can resolve but was not given the input
                      (see `RESOLVABLE`); a text classifier alone cannot produce it

    A line whose clause is recognisable but whose *effect* the engine could apply - there are
    none in Phase 4's corpus, by construction - would report `condition_effect_unimplemented`
    with the same condition state. That path exists so the four refusal reasons stay expressible.
    """
    low = ' ' + str(text or '').strip().lower()
    for needle, condition_id in CONDITION_VOCABULARY:
        if needle in low:
            return (condition_id, UNSUPPORTED, UNMODELLED_CONDITIONS[condition_id],
                    'mechanic_unsupported')
    return ('unspecified', UNSUPPORTED, UNMODELLED_CONDITIONS['unspecified'], 'mechanic_unsupported')


def refusal(condition_id, text, state, reason, reason_code, **extra):
    """The structured block a refused effect carries (milestone 4.2).

    Shape (kept inside the existing marker so no consumer breaks):
        {'condition': 'on_kill', 'state': 'unsupported',
         'reason_code': 'mechanic_unsupported', 'reason': '...', 'text': 'On Kill: ...'}
    """
    return result(condition_id, state, reason, reason_code=reason_code, text=str(text or ''),
                  **extra)


# ------------------------------------------------------------------ selftest
def selftest():
    """The state space, the two resolvable conditions, and the corpus classifier. Offline."""
    failures = []
    counter = [0]

    def check(label, ok, detail=''):
        counter[0] += 1
        print('%s  %s%s' % ('PASS' if ok else 'FAIL', label,
                            '' if ok else ' -- %s' % detail))
        if not ok:
            failures.append(label)

    # --- the state space itself
    check('four states, no more', len(STATES) == 4 and len(set(STATES)) == 4)
    for state in STATES:
        row = result('target_faction', state, 'synthetic', inputs={'k': 1})
        check('state %s carries its own code and meaning' % state,
              row['code'] == STATE_CODES[state] and state in MEANING
              and row['applied'] is (state == SATISFIED))
    for bad in NOT_A_STATE:
        try:
            result('target_faction', bad, 'synthetic')
            check('a non-state (%r) is rejected, not coerced' % (bad,), False)
        except ValueError:
            check('a non-state (%r) is rejected, not coerced' % (bad,), True)

    # --- the four-state meaning: only `satisfied` may apply, and only `not_satisfied` may be zero
    applied = {s: result('x', s, 'y')['applied'] for s in STATES}
    check('only satisfied applies a contribution', applied == {SATISFIED: True,
                                                              NOT_SATISFIED: False,
                                                              UNKNOWN: False,
                                                              UNSUPPORTED: False},
          str(applied))
    check('unknown and unsupported both withhold', withholds(result('x', UNKNOWN, 'y'))
          and withholds(result('x', UNSUPPORTED, 'y')))
    check('unknown and unsupported block the calculation; a false does not',
          blocks(result('x', UNKNOWN, 'y')) and blocks(result('x', UNSUPPORTED, 'y'))
          and not blocks(result('x', NOT_SATISFIED, 'y')))

    # --- target_faction: satisfied / not_satisfied / unknown
    none_ctx = normalise_context(None)
    check('an absent context says so', none_ctx['supplied'] is False)
    unk = target_faction('grineer', none_ctx)
    check('no target faction -> unknown (never a silent zero)',
          unk['state'] == UNKNOWN and unk['reason_code'] == 'condition_unknown', str(unk))
    hit = target_faction('grineer', normalise_context({'target_faction': 'Grineer'}))
    check('matching faction -> satisfied', hit['state'] == SATISFIED and hit['applied'])
    miss = target_faction('grineer', normalise_context({'target_faction': 'corpus'}))
    check('other faction -> not_satisfied, and it is a reported zero',
          miss['state'] == NOT_SATISFIED and not miss['applied']
          and miss['reason_code'] == 'condition_not_satisfied', str(miss))
    check('an unknown context key is reported, not kept',
          normalise_context({'target_faction': 'grineer', 'crit_stacks': 3})['ignored']
          == ['crit_stacks'])

    # --- first_shot: satisfied / not_satisfied / unknown (and a non-ordinal is unknown)
    check('no attack context -> unknown', first_shot(none_ctx)['state'] == UNKNOWN)
    check('shot 1 -> satisfied',
          first_shot(normalise_context({'attack': {'shot_index': 1}}))['state'] == SATISFIED)
    check('shot 3 -> not_satisfied',
          first_shot(normalise_context({'attack': {'shot_index': 3}}))['state']
          == NOT_SATISFIED)
    for bad in ('1', 0, -2, True, 1.5):
        check('shot_index %r is unknown, not coerced' % (bad,),
              first_shot(normalise_context({'attack': {'shot_index': bad}}))['state'] == UNKNOWN)

    # --- evaluate(): an id with no evaluator is unsupported, never a guess
    check('an unknown condition id refuses as unsupported',
          evaluate('weapon_is_primed', none_ctx)['state'] == UNSUPPORTED)
    check('evaluate() reaches the real evaluators',
          evaluate('target_faction', normalise_context({'target_faction': 'grineer'}),
                   faction='grineer')['state'] == SATISFIED)

    # --- the corpus classifier
    cases = {'On Kill:\\n+40% Multishot for 20s. Stacks up to 5x.': 'on_kill',
             '+60% Damage on hit': 'on_hit',
             '+30% Reload Speed on reload': 'on_reload',
             '+120% Critical Damage on headshot': 'on_headshot',
             '+30% Damage per status effect on the target': 'target_status',
             '+5% Damage for each enemy within 10m': 'per_unit',
             '+15% Damage while airborne': 'state_clause',
             '+20% Damage after rolling': 'sequence_clause',
             'Something quite unexpected indeed': 'unspecified'}
    for text, want in cases.items():
        cid, state, reason, code = classify_conditional_text(text)
        check('%r classifies as %s' % (text[:34], want), cid == want, cid)
        check('  ... and refuses as unsupported with a named reason',
              state == UNSUPPORTED and code == 'mechanic_unsupported' and bool(reason))
    check('every classifier answer stays inside the state space',
          all(classify_conditional_text(t)[1] in STATES for t in cases))
    check('the four condition refusals are exactly the four',
          set(CONDITION_REASON_CODES) == {'condition_unknown', 'condition_not_satisfied',
                                          'condition_effect_unimplemented', 'mechanic_unsupported'}
          and set(CONDITION_REASON_CODES).issubset(set(REASON_CODES))
          and set(REASON_CODES) - set(CONDITION_REASON_CODES) == {'context_unused'}
          and all(REASON_CODES[c] for c in REASON_CODES))
    # `context_unused` is the fifth, and it is about a *stated input* rather than a condition:
    # a caller's input this engine has no model for. It stays in the same vocabulary on purpose.
    check('every reason code carries a description, and none is a duplicate',
          all(isinstance(v, str) and v.strip() for v in REASON_CODES.values()) and
          len(set(REASON_CODES.values())) == len(REASON_CODES))
    check('a structured refusal keeps the text it came from',
          refusal('on_kill', 'On Kill: +40% Multishot', UNSUPPORTED, 'r',
                  'mechanic_unsupported')['text'] == 'On Kill: +40% Multishot')
    check('a bad reason_code is a programming error, not a silent default',
          _raises_it(lambda: refusal('on_kill', 'x', UNSUPPORTED, 'r', 'nah')))

    print('\nconditions selftest %s (%d checks, %d failed) - nothing written'
          % ('OK' if not failures else 'FAILED', counter[0], len(failures)))
    return 0 if not failures else 1


def _raises_it(fn):
    try:
        fn()
        return False
    except ValueError:
        return True


if __name__ == '__main__':
    import sys
    sys.exit(selftest())
