# M28 — carry-over
Non-blocking findings left open, with the reason each was left. Read them as
BACKGROUND: they tell you what is known-wrong so you do not mistake it for the
intended design. Do not fix them as part of another step.

## From M28.1, review round 1 — two copies of the corrected half-truth, Medium

Both confirmed by the reviewer, both outside M28.1's fence, **both folded into
M28.2's fence** because the sentence becomes true the moment `age` lands:

- **`docs/product/charter.md:236`** — *"the backup is encrypted with a key not
  stored beside it"*. Describes the whole artifact as encrypted, which is false
  of today's plain-SQL-plus-gzip dump; only a column subset is. Same
  operator-facing safety claim just corrected in the script and the runbook, one
  file over.
- **`Makefile:203-204`** — the `backup:` target's comment says the dump is
  *"useless without HASHI_SECRET_KEY"* with no mention that the rest is a
  plaintext fleet map. A softer half-truth by omission, on the surface
  (`make backup`'s own comment) most likely to be read at the moment of decision.

## From M28.2, review round 1 — the fixture keypair looks real to a scanner, Low

`tests/e2e/infra/test_restore_proves_the_backup.py` commits a disposable `age`
keypair. The reviewer judged it acceptable and verified it is a real, working pair that
never protects real data — the stack under test receives only the public half.

The residual: **an age key cannot carry a "fake" marker inside its encoding.** The
adjacent `HASHI_SECRET_KEY` fixtures literally spell `-not-real-0000…` in the value, so
they are self-evident even in a scanner alert that shows only the matched string. The
age identities are not, so a gitleaks- or push-protection-style scanner would flag them
as high-confidence hits and a human would have to open the file and read the comment to
dismiss them.

**No scanner is wired into this repository today** — `aikit.yml`'s `security:` block
deliberately has no `scan:` key, because none of gitleaks, osv-scanner or semgrep is
installed and adding one is an architect decision. **Left open because** the fix is a
one-line `# gitleaks:allow`-style annotation that is only meaningful once a scanner
exists, and choosing that scanner is the owner's.

## From M28.2 — a marginal timeout that is not this milestone's, Low

The builder's first `make verify` failed on
`tests/e2e/infra/test_panel_bootstrap.py::test_a_control_plane_that_never_answers_is_reported_as_a_failure`
with `TimeoutExpired` at its 600s subprocess cap, spent inside `docker build`. Diagnosed
rather than guessed: that test alone takes ~364s cold and ~79s warm, and this machine's
builder cache is ~10GB with the disk 64% full, so BuildKit GC evicts the `pip install`
layer. The reviewer corroborated both numbers on the same machine and confirmed the test
file is untouched by M28.2.

**Left open because** it is a pre-existing marginal cap under disk pressure, not a
regression. If it recurs on the fleet's dind, the cap is the thing to look at.

## From M28.3, review round 1 — three Lows

**1. The `http` private-address check can be raced by DNS.** `deploy/backup/upload.py`'s
`configuration()` resolves the endpoint host once to decide whether plain `http` is
allowed; `send()` opens its own connection later and the OS resolves again. A rebinding
answer between the two could route an `http` PUT to a public address despite passing.
**Blast radius is narrow:** the secret never crosses the wire either way (SigV4 signs),
so only the access-key id, the bucket name and the ciphertext could leak, and only for
an operator who deliberately opted into `http` against something meant to be private —
which in practice is a test endpoint. Disclosed rather than claimed away. **Left open**
as a recorded limit; closing it means pinning the resolved address into the connection.

**2. `docs/deploy/runbook.md`'s `### What you carry` item 3 is stale future tense.** It
says the bucket read credential *"becomes needed the day the offsite upload exists"* —
and M28.3 is the day. M28.1 set the rule that the description and the behaviour move in
the same step, and this section was not touched. **Folded into M28.4's fence**, which is
in the runbook anyway.

**3. Port `54308` is outside the documented 54100–54299 block**, joining the
pre-existing 54300/54301/54305 the restore scenario already uses (recorded in
`docs/tracker/M29/carry-over.md`, "From M29.3b"). Loopback-only and test-only. **This is
a fourth instance of one known gap, not a new kind** — whoever decides the third-block
convention decides all four together.


## From M28.14

**1. `test_a_stale_apply_records_no_applied_digest` is flaky, and it is in the gate.**
`tests/control/test_apply_must_reach_the_daemon.py:325-334` reads `first` without a
`session.expire_all()`, while the second read twelve lines later has one. SQLAlchemy's
identity map holds **weak** references, so whether the stale `applied_digest=None` copy
is still alive at that `select` depends on garbage collection — which is why it passes
alone, fails under the full suite, and passed inside `make verify` on the same commit
that failed `make test-control`. **Red two runs in three and green in the one the fleet
reports on is worse than steadily red.** Pre-existing, not M28.14's, and carried into
M28.16 rather than left here.

**2. The Settings item is half closed.** `HASHI_BACKUP_RECORD` is now a row — it is the
only backup setting `settings.py` has. The other half of acceptance's note, the Overview
naming `HASHI_BACKUP_ENABLED` by hand and sending the owner to a markdown file, is
unchanged and is **AST-pinned from the infra zone**, so moving it is cross-zone work and
not a thing one diff may do.

**3. `_missed_recently` uses `day >= horizon`**, so a date exactly `RECENT_GAP` old counts
as recent. Tested at 1 day (in) and 57 days (out) but not at the 56-day edge itself,
which is below this module's own habit — `SUCCESS_STALE_AFTER` is boundary-tested at 47h
and 49h.
