# directive-90be25f3-9

**Type:** epic
**Goal:** Turn the owner's directive ("plan it yourself, the fleet builds it, I
want a working VPN service; report status and a PR after each big stage, merge
the small ones yourselves") into an ordered, dispatchable queue of work that
carries hashi from scaffold to a service a friend can actually use.

## Outcome

18 tasks in 4 stages, queued in `children.json`. Ohno's backlog items 0–10 are
reused as-is, unrenumbered; items 11–25 are not taken because they need a rented
host, which is the owner's money decision.

- **Stage 0** — 1 task: prepare the tree (no zone, no backlog item)
- **Stage 1 = M1** — items 0, 1, 1a, 2, 3 + an integration review → owner PR #1
- **Stage 2 = M2** — items 3a, 4, 5, 6, 6a, 7, 8, 9, 10 + an integration review → owner PR #2
- **Stage 3** — the M3 decision pack (Q4 money/hosts, Q5 decoy principle,
  Q6 port publication, charter amendments C, E and F)

## Assumptions (UNATTENDED RUN — nobody answered, defaults taken)

Xavier's six clarifying questions were answered with his own conservative
defaults, not by the owner. Each is reversible by a single owner reply.

1. **Merge authority.** The directive ("merge the small ones yourselves") is read
   as a task-scoped raise to L2 **on `develop` only**; **`main` is never
   agent-merged**. A "big stage" = a milestone, so the owner sees exactly two
   PRs. Recorded in `docs/tracker/`, not in the write-protected `.claude/`.
2. **Ceiling.** The epic stops at backlog item 10 and ends in a decision gate.
   Items 11–25 need money and a live host — charter §Autonomy makes both
   always-ask — and their acceptance text is sketch, not frozen.
3. **No container runtime here.** Scenarios that cannot execute skip **loudly**,
   naming the command that would prove them. Nothing is weakened to go green.
   M2 therefore ships **delivered, not accepted**.
4. **Item 0** lands as its configuration half only. No agent reads, moves or
   opens the real `.env`; the file-move half stays blocked on the owner (Q2).
5. **Stale rulebooks.** `.claude/**` is write-protected, so each spec carries the
   decided text verbatim and names the stale rulebook line. Correction C was
   re-issued: `origin/develop` now exists, so the original text was factually out
   of date.
6. **Subscription format** stays the frozen base64 URI list; no second format is
   added. Q7 (which clients friends actually use) leads the Stage-2 PR as a
   manual owner check.
7. **Charter conflict F**, found by Ohno during traceability review: the charter's
   Stack table assigns phase 1 to WireGuard + AmneziaWG, while M1 builds
   VLESS+Reality and VLESS+WS+TLS. Dispatch proceeds because M1 closes criterion
   4, which is phase-agnostic, and because the charter itself demands the
   subscription question be settled before the first transport is built. The M1
   PR is forbidden from claiming "phase 1 delivered as charted".
