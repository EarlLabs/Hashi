# M26 — fix round 5: walk 4's findings (2026-10-02)

Asked for by the owner on 2026-10-02. Code and a disposable test database only — **no
real host was dialled, written to or restarted.** Branch `task/M26-fix-round-5`, not
pushed. The decisions are in `docs/decisions.md` under 2026-10-02; this file is what was
done and what is still unproven.

## What closed, and the test that was red before it

| walk 4 finding | fix | red on the previous code |
|---|---|---|
| **blocker** — a condemned node empties every user's link | An apply whose push landed and whose *measurement* refused the node no longer demotes a node that was already serving: it stays `active` and in every link, the 502 says so, and the verdict is kept as the row's finding. A node not yet serving is still refused into service (`degraded`). Interrupted pushes still degrade (core invariants §4). | `test_a_false_red_on_a_serving_node_leaves_every_link_whole` — on the old code the link decoded to `''` after the press, exactly the walk's observation |
| **blocker** — "the port is held" is not "the node is serving" | The control half of `36d6b1b`: `apply.serving_checks` → `serving.confirm_serving(checks=…)` and `health.check_node(serving_checks=…)`. For a wg-family transport, holding the peers rendered into its config is what confirms it; the held port no longer does. | `test_a_held_port_does_not_make_a_wg_node_serving[peers=[]]` and `[squatter]`, `test_the_probe_asks_the_same_question_and_says_what_a_no_means` (both modes) — old code: apply 200, probe healthy |
| **high** — an unmeasured apply prints the healthy line | `apply.Applied.unmeasured`, `ApplyResponse.serving_unmeasured`, and a standing notice on the panel (`console.APPLIED_UNMEASURED`) instead of the toast. | `test_an_apply_without_ss_does_not_print_the_healthy_line` |
| **medium** — a verdict never improves on its own | `health.remeasure_forever` in the lifespan: every 60 s (`HASHI_FINDING_REMEASURE_INTERVAL`, `0` = off) probes each `active` node carrying a finding. Degraded nodes are deliberately not re-measured or promoted. | `test_a_finding_on_a_serving_node_is_re_measured_without_a_press` |
| **low** — withdrawn-access note with zero revoked users | Shown only when someone is revoked. | `test_no_withdrawal_note_when_nobody_was_withdrawn` |

Skipped by the owner's instruction: the 14 hand-typed numbers per hop.

Accept-direction twins, so none of the refusals can pass on a product that refuses
everything: a wg node holding its peers applies with nothing unmeasured and probes green;
a wg node with no `ss` is still MEASURED by its own check; a node whose image lacks the
tool (exit 127) applies, unmeasured, refused by nothing.

## Tests changed, and why each is not a weakened test

- `test_apply_must_reach_the_daemon.py::test_a_daemon_that_did_not_come_back_on_this_config_fails_loudly`
  asserted `degraded` for a stale daemon on an already-active node. Now asserts `active`,
  the verdict as the row's finding, and the 502 still saying so — the owner's rule, and
  M1's "fails loudly" is untouched.
- `test_a_probes_finding_outlives_the_banner.py::test_an_apply_that_could_not_confirm_the_daemon_clears_nothing`
  asserted a `state_detail`, which only a demotion writes. Still asserts the probe's finding
  is kept verbatim; now also that the node stayed active and the banner names both the fault
  and that it stays in users' links.
- `test_a_user_added_since_the_last_apply_is_not_on_the_nodes.py::test_the_users_screen_says_it_too…`
  now revokes somebody first, which is what makes the withdrawal note true of that fleet.
- `conftest.accepting_nodes` answers the serving question YES, for the reason it already
  answers the port question "held".

## What only a real-host walk can confirm

- That `docker compose exec -T amneziawg awg show amneziawg peers` on the pinned image
  prints what the fake prints (one key per line) — `tests/e2e/edge/test_the_serving_check_meets_the_real_daemon.py`
  from `36d6b1b` runs the real daemon on the stand, but not on the owner's hosts.
- Walk 4's two contrived hosts again (`nc` on the port; the real daemon with its peer
  removed) — apply and probe must now both refuse, in the transport's own words.
- The false-red case on the owner's Shape (control + entry on one Russian box): a slow
  entry must leave `GET /sub/{token}` whole, and the finding must clear itself within
  about a minute of the host actually serving.
- The outer edge of the waiting window (a container down past the window that then
  recovers) is still untested anywhere; the re-measure loop is now what is expected to
  clear its finding.

## Decided by the owner the same day, and built

- An apply that cannot reach an ACTIVE host at all (no session opened, nothing written)
  no longer degrades it: it stays in every link and the operator is warned. Test:
  `test_a_serving_node_nobody_could_reach_stays_in_every_link` (red before: the link
  decoded to `''`). Unchanged, with tests: a draft that cannot be reached stays out; a
  host that drops after the session opened is still degraded (§4). A record with no
  usable SSH address or key still degrades (`target_for`) — see the decisions row.
