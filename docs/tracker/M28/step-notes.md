# M28 — step notes
Conventions established here. They bind later steps, and later milestones in
this codebase, until something supersedes them. Follow them; do not relitigate.

## M28.1 — what the artifact is, and the sentence that was false

`make test-infra` 241 passed; `make verify` green (e2e 192 passed). Words only —
no behaviour changed, and the reviewer confirmed no `pg_dump`, `gzip`, `chmod`,
restore or compose line moved.

1. **The four-item decision lives in `docs/deploy/runbook.md` → `## Backups` →
   "What belongs in a backup, and what does not"**, a five-row table.
   **Later steps extend that table; do not restate the decision elsewhere.**
   Verdicts, so nobody re-derives them: database **yes**; `caddy_data` **no**;
   `~/.hashi/management/` **yes, but only inside the whole-artifact age
   encryption — never in the plain dump**; `.env` **never, not even encrypted**;
   `/opt/hashi` on a node **no**.

2. **`.env` is the one an operator will be tempted to include, and the reason is
   the whole design.** It holds `HASHI_SECRET_KEY`; beside the data, one stolen
   age identity yields both halves and the encryption bought nothing. Excluding
   it is exactly what makes a restore cost **two secrets that never meet on the
   control host**.

3. **The exact `EncryptedText` set, verified against `control/app/models/`:**
   `Node.ssh_private_key`, `NodeTransport.secrets`, `Subscription.token`,
   `Credential.subject`, `Credential.secrets`, `Credential.tunnel_address` — six,
   no more, no fewer. Everything else is in the clear, including **every node's
   real address and port**, `ssh_host_key`, `transport_name`, states and every
   timestamp. Any later text describing the artifact must match this list.

4. **The artifact's description and the artifact's behaviour must change in the
   same step.** The script and the runbook now deliberately say **"this file is
   NOT encrypted"**. M28.2, when it adds `age`, must update the script's WARNING
   block, the script header **and** the runbook's `## Backups` opening in that
   same diff, or the project ships a new lie pointing the other way.

5. **`tests/infra/test_backup_script.py::test_every_run_says_the_dump_needs_the_secret_key`
   asserts the literal substrings `HASHI_SECRET_KEY` and `cannot be restored`**
   are present in `scripts/backup.sh`. Any rewording keeps both or changes the
   test with it. The reviewer checked the current wording is not gaming it: both
   substrings attach to a true claim about the six columns.

6. **`caddy_data`'s reasoning is documentation-derived, not measured**, and is
   recorded in the runbook's `## Known-unproven`. This project has never
   re-issued a certificate on a replacement host. **Do not upgrade it to a fact
   without a real rebuild.** The `tls internal` half was verified in
   `deploy/caddy/Caddyfile`: the panel is unaffected by losing `caddy_data`; only
   `/sub/*` needs a public issuance.

7. **`~/.hashi/management/` is regenerable but not reproducibly.**
   `scripts/management-tunnel.sh` writes the host's own key and each peer's
   public key and PSK to disk, but **prints each peer's private key once and
   keeps no copy** — verified. A fresh run regenerates the host keys, so every
   device already enrolled breaks.

### How to test a words-only change to the script

`make test-infra` (4s, no Docker) reads `scripts/backup.sh` as text; nothing
boots. **The only thing that runs the script is
`tests/e2e/infra/test_restore_proves_the_backup.py`** (~3 min, inside
`make verify`). Check `docker compose ls` for a live stand before `make verify` —
an acceptance stand's browser container joins the same project and fails
`test_stack_boots`.

### Wording later steps must match

The dump warning opens **"IMPORTANT: this file is NOT encrypted."** The runbook
heading is **"What belongs in a backup, and what does not"**. The three carried
items are **`HASHI_SECRET_KEY`**, **the private half of the age keypair**, and
**a read credential for the backup bucket** — the last two flagged as future,
not claimed as present.

## M28.2 — the artifact is encrypted, and the host cannot read it back

`make test-infra` 249 passed (was 241, +8); `make verify` green (e2e 194 passed).
Every claim below was reproduced by the reviewer running it, not reading it.

1. **`age` lives in the CONTROL IMAGE, not on the host** (`deploy/docker/control.Dockerfile`,
   apt, Debian trixie, deliberately **unpinned** — a Debian binary revision is a mirror
   snapshot that gets deleted, so a pin fails the rebuild you are doing *because* you
   need a restore; what is stable is the file format, which age versions itself).
   Same reasoning as pg_dump-in-the-db-container. **Nothing new is required of the
   control-plane host, and the suite passes on a machine with no `age`.** Do not
   "simplify" this to a host package: the restore host is rented an hour before use.
   The apt layer sits before the source `COPY`, so ordinary code changes keep it cached.

