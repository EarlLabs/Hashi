# hashi-e2e-e2e-113

**Type:** feature (test infrastructure + stabilisation)
**Goal:** stand up the acceptance-scenario suite that this project has had a
harness for but no scenarios in, run it for real against a booted stack, and fix
what the run finds. From here development verifies itself: every later task adds
scenarios to a suite that already runs.

**Zones:** `control`, `edge`, `infra` (all three — the scenarios cover the whole
booted stack, and every fix below is in the zone that owns the file).

## Scope

In scope: `tests/e2e/**`, the boot path those scenarios need (compose, images),
and defects the run exposed.

Out of scope, deliberately: implementing any backlog item. Every product feature
— persistence, operator auth, subscription delivery, the first transport —
remains `queued`. This task adds no product behaviour; it makes the behaviour
that exists provable.

## Result

14 scenarios, green from a cold boot. Five defects found and fixed — see
`tasks/alfred-findings-hashi-e2e-e2e-113.md` for each one with its evidence.
