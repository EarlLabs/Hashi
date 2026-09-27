# M27 — carry-over
Non-blocking findings left open, with the reason each was left. Read them as BACKGROUND:
they tell you what is known-wrong so you do not mistake it for the intended design. Do not
fix them as part of another step.

## From M27.1 — OPEN, carried into M27.2

**1. A false security claim in the durable record.** `docs/decisions.md:159` says *"seizing
the control host yields ciphertext and seizing the delivery host yields the credential."*
**The first half is false.** `HASHI_SECRET_KEY` lives in `.env` **on the control host** —
`scripts/panel-bootstrap.sh` refuses to install unless it finds it there,
`docs/deploy/runbook.md` says *"`HASHI_SECRET_KEY` goes in `.env` here"*, and this same file's
2026-09-23 row records that `.env` holds the key and is excluded from the backup **for that
reason**. So seizing the control host yields the key beside the database, and therefore the
tokens in the clear.

The true property is about the **dump**, not the host: M28 built *two secrets that never meet
on the control host* about the age identity, not about the master key being absent. **It is
false in exactly the arrangement this milestone is about** — under Shape B the control host
*is* the Russian entry, which is why `panel-bootstrap.sh` has that refusal — and a later step
reading it would rank the control host as the ciphertext-only side when choosing where a token
store may live. **M27.2 corrects it while writing its own row.**

**2. The store shape is presumed in a neighbouring clause.** `docs/decisions.md:158` says a
host that stops serving keeps *"its token files"*, which presumes the naive one-file-per-token
store the next row says M27.2 may or may not land. Should read *"whatever token store M27.2
lands"*.

**3. The stop-case gap has no home outside one decisions row.** `docs/PLAN.md`'s M27.2 text
does not mention removing delivery material, and **none of M27's six done-when boxes covers a
host that stops being a delivery host.** The clause is correct; its carry is weaker than it
reads. Echo it in a step's text or as a done-when box.

## Not M27's — a gate-integrity finding, worth its own work

**`tests/control/conftest.py:107` skips per-test when Postgres is unavailable, and the victim
is whichever test runs first.** The fixture is function-scoped, so a slow container costs an
arbitrary number of tests and the run still **exits 0 with a green summary**. Observed once in
this milestone as 992 passed / 3 skipped where the real number is 993/2. The cited file:line
in the first report was just that run's draw, not a fixed location. A session-scoped
wait-for-Postgres, or a hard failure rather than a skip once the URL is explicitly configured,
would close it. Same family as everything M28 was about: a check that goes quiet rather than
red.


## From M27.2 — open

