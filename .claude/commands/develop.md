# /develop — Feature Development Pipeline (hashi)

> **Solo project.** There is only one persona here — `alfred`. Ignore every "spawn `<agent>`" instruction below **except the one phase that says "Run the review-loop skill"** (do not confuse this with a phase that merely has "Review" in its title, such as a Quality Review that spawns Xavier — that one is not the exception; collapse it into your own work like every other spawn instruction): do every other phase's work yourself, in this same context, one phase after another, and skip any step that exists only to hand work between separate agents (Handoff files, cross-agent status pushes). The review-loop phase still happens — the review-loop skill (`.claude/skills/review-loop/`) spawns `reviewer-strict`, a second, independent, edit-incapable agent, for every development task, and in solo YOU (the orchestrator) apply its findings yourself, same as the skill's default rule. This is not optional and self-review is never a substitute for it — see `alfred.md`.

**You are the pipeline ORCHESTRATOR.** Do NOT implement anything yourself.
Spawn each agent with the Agent tool; `subagent_type` = the filename in
`.claude/agents/` without `.md`.

All inter-agent communication happens through files:
- `docs/tracker/{task-id}/tasks/`
- `docs/tracker/{task-id}/status/`

**Zone-driven.** This project's zones and their owners are in
`.claude/workflow.md`. Spawn an agent only when its zone is actually involved —
a zone the feature does not touch gets no agent, no task file, no status file.

---

## Before you start

1. Assign a short `task-id` slug from the request (e.g. `cart-checkout`,
   `auth-refresh`).
2. Create the tracker directories:
```bash
mkdir -p docs/tracker/{task-id}/status docs/tracker/{task-id}/tasks
```
3. Write the goal at the task root:
```bash
cat > docs/tracker/{task-id}/README.md <<'EOF'
# {task-id}

**Type:** feature
**Goal:** {1–2 sentences: what this achieves and why}
EOF
```
4. Register the task, if this project has a tracker service:
```bash
 task:create "feature: {task-id}" "{description}" "feature" "Pipeline: /develop"
```
Remember the returned id for the status updates below.

5. **Record the review baseline** — every later review reads a diff, not a
   developer's account of its own work:
```bash
git rev-parse HEAD    # remember this ref as <baseline>
```
If the tree is dirty with unrelated changes, say so before going further.

---

## Phase 1 — Clarifying questions (Xavier)

Spawn `architect-xavier`:
```
Feature request: <full description from the project owner>
task-id: <task-id>

Analyse the project context and decide which zones are involved.
Form clarifying questions — once, in one batch.
If docs/product/backlog.md shows a PO dispatched this task, SCOPE questions go
to the PO, not the owner; answer technical questions yourself.
Otherwise send them via: scripts/ask_owner.sh "Xavier — <task-id>: <questions>"
Do NOT write specs yet. Return the questions so the orchestrator can record them.
```

**Then STOP.** Notify the owner and wait for the reply before Phase 1b.

---

## Phase 1b — Specs (Xavier, after the answers)

Spawn `architect-xavier`:
```
Feature request: <original>
task-id: <task-id>
Owner's answers: <reply>

Write one spec per involved lead or direct-report developer, and the security
review task for Sherlock Holmes. Name the zone in every spec.
Tracker directory: docs/tracker/<task-id>/
```

Xavier produces, for the involved zones only:
- `docs/tracker/{task-id}/tasks/xavier-to-<target>-{task-id}.md`
- `docs/tracker/{task-id}/tasks/xavier-to-holmes-{task-id}-review.md`
- `docs/tracker/{task-id}/status/architect-xavier.yml`

---

## Phase 2 — Security review of the design (Sherlock Holmes)

Spawn `security-holmes`:
```
task-id: <task-id>
Review every spec in docs/tracker/<task-id>/tasks/.
Write findings and update docs/tracker/<task-id>/status/security-holmes.yml.
```

Critical findings → re-spawn `architect-xavier` with them, then re-run Phase 2.

---

## Phase 3 — Decomposition (leads, in parallel)

For **each** spec file addressed to a lead, spawn that lead simultaneously:
```
task-id: <task-id>
Read and decompose: docs/tracker/<task-id>/tasks/xavier-to-<lead>-<task-id>.md
Create developer task files in docs/tracker/<task-id>/tasks/.
Developer scopes must not overlap in files.
```

**Skip this phase for zones with no lead** — those specs go straight to the
developer. Wait for all leads before Phase 4.

---

## Phase 4 — Implementation (developers, in parallel)

List the task files that now exist in `docs/tracker/{task-id}/tasks/` and
spawn **exactly** the developers addressed by them, simultaneously:
```
task-id: <task-id>
Implement your task: docs/tracker/<task-id>/tasks/<from>-to-<dev>-<task-id>.md
```

Wait until every spawned developer reports `status: review`. A developer at
`blocked` stops the pipeline — notify the owner.

---

## Phase 5 — Code review loop (max 3 rounds)

Run the **review-loop** skill (`.claude/skills/review-loop/`): task = the
original feature request, round cap = 3, starting point
= **Already done** with baseline = the ref from "Before you start". It owns
the loop itself — reading the diff,
`VERDICT:` parsing, ping-pong detection, the medium/low carry-over. What's
specific to `/develop` and not covered by the skill's generic "who reviews"
rule:

- Read the developer status files to see which zones actually changed. For
  each changed zone, the reviewer round includes **both** its reviewer
  persona **and** its lead (if it has one), in parallel, each getting a
  **fresh** agent instance every round.
- Reviewers **report**; the **developer who owns the zone fixes**. Never
  patch a developer's zone yourself (the skill's orchestrator) — that is how
  ownership, and the next agent's diff, get destroyed.
- Findings and the round's `VERDICT:` line go to
  `docs/tracker/<task-id>/tasks/<reviewer>-findings-<task-id>.md`, so a
  round ≥ 2 review can point at the exact file instead of re-deriving it.
- The pipeline already has a lead and a Phase 6 security review — a stalled
  code-review round is reviewers arguing, not defects being found; the
  skill's round cap and ping-pong stop exist for exactly that.

---

## Phase 6 — Security review of the code (Sherlock Holmes)

Spawn `security-holmes`:
```
task-id: <task-id>
Review the implemented code against the design and your Phase 2 findings.
Read: docs/tracker/<task-id>/tasks/holmes-to-xavier-<task-id>-findings.md
Check each developer's surface audit against the diff.
Update: docs/tracker/<task-id>/status/security-holmes.yml
```

---

## Phase 7 — Completion (Xavier)

Spawn `architect-xavier`:
```
task-id: <task-id>
Verify completion: every acceptance criterion has a corresponding change,
contracts are consistent, no zone was edited by two owners.
Read every task and status file.
```

---

## Phase 8 — Verification

Run the project-wide verification (it covers every zone):
```bash
make test-control && make test-edge && make test-infra
```
If only one zone changed, its own command is faster and enough — see the zone
table in `.claude/workflow.md`.
Red → find the cause, re-spawn the responsible developer, re-run. **No PR before
the build is green.**

---

## Phase 9 — Deliver

With git workflow instructions (remote mode): Xavier opens the PR following them —
push, PR against `develop`, self-review, then notify.

Without them (local mode): the changes are in the working tree; report what was
implemented and which files changed.

---

## Global rules

- Leads never write implementation code; reviewers never edit code.
- Any agent returning `blocked` stops the pipeline — notify the owner immediately.
- Never spawn an agent whose zone this feature does not touch.
- The git iron rules apply throughout: never `main`, never `git revert`,
  never auto-resolve a conflict.
