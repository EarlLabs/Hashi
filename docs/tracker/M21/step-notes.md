# M21 — step notes

Conventions established here. They bind later steps, and later milestones in
this codebase, until something supersedes them. Follow them; do not relitigate.

## Asserting that the operator was told something (M21.1)

`tests/control/conftest.py` holds **`assert_plain_reason(reason, *addresses)`** —
import it as `from .conftest import assert_plain_reason`. That import idiom works
in `tests/control` under `--import-mode=importlib`; the precedent is
`tests/control/test_migrations.py:32`. (`tests/edge/test_upstream_validation.py`
warns the idiom is "not reliable" and uses a fixture instead — follow each zone's
own precedent.)

It asserts the **property**, not the sentence: non-empty after strip, one line,
no traceback markers, at least four ordinary lowercase words, and **every address
the node is known by** absent. It accepts every real arm (`the node did not answer
within 1s`, `could not establish an SSH session: ConnectionRefusedError`) and
rejects `None`, `""`, `OSError`, `OSError(113, …)`, `[Errno 113] …`, a dotted
exception path, a traceback, and any text carrying an address.

At least one address is **required at runtime** (`assert addresses`), so the
variadic signature is not a silent no-op — `assert_plain_reason(text)` fails, and
the pre-M21.2 keyword form `address=` now raises `TypeError`. Both are loud.

**Where the fact lives, separately from the wording:** `HealthResponse.reachable
is False` on the health path, and `isinstance(raised.value.__cause__,
NodeUnreachable)` on the apply path — that is the only arm of `apply_node` that
raises `from` a `NodeUnreachable`. Assert the fact and the wording separately; a
prose heuristic alone cannot tell a real reason from a plausible-looking one.

`INTERNAL_ERROR_COMPLAINT = "unexpected internal error"` is asserted **absent**
alongside the existing `TRANSITION_COMPLAINT`, so a genuine bug in `apply_node`'s
broad catch cannot satisfy "a plain reason".

## A node is known by two addresses, and both must be checked (M21.2)

Both files use the constant `ADVERTISED_ADDRESS` (an RFC 5737 documentation
address) for the node's `address` column — what a *friend* would dial. It is
never dialled by any test. What `control` dials is the node's
`ssh_host`/`ssh_port`, supplied by one of two conftest fixtures:

- **`unanswering_ssh`** — loopback, `listen()`s and never `accept()`s, so the
  kernel completes the handshake, asyncssh's banner goes unanswered and
  `asyncio.wait_for` in `edge/bootstrap/ssh.py` ends it at `connect_timeout`.
  Used by `test_node_timeouts.py`, which needs a real blackhole. No thread, no
  `accept()` — the shape behaves identically on BSD.
- **`refusing_ssh`** — loopback, **bound and never listening**, so every connect
  is one RST from the local kernel. Used by `test_first_apply_failure.py`. A
  merely *closed* port is not equivalent and is wrong: another process can take
  it mid-test, and a closed ephemeral port can be handed back to the connecting
  socket as its own source port, at which point TCP self-connects and the node
  answers. Holding the bind rules out both.

Both yield a `LoopbackSSH(host, port)` NamedTuple. A test node is registered by
passing `ssh_host=` / `ssh_port=` to `POST /api/nodes` alongside the advertised
`address`.

**Always pass both:** `assert_plain_reason(text, <fixture>.host, ADVERTISED_ADDRESS)`.
Until M21.2 a node's two addresses held the same string — `ssh_host` falls back to
`address` in `control/app/services/nodes.py` — which is the only reason one
argument ever looked sufficient. It was not: proven by mutation, a reason
carrying the advertised address passed all seven leak assertions before this was
widened.

**The timing assertion has a floor as well as a ceiling.** `elapsed >=
node_connect_timeout / 2` sits beside the pre-existing `< node_connect_timeout *
10`. The ceiling alone is trivially satisfied by anything that refuses fast, so
the floor is the half carrying the claim; it fails if the unanswering target is
ever repointed at a refusing one. It cannot flake, because load only ever pushes
elapsed up.

**The determinism convention, stated generally:** *the test opens the thing it
depends on.* If a behaviour is a property of the host — a routing table, a `sleep`
implementation, a shell builtin — either provide it yourself or skip with a reason
the reader can act on. Never assert on what the host happens to do.

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
