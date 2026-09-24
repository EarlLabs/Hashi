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
   **Narrowed by M28.14:** still two weights and still no third colour, but a gap
   that is *still running* may now take the neutral banner frame and a `missed days`
   label even on a `fresh` standing. The frame moved; the palette did not.

4. **`missed_total` is history, never an alarm.** Cumulative, survives the run that ends
   a gap, stated beside a healthy backup, changes the weight of nothing.
   **Narrowed by M28.14, and read the distinction before you touch either:**
   `missed_total` still triggers nothing — a cumulative number that never falls would
   make a permanent badge, which is §3's own argument against it. What draws a label is
   `missed_recently`, a count over `backups.RECENT_GAP` (8 weeks) that decays to zero on
   its own once the gap ages out. Window, not total. The reader supplies the **count**,
   `console.A_GAP_WORTH_A_LABEL` (5) owns the **threshold** — keep that split.

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

## M28.7 — an env file's own line was reaching cron's mail

`make test-infra` 323 passed (was 309); `make test-control` **957 passed, 2 skipped**
against a real Postgres (the 2 are still the `wireguard declares it cannot carry a hop`
pair); `make verify` green, e2e **210** (was 207). Two rounds. Every surface below was
RUN with both streams captured, not read. **This step touched no document at all.**

1. **THE LEAK, and it was real — reproduced independently at baseline by the reviewer.**
   `docker compose` is the one thing allowed to open the env file, and when it cannot
   **parse** that file it quotes the offending line's whole value back:
   `unterminated quoted value "…"`, `Invalid template: "…"`,
   `unexpected character … in variable name "…"`. `scripts/backup.sh` printed compose's
   complaint so an operator could see which variable was wrong; `backup-run.sh` prints a
   failed run's whole output; cron mails it. **One unclosed quote on the
   `HASHI_SECRET_KEY` line put the master key in `/var/mail/<operator>`, six times a
   day, for as long as the file stayed wrong.**

2. **Fixed with ONE gate, `env_file_must_be_readable`, called from the DISPATCH.** It
   **captures compose's complaint and drops it**, repeating only the env file's path and
   compose's own line number out of a **digits-only `BASH_REMATCH` capture**. The
   reviewer tried to fool that capture with a value embedding the literal text
   `line 999:` inside the unterminated quote; it still reported the real number, because
   compose's `failed to read <path>: line N:` prefix always precedes attacker-controlled
   content, so the leftmost match is structurally the real one. Also tried a 5000-byte
   value and a locale change.

   **What makes it safe is STRUCTURAL and is the property to preserve**: the gate runs
   before any of the three verb functions is entered, so every compose call any of them
   can reach is behind it — however many there come to be. **Do not turn it into a count
   to check against** (the first version of this note said six; the real number is a
   dozen), do not move it inside a verb, and do not "simplify" it to scrubbing at each
   printer. Any other compose refusal — `error while interpolating … required variable X
   is missing a value` — names variables and never values and passes through untouched,
   so an operator with a genuinely missing variable is still told which one.

3. **WHERE CRON'S OUTPUT ACTUALLY GOES, measured in two throwaway Debian containers**
   (never the real crontab). **With an MTA — which Debian's `cron` pulls in by default —
   output is delivered to `/var/mail/<operator>`, mode 0660, and stays there**; the
   `Subject:` carries the crontab command verbatim. **With no MTA it is discarded
   entirely.** The second is not a leak, it is the other failure, and M28.5's record is
   already the channel that does not depend on mail. **Do not add `>/dev/null` to the
   entry** — it would make the mail shape safe and the no-MTA shape permanently silent.

4. **Everything else came back clean.** Stdout is byte-clean on every uploader branch
   (six driven, plus a real 403 XML and a closed port); `RequestId`/`HostId` dropped and
   `<Message>` capped at 200 chars; the one-off containers use `--entrypoint`, so uvicorn
   and its access log never start in one, and `--rm` takes the json-file log with it; the
   control reader's log lines carry the path and the exception's **kind** only. M28
   touched neither `main.py`, `entrypoint.sh` nor the `Caddyfile`, so access logging is
   where M7 left it.

5. **The record's values are structurally independent of the database's contents** —
   dates, exit codes, and three env settings sanitised to `[A-Za-z0-9_+:/.-]` and 64
   characters. That is *why* M28.5's S10d passes against a real fleet, and it is the
   thing to preserve: **a fourth whitelisted name is how a fleet value gets in.**

6. **A restore prints command tags and never a row — and the reason is not ours.**
   `pg_dump --clean --if-exists` puts **`SET client_min_messages = warning;`** in the
   **artifact's** own preamble, so `NOTICE: table "…" does not exist, skipping` never
   reaches the operator, even restoring onto a database with no tables. Measured against
   a real Postgres 16 by two agents independently, and proven load-bearing by stripping
   that one line, which brings the NOTICE straight back. **The first version of this note
   claimed "no table names" as flatly true on reasoning alone**; it happens to hold, for
   a reason nobody here chose — which is why S12 pins the mechanism beside the claim. A
   table name there would **not** be a charter matter (schema names are public, they are
   in this repository's own migrations, and a restore is interactive and never
   scheduled). **A row is the charter matter**, and that is what S12 asserts.

### How to test what M28.7 built

- **`tests/infra/test_the_backup_surfaces_record_nobody.py`** (14 tests, ~1s, no Docker).
  It imports `env_file`, `run`, `seed` and `verdict` from `test_backup_schedule.py` — use
  those, and anything put through `run()` inherits M28.5's planted-secret assertion. The
  `>>` check strips double-quoted literals first, because the crontab block's own
  `# >>> hashi backup schedule >>>` markers are a string the installer **prints**. Known
  limit: it checks for the `>>` token, so a future surface achieving append semantics by
  read-then-overwrite would evade it.
- **`tests/control/…failing_says_so.py`** gained `DISAPPOINTING`, ten damaged records each
  carrying a planted marker, driven through the real `read`. **Add a new give-up branch to
  `backups.py` and add its shape here, or it is unwatched.** The AST walk forbids
  `logger.*` being handed `data`/`raw`/`value`/`record`.
