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
