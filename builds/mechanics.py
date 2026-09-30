"""The declarative mechanic registry (Phase 6, 6.1).

Phase 5's fourth adversarial review found that a mechanic's requirements lived in four unrelated
places - trigger logic, consumed-context accounting, the trace hook, and the target/mitigation
integration - and that forgetting one of them failed *silently*: a stated field vanished, a factor
went untraced, a refusal lost its blast radius. This module is the one place a mechanic is declared.

A declaration is machine-readable, and the engine derives from it:

1. **consumed-context accounting** - the fields a mechanic reads are `consumes`; the union over the
   registry is what `evaluation.unused`, the `context_unused` markers and the canonical target /
   attack field lists are built from (`conditions.py` reads `consumed_fields()`);
2. **condition/evaluation dispatch** - `path_rule()` is the target path's trigger,
   `armour_transformers()` is the target-state loop that applies armour transforms in registry
   order (corrosive and Heat both land through it), `rider_stats()` is the set of conditional-rider
   stats that may apply from stated build state, and `live()` decides whether a mechanic is asked
   its question at all (its stated trigger, or a build fact it declares as `required_when`);
3. **trace destination** - every mechanic names where its rows go (`trace`, or `stat_traces` when
   the destination depends on which stat it moves), so nothing is attached to a trace by hand;
4. **unsupported/refusal registration** - a mechanic's `refusal_codes` are checked against
   `builds/unsupported.REGISTRY` and the reason-code vocabulary at import and in the gates, so a
   refusal cannot ship unnamed;
5. **mechanic discovery/introspection** - `introspect()` feeds `python builds/debug.py mechanics`,
   the Phase 6 gate's report, and the docs.

A declaration that is missing a required property raises `MechanicDeclarationError` at import - a
half-declared mechanic fails loudly at start-up instead of being silently ignored at runtime (the
architecture-invariant test asserts exactly that).

Nothing in here does arithmetic. The registry *describes* mechanics whose implementations live in
the engine modules (`builds/enemies.py`, `builds/statuses.py`, `builds/buffs.py`, ...), referenced
by dotted path and resolved lazily so the registry can never create an import cycle.
"""
import importlib
import sys

__all__ = [
    'FAMILIES', 'STAGES', 'Rule', 'Mechanic', 'MechanicDeclarationError', 'REGISTRY',
    'register', 'resolve', 'by_family', 'by_stage', 'by_condition', 'consumed_fields',
    'required_fields', 'path_rule', 'armour_transformers', 'implemented_transformers', 'live',
    'rider_stats', 'trace_for', 'withholds_for', 'deps_for', 'roster_contract', 'refusal_codes',
    'introspect', 'table', 'TARGET_PATH_RULE', 'REQUIRED_WHEN', 'UNDECLARED_WITHHOLDS',
    'verify_declarations', 'PENDING_VERIFICATION', 'STAGES_BY_FAMILY', 'SINGLETON_STAGES',
    'TRACE_KEYS',
]

FAMILIES = ('target_damage', 'target_state', 'build_state', 'set', 'pool')
STAGES = ('target_path', 'damage_per_type', 'damage_to_health', 'armour_transform',
          'rider_contribution', 'set_scaling', 'pool_result')
