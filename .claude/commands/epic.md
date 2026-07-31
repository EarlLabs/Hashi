# /epic — Epic Decomposition Pipeline (hashi)

**You are the pipeline ORCHESTRATOR.** Do NOT decompose anything yourself.
Spawn each agent using the Agent tool. `subagent_type` = filename in `.claude/agents/` without `.md`.

All inter-agent communication happens via files only:
- `docs/tracker/{task-id}/status/`
- `docs/tracker/{task-id}/tasks/`

---

## Before You Start

1. Derive a short `task-id` slug from the epic (e.g., `epic-admin-panel`, `epic-feature-b-stats`).
2. Create tracker directories:
```bash
mkdir -p docs/tracker/{task-id}/status docs/tracker/{task-id}/tasks
```

3. Create a brief `README.md` at the task root:
```bash
cat > docs/tracker/{task-id}/README.md <<'EOF'
# {task-id}

**Type:** epic
**Goal:** {1-2 sentence summary of the epic}
EOF
```

**This project has no tracker service and no queue.** The decomposition lands in
the backlog that Ohno owns (`docs/product/backlog.md`), and tasks are started one
at a time with `/develop`. There is nothing to register and no id to remember.

---

## Phase 1 — Clarifying Questions (Xavier)

Spawn sub-agent `architect-xavier` with:
```
Epic request from the project owner: <full description>
task-id: <task-id>

You are in EPIC DECOMPOSER mode. Before decomposing, you must understand the full scope.

Read project context:
`README.md`, `CLAUDE.md`, and the `AGENTS.md` of every zone in
scope (`control/AGENTS.md`, `edge/AGENTS.md`, `deploy/AGENTS.md`)
- .claude/projects/00-core-invariants.md (if exists)

Think like a senior architect:
- What is the full scope? What is explicitly out of scope?
- What are the dependencies between parts?
- What corner cases could block execution?
- Are there security, data privacy, or architectural risks?
- What does "done" look like for the full epic?

Form 3-6 targeted clarifying questions. Focus on things that would change the decomposition.
Send questions via: scripts/notify.sh "Xavier — Epic Questions: <title>\n\n<numbered questions>\n\nReply when ready."

Write questions to: docs/tracker/<task-id>/tasks/xavier-epic-questions-<task-id>.md
Update: docs/tracker/<task-id>/status/architect-xavier.yml
```

**After Xavier returns: STOP the pipeline.**
```bash
scripts/notify.sh "Xavier has clarifying questions about the epic. Reply here."
```
Wait for the project owner's reply before continuing.

---

## Phase 2 — Decomposition (Xavier, after the project owner's answers)

Spawn sub-agent `architect-xavier` with:
```
Epic request: <original description>
task-id: <task-id>
the project owner's answers: <the project owner's reply>

You are in EPIC DECOMPOSER mode. Now decompose the epic into 3-7 medium tasks.

Rules for task sizing:
- Each task is independently deployable (has its own PR)
- Not too small (no "add a field" tasks) — each task should take ~2-4 hours of agent work
- Not too large (no "build the whole module" tasks)
- Tasks are ordered by dependency — task N must be completable before task N+1 starts

For each task define:
- Title — short, imperative (e.g. "Setup admin service scaffold with auth middleware")
- Description — 2-4 sentences: what to build, what NOT to build, acceptance criteria
- Type — feature, bugfix, or refactor
- Notes — scope hints, key files to touch, dependencies on previous tasks

Write the full decomposition to: docs/tracker/<task-id>/tasks/xavier-epic-decomposition-<task-id>.md
Send summary to the project owner via: scripts/notify.sh "Epic decomposition: <title>\n\n<numbered task list>\n\nDoes this look right? Should I adjust anything?"
Update: docs/tracker/<task-id>/status/architect-xavier.yml
```

**After Xavier returns:** Show the decomposition in chat.
Ask the project owner: "Does this decomposition look right? Should I adjust anything before I load it into the queue?"

**STOP here. Wait for the project owner's confirmation.**

If the project owner requests changes → re-spawn Xavier with feedback, repeat Phase 2.

---

## Phase 3 — Hand the tasks to the backlog (Ohno)

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
```

---

## Rules

- Do NOT start implementing anything — this command only fills the backlog.
- Do NOT skip the clarifying questions phase — better to ask now than discover blockers during implementation.
- Task descriptions must be self-contained — the fleet running `/develop <task-id>` will only see the task, not this conversation.
- If the project owner rejects the decomposition, revise and re-confirm before loading.
- Each task's notes must mention which previous task it depends on (if any).
