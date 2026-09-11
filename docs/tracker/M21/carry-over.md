# M21 — carry-over

Non-blocking findings left open, with the reason each was left. Read them as
BACKGROUND: they tell you what is known-wrong so you do not mistake it for the
intended design. Do not fix them as part of another step.

## From M21.1, review round 1

- **Low** — `tests/control/test_first_apply_failure.py:227` applies
  `assert_plain_reason` to `raised.value.message`, whose wrapper prefix ("the node
  could not be configured and has been marked degraded: …") on its own supplies
  more than the four prose words the helper needs. Under the reviewer's
  bare-class-name mutation this was the one unreachable-path test that stayed
  green, and the stored `state_detail` is not checked there at all. The property
  is covered by the other four call sites, so this is a tightening rather than a
  hole. Fix would be: also read the node back and
  `assert_plain_reason(node.state_detail, refusing_ssh.host, ADVERTISED_ADDRESS)`,
  keeping the existing message-level assertions. (Line number and helper
  signature updated after M21.2 — the finding itself is unchanged.)

## From M21.2, review round 2

Nothing left open. Round 1's Medium (the no-leak check had narrowed to the
dialled endpoint and no longer guarded the node's advertised address) and its Low
(an fd leaked if `_bound_loopback_socket`'s `bind` raised) were both fixed in
`808d97a` rather than carried, and round 2 verified each by mutation. They are
recorded here only so the sequence is legible: a clean verdict was returned first
and the fixes were asked for anyway, because a milestone about a trustworthy gate
is the wrong place to bank a coverage reduction.

## From M21.3, review round 1

Nothing left open — the round returned `VERDICT: CLEAN` with no findings at any
severity.

One pre-existing observation was recorded rather than fixed, and it belongs to a
later milestone rather than here: the WireGuard family's `DataPlane.executables`
tuple does not declare `sleep`, although the supervisor's shell line invokes it.
Harmless today (both pinned images ship busybox) and out of M21.3's reach.
**M19.3 declares `ip` for that same tuple and is where this should be picked up.**

## Found after M21 closed, on 2026-09-10 — the same defect class, one zone over

`make verify` went red once on an untouched, already-reviewed tree and green on
the immediate retry. The failure was **not** an assertion:

```
subprocess.TimeoutExpired: Command '[…/scripts/panel-bootstrap.sh, --env-file, …]'
timed out after 600 seconds
tests/e2e/infra/test_panel_bootstrap.py::test_a_control_plane_that_never_answers_is_reported_as_a_failure
```

The captured output shows it was **still building docker images** when the budget
expired. So the 600s is being spent on work unrelated to the property under test —
the scenario deliberately boots an unhealthy control plane and waits for the
bootstrap script to report the failure, and image builds are charged to the same
clock. Under load (this run had several containers and agents in flight) the build
alone can eat the budget.

**This is exactly M21's thesis, in `infra` rather than `control`:** a gate that
goes red for reasons unrelated to the change trains everyone reading it to re-run
rather than investigate. M21 fixed the two `control` tests coupled to what a
reserved address happens to do; it did not look at timeout budgets in
`tests/e2e/infra/`, and nothing else did either.

**Suggested fix, in the M21.1 spirit — separate the budget from the property:**
build the images *before* starting the clock (a fixture, or a warm-up call), so
the 600s covers only "the script notices an unhealthy control plane and says so".
Failing that, the timeout must be sized for a cold build on a loaded machine and
say in its own message which of the two it ran out of, so the next reader is not
left guessing.

Recorded rather than fixed because M21 was already closed and committed when this
appeared, and `infra` is a different zone from the `control` work in flight.

### And the timeout LEAKS ITS STACK, which is why it gets worse

Found 2026-09-11, and it explains why this looked like bad luck rather than a
mechanism. When `test_a_control_plane_that_never_answers_is_reported_as_a_failure`
times out at 600s, **the compose project it started is never torn down.** Twelve
containers were found still running from two such runs — `feecfa07` (2026-09-09,
up 40 hours) and `f3d64920` (2026-09-10 22:16, the baseline run of this very
session) — each a full three-service stack, and in each the `unhealthy-control`
container is in a **health-restart loop**, burning CPU indefinitely.

So the failure feeds itself: a timeout leaves a stack behind, the leaked stacks
compete for the same engine, and the next run is likelier to time out and leak
another. Two runs had leaked six containers each before anyone looked.

**This strengthens the fix already named above** (build the images before starting
the clock) and adds a second, independent one: the scenario must tear its project
down in a `finally`, so a timeout cleans up after itself. A test that leaks a
service stack on the one path it is designed to exercise — the *unhealthy* control
plane — is leaking on its most-travelled failure route.

Clean-up for anyone who meets this: `docker compose -p <project> down -v`, or
remove by the `hashi-panel-bootstrap-` name prefix. Nothing in them is worth
keeping; they are disposable scenario stacks with random hex suffixes.

