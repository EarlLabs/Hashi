# M16 — acceptance: **partial**

Walked 2026-09-12 by an independent agent on a disposable stand, with no sight of
the diff, the changed file names, or any account of how the milestone was built.
The live fleet was then read directly, read-only.

## Verdict

**Partial.** Two of the three "done when" lines pass. The third cannot be
answered anywhere but the field, and the reason is **not a defect in M16** — it
is two access-and-deployment walls, described below. Recorded as partial under
the owner's written lift of 2026-09-12 (autopilot prompt, "Acceptance where the
stand cannot reach", clauses 2–4), which covers exactly this case.

| "done when" | verdict |
|---|---|
| It is written down where names are resolved, and why | **good** |
| No resolver address is hardcoded | **good** |
| A friend's lookup provably does not leave the entry's own interface | **could not — needs the field** |

## What passed, and on what evidence

**"It is written down where names are resolved, and why"** — passed, and the
walker called it unusually well done: the panel copy says it at the point of
use, `docs/decisions.md:58` carries the decision *with both rejected
alternatives and the residual risk the owner knowingly accepted*, and
`docs/deploy/runbook.md:737–782` tells an operator what to do about it. A
reader who arrives cold learns the why, not just the what.

**"No resolver address is hardcoded"** — passed. A whole-tree grep for twelve
well-known public resolver addresses, and for the names a default would hide
behind (`DEFAULT_DNS`, `FALLBACK_RESOLVER`), returns nothing. The address is
node-record data, as the charter's "never hardcode a country, provider, IP,
domain or port" requires.

**The fail-closed half of the third line — proven on the stand.** This is worth
stating precisely, because it is the half that protects the friend:

- A hop-dialling node with **no resolver renders nothing at all**. It does not
  fall back to resolving locally, which is the leak M16 exists to prevent. It
  refuses, surfacing as `ConfigRefused`.
- **The refused apply leaves state untouched.** `entry2-ru` remained `draft`
  with a `NULL` resolver afterwards. Nothing was half-written.
- **A node with no hop is unaffected** — it gets no `dns` block and needs no
  resolver, correctly.

**The charter's one hard record holds.** Nothing in M16 logs a query. Checked at
the code level and against the live config, which carries
`log: {"loglevel": "warning", "access": "none"}`.

## Why the third line could not be answered — two walls, neither a defect

**Wall 1 — M16 is not deployed on the fleet.** Every file in `/opt/hashi/conf`
on the leaf is dated `2026-09-09 08:41`, and the live `vless-reality.json` greps
**zero** for `"dns"`, `domainStrategy` and `sendThrough`. The owner's scenario
describes watching a friend's lookup under M16's behaviour; that behaviour is
not yet on the hosts. There is nothing to watch. **This is expected** — the run
builds on a branch and the owner merges.

**Wall 2 — the entry refuses this key.** `158.160.67.252` answered and rejected
seven accounts (`root`, `ubuntu`, `hashi`, `admin`, `debian`, `yc-user`,
`cloud-user`), all `Permission denied (publickey)`. The host is demonstrably
healthy — the leaf's `amneziawg` shows a live hop to it, handshake seconds old,
~744 KiB in / ~760 KiB out — so it is up and carrying traffic; it simply will
not take this key. Per M19's own finding, that box takes keys from cloud
metadata, so a key has to be added **there**, not in a file on the host.

The entry is the only node where the third line can be observed at all: it is
the node that dials the hop, and therefore the only one that gets a `dns` block.

**Both walls are recorded as field-checklist items with the exact observation
needed** — see `docs/tracker/field-checklist.md`, items 7–9 and the M16 rows.

## Findings — works, but awkward (7)

None of these block. They are dispositioned below rather than listed and
forgotten.

| # | finding | disposition |
|---|---|---|
| 1 | Multicast, broadcast, reserved and CGNAT addresses are accepted as resolvers. A multicast address is syntactically an address and will never answer. | **fix** — M16.3 |
| 2 | A 1000-character value grows the dialog past the viewport, putting `set resolver` beyond reach with no way to submit. | **fix** — M16.3 (a length bound fixes the cause, not the symptom) |
| 3 | `ResolverMissing:` — a Python class name — reaches the operator's banner, with a 502 and a traceback behind it. | **fix** — M16.3. A traceback to the operator is past "awkward". |
| 4 | A resolver cannot be removed once set. A node that stops dialling a hop keeps a stale one. | **fix** — M16.3 |
| 5 | The Nodes table has no resolver column, during exactly the upgrade the runbook tells the operator to perform. | **fix** — M16.3. This is the discoverability of the one action the runbook mandates. |
| 6 | The audit trail records **that** a resolver was set, never **to what**. | **fix** — M16.3. A resolver address is node configuration, not a friend's query: recording it is config history and breaches nothing. Without it the trail cannot answer "what was it before" during the one upgrade that changes it. |
| 7 | The hop dialog's `client_dns` box does nothing. | **fix** — M16.3. A dead control that looks live is worse than no control. |

All seven are sent to a single fresh `step-loop` (M16.3), per autopilot §3 — the
milestone's code is finished, so no implementer still holds it, and a fix
arriving after acceptance earns its own review round.

## What must never be claimed from this

M16 does not touch the charter's first success criterion — surviving a mobile
whitelist shutdown. That is a field observation on a real Russian mobile network
and nothing in this milestone or this run covers it.
