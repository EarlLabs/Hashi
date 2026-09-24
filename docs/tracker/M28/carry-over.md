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


## From M28.15

**1. `tick` still reads the record leniently while `status` and `due` read it strictly.**
The sixth surface, reproduced twice and deliberately left: `"last_attempt": "probably
fine"` makes `tick` conclude the day's backup was taken (self-heals next day), and
`"due_date": "2099-01-01"` makes it **exit 0, print nothing, and wait until 2099** — the
taking channel silently stopped while both speaking channels say so. Fixing it needs a
decision about what `tick` does with an unreadable record, which is the owner's.

**2. The shared answer, specified and not built.** `scripts/backup-run.sh` contains **two
readers of one file**. `scripts/lib/backup-record.sh` would hold the canonicaliser, the
strict validator and the field readers behind one entry point returning either a refusal
key or a validated reading — the same move `scripts/lib/env-value.sh` was in M28.13, and
against the same lesson: *the defect was never one bad comparison; it was a second parser
that gives the right answer on every file anybody tests with.* It is a refactor across a
working feature and needs [[1]] decided first.

**3. A directory at the record path splits the two channels** — pre-existing, found
reviewing M28.15. The command line's `[ -f ]` reads it as *"No backup has ever been
recorded on this host"*, while the panel classes the same shape as presence-with-nothing-
legible and answers UNREADABLE. `write_state`'s `mv` then deposits `last-run.json.partial`
*inside* that directory, so the schedule runs and leaves no record. Carried into M28.17.


## From M28.16

**1. About 40 un-audited reads-through-a-populated-session remain in `tests/control/`.**
All pass with the cyclic collector off, so none of them *flakes* — but that sweep cannot
distinguish "this read is fresh" from "the stale copy happens to agree", which is exactly
the class the two blind assertions belonged to. Separating them needs mutation testing,
which is a piece of work rather than a line. `expire_all` already appears 104 times across
23 files in the zone.

**2. The identity-map trap is a zone-wide idiom documented only in per-file comments.**
Both the implementer and the reviewer argue for one line in
`.claude/projects/01-control-rulebook.md` §Testing, beside the existing `expire_on_commit=False`
entry in §Traps — *a test that reads through the same session a fixture wrote through must
`session.expire_all()` first; the identity map holds weak references, so a stale read is a
garbage-collection lottery.* The rulebook was correctly not edited by a step that does not
own it. Worth its own step together with [[1]].

**3. The cost of this being undocumented, measured once:** one flaky gate that verified this
milestone twice, plus two assertions that could not fail. That is the argument for [[2]].


## From M28.17

**1. The runbook still writes "64 KiB" in prose, and nothing pins it.** The two code sides
now move together; the runbook would go stale behind them silently — a smaller version of
the defect this step closed. Either phrase it without the number or extend the parity
section to read the runbook, the way §7 of the same file already greps it. **Folded into
M28.18** rather than left here.

**2. `shell_number`'s regex is anchored at the left margin**, so an *indented* later
re-assignment of `MOST_OF_A_RECORD` inside a function would be invisible and the pin would
keep comparing the margin value. Contrived — every constant in that script is at the margin
— but it is the one silent hole in an otherwise loud reader. Counting
`^[[:space:]]*MOST_OF_A_RECORD=` and still requiring exactly one would close it. **Folded
into M28.18.**

**3. The `size` and `shape` fault paragraphs wrap raggedly** — they carry hard newlines from
the `fault=` assignment and sit next to evenly-wrapped shared paragraphs. Cosmetic, and
acceptance judges this wording. **Folded into M28.18.**


## From M28.18

**1. The panel does not notice a record whose `due_date` alone is ahead** — the eighth
surface, and it invalidates a sentence three files now carry. `control/app/services/backups.py::_ahead()`
reads only the `last_success`/`last_failure` timestamps, by its own documented design, so
the 2099 record gives `standing=SILENT` and **no banner**, while `due` exits 1 saying
*"NOTHING IS BACKED UP AT ALL"*. Reachable without a hand edit: moving `HASHI_BACKUP_TZ`
west across the date line gives `due` `clock=ahead` and the panel `FRESH`. The claim that
*"the panel draws a banner about the same file"* is true only of the organic clock-jump
case, where the run timestamps are ahead too. Carried into M28.20 (`control`), with the
prose narrowed in M28.19 (`infra`).