2. **The plaintext exists only in RAM, in flight.** `pg_dump` (db) → `gzip -9` (host) →
   `age` (control) → file. The destination is created **empty under `umask 077` before
   the write** — the old code ran `chmod 600` *after*, leaving a window at the
   operator's umask — then `chmod 600` and `mv`; a failed pipeline deletes the partial,
   so no half-artifact can be mistaken for a backup. Restore mirrors it: ciphertext
   staged into the container, identity streamed on stdin (`--identity -`), plaintext a
   pipe into `psql`, staged file removed by an EXIT trap. **No intermediate plaintext
   file, no temp, no encrypt-in-place, in either direction.**

   Known residual, accepted: the plaintext crosses the host's memory between two
   containers. Closing it means building our own Postgres image, and
   `tests/infra/test_builds_converge.py` records that the db being **pulled** is why a
   build never recreates it. **Do not make `db` a built service to shorten this pipe.**

3. **The recipient reaches `age` through `deploy/docker-compose.backup.yml`** — a
   one-variable overlay loaded only by `scripts/backup.sh`, with a `:?` guard. It is
   **not** in the base compose file because `tests/infra/test_compose.py::test_required_env_vars_fail_loudly`
   requires a `:?` guard on every interpolation there, and **`${VAR:?}` fires on an
   EMPTY value too** (verified live) — `.env.example` ships the recipient blank, so the
   whole stack would refuse to boot on a host with no keypair yet. **No Make target may
   load this overlay**; a test asserts it.

4. **A missing or blank recipient is a refusal, before `pg_dump` runs, and there is no
   plaintext fallback — ever.** `compose config --quiet` trips the guard first, so the
   database is untouched and no file exists. A fallback is how the plain shape survives.

5. **Restore takes `HASHI_RESTORE_AGE_IDENTITY` (a path) from the environment at the
   moment it runs.** The private half is never written to this host.
   `HASHI_RESTORE_AGE_IDENTITY=… make restore FROM=…` is the documented form.

6. **The shape is sniffed from the file, never the name**: `age-encryption.org/v1` →
   age; gzip magic `1f8b` → the pre-M28.2 plain shape (restores, no identity needed);
   anything else → refused naming both shapes. **All three resolve before the
   destructive confirmation prompt** — nobody types a database name to authorise a
   restore that was always going to refuse. Pre-M28.2 artifacts must keep restoring;
   do not drop that branch.

7. **`docker compose run` replaced `exec` for the dump**, because `exec` reads the
   environment a container was *created* with, so a recipient added to `.env` without a
   `make up` would be silently missing. Cost: one container start per backup, and
   compose's creation noise — **stderr only; stdout is byte-clean, verified with a
   100,000-byte round trip.** Anything added to this pipeline must preserve that, since
   one polluting byte corrupts the artifact.

8. **What a reader of the bucket learns is now a recorded decision**
   (`docs/decisions.md`, two rows of 2026-09-23): existence, size and timing and nothing
   else — plus the jurisdiction and payment-identity row, accepted knowingly. **M28.3
   and M28.4 cite those rows rather than re-deriving them.**

### How to test what M28.2 built

- `tests/infra/test_backup_script.py` gained `body_of()` / `code_of()` helpers that
  extract one shell function with comments and heredocs stripped — **use them for any
  ordering claim**, or the assertion measures the prose.
- `tests/e2e/infra/test_restore_proves_the_backup.py` carries a **committed disposable
  age keypair**. Committed on purpose: generating one needs `age` on the machine running
  pytest, which the design exists to avoid. The stack's env file gets only the public
  half; the private halves are passed only when a test invokes
  `HASHI_RESTORE_AGE_IDENTITY`, mirroring what a real operator does.
- `control_image(project, path)` asks compose for the built image name **while the stack
  is up**; `age_in_the_image()` runs age via `docker run --rm -i --entrypoint sh <image>`.
  **`--entrypoint sh` is mandatory** — the image's own entrypoint boots the app and
  answers "database did not become reachable" instead of decrypting.
- The fixture produces **two** artifacts: the encrypted one from the script, and a
  pre-M28.2 plain `.sql.gz` taken with `pg_dump` directly, because the script has no
  code path that writes one any more. Five scenarios, ~150s.