# Which stages a family may run: a declaration that no dispatcher would ever reach is a silent
# no-op with a nice name (review 1, F5).
STAGES_BY_FAMILY = {
    'target_damage': ('target_path', 'damage_per_type'),
    'target_state': ('target_path', 'armour_transform', 'damage_to_health'),
    'build_state': ('damage_per_type', 'rider_contribution'),
    'set': ('set_scaling',),
    'pool': ('pool_result',),
}
# Stages the engine runs exactly once per pass: a second declaration for one of them would never be
# consulted (review 1, F5: a second rider mechanic registered silently and its stats were ignored).
SINGLETON_STAGES = ('rider_contribution', 'pool_result')
# The trace keys the engine builds. A declared destination outside this set is a trace the user can
# never open (review 1, F5), so it is refused at import rather than shipped.
TRACE_KEYS = ('damage', 'damage_multiplier', 'elemental_damage', 'impact', 'puncture', 'slash',
              'heat', 'cold', 'electricity', 'toxin', 'blast', 'corrosive', 'gas', 'magnetic',
              'radiation', 'viral', 'void', 'true', 'multishot', 'critical_chance',
              'critical_multiplier', 'status_chance', 'magazine_size', 'reload_time', 'fire_rate',
              'attack_speed', 'damage_to_health', 'viral_amplifier', 'target_damage', 'pool',
              'health', 'armor', 'shield', 'shields', 'energy', 'ability_strength',
              'ability_duration', 'ability_range', 'sprint_speed', 'zoom', 'punch_through',
              'range', 'combo_duration', 'status_duration', 'accuracy', 'recoil',
              'projectile_speed')
# the result keys a mechanic's refusal is allowed to withhold (its blast radius)
WITHHOLD_KEYS = ('target_damage', 'damage_per_shot', 'damage_per_shot_expected_crit', 'burst_dps',
                 'sustained_dps', 'damage_to_health', 'damage_to_health_expected_crit',
                 'damage_on_first_shot', 'multishot', 'critical_chance', 'critical_damage',
                 'status_chance', 'reload_time', 'fire_rate', 'pool', 'shots_to_kill')


class MechanicDeclarationError(Exception):
    """A mechanic was declared without something the engine needs to derive its plumbing."""


# --------------------------------------------------------------------------- the rule DSL
class Rule:
    """A machine-readable statement about which context fields make a mechanic live.

    `field` / `any_of` / `all_of` nest, so the target path's trigger - armour, or a landing plus a
    faction, or a stated state mechanic - is data, not a hand-written `if` in the weapon engine.
    """

    __slots__ = ('field', 'any_of', 'all_of')

    def __init__(self, field=None, any_of=(), all_of=()):
        self.field = field
        self.any_of = tuple(any_of)
        self.all_of = tuple(all_of)

    def fields(self):
        """Every dotted field this rule mentions (for consumed accounting)."""
        out = []
        if self.field:
            out.append(self.field)
        for part in list(self.any_of) + list(self.all_of):
            out.extend(part.fields() if isinstance(part, Rule) else [part])
        return tuple(out)

    def stated(self, ctx):
        for part in self.any_of:
            if _stated(part, ctx):
                return True
        if self.any_of:
            return False
        if self.all_of:
            return all(_stated(part, ctx) for part in self.all_of)
        return _stated(self.field, ctx)

    def describe(self):
        def one(part):
            if not isinstance(part, Rule):
                return part
            text = part.describe()
            return '(%s)' % text if (part.any_of and part.all_of) else text
        if self.any_of:
            return ' or '.join(one(part) for part in self.any_of)
        if self.all_of:
            return ' and '.join(one(part) for part in self.all_of)
        return self.field or '?'


def _stated(part, ctx):
    from . import conditions
    if isinstance(part, Rule):
        return part.stated(ctx)
    head, _, tail = part.partition('.')
    if tail:
        return conditions.has(ctx, head, tail)
    return conditions.has(ctx, head)


def F(field):
    return Rule(field=field)


def ANY(*parts):
    return Rule(any_of=parts)


def ALL(*parts):
    return Rule(all_of=parts)


# What makes the target path run at all (Phase 5's semantics, plus Heat): armour stated, or a
# landing layer plus a faction, or a stated state mechanic. Declared here so weapons.py asks the
# registry instead of restating it - and so a new target mechanic cannot forget to join the path.
TARGET_PATH_RULE = ANY(F('target.armor'), ALL(F('target_faction'), F('target.protection')),
                       F('target.corrosive_stacks'), F('target.heat_strip'), F('target.preset'))
