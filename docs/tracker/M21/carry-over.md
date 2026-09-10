# M21 — carry-over

Non-blocking findings left open, with the reason each was left. Read them as
BACKGROUND: they tell you what is known-wrong so you do not mistake it for the
intended design. Do not fix them as part of another step.

## From M21.1, review round 1

- **Low** — `tests/control/test_first_apply_failure.py:206` applies
  `assert_plain_reason` to `raised.value.message`, whose wrapper prefix ("the node
  could not be configured and has been marked degraded: …") on its own supplies
  more than the four prose words the helper needs. Under the reviewer's
  bare-class-name mutation this was the one unreachable-path test that stayed
  green, and the stored `state_detail` is not checked there at all. The property
  is covered by the other four call sites, so this is a tightening rather than a
  hole. Fix would be: also read the node back and
  `assert_plain_reason(node.state_detail, address=UNREACHABLE_ADDRESS)`, keeping
  the existing message-level assertions.
