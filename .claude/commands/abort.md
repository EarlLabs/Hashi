# /abort — Discard Current Work & Return to Clean State

Use `/abort` to abandon the current task and return to a clean state.

---

## Step 1 — Identify current state

Check if there's an in-progress task in `docs/tracker/` status files.

If **git workflow instructions** were provided (remote mode):
```bash
CURRENT_BRANCH=$(git branch --show-current)
```
If already on `develop` or `main` → notify the project owner "Already on develop, nothing to abort." and stop.

---

## Step 2 — Record the abort in the tracker files

This project has no tracker service, so the record is the task's own directory.
If a task-id can be identified, write the reason into every status file under
`docs/tracker/{task-id}/status/` that is not already `done`:

```yaml
status: blocked
progress: "Aborted by the project owner."
blockers: "Aborted by the project owner — <reason, if given>."
```

**Never delete the task directory.** An aborted task with its reason on the
record is what stops the same work being restarted blindly next week.

---

## Step 3 — Discard changes

If **git workflow instructions** were provided (remote mode):
```bash
git checkout -- .
git clean -fd
git checkout develop
git pull origin develop
git merge origin/main --no-edit
git branch -D "$CURRENT_BRANCH"
```

If **no git workflow instructions** (local mode):
- Revert any uncommitted changes in the working directory
- Report what was discarded

---

## Step 4 — Notify

If in remote mode:
```bash
scripts/notify.sh "Aborted task branch: $CURRENT_BRANCH
Switched to develop. Ready for next command."
```

---

## Rules

- This command ONLY discards local changes. It does NOT delete remote branches or close PRs.
- If a PR was already created, notify the project owner so they can close it manually if needed.
- After abort, the task's tracker directory stays on the record. To pick the work
  up again, re-run `/develop <task-id>` — there is no queue in this project.