# A mechanic can also be live because of the build itself (the engine calls this its "required_when"
# fact): a build that deals viral is asked the viral question even with no target state stated.
REQUIRED_WHEN = ('build.deals_viral', 'build.deals_corrosive', 'build.deals_heat')


# --------------------------------------------------------------------------- the declaration
class Mechanic:
    """One mechanic, declared once.

    `consumes` is dotted and canonical ('target.armor', 'buffs.on_kill', 'target_faction').
    `required` / `one_of` fields absent from a live mechanic make it `unknown` with the field named;
    `optional` fields are read when stated and never demanded.
    `withholds` lists the result keys a refusal of this mechanic may suppress - its blast radius.
    `deps` names the mechanics whose answers it needs (dependency/blast-radius tests derive from it).
    """

    REQUIRED_PROPERTIES = ('id', 'name', 'family', 'stage', 'consumes', 'source',
                           'instant', 'averaged', 'strict', 'hypothetical', 'emits_rows')

    def __init__(self, id, name, family, stage, consumes=(), required=(), optional=(), one_of=(),
                 stats=(), trigger=None, trace=None, stat_traces=None, emits_rows=True,
                 condition_id=None, refusal_codes=(), source='', instant=True, averaged=False,
                 strict=True, hypothetical=True, withholds=(), deps=(), required_when=None,
                 roster=None, evaluate=None, apply=None, trace_row=None, notes=''):
        self.id = id
        # The condition-row id this mechanic emits (defaults to its own id). The engine's rows and
        # the registry are joined through this, which is what lets a refusal's blast radius be
        # derived from the declaration instead of a hand-written list at the call site.
        self.condition_id = condition_id or id
        self.name = name
        self.family = family
        self.stage = stage
        self.consumes = tuple(consumes)
        self.required = tuple(required)
        self.optional = tuple(optional)
        self.one_of = tuple(one_of)
        self.stats = tuple(stats)
        self.trigger = trigger
        self.trace = trace
        self.stat_traces = dict(stat_traces or {})
        self.emits_rows = emits_rows
        self.refusal_codes = tuple(refusal_codes)
        self.source = source
        self.instant = instant
        self.averaged = averaged
        self.strict = strict
        self.hypothetical = hypothetical
        self.withholds = tuple(withholds)
        self.deps = tuple(deps)
        self.required_when = required_when
        self.roster = roster
        self.evaluate = evaluate
        self.apply = apply
        # the builder for this mechanic's trace row(s): a declared function, not an `if` at the
        # trace site (the attacker of this registry is a mechanic whose row silently never appears)
        self.trace_row = trace_row
        self.notes = notes

    def as_row(self):
        """The introspection row (debug.py, the gate report, the docs)."""
        return {
            'id': self.id, 'name': self.name, 'family': self.family, 'stage': self.stage,
            'condition_id': self.condition_id,
            'trigger': self.trigger.describe() if self.trigger else None,
            'consumes': list(self.consumes), 'required': list(self.required),
            'optional': list(self.optional), 'one_of': list(self.one_of),
            'stats': list(self.stats),
            'trace': self.trace or (self.stat_traces and 'by stat' or None),
            'trace_by_stat': dict(self.stat_traces), 'emits_rows': self.emits_rows,
            'refusal_codes': list(self.refusal_codes),
            'states': _states(self), 'withholds': list(self.withholds), 'deps': list(self.deps),
            'required_when': self.required_when, 'roster': self.roster,
            'evaluate': self.evaluate, 'apply': self.apply, 'trace_row': self.trace_row,
            'source': self.source,
            'notes': self.notes,
        }


def _states(m):
    out = []
    if m.instant:
        out.append('instant')
    if m.averaged:
        out.append('averaged')
    if m.strict:
        out.append('strict')
    if m.hypothetical:
        out.append('hypothetical')
    return out


