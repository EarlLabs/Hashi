# /fix — Bug Fix Pipeline (hashi)

**You are the pipeline ORCHESTRATOR.** Do NOT fix anything yourself.
`subagent_type` = the filename in `.claude/agents/` without `.md`.

Lighter than `/develop`: one zone, one developer, one review pass. If the bug
turns out to need work in two zones, stop and run `/develop` instead — a "fix"
spanning zones is a feature wearing a disguise.

---

## Before you start

`/fix <task-id> <bug description>`

- **Existing `task-id`** → reuse `docs/tracker/{task-id}/`, so the fix sits
  next to the work that introduced it.
- **New bug** → assign a slug, create
  `docs/tracker/{task-id}/{status,tasks}/`, and write the reproduction at the
  task root:
```bash
cat > docs/tracker/{task-id}/README.md <<'EOF'
# {task-id}

**Type:** fix
**Symptom:** {what the user sees}
**Expected:** {what should happen}
**Reproduction:** {exact steps, or the failing scenario}
EOF
```

A bug without a reproduction is a report, not a task. Get one before spawning
anybody — including from the owner, if that is the only source.

---

## Phase 1 — Triage (Xavier)

Spawn `architect-xavier`:
```
task-id: <task-id>
Bug: <description + reproduction>

Read docs/tracker/<task-id>/ for existing context.
Assign this bug to exactly ONE zone. Do not propose the fix — assign ownership
and state the expected behaviour.
Write: docs/tracker/<task-id>/tasks/xavier-to-<target>-fix-<task-id>.md
```

If Xavier reports the defect spans zones → stop, tell the owner, suggest
`/develop`.

---

## Phase 2 — Fix (the zone's developer, directly)

This project has no leads — every zone has exactly one developer, so Xavier's fix
task goes straight to them. Spawn that developer.
```
task-id: <task-id>
Fix your task: docs/tracker/<task-id>/tasks/<from>-to-<dev>-fix-<task-id>.md

Reproduce the bug first, then fix it. A fix you cannot show failing before and
passing after is not a verified fix.
Add the regression scenario that would have caught this.
```

---

## Phase 3 — Review

Spawn the zone's reviewer:
```
task-id: <task-id>
Review the fix. Confirm: the reproduction now passes, a regression scenario
exists and can fail, the change is minimal and inside the zone, no unrelated
refactoring rode along.
```

Spawn `security-holmes` **only** if the bug or its fix touches auth, input
handling, secrets or an externally reachable surface.

---

## Phase 4 — Verify

```bash
make test
```
Green, plus the reproduction now passing. Then deliver as in `/develop` Phase 9.

---

## Rules

- One zone, one developer. Two zones → `/develop`.
- No opportunistic refactoring inside a fix — it hides the fix in the diff.
- The regression scenario is part of the fix, not a follow-up.
- `blocked` → notify the owner and stop.
