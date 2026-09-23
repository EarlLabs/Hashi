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

## M28.3 — it leaves the machine, with a key that can only add to it

`make test-infra` 258 passed (was 249, +9); `make verify` green (e2e 199, was 194);
the restore scenario file alone: **10 passed, no skips**, so the store scenarios
really ran.

1. **The upload is `deploy/backup/upload.py` — standard library only, run inside a
   one-off control container.** `hashlib`/`hmac` sign, `http.client` sends. No SDK (a
   dependency, and `pyproject.toml` is architect territory), no vendor CLI, no
   `curl`+`openssl` (the image ships neither). **The program is passed to the container
   as a `-c` ARGUMENT read from the checkout, deliberately not baked into the image**:
   an upload must never wait on a rebuild, and a stale image cannot break it. Do not
   move it into the Dockerfile.

2. **The secret reaches the container only through the environment — verified
   empirically, not argued.** The reviewer ran the uploader with a marker secret and
   checked `docker inspect --format '{{json .Args}}'` and host `ps auxww`: **the secret
   is in neither.** Only the program source and `put`/object-name reach argv. Anything
   that changes how the uploader is invoked must preserve that — this is the box that
   gets seized.

3. **`http.client`, not `urllib`, and this was measured.** A store that refuses the
   credential answers and closes while the body is still going out; urllib reports
   "connection broken" and hides the 403 sitting in the socket. The write error is
   caught and the response read anyway, so the operator sees
   `HTTP 403: SignatureDoesNotMatch` instead of being sent to look at their network.

4. **Path style (`<endpoint>/<bucket>/<key>`), never bucket-as-subdomain** — the latter
   is one provider's DNS convention, not the protocol. The only vendor-shaped strings
   permitted anywhere are `AWS4-HMAC-SHA256`, `AWS4`, `aws4_request` and `x-amz-*`;
   `test_the_uploader_names_no_provider` strips exactly those and fails on the rest.
   Error text is reduced to the store's `<Code>`/`<Message>`; RequestId and HostId are
   dropped.

5. **`send()` hardcodes the literal `"PUT"` and `main()` exposes only
   `preflight`/`put`.** There is no GET, LIST or DELETE code path in the product — a
   test extracts the method from `putrequest` and asserts the set is exactly `{"PUT"}`.
   The e2e read-back calls the pure `signed()` helper for header maths and issues its
   own GET with `httpx`, so the test's shortcut never gives the product a read path.

6. **What "uploaded" means, and the sentence M28.6 must not inflate:** the store
   received exactly those bytes and accepted them — the payload SHA-256 is inside the
   signature, and the `ETag` is compared when it is md5-shaped. It does **not** mean the
   object is still there, that retention keeps it, or that it can be read back: the key
   is write-only and the host cannot look. Every successful run prints that distinction.
   **Write-only-ness is a bucket-side property no test here can assert.**

7. **Exit codes are now part of the script's contract: 0 written (and sent, if on), 1 no
   dump, 2 usage, 3 the dump exists and did NOT leave the machine.** **3 is what M28.6
   keys the panel's failure state on.** A failed upload never deletes or rewrites the
   artifact; `make backup-upload FROM=<path>` retries the same file and never touches
   the database.

8. **`deploy/docker-compose.upload.yml` carries the S3 block with NO `:?` guards**,
   unlike the base file — the variables are required only when
   `HASHI_BACKUP_ENABLED=1`, and a guard cannot say "required if". The conditional
   refusal lives in `upload.py::configuration()` and fires **before `pg_dump`**, naming
   every missing variable at once. The credential must never reach the long-running
   control container: no Make target loads this overlay and the base compose file
   carries no `HASHI_BACKUP_S3_*`. Tests assert both.

9. **Only the `age` shape is ever sent offsite.** `command_upload` sniffs magic bytes
   and refuses a pre-M28.2 plain dump — those still restore, but a bucket is somebody
   else's disk and that shape is a readable map of the fleet.