- **`_every_stream(fleet)`** collects both streams of nine runs the fixtures **already
  made** — a dump, four ticks, a `status`, an accepted upload, a refused upload, a refusal
  before the dump — and sweeps them for the live subscription token of the fleet this
  module really dumped. It costs nothing; put new runs into the scenario results and they
  are swept for free.
- **S12 costs no second stack**: it runs LAST inside the `dumped` fixture, on the source
  stack whose database is about to be `down -v`'d anyway — drop the schema, restore into
  it. **The `public` table count is read and asserted `== "0"` first**, because without
  that a silently-failed drop turns the scenario into S1 under another name; the reviewer
  broke the drop to a no-op and confirmed it goes red. Every other restore here goes onto
  a migrated stack, which is why the bare case had never been run.
- **Red-first, all of it**: the gate removed, a stray `echo` on the quiet tick, an append,
  a `print` in the uploader, the secret in `say()`, the file's bytes in a log line, a
  `print` in `_parse` — each watched failing, then restored.

### Wording later steps must match

The gate's refusal opens **"the env file at <path>, at line N, is one compose cannot
read."** and says **"Nothing was dumped, written or sent."** It deliberately does **not**
repeat what compose said; **a step that "improves" it by quoting compose reopens the
leak.**

## M28.8 — one command, two secrets that never meet, three things it will not do

`make test-infra` **351 passed** (was 323); `make verify` green, e2e **214** (was 210).
Two rounds plus one line. Round 1 found M28.7's leak living in a second script.

1. **The command is a FOURTH VERB of `scripts/backup.sh`, never a new script**, and that
   is structural rather than tidy: M28.7's gate runs in the dispatch before any verb is
   entered, so a new verb inherits it and every compose call it can reach — including
   those inside `scripts/panel-bootstrap.sh`, which it invokes — is behind it. **Add the
   next verb the same way.**

   ```
   HASHI_RESTORE_AGE_IDENTITY=… HASHI_RESTORE_S3_ACCESS_KEY_ID=… \
   HASHI_RESTORE_S3_SECRET_ACCESS_KEY=… make restore-from-bucket [OBJECT=<name>]
   ```

2. **The `HASHI_SECRET_KEY` tension is settled in one direction:** that key **does** go
   into `.env` on the rebuilt host — the control plane cannot start or read one credential
   without the right one, and it is the restored machine's own key exactly as it was the
   lost machine's. **The age identity and the bucket's READ credential never do.** Do not
   relitigate this as "nothing carried may touch the host".

3. **The enforcement is a refusal in the shell, and it is load-bearing because compose
   cannot do it — MEASURED, twice, independently.** Compose's short pass-through form
   (`- VAR`) does **not** mean "from the shell only": with `--env-file` an env-file value
   reaches the container exactly as a shell value would. So no shape of the overlay can
   enforce it. The command requires both S3 names in its **own process environment**, so a
   credential only in `.env` is a refusal naming where it belongs. **The script still
   opens no env file** — that invariant was not traded for this check. Residual, stated: a
   credential written into **both** is not detected.

4. **The object is chosen by the STORE's `LastModified`, never by the name.** The name is
   picked by whichever key wrote the object, and on a live control plane that is a key an
   attacker would hold; the store's clock is the one value the lost host had no say in.
   Both are printed. **Listing is PAGED** — a bucket passes 1000 objects in under three
   years and a listing answers lexicographically, so one page of a long history is the
   **oldest** names wearing the word "newest". Verified across two real pages with an
   object named to sort newest and dated oldest.

5. **A damaged artifact is walked past (five deep); a wrong identity is not.** Every
   object was written to the same public half, so walking is a slower way to print the
   same sentence. **Both are verified BEFORE the destructive confirmation** — decrypt,
   `gunzip -t`, identity streamed on stdin, plaintext a pipe and never a file — extending
   M28.2's rule one step.

6. **The four non-secret S3 fields fall back to `HASHI_BACKUP_S3_*`; the two credentials
   fall back to nothing, ever.** Falling back to the write-only key would turn the
   clearest refusal — *"that key may only write"* — into a 403 that reads as the
   operator's own key being wrong.

7. **The install comes BEFORE the bucket is read**, mechanically: the program that speaks
   to the store runs inside this project's control image, which is what keeps a rented
   host from needing anything installed, and there is no image until something builds one.
   It is also what makes the command safe to re-run after any failure.

8. **`git` and `make` are not checked, deliberately** — they are what put the checkout on
   the machine and what ran the command. Only the runtime, the compose plugin and a live
   daemon are, each with its own sentence. **The command does not install a runtime**:
   piping a vendor's script into a root shell on the day of a seizure is not a trade to
   make on somebody's behalf.

9. **`fetch.py` repeats `upload.py`'s SigV4 and cannot import it** — each is a single
   `-c` argument. `test_the_two_programs_sign_a_request_identically` compares **computed
   `Authorization` headers** under a fixed clock, not source text. Fix one and it goes red
   rather than a store refusing a credential during a rebuild.

### Round 1 — the same leak, one script over

10. **`scripts/panel-bootstrap.sh` had M28.7's leak too**, reproduced live: one unclosed
    quote on the `HASHI_SECRET_KEY` line and `compose up -d --build` printed
    `unterminated quoted value "<the master key>"` — and the health-timeout path printed
    it a **SECOND** time through `compose ps`, with a **three-minute wait between them**.
    **The destination is what makes it its own finding**: this is not cron's mail, it is
    the output of a **failed install**, which is exactly what somebody pastes into a chat
    window when asking why their install did not work.

11. **The gate is now ONE implementation in `scripts/lib/env-file-gate.sh`**, sourced by
    both scripts, never copied. Two scrubbers drift. It uses the **caller's own `COMPOSE`
    array** — a test asserts the body contains `"${COMPOSE[@]}" config --quiet` and **no
    literal `docker compose`**, proven by injection — and refuses loudly if sourced
    without `ENV_FILE` and `COMPOSE`, blaming the script that sourced it rather than the
    operator. `ENV_GATE_NOTHING_HAPPENED` is the one per-caller sentence.
    **Position, not a count, in both**: the dispatch in `backup.sh`, the top of section 1
    in `panel-bootstrap.sh`. A test walks every `"${COMPOSE[@]}"` occurrence and requires
    each to follow the call site — proven by moving one above it.

### Round 2 — the audit that said it had looked

