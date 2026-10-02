"""Polling a node's health — backlog item 13, control side.

WHAT: renders what a node SHOULD be running, probes it, and reports the difference.
WHY:  the control plane polls; a node never dials us. And health is deliberately
      narrow: whether the node serves, not who used it. There is no code path in this
      module or the one it calls that could produce a per-user figure.
HOW:  renders through the same function the apply path uses, so "drifted" means the
      node differs from what we would push — not from a second, separately written
      idea of what should be there. "stale" is the same comparison against what the
      running PROCESS was started from, which is a different question and was the one
      nothing asked until M1.

      AND WHAT IT FOUND IS KEPT — M26's first acceptance walk. Until then a probe's
      answer lived exactly as long as the banner carrying it: the walk stopped a leaf's
      user-facing daemon, read the correct finding, reloaded once and saw ``active``
      beside ``in sync`` again on a node whose users were carrying nothing. So every
      probe that reaches a host writes what it found onto that host's own row
      (``nodes.record_probe``), in the words the operator read.

      WHAT CLEARS IT is a later probe — or an apply that took the same reading and got a
      different answer, which since M26's THIRD walk means one that watched the new
      containers stay up AND asked the node what is holding their ports. An apply that
      could not ask clears nothing. The rule and the two walks that produced it are at
      the clearing itself (``apply.apply_node``): an apply may only clear a finding it
      has contradicted, with a measurement of the same kind.

      AND WHERE EACH CONFIG SHOULD ANSWER — M22, the same division of labour one field
      over. The port is the operator's own parameter and the protocols are the
      transport's own declaration, so `control` resolves both and passes them in;
      `edge` reads the node's socket table and compares. What comes back is three
      answers per transport rather than two — listening, not listening, and nobody
      could ask — because collapsing the third into the second reports a host whose
      socket table could not be read as a fleet-wide outage.

      AND EACH TRANSPORT'S OWN SERVING QUESTION — M26's fourth walk, fix round 5. The
      held port was satisfied by ``nc`` and by a wg-family daemon holding none of its
      peers; a transport that declares what serving means for it is now asked that, and
      its NO is a finding like any other (``apply.serving_checks`` builds the questions).
"""

import asyncio
import contextlib
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.api import schemas
from control.app.db import Database
from control.app.errors import DomainError, NodeCannotServe
from control.app.models import Node, NodeState

# ``console`` for one function: the sentence a probe's answer becomes. It is composed
# there because the banner, the notice and now the node's own row must not come to three
# accounts of one answer, and this module is where the answer is produced — so the
# dependency points from the measurement to the wording rather than the other way, and
# nothing in ``console`` imports this module back.
from control.app.services import apply, console, nodes
from edge.bootstrap import NodeConnection, NodeUnreachable
from edge.health import probe

logger = logging.getLogger(__name__)


async def check_node(session: AsyncSession, *, node_id: str) -> schemas.HealthResponse:
    """Probe one node and report what it is actually doing.

    A node that cannot be reached is reported as unreachable rather than raising: the
    panel must be able to show a dead node's row, and an exception here would make one
    unreachable host break the whole nodes page.

    A node the state machine will not put back into service is REFUSED rather than dialled
    — M23, round 12, and the reasoning is at ``apply.CANNOT_BE_DIALLED``. It raises rather
    than answering ``reachable=False``, which would have been the smaller change and a
    lie: that field means this control plane tried and could not, and every list beside it
    is composed on the same promise. Nothing was tried here.
    """
    node = await nodes.get_node(session, node_id)

    # BEFORE anything is rendered, decrypted or dialled — the same place the apply door
    # asks it, through the same predicate, so the two buttons on one row cannot come to
    # different answers about one address.
    if apply.cannot_serve_again(node.state):
        raise NodeCannotServe(apply.CANNOT_BE_DIALLED.format(state=node.state))

    expected = await apply.render_for_node(session, node)
    # Which transport each placed config came from — the probe needs it to know which
    # EXTENSION the file on the node carries, and since M15 a config's name and its
    # transport's name are two strings (see ``apply.placed_transports``).
    placed = await apply.placed_transports(session, node)
    # And where each of them should be answering — the port off the row, the protocols
    # off the transport's declaration. A row neither can be resolved for is absent here,
    # and the probe then says its port was not checked rather than that it is silent.
    listeners = await apply.placed_listeners(session, node)
    # And each placed config's transport's OWN serving question — M26's fourth walk, the
    # one the port question above could not stand in for: ``nc`` on the number satisfied
    # it, and so did the real daemon holding none of its peers. Judged against the same
    # render as ``expected``, so "the peers it should hold" means what an apply would push.
    checks = apply.serving_checks(placed, expected)

    try:
        async with NodeConnection(apply.target_for(node, apply.settings())) as connection:
            health = await probe(
                connection,
                expected=expected,
                transports=placed,
                listeners=listeners,
                serving_checks=checks,
            )
    except NodeUnreachable as exc:
        unreachable = schemas.HealthResponse(
            node_id=node.id,
            reachable=False,
            healthy=False,
            running=[],
            restarting=[],
            missing=sorted(expected),
            drifted=[],
            # Empty rather than "everything": a node we could not reach has told us
            # nothing about what its containers are running, and reporting a guess as
            # a finding is the fault this milestone is about, one field over. The same
            # reasoning covers the two port answers: an unreachable node was never asked
            # what it is listening on, so neither list may name anything.
            stale=[],
            listening=[],
            not_listening=[],
            detail=str(exc),
        )
        # A node that could not be dialled is a finding as much as a crash loop is —
        # what it is NOT is a report about containers nobody looked at, and the empty
        # lists above are what keeps those two apart. The sentence recorded says the
        # host could not be reached and names the reason the SSH layer gave.
        await nodes.record_probe(
            session, node, finding=console.health_summary(node.name, unreachable)
        )
        return unreachable

    answer = schemas.HealthResponse(
        node_id=node.id,
        reachable=health.reachable,
        healthy=health.healthy,
        running=health.running,
        restarting=health.restarting,
        missing=health.missing,
        drifted=health.drifted,
        stale=health.stale,
        listening=health.listening,
        not_listening=health.not_listening,
        serving=health.serving,
        not_serving=health.not_serving,
        # What each answer MEANS, in the transport's own words — the console has no way
        # to know what a protocol's yes established, and must not guess.
        serving_means={
            name: checks[name].question.confirms
            for name in health.serving
            if name in checks
        }
        | {
            name: checks[name].question.refutes
            for name in health.not_serving
            if name in checks
        },
        detail=health.detail,
    )
    # ``None`` on a healthy answer, and the timestamp is written either way: a probe that
    # found nothing wrong is the reading that makes "never probed" a distinguishable
    # third state on the screens that report this.
    await nodes.record_probe(
        session,
        node,
        finding=None if answer.healthy else console.health_summary(node.name, answer),
    )
    return answer