REGISTRY = {}
# Paths whose module was still importing when the declaration was registered: the engine and the
# registry import each other by design (conditions derives its field list from the registry), so
# those are verified by verify_declarations() instead of at registration time.
PENDING_VERIFICATION = []


def register(mechanic):
    """Validate and add a declaration. Raises `MechanicDeclarationError` on anything incomplete."""
    _validate(mechanic)
    if mechanic.id in REGISTRY:
        raise MechanicDeclarationError('mechanic %r is declared twice' % mechanic.id)
    for existing in REGISTRY.values():
        if existing.stage in SINGLETON_STAGES and existing.stage == mechanic.stage:
            raise MechanicDeclarationError(
                'mechanic %r declares the %r stage, which %r already runs: the engine runs that '
                'stage once per pass, so this declaration would never be consulted'
                % (mechanic.id, mechanic.stage, existing.id))
        if existing.condition_id == mechanic.condition_id:
            raise MechanicDeclarationError(
                'mechanic %r emits the condition row %r, which %r already emits: condition ids are '
                'how a refusal row is traced back to its mechanic, so they have to be unique'
                % (mechanic.id, mechanic.condition_id, existing.id))
    REGISTRY[mechanic.id] = mechanic
    return mechanic


def _declare_path(path, property_name, mechanic):
    """A declared implementation must be a dotted path that resolves to a callable.

    It is resolved here, at registration time, so a typo is a start-up error rather than an
    AttributeError in a caller's request (review 1, F5). The registry still holds only the path, so
    it never imports the engine eagerly by itself.
    """
    if path is None:
        return
    if '.' not in str(path):
        raise MechanicDeclarationError(
            'mechanic %r: %s must be a dotted module.attribute path, not %r'
            % (mechanic.id, property_name, path))
    module_name, _, attribute = str(path).partition('.')
    try:
        target = resolve(path)
    except ImportError as exc:
        raise MechanicDeclarationError(
            'mechanic %r: %s=%r does not resolve (%s)' % (mechanic.id, property_name, path, exc))
    except AttributeError as exc:
        module = sys.modules.get('%s.%s' % (__package__, module_name))
        if module is not None and getattr(getattr(module, '__spec__', None), '_initializing', False):
            # the engine module is mid-import (the registry's import cycle): defer
            PENDING_VERIFICATION.append((mechanic.id, property_name, path))
            return
        raise MechanicDeclarationError(
            'mechanic %r: %s=%r does not resolve (%s)' % (mechanic.id, property_name, path, exc))
    if not callable(target):
        raise MechanicDeclarationError(
            'mechanic %r: %s=%r is not callable' % (mechanic.id, property_name, path))