12. **`SURFACES` existed and one test iterated its own copy.** The shared gate joined
    `SURFACES`, but `test_no_backup_surface_appends_to_anything` walked a separate
    `(BACKUP, RUNNER, INSTALLER)` — so the one file both scripts now depend on for exactly
    this class of finding was swept for a log destination and **never for an append**.
    Nothing leaked; **the audit claimed coverage it did not have**, which is the shape that
    rots quietly. Now one list, with the uploader excluded by a **stated reason in code**
    (`>>` is a shell redirection; in Python it is a right shift), and the loop closes by
    asserting **what it actually swept**. Proven red-first, and the old tuple confirmed
    blind to the same plant. **Add the next surface to `SURFACES`; do not build a second
    list.**

    *This last line landed on the reviewer's own verbatim prescription after round 2
    returned clean, and was not independently re-reviewed. It changes one test's iteration
    target and nothing else.*

### Not proven, and do not imply otherwise

- **No single invocation does install-from-nothing AND fetch.** The disposable store lives
  on the source stack's network and the rescue project's network does not exist until
  something creates it, so S13 runs the command **twice**: run one installs from zero and
  then fails at an endpoint that does not resolve (a real failure mode, asserted); the
  store is connected to the network run one created; run two does the real
  list/fetch/open/restore.
- **The four-field fallback to `HASHI_BACKUP_S3_*` is unit-tested only.**
- **`OBJECT=` and the damaged-artifact walk are asserted statically only.**
- **Nothing here runs on a genuinely bare host** — M28.9 is that walk, and the three
  runtime refusals are text assertions, not exercised.
- Retention and "the object is still there" remain M28.4's *"What this repository cannot
  tell you, and never will"*. M28.8 did not widen it.

### How to test what M28.8 built

`tests/infra/test_the_restore_comes_from_the_bucket.py` (26 tests, no Docker) imports both
`fetch.py` and `upload.py` with `importlib` and runs them in-process against a fake store.
**Use a genuinely public address in any http test** — Python marks `198.51.100.0/24` and
`203.0.113.0/24` as private, so a test written with one of those passes whatever the code
does.

S13 is a **third** compose project whose env file names no object store at all. The fetched
artifact lands in the checkout's `backups/` — read what you need before the `finally`.
**Disconnect the store before `down -v`** or the rescue network survives teardown.

### Wording later steps must match

**`make restore-from-bucket`**, **`OBJECT=<name>`**. Runbook headings **"Coming back from
the bucket, on a machine that has never run this"** and **"What `make restore-from-bucket`
does not do"**. Pinned: **"the artifact is intact; the identity is wrong."** (echoing
M28.6's *"The data is intact; the key is wrong."*, which the closing screen quotes verbatim
for the one failure the command cannot see), **"A restore needs a credential that may LIST
and GET this bucket"**, **"The credential works — this is the bucket or the prefix"**,
**"Nothing was fetched and nothing was changed"**, and the closing **"Three things it did
NOT do"** naming DNS, the certificate and **"Telling anybody"**.

## M28.9 — the restore, performed on real hosts

**It works.** A control plane built on the Russian box and killed without a graceful
stop came back on a machine that had never run this project: one command plus the three
carried inputs, the existing node applied from the rebuilt panel in **3.8s**, and the
existing user's subscription returned **byte for byte identical** — same token, same
path, `sha256 14b0d1fb…`, 336 bytes, compared before and after. Honest bare-host total
**≈2m 05s**.

1. **The two layers do exactly what the plan says.** A bucket reader gets
   `age-encryption.org/v1` and `no identity matched any of the recipients`. The decrypted
   dump has **the leaf address in the clear** — the address M28.2 exists to cover — and
   the subscription token **0 times**, because that column is encrypted. Both halves
   confirmed on a real artifact.
2. **The scheduled path fired unattended at the appointed minute** and recorded
   `outcome: offsite`, `missed_total: 0`. The panel said so immediately. Nobody expected
   to avoid falling back to `make backup`, and it was not needed.
3. **The three inputs are distinguishable when wrong**, tested by breaking each: a wrong
   identity says *"the artifact is intact; the identity is wrong"* and **stops**; the
   host's own write-only key says *"A restore needs a credential that may LIST and GET
   this bucket … no key on the lost host was ever the right one"*; no credential at all
   refuses **before installing anything**. A wrong `HASHI_SECRET_KEY` cannot be seen by
   the command and is deferred to the panel's own sentence, as designed.
4. **The three things it says it does not do were confirmed by observation**, not by
   reading: DNS still pointed at the destroyed box; with the name forced at the new host
   TLS aborted **even with verification disabled**, because no certificate for that name
   exists there and cannot until DNS moves; and nothing anywhere touched
   `scripts/notify.sh`.
5. **The charter held on the live deployment**: the token appears **0** times in any
   container log and **0** times in Docker's on-disk JSON logs, `/sub/` **0** times, ufw
   `LOGLEVEL=off` with no `ufw.log`.

**What this walk cannot prove** — a disposable MinIO store the walker stood up, on a host
they control, with keys they minted. It proves the command, the credential split, the
artifact and the age layer. It proves **nothing** about the owner's Yandex account, its
retention, its object lock, its write-only key, or whether it is reachable from inside
Russia on the day it is needed. The VM was not deallocated (no cloud API): destruction was
SIGKILL plus removal of containers, volumes, images, the checkout and the env file. Three
roles were collapsed onto two machines. **And nothing here says anything about surviving a
Russian mobile whitelist shutdown.**

## M28.10 — what the walk found, answered where the operator is standing

`make test-infra` **379 passed** (was 351); `make verify` green, e2e **220** (was 214).
Six findings, one diff, `control/` untouched.

1. **`make hash-password` → `scripts/hash-password.sh`, and it must stay compose-free.**
   Plain `docker build -f deploy/docker/control.Dockerfile` then `docker run --entrypoint
   python3 … -m control.cli hash-password`. **No `docker compose`, no `--env-file`, no
   `.env` anywhere** — asserted — because the env file is what this command exists to help
   fill in, and every base-stack interpolation carries a `:?` guard. That ordering is the
   whole trick: the image builds from a checkout that needs no `.env`.
   **Correction from round 1:** stdout is **not** "the line alone" — it is
   `control/cli.py`'s whole block. What the redirection buys is that **nothing the script
   emitted** lands among it. Claim it that way; a line count is a checkable claim about a
   file outside this fence, and the first version of it was false.