10. **`http` is refused unless the endpoint resolves to a private or loopback address.**
    SigV4 keeps the secret off the wire, but over plain http the key id and the bucket
    name would not be. This is also what lets a disposable test endpoint work without
    TLS. Known limit, recorded in the carry-over: the check resolves once and `send()`
    re-resolves, so a rebinding answer could differ.

### How to test what M28.3 built

`tests/e2e/infra/test_restore_proves_the_backup.py` is still the only thing that runs
the script end to end: **10 scenarios, ~160s**. The five new ones share one module
fixture, `offsite_scenarios()`, because all of them need a stack with a fleet and a
store on that stack's own network.

The store is `quay.io/minio/minio` **pinned** (quay, not the other registry, where it
is now behind a login), started with `--network <the stack's own, via docker inspect>`
and a bucket pre-created as a directory so no credential needs to create one. Published
on `127.0.0.1:54308` **only so pytest can read the object back**; the host under test
reaches it by container name. It is in no compose file and no Make target, and **it
must be removed before `compose down -v`** or the project's network will not delete.

If the image cannot be pulled the upload scenarios **skip** with "this is a skip, not a
pass" — an offline machine stays green and unproven rather than red. **Check which you
got** before believing an upload is covered.

### Wording later steps must match

Success prints **"the object store accepted it"** and **"What that proves… What it does
not prove"**. A failure prints **"The artifact is written and it did NOT leave this
machine"** plus `make backup-upload FROM=<path>`. With no store configured: **"This
artifact is on this host and nowhere else"**. The runbook's new subsection is **"Where
the artifact goes, and the credential that sends it"**.

## M28.4 — retention is on the bucket, and this repository cannot check it

`make test-infra` 263 passed (was 258, +5); `make verify` green (e2e 199, **no skips**,
so the offsite scenarios really ran). Documentation and five static tests; no behaviour
changed — confirmed by an empty diff over `scripts`, `deploy`, `control`, `edge`. Every
technical claim below was checked against real object-storage semantics by the reviewer.

1. **Bucket versioning is THE mechanism and is required. The three are not a choice.**
   Versioning answers the overwrite — the host's key can `PutObject` to an arbitrary
   name including yesterday's, and versioning makes that additive instead of
   destructive — and it downgrades a `DeleteObject` to a delete marker, covering "the
   key had more authority than intended" one level down. **Object lock** is an upgrade
   on top where a store has it: it is what survives `DeleteObjectVersion`, is defined on
   versions, therefore requires versioning and is never a substitute. **A lifecycle rule
   defends against nothing** — it deletes on a schedule, is the necessary counterweight
   to versions accumulating, and is the only one that can undo the other two. Do not
   relitigate this as "pick whichever the store offers".

2. **The object name is not the defence, and it looks like it.** `hashi-<timestamp>…`
   stops two runs colliding — an accident. **The uploading key picks the name, so it can
   write yesterday's.** Naming defends against mistake; versioning defends against
   intent. Keep that split in any later text.

3. **The fallback, if a store has none of the three: a copy pulled DOWN** by a machine
   holding a read credential, onto media the owner holds; **the cadence of the pull is
   the window that can be lost.** A second destination in `.env` on this host is
   explicitly **not** a fallback — two keys on one box are two things one seizure takes.

4. **The verification is the owner's, in protocol terms** and needs an administrative
   credential, not the write-only one: `GetBucketVersioning` must say `Enabled`
   (`Suspended` and empty both mean new writes are unversioned), plus
   `GetObjectLockConfiguration` and `GetBucketLifecycleConfiguration` — then the
   empirical check, because a setting can read `Enabled` and not behave: `PutObject`
   twice under one key, then `ListObjectVersions`. **No provider is named anywhere in
   the section**, deliberately: every console names these differently and the protocol
   does not.

5. **Nothing in this tree asserts the retention and nothing ever can** — write-only
   credential, no read path in the product, a bucket in an account this code has no
   standing in. The runbook says so in those words, under *"What this repository cannot
   tell you, and never will"*, so a green `make verify` is not read as a configured
   bucket. **M28.6 must not inflate this.**