**2. The "records nobody" audit is first hop only.** `_sourced_libraries` reads `BACKUP`,
`RUNNER` and `INSTALLER` and does not recurse into what it finds. Proven by planting
`scripts/lib/record-notes.sh` with a `tee -a /var/log/…` in it, sourced from
`backup-record.sh`: **all 14 tests stayed green.** Since record handling now lives in a
library, the next move is library→library — exactly the hop this rule does not cover, and
exactly the scenario the test's own docstring describes. Carried into M28.19.

**3. Two fence seams, both planted and confirmed.** Process substitution under a command
word not in the tool list (`done < <(sed -n 1p "${STATE_FILE}")`) passes the entry-point
fence; and `_whole_pipelines` folds a **comment** line ending in `\` into the code line
below, although bash does not continue comments, hiding that line from the pipe guard.
Three such doc-comment continuations already exist in the tree, all followed by more
comment lines today, so nothing is hidden right now. Carried into M28.19.

**4. THE RESTORE PATH IS UNPROVEN BY THE SUITE ON THIS MACHINE.** `make verify` gives e2e
**214 passed / 10 skipped**: four upload and six bucket-restore scenarios skip because
`object_store()` runs `docker pull` unconditionally and quay.io answers **401** here — the
image is present locally (`cd04ea408e18`) and that does not help. Not caused by any diff in
this milestone; the file's last change was M28.12. **M28 must not close on a 214/10 run** —
it is the offsite-backup-and-restore milestone, and `CLAUDE.md` records the cost of exactly
this: *"for eleven milestones nothing else included those scenarios, and one of them had
been failing since the day it was written."* The six local-artifact restore scenarios did
run and pass. Carried into M28.19.


## From M28.19

**1. The sixth instance, in the paragraph written to fix the fifth** —
`scripts/backup-run.sh:472-474`. The DUE paragraph promises *"one extra dump and then a
record that reads normally"*. False when `last_failure` is **also** ahead — the organic shape
when a clock jumps forward and the run under the jumped clock fails, which is the case the
retry logic exists for. Measured: after the promised repairing run **succeeds**, the record
is `due_date=today, last_success=now, last_failure=2099`, and that record still answers
`clock=ahead`, `due` still exits 1, `status` still prints the whole block, the panel still
reports `failure_ahead=True`. Permanently loud, not repaired. The code comment at `:530`
states the consequence correctly; only this sentence promises otherwise, and it contradicts
the RUN paragraph three lines above. **Carried into M28.21.**

**2. The seventh, in the runbook's panel section** — `docs/deploy/runbook.md:1741-1747`,
rewritten by this diff. *"And a **run** in the record dated ahead … the screen goes loud"* —
the panel reads `last_success` and `last_failure` only, so an `last_attempt`-alone-ahead
record is `FRESH` with no banner. The paragraph's qualifier corrects the wrong axis, and the
true statement sits 85 lines further down where a reader of that section has no reason to go.
**Carried into M28.21.**

**3. One more negative assertion over wrapped output without `flowing()`** —
`tests/infra/test_what_the_command_line_may_say_about_a_backup.py:383`. Fires today only
because the phrase happens to fit one source line; re-added across a line break it would pass
silently. The rest of `tests/infra/` and `tests/e2e/infra/` was swept and this is the only
other one. **Carried into M28.21.**

**4. The audit's seam list reads as exhaustive and is not.** Three further spellings walk the
whole sweep out: `. "${REPO_ROOT}"/scripts/lib/a.sh` (quote closed after the variable), `.
${REPO_ROOT}/scripts/"lib/a.sh"`, and two `source` statements on one line (the pattern is
anchored at `^\s*`, so only the first is found). None is written in this tree today — which
is exactly the argument that was made about the braceless form one round earlier. **Carried
into M28.21.**


## From M28.20 — and the convention this milestone actually earned

**1. Five more instances of the prose class, four of which no test here could catch.** All
in the `control` zone or in this tracker, all carried into M28.22:
- `console.py:1072-1074` (+ its docstring `:1034-1036`, comment `:995-999`, and the wording
  list in the step notes) — *"the run times … are printed here exactly as the record has
  them"* and *"agree with `make backup-status` to the minute"*. **The panel never prints the
  record's times**: `_ago`/`_how_long` print a coarse age, so the screen says "4 hours ago"
  over a record holding `2026-09-23T08:00:00Z`. True of `make backup-status`, which prints
  the ISO timestamp; carried to the channel that prints ages. **Introduced by the round-1
  fix**, so it is a new instance rather than a reversal.
- `console.py:1085-1086` — *"A clock that moved on that host **is what** leaves a record like
  this behind"* names one cause exclusively where the residue note lists four (hand-seeded, a
  moved clock, a hand edit, a record carried from another machine). Not round 1's finding
  returning: that named an **impossible** cause, this names a **possible** one as if it were
  the only one. The load-bearing half — *"and a timezone cannot"* — survives any fix.
- `backups.py:145-148` — *"every host scheduled east of UTC … ten hours out of every day"*.
  The ten hours is right for UTC+14 at 04:00 local; a host at UTC+1 resolving 04:00 writes a
  due date equal to the UTC date and is never flagged. The argument for the grace is
  untouched; only the scope overstates.
- `tests/control/test_a_backup_that_has_been_failing_says_so.py:697-698` — the module rule
  *"silent about keys it does not read, strict about keys it does"*, falsified by this very
  step, in a file it edits. **The risk is not cosmetic:** a later reader "finishing" the
  parser on the strength of that rule reopens the two-channel defect M28.18 closed.
- `docs/tracker/M28/step-notes.md:1598-1600` — the residue note lists *"a host clock that
  jumped back by a day or more"* among the shapes now caught. Measured against the real
  `_due_ahead`: back 24 h → False, 36 h → False, 47 h → True. The grace is **strictly** more
  than a day. Overstated twice, in fact, since a backward jump also leaves the run timestamps
  ahead and is already loud via the run half.
- `docs/tracker/M28/step-notes.md:1447-1449` — M28.18's *"`_parse` does not read them at
  all"*, now false for `due_date`. The sweep hit that M28.21 missed: it lists the identical
  sentence in `scripts/lib/backup-record.sh:131-133` and not this copy.

**2. What to pin, and what pinning cannot do — the convention, as argued by the reviewer that
measured it.** Keep pinning, but as the **regression net**, not the remedy.
- **No test can tell a true sentence from a false one; it can only tell you which states a
  sentence appears in.** Four of the six findings above are prose no conceivable test in this
  repository would catch.
- **A positive phrase assertion certifies nothing.** It tests that a string is present, while
  a reader of a green suite takes it as "that sentence has been checked" — a human judgement
  laundered into a machine result, then made expensive to revisit. That is exactly how
  `assert "check both on that host" in detail` made a false clause load-bearing.
- **Pin the gate, not the sentence.** `assert (PHRASE in detail) is (standing is not NEVER)`
  fails in **both** directions and forces the state the sentence holds for to be written down
  executably. **This is the house form.**
- **The absence half carries the information**, and only through `flowing()`. A phrase list
  the panel must never grow, swept over every standing, is worth more than every positive
  assertion beside it.
- **Never pin a sentence naming a cause, a mechanism, or another channel's behaviour** — a
  moved `HASHI_BACKUP_TZ`, a base image carrying a zone database, what `make backup-status`
  prints. Nothing in this repo determines those, so they can never go red; pinning them is
  strictly worse than not.
- **Pin by constant reference.** A literal in a test is a second copy of the sentence, and two
  copies never disagree even when both are wrong.

**The convention that actually closed the eight surfaces is the other one:** *a sentence about
behaviour names the state it holds for, and when you narrow one you sweep the tree for it
rather than reading the diff.* Pinning stops a corrected sentence reappearing in a state
nobody had in mind. Billing it as the remedy is how a false phrase ends up load-bearing.
