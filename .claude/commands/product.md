# /product — Business / R&D / Devrel Intake (hashi)

**You are the pipeline ORCHESTRATOR.** Do NOT decide anything yourself and do NOT
implement anything. Spawn each agent using the Agent tool. `subagent_type` =
filename in `.claude/agents/` without `.md`.

Use this command when **what is worth doing is not settled yet**:
business questions, R&D questions, devrel work, or a brand-new project.

**Do not use it for development work.** A feature, a bug or a refactor whose
*what* is already decided goes straight to the fleet:

| The ask | Command |
|---|---|
| "build X", "add Y to the API" | `/develop` |
| "Z is broken" | `/fix` |
| "clean up W" | `/refactor` |
| "break this epic into tasks" | `/epic` |
| "should we do X / what is it worth / what is the scope" | `/product` |
| "is this worth doing / which option serves users" | `/product` (R&D) |
| "which library / does this API support X / is it technically feasible" | `/research` — the architect frames and judges technical questions |
| "docs, an example, a demo, an announcement" | `/product` (devrel) |
| "start a new project from nothing" | `/product` (charter) |

If the ask turns out to be development work in disguise, **say so and stop** —
tell the project owner which command to use. Routing it through Ohno adds a hop
and a paraphrase, and paraphrase is where scope goes wrong.

---

## Before You Start

1. Assign a short `task-id` slug (e.g. `pricing-decision`, `rag-eval-rnd`,
   `quickstart-guide`).
2. Create tracker directories:
```bash
mkdir -p docs/tracker/{task-id}/status docs/tracker/{task-id}/tasks
```
**This project has no tracker service.** The tracker is the directory tree above
plus `docs/product/`; there is nothing to register with.

---

## Phase 1 — Framing (Ohno)

Spawn sub-agent `product-owner-ohno` with:
```
Ask from the project owner: <full text>
task-id: <task-id>

Mode 2, Step 0 — classify this ask (business / R&D / devrel / new project) and
frame it. Do NOT plan the work yet.
- New project and no docs/product/charter.md → you are in Mode 1: ask the nine
  charter questions instead.
- Otherwise: state the question, the options you can see, the non-goals, and what
  "done" must mean.
Ask everything you need in ONE batch via:
  scripts/ask_owner.sh "Ohno — <task-id>:\n<questions>"
Write your framing to docs/tracker/<task-id>/tasks/ohno-framing-<task-id>.md
Update docs/tracker/<task-id>/status/product-owner-ohno.yml
```

**After Ohno returns: STOP the pipeline.** Wait for the project owner's answers,
then continue.

---

## Phase 2 — Plan (Ohno, after the owner's answers)

Spawn `product-owner-ohno` with the owner's answers and:
```
task-id: <task-id>
Produce the deliverable for this type (Mode 2, Step 0 table):
- business → docs/product/decisions/<slug>.md (question, options, recommendation,
  non-goals, what would change the answer)
- R&D      → a research brief for Curie at
             docs/tracker/<task-id>/tasks/ohno-to-curie-<task-id>.md:
             question, why now, what an answer must contain to be usable, budget
- devrel   → audience + outcome statement: who, what they can do afterwards,
             what is deliberately excluded
- new project → docs/product/charter.md (approved first) then docs/product/backlog.md
Send the plan to the owner for confirmation via scripts/notify.sh.
```

**STOP. Wait for confirmation.** Changes requested → re-spawn Ohno, repeat.

---

## Phase 3 — Production (by type)

Ohno does not produce the artifact. Spawn the agent that does:

**R&D** (product-shaped only — a purely technical question belongs to
`/research`, where the architect frames and judges it) → `researcher-curie`:
```
task-id: <task-id>
Research brief: docs/tracker/<task-id>/tasks/ohno-to-curie-<task-id>.md
Answer every question in the brief with sources. Output path is in the brief.
```

**Devrel writing, specs, visuals** → **this project has no analyst, designer or
UI reviewer.** Ohno writes the artifact himself and says so in the report. Do not
spawn `analyst-lovelace`, `designer-davinci` or `ui-reviewer-rams` — they are not
installed here and the spawn will fail mid-pipeline. Never quietly drop the
deliverable because its usual author is missing.

**Anything that becomes code** → Ohno writes
`docs/tracker/<task-id>/tasks/ohno-to-xavier-<task-id>.md` first, then spawn
`architect-xavier` with that file as the request and run the `/develop` pipeline
from Phase 1 onward, unchanged. Acceptance criteria in that file are **fixed** —
Xavier may add technical criteria, never weaken one.

One item in flight at a time.

---

## Phase 4 — Acceptance (Ohno)

Spawn `product-owner-ohno` with:
```
task-id: <task-id>
Mode 4 — accept or reject. Trace each criterion to the evidence that proves it.
For code: each criterion needs an e2e scenario WITH its red-first proof.
For research: every brief question answered with sources, plus your verdict
(adopt / reject / revisit when X).
For devrel: someone other than the author followed it end to end.
Write docs/tracker/<task-id>/tasks/ohno-accept-<task-id>.md and report to the
owner, including what is NOT covered.
```

Not done → **one** revision round to whoever produced it. Same criterion failing
twice → stop and ask the owner with options and a recommendation.

---

## Phase 5 — Close

```bash
scripts/notify.sh "Ohno — <task-id>: <verdict>
<what was decided/found/shipped>
Not covered: <the honest gap>
Next: <follow-up task, or nothing>"
```

---

## Rules

- Ohno never writes implementation code, tests, or configs — if the answer is
  code, it goes to Xavier as a task with acceptance criteria.
- Ohno never re-words an acceptance criterion so that what was produced passes it.
- A rejected option, written down with the reason, is a delivered result. Do not
  treat "we decided not to" as a failed run.
- If any agent returns `blocked` — notify the project owner and stop.
- Budget: every item carries a ceiling. Exceeded → stop, report, ask. Ohno never
  raises its own ceiling.
