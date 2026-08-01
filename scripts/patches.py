#!/usr/bin/env python3
"""Project surgery applied to hashi/.claude AFTER a fresh kit render.

WHAT: every edit that turns the generic kit into *this* project's fleet — no
      leads, no tracker service, per-zone e2e directories.
WHY:  the kit is a moving target (it changed mid-scaffold once already). Keeping
      the surgery as a script means re-rendering from a newer kit is one command
      instead of an archaeology exercise, and every patch that stops matching
      fails loudly instead of silently not applying.
HOW:  python3 scripts/render.py && python3 scripts/patches.py, from the repo
      root. Each patch asserts its anchor and fails loudly if the kit moved.
"""
import pathlib
import sys

OUT = pathlib.Path(__file__).resolve().parents[1] / ".claude"

NO_LEADS = """**This project has no leads.** Every zone has exactly one developer,
so Xavier's specs are already developer tasks: they go straight to the zone's
developer."""

PATCHES: list[tuple[str, str, str]] = [
    # ---------------------------------------------------------------- develop
    ("commands/develop.md",
     """4. Register the task, if this project has a tracker service:
```bash
{{TRACKER_CMD}} task:create "feature: {task-id}" "{description}" "feature" "Pipeline: /develop"
```
Remember the returned id for the status updates below.""",
     """4. **This project has no tracker service.** The tracker is the directory tree
   above and nothing else — there is no queue to register with and no id to
   remember."""),

    ("commands/develop.md",
     """## Phase 3 — Decomposition (leads, in parallel)

For **each** spec file addressed to a lead, spawn that lead simultaneously:
```
task-id: <task-id>
Read and decompose: docs/tracker/<task-id>/tasks/xavier-to-<lead>-<task-id>.md
Create developer task files in docs/tracker/<task-id>/tasks/.
Developer scopes must not overlap in files.
```

**Skip this phase for zones with no lead** — those specs go straight to the
developer. Wait for all leads before Phase 4.""",
     f"""## Phase 3 — Decomposition

{NO_LEADS} Skip to Phase 4."""),

    ("commands/develop.md",
     """which zones actually changed. For each changed zone, spawn its reviewer **and**
its lead (if it has one), in parallel, with a **fresh** agent each round:""",
     """which zones actually changed. Spawn `reviewer-granger` — one reviewer covers all
three zones here — as a **fresh** agent each round:"""),

    ("commands/develop.md",
     """  already has a lead and a security review; a fourth code-review round is
  reviewers arguing, not defects being found.""",
     """  already has Xavier's completion check and a security review; a fourth
  code-review round is reviewers arguing, not defects being found."""),

    ("commands/develop.md",
     "- Leads never write implementation code; reviewers never edit code.",
     """- Reviewers never edit code; Xavier never implements. Scope questions go to the
  owner (or to Ohno if `/product` dispatched this task), never to a developer."""),

    # -------------------------------------------------------------------- fix
    ("commands/fix.md",
     """## Phase 2 — Fix (developer, or lead → developer)

Zone with a lead: spawn the lead to write the single developer task, then the
developer. Zone without: spawn the developer directly.""",
     """## Phase 2 — Fix (the zone's developer, directly)

This project has no leads — every zone has exactly one developer, so Xavier's fix
task goes straight to them. Spawn that developer."""),

    # --------------------------------------------------------------- refactor
    ("commands/refactor.md",
     "## Phase 2 — Execute (leads → developers, or developers directly)",
     "## Phase 2 — Execute (the zone's developer, directly)"),

    # --------------------------------------------------------------- workflow
    ("workflow.md",
     """### Phase 3: Decomposition (leads)
Each lead decomposes its spec into **non-overlapping** developer tasks. Two
developers assigned the same file is the most expensive mistake available at this
step. Leads write tasks and acceptance criteria; leads do not write code.

Zones with a single developer skip this phase — the spec goes straight to them.""",
     """### Phase 3: Decomposition — **not used in this project**
There are no leads here: every zone has exactly one developer, so Xavier's specs
go straight to that developer. Nothing waits on this phase."""),

    ("workflow.md",
     """### Phase 5: Code review loop (reviewers + leads, max 3 rounds)
Reviewers are scoped by zone and run in parallel when several zones changed.
Leads verify scope compliance, ownership overlap and integration consistency.
Order of checks:""",
     """### Phase 5: Code review loop (Hermione Granger, max 3 rounds)
One reviewer covers all three zones. Ownership overlap and integration
consistency are Xavier's in Phase 7 — in a fleet with no leads that check has
exactly one owner, and it is him.
Order of checks:"""),

    ("workflow.md",
     """5. Xavier writes one spec per involved lead or direct-report developer, each
   naming the zone, the scope, the out-of-scope list, the contracts at the
   boundary, and the acceptance criteria.""",
     """5. Xavier writes one spec per involved developer, each naming the zone, the
   scope, the out-of-scope list, the contracts at the boundary, and the
   acceptance criteria."""),

    ("workflow.md",
     "2. The lead (or the direct-report developer) takes one fix task.",
     "2. That zone's developer takes one fix task."),

    ("workflow.md",
     "5. Verification (`the zone's verify command (see the zone table above)` for the zone) passes **before** review.",
     """5. The zone's own verify command (see the zone table above) passes **before**
   review — not `make test`, which is the project-wide one."""),

    ("workflow.md",
     """   git checkout develop && git pull origin develop && git merge origin/main --no-edit
   ```""",
     """   git checkout develop && git pull origin develop && git merge origin/main --no-edit
   ```
   **This repository has no `origin` yet.** Until one exists, the local
   equivalent is `git checkout develop && git merge main --no-edit` — and if you
   skip it you will branch from a tree missing everything merged since."""),

    # ------------------------------------------------------------------- epic
    ("commands/epic.md",
     """4. Register the task in the SQLite tracker:
```bash
TASK_RECORD=$({{TRACKER_CMD}} task:create \\
  "epic: {epic title}" \\
  "{epic description from arguments}" \\
  "epic" \\
  "Pipeline: /epic")
TRACKER_ID=$(echo "$TASK_RECORD" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
{{TRACKER_CMD}} task:status "$TRACKER_ID" in_progress
```

Remember `$TRACKER_ID` — use it for all `{{TRACKER_CMD}} task:*` calls throughout this pipeline.""",
     """**This project has no tracker service and no queue.** The decomposition lands in
the backlog that Ohno owns (`docs/product/backlog.md`), and tasks are started one
at a time with `/develop`. There is nothing to register and no id to remember."""),

    ("commands/epic.md",
     'scripts/notify.sh "Xavier задал уточняющие вопросы по эпику. Ответьте здесь."',
     'scripts/notify.sh "Xavier has clarifying questions about the epic. Reply here."'),

    ("commands/epic.md",
     """## Phase 3 — Load tasks into tracker

After the project owner confirms (any affirmative reply), read the decomposition file and create each task in order:

```bash
# Repeat for each task (they will be queued in creation order = FIFO priority):
{{TRACKER_CMD}} task:create \\
  "<task title>" \\
  "<task description>" \\
  "<type>" \\
  "Epic: <epic slug>. <notes>"
```

This loads them into the tracker queue. `/next` will execute them in FIFO order.

---

## Phase 4 — Show final queue

```bash
{{TRACKER_CMD}} task:list pending
```

Display the pending queue in chat so the project owner can see the order.

---

## Phase 5 — Notify & Complete

```bash
{{TRACKER_CMD}} task:status "$TRACKER_ID" done
scripts/notify.sh "Epic loaded: <epic title>

Tasks queued: N
<numbered list: 1. title, 2. title, ...>

Run /next to start execution."
```""",
     """## Phase 3 — Hand the tasks to the backlog (Ohno)

After the project owner confirms (any affirmative reply), spawn
`product-owner-ohno` to fold the decomposition into the backlog he owns:

```
task-id: <task-id>
Mode 2 — the epic decomposition at
docs/tracker/<task-id>/tasks/xavier-epic-decomposition-<task-id>.md is approved
by the owner. Add each task to docs/product/backlog.md in order, with acceptance
criteria written as Given/When/Then e2e scenarios, out-of-scope, depends_on and
status: queued. Do not re-scope the tasks; if one does not trace to a line in
docs/product/charter.md, say so instead of adding it.
```

**Xavier does not write the backlog** — it is Ohno's file, and a decomposition
that edits it directly would put an architect in charge of scope.

---

## Phase 4 — Show the queue

Display the queued items from `docs/product/backlog.md` in chat, in order, so the
project owner can see what will be built and in what sequence.

---

## Phase 5 — Notify & Complete

```bash
scripts/notify.sh "Epic decomposed: <epic title>

Tasks in backlog: N
<numbered list: 1. title, 2. title, ...>

Start the first one with /develop <task-id>."
```"""),

    ("commands/epic.md",
     """- Do NOT start implementing anything — this command only populates the queue.""",
     """- Do NOT start implementing anything — this command only fills the backlog."""),

    ("commands/epic.md",
     "- Task descriptions must be self-contained — the agent running `/next` will only see the task, not this conversation.",
     "- Task descriptions must be self-contained — the fleet running `/develop <task-id>` will only see the task, not this conversation."),

    # ---------------------------------------------------------------- product
    ("commands/product.md",
     """3. Register the task so it shows up in the bot and dashboard:
```bash
TASK_RECORD=$({{TRACKER_CMD}} task:create \\
  "product: {task-id}" \\
  "{the ask, verbatim from the project owner}" \\
  "product" \\
  "Pipeline: /product")
TRACKER_ID=$(echo "$TASK_RECORD" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
{{TRACKER_CMD}} task:status "$TRACKER_ID" in_progress
```""",
     """**This project has no tracker service.** The tracker is the directory tree above
plus `docs/product/`; there is nothing to register with."""),

    ("commands/product.md",
     """**Devrel writing / specs** → `analyst-lovelace`; **visuals/mockups** →
`designer-davinci`, then `ui-reviewer-rams` — **only if those personas are
installed here.** If they are not, Ohno writes the artifact itself and says so in
the report. Never spawn an agent this project does not have, and never quietly
drop the deliverable because its usual author is missing.""",
     """**Devrel writing, specs, visuals** → **this project has no analyst, designer or
UI reviewer.** Ohno writes the artifact himself and says so in the report. Do not
spawn `analyst-lovelace`, `designer-davinci` or `ui-reviewer-rams` — they are not
installed here and the spawn will fail mid-pipeline. Never quietly drop the
deliverable because its usual author is missing."""),

    ("commands/product.md",
     """```bash
{{TRACKER_CMD}} task:status "$TRACKER_ID" done
scripts/notify.sh "Ohno — <task-id>: <verdict>""",
     """```bash
scripts/notify.sh "Ohno — <task-id>: <verdict>"""),

    # --------------------------------------------------------------- research
    ("commands/research.md",
     """4. Register the task in the SQLite tracker:
```bash
TASK_RECORD=$({{TRACKER_CMD}} task:create \\
  "research: {topic}" \\
  "{topic description from arguments}" \\
  "research" \\
  "Pipeline: /research")
TRACKER_ID=$(echo "$TASK_RECORD" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
{{TRACKER_CMD}} task:status "$TRACKER_ID" in_progress
```""",
     """**This project has no tracker service** — the tracker directories above are the
whole record. Nothing to register."""),

    # ----------------------------------------------------------------- review
    ("commands/review.md",
     """Find the most recent task with `status = review`:
```bash
{{TRACKER_CMD}} task:list
```""",
     """Find the most recent task with a status file at `status: review`:
```bash
grep -rl 'status: review' docs/tracker/*/status/ | sort
```"""),

    # ------------------------------------------------------------------ abort
    ("commands/abort.md",
     """## Step 2 — Update tracker (if applicable)

If a task-id can be identified:
```bash
{{TRACKER_CMD}} task:status "$TASK_ID" idle
{{TRACKER_CMD}} task:notes "$TASK_ID" "Aborted by the project owner. Returned to queue."
```""",
     """## Step 2 — Record the abort in the tracker files

This project has no tracker service, so the record is the task's own directory.
If a task-id can be identified, write the reason into every status file under
`docs/tracker/{task-id}/status/` that is not already `done`:

```yaml
status: blocked
progress: "Aborted by the project owner."
blockers: "Aborted by the project owner — <reason, if given>."
```

**Never delete the task directory.** An aborted task with its reason on the
record is what stops the same work being restarted blindly next week."""),

    ("commands/abort.md",
     "- After abort, the task goes back to `idle` — it can be picked up again by `/next`.",
     """- After abort, the task's tracker directory stays on the record. To pick the work
  up again, re-run `/develop <task-id>` — there is no queue in this project."""),

    # ------------------------------------------------------------------- ohno
    ("agents/product-owner-ohno.md",
     "| **devrel** — docs, examples, a demo, an announcement, a talk | **you** | own the audience and \"done\"; delegate production (Lovelace writes, Xavier's fleet builds the demo, da Vinci mocks the visuals) |",
     "| **devrel** — docs, examples, a demo, an announcement, a talk | **you** | own the audience and \"done\"; **write the artifact yourself** — this project has no analyst and no designer. Xavier's fleet builds any demo code |"),

    ("agents/product-owner-ohno.md",
     "the non-goals, what would change the answer | you, plus Lovelace if a spec falls out of it | the owner accepts",
     "the non-goals, what would change the answer | you | the owner accepts"),

    ("agents/product-owner-ohno.md",
     "what is deliberately left out | Lovelace writes, the dev fleet builds any demo code, da Vinci mocks visuals | the artifact exists",
     "what is deliberately left out | **you write it**; the dev fleet builds any demo code | the artifact exists"),

    ("agents/product-owner-ohno.md",
     """- **Success criteria** — answer 4, each written as a Given/When/Then scenario
  (see `docs/e2e/README.md` §3), because these become acceptance criteria later""",
     """- **Success criteria** — answer 4, each written as a Given/When/Then scenario,
  because these become acceptance criteria later. One user-visible outcome per
  scenario; no implementation words; a criterion nobody could run is not one"""),

    ("agents/product-owner-ohno.md",
     """- **A green suite is not acceptance.** For each new scenario there must be a
  **red-first proof** in the report (`docs/e2e/README.md` §3, rule 3) — the
  behaviour was broken, the right assertion went red, it was restored. Without
  it you have no evidence the test can fail.""",
     """- **A green suite is not acceptance.** For each new scenario there must be a
  **red-first proof** in the report — the behaviour was deliberately broken, the
  *right* assertion went red, and it was restored. Without it you have no
  evidence the test can fail at all, and a test that cannot fail is worse than
  no test."""),

    # ----------------------------------------------------------------- holmes
    ("agents/security-holmes.md",
     "- **Charles Xavier**: review the technical spec before it goes to team leads",
     """- **Charles Xavier**: review the technical spec before it goes to the zone
  developers (this project has no team leads — specs go straight to them)"""),

    ("agents/security-holmes.md",
     "2. Read all lead spec files included in the review task.",
     "2. Read all developer spec files included in the review task."),

    ("agents/security-holmes.md",
     """When all developers are done and the code reviewers + leads have performed their
initial checks:""",
     """When every developer reports `status: review` and Hermione Granger has reported
her findings:"""),
]

