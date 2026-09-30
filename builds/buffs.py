#!/usr/bin/env python3
"""Stated buff state: the stack/uptime model for conditional riders (Phase 5, 5.3 + 5.4).

The rule this module exists to enforce: **the engine never simulates combat and never guesses a
combat state.** For a rider such as "On Kill: +30% Multishot for 20s. Stacks up to 5x." the engine
accepts what a caller explicitly states, in exactly one of two forms:

    INSTANT / STATED STATE     {"on_kill": {"stacks": 3}}          - three stacks right now
    AVERAGED / UPTIME STATE    {"on_kill": {"uptime": 0.65, "stacks": 5}}
                                                                - five stacks, active 65% of the
                                                                  time, as stated by the caller

The two concepts are never mixed: an averaged answer says so on the condition row, the rider row,
the trace and `result.assumptions`, and the engine never derives uptime from a duration, a kill
rate or a rotation. Uptime without a stated stack count is `unknown` - the stack count cannot be
invented. `{"active": true}` alone on a stacking buff is `unknown` with the stack count named as
missing, never read as one stack.

The trigger vocabulary is deliberately tiny. Phase 5 enables exactly one rider family - the
"On Kill: +X% <stat> ... Stacks up to Nx" lines whose stat this engine already computes - and every
other conditional line in the corpus keeps refusing. `parse_rider` still describes them (so a
refusal can name the trigger, the stat and the stack clause), which is what makes the refusals
precise without pretending the mechanics work.

Sources for the semantics of the enabled family:
    the mod's own card text (DE export, via builds/ingest.py) carries the value, the duration and
    the "Stacks up to Nx" clause; the wiki's Galvanized pages (e.g. Galvanized Scope, retrieved
    2026-09-30) document that each stack adds the listed value again and that the maximum is
    value x (stacks + 1) at max rank - which is what "Stacks up to Nx" means.
"""
import re

from . import conditions, schema

TRIGGERS = ('on_kill',)
TRIGGER_MARKERS = {'on_kill': 'on kill:'}
# The rider stats Phase 5 applies. Deliberately narrow: a stat is enabled only when the engine
# already computes it and the rider's additive stacking into it is the same arithmetic the mod's
# own unconditional line uses. Everything else parses and refuses.
ENABLED_STATS = {'multishot': 'multishot'}

STATE_FIELDS = ('stacks', 'uptime', 'active')
STACK_CLAUSE_RE = re.compile(r'stacks?\s+up\s+to\s+(\d+)\s*x', re.IGNORECASE)
DURATION_RE = re.compile(r'\bfor\s+(\d+(?:\.\d+)?)\s*s\b', re.IGNORECASE)
VALUE_RE = re.compile(r'([+-]\d+(?:\.\d+)?)\s*%')


def parse_rider(text):
    """A conditional stat line -> what the engine can say about it, or None when it is not a rider.

    Returns (order-stable dict):
        {'text', 'trigger', 'stat', 'unit', 'value', 'max_stacks', 'duration_s',
         'applicable': bool, 'enabled': bool, 'reason': str|None}

    `applicable` means: a trigger this engine resolves, a stat it can name, a signed percentage,
    and a documented "Stacks up to Nx" clause. `enabled` means the stat is one of ENABLED_STATS.
    A rider that is applicable but not enabled is still refused by name - the difference is only
    how precisely the engine can say why.
    """
    if text is None:
        return None
    raw = str(text).strip()
    low = raw.lower()
    trigger = None
    for name in TRIGGERS:
        if low.startswith(TRIGGER_MARKERS[name]):
            trigger = name
            break
    rider = {'text': raw, 'trigger': trigger, 'stat': None, 'unit': None, 'value': None,
             'max_stacks': None, 'duration_s': None, 'applicable': False, 'enabled': False,
             'reason': None}
    if trigger is None:
        rider['reason'] = 'the trigger is not one this engine resolves'
        return rider
    body = raw[len(TRIGGER_MARKERS[trigger]):].strip()
    value_match = VALUE_RE.search(body)
    if not value_match:
        rider['reason'] = 'the line carries no signed percentage this engine can read'
        return rider
    rider['value'] = float(value_match.group(1))
    rider['unit'] = 'percent'
    tail = body[value_match.end():].strip()
    duration = DURATION_RE.search(tail)
    if duration:
        rider['duration_s'] = float(duration.group(1))
        tail = (tail[:duration.start()] + tail[duration.end():]).strip()
    stacks = STACK_CLAUSE_RE.search(tail)
    if stacks:
        rider['max_stacks'] = int(stacks.group(1))
        tail = (tail[:stacks.start()] + tail[stacks.end():]).strip()
    phrase = tail.strip(' .,;:')
    phrase = re.sub(r'\s+', ' ', phrase).strip().lower()
    vocab = schema.STAT_VOCABULARY.get(phrase)
    if vocab:
        rider['stat'], canon_unit = vocab
        rider['unit'] = canon_unit or 'percent'
    if rider['stat'] is None:
        rider['reason'] = ('the rider\'s stat is not one this engine models (%r)' % phrase
                           if phrase else 'the line names no stat this engine models')
        return rider
    if rider['max_stacks'] is None:
        rider['reason'] = ('the rider moves %s but carries no "Stacks up to Nx" clause, so this '
                           'engine has no sourced stacking model for it' % rider['stat'])
        return rider
    if rider['value'] is None or rider['value'] <= 0:
        rider['reason'] = 'the rider is not a positive bonus this engine applies'
        return rider
    rider['applicable'] = True
    rider['enabled'] = rider['stat'] in ENABLED_STATS
    if not rider['enabled']:
        rider['reason'] = ('the rider moves %s, which this phase does not apply conditionally'
                           % rider['stat'])
    return rider


