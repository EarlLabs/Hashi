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

## Phase 3 — Review (max 2 rounds)

Record the baseline before Phase 2 (`git rev-parse HEAD`) so the reviewer reads a
diff rather than the developer's account of it. Then spawn the zone's reviewer:
```
task-id: <task-id>
Round: N of 2
Diff range: git diff <baseline>..HEAD
Review the fix. Run the zone's verify command yourself — a failure is Must Fix.
Confirm: the reproduction now passes, a regression scenario exists and CAN fail,
the change is minimal and inside the zone, no unrelated refactoring rode along.
[round 2] Verify each previous finding explicitly before reviewing again.
End with exactly: VERDICT: CLEAN  or  VERDICT: <n> must-fix, <m> should-fix
```

Must-fix → the **owning developer** fixes (never the orchestrator) → round 2.
Still must-fix after round 2, or a round re-reporting an earlier round's fix →
stop and ask the owner. A bug fix that needs three review rounds is not a bug
fix; it is a design problem wearing one.

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