# --- re-measuring a finding nobody pressed probe on — fix round 5 ------------------------
#
# WALK 4's FOURTH FINDING: a verdict never improved on its own. The apply waits a bounded
# window and stops; 35 seconds after one refused, the node was serving at 0% loss and the
# panel still read the refusal, because nothing measured the host again until a human
# pressed probe. Since this round a verdict on a node in service no longer demotes it (see
# ``apply.apply_node``), so what is left standing is a FINDING on a serving node's row —
# and a finding that is never re-measured is a warning that outlives its truth.
#
# DECIDED (docs/decisions.md, 2026-10-02):
#
# * A node IN SERVICE that carries a finding is re-measured on a timer, by exactly the
#   probe an operator would press (``check_node``), so the row's finding is cleared or
#   restated by a measurement of the same kind — the rule an apply already keeps.
# * A DEGRADED node is NOT re-measured automatically. Its way back into users' links is an
#   apply, which grants, pushes and re-measures in one act; a timer that found it serving
#   could only either promote it — putting a node into every user's link with no operator
#   act, which is the decision this panel exists to leave with the operator — or write a
#   note beside a state it cannot change. Neither is the smallest honest thing.
# * Nothing here changes a node's state, writes an applied digest or touches a user. It
#   records what a probe found, which is all a probe ever does.
#
# The loop is the control plane polling, which is the direction the topology allows: a
# node never dials in. It logs node ids and counts only — never an address, a transport
# parameter or anything a host printed.


async def nodes_to_remeasure(session: AsyncSession) -> list[str]:
    """The ids of every node in service that carries a finding, oldest finding first."""
    result = await session.execute(
        select(Node.id)
        .where(Node.state.in_(NodeState.serving()))
        .where(Node.last_probe_finding.is_not(None))
        .order_by(Node.last_probe_at, Node.id)
    )
    return list(result.scalars())


async def remeasure_findings(database: Database) -> int:
    """One pass: probe each node in service that carries a finding. Returns how many.

    One session per node, so a host that hangs or a probe that raises costs that node's
    reading and nobody else's. A refusal (``NodeCannotServe`` — the node left service
    between the select and the probe) and any other domain error are skipped quietly:
    the row already says what an operator needs, and this pass has nothing to add to it.
    """
    ids: list[str] = []
    async for session in database.session():
        ids = await nodes_to_remeasure(session)
    for node_id in ids:
        try:
            async for session in database.session():
                await check_node(session, node_id=node_id)
        except DomainError:
            continue
        except Exception as exc:
            # The TYPE only, never ``str(exc)``: an arbitrary error out of the SSH layer
            # can carry the host's address, and this line is written with nobody
            # watching. One node's failure does not end the pass for the others.
            logger.error("re-measuring node %s failed: %s", node_id, type(exc).__name__)
    return len(ids)


async def remeasure_forever(database: Database, *, interval: float) -> None:
    """Sleep, re-measure, repeat — until cancelled.

    Sleeps FIRST: a control plane that has just started has no reason to dial a host in
    its first second, and an apply that just recorded a verdict deserves the interval
    before a probe second-guesses it. A pass that fails is logged and the loop goes on —
    the audit sweeper's rule, for its reason: a loop that dies once dies silently.
    """
    while True:
        await asyncio.sleep(interval)
        try:
            remeasured = await remeasure_findings(database)
            if remeasured:
                logger.info("re-measured %d node(s) carrying a finding", remeasured)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "re-measuring nodes that carry a finding failed; next pass in %.0f seconds",
                interval,
            )


def start_remeasurer(database: Database, *, interval: float) -> asyncio.Task | None:
    """The loop as a task for the lifespan to hold, or ``None`` when it is turned off."""
    if interval <= 0:
        return None
    return asyncio.create_task(
        remeasure_forever(database, interval=interval), name="finding-remeasure"
    )


async def stop_remeasurer(task: asyncio.Task | None) -> None:
    """Cancel the loop and wait for it, for ``audit.stop_sweeper``'s reason."""
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
