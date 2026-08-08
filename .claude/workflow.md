# Team Workflow — hashi

How the agent fleet coordinates work in this repository. Every persona in
`.claude/agents/` follows this document; where the two disagree, this document
wins and the persona is the bug.

> **Solo project.** There is only one persona here — `alfred`. Ignore every "spawn `<agent>`" instruction below **except the one phase that says "Run the review-loop skill"** (do not confuse this with a phase that merely has "Review" in its title, such as a Quality Review that spawns Xavier — that one is not the exception; collapse it into your own work like every other spawn instruction): do every other phase's work yourself, in this same context, one phase after another, and skip any step that exists only to hand work between separate agents (Handoff files, cross-agent status pushes). The review-loop phase still happens — the review-loop skill (`.claude/skills/review-loop/`) spawns `reviewer-strict`, a second, independent, edit-incapable agent, for every development task, and in solo YOU (the orchestrator) apply its findings yourself, same as the skill's default rule. This is not optional and self-review is never a substitute for it — see `alfred.md`.

---
## Zones
A **zone** is the unit of ownership: a set of paths, a rulebook, a verification
command, and exactly one owner at a time. Work that crosses zones is **split**,
never shared.

| `control` | Control plane (FastAPI) | `control/**`, `tests/control/**`, `tests/e2e/control/**` | `01-control-rulebook.md` | `make test-control` | Ohno |
| `edge` | Edge (pure config-rendering library) | `edge/**`, `tests/edge/**`, `tests/e2e/edge/**` | `02-edge-rulebook.md` | `make test-edge` | Ohno |
| `infra` | Deploy / CI / infra | `deploy/**`, `.github/**`, `Makefile`, `scripts/**`, `.e2e/**`, `.env.example`, `tests/infra/**`, `tests/e2e/infra/**` | `04-infra-rulebook.md` | `make test-infra` | Ohno |

---
## Branch & merge model
### Iron rules (no exceptions)
1. Agents **never** push, merge or open PRs targeting `main`.
2. Agents **never** run `git revert`, in any branch.
3. All PRs target `develop`.
4. Before starting a task, sync the integration branch:
   ```bash
   git checkout develop && git pull origin develop && git merge origin/main --no-edit
   ```
5. Before merging, the agent self-reviews its own PR diff and fixes what it finds.
6. After merging, report to the project owner via `scripts/notify.sh`.
7. **Merge conflicts are never auto-resolved and never reverted.** Report and stop.
8. **Auto-merge is opt-in per task.** By default an agent opens a PR and waits. It
   may merge only when the owner says so for *that* task. There is no global
   auto-merge switch.

---
## Task ID and tracker directory
Each request gets a short `task-id`. Everything about it lives under
`docs/tracker/{task-id}/`:

- `tasks/*.md` — specs, findings, handoffs between agents
- `status/*.yml` — structured progress, one file per agent

Rules: every agent uses the same tracker root for the task, and **tracker
artifacts are never deleted** — not after completion, not after a cancellation.

---
## Agent registry
| `alfred` | Ohno | Overseer | — | `opus` |
| `reviewer-strict` | Strict Reviewer | Independent Reviewer | — | `sonnet` |

---
## Workflow phases
### Phase 0: Product intake (—) — `/product` only
<!-- Renderer: delete this phase entirely if no Product Owner is installed. -->
**Skipped by every development command.** `/develop`, `/fix`, `/refactor` and
`/epic` start at Phase 1. Phase 0 exists for asks where *what is worth doing* is
still open: business questions, R&D, devrel, and a new project's charter.

Anything that turns into code leaves Phase 0 as a task, never as an
implementation: the PO writes `—-to-xavier-{task-id}.md` with fixed
acceptance criteria, and Phase 1 runs unchanged.

This project has no Product Owner — the owner drives every task.

### Phase 1: Architecture & requirements (Xavier)
1. The project owner submits a request.
2. Xavier assigns a `task-id` and creates `docs/tracker/{task-id}/{status,tasks}/`.
3. Xavier reads the context (`README.md`, `CLAUDE.md`, `control/AGENTS.md`, `edge/AGENTS.md`, `deploy/AGENTS.md`) and the rulebooks for the affected
   zones, and decides which zones are involved.
4. Xavier asks clarifying questions — once, in one batch — and waits.
5. Xavier writes one spec per involved lead or direct-report developer, each
   naming the zone, the scope, the out-of-scope list, the contracts at the
   boundary, and the acceptance criteria.
6. Xavier opens a security review of the design for Sherlock Holmes.

### Phase 2: Security review of the design (Sherlock Holmes)
Findings written to `docs/tracker/{task-id}/tasks/holmes-to-xavier-{task-id}-findings.md`.
Critical findings go back to Phase 1 before decomposition starts.

### Phase 3: Decomposition (leads)
<!-- Renderer: if this project has no leads, replace this phase with one line: specs go straight to the zone's developer. -->
Each lead decomposes its spec into **non-overlapping** developer tasks. Two
developers assigned the same file is the most expensive mistake available at this
step. Leads write tasks and acceptance criteria; leads do not write code.

Zones with a single developer skip this phase — the spec goes straight to them.

