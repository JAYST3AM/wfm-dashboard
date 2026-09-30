# Refusal-preservation gate - Phase 4

```
python design/_planner/conditions_gate.py --falsify
database: F:\VSC Projects\wfm-dashboard\data\build_data.json
```

| check | result |
| --- | --- |
| `states/exactly-four` the state space is exactly satisfied / not_satisfied / unknown / unsupported | PASS |
| `states/vocabulary` every condition state in a payload is one of the four | PASS |
| `refusal/corpus-count` the conditional corpus is non-empty | PASS |
| `refusal/structured` every conditional mod refuses with a state and a reason code | PASS |
| `refusal/never-applied` no conditional clause is ever applied | PASS |
| `refusal/checked-count` every conditional mod that this database can equip was actually checked | PASS |
| `rider/never-in-totals` a conditional line never adds to the totals, measured stat by stat | PASS |
| `unknown/withheld` a faction bonus with no target stated is withheld, not zero | PASS |
| `unknown/numbers-intact` and every Phase 1 number is exactly what it was without the mod | PASS |
| `unknown/context-resolves` and stating the target resolves it (the pipeline works) | PASS |
| `unsupported/viral-cap` stacks above the cap are unsupported, and no multiplier is produced | PASS |
| `unsupported/viral-landing` an unknown landing is unsupported, not assumed | PASS |
| `unsupported/unmodelled-named` an unmodelled stat is named, never a silent zero | PASS |
| `numbers/viral-formula` the viral multiplier is the documented formula | PASS |
| `numbers/viral-refuses` and it produces no value outside its domain | PASS |
| `numbers/viral-states` the viral mechanic reaches all four states | PASS |
| `malformed/never-crashes` malformed builds, options and contexts never crash | PASS |
| `states/validation-codes-complete` every code the validation and capacity engines emit is listed in validation.CODES | PASS |
| `registry/coverage` every emitted refusal code has a registry entry | PASS |
| `strict/refused` a strict evaluation with an unresolved condition refuses | PASS |
| `context/stated-inputs-named` an input this engine has no model for is refused by name, not dropped | PASS |
| `context/used-inputs-not-flagged` an input the engine did use is not reported as unused | PASS |
| `strict/no-number-survives` a refused stat is withheld everywhere it is reported, traces included | PASS |
| `hypothetical/never-invents` an unresolvable input produces no number, hypothetical mode included | PASS |
| `evaluation/engine-declared` a frame build reports not_evaluated; a weapon build reports its engine evaluated | PASS |
| `states/reachable` each state is reached by the producer that owns it, and all four are reached | PASS |
| `page/no-maths` no Phase 4 formula constant appears in the page | PASS |

**27 checks, 0 failed.**

## Falsification: does the gate catch breakage?

| deliberate break | what it would let through | caught | failed checks |
| --- | --- | --- | --- |
| unknown-reporting-applied | a withheld condition starts contributing | yes | `refusal/never-applied`, `unknown/withheld`, `unknown/numbers-intact` |
| fifth-state-false | a boolean can stand in for a condition state | yes | `states/exactly-four`, `numbers/viral-states`, `states/reachable` |
| classifier-assumes-satisfied | conditional text is treated as satisfied | yes | `refusal/never-applied`, `states/reachable` |
| stated-input-dropped | a stated input with no model is silently ignored | yes | `context/stated-inputs-named` |
| rider-lands-in-totals | a conditional rider's value is folded into the totals | yes | `rider/never-in-totals` |
| viral-cap-approximated | an unsupported stack count produces a multiplier | yes | `numbers/viral-formula`, `numbers/viral-refuses` |
| refused-number-survives | a refused stat keeps its number in the mirrored structures | yes | `strict/no-number-survives` |
| hypothetical-invents | a hypothetical evaluation invents an amplifier it was never given | yes | `hypothetical/never-invents` |
| evaluation-claimed | an engine that never evaluated claims it did | yes | `evaluation/engine-declared` |
| malformed-context-raises | a junk context crashes instead of answering unknown | yes | `malformed/never-crashes` |
| page-carries-formula | a formula constant appears in the page | yes | `page/no-maths` |

11 of 11 breaks caught.