6. **`## Backups` now has TWO decision tables.** M28.1's *What belongs in a backup, and
   what does not* is for what goes into an artifact; the new *The retention this host's
   own key cannot reach* is for what the bucket does to it. Extend the right one.

7. **`.env.example` points at the runbook heading by its exact title**, and
   `test_the_env_file_sends_the_operator_to_the_section_that_decides_retention` fails if
   the heading is renamed.

8. **`HASHI_RESTORE_S3_*` still has no consumer in the repository** — verified by grep;
   `.env.example` now says so. Until M28.8 the owner fetches the object with their own
   client. `HASHI_RESTORE_AGE_IDENTITY` is the one a restore really reads.

### How to test what M28.4 built

`make test-infra` (4s, no Docker). The five new tests sit on a `retention_section`
fixture that slices by the exact heading, and `_table_rows()` parses the table into
cells so the verdict column is asserted rather than the prose around it. **No e2e
scenario reads `docs/deploy/runbook.md`** — a words-only change there is fully covered
by the static tier.

### Wording later steps must match

Heading: **"The retention this host's own key cannot reach"** (quoted in `.env.example`).
Pinned sentences: **"nobody loses a backup by mistake"** / **"nobody loses one on
purpose"**, and **"No test in this tree asserts any of the above"**. Verdict cells:
**"Required. This is the mechanism."** and **"Not a retention mechanism."**

## M28.5 — the schedule carries no hour, and a missed day is written down

`make test-infra` 309 passed (was 263, +46); `make verify` green (e2e 203, was 199,
**no skips**). Two review rounds; round 1 found a High that both gates had missed.

1. **The mechanism is ONE cron entry, `*/15 * * * * scripts/backup-run.sh tick`**, in the
   crontab of the account that already runs `make up` (`make backup-schedule`, idempotent,
   no root, no new package, no image). **It carries no hour, and that is the design.**
   `0 4 * * *` is a promise cron cannot keep — a box off at 04:00 misses the minute and
   nothing records that it did. All scheduling lives in the script, so cron's own timezone
   (implementations disagree) decides nothing. **Do not "simplify" this to an hour in the
   crontab.** A systemd timer (`OnCalendar=*:0/15`, `Persistent=true`) is the documented
   equivalent for a host with no `crontab`; an alternative, not the default.

2. **A compose scheduler service was REJECTED and must not be reopened.** It would need
   `/var/run/docker.sock` in a long-running container — root on the host — plus the env
   file, including `HASHI_SECRET_KEY`, `POSTGRES_PASSWORD` and the S3 credential, because
   the dump comes out of `db` and is encrypted in `control`.
   `deploy/warden/docker-compose.yml` already refuses that mount once.

3. **`HASHI_BACKUP_AT` is HH:MM in `HASHI_BACKUP_TZ`, an IANA zone NAME, never an
   offset.** Every wrong value still takes the backup and is recorded: unset → host clock,
   `zone_source=unset` (**no country is ever defaulted to**); unknown or path-shaped zone →
   the same, `unknown`; bad time → `04:00`, `at_source=malformed`. Checked, not assumed:
   **`TZ=Nowhere/Useful date` prints UTC and exits 0**, so the zone is looked up rather
   than trusted — and refused **by name** first (`/*|.*|*/../*|*/..`), because
   `../../../../etc/passwd` names a real file under the zone database and was otherwise
   recorded as a configured zone. Residual, accepted: a symlink inside that root-owned
   database pointing out of it would still pass.

4. **A box that was down takes ONE late run, not one per missed day** — a dump is a copy
   of the database as it is now. The gap days go into `missed_dates` by date and **survive
   the run that ends the gap**; `missed_total` is cumulative.

5. **The record is `backups/state/last-run.json`**, mode 0644, atomic, **one key per
   line** so a shell with no JSON parser can read it. Closed key set, asserted:
   `schema, written_at, at, at_source, zone, zone_source, offsite, due_date, attempts,
   retry_not_before, last_attempt, last_success, last_failure, missed_dates,
   missed_total`. The three nested entries are `{at, due_date, exit_code, outcome}` or
   `null`. **"Has one failed since?" is `last_failure.at > last_success.at`.** `outcome` ∈
   `offsite | on-this-host-only | not-sent | no-artifact | refused`, derived from M28.3's
   exit code plus `HASHI_BACKUP_ENABLED` — **never by parsing output**. **Nothing about a
   person, ever**, asserted statically and against the real fleet in e2e.

