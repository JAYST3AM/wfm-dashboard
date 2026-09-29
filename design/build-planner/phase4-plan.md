# Phase 4 plan (proposed)

**Status: proposed, not started.** Recommended by an external review (chatgpt.com, guest) on
2026-09-29, after reading the Phase 3 report. Whether Phase 4 happens, in what order, and with how
much scope is Jay's call.

**Phase 4 = a Conditional Combat Model.** Conditional effects become a first-class, four-state
concept before any new mechanic is implemented, and the first status mechanic only arrives after the
condition machinery has been proven on its own.

**The governing rule for the whole phase:** every new mechanic must be able to end in a refusal, and
refusal must stay distinguishable from zero, false, or unsupported input.

## The milestones (the order matters)

**4.1 — Formalize condition states.** Give the engine a first-class representation for conditional
effects *before* implementing any new game mechanic. Define the condition result space explicitly -
`satisfied`, `not_satisfied`, `unknown`, `unsupported` - and say what each means for a calculation:
`not_satisfied` ⇒ the contribution is deterministically absent; `satisfied` ⇒ it may be applied;
`unknown` ⇒ refuse the affected calculation (unless the caller explicitly asks for a hypothetical
evaluation); `unsupported` ⇒ refuse with the mechanic's named reason.
*Independent verification:* synthetic conditional effects covering all four states, asserting none
can silently become an ordinary unconditional modifier.

**4.2 — Make conditional mods report why they refuse.** The ~416 conditional mods stay refused, but
the refusal stops being a flat "conditional mod unsupported" and becomes structured: the mod is
known but its condition is unknown / the condition is known and false / the condition is known and
true but its effect is unimplemented / the whole mechanic is unsupported.
*Independent verification:* a representative sample of the corpus produces deterministic, named
refusals, and no existing unconditional calculation changes. This is the migration path that avoids
turning Phase 4 into "implement 416 things".

**4.3 — Add one minimal condition source.** One concrete condition whose truth can be determined
entirely from the supplied build/evaluation context - intrinsic to the build, not requiring
simulation - to establish the pipeline: input → condition evaluation → condition state → effect
evaluation → damage result or refusal. Tests for all four outcomes, including deliberately
incomplete input that must produce `unknown`.
*Independent verification:* Phase-1 calculations are structurally unchanged when no conditional
mechanic is involved - conditionality must not contaminate the unconditional model.

**4.4 — First status mechanic.** One status effect, one precisely defined piece of its behaviour —
not "status effects" as a category. Acceptance criteria: exact inputs and exact output documented;
known-applicable state calculates; known-non-applicable state calculates; missing information
produces `unknown` and refuses; an unsupported interaction produces `unsupported` and refuses; the
result has regression pins; the page displays whatever the engine returns without interpreting it.
Do not model the rest of the status system around it. If one mechanic exposes an awkward
abstraction, fix the abstraction while only one mechanic depends on it.

**4.5 — Conditional damage evaluation.** Generalize the evaluation boundary so the engine
distinguishes a deterministic result ("this build deals X under these stated inputs") from a
conditional result ("X applies when condition C is satisfied") from a refused result ("no damage
result: condition unknown / mechanic unsupported"). Introduce an explicit **evaluation context**
here - the future home for target properties, status state, attack context, known buffs/debuffs -
but do not populate it with speculative fields merely because they might be useful.
*Independent verification:* the imported-loadout damage pins run through the new path and keep their
existing answers; Phase 4 must not quietly redefine Phase 1.

**4.6 — Second mechanic + refusal audit.** A second mechanic chosen to be *different enough to expose
hard-coded assumptions*; its purpose is to test whether the abstraction generalizes, not to add user
value. Then a deliberate audit: which previously refused mechanics are still refused; did any
unknown become false; did any unsupported interaction become zero; are warnings/errors still
structured; can malformed conditional input still reach an exception; does the page still contain
zero Warframe calculations? If the second mechanic needs special-case plumbing everywhere, stop and
redesign the abstraction rather than adding a third.

## Explicitly NOT in Phase 4

1. **Not all 416 conditional mods** - they are the refusal corpus that tells us where the boundary
   is; implementing them all would make Phase 4 a content-entry project before the model is proven.
2. **No combat simulator** - no tick-by-tick enemy simulation, proc timelines, attack rotations or
   probabilistic models. Phase 4 answers "what does this build do under exactly these stated
   inputs", not "what happens during 37 seconds of a mission".
3. **No inverse solver** - "find a build that kills X" is later; first make
   `build + context → exact answer or refusal` reliable, then a solver can search that function.
4. **No external game-data or network dependency** - if a mechanic needs data we do not possess, it
   is refused; an information gap is never solved by quietly adding a live API.
5. **No recommendations** - no "farm this next", "install this mod", "upgrade this first"; those
   need a preference layer the engine does not have.
6. **The UI never gains semantic authority** - the page stays an engine-answer renderer. If Phase 4
   needs a new number, the engine owns it; the browser renders `condition: unknown / effect: refused
   / reason: target status state not supplied` and must not decide that unknown "probably means
   false".

## The gate to add before Phase 4 is called complete

A **refusal-preservation regression gate**: take a corpus of mechanics that are supposed to remain
unsupported and assert that they stayed unsupported. That is almost as important as the positive
tests, because the project's distinctive promise is not "it knows lots of Warframe mechanics" but
"when it doesn't know, it tells you exactly that". Phase 4 should increase the first property
without weakening the second.

## Starting point in this repo

- The refusal corpus already exists: 416 mods with a conditional effect, 1071 with an unmodelled
  stat, `isAugment` 400 / 217 real, Conclave buckets 39 + 50.
- The contract that must keep holding: a refusal is an answer (engine validation codes survive a
  refusal; `#plError` is reserved for a real failure to answer), and the engine owns every number
  the page prints.
- Baseline to protect: full suite 1999 passed / 5 skipped / 0 failed; browser gate 113 checks / 0
  failed; stage-10 regression gate 121 checks / 0 failed; 5 falsification mutations all tripping
  their named tests (as of `829e208`).