2. **A non-empty placeholder passes a presence check.** `panel-bootstrap.sh` now refuses
   an env file whose hash is still `.env.example`'s own placeholder line, **read out of
   `.env.example`** so the two cannot drift. Without it the failure surfaced 180 seconds
   later as a health-check timeout about a container.
3. **The destructive confirmation is measured, not asserted.** `rows_at_stake()` counts
   `public` base tables via `information_schema` + `query_to_xml`, excluding
   `alembic_version`, and **names no table of ours**. Zero rows → says so and asks
   nothing; rows → asks, stating the count, so *"every current node, user and credential
   is overwritten"* is only printed when true; unreadable → treated as rows, the safe
   direction.
4. **`no_terminal_refusal` fires in two places and the second is the point** — in
   `command_restore` before `read -r`, and in `command_restore_from_bucket` **after the
   install and before the bucket is read**, the earliest moment a database exists to
   count. `FORCE=1` is named in the refusal. **The e2e rescue run no longer passes
   `FORCE=1`, and that absence is the assertion**: no tty, `stdin=DEVNULL`, and it
   succeeds because a fresh control plane holds no rows.
5. **`make restart-control` is what a restore ends with** — never `make down && make up`,
   which converges a deployed stack to the base shape and unpublishes it.
6. **The deployed publication is TWO overlays now**: `public.yml` (80/443 + console on
   loopback) and `tunnel.yml` (console on `HASHI_PRIVATE_BIND_ADDR`). `make up-panel` =
   both, **meaning unchanged**; **`make up-panel-over-ssh`** = the first alone, for a host
   with no tunnel, which is every host a restore just rebuilt. `tests/infra/test_compose.py`
   iterates `PANEL_OVERLAYS` — **add a third overlay to that list, do not start a second
   one.**
7. **A restored fleet is an unbacked-up fleet, and the closing screen now measures it**
   with the same `config --quiet` a dump makes, compose's complaint discarded per M28.7.
   The write-only key and the age recipient lived only in the lost `.env`, which is
   deliberately not in the backup.
8. **A backtick inside an unquoted heredoc is EXECUTED.** The wrong-identity diagnostic was
   running `age-keygen` at an operator on a host that has none. Escaped, and a sweep now
   covers every `scripts/**/*.sh`. Its parser needs `(?<!<)<<(?!<)` — `backup-schedule.sh`
   prints `# <<< hashi backup schedule <<<`, and a parser without that guard swallows the
   rest of the file and sweeps nothing. It did, first try.
9. **One existing guard was loosened, knowingly**: the provider check strips the literal
   `127.0.0.1` so the closing screen can print an `ssh -L` line. Loopback names no host and
   rotates nowhere; every other dotted quad still fails, verified.
10. **`docs/decisions.md` may be SHARPENED in place by the step that wrote the row, while
    that step is still in review** — the file's own header says so at lines 15-21, dated
    2026-09-11, *"so it stops being re-derived by whoever next feels reasonable"*. It does
    not trip the record check, because the row did not exist at the baseline. After
    acceptance it is append-only like every other row.
11. **A test whose name states a property it does not check is this repository's most
    recorded defect** — caught here for the third milestone running.
    `test_the_build_and_the_prompts_stay_off_stdout` now sweeps eight real strings from
    three noisy sources and asserts each appears on **stderr**, so it cannot pass by
    nothing having been printed.

### Not proven by any suite, and do not imply otherwise

Findings 1–4's field halves: that a bare Ubuntu host runs `make hash-password` with
nothing installed, that `make up-panel-over-ssh` binds on a machine with no tunnel, that
`ip addr add` is no longer needed. **And nothing asserts `make restart-control` is
sufficient after a restore** — it restarts the process; no test then reads the panel.

## M28.11 — the panel must not say a backup left the machine when it did not

`make test-control` **971 passed, 2 skipped** against a real Postgres (the 2 are the
long-standing `wireguard` pair, not the ~670 database skips); `make verify` green, e2e
**222**. Acceptance blocked on three panel findings; a second bare-host walk added a
fourth mid-step.

**Note on the diff:** half of it (`control/app/services/backups.py`, the new e2e file) is
in `4175562`, a *plan* commit that swept in work in progress because the coordinator ran
`git add -A` while the implementer was editing. Nothing was rewritten. **Read this step by
path — `git diff bc43f59..HEAD -- control/ tests/control/ tests/e2e/control/`** — not by
commit.

1. **The root cause was a dropped field, and the reasoning for dropping it was true
   only conditionally.** `Record` deliberately omitted the record's top-level `offsite`,
   its own docstring saying *"it is already in every run's `outcome`"* — which holds only
   while the outcome is one of the five known words. With an unrecognised word (`"ok"`)
   the panel had **no source at all**, and the two screens could not differ. **A field
   dropped because another field implies it is a field that stops being implied.**

2. **THE CAVEAT IS NO LONGER ONE CONSTANT — it is three, keyed on where the HOST sends,
   never on the standing.** `console.BACKUP_CAVEATS[Destination]`, public because tests
   sweep it. `BACKUP_NOT_THE_BUCKET` is byte-for-byte unchanged and is now the `OFFSITE`
   one only. M28.6 §5's *"the bucket caveat is on all six"* is **superseded**: what is on
   all six is *a* caveat, and all three end with the identical clause **"The only thing
   that proves a backup is a restore"**.

3. **The two claims are different and both are said.** Whether a run reached a store **at
   all** is something this host recorded — and it was being thrown away, with
   `HASHI_BACKUP_ENABLED=0` as the shipped default, so by default the screen talked about
   a bucket that does not exist. Whether the artifact is **still there** is refused
   exactly as before. **Do not merge them back.**

