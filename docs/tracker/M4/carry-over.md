# M4 — carry-over

Non-blocking findings left open, with the reason each was left. Read them as
BACKGROUND: they tell you what is known-wrong so you do not mistake it for the
intended design. Do not fix them as part of another step.

## From M4.4's review

- **`node_connect_timeout` is global to the fleet, not per-node.** Raising it for
  one real node on a congested link from Russia slows the fast-failure path for
  every other node, including one that genuinely is blocked — in tension with
  "revocation is the operation whose whole point is being fast". Raised by the
  reviewer explicitly as a limitation rather than a defect, since no per-node
  granularity was asked for.

  **The implementer's view, recorded because it is a concrete proposal:** it
  deserves its own *step*, not a milestone — one field on the node record plus a
  two-line fallback in `target_for`, in the shape the codebase already uses for
  `ssh_port` and `ssh_host` (`node.connect_timeout or settings.node_connect_timeout`).
  That keeps the fleet default as the answer for the common case and makes the
  congested-link node pay for itself alone. It needs a migration, which is why it
  is a step and not a drive-by. It suggests placing it after M4.1–M4.3, since it
  touches `target_for` in the same file those steps work in.

- **`apply_node` still serialises N node operations with no ceiling on the whole
  operation.** A fan-out across many dead nodes is bounded per node but additive
  in aggregate. Named by the implementer as out of scope for M4.4.

## From M4.1's review

- **Low — `control/app/services/apply.py` around the `NodeOperationFailed`
  raise.** The message says *"has been marked degraded"* even on the one
  reachable path where it was not: applying an already-`retired` node, where
  `_record_failure` correctly swallows the refused `retired → degraded`
  transition and the state does not change. The safety property holds —
  `retired` is never in `NodeState.serving()` — so this misleads about mechanism
  only, in a case an operator has to deliberately trigger, and
  `GET /api/nodes/{id}` shows the true state immediately. Left because rewording
  an operator-facing string is acceptance-visible and belongs to whoever owns
  that wording, not to a step about the state machine.

## Verified NOT a problem, recorded so it is not re-litigated

- A node that reaches `degraded` from `draft` is treated **identically** to one
  that reaches it from `active`: `NodeState.serving()` returns only `(ACTIVE,)`
  and `nodes.serving_transports` filters on it, so neither can enter a
  subscription. Nothing in the codebase branches on how a node reached its state
  — there is no state history and no audit table. Checked by the M4.1 reviewer
  against `serving()`, the panel template, `relay.py` and `health.py`.
- `NodeTransport.applied_at` stays NULL on a failed first apply — every failure
  path returns before it is set — so "which nodes have never worked" is still
  answerable without a dedicated state.
