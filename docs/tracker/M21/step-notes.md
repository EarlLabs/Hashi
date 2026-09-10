# M21 — step notes

Conventions established here. They bind later steps, and later milestones in
this codebase, until something supersedes them. Follow them; do not relitigate.

## Asserting that the operator was told something (M21.1)

`tests/control/conftest.py` holds **`assert_plain_reason(reason, *, address)`** —
import it as `from .conftest import assert_plain_reason`. That import idiom works
in `tests/control` under `--import-mode=importlib`; the precedent is
`tests/control/test_migrations.py:32`. (`tests/edge/test_upstream_validation.py`
warns the idiom is "not reliable" and uses a fixture instead — follow each zone's
own precedent.)

It asserts the **property**, not the sentence: non-empty after strip, one line,
no traceback markers, at least four ordinary lowercase words, and the node's
address absent. It accepts every real arm (`the node did not answer within 1s`,
`could not establish an SSH session: OSError`) and rejects `None`, `""`,
`OSError`, `OSError(113, …)`, `[Errno 113] …`, a dotted exception path, a
traceback, and any text carrying the address.

**Where the fact lives, separately from the wording:** `HealthResponse.reachable
is False` on the health path, and `isinstance(raised.value.__cause__,
NodeUnreachable)` on the apply path — that is the only arm of `apply_node` that
raises `from` a `NodeUnreachable`. Assert the fact and the wording separately; a
prose heuristic alone cannot tell a real reason from a plausible-looking one.

`INTERNAL_ERROR_COMPLAINT = "unexpected internal error"` is asserted **absent**
alongside the existing `TRANSITION_COMPLAINT`, so a genuine bug in `apply_node`'s
broad catch cannot satisfy "a plain reason".

Fixture address constants: `UNANSWERING_ADDRESS` (`test_node_timeouts.py`) and
`UNREACHABLE_ADDRESS` (`test_first_apply_failure.py`). Both are already passed to
`assert_plain_reason` as `address=`, so the no-leak check follows any change to
them automatically.

## Provoking a failure mode the network will not give you

A one-file pytest plugin that rebinds `asyncssh.connect` to a coroutine raising
the error you want, loaded with `PYTHONPATH=<dir> pytest -p <module>`, keeping
the plugin **out of the repository** (scratchpad only). That is how both arms of
the flake were proven red-first, and how the reviewer independently checked the
new assertions still fail on a regression. It patches the library, so it is a
diagnostic — **not** a substitute for making the network itself deterministic.

## Do not relitigate

- No production code was touched by M21.1, and no operator-visible string moved.
- `tests/e2e/infra/test_panel_bootstrap.py:413` asserts `"did not answer" in
  combined` — the same coupling in a different zone. Left deliberately; it is
  `infra`, not this diff.
- `edge/bootstrap/ssh.py`'s OSError arm ends its sentence with a bare class name
  (`… : OSError`). It reads worse than the timeout arm's. Left deliberately —
  changing it is `edge` work and would defeat M21.1's own point.