**1. A recorded log-exposure claim that is probably false.** The M27.2 deferral row says an
SFTP failure reaches `logger.exception` *"carrying asyncssh's own message, which names the
remote path — the first time a per-subscription identifier can land in this control plane's
log."* Review could not substantiate it: asyncssh builds `SFTPError` from the server's
FXP_STATUS `reason`, and OpenSSH's sftp-server sends generic reasons (`Permission denied`, `No
such file`) with no path; the only asyncssh site that interpolates a path is `rmtree`, which is
not on this route; and `apply.py`'s generic arm uses `type(exc).__name__`, never `str(exc)`.
**The row hands M27.3 an exposure that may not exist.** Errs conservative, which is why it was
not blocking. Measure it — force an SFTP failure, read the log record — and record what was
observed, or soften the claim to what was actually checked.

**2. The `DNS =` discriminator in the seizure inventory is wrong.** The row qualifies it as
*"on a node with no hop"*. Hop-ness is right for the **VLESS** server config, but a WireGuard
user transport is `Egress.LOCAL` with or without a hop, and `edge/egress.py` renders a resolver
exception into the server config's `PostUp` for every resolver that is **off the internet**. So
on a no-hop node with a **private** resolver — the case `resolver_problem` deliberately allows,
and the one an operator copying from `/etc/resolv.conf` lands in — the address is already in
the node's own server config and the `DNS =` line is not a widening at all. The real
discriminator is public-vs-private resolver.

**3. A fourth state the taxonomy presents as exhaustive.** A node in a **non-serving** state
(degraded, or draft-but-previously-applied) is skipped by the revocation fan-out, which calls
`apply_node(..., only_if_serving=True)`, so it keeps a revoked user's artifact until it is
repaired. Neither "an apply runs on it" nor "no apply reaches it again". Temporary, and matched
by the config residual, so a completeness point about the row rather than a new defect.

**4. The pin test asserts `409` but not which 409.** A future change refusing the apply for a
different reason would keep it green while the pinned state silently stopped being reachable.
Assert the error code or the sentence.

**5. An exclusivity claim `edge` cannot see.** `edge/bootstrap/delivery.py` says
`control/app/services/apply` is *"the only one"* that calls `place_delivery`. True today,
unverifiable from that package, and rots silently — the class the convention exists to prevent.
Drop *"the only one"*, keep the name.


## From M27.3 — OPEN, carried into M27.4

**1. A correction applied in one place out of five.** Four places still assert the control
plane answers an unknown token with a **bare** 404: `edge/bootstrap/delivery_site.py:216-218`,
`edge/bootstrap/delivery-site.Caddyfile.j2:54-57`,
`tests/edge/test_what_a_delivery_host_serves_and_what_it_writes_down.py:199-200`, and
`tests/e2e/infra/test_a_delivery_host_serves_a_subscription_and_logs_nothing.py:270-271`.
**Measured false:** `GET /sub/<unknown>` on the control plane returns 404 with
`cache-control`, `content-security-policy`, `referrer-policy`, `x-content-type-options` and
`x-frame-options` — and two of those are exactly the ones the e2e assertion message says no
control-plane 404 carries.

**The same round discovered this and corrected `docs/decisions.md` to say the opposite**, then
left the claim standing everywhere else, so **the durable record and the source now contradict
each other about one measurement.** The true statement is already written in the row: a
delivery host's refusal matches the control plane's **public site** (bare Caddy 404) and
deliberately does **not** match the control plane's own `/sub/` 404, because matching that
would mean answering with the header set that identifies a hashi control plane.

**2. A test that cannot fail, in the test added to fix an untested guarantee.** Deleting the
`sqlalchemy.engine` pin from `configure_logging` leaves all four tests in
`tests/control/test_the_loggers_this_process_silences_stay_silenced.py` **green**, because
SQLAlchemy sets `logging.getLogger("sqlalchemy")` to WARNING at import, so the child's
effective level is 30 whatever the root and the pin do. `asyncssh` and `uvicorn.access` go
genuinely red. The file's header claims the guarantee for all three. Fix: drive the **parent**
to DEBUG before calling `configure_logging`, add those parents to the save/restore set, and
re-run the deletion mutation for all three.

**3. `file` and `file_server` disagree on a directory** named `<name><extension>`: `file`
treats it as absent, `file_server` serves its index — measured, 200 with a body and **none of
the headers**, i.e. a document without `no-store`. Unreachable in practice (the push writes
only regular files, replaces the directory wholesale, and mounts `:ro`, so it needs root on the
node already). One sentence, or give `file_server` a matcher too.

**4. The header guard test misses the block a real link hits.**
`test_the_headers_are_set_only_where_the_artifact_is_really_there` loops `ARTIFACT_EXTENSION`
and so covers the two shape matchers but not `@no_shape_named` — the block a URL a user
already holds actually reaches. Deleting the `file` guard from that one block leaves it and
its neighbour green; only the e2e scenario catches it.


## From M27.4 — two gate-integrity findings, neither this milestone's

**1. `make verify` is red for four hours a day, and has been since M28.** Confirmed at 00:54 UTC:
`tests/infra/test_what_the_command_line_may_say_about_a_backup.py::{test_the_tick_that_takes_it_leaves_a_record_this_clock_can_read,
test_a_run_timestamp_ahead_does_not_make_the_tick_dump, test_an_ordinary_record_says_none_of_that}`
fail between **00:00 and 04:00 UTC**. The module builds `A_REAL_RUN_HALF_AN_HOUR_AGO` at import
with `due_date = today_in("Etc/UTC")`, while `scripts/backup-run.sh` computes the due date from the
configured `at=04:00` window — so inside that window the fixture's record is dated a day **ahead**
of the schedule's own due date and the script correctly answers `clock=ahead`. **The product is
right and the fixture is wrong.** Proven pre-existing: the same three fail at `530e61b` in a clean
worktree at the same wall clock, and M27.4 touches no infra file the suite collects.

This is the sharpest instance yet of the family this run keeps finding — **a gate whose colour
depends on the hour**, green in every run anyone happened to make. Fixed as its own step because
every remaining step of M27 gates on `make verify`.

**2. `test_panel_bootstrap.py::test_running_it_again_changes_nothing` went red once** on a cached
rebuild recreating one container of a shared module-scoped install, and green on three re-runs.
Not in any M27 diff. The property depends on a fully-cached rebuild producing the same image id,
which a session that also pulls or builds images elsewhere can break. Worth pinning the base images
that scenario builds, or making the assertion name which service was recreated so the next red run
explains itself.
