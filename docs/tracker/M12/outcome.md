# M12 — outcome

**Four steps, one commit plus the orchestrator's two Low fixes, `infra` zone. One
review round, CLEAN.** `acceptance: no` — a milestone whose subject *is* the
acceptance instrument cannot be judged by that instrument.

**Gate:** `make verify` green — 218 control, 230 edge (3 skipped), 161 infra, 140
e2e, stand torn down. **The gate did not get slower**: the browser stays behind
its compose profile, so `make e2e-up` neither builds nor starts it. The ~40s
build lands only on `stand.sh up`, once per machine.

## Why this milestone existed

The instrument the plan intends to judge M8, M9 and M10 with could not take a
single action. The pinned image ships the browser binaries and `pip` but **not**
the `playwright` package the driver imports — and `begin` started its
in-container server with `stderr=DEVNULL`, so the traceback that said exactly
that was thrown away one line before the failure was reported. What it reported
instead was *"the browser did not come up inside the stand"* — a message naming
the symptom, hiding the cause, and pointing at the one layer that was working.

## What each step actually bought

- **M12.1** — the browser is **built**, not pulled, and the Dockerfile re-runs the
  driver's exact import at build time, so a broken image fails where somebody is
  watching a build. The version is written **once**, as `ARG PLAYWRIGHT_VERSION`
  before the first `FROM`; the image tag and the `pip` pin are both derived from
  it, and a test asserts they resolve equal and that the literal appears exactly
  once.
- **M12.2** — a failed `begin` now prints the in-container server's own output.
  **The privacy claim is structurally true, not merely usually true**, which the
  reviewer verified by tracing `serve()`: playwright starts, the browser launches
  and a page is created all *before* the socket binds, and `begin` reads that log
  only in the branch where the socket never appeared — so no client has connected
  and no URL or subscription token can exist in it. It stays in the container,
  is truncated per `begin`, and is never collected into the evidence directory.
- **M12.3** — `stand.sh up` proves the instrument every time: `begin`, `open`,
  `end` through the real driver, and it refuses to print `ready.` if that fails.
  It opens `/panel/` and **never a `/sub/` address**, which would put a bearer
  token in the stand's output and in a screenshot name.
- **M12.4** — `down` takes everything `up` started. `E2E_ALL_PROFILES` is the one
  list a new profile must join, and a test fails if it does not; `stand.sh down`
  asks docker whether anything carrying the project label survived before it says
  `gone.`

## Two things found on the way

- **`drive.py` was committed `0644`** while both its siblings were `0755`, so the
  documented hands command died on `Permission denied`. The same class of defect
  as the milestone itself: the instrument was unusable and nothing said so.
- **A latent way to defeat M12.4.** `e2e-down: E2E_PROFILES := …` is a
  target-specific variable, and GNU Make lets a command-line `E2E_PROFILES=`
  silently win over one. Raised as a Low by the reviewer; fixed with `override`,
  and the test was **tightened to require it** rather than tolerate it — proven
  red-first by removing the keyword and watching the assertion fail. A guarantee
  that can be switched off from the command line is not a guarantee.

## The pattern worth keeping

Every step here is a case of the same rule: *a check that cannot fail is worse
than no check.* `stand.sh up` used to print `ready.` about a stand whose driver
could not act; `test_drive.py` tested the driver's argument handling on the host
and never asked whether the container could import what the driver imports. Both
were green the entire time.
