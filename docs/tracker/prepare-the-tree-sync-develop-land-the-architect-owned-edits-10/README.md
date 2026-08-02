# prepare-the-tree-sync-develop-land-the-architect-owned-edits-10

**Type:** refactor
**Epic:** `directive-90be25f3-9`, task 1 of 18 (Stage 0 — preparation)
**Spec:** `docs/tracker/directive-90be25f3-9/tasks/xavier-epic-decomposition-directive-90be25f3-9.md` §1

**Goal:** the fleet's next 17 tasks branch from a tree that is (1) not six commits
stale, (2) able to ship `edge/transports/*` into a built image, (3) already
carrying every dependency this epic was designed around, so no developer is
blocked by design — and (4) able to read the architect's decided contract text
somewhere that is not write-protected.

**Behaviour change:** none. No runtime code is touched. `pyproject.toml` changes
what the *build* collects and what the *environment* contains; every import path,
entry point and test assertion stays as it is.

**Out of scope — must NOT be touched:**
- `.claude/**` — write-protected; this task exists partly because of that
- `docs/product/backlog.md`, `docs/product/charter.md` — Product Owner's files
- `control/**`, `edge/**`, `deploy/**` — zone territory
- `main` — never pushed to, never agent-merged
- the stale `origin/task/2-control-plane-…` branch — left alone deliberately

**Safety net:** `make test` (full suite, all three zones) before and after, plus
`pip install . --target` proving `edge/transports/` reaches an installed tree —
the empirical reproduction of the defect (b) fixes.
