# M4 — outcome

**Steps:** M4.1, M4.2, M4.3, M4.4, M4.5, M4.6 — all built, all reviewed.
**Rounds:** one each, except M4.4 which took two. Its round-1 High was not about
its behaviour at all: it changed `edge` and `control` in one diff. The split was
then verified by running each zone's gate at its own commit, and the round-2
reviewer confirmed byte-identity against the original commit object.

**Acceptance:** `acceptance: no` in the plan — "provable by test once M1 is in".
No acceptance loop was run, by the plan's own instruction. M4.1's behaviour was
nonetheless confirmed on real hardware; see `step-notes.md`.

**Gate at close:** `make test` green — 169 control, 134 edge (3 skipped), 90
infra. The control zone runs against a real Postgres here, so it includes 85
tests CI never runs.

## Why this milestone grew from three steps to six

Each addition is traceable to evidence rather than to scope drift:

- **M4.4** — the baseline gate took 7m39s, of which 23 node dials at 20 s each.
  The plan said there was no connect timeout; there was one, sharing the command
  budget. What had *no* ceiling was the SFTP transfers and the session close.
- **M4.5** — M4.2's implementer recorded an identity comparison as harmless; its
  reviewer disproved that by reproducing it. `state is not node.state` was
  always true, so a second failed apply kept the *first* failure's reason in
  `state_detail` — this milestone's own "done when", violated.
- **M4.6** — two guards that could not fail. One double drifted from the real
  signature; one leak test injected an exception that never carried an address.

## The two results worth remembering

**The reordering paid for itself within the hour.** M4 was moved ahead of M1 on
field evidence, and the very next fault found on real hardware (M13) would have
cost the same archaeology without it.

**Fixing at the type beat fixing at the comparison.** M4.5 could have been
`is` → `==`. Instead `Node.state` got an `EnumText` decorator so the
`Mapped[NodeState]` annotation stops lying, which removes the whole class. The
step notes had already been forced to write down "assert node state with `==`,
never `is`" as a convention — a convention that exists to work around a type
that lies is a smell, and it is now gone.