def effective_stacks(row):
    """The stacks an averaged/instant row grants (a float), or None when the row grants none.

    `satisfied` rows carry `stacks_effective`; everything else returns None so a caller cannot
    multiply by a missing key. A `not_satisfied` row contributes a reported zero - the caller adds
    nothing, and the row says the contribution is zero on purpose.
    """
    if not row or row.get('state') != conditions.SATISFIED:
        return None
    return row.get('stacks_effective')


def evaluate_state(trigger, raw_state, max_stacks, mod=None, mod_name=None):
    """A caller-stated buff state -> one condition result (all four states, never a boolean).

    `max_stacks` is the cap the *mod's own card* documents ("Stacks up to Nx"), so a state that is
    fine for one mod can still be refused for another one in the same build - which is the truth.
    """
    where = {'trigger': trigger, 'mod': mod, 'mod_name': mod_name, 'max_stacks': max_stacks}
    if trigger not in TRIGGERS:
        return conditions.result(
            trigger, conditions.UNSUPPORTED,
            'this engine has no model for the %r trigger' % (trigger,),
            reason_code='mechanic_unsupported', **where)
    if raw_state is None:
        return conditions.result(
            trigger, conditions.UNKNOWN,
            'no %s state was supplied for this evaluation: state the active stacks, or an '
            'uptime and the stacks to assume' % trigger,
            reason_code='condition_unknown', missing=['buffs.' + trigger], **where)
    if not isinstance(raw_state, dict):
        return conditions.result(
            trigger, conditions.UNKNOWN,
            'buffs.%s %r is not an object this engine will interpret' % (trigger, raw_state),
            reason_code='condition_unknown', inputs={trigger: repr(raw_state)},
            missing=['buffs.%s as an object' % trigger], **where)
    stacks = raw_state.get('stacks')
    uptime = raw_state.get('uptime')
    active = raw_state.get('active')
    inputs = {k: v for k, v in raw_state.items() if k in STATE_FIELDS}
    unknown_keys = [k for k in raw_state if k not in STATE_FIELDS]

    # --- the contradictions and malformed shapes first: none of them may be coerced -------------
    if uptime is not None and (isinstance(uptime, bool) or not isinstance(uptime, (int, float))):
        return conditions.result(
            trigger, conditions.UNKNOWN,
            'uptime %r is not a fraction in 0..1' % (uptime,),
            reason_code='condition_unknown', inputs=inputs,
            missing=['an uptime as a number in 0..1'], **where)
    if uptime is not None:
        # the same unbounded-integer rule as the target fields: 10**400 is a stated value this
        # engine cannot express, and it must answer rather than raise
        try:
            fraction = float(uptime)
        except (OverflowError, ValueError):
            fraction = None
        if fraction is None or fraction != fraction or fraction in (float('inf'), float('-inf')) \
                or not (0.0 <= fraction <= 1.0):
            return conditions.result(
                trigger, conditions.UNKNOWN,
                'uptime %r is outside 0..1, so it is not a fraction of time' % (uptime,),
                reason_code='condition_unknown', inputs=inputs,
                missing=['an uptime as a number in 0..1'], **where)
    if active is not None and not isinstance(active, bool):
        return conditions.result(
            trigger, conditions.UNKNOWN,
            'active %r is not a boolean, and this engine will not read a truthy string as one'
            % (active,),
            reason_code='condition_unknown', inputs=inputs,
            missing=['a boolean active'], **where)
    if stacks is not None and (isinstance(stacks, bool) or not isinstance(stacks, int)):
        return conditions.result(
            trigger, conditions.UNKNOWN,
            'stacks %r is not a stack count this engine will interpret' % (stacks,),
            reason_code='condition_unknown', inputs=inputs,
            missing=['an integer stack count'], **where)
    if stacks is not None and stacks < 0:
        return conditions.result(
            trigger, conditions.UNKNOWN,
            'stacks %d is negative, which is not a buff state' % stacks,
            reason_code='condition_unknown', inputs=inputs,
            missing=['a non-negative stack count'], **where)
    if stacks is not None and stacks > max_stacks:
        return conditions.result(
            trigger, conditions.UNSUPPORTED,
            'stacks %d is above the %dx cap this mod documents: stacks beyond it replace the '
            'oldest, which is a timeline this engine does not model' % (stacks, max_stacks),
            reason_code='mechanic_unsupported', inputs=inputs,
            unsupported_code='buff_stacks_above_cap', **where)
    if active is False and stacks:
        return conditions.result(
            trigger, conditions.UNKNOWN,
            'the state says the effect is both inactive and carrying %d stacks' % stacks,
            reason_code='condition_unknown', inputs=inputs,
            missing=['either active: false or a stack count, not both'], **where)

    # --- averaged / uptime state -----------------------------------------------------------------
    if uptime is not None:
        if stacks is None:
            return conditions.result(
                trigger, conditions.UNKNOWN,
                'an averaged state was requested (uptime %r) but the stack count to assume was '
                'not stated; this engine does not invent one' % (uptime,),
                reason_code='condition_unknown', inputs=inputs,
                missing=['buffs.%s.stacks' % trigger], **where)
        fraction = float(uptime)
        assumed = stacks * fraction
        assumption = ('averaged: %d stack%s at %s%% uptime (stated by the caller)'
                      % (stacks, '' if stacks == 1 else 's', round(fraction * 100.0, 4)))
        if assumed == 0:
            return conditions.result(
                trigger, conditions.NOT_SATISFIED,
                'the stated uptime is 0%%, so the effect contributes nothing',
                reason_code='condition_not_satisfied', inputs=inputs,
                mode='averaged', assumption=assumption,
                stacks=stacks, uptime=fraction, stacks_effective=0.0, **where)
        return conditions.result(
            trigger, conditions.SATISFIED,
            '%d stack%s averaged over %s%% uptime' % (stacks, '' if stacks == 1 else 's',
                                                      round(fraction * 100.0, 4)),
            inputs=inputs, mode='averaged', assumption=assumption,
            stacks=stacks, uptime=fraction, stacks_effective=assumed, **where)

    # --- instant / stated state ------------------------------------------------------------------
    if active is False and stacks is None:
        return conditions.result(
            trigger, conditions.NOT_SATISFIED,
            'the caller states the effect is not active',
            reason_code='condition_not_satisfied', inputs=inputs, mode='instant',
            stacks=0, stacks_effective=0.0, **where)
    if stacks is None:
        if active is True:
            return conditions.result(
                trigger, conditions.UNKNOWN,
                'the effect is stated active, but this rider stacks up to %dx and no stack count '
                'was given; this engine will not assume one' % max_stacks,
                reason_code='condition_unknown', inputs=inputs, mode='instant',
                missing=['buffs.%s.stacks' % trigger], **where)
        return conditions.result(
            trigger, conditions.UNKNOWN,
            'the state names neither stacks nor active',
            reason_code='condition_unknown', inputs=inputs, mode='instant',
            missing=['buffs.%s.stacks' % trigger], **where)
    if stacks == 0:
        return conditions.result(
            trigger, conditions.NOT_SATISFIED,
            'the effect currently has no stacks',
            reason_code='condition_not_satisfied', inputs=inputs, mode='instant',
            stacks=0, stacks_effective=0.0, **where)
    if unknown_keys:
        # Named, not dropped: a rider row that quietly ignored half its input would look supported.
        return conditions.result(
            trigger, conditions.UNKNOWN,
            'the state carries field(s) this engine does not read: %s'
            % ', '.join(sorted(str(k) for k in unknown_keys)),
            reason_code='condition_unknown', inputs=inputs, mode='instant',
            missing=['one of: ' + ', '.join(STATE_FIELDS)], **where)
    return conditions.result(
        trigger, conditions.SATISFIED,
        'the effect currently carries %d stack%s' % (stacks, '' if stacks == 1 else 's'),
        inputs=inputs, mode='instant', stacks=stacks, stacks_effective=float(stacks), **where)