### Phase 4: Implementation (developers)
1. Developers implement only inside their zone.
2. Every rulebook named in their pre-read applies.
3. **Acceptance criteria are e2e scenarios**: one scenario per criterion, written
   before or alongside the code. Unit tests only where a specific piece of pure
   logic is worth pinning. A test that cannot fail is worse than no test.
4. Every new externally reachable surface goes in the developer's **surface
   audit** (what it is, who may reach it, how that is enforced, behaviour on
   invalid input).
5. Verification (the zone's own verify command — see the zone table above)
   passes **before** review.
6. Developers keep their own status file current.

### Phase 5: Code review loop (reviewers + leads, max 3 rounds)
Run the **review-loop** skill (`.claude/skills/review-loop/`) with the
original request as its task, a round cap of 3, and
starting point **Already done** — the baseline is the ref recorded at the
start of `/develop`, since the implementation phases above already did the
work the skill would otherwise do in its own Phase 0-1. It owns the loop
mechanics from there — reading the diff, round caps, the `VERDICT:` line,
ping-pong detection, carrying medium/low findings across rounds — so this
phase only states what's specific to `/develop`, not the loop itself:

- Reviewers are scoped by zone and run in parallel when several zones changed.
- Leads verify scope compliance, ownership overlap and integration
  consistency, on top of what the skill's reviewer already checks.
- Order of checks: acceptance criteria first, then scope, then rulebooks,
  then a verification run (the zone's own — a failure is `high` regardless
  of what a status file claims), then correctness.
- **Reviewers report; the developer who owns the zone fixes** — the skill's
  "orchestrator only fixes" rule, applied per zone.

### Phase 6: Security review of the code (Sherlock Holmes)
Traceability from the Phase 2 findings to the code that addresses them, then the
implementation itself: authz boundaries, input validation, secret handling,
logging, error leakage, and the surface audit against the diff.

### Phase 7: Completion (Xavier)
Xavier verifies that the sum of the changes matches the original request: every
criterion has a corresponding change, contracts are consistent, no zone was
edited by two owners, verification passes. This is the **technical** check.

### Reporting cadence and merge authority
How often the owner hears from the fleet, and whether it may merge its own PRs,
is one setting: the **autonomy level** in `.claude/git-workflow.md`
(L0 review each PR · L1 batch · L2 autonomous merge into
`develop`). `main` is never agent-merged at any level.

Batching lowers the noise, never the escalation: a blocked agent, a red gate, an
exhausted budget or a question for the owner goes out immediately at every level,
and stops the queue.

### Phase 8: Acceptance (—) — only for work the PO dispatched
<!-- Renderer: delete this phase entirely if no Product Owner is installed. -->
Independent product-level accept/reject: each acceptance criterion traced to the
e2e scenario that proves it and the run result, **including the red-first proof**
(break the behaviour, watch the right assertion fail, restore). A criterion with
no scenario is not done. What the scenarios do not cover goes in the report.

A task that arrived through `/develop` without a PO is accepted by whoever sent
it; the PO does not review it uninvited.

---
## File conventions
### Product files (Phase 0 only)
- `docs/product/charter.md` — what the project is and is not; changed only
  with the owner's approval.
- `docs/product/backlog.md` — milestones → tasks, each with acceptance
  criteria as e2e scenarios, out-of-scope, `depends_on`, budget, status.
- `docs/product/decisions/{slug}.md` — business decision memos.
Durable: they outlive any `task-id` and are never deleted. A cancelled task stays
with its reason — that is the record of a decision.

### Task files
`docs/tracker/{task-id}/tasks/{from}-to-{to}-{task-id}.md`, with `-fix-`,
`-refactor-`, `-review`, `-findings` variants. They describe **what** and the
acceptance criteria — never implementation code.

### Status files
`docs/tracker/{task-id}/status/{agent-slug}.yml`:
```yaml
agent: dev-anderson      # the FULL persona slug — same as the filename
role: dev
zone: control
task: "Feature or sub-feature name"
state: in_progress
progress: "What is done so far"
blockers: null
updated_at: 2026-01-01T12:00:00Z
```
State values: `idle` / `pending` / `in_progress` / `blocked` / `review` / `done`.

**These field names are a contract, not a style.** A project connected to the
tracker relays these files upstream, and the panel joins them on the slug: write
`status:` instead of `state:`, or the short handle instead of the full slug, and
the agent shows as **idle forever** while it works. Update the file at every
transition — an agent that writes its status once, at the end, looks stalled for
as long as it is busy.

Developers moving to `review` must also carry `pre_read`, `verified` and
`surfaces` (see the dev persona).

---
## Fix flow (`/fix`)
1. Xavier assigns the bug to **one** zone.
2. The lead (or the direct-report developer) takes one fix task.
3. The developer fixes, verifies, and moves to review. Same gates as Phase 5–7,
   scoped to the change.

---
## Where the rules live
- **This file** — the procedure: who does what, in what order.
- **`.claude/projects/*.md`** — the project's law: invariants, per-zone rulebooks,
  the security checklist. Personas point at them; they never restate them.
- **Personas** — the role contract for one agent.

When a rule is stack-specific, it belongs in a rulebook, not in a persona. That
is what keeps the fleet reusable across projects.
