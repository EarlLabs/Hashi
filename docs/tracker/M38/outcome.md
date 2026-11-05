# M38 — outcome

**Landed on `task/M38` (2026-11-02 → 2026-11-04), stacked on M37.** Two commands added to the
owner-only Telegram bot: `/nodes` lists the serving nodes whose host does not hold the
configuration the panel would push — the console's own "behind" block
(`nodes_missing_what_they_would_be_given`, a digest comparison, no network), each with an
`apply it: /apply <name>` line, or one sentence when nothing is behind; `/apply <name>` runs
the Nodes screen's Apply (`apply.apply_node`, the serving-only guard off), taking a draft or
degraded node into service and marking it degraded on a failure after the first byte. The
add's reply, when a node could not be updated, now names that node with the panel's reason
sentence and offers `/apply` for it. Nothing an apply knows reaches the chat except the
panel's own sentences — never a config, a key or a raw error. Runbook section extended, one
journal row.

**Steps and review rounds.** M38.1 (`/nodes`, the add's offer): 1 round, clean. M38.2
(`/apply <name>`): 1 round, clean. M38.3 (docs): 1 round, clean. Nothing stopped at a cap; no
reviewer disagreement. Two network/usage interruptions during the run (a reviewer and an
implementer) were resumed from their transcripts with no lost work.

**Acceptance.** One round on a disposable stand with the fake Telegram, verdict GOOD — may
merge. The agent registered a throwaway unreachable node to exercise `/nodes` with a node
present and `/apply` against a host that cannot be reached, and confirmed every bot reply
word-for-word against the panel's own sentences and the database: `/nodes` mirrors the
behind block in four fleet states; the add's reply offers `/apply` only for the node it could
not reach; `/apply` matches the Nodes screen's Apply (nothing-to-apply, draft→degraded,
serving-stays-active); no key, config or raw error in any reply or log; an unknown name
refused in words; a stranger's command silent. One clumsy line: `/apply` of a
nothing-enabled node says "applying… about a minute" then refuses in the same second, the
same by-design trade as M37's "adding…". Could not be observed on a stand: a successful
apply and a node applied from the owner's phone (no reachable host), the checker-refusal
key-quoting path specifically, and reply-splitting past 4096 chars (unit-tested).

**Gate.** Close gate green on the final tree: control 1333, edge 1025, infra 649 (edge and
infra in a Linux container with CI's pins), e2e 226 passed with the failing set exactly this
Mac's host-bound baseline and nothing new — the two new M38 scenarios among the passes. The
real `make verify` is the PR's CI run on Ubuntu.
