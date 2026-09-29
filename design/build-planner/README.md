# Build planner — design notes

The engine itself lives in [`builds/`](../../builds) and is documented for users and
future-me in [`docs/build-planner.md`](../../docs/build-planner.md). This folder holds the
*evidence* behind it: the wiki research the formulas came from, written before any code so
that a disputed number can be argued about with citations instead of memory.

| File | Covers |
|---|---|
| `references/capacity-polarity.md` | Mod capacity, rank/supercharger interaction, the Mastery floor, drain & polarity rounding, Aura/Stance bonuses, Forma, Exilus, duplicate-mod rules |
| `references/weapon-stat-math.md` | Damage order of operations, elemental combination and slot order, innate elements, crit tiers, status, multishot, reload, fire rate, faction damage, DPS |
| `references/frame-stat-math.md` | Ability Strength/Duration/Range/Efficiency stacking, caps and floors, Health/Shield/Armour/Energy rank scaling |
| `references/wfcd-data-shapes.md` | What WFCD's JSON actually contains per category — field names, units, and the traps (rank-0 base stats, starter-mod duplicates, the stale AlecaFrame mirror) |

Each file quotes the wiki text, names the page, and stamps the retrieval date, and marks
anything genuinely unstated as `UNSTATED — do not guess` rather than filling it in. Where
the engine had to choose (for example the Mastery-capacity floor vs. a supercharger), the
choice is recorded there and in the module docstring, and the result carries a flag.

The phase roadmap (what the engine deliberately refuses today and when each mechanic is
due) is in `docs/build-planner.md`; the machine-readable twin of that list is
`builds/unsupported.py` (`python builds/debug.py unsupported`).
