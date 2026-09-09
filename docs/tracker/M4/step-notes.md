# M4 — step notes

Conventions established here. They bind later steps, and later milestones in
this codebase, until something supersedes them. Follow them; do not relitigate.

## Sequencing — read this first

**M4 was moved ahead of M1 during the field run of 2026-09-08, on evidence.** The
first apply to a real host returned `409: a node cannot go from draft to
degraded` and the control plane logged exactly one line about it: `domain error:
conflict`. The underlying failure was destroyed while being handled. Recovering
it took a node health probe, an inspection of the host and reproducing the
command by hand — and it turned out to be a one-line permission error, now
milestone M13. M1 and M2 are diagnosed by applying to a live node and reading
what comes back, so M4.1 is the instrument they are diagnosed with, not a
follow-up to them.

## From M4.4 — bounded node operations

**The plan's premise was wrong and the correction is recorded in the plan
itself.** There *was* a connect timeout; it shared the 20-second budget used for
commands, and the suite paid it 23 times (measured with `--durations`: every dial
cost 20.2–20.4 s). What had **no ceiling at all** was the SFTP transfers and the
session close — a node that completes the handshake and then goes quiet hung
forever, which is a better description of a blocked node than a refused
connection is.

**Two ceilings now, and they must not be collapsed back into one.**
`NodeTarget.connect_timeout: int = 5` for reaching a node;
`NodeTarget.timeout: int = 20` for a command over a session already open;
`CLOSE_TIMEOUT = 5` at module level. `apply.target_for(node, settings)` is the
only place `control` builds a `NodeTarget` and it passes both.

**Cross-zone work never lands in one diff — this step learned it the hard way.**
The first attempt changed `edge/bootstrap/ssh.py` and `control/` together and was
rejected `1 high` against `CLAUDE.md`'s zone table and
`.claude/projects/00-core-invariants.md` §2. It was split into an `edge`-only
commit and a `control`-only commit, **each verified green on its own zone gate at
its own commit** — not merely split in the log. The `edge` half alone takes the
control suite from 7m36s to 2m32s; the `control` knob buys the rest, to 75s.
Expect the same standard.

**Testing an unreachable node in `tests/control` is now cheap** — about 1 s per
dial, because the `settings` fixture in `tests/control/conftest.py` sets
`node_connect_timeout=1`. No mocks and no fake SSH server needed. The pattern is
in `tests/control/test_node_timeouts.py`: create a node via `POST /api/nodes`
pointed at `192.0.2.10` (TEST-NET-1, reserved for documentation and therefore not
a hardcoded real address), then call the service directly.

**`health.check_node` is the reporting path that does NOT touch node state.** Use
it to assert a failure message without tripping the `draft → degraded` bug that
M4.1 is about. It is also how M13 was diagnosed in the field.

**`read_file` now RAISES `NodeUnreachable` on a transfer timeout** where its
neighbour returns `None` for a missing file. Deliberate: `None` means "the file
is not there", which drift detection reads as a difference, and a node that went
silent has told us nothing about the file. Its only production call site is
`edge/health/probe.py`, guarded by `control/app/services/health.py::check_node`.
Anything new calling `read_file` outside such a guard will propagate rather than
degrade to "absent".

**Operator-facing wording introduced here — these strings reach the panel, and
both new test files assert they contain no host, address or node-side path:**

- `the node did not answer within {n}s`
- `the node stopped responding while a file was being placed on it (after {n}s)`
- `the node stopped responding while a file was being read back (after {n}s)`

Later message work matches these rather than inventing a fourth shape.
## M4.1 — proven on real hardware, 2026-09-09

Same node, same transport, same apply, before and after the fix.

**Before** — API response:
```
{"error":{"code":"conflict","message":"a node cannot go from draft to degraded.
 From draft it may become: active, retired"}}
```
Whole log record of the failure:
```
INFO control.app.errors: domain error: conflict
```
Recovering the real cause took a node health probe, an inspection of the host's
filesystem, and reproducing the failing command by hand over SSH.

**After** — API response, status 502:
```
the node could not be configured and has been marked degraded: command failed (1):
'mkdir -p /opt/hashi/conf && chmod 700 /opt/hashi /opt/hashi/conf':
mkdir: cannot create directory '/opt/hashi': Permission denied
```
Node state `degraded`, with that same sentence in `state_detail`. Log:
```
ERROR control.app.services.apply: apply failed for node <id>: command failed (1):
  'mkdir -p /opt/hashi/conf && chmod 700 ...': mkdir: cannot create directory
  '/opt/hashi': Permission denied
INFO control.app.services.nodes: node <id> state -> degraded
INFO control.app.errors: domain error: node_operation_failed
```

The log line names the node id and the command that failed. It carries no
address and nothing about a connection, so it does not become the record the
charter forbids.

**This is the milestone justifying its own reordering.** M13 was found the hard
way an hour earlier; with M4.1 in place the same class of fault arrives in the
response body.
