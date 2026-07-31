# Team Workflow — hashi

How the agent fleet coordinates work in this repository. Every persona in
`.claude/agents/` follows this document; where the two disagree, this document
wins and the persona is the bug.

---
## Zones
A **zone** is the unit of ownership: a set of paths, a rulebook, a verification
command, and exactly one owner at a time. Work that crosses zones is **split**,
never shared.

| Zone | Label | Paths | Rulebook | Verify | Owner |
|---|---|---|---|---|---|
| `control` | Control plane: API, admin panel, subscription delivery, persistence | `control/**`, `tests/control/**` | `.claude/projects/01-control-rulebook.md` | `make test-control` | Thomas Anderson (`dev-anderson`) |
| `edge` | Data plane: transport profiles, node bootstrap, config rendering, health | `edge/**`, `tests/edge/**` | `.claude/projects/02-edge-rulebook.md` | `make test-edge` | John von Neumann (`dev-neumann`) |
| `infra` | Deployment and operations: compose stacks, Caddy, CI, backups, secrets | `deploy/**`, `.github/**`, `Makefile`, `tests/infra/**` | `.claude/projects/04-infra-rulebook.md` | `make test-infra` | Pepper Potts (`dev-potts`) |

`docs/**` and `.claude/**` belong to no zone — they are owner and architect
territory, written by whoever the workflow assigns.

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
| Agent | File | Role | Zone | Model |
|---|---|---|---|---|
| Taiichi Ohno | `product-owner-ohno.md` | Product Owner — charter, backlog, accept | — | opus |
| Charles Xavier | `architect-xavier.md` | Solution Architect — also every developer's lead | all | opus |
| Sherlock Holmes | `security-holmes.md` | Security review (design + code) | all | opus |
| Marie Curie | `researcher-curie.md` | Research | — | opus |
| Thomas Anderson | `dev-anderson.md` | Developer | `control` | opus |
| John von Neumann | `dev-neumann.md` | Developer | `edge` | opus |
| Pepper Potts | `dev-potts.md` | Developer | `infra` | opus |
| Hermione Granger | `reviewer-granger.md` | Code review | `control`, `edge`, `infra` | sonnet |

**Not installed in this project**, so nothing may wait on them: team leads
(each zone has one developer — Xavier is the escalation path), a second
reviewer, the analyst, the designer and the UI reviewer.

---
## Workflow phases
### Phase 0: Product intake (Taiichi Ohno) — `/product` only
**Skipped by every development command.** `/develop`, `/fix`, `/refactor` and
`/epic` start at Phase 1. Phase 0 exists for asks where *what is worth doing* is
still open: business questions, R&D, devrel, and a new project's charter.

Anything that turns into code leaves Phase 0 as a task, never as an
implementation: the PO writes `ohno-to-xavier-{task-id}.md` with fixed
acceptance criteria, and Phase 1 runs unchanged.

Ohno is reached **only** through `/product`. This project has
no tracker service and no Hub: the slash command spawns him, he reads and writes
`docs/product/`, and he exits. Nothing dispatches to him automatically, and no
development command waits on him.

### Phase 1: Architecture & requirements (Xavier)
1. The project owner submits a request.
2. Xavier assigns a `task-id` and creates `docs/tracker/{task-id}/{status,tasks}/`.
3. Xavier reads the context (`README.md`, `CLAUDE.md`, and the `AGENTS.md` of every zone in
scope (`control/AGENTS.md`, `edge/AGENTS.md`, `deploy/AGENTS.md`)) and the rulebooks for the affected
   zones, and decides which zones are involved.
4. Xavier asks clarifying questions — once, in one batch — and waits.
5. Xavier writes one spec per involved developer, each naming the zone, the
   scope, the out-of-scope list, the contracts at the boundary, and the
   acceptance criteria.
6. Xavier opens a security review of the design for Sherlock Holmes.

### Phase 2: Security review of the design (Sherlock Holmes)
Findings written to `docs/tracker/{task-id}/tasks/holmes-to-xavier-{task-id}-findings.md`.
Critical findings go back to Phase 1 before decomposition starts.

### Phase 3: Decomposition — **not used in this project**
There are no leads here: every zone has exactly one developer, so Xavier's specs
go straight to that developer. Nothing waits on this phase.

### Phase 4: Implementation (developers)
1. Developers implement only inside their zone.
2. Every rulebook named in their pre-read applies.
3. **Acceptance criteria are e2e scenarios**: one scenario per criterion, written
   before or alongside the code. Unit tests only where a specific piece of pure
   logic is worth pinning. A test that cannot fail is worse than no test.
4. Every new externally reachable surface goes in the developer's **surface
   audit** (what it is, who may reach it, how that is enforced, behaviour on
   invalid input).
5. The zone's own verify command (see the zone table above) passes **before**
   review — not `make test`, which is the project-wide one.
6. Developers keep their own status file current.

### Phase 5: Code review (Hermione Granger)
One reviewer covers all three zones. Order of checks: acceptance criteria first,
then scope, then rulebooks, then correctness. Reviewers report; they never edit.
Ownership overlap and integration consistency are checked by Xavier in Phase 7 —
in a fleet with no leads, that check has exactly one owner and it is him.

### Phase 6: Security review of the code (Sherlock Holmes)
Traceability from the Phase 2 findings to the code that addresses them, then the
implementation itself: authz boundaries, input validation, secret handling,
logging, error leakage, and the surface audit against the diff.

### Phase 7: Completion (Xavier)
Xavier verifies that the sum of the changes matches the original request: every
criterion has a corresponding change, contracts are consistent, no zone was
edited by two owners, verification passes. This is the **technical** check.

### Phase 8: Acceptance (Taiichi Ohno) — only for work the PO dispatched
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
`docs/tracker/{task-id}/status/{agent-file-name}.yml`:
```yaml
agent: anderson
role: dev
zone: control
task: "Feature or sub-feature name"
status: in_progress
progress: "What is done so far"
blockers: null
updated: 2026-01-01T12:00:00Z
```
Status values: `idle` / `pending` / `in_progress` / `blocked` / `review` / `done`.

Developers moving to `review` must also carry `pre_read`, `verified` and
`surfaces` (see the dev persona).

---
## Fix flow (`/fix`)
1. Xavier assigns the bug to **one** zone.
2. That zone's developer takes one fix task.
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
