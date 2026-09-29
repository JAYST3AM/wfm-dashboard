# Phase 3 report — the current loadout, imported read-only

**Status: complete.** Local-only, read-only import of the player's in-game loadout into the Build
Planner, with per-field provenance, a clone path that goes through the page's own validator, and no
invented values anywhere.

## What was built

| Piece | File | What it does |
| --- | --- | --- |
| Save reader | `scripts/player_loadout.py` | Decrypts via `scripts/saveio.py`, maps, caches; returns a *named state* (`ok`, `missing`, `locked`, `malformed`, `no_build_data`) instead of raising |
| Mapping engine | `builds/player_import.py` | Pure: save + catalogue → snapshot; provenance per field (`observed` / `derived` / `unknown`); clone builder |
| Routes | `server.py` | `GET /api/planner/current`, `POST /api/planner/current/refresh`, `POST /api/planner/clone` |
| UI | `static/planner-current.js` + `planner.html` + `planner.css` | The Current Loadout card: rows per category, a detail pane with the engine's own verdict, refresh, and clone |
| Page plumbing | `static/planner.js` | `api.current`, `api.cloneCurrent`, `adopt()` (a v1 document enters through the page's own `cleanV1`) |
| Audit | `docs/player-build-import.md` | Every field, field by field: what the save says, what WFM can prove, what stays unknown |
| Tests | `tests/test_player_import.py` (20) + fixtures | Synthetic save fixtures whose ids are checked against the ingested catalogue |
| Gate | `design/_planner/build_planner_gate.js` §20 + wrapper state probes | 12 browser checks + 4 source-state checks |

## Provenance: what is claimed, and why

* **observed** — the save states it: equipment identity and kind, the active config index per
  category, installed mods by copy id (mod path + rank from `UpgradeFingerprint`), slot order, the
  active config's slot polarities (their positions corroborate the installed mods), the source
  timestamps, and the raw `Features` bitmask. "Observed" is about the source, not about the game's
  live state: a save can be stale or mid-write.
* **derived** — `equipment_rank` at 30 when the recorded XP is at or above the rank-30 requirement,
  or 0 when the save records an explicit zero (an ABSENT XP field is `unknown`: "I cannot derive
  anything but 0" is not "the rank is 0"); the Forma count from the save's own `Polarized`; "the
  single preset per type is the current build" (the save carries exactly one per type and
  `CurrentLoadOutIds` holds only placeholder ids, so it cannot corroborate - the note says both).
* **unknown** — Catalyst/Reactor, Exilus unlock, Archwing/Mech ids (not in the Phase-1 catalogue),
  `Features` bit semantics, and anything the catalogue cannot resolve.
* **The engine cannot take these slots** — arcane slots (10-11) and anything else outside the
  engine's slot vocabulary is imported into a named `unsupported` list, shown in the card, never
  silently dropped.

## Evidence

* **Unit/contract suite:** `pytest tests/test_player_import.py -q` → **20 passed**.
* **Browser gate:** `python design/_planner/build_planner_gate.py` → **113 checks, 0 failed, PASS**
  (12 new `current` checks: the six rows, the freshness label, read-only affordances, no fixed
  layer, the imported mods with their save ranks, the engine verdict, drain parity between the card
  and the API, the Phase-1 damage pin on the imported build, the clone landing in the planner, the
  snapshot being byte-identical across a clone, the card surviving a planner edit + reload, and a
  broken source rendering as a named calm state); plus 4 source-state checks measured on the booted
  server (`ok` / `malformed` / `no_build_data` / `missing`).
* **Falsifiability** (`p3_falsify.py`, source-level mutations, original bytes restored and
  hash-checked, `unfalsified mutations: 0`):

  | Mutation | Result |
  | --- | --- |
  | a clone that invents a Catalyst | TRIPPED |
  | a clone that forgets what it does not know | TRIPPED |
  | an import that drops unreadable ids | TRIPPED |
  | a rank claimed from nothing | TRIPPED |
  | a slot order that no longer matches the save | TRIPPED |

## Bugs found and fixed while wiring it

* `resolve_mod` returned the catalogue *row* but not the key the catalogue is indexed by, so every
  cloned slot was skipped as unresolved — found by running the clone against the real save.
* Slot keys: the page's storage vocabulary is `normal:<i>` and bare `aura` / `exilus` / `stance`;
  the engine's compute contract is different again (`index` present only for normal slots). Both
  are now encoded where they belong and pinned by tests (`invalid_slot_index` and `unknown_mod`
  errors were the tells).
* A polarity the page cannot store (`AP_UNIVERSAL` → `universal`) would have failed the whole clone
  document; such polarities are now counted and reported instead.
* `AP_UMBRA` maps to the page's spelling `umbral`, not the engine catalogue's `umbra`.
* A `ReferenceError` in the card's `ready` handler (a leftover module-level variable after a
  refactor) — caught because the planner's listener wrapper logs instead of swallowing.
* The card's clone note was overwritten by the following render; the note is now written last.

## A GPT review round (2026-09-29)

An external review (chatgpt.com, guest) read this report and the phase summary. Verdict: sound, with
three wording corrections, all applied here - `verified` renamed to `observed`; the rank rule
narrowed so an absent XP field is `unknown` rather than a derived 0; and the privacy claim stated as
what it is (no telemetry, no external call, loopback bound) instead of "nothing leaves the machine".
It also asked that the clone work be described as what the evidence shows - a validated exact
snapshot clone (whole-document validator, byte-identical snapshot) - rather than a transactional
guarantee. Its Phase 4 recommendation: a **Conditional Combat Model** (conditional effects as a
framework with condition satisfied / not satisfied / unknown / unsupported states, plus a first small
set of status mechanics), ahead of sharing, market prices or "what to farm next".

## Known limits (deliberate)

* The save records **no Catalyst/Reactor and no Exilus unlock**, so a cloned build can read
  "capacity exceeded" where the in-game build fits. The card states the assumption and asks the
  engine the Catalyst question too; it does not guess.
* **Companions** import identity and mods, but the engine has no precept slot, so companion mods
  land in the named unsupported list rather than being forced into normal slots.
* **Archwing/Mech** equipment is not in the Phase-1 catalogue: the card says "Unknown item" and
  logs the raw path.
* **No polling and no sharing.** The read happens on request; nothing leaves `127.0.0.1`.
