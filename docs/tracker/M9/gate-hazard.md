# A hazard in how this pipeline runs the gate — found 2026-09-10

Not a defect in the product. A defect in how the work was driven, recorded
because it will recur on every future run of this pipeline and because it
manufactures "flakes" that look like real regressions.

## What happens

`tests/control/conftest.py:39` points every control test at **one shared
Postgres** — `postgresql+asyncpg://hashi:replace-me@127.0.0.1:54132/hashi` —
unless `HASHI_TEST_DATABASE_URL` is set. The fixtures drop and recreate schema
against it.

This pipeline runs **implementers that self-gate** and **reviewers that
independently verify**, and the whole point of the reviewer running the gate
itself is that it does not trust the builder's claim. So two `make test-control`
runs, or a `make test-control` beside a `make e2e-verify`, routinely overlap
against the same database. Each one's schema teardown is the other's missing
table.

## What it looked like before it was understood

`tests/control/test_apply_must_reach_the_daemon.py::test_a_stale_apply_records_no_applied_digest`
was reported as *"intermittently red at baseline"*, verified pre-existing by
stashing the diff — a completely reasonable conclusion from inside one agent. It
passes **6/6 in isolation**. Running the full control suite while a reviewer was
mid-gate produced a burst of failures far larger than one flaky test, which is
what gave the game away.

**Any "flake" seen during this run should be re-measured alone before it is
believed**, including the ones already recorded.

## What to do about it

- **Immediately, and free:** never run the gate while an agent is running it.
  Serialise, or give each runner its own database with
  `HASHI_TEST_DATABASE_URL`.
- **Properly, and `infra` work:** the control suite should take a database per
  run — a per-worker schema, a template database, or a disposable container —
  so the gate is safe to run concurrently by construction. Nothing currently
  says it is unsafe, which is the actual defect: a gate with an undocumented
  serialisation requirement is a gate that produces mysterious red runs.
  `conftest.py` names `HASHI_TEST_DATABASE_URL` for the fleet's isolated dind,
  so the mechanism exists; what is missing is using it, and saying so.

## Why this belongs in the tracker rather than being fixed here

It is `control`/`infra` scaffolding, not M9's subject, and changing how every
control test gets its database mid-milestone would put a large unreviewed change
under a milestone about panel screens. It is written down instead — with the
warning that it has already caused at least one wrong conclusion in this run.
