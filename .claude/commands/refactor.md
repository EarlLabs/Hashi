# /refactor — Refactoring Pipeline (hashi)

> **Solo project.** There is only one persona here — `alfred`. Ignore every "spawn `<agent>`" instruction below **except the one phase that says "Run the review-loop skill"** (do not confuse this with a phase that merely has "Review" in its title, such as a Quality Review that spawns Xavier — that one is not the exception; collapse it into your own work like every other spawn instruction): do every other phase's work yourself, in this same context, one phase after another, and skip any step that exists only to hand work between separate agents (Handoff files, cross-agent status pushes). The review-loop phase still happens — the review-loop skill (`.claude/skills/review-loop/`) spawns `reviewer-strict`, a second, independent, edit-incapable agent, for every development task, and in solo YOU (the orchestrator) apply its findings yourself, same as the skill's default rule. This is not optional and self-review is never a substitute for it — see `alfred.md`.

**You are the pipeline ORCHESTRATOR.** Do NOT refactor anything yourself.
`subagent_type` = the filename in `.claude/agents/` without `.md`.

**The defining rule: behaviour does not change.** If the request would change what
the software does, it is not a refactor — run `/develop`. Say so and stop.

---

## Before you start

1. Assign a `task-id` and create `docs/tracker/{task-id}/{status,tasks}/`.
2. Record the goal — refactors without a stated goal expand without limit:
```bash
cat > docs/tracker/{task-id}/README.md <<'EOF'
# {task-id}

**Type:** refactor
**Goal:** {what becomes easier afterwards, concretely}
**Behaviour change:** none
**Out of scope:** {what must NOT be touched}
EOF
```
3. **Establish the safety net first.** Identify the scenarios that prove current
   behaviour. If they do not exist, the first task of this refactor is writing
   them — a refactor without a net is a rewrite with optimism.

---

## Phase 1 — Scope (Xavier)

Spawn `architect-xavier`:
```
task-id: <task-id>
Refactor request: <description>

Define the boundary: which zone(s), which paths, what stays untouched.
State how behaviour preservation will be proven.
Write one spec per involved target:
docs/tracker/<task-id>/tasks/xavier-to-<target>-refactor-<task-id>.md
```

Prefer one zone at a time. A refactor touching every zone at once cannot be
reviewed, cannot be bisected, and cannot be safely reverted.

---

## Phase 2 — Execute (leads → developers, or developers directly)

```
task-id: <task-id>
Refactor your task: docs/tracker/<task-id>/tasks/<from>-to-<dev>-refactor-<task-id>.md

Behaviour must not change. Do not add features, do not fix unrelated bugs
(report them instead), do not rename what the task did not ask you to rename.
Run the safety-net scenarios before you start and after you finish — the same
set must pass, unchanged.
```

---

## Phase 3 — Review (max 2 rounds)

Record the baseline before Phase 2. Run the **review-loop** skill
(`.claude/skills/review-loop/`): task = the refactor's stated goal, round
cap = 2, starting point = **Already done** with that
baseline, reviewer = the zone's reviewer persona. **The owning developer
fixes findings — never you, the orchestrator** (same carve-out as `/fix`).
The question for this review is not "is the new code nicer" but:
1. Did behaviour change anywhere? Any changed assertion is a finding.
2. Is the stated goal actually achieved?
3. Did unrelated changes ride along?
4. Is the diff reviewable, or should it have been split?

Hitting the round cap means the refactor is too large — split it and start
over rather than reviewing it again.

---

## Phase 4 — Verify

```bash
make test-control && make test-edge && make test-infra
```
Plus the safety-net scenarios, **unchanged**. A refactor that required editing its
own tests to stay green has changed behaviour — send it back and make that the
finding.

Deliver as in `/develop` Phase 9.

---

## Rules

- Behaviour changes → `/develop`, not here.
- Test edits inside a refactor are a red flag, not a convenience.
- One zone at a time unless the owner explicitly accepts a wider blast radius.
- `blocked` → notify the owner and stop.