def _validate(m):
    for prop in Mechanic.REQUIRED_PROPERTIES:
        if getattr(m, prop, None) in (None, ''):
            raise MechanicDeclarationError('mechanic %r is missing %s' % (m.id, prop))
    if m.family not in FAMILIES:
        raise MechanicDeclarationError('mechanic %r: unknown family %r (one of %s)'
                                       % (m.id, m.family, FAMILIES))
    if m.stage not in STAGES:
        raise MechanicDeclarationError('mechanic %r: unknown stage %r (one of %s)'
                                       % (m.id, m.stage, STAGES))
    if m.stage not in STAGES_BY_FAMILY.get(m.family, ()):
        raise MechanicDeclarationError(
            'mechanic %r: a %s mechanic cannot run the %r stage (that family runs %s) - no '
            'dispatcher would ever reach it'
            % (m.id, m.family, m.stage, STAGES_BY_FAMILY.get(m.family)))
    for prop in ('id', 'name', 'family', 'stage', 'source'):
        if not isinstance(getattr(m, prop), str) or not getattr(m, prop).strip():
            raise MechanicDeclarationError(
                'mechanic %r: %s must be a non-empty string (got %r)'
                % (m.id, prop, getattr(m, prop)))
    for prop in ('instant', 'averaged', 'strict', 'hypothetical', 'emits_rows'):
        if not isinstance(getattr(m, prop), bool):
            raise MechanicDeclarationError(
                'mechanic %r: %s must be True or False (got %r)'
                % (m.id, prop, getattr(m, prop)))
    for destination in ([m.trace] if m.trace else []) + list(m.stat_traces.values()):
        base = str(destination).split('.')[0]
        if '{' in str(destination):
            continue
        if base not in TRACE_KEYS:
            raise MechanicDeclarationError(
                'mechanic %r declares the trace destination %r, which is not a trace this engine '
                'builds (known keys: %s ...)' % (m.id, destination, ', '.join(TRACE_KEYS[:6])))
    # A mechanic must support at least one state: a declaration that supports none of them is a
    # mechanic that can never answer, which is the same silent hole by another route.
    if not any((m.instant, m.averaged, m.strict, m.hypothetical)):
        raise MechanicDeclarationError(
            'mechanic %r supports no state (instant/averaged/strict/hypothetical are all False)'
            % m.id)
    # A mechanic that cannot say which stated fields make it live is exactly the silent failure this
    # registry exists to stop - but a declaration whose only job is to name a refused input or
    # domain (no evaluator, no rows) is allowed to be input-less.
    refusal_only = not m.evaluate and not m.apply and not m.emits_rows
    if m.family in ('target_damage', 'target_state', 'pool') and not m.trigger and not refusal_only:
        raise MechanicDeclarationError(
            'mechanic %r: a %s mechanic must declare its trigger rule - a mechanic that cannot say '
            'which stated fields make it live is exactly the silent-failure this registry exists '
            'to stop' % (m.id, m.family))
    if m.family in ('target_state', 'target_damage', 'build_state', 'pool') and not m.consumes \
            and not m.trigger and not refusal_only:
        raise MechanicDeclarationError('mechanic %r consumes nothing and has no trigger' % m.id)
    if m.emits_rows and not (m.trace or m.stat_traces):
        raise MechanicDeclarationError(
            'mechanic %r emits rows but declares no trace destination (trace or stat_traces) - an '
            'untraced factor is a number the user cannot audit' % m.id)
    for stat, key in m.stat_traces.items():
        if not key:
            raise MechanicDeclarationError('mechanic %r: stat_traces[%r] is empty' % (m.id, stat))
    if m.stats and m.stat_traces and set(m.stat_traces) != set(m.stats):
        raise MechanicDeclarationError(
            'mechanic %r moves the stats %s but declares destinations only for %s: a stat without a '
            'declared destination is a factor the user cannot audit'
            % (m.id, ', '.join(sorted(m.stats)),
               ', '.join(sorted(m.stat_traces)) or 'none'))
    if m.stats and not m.stat_traces and m.family == 'build_state' and not m.trace:
        raise MechanicDeclarationError('mechanic %r moves stats but names no destination' % m.id)
    from . import conditions as conditions_mod
    from . import unsupported as unsupported_mod
    for code in m.refusal_codes:
        if unsupported_mod.entry(code) is None and code not in conditions_mod.REASON_CODES:
            raise MechanicDeclarationError(
                'mechanic %r declares refusal code %r, which is neither a row in '
                'builds/unsupported.REGISTRY nor a known reason code' % (m.id, code))
    for key in m.withholds:
        if key not in WITHHOLD_KEYS:
            raise MechanicDeclarationError(
                'mechanic %r withholds %r, which is not a published result key' % (m.id, key))
    for dep in m.deps:
        if dep not in REGISTRY:
            raise MechanicDeclarationError(
                'mechanic %r depends on %r, which is declared later or not at all (declare '
                'dependencies first)' % (m.id, dep))
    for field_name in m.one_of:
        if field_name not in m.consumes:
            raise MechanicDeclarationError(
                'mechanic %r lists %r in one_of but does not consume it' % (m.id, field_name))
    if m.required_when is not None and m.required_when not in REQUIRED_WHEN:
        raise MechanicDeclarationError(
            'mechanic %r: unknown required_when fact %r (one of %s)'
            % (m.id, m.required_when, REQUIRED_WHEN))
    for group in (m.required, m.optional):
        for field_name in group:
            if field_name not in m.consumes:
                raise MechanicDeclarationError(
                    'mechanic %r lists %r as required/optional but does not consume it'
                    % (m.id, field_name))
    for field_name in m.trigger.fields() if m.trigger else ():
        if field_name not in m.consumes:
            raise MechanicDeclarationError(
                'mechanic %r trigger names %r but consumes does not (a trigger that reads an '
                'undeclared field would vanish from the unused accounting)' % (m.id, field_name))
    _declare_path(m.evaluate, 'evaluate', m)
    _declare_path(m.apply, 'apply', m)
    _declare_path(m.trace_row, 'trace_row', m)
    if m.stage == 'armour_transform' and m.evaluate and not m.trace_row:
        raise MechanicDeclarationError(
            'mechanic %r transforms the armour but declares no trace_row: an applied transform '
            'whose trace row is missing is a number the user cannot audit' % m.id)