# Kit files carry renderer-only HTML comments; they are instructions to the
# scaffolder, not to agents, and an agent reading one will act on it.
STRIP_PREFIXES = ("<!-- Renderer:",)


def main() -> int:
    # Strip first: the kit's renderer comments sit between lines that patches
    # below use as anchors, and they must not survive into an agent's context.
    for path in OUT.rglob("*.md"):
        lines = path.read_text().splitlines(keepends=True)
        kept = [ln for ln in lines if not ln.lstrip().startswith(STRIP_PREFIXES)]
        if len(kept) != len(lines):
            path.write_text("".join(kept))

    failures = []
    for rel, old, new in PATCHES:
        path = OUT / rel
        text = path.read_text()
        if old not in text:
            failures.append(f"{rel}: anchor not found -> {old.splitlines()[0][:70]!r}")
            continue
        path.write_text(text.replace(old, new, 1))

    leftovers = sorted(
        f"{p.relative_to(OUT)}:{i}"
        for p in OUT.rglob("*.md")
        for i, ln in enumerate(p.read_text().splitlines(), 1)
        if "{{" in ln
    )

    for f in failures:
        print("PATCH FAILED:", f, file=sys.stderr)
    if leftovers:
        print("UNRESOLVED SLOTS:", *leftovers, sep="\n  ", file=sys.stderr)

    if failures or leftovers:
        return 1
    print(f"applied {len(PATCHES)} patches; no unresolved slots")
    return 0


if __name__ == "__main__":
    sys.exit(main())