6. **M28.6 reads `/var/lib/hashi/backup/last-run.json`** — `deploy/docker-compose.yml`
   mounts `../backups/state` there **read-only**, so the panel reads and the control plane
   can neither invent a success nor erase a failure. **No deploy change needed in M28.6.**
   On a remote daemon the mount arrives empty, which reads as "nothing recorded".

7. **`scripts/backup-run.sh` is the one script that opens the env file**, and may read
   exactly three non-secret names (`HASHI_BACKUP_AT`, `HASHI_BACKUP_TZ`,
   `HASHI_BACKUP_ENABLED`). The whitelist is enforced (`exit 2`) and the reviewer attacked
   it — substring collisions, comment injection, shell expansion — and could not get
   anything to stdout, stderr, the record or a trace. `scripts/backup.sh` still opens
   nothing. **Adding a fourth name is how a secret gets read: don't.**

8. **Exit codes are M28.3's, unchanged and passed through.** `1` is retried hourly, six
   times a day; **`3` is NOT retried** — the artifact is on disk and re-dumping fills it
   with copies of the same database; the remedy stays `make backup-upload FROM=<path>`.

9. **`make backup` now goes through `scripts/backup-run.sh now`.** Same output, same exit
   codes, plus the record — otherwise the panel reports a host as un-backed-up an hour
   after its operator backed it up. It takes the same lock, so `make backup` during a tick
   exits 1.

10. **The read-only mount introduced a root-owned-directory hazard, handled.** A bind
    mount whose source is missing is created by dockerd as root. `make env` and
    `panel-bootstrap.sh` both `mkdir -p backups/state` before any `up`, and
    `ensure_state_dir` refuses **loudly** with the `chown` rather than skipping.

### Round 1's findings — the leading zero, and the zone that was a path

11. **A leading zero is OCTAL to `$(( ))` and to `printf %d`, and it was fatal.**
    `HASHI_BACKUP_AT=08:xx`/`09:xx` — valid, in range, accepted as `configured` — killed
    the tick under `set -e` **before any record was written**, so `missed_dates` never grew
    and the panel would have shown nothing wrong. **Worse than the `malformed` fallback,
    which at least still backs up.** Both gates stayed green because no test picked those
    hours. Fixed with `10#`, and the sweep found the same shape in the integers read back
    **out of the record** (`attempts`, `missed_total`, `exit_code`) — that is what
    `as_number()` is for, because a file on a disk is where a hand edit puts an `08`.
    Checked empirically so nobody re-derives it: **`[ 08 -ge 6 ]` is SAFE** (POSIX `test`
    is base 10) while `[[ 08 -ge 6 ]]` and `$((08+1))` both error; and **no `date +%d`/`+%m`
    reaches arithmetic** — every date is string-compared or handed back to `date -d`.

12. **The env-file secrecy check runs on every invocation, not in one test.**
    `run()` in `tests/infra/test_backup_schedule.py` asserts two planted secrets are absent
    from stdout, stderr **and the record** after each of the 46 calls — and it was proven to
    fire by inserting a deliberate leak. Put new scheduling tests through `run()` and they
    inherit it; a test that calls the script directly does not.

### How to test what M28.5 built

`tests/infra/test_backup_schedule.py` (46 tests, ~7s, **no Docker**). **The seam is the
`due` verb**: it answers "what would `tick` do right now", including `missed=`, and changes
nothing — so every scheduling decision is reachable without dumping a database and without
a test backdoor. Drive it with `seed(state, …)` and `env_file(tmp, …)`, with `ENV_FILE` and
`HASHI_BACKUP_STATE_DIR` in a **stripped** env, as cron would.

