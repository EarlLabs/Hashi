# M21 — carry-over

Non-blocking findings left open, with the reason each was left. Read them as
BACKGROUND: they tell you what is known-wrong so you do not mistake it for the
intended design. Do not fix them as part of another step.

## From M21.1, review round 1

- **Low** — `tests/control/test_first_apply_failure.py:227` applies
  `assert_plain_reason` to `raised.value.message`, whose wrapper prefix ("the node
  could not be configured and has been marked degraded: …") on its own supplies
  more than the four prose words the helper needs. Under the reviewer's
  bare-class-name mutation this was the one unreachable-path test that stayed
  green, and the stored `state_detail` is not checked there at all. The property
  is covered by the other four call sites, so this is a tightening rather than a
  hole. Fix would be: also read the node back and
  `assert_plain_reason(node.state_detail, refusing_ssh.host, ADVERTISED_ADDRESS)`,
  keeping the existing message-level assertions. (Line number and helper
  signature updated after M21.2 — the finding itself is unchanged.)

## From M21.2, review round 2

Nothing left open. Round 1's Medium (the no-leak check had narrowed to the
dialled endpoint and no longer guarded the node's advertised address) and its Low
(an fd leaked if `_bound_loopback_socket`'s `bind` raised) were both fixed in
`808d97a` rather than carried, and round 2 verified each by mutation. They are
recorded here only so the sequence is legible: a clean verdict was returned first
and the fixes were asked for anyway, because a milestone about a trustworthy gate
is the wrong place to bank a coverage reduction.
