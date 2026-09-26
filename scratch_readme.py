"""README: same Live / Not live wording (the config KEY stays `dry_run`)."""
import sys

P = 'README.md'
s = open(P, encoding='utf-8').read()
PAIRS = [
    ("plus a **dry-run-first trader toolkit** that plans listings, watches undercuts and keeps its own",
     "plus a **plan-first trader toolkit** that plans listings, watches undercuts and keeps its own"),
    ("## Safety: dry run is the default and the only shipped mode",
     "## Safety: posting is Not live by default, and that is the only shipped mode"),
    ("- **`dry_run` is locked on.** It is the master safety gate, and the settings writer refuses to set it\n"
     "  false: `python scripts/trader/settings.py --set dry_run=false` exits `3` and leaves the file\n"
     "  byte-identical. Every trader engine therefore plans and checks — none of them posts, relists or\n"
     "  reprices.",
     "- **Posting is Not live, and `dry_run` is locked on.** `dry_run` is the master gate; the settings\n"
     "  writer refuses to turn it off (i.e. go Live): `python scripts/trader/settings.py --set\n"
     "  dry_run=false` exits `3` and leaves the file byte-identical. Every trader engine therefore plans\n"
     "  and checks — none of them posts, relists or reprices."),
    ("queue) runs dry run only. `auto.py`, the supervised orchestrator, is v0: one cycle at a time, dry\nrun.",
     "queue) is Not live. `auto.py`, the supervised orchestrator, is v0: one cycle at a time, Not live."),
    ("**Trader — `scripts/trader/`** (the local trader stack; it is not published with this repository, and\nit is dry run)",
     "**Trader — `scripts/trader/`** (the local trader stack; it is not published with this repository, and\nit is Not live)"),
    ("- `auto.py` — supervised single cycle over the engines (v0, dry run).",
     "- `auto.py` — supervised single cycle over the engines (v0, Not live)."),
    ("- `scripts/trader/settings.json` — the trader guardrails: `dry_run` (locked on),",
     "- `scripts/trader/settings.json` — the trader guardrails: `dry_run` (the Live/Not-live gate, locked to Not live),"),
    ("- Nothing is posted on your behalf: the trader engines are dry run.",
     "- Nothing is posted on your behalf: the trader engines are Not live."),
    ("- harden `auto.py` (v0) so a supervised dry-run cycle can run on a timer, and fold the digest/push",
     "- harden `auto.py` (v0) so a supervised Not-live cycle can run on a timer, and fold the digest/push"),
    ("- connect an account — your own orders.", "- connect an account — your own orders."),
]
bad = []
for old, new in PAIRS:
    if s.count(old) != 1:
        bad.append('%d matches: %r' % (s.count(old), old[:60]))
        continue
    s = s.replace(old, new, 1)
if bad:
    print('FAILED:'); [print(' ', b) for b in bad]; sys.exit(1)
open(P, 'w', encoding='utf-8', newline='').write(s)
print('README updated: Not live / Live wording, dry_run kept as the config key')
