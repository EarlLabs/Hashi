# /develop — Feature Development Pipeline (hashi)

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
4. **This project has no tracker service.** The tracker is the directory tree
   above and nothing else — there is no queue to register with and no id to
   remember.

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

## Phase 3 — Decomposition

**This project has no leads.** Every zone has exactly one developer,
so Xavier's specs are already developer tasks: they go straight to the zone's
developer. Skip to Phase 4.

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

Reviewers **report**; the **developer who owns the zone fixes**. Never patch a
developer's zone yourself — that is how ownership, and the next agent's diff, get
destroyed.

### Round N
Announce it: "Review round N of max 3". Read the developer status files to see
which zones actually changed. Spawn `reviewer-granger` — one reviewer covers all
three zones here — as a **fresh** agent each round:
```
task-id: <task-id>
Round: N of 3
Review the <zone> changes.
Diff range: git diff <baseline>..HEAD   ← review THIS, not the status files
Run the zone's verify command yourself; a failure is automatically Must Fix.
Check acceptance criteria first, then scope, then the rulebooks.
[round ≥ 2] Previous findings: docs/tracker/<task-id>/tasks/<reviewer>-findings-<task-id>.md
            Verify EACH previous item explicitly before your own review, and
            report per item whether it is fixed, partial, or absent.
Write findings to docs/tracker/<task-id>/tasks/<reviewer>-findings-<task-id>.md
ending with exactly: VERDICT: CLEAN  or  VERDICT: <n> must-fix, <m> should-fix
```

### Decide from the verdict lines
- **Every reviewer `VERDICT: CLEAN`** → Phase 6.
- **Any must-fix** → re-spawn only the developers who own those findings, then
  start a **new round** with fresh reviewers.

### Stop conditions — both are mandatory
- **Round cap: 3.** At round 3 with must-fix findings remaining, stop. Keep every
  fix made so far, list what is unresolved, and tell the owner. The pipeline
  already has Xavier's completion check and a security review; a fourth
  code-review round is reviewers arguing, not defects being found.
- **Ping-pong detection.** Keep a ledger of findings as `file + one-line
  description` across rounds. If a round re-reports something an earlier round
  already fixed, or flags code that exists *because* of an earlier finding, that
  is reviewer disagreement, not progress: **stop immediately**, keep the current
  state, and put both positions to the owner. Loops like this converge on nothing
  and cost a full fleet spawn per round.

### Carry-over
Accumulate every **Should Fix** and **Nit** from every round into one
deduplicated list. Fresh reviewers will not re-find them, and they must not be
lost between rounds — report them at the end for the owner to decide.

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
make test
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

- Reviewers never edit code; Xavier never implements. Scope questions go to the
  owner (or to Ohno if `/product` dispatched this task), never to a developer.
- Any agent returning `blocked` stops the pipeline — notify the owner immediately.
- Never spawn an agent whose zone this feature does not touch.
- The git iron rules apply throughout: never `main`, never `git revert`,
  never auto-resolve a conflict.
