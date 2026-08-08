# /epic — Epic Decomposition Pipeline (hashi)

> **Solo project.** There is only one persona here — `alfred`. Ignore every "spawn `<agent>`" instruction below **except the one phase that says "Run the review-loop skill"** (do not confuse this with a phase that merely has "Review" in its title, such as a Quality Review that spawns Xavier — that one is not the exception; collapse it into your own work like every other spawn instruction): do every other phase's work yourself, in this same context, one phase after another, and skip any step that exists only to hand work between separate agents (Handoff files, cross-agent status pushes). The review-loop phase still happens — the review-loop skill (`.claude/skills/review-loop/`) spawns `reviewer-strict`, a second, independent, edit-incapable agent, for every development task, and in solo YOU (the orchestrator) apply its findings yourself, same as the skill's default rule. This is not optional and self-review is never a substitute for it — see `alfred.md`.

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

4. Register the task in the SQLite tracker:
```bash
TASK_RECORD=$( task:create \
  "epic: {epic title}" \
  "{epic description from arguments}" \
  "epic" \
  "Pipeline: /epic")
TRACKER_ID=$(echo "$TASK_RECORD" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
 task:status "$TRACKER_ID" in_progress
```

Remember `$TRACKER_ID` — use it for all ` task:*` calls throughout this pipeline.

---

## Phase 1 — Clarifying Questions (Xavier)

Spawn sub-agent `architect-xavier` with:
```
Epic request from the project owner: <full description>
task-id: <task-id>

You are in EPIC DECOMPOSER mode. Before decomposing, you must understand the full scope.

Read project context:
`README.md`, `CLAUDE.md`, `control/AGENTS.md`, `edge/AGENTS.md`, `deploy/AGENTS.md`
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
scripts/notify.sh "Xavier asked clarifying questions about the epic. Reply here."
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

## Phase 3 — Load tasks into tracker

After the project owner confirms (any affirmative reply), read the decomposition file and create each task in order:

```bash
# Repeat for each task (they will be queued in creation order = FIFO priority):
 task:create \
  "<task title>" \
  "<task description>" \
  "<type>" \
  "Epic: <epic slug>. <notes>"
```

This loads them into the tracker queue. `/next` will execute them in FIFO order.

---

## Phase 4 — Show final queue

```bash
 task:list pending
```

Display the pending queue in chat so the project owner can see the order.

---

## Phase 5 — Notify & Complete

```bash
 task:status "$TRACKER_ID" done
scripts/notify.sh "Epic loaded: <epic title>

Tasks queued: N
<numbered list: 1. title, 2. title, ...>

Run /next to start execution."
```

---

## Rules

- Do NOT start implementing anything — this command only populates the queue.
- Do NOT skip the clarifying questions phase — better to ask now than discover blockers during implementation.
- Task descriptions must be self-contained — the agent running `/next` will only see the task, not this conversation.
- If the project owner rejects the decomposition, revise and re-confirm before loading.
- Each task's notes must mention which previous task it depends on (if any).