# --------------------------------------------------------------------------- derived plumbing
def by_family(family):
    return tuple(m for m in REGISTRY.values() if m.family == family)


def by_stage(stage):
    return tuple(m for m in REGISTRY.values() if m.stage == stage)


def by_condition(condition_id):
    """The mechanic that emits a given condition row (or None)."""
    for mechanic in REGISTRY.values():
        if mechanic.condition_id == condition_id:
            return mechanic
    return None


def consumed_fields(family=None):
    """Every dotted field the registry consumes (optionally restricted to a family)."""
    out = []
    for mechanic in REGISTRY.values():
        if family and mechanic.family != family:
            continue
        out.extend(mechanic.consumes)
    return frozenset(out)


def required_fields(family=None):
    out = []
    for mechanic in REGISTRY.values():
        if family and mechanic.family != family:
            continue
        out.extend(mechanic.required)
    return frozenset(out)


def path_rule():
    """The target path's trigger (declared once, above)."""
    return TARGET_PATH_RULE


def armour_transformers():
    """The target-state mechanics that transform the armour value, in declaration order."""
    return tuple(m for m in REGISTRY.values() if m.stage == 'armour_transform'
                 and m.family == 'target_state')


def implemented_transformers():
    """The armour transformers that have an evaluator and a transform (refusal-only rows skip)."""
    return tuple(m for m in armour_transformers() if m.evaluate and m.apply)


def live(mechanic_id, ctx, facts=None):
    """Is this mechanic live? Its stated trigger, or a build fact it declares as required_when.

    This is the dispatch rule: the engine asks the registry which mechanics the caller's context
    makes live, instead of each call site deciding for itself.
    """
    mechanic = REGISTRY[mechanic_id]
    if mechanic.trigger is not None and mechanic.trigger.stated(ctx):
        return True
    if mechanic.required_when:
        return bool((facts or {}).get(mechanic.required_when))
    return False


def rider_stats():
    """The stats a conditional rider may move (the rider mechanic's declared stat list)."""
    for mechanic in REGISTRY.values():
        if mechanic.stage == 'rider_contribution':
            return tuple(mechanic.stats)
    return ()


def trace_for(mechanic_id, **fmt):
    """Trace destination for a mechanic (``stat_traces`` wins when the stat is named)."""
    mechanic = REGISTRY[mechanic_id]
    stat = fmt.get('stat')
    if stat and mechanic.stat_traces:
        key = mechanic.stat_traces.get(stat)
        if not key:
            raise MechanicDeclarationError(
                'mechanic %r has no trace destination declared for stat %r (its declarations: %s)'
                % (mechanic_id, stat, sorted(mechanic.stat_traces)))
        return key
    if not mechanic.trace:
        raise MechanicDeclarationError('mechanic %r declares no trace destination' % mechanic_id)
    return mechanic.trace.format(**fmt) if '{' in mechanic.trace else mechanic.trace


