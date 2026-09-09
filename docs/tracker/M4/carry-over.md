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

## From M4.2's review

- **The "harmless" claim about `nodes.py:311` was wrong, and it is now M4.5.**
  The reviewer reproduced it: `state is not node.state` is *always* true because
  `Node.state` is a `String(16)` carrying a plain `str`, so a second failed apply
  raises `Conflict: degraded -> degraded`, `_record_failure` swallows it, and
  `state_detail` keeps the **first** failure's reason. Promoted out of carry-over
  into a step, because it defeats M4's own "done when".

- **Medium/Low — the node-stack doubles are unpinned** (`tests/control/test_revocation_push.py`).
  Well-justified and tightly scoped — only the host-touching calls are faked,
  `render_compose` and `digest_of` stay real — but a changed signature makes the
  double go silently green. Now M4.6.

## Verified NOT a problem, recorded so it is not re-litigated

- **No second lazy load survives on the revoke path.** The reviewer traced
  `revoke_friend → friends.revoke → apply_many → apply_node → render_for_node`
  and the untested hop/relay branch. `Node.transports` is `lazy="selectin"` (the
  hazard); `NodeTransport.node` and `Credential.node_transport`/`.friend` are
  `lazy="joined"` and safe. `relay.peer_of`/`hop_view` touch only the joined
  ones, so they are not a second instance of the same bug even though this
  step's tests do not reach them.
- **Filtering the digest write on rendered names rather than on `enabled` is not
  new behaviour** — the pre-fix code filtered the same way. It preserves existing
  semantics and only removes the lazy-load hazard.
