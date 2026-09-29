# Prompt for an outside reviewer (GPT / another model)

Paste this, with the listed files attached. It is deliberately adversarial: the value is in what it
finds wrong, not in a restatement of the report.

---

You are reviewing a completed implementation against its specification. Be adversarial. I do not
want a summary of what was built — I want what is wrong with it, what is unproven, and what you
would do differently. Assume the implementer is overconfident about their own work.

Attached:
1. `docs/trading-session-workflow.md` — the specification. This is the source of truth.
2. `design/_session/report.md` — the implementer's account of what shipped and why.
3. `design/_stage10/gate-report.md` — the browser acceptance run (live app, headless Chrome).
4. `design/_session/audit-backend.md`, `audit-frontend.md`, `audit-tests-qa.md` — the read-only
   audit of the codebase taken BEFORE the implementation.

You cannot execute anything. Judge these documents against each other, and against any source files
I paste afterwards (paste a file, I will send it).

Report, in this order:

1. **Spec requirements with no evidence of being met.** Cite the section of the spec and the line of
   the report that fails to answer it. Silence in the report is a finding.
2. **Claims the evidence contradicts or cannot support.** Anything the report asserts that the gate
   report or the audits do not back, and anything asserted without a number.
3. **Duplicated logic.** The spec insists on reusing existing producers rather than adding a second
   source of truth for prices, buyers, inventory or trade history. The backend audit lists what
   already existed. Name any place the implementation looks like a second implementation.
4. **The hard rules.** Flag anything that writes a data file non-atomically, infers a trade without
   explicit user confirmation, or automates a whisper/listing. These are stated in the spec as
   non-negotiable.
5. **The three weakest parts of this implementation**, each with the concrete change you would make.
6. **One-word verdict** — SHIP / FIX / REBUILD — and the single most important reason for it.

If something is missing that you need in order to judge, say exactly which file or number and stop
there rather than guessing. Do not praise anything.