# A condition row the registry does not know about must not silently withhold *nothing*: the
# conservative fallback is the wider Phase 1 set, because an undeclared mechanic is exactly the
# situation this registry is meant to make impossible - it should be loud, not permissive.
UNDECLARED_WITHHOLDS = ('damage_per_shot', 'damage_per_shot_expected_crit', 'burst_dps',
                        'sustained_dps', 'damage_to_health', 'damage_to_health_expected_crit')


def withholds_for(condition_ids, declared_only=False):
    """The published result keys a set of refused *condition rows* may suppress.

    Phase 5's blast-radius fix is now a derivation: the target-path row withholds the target block
    and nothing else, because that is what its declaration says, while a Phase 4 row keeps the wide
    set its own declaration names.
    """
    out = []
    for condition_id in condition_ids:
        mechanic = by_condition(condition_id)
        keys = mechanic.withholds if mechanic else UNDECLARED_WITHHOLDS
        for key in keys:
            if key not in out:
                out.append(key)
    return tuple(out)


def deps_for(mechanic_id):
    return REGISTRY[mechanic_id].deps


def roster_contract(family='set'):
    """The roster rule every set mechanic reuses (distinct, legal, known members)."""
    for mechanic in REGISTRY.values():
        if mechanic.family == family and mechanic.roster:
            return mechanic.roster
    return None


def refusal_codes():
    out = set()
    for mechanic in REGISTRY.values():
        out.update(mechanic.refusal_codes)
    return frozenset(out)


def resolve(path):
    """Resolve a declared dotted path lazily (no import cycle can come from the registry).

    Paths are written relative to this package ('statuses.evaluate_corrosive'), so they are
    imported as `builds.statuses` - a bare import here would depend on the caller's sys.path.
    """
    module_name, _, attribute = str(path).partition('.')
    module = importlib.import_module('%s.%s' % (__package__, module_name))
    return getattr(module, attribute)


def verify_declarations():
    """Resolve every declared path now that every module is imported. Raises on a typo.

    `_declare_path` defers a path whose module was mid-import (the registry/engine import cycle);
    this is the second half of that check, and the gates, the selftest and the tests call it, so a
    declaration that names a function which does not exist cannot survive to a caller's request.
    """
    for mechanic_id, property_name, path in list(PENDING_VERIFICATION):
        target = resolve(path)
        if not callable(target):
            raise MechanicDeclarationError(
                'mechanic %r: %s=%r is not callable' % (mechanic_id, property_name, path))
    for mechanic in REGISTRY.values():
        for property_name in ('evaluate', 'apply', 'trace_row'):
            path = getattr(mechanic, property_name)
            if not path:
                continue
            target = resolve(path)
            if not callable(target):
                raise MechanicDeclarationError(
                    'mechanic %r: %s=%r is not callable' % (mechanic.id, property_name, path))
    return True


def introspect():
    return [m.as_row() for m in REGISTRY.values()]


def _load_declarations():
    """Import the declaration table once, after the registry API above exists."""
    from . import mechanics_table  # noqa: F401  (registers as a side effect)


def table():
    """A compact text table (debug.py and the gate report)."""
    lines = ['%-22s %-14s %-18s %-30s %s' % ('id', 'family', 'stage', 'trigger', 'consumes')]
    for row in introspect():
        lines.append('%-22s %-14s %-18s %-30s %s' % (
            row['id'], row['family'], row['stage'], row['trigger'] or '-',
            ', '.join(row['consumes']) or '-'))
    return '\n'.join(lines)


_load_declarations()