4. **`Destination` is `OFFSITE` / `THIS_HOST` / `UNKNOWN`, and `UNKNOWN` collapses into
   neither.** Guessing "offsite" is the original bug; guessing "this host" denies a
   working upload. An unrecognised `offsite` *word* is `UNKNOWN`, not `UNREADABLE`
   (`outcome`'s precedent); a record **missing** the key is `UNREADABLE`, because it is
   now a key this reader reads.

5. **The caveat is phrased about the HOST, not the run above it.** A run whose outcome is
   `offsite` under a host whose `offsite` is now `no` is a switch thrown between two runs,
   not a damaged record — and a caveat saying "none of this left the machine" would
   contradict a true sentence directly above it.

6. **NONE OF THE THREE CAVEATS CONTAINS AN APOSTROPHE, and that is not style.** Jinja
   autoescaping makes it `&#39;`, so a constant carrying one cannot be asserted verbatim
   against a **rendered page** — and asserting against the composed object instead is
   exactly the test that would not notice a template dropping the line. The screen-level
   assertions go through `client.get("/panel/")` and read `.text`, which is the class of
   test that catches what acceptance caught. **Keep new caveats apostrophe-free.**

7. **`missed_dates` is sorted NEWEST FIRST in the reader, and the invariant belongs to the
   type.** The panel labels the first few "most recent" and used to trust the writer's
   order, which during a live gap pointed six weeks back. Validated `YYYY-MM-DD` **before**
   the sort, so text order is date order. The writer should sort too (M28.12) — **not
   sufficient**, because the record is a file on a disk where a hand edit goes.

8. **A future timestamp: the clamp stays, the sentence changes.** `_age` still clamps — a
   disagreeing clock must not turn a stale backup fresh or the reverse — and
   `success_ahead` / `failure_ahead` carry what the clamp hides, per-run because the screen
   prints two ages in two sentences. `CLOCK_AHEAD_GRACE = 1 minute`: writer and reader
   normally share one kernel clock. **`FRESH` goes loud with the label `clock ahead`** —
   it is the only quiet standing and therefore the only place this could hide for ever.
   **Not a seventh standing and not a second colour**: `Standing` is still exactly six, and
   every other standing keeps its own label and merely gains the clause.

9. **The panel's advice must be true on the machine the panel is running on.** The
   "nothing recorded" state named `make backup`, which **refuses** on a host restored out
   of the backup history — the age recipient and the S3 key were in the `.env` that is
   deliberately in no backup. **The panel cannot tell that host from one where the schedule
   was never installed** (a record is all it reads) and does not try: it leads with
   `make backup-status`, which runs either way. **It deliberately does not borrow the
   restore screen's wording** — that screen ran on the host and *measured* the recipient,
   so it is entitled to a verdict; this reads one file and is not. A test asserts the panel
   never says *"NOT backing anything up"*.

### How to test what M28.11 built

Same fixtures as M28.6, plus `record(offsite=…)` and `run(-N)` / `live(-N)` for a
timestamp N hours in the **future**. **`test_every_standing_and_every_destination_closes_with_a_caveat`
iterates the real `Standing` × real `Destination`** — a seventh standing or a fourth
destination is covered free and cannot be satisfied by a hand-picked pair. **Two field-list
assertions pin `Reading` and `Record` name-for-name**, so a field added to either fails
there first, on purpose: a value crossing from a file into a rendered page has to be
justified. The screen-level regression writes the same record twice differing only in
`offsite` and compares the two **rendered pages**, because byte-identical pages is what
acceptance observed and an assertion on two standings would not have seen it.

**The infra zone guards the runbook's `### When the backup runs…` section against
containing a table.** A first draft added one and `make verify` caught it. **Write prose
there, not a table.**

### Wording M28.12 must match, or the two channels disagree

Caveat openings: **"What this does NOT say: whether any of those artifacts is still in the
bucket."** (upload on) / **"What this does NOT say: that this host is sending its backups
anywhere."** (upload off) / **"What this does NOT say: whether anything was sent
anywhere."** (cannot tell). All three close with **"The only thing that proves a backup is
a restore"**. Future timestamps read **"at a time that had not come yet when this was
read"** under the label **`clock ahead`**. The restored-host advice says **".env is in no
backup by design"** and **"make backup refuses there"**, leading with **"start with make
backup-status"**.

## M28.12 — the command line must not be more confident than the panel

`make test-infra` **426 passed** (was 379); `make verify` green, e2e **222** — the first
independent run of M28.11's two new scenarios. Two rounds; round 1 found a High that
reopened the very bug this step closed.

1. **`make backup-status` applies the panel's rules key for key** — unknown `schema`, a
   missing key it reads (`offsite` included), a malformed timestamp/count/date, a nested
   entry that is not a run, any string over 200 characters → refuses, **naming the field
   and never its contents**, exit 1. Verified with acceptance's own inputs: `schema: 99`
   and a 1000-character `outcome` carrying `<script>` are both refused with the field
   named and nothing echoed. **Still readable on both sides**: an unknown `outcome` word
   (named verbatim) and an unknown `offsite` word.

2. **The three caveats are pinned to `control/app/services/console.py` from the infra
   zone**, and the pin parses rather than greps: `panel_caveats()` uses `ast` to read
   `BACKUP_CAVEATS` and follow each value to its constant. A substring search over the
   file would pass on a sentence sitting in a comment — **proven, by moving one there and
   watching the test fail.** The cross-zone *read* was judged legitimate (precedented by
   `test_node_bootstrap_agrees_with_the_control_plane.py`); it buys two channels that
   cannot drift about whether an operator's backups are safe.

3. **The caveat is chosen by the RECORD's `offsite`, never the live env file**, though
   this channel can read both. Where they disagree it says so in one extra line — the one
   fact the panel cannot have, additive rather than a different verdict.

4. **`missed_dates` is stored NEWEST FIRST by the writer** (`sort -r` + `head`). Both
   readers still sort: M28.11's reason stands, a record is a file a hand edit reaches.
   `due`'s `missed=` stays chronological — it is a walk of the gap, not the record.

5. **A compose refusal is attributed to the variable compose named.**
   `missing_value_advice` captures `required variable X is missing a value` as a bare
   identifier — the reviewer attacked it with odd characters, an embedded name, two
   variables, a multi-line refusal and near-miss names and **could not defeat it**. The
   `age-keygen` page appears only for `HASHI_BACKUP_AGE_RECIPIENT`; any other name gets
   *"THIS IS NOT ABOUT YOUR BACKUP KEYPAIR"* and why a new pair orphans the store.

6. **`compose ps --format json` has THREE answers.** Empty with exit 0 is a real
   "publishes nothing"; a non-zero exit is **"could not tell"** and is said out loud before
   the converge and again on the closing screen. `|| true` is gone and a test pins that it
   has not come back — silence is the failure the warning exists to prevent.

7. **A management tunnel is never generated from `.env.example`'s own values**, compared on
   three keys because an address range is a value somebody could really choose. **Skipped,
   not refused** — a restored host must not be stopped by it.

8. **Everything a restore prints is on stderr**; the closing screen reads the private port
   from the **caddy** container, since that port is Caddy's, not control's.

### Round 1's High, and the class it belongs to

9. **Three whole-line comparisons of operator-written text existed, and all three are
   closed — plus a fourth thing that was not a comparison at all.** `mgmt_is_the_template`
   and the placeholder-hash refusal both compared **lines** for equality, which a **CRLF
   env file** (edited on Windows — an ordinary thing to do while rebuilding from a laptop)
   and a **quoted value** each defeat. The first generated a tunnel out of the template and
   printed two fabricated device private keys — **the exact bug this step exists to
   close**; the second let an unfilled hash through and returned M28.10's three-minute
   health-check timeout. Both now compare **values** through **`env_value_of`**, defined
   once beside `has_value` and applied to **both** sides. `raw_field` in the record
   validator strips `\r` for the same reason.

   **The fourth was the real lesson**: `HASHI_PRIVATE_BIND_ADDR` had its own weaker parser
   in the same file — first assignment instead of last, double quotes only, no `\r`, no
   comment strip. **The defect was never one bad comparison; it was a second parser that
   gives the right answer on every file anybody tests with.** There is now **exactly one
   env-file value parser in `panel-bootstrap.sh` and a test enforces it**, proven red-first
   by planting a second one. `backup-schedule.sh`'s `$0 ==` compares markers **it printed
   itself** and is not this shape.

10. **Known and deliberately not fixed here — now M28.13.**
    `scripts/management-tunnel.sh::value_of` is the same weak parser (no `\r` strip,
    first-assignment-wins). On a CRLF-edited, **genuinely configured** `.env` it splices a
    carriage return into `Endpoint = <host>^M:<port>^M`, `Address`, `ListenPort`, `MTU` and
    the last peer's address — in the host's own `awg-mgmt.conf` **and in every device
    config an operator pastes onto a phone**. Reproduced, not inferred. Different failure
    class from the High (config corruption of a real tunnel, not a credential leak) and it
    has its own 435-line suite, so it wants its own red-first test.

### How to test what M28.12 built

`tests/infra/test_the_command_line_says_what_the_panel_says.py` (no Docker). It imports
`env_file`, `run`, `seed` from `test_backup_schedule.py`, so every status invocation
inherits M28.5's planted-secret assertion. `record_text(**fields)` writes a record in the
writer's own layout with fields overridden **verbatim** — the seeded JSON must be one key
per line or the shell reader is right to call it damaged. `advice(refusal)` and
`sliced()` + `drive()` slice functions out of the scripts and **run** them, which is how
the three advice branches and both template checks are exercised without Docker.

## M28.13 — the same weak parser, in the script that writes the tunnel

`make test-infra` **426 → 431 (+5)**; `make verify` green, e2e **222**. The builder
reported the baseline as 427 and the delta as +4; the reviewer measured the baseline twice
on a clean worktree and it is **426**. **The fifth test is
`test_no_operator_facing_heredoc_runs_a_command[env-value.sh]`** — a pre-existing
parametrised sweep over `scripts/*.sh` + `scripts/lib/*.sh` that picked the new library up
by itself. Recorded precisely because the notes are what later steps trust, and 427 would
be exactly the class of wrong record M28.10 and M28.12 exist to catch.

1. **There is now exactly ONE env-file value parser in this repository**:
   `scripts/lib/env-value.sh::env_value_of FILE KEY`, sourced by `panel-bootstrap.sh`,
   `management-tunnel.sh` and `backup-run.sh`. **Extracted, not copied a third time** —
   M28.12's lesson was that the defect is a second parser, so fixing the second by writing
   a third would have missed it. The guard test moved from "this script" to "this
   repository" and was **proven by breaking it twice**: a planted second definition and a
   planted raw `sed` each fail it by name.

2. **The file is an ARGUMENT, not the caller's `ENV_FILE`**, unlike
   `scripts/lib/env-file-gate.sh`. Deliberate and judged right: the gate *drives a command*
   with the caller's own compose set, while this is pure extraction — and
   `panel-bootstrap.sh` must read **two different files** (`.env` and `.env.example`) with
   the same parser, which an implicit caller-variable convention would make actively wrong.
   Cost, stated: a future library copying the gate's shape will not compose with this one.

3. **`backup-run.sh`'s three-name whitelist did NOT follow the extraction out.** It stays
   in the script it constrains, structurally in front of the call, and a test pins that
   `exit 2` precedes `env_value_of` inside `env_value()`. **Attacked and held**: a planted
   `env_value HASHI_SECRET_KEY` refuses with exit 2 and prints nothing of the file. The
   library has no whitelist of its own **by design** — a shared reader holding every
   caller's fence is one place to get them all wrong at once — and every other call site
   passes a hardcoded non-secret key literal, never a variable.

4. **Reading `\r` changed for `backup-run.sh` and no caller's value did.** Its old copy did
   not strip `\r`; the library does. All three call sites pass through `sanitised()`, whose
   `tr -cd 'A-Za-z0-9_+:/.-'` allowlist never admitted a carriage return. **That is the
   proof, not the green suite.**

5. **What was actually corrupted, reproduced byte-exact at baseline with `cat -A`**:
   `Address = 10.77.0.1/24^M`, `ListenPort = 51821^M`, `MTU = 1420^M` in `awg-mgmt.conf`,
   and `MTU = 1420^M` plus `Endpoint = panel.invalid^M:51821^M` in **both printed device
   configs** — the ones an operator pastes onto a phone.

6. **The plan's peer-address claim was FALSE and is corrected here.**
   `PEER_SPECS=(${MGMT_PEERS})` does glue `\r` to the last spec, but the loop's
   pre-existing `tr -d '[:space:]'` removes it, because POSIX `[:space:]` includes CR.
   Confirmed at baseline as well as at HEAD. The test keeps the assertion as a **pin**, not
   as a fix.

7. **`text=True` HIDES the byte this step is about.** Python's universal-newline decoding
   turns `Endpoint = panel.invalid\r:51821\r\n` into two separate lines and `'\r' in
   stdout` reads **False** — verified. The suite's `run()` grew `raw=True`, and the CRLF
   scenario uses it, plus `read_bytes()` for the conf. **A test that decodes cannot see
   this defect**, which is worth remembering for any assertion about bytes.

8. **The operator-facing contract is untouched.** No refusal text, progress line or
   device-config layout changed; the generated `awg-mgmt.conf` holds exactly one
   `PrivateKey` — the host's own — and peer stanzas carry only `PublicKey`/`PresharedKey`.
   The script still prints each device's private key once and stores none.

### How to test what M28.13 built

`tests/infra/test_management_tunnel_script.py::edited_env(tmp_path, transform, **overrides)`
re-saves the suite's own complete env file through a text transform and writes it as
**bytes** — `write_text` would translate the line ending back.
`lambda t: t.replace("\n", "\r\n")` is the Windows editor. **Use `run(..., raw=True)`
whenever the assertion is about a byte.** Red-first was real: **3 failed, 1 passed**, and
the one that passed (quoted values) did so *before* the fix — the old parser already
stripped quotes, which was reported rather than counted as a win.


## From M28.14 — the panel stopped promising a schedule it cannot see

**Pinned wording. The panel may not say a backup is taken; only that one would be due.**
*"A run would be due at {at} {zone}."* / *"That is the time the schedule would use if one
is installed"* / *"so it cannot tell you whether anything on that host is taking these
backups at all."* The `never` standing's opening was corrected the same way. A test,
`test_no_standing_says_a_backup_is_taken_daily`, sweeps every standing that has a record,
so a new standing cannot quietly reintroduce the claim.

**Why the panel is not allowed to just go and look.** It renders from the one record it
already reads: no subprocess, no crontab, no I/O. The record is written by the *run*, so
it cannot attest that a *schedule* exists either — which is why M28.14 was forbidden from
adding a `schedule_installed` field and told to say less instead. If a later milestone
wants the panel to state a schedule as fact, something that actually knows has to write
it down first. `test_nothing_this_panel_says_about_the_schedule_needs_a_second_source`
builds the sentence from a hand-made `Reading` and holds that line.

**New label `missed days`**, alongside `not recorded` / `not readable` / `no backup` /
`silent` / `failing` / `clock ahead`, which still wins where both apply.

**`backups.Reading` gained `missed_recently`**, between `failed_since` and
`success_ahead`. The name-for-name field pin in
`test_the_reading_that_reaches_a_screen_carries_no_request_and_no_person` was updated
with it; a further field has to be justified there first.

**`RECENT_GAP` is 8 weeks on purpose:** longer than the 30 dates
`scripts/backup-run.sh` retains (`MISSED_KEPT=30`, newest-first), so the count can only
ever undercount a long gap, never exaggerate one.

**A good run can now be loud.** `fresh` with a label is the first standing where a
*successful* last run draws a banner. Anything testing `loud is False` or `label is None`
as "the backups are fine" is wrong — **test the standing, never the frame.** Nothing in
the tree did that when M28.14 landed (swept: the only consumer of either is
`control/app/templates/panel/overview_body.html`), but `scripts/backup-status` mirrors
these rules and does **not** have this label, so the two channels differ in weight on the
same record until an infra step closes it.

**How to test dates that reach a screen.** `days_before(count, ending=…, base=…)` in
`tests/control/test_a_backup_that_has_been_failing_says_so.py` builds consecutive missed
dates. **Pass `base=datetime.datetime.now(datetime.UTC)` for anything that renders a
page** — a rendered page reads the wall clock, so dates pinned to the fixed `NOW` age out
of the window and the test then fails on a calendar rather than on a change. Same trap
`live()` exists for. `_every_standing_with_a_record()` sweeps a claim over all four
branches that have a record.

**Red-first was argued, not observed, and that is a gap in the record rather than in the
substance.** The two new e2e scenarios assert strings that did not exist before the fix,
and the reviewer confirmed against the baseline source that neither can pass at
`12f79a5` — but nobody watched them fail in a reverted tree, because that costs a third
12-minute stand cycle. Said plainly here so the next reader is not told a check happened
that did not.


## From M28.15 — the command line stopped promising a schedule, and one file stopped giving two answers

**The command line may look; the panel may not.** `scripts/backup-schedule.sh show` gained a
third exit code — 0 installed / 1 no entry / **3 no `crontab` on this host** — and
`backup-status` prints one of three answers from it. The old single line split in two, and
the split is the point: **`scheduled:` is about the crontab, `appointed:` is about the env
file.** They answer different questions and used to be one sentence, which is how a host
with no schedule was told a backup is taken daily. The family now agrees: install →
`scheduled: yes`; `make backup-unschedule` → its own "removed…" and the next
`backup-status` says `NO`, byte-identical to a host that never had one.

Operator-facing wording acceptance will judge: `scheduled:    yes` / `scheduled:    NO —
nothing on this host takes a backup.` / `scheduled:    NOT KNOWN — this host has no
\`crontab\`…`; `appointed:    <at> <zone> (<source>), whenever something runs it` followed
by `— from <env file> as it is now, not from this record`.

**`due` refuses a damaged record**, exit 1, naming the key, printing no `action=` line at
all — through `refuse_damaged_record`, **one function shared with `status` so the two
cannot drift**. `due`'s line is `action=… clock=ok|ahead due=… …`, with `clock=` second,
right after the verdict it qualifies. Cron runs `tick`, never `due`, so the exit-code
change reaches no scheduler.

**`HASHI_BACKUP_ENABLED` has one source: the env file.** The upload compose invocation is
wrapped in `env -u HASHI_BACKUP_ENABLED` so a value in the calling shell cannot outrank it;
`--env-file` is intact and compose's own interpolation is the fallback. No third precedence
rule was invented, and none should be.

### The pipe, and why the fix is one character wide

Readers used to do `printf '%s\n' "${RECORD}" | grep -q …` under `set -o pipefail`. Past
the 64 KiB pipe buffer `grep -q` exits on its first match, `printf` dies of SIGPIPE, and
pipefail turns 141 into failure — **so a key that is present is reported absent**, and the
script then accuses the operator of a damaged record while naming a key whose value is
perfectly valid. Measured on one unchanged file: `0 0 1 0 1 0 0 1 1 0 1 1`, six refusals
naming four different valid keys; after the fix, 60 consecutive runs, one md5.

**All five readers take a herestring** (`grep -q … <<<"${RECORD}"`). **Never reintroduce a
pipe over `${RECORD}`** — `test_no_reader_of_the_record_feeds_it_through_a_pipe` is
structural for a reason worth understanding: at the baseline it failed 4 times out of 4,
while the *behavioural* race test failed only 3 times out of 4. A behavioural test for a
race passes on the run where the race does not fire, so the deterministic guard is the one
that holds the line.

**The window is narrow and that is why every earlier test was green.** The trap needs the
*canonicalised text* over the pipe buffer, not the file: 2000 missed dates (26 KB text) →
0/15 flakes, the race cannot fire; 4900 dates (64 187 bytes on disk, 69 162 of text) →
flaky; 6000 dates → over the ceiling and deterministically refused. Every shipped test
before this used sub-kilobyte records. `A_LEGAL_RECORD_THIS_BIG` and
`ENOUGH_RUNS_TO_SEE_A_RACE = 12` exist to keep a regression test inside that window.

### The ceiling, and the one behaviour change on the writing path

A file over `MOST_OF_A_RECORD` (65 536) is **refused whole, naming `size`, with none of it
read** — matching `control/app/services/backups.py`, which refuses any file over the same
number unconditionally. The rejected alternative is written down because it is tempting:
reading the first 64 KiB and judging *that* is a verdict about a file nobody has seen all
of, and a file whose opening happens to parse would be read out as fact.

**Consequence, and it is not new:** `tick`/`now` get an empty `RECORD` for an over-large
file, treat it as *no record*, take a backup and overwrite it. The baseline destroyed that
file too — it read the first 64 KiB and **salvaged** `last_success` and 30 missed dates out
of it into a small, valid, authoritative record. The change is that the replacement no
longer launders unverified bytes into an assertion. `STATE_DIR` comes from the **process
environment only** and is not among the three names the script takes from an env file, so
no env-file typo can redirect it, and the write is `mkdir -p` + `mv` to a file named
`last-run.json` — it cannot truncate a file an operator named.

### Two corrections to earlier claims, kept because both were wrong in the same way

**The record reader does NOT refuse unknown keys, and must not.**
`control/app/services/backups.py::_parse` ignores them *by documented design* — "a later
version of the writer adding a sixteenth key must not make this panel go unreadable" —
so teaching the shell to refuse them would manufacture the exact two-channels-disagree
defect this step exists to close. The closed 15-key set is enforced on the **writer**, by
`tests/infra/test_backup_schedule.py::RECORD_KEYS`. An instruction in M28.15's brief said
otherwise; the instruction was wrong and was withdrawn.

**`tick`'s lenient read does not always self-heal.** A damaged `last_attempt` self-heals
when the due date rolls over. **A `due_date` ahead of the clock does not:** `tick` exits 0,
prints nothing, and waits until the calendar catches up — verified with `2099-01-01` — on
the channel that actually takes backups, while `due` exits 1 and the panel draws a banner.
That is the accurate version of the sixth surface.


## From M28.16 — the identity-map trap, and the switch that makes it deterministic

**The rule, for any new test in `tests/control/` that uses both `client` and `session`:**
if a helper or fixture touched the row through `session` before the request under test,
call `session.expire_all()` **before every read**, not just the second one. The long
explanation lives under `fleet_with_user` in `tests/control/test_revocation_push.py` —
point at it rather than re-deriving it.

**The mechanism, confirmed against the code rather than assumed.** Fixtures call
`nodes.set_node_state` through the *test's own* session; `Node.transports` is
`lazy="selectin"` (`control/app/models/node.py:257`), so every `NodeTransport` lands in
that session's identity map with `applied_digest=None` before any apply runs. Sessions are
built `expire_on_commit=False` (`control/app/db.py:41-42`), so a later `select`/`get`
returns that copy instead of the row. The map holds **weak** references, but `Node` and
`NodeTransport` back-populate each other into a **reference cycle** — so "still alive"
means "the cyclic collector has not run yet".

**The direction matters and was written down backwards once already.** A surviving stale
copy is what turns such a test **red**: the first read sees the fixture's `None` while the
second, already expired, sees the digest the apply really wrote. When the collector has
taken the copy, both reads agree and it passes. Anyone who records this as "the stale copy
made it pass for the wrong reason" has it inverted.

**The reproduction is the asset, not the fix.** Run pytest with a two-line plugin calling
`gc.disable()` in `pytest_configure`, and any GC-timing-dependent test in this zone becomes
deterministic: at the baseline the flake failed **5 of 5** with the collector off and passed
**5 of 5** with it on. Costs one extra suite run (~7m30s). The plugin is a diagnostic and
does not belong in the repository.

**Running the whole zone with the collector off is the mechanical version of "does this
shape repeat"** — it found three more instances in `test_revocation_push.py`.

**What that sweep cannot find, and why it is not a complete audit.** It finds tests that
*fail* on a stale copy. It cannot find one whose expectation happens to **equal** the stale
value — those simply never flake and never fail. Two such were found by reading, not
mechanically: `test_a_pushed_node_is_left_active` and
`test_an_unexpected_error_after_the_push_leaves_the_node_alone` asserted `ACTIVE` /
`state_detail is None`, which is exactly what the stale copy says, so a revocation that
degraded every node it pushed to would still have read back as untouched. Both were
confirmed blind by mutation — degrading the fleet through a separate engine and watching the
pre-fix bodies pass anyway — and expiring made them real tests for the first time.

**Two Postgres agents do not fit in one database.** `clean_database` drops and recreates
every table, so two suites sharing one database silently corrupt each other — which happened
in this run and cost a discarded suite. If a step needs repeated `make test-control` while
another zone is live on the branch, take
`HASHI_TEST_DATABASE_URL=postgresql+asyncpg://hashi:replace-me@127.0.0.1:54132/<own-db>`
and `CREATE DATABASE` it.