def rider_trace_row(mod_name, mod_id, rank, rider, row, contribution, total_after=None):
    """The trace-modifier row an applied rider contributes (never built for a refusal)."""
    if row.get('state') != conditions.SATISFIED:
        return None
    mode = row.get('mode')
    note = ('%g%% per stack, %d stack%s -> +%g%% multishot'
            % (rider['value'], row.get('stacks'),
               '' if row.get('stacks') == 1 else 's',
               round(contribution, 4)))
    if mode == 'averaged':
        note = '%s (%s)' % (note, row.get('assumption') or 'averaged')
    return {'source': 'On Kill', 'category': 'percent', 'value': round(contribution, 4),
            'unit': 'percent', 'mod': mod_id, 'mod_name': mod_name, 'rank': rank,
            'condition': row.get('condition'), 'state': row.get('state'),
            'stacks': row.get('stacks'), 'mode': mode,
            'assumption': row.get('assumption'), 'note': note}


def assumption_lines(rows):
    """Every stated assumption in a list of condition rows (for `result.assumptions`)."""
    out = []
    for row in rows or []:
        text = (row or {}).get('assumption')
        if text and text not in out:
            out.append(text)
    return out


# ------------------------------------------------------------------ selftest
def selftest():
    failures, counter = [], [0]

    def check(label, ok, detail=''):
        counter[0] += 1
        print('%s  %s%s' % ('PASS' if ok else 'FAIL', label, '' if ok else ' -- %s' % detail))
        if not ok:
            failures.append(label)

    # --- parse_rider on the corpus family
    galv = parse_rider('On Kill: +30% Multishot for 20s. Stacks up to 5x.')
    check('a Galvanized rider parses: trigger, stat, value, stacks, duration',
          galv['trigger'] == 'on_kill' and galv['stat'] == 'multishot' and galv['value'] == 30
          and galv['max_stacks'] == 5 and galv['duration_s'] == 20
          and galv['applicable'] and galv['enabled'], str(galv))
    r0 = parse_rider('On Kill: +2.7% Multishot for 20s. Stacks up to 5x.')
    check('a rank-0 spelling parses with its own value', r0['value'] == 2.7 and r0['enabled'])
    other = parse_rider('On Kill: +50% Reload Speed for 3s')
    check('a rider with no stack clause is described but not applicable',
          other['stat'] == 'reload_speed' and not other['applicable']
          and 'Stacks up to' in other['reason'], str(other))
    apt = parse_rider('On Kill: +40% Direct Damage per Status Type affecting the target for 20s. '
                      'Stacks up to 2x.')
    check('a per-status rider parses only to a refusal with a named stat',
          not apt['applicable'] and apt['stat'] is None and apt['reason'], str(apt))
    weird = parse_rider('On Kill or Assist: Slain enemies have a 2% chance to drop an Energy Orb')
    check('a different trigger is not an on_kill rider', weird['trigger'] is None
          and not weird['applicable'])
    check('an empty line is None', parse_rider('') is not None and parse_rider(None) is None)

    # --- the four states, instant
    ok = evaluate_state('on_kill', {'stacks': 3}, 5, mod='m', mod_name='Galvanized Chamber')
    check('3 stacks -> satisfied, effective 3', ok['state'] == 'satisfied'
          and ok['stacks_effective'] == 3.0 and ok['mode'] == 'instant')
    zero = evaluate_state('on_kill', {'stacks': 0}, 5)
    check('0 stacks -> not_satisfied (a reported zero)', zero['state'] == 'not_satisfied'
          and zero['stacks_effective'] == 0.0)
    off = evaluate_state('on_kill', {'active': False}, 5)
    check('active: false -> not_satisfied', off['state'] == 'not_satisfied')
    missing = evaluate_state('on_kill', None, 5)
    check('no state -> unknown with the input named', missing['state'] == 'unknown'
          and missing['reason_code'] == 'condition_unknown'
          and missing['missing'] == ['buffs.on_kill'])
    over = evaluate_state('on_kill', {'stacks': 6}, 5)
    check('stacks above the mod cap -> unsupported with the cap named',
          over['state'] == 'unsupported' and over['unsupported_code'] == 'buff_stacks_above_cap')
    check('the same state is fine for a mod with a higher cap',
          evaluate_state('on_kill', {'stacks': 6}, 6)['state'] == 'satisfied')

    # --- averaged
    avg = evaluate_state('on_kill', {'uptime': 0.65, 'stacks': 5}, 5)
    check('uptime + stacks -> satisfied at stacks x uptime, with the assumption stated',
          avg['state'] == 'satisfied' and abs(avg['stacks_effective'] - 3.25) < 1e-9
          and avg['mode'] == 'averaged' and '65' in avg['assumption'], str(avg))
    avg_no_stacks = evaluate_state('on_kill', {'uptime': 0.65}, 5)
    check('uptime without stacks -> unknown (no invented stack count)',
          avg_no_stacks['state'] == 'unknown'
          and avg_no_stacks['missing'] == ['buffs.on_kill.stacks'])
    check('uptime 0 -> not_satisfied', evaluate_state('on_kill', {'uptime': 0, 'stacks': 5},
                                                      5)['state'] == 'not_satisfied')
    for bad in (1.5, -0.1, '65%', True, [0.5]):
        check('uptime %r -> unknown, never coerced' % (bad,),
              evaluate_state('on_kill', {'uptime': bad, 'stacks': 5}, 5)['state'] == 'unknown')

    # --- contradiction / malformed shapes
    check('active false + stacks -> unknown (contradiction)',
          evaluate_state('on_kill', {'active': False, 'stacks': 3}, 5)['state'] == 'unknown')
    check('active: true alone on a stacking buff -> unknown (no assumed stack)',
          evaluate_state('on_kill', {'active': True}, 5)['state'] == 'unknown')
    check('active: "yes" -> unknown, never read as True',
          evaluate_state('on_kill', {'active': 'yes'}, 5)['state'] == 'unknown')
    check('stacks "3" -> unknown, never coerced',
          evaluate_state('on_kill', {'stacks': '3'}, 5)['state'] == 'unknown')
    check('empty state object -> unknown', evaluate_state('on_kill', {}, 5)['state'] == 'unknown')
    check('a non-object state -> unknown',
          evaluate_state('on_kill', 'active', 5)['state'] == 'unknown')
    check('an unread field is named, not dropped',
          'field(s)' in (evaluate_state('on_kill', {'stacks': 2, 'kills': 4}, 5)['reason'] or ''))
    check('an unknown trigger -> unsupported with the trigger named',
          evaluate_state('on_reload', {'stacks': 1}, 1)['state'] == 'unsupported')

    # malformed input never raises
    for junk in (42, [1, 2], {'stacks': {}}, {'stacks': 1.5}, {'uptime': float('inf')},
                 {'active': None, 'stacks': None}, float('nan')):
        try:
            evaluate_state('on_kill', junk, 5)
        except Exception as exc:                                     # noqa: BLE001
            check('a malformed state never raises (%r: %s)' % (junk, exc), False)
    check('malformed states never raise', True)

    # --- the trace row only exists for a real contribution
    row = rider_trace_row('Galvanized Chamber', 'id', 10, galv, ok, 90.0)
    check('an applied rider traces its per-stack arithmetic', row['value'] == 90.0
          and '30%' in row['note'] and row['stacks'] == 3)
    check('a refusal traces nothing', rider_trace_row('x', 'id', 10, galv, missing, None) is None)
    check('assumption_lines collects the averaged assumption',
          assumption_lines([avg]) == [avg['assumption']] and assumption_lines([ok, zero]) == [])

    print('\nbuffs selftest %s (%d checks, %d failed) - nothing written'
          % ('OK' if not failures else 'FAILED', counter[0], len(failures)))
    return 0 if not failures else 1


if __name__ == '__main__':
    import sys
    sys.exit(selftest())