**Never let a test touch the real crontab** — the installer's round trip was exercised by
hand; the suite only reads the script's text. **Not proven anywhere, and say so rather than
implying it: that a host's `cron` daemon invokes a `*/15` line.** That needs a wall-clock
wait on a quarter-hour boundary in a privileged container and would prove cron, not hashi.

The e2e `schedule_scenarios()` runs inside the `dumped` fixture **before**
`offsite_scenarios()`, which leave the env file pointing at a torn-down store. Artifacts
land in the checkout's `backups/` and are deleted on the way out, so **read any bytes you
need before the `finally`.**

### Wording later steps must match

Runbook heading: **"When the backup runs, and how you know it did"**. Make verbs:
**`make backup-schedule` / `backup-unschedule` / `backup-status`**. `status` prints **"No
backup has ever been recorded on this host."**, **"last success:"**, **"last attempt:"**,
**"FAILED SINCE THE LAST SUCCESS:"**, **"days with no backup:"**, and closes with **"What
this does NOT say: whether any of those artifacts is still in the bucket."** — **M28.6 must
not inflate that last one.**

## M28.6 — the panel says where the backups stand, and refuses to say more

`make test-control` **945 passed, 2 skipped** against a real Postgres (the 2 are the
long-standing `wireguard declares it cannot carry a hop` pair, **not** the ~670
database skips); `make verify` green, e2e **207** (was 203). Two rounds.

1. **It lives at the top of the Overview, above the four stat cards.** `/panel/` **is**
   the Overview, so a run that did not land is read on the first request of every
   session without anybody navigating — which is the plan's own criterion. **Not the
   Nodes screen** (every row there is about one node; this is about none of them) and
   **not Settings** (a screen you have to decide to open). Above the cards because it is
   the only thing there that can be six weeks out of date.

2. **Freshness keys on the age of the last SUCCESS, not on "has one failed since", and
   this is the load-bearing decision.** A crontab that was removed produces **no failure
   at all** — nothing runs, so nothing fails, and M28.5's own
   `last_failure.at > last_success.at` reads that record as healthy for ever. That is
   exactly the six-weeks case, so it gets its own standing, `silent`, whose sentence is
   *"nothing has failed either — so nothing has been trying"*.
   `SUCCESS_STALE_AFTER = 2 days`: one appointed time missed plus a day of slack,
   boundary-tested at 47h and 49h.

3. **Six standings, two weights, and no third.** `not recorded` / `not readable` /
   `no backup` / `silent` / `failing` use the neutral `.banner` frame with the severity
   in the **label**; a recent success is a muted `.section-note`. **The failure red is
   deliberately not used** — `docs/decisions.md` (2026-09-10) reserves it for a request
   that was refused or failed, i.e. an answer to something the operator just did, and a
   standing condition is not that. The console's banner scan then forces `role="status"`.
   **A blip and six weeks are the SAME standing**, separated only by *"19 hours ago"*
   versus *"43 days ago"* — a banner that shouts on the first failure is ignored by the
   fortieth. Do not add a second colour or a shouting threshold.

4. **`missed_total` is history, never an alarm.** Cumulative, survives the run that ends
   a gap, stated beside a healthy backup, changes the weight of nothing.

5. **The bucket caveat is on all six, the good one included**, rendered outside the
   banner/note conditional, and it opens with the words `make backup-status` closes
   with: **"What this does NOT say: whether any of those artifacts is still in the
   bucket."** Every headline talks about **runs**, never about an artifact existing;
   there is no tick, no green and no colour anywhere in the feature. A test sweeps all
   six for "safe", "guaranteed", "verified", "backed up and", "you are covered" — and it
   iterates the real `Standing` enum, so it cannot be satisfied by a hand-picked string.

6. **The reader never raises and there are exactly two bad answers.** `ABSENT` is
   `FileNotFoundError` **alone** — the empty mount, which means *nothing recorded*, not
   *broken*. `UNREADABLE` is everything else: a directory, a permission, non-UTF-8,
   non-JSON, an unknown `schema`, a nested entry of the wrong shape, or a file over
   64 KiB. Parsing is **strict about keys it reads, silent about keys it does not**, so a
   sixteenth key from a later writer changes nothing. **A damaged `last_success` is
   `UNREADABLE`, not "no backup has ever succeeded"** — same alarm, different reason.

