# M15 — what landed

**Closed 2026-09-11.** Three steps, **8 review rounds**, acceptance **good on the
first round**. `make verify` green: 537 control, 230 edge, 169 infra, 155 e2e.

## The field bug is gone, and it was proven gone

The walk built `entry-ru`, offered `amneziawg` to friends at UDP 51820, then made
that same node the entry end of a hop over the same transport. **No 409, no
"already configured".** Both ends written; the node carries `amneziawg` (friends,
51820) and `amneziawg-2` (relay-entry, 51821), distinguishable on every screen
that lists them, and the friend's subscription carries only the friend-facing
config.

Uniqueness moved off `(node, transport_name)` onto **the listening port —
qualified by transport-layer protocol — and the config name**, per the owner's
decision. Removal shipped, so the corner is no longer permanent: withdraw keeps
the row *and its port*; remove deletes it and gives the name back.

## The two things M15 did not know it contained

**The runbook was wrong in a second, deeper way.** `amneziawg` on Shape A's single
box is *right* — that box dials no hop. It breaks only when the box becomes an
entry with a hop, where a friend-facing kernel tunnel gets `Egress.HOP` and is
refused at render. So the runbook now recommends `vless-reality` for friends on a
hop-dialling node, and carries a **capability table whose three columns are
derived from code** — a transport added to `edge/transports/` without a row turns
`make test-infra` red. That is M15's durable half: the contradiction that survived
eleven milestones cannot return silently.

**"A failed apply marks the node degraded" was false in three documents.** True of
a push failure and a `target_for` failure; false of a **render** refusal, which
raises before either `try:` that records. So an already-active node whose render
now refuses **stays active and stays in every friend's link**, serving its
last-applied config, with nothing red on the Nodes screen. Corrected in the
runbook (twice) and in the field checklist, and traced to its likely source: a
comment at `control/app/panel/routes.py:1659`, `control`-zone and left for a
control diff.

## Caught in review, both outside a test's reach

- A unique index on the port number alone **would have aborted the control plane's
  boot** on a database holding Reality/TCP 8443 beside AmneziaWG/UDP 8443 — a state
  the runbook puts within reach — failing inside `entrypoint.sh` where the only
  output is a traceback. Closed by adding a required `edge` contract field,
  `TransportMeta.listens_on`, because `family` is free text the contract says
  `control` reads to decide nothing.
- An e2e audit assertion green **only by alphabetical filename ordering** on a
  shared database. It would fire on any second run against one stack.

## Open for the owner

**Should a render refusal degrade the node?** It does not today, and two such
refusals reach real operators — M15's egress one and M17's `AmbiguousPeerRoute`.
Making it degrade needs the state machine to allow draft→degraded, which changes
what a node's state means. Recorded, not decided.

**Clumsy, from acceptance:** the Audit log cannot tell the two instances apart —
every entry reads `amneziawg enabled/removed on entry-ru` with no config name, on
the one screen whose job is saying what you changed.

## Field checklist

Six items, `docs/tracker/field-checklist.md` — the load-bearing one being that the
stand **never applied anything**, so that two instances actually bind two ports
side by side on a real kernel is exactly what M15's decision rests on and exactly
what only the hosts can show.
