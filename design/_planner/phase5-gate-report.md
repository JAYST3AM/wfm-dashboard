# Phase 5 target-model gate

```
python design/_planner/phase5_gate.py --falsify
database: F:\VSC Projects\wfm-dashboard\data\build_data.json
```

| check | result |
| --- | --- |
| `enemy/faction-required` no stated faction: the damage-type modifiers stay unknown | PASS |
| `enemy/layer-required` no stated landing layer: the engine will not pick one | PASS |
| `enemy/armour-required` a health landing with no stated armour is withheld, not 0 | PASS |
| `enemy/armour-invalid` a junk armour value is unknown, never read as no armour | PASS |
| `enemy/layer-invalid` an unknown landing layer is refused by name, not defaulted | PASS |
| `enemy/faction-invalid` an unknown faction is refused, never a default faction | PASS |
| `enemy/armour-pinned` the armour rule matches its pinned values at every plateau | PASS |
| `enemy/corrosive-pinned` stated corrosive procs reduce the armour the mitigation uses, by the pinned values | PASS |
| `enemy/corrosive-invalid` junk or over-cap stack counts refuse, never approximate | PASS |
| `enemy/no-context-no-target-damage` with no target context the answer holds no target block and Phase 1 is itself | PASS |
| `enemy/target-does-not-move-phase-1` the target path adds its block and leaves every Phase 1 number where it was | PASS |
| `enemy/unsupported-contributes-nothing` an unmodelled conditional rider leaves every number exactly as it was | PASS |
| `buff/stated-stacks` a stated on-kill stack count is applied end to end (context -> state -> effect) | PASS |
| `buff/applied-in-the-stat` the applied rider actually moves the stat it names, and only that one | PASS |
| `buff/no-state-no-number` no stated buff state: unknown, no contribution, and the stat is the base one | PASS |
| `buff/averaged-states-its-assumption` an averaged state carries its stated assumption into the answer | PASS |
| `buff/junk-state-never-a-number` a malformed or contradictory buff state never produces a contribution | PASS |
| `states/four-states-only` every condition row speaks the four-state vocabulary, and none is a boolean | PASS |
| `validate/booleans-are-booleans` a declared boolean rejects truthy strings and accepts real booleans | PASS |
| `validate/boolean-code-registered` the invalid_boolean code is in the validation vocabulary | PASS |
| `enemy/alias-armour-is-armour` the British spelling of armour is read as the armour it is | PASS |
| `enemy/unsupported-target-fields-named` a stated target field with no consumer is refused by name, not dropped | PASS |
| `enemy/removed-vocabulary-named` the health_type / armor_type vocabulary Damage 3.0 removed is refused by name | PASS |
| `enemy/non-object-target-ignored-named` a target that is not an object is named as ignored, never half-read | PASS |
| `enemy/conflicting-alias-named` a conflicting second spelling is named, and the canonical field is the one used | PASS |
| `enemy/target-refusal-keeps-the-build` an unresolved target state withholds the target block, never the Phase 1 numbers | PASS |
| `enemy/malformed-never-crashes` a malformed target or buff shape is answered with a state, never raised | PASS |
| `trace/target-stages` the target trace carries every stage from base damage to the mitigation | PASS |
| `trace/rows-compose` the per-type trace rows multiply to the applied factor (display precision) | PASS |
| `trace/provenance-on-every-row` the target and corrosive rows carry their wiki source with a revision id | PASS |
| `set/umbral-counts-distinct-members` duplicates, refused members and unknown members are named, never silently counted | PASS |
| `refusals/umbral-codes-exercised` the reachable set-bonus codes are exercised, so their registry rows are not dead | PASS |
| `refusals/phase-4-gate` the Phase 4 refusal-preservation gate still passes | PASS |
| `refusals/registry-covers-phase-5` every refusal the new paths emit has a registry entry (markers and condition codes) | PASS |
| `refusals/phase-5-condition-codes-exercised` the Phase 5 condition codes are reachable, so the registry rows above are not dead | PASS |
| `page/no-enemy-maths` no enemy/buff formula constant appears in the page | PASS |
| `page/no-mitigation-copy` the page carries no armour/DR computation of its own | PASS |

**37 checks, 0 failed.**

## Falsification: does the gate catch breakage?

| deliberate break | what it would let through | caught | failed checks |
| --- | --- | --- | --- |
| unparseable-armour-becomes-zero | an armour value the model cannot read is read as 0 armour | yes | `enemy/armour-invalid` |
| missing-armour-becomes-zero | a missing armour value quietly becomes 0 armour | yes | `enemy/armour-required`, `enemy/armour-invalid`, `enemy/target-refusal-keeps-the-build` |
| missing-layer-defaults | a missing landing layer is defaulted to health | yes | `enemy/layer-required` |
| unknown-faction-defaults | an unknown faction is defaulted to grineer | yes | `enemy/faction-invalid` |
| unknown-becomes-false | an unknown condition is reported as not_satisfied | yes | `enemy/faction-required`, `enemy/layer-required`, `enemy/armour-required`, `enemy/armour-invalid`, `enemy/faction-invalid`, `enemy/corrosive-invalid` |
| unsupported-contributes | a conditional mechanic with no model is folded into the totals | yes | `enemy/unsupported-contributes-nothing` |
| unstated-rider-applies | a rider with no stated state is treated as one stack | yes | `buff/no-state-no-number`, `refusals/phase-4-gate` |
| stacks-invented | an uptime without a stack count invents the maximum stack count | yes | `buff/junk-state-never-a-number` |
| uptime-assumed | with no buff state the engine assumes 50% uptime at max stacks | yes | `buff/no-state-no-number`, `refusals/phase-4-gate` |
| malformed-target-raises | a malformed target value crashes instead of answering unknown | yes | `check_enemy_inputs_are_required`, `enemy/malformed-never-crashes`, `check_refusal_registry_covers_new_paths` |
| truthy-string-as-boolean | truthy strings are accepted as booleans | yes | `validate/booleans-are-booleans` |
| corrosive-cap-approximated | an over-cap corrosive stack count produces a reduction | yes | `enemy/corrosive-invalid`, `refusals/phase-5-condition-codes-exercised` |
| target-moves-phase-1 | the target path contaminates the Phase 1 numbers | yes | `enemy/target-does-not-move-phase-1` |
| phase-1-drifts-without-context | the Phase 1 numbers drift with no target context at all | yes | `enemy/no-context-no-target-damage` |
| armour-rule-constant | the armour reduction stops depending on the stated armour | yes | `enemy/armour-pinned`, `enemy/corrosive-pinned` |
| enemy-maths-in-page | an enemy formula constant appears in the page | yes | `page/no-enemy-maths` |

16 of 16 breaks caught.