7. **A FIFO at the record path used to hang the front page for ever, and the fix avoids
   the blocking state rather than timing out of it.** `open()` on a FIFO with no writer
   blocks in the kernel and never returns; `asyncio.wait_for` cancels the coroutine but
   the OS thread stays blocked and the executor never drains — round 1 had to `kill -9`.
   The reader now uses `O_RDONLY | O_NONBLOCK` and checks `S_ISREG` via `fstat`
   **before a byte is read**: a FIFO now answers `unreadable` in ~2ms. A `wait_for`
   ceiling (`READ_CEILING_SECONDS = 2.0`) sits behind it for the case `O_NONBLOCK`
   cannot cover — a dead NFS or fuse mount blocks in the VFS regardless of the flag.
   **The residual is written down in the code**: the timeout frees the *request*, not
   the *thread*, because nothing in Python can reclaim a thread blocked in a syscall; a
   private executor was rejected because non-daemon threads joined at interpreter exit
   turn a leak into a shutdown hang.
   `O_NONBLOCK` is a no-op for regular files per POSIX, so there is no truncation risk
   once `S_ISREG` passes — verified on records of 500 B, 28.5 KB and 63.5 KB.

8. **`HASHI_BACKUP_RECORD`** defaults to the mount point
   `/var/lib/hashi/backup/last-run.json`, so nothing need be added to an env file.
   `.env.example` deliberately does not mention it (infra's fence) and the Settings
   screen has no row for it (the backup section already names the file it read).

9. **An unknown `outcome` is named verbatim** — *"the run reported “X”"* — rather than
   turning the record unreadable. The set is closed today; a sixth word must not break a
   screen.

10. **The zone is printed as the IANA name and never interpreted into a place.** No
    country, no flag, no offset. `zone_source` ∈ `configured | unset | unknown |
    no-zone-database` each get their own sentence, because all three failures resolve to
    UTC and the operator fixes a different thing in each.

### How to test what M28.6 built

- **`tests/control/conftest.py` gained a `backup_record` fixture** pointing at a path
  that does not exist, wired into `settings` — so every other test in the zone draws the
  Overview against "no backup has ever been recorded", which is what the field really
  looks like. Override it the way `settle_window` is overridden.
- `tests/control/test_a_backup_that_has_been_failing_says_so.py` (~30 tests, no Docker).
  **`live()` exists because a rendered screen reads the wall clock** — a record pinned to
  a fixed `NOW` reads "42 days ago" in the morning and "43" after lunch, and that flake
  cost a round. Use `live()` in anything that renders and asserts a number.
- The FIFO regression test runs **in a subprocess with a hard timeout**, so a regression
  fails it rather than wedging `make verify`. Keep it that way.
- The e2e scenario writes into the bind-mount source **through a one-off container from
  the stack's own image**, with `--entrypoint sh` and `--user <the directory's uid:gid>`:
  the engine is not always the machine running pytest, and a root-owned file left in a
  checkout is one the real unprivileged schedule could never rewrite. It restores
  whatever was there.

**Nothing mechanically joins the writer to the reader**, and this is the milestone's one
real seam. The reader is pinned to M28.5's closed key set from the control end, the
writer from the infra end, and one test parses a byte-for-byte copy of the writer's
heredoc output — but **no test runs `scripts/backup-run.sh` and then reads the panel**.
Schema drift there would be caught only by a person noticing the two disagree. **Do not
report that seam as covered.**

### Wording later steps must match

Caveat, under every standing: **"What this does NOT say: whether any of those artifacts
is still in the bucket."** Labels: **`not recorded` / `not readable` / `no backup` /
`silent` / `failing`**, and none on the good one. Headlines: **"No backup has ever been
recorded on this host."**, **"Backups on this host are failing."**, **"…so nothing has
been trying."** Outcome clauses are M28.3's pinned words — **"the object store accepted
it"**, **"on this host and nowhere else"**, **"it did NOT leave this machine"**.
