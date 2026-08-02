# move-the-owner-s-real-secrets-out-of-the-fleet-s-read-write-11

**Type:** feature (`/develop`) · **Zone:** `infra` (only)
**Epic:** `directive-90be25f3-9` — task 2 of 18, Stage 1 (M1)
**Backlog item:** `0` — `infra-env-out-of-warden-mount`
**Baseline:** `50fe8c1cd2e82cddd1e4d4bc1db5690eeceaec3e`
**Branch:** `task/2-env-out-of-warden-mount-directive-90be25f3-9` → PR into `develop`

**Goal:** the warden stack must read its environment file from a path OUTSIDE
every path mounted into the agent container, so the owner's real secrets stop
sitting inside a read-write mount handed to an unattended agent; and a start
without that file must fail loudly naming the required action instead of
silently substituting empty strings. Folds in the related `Makefile` defect
(warden compose run without `--env-file`).

**Acceptance (frozen, `docs/research/product-owner-ohno-4/research.md` §3 item 0):**
- **S1** no file carrying real secrets is under any path mounted into the agent container.
- **S2** the warden stack starts from the new location; a start without the env file
  fails with a clear error. **S2 cannot execute here** — no container runtime.

**Residual risk not removed by this task:** the owner must still move the file.
