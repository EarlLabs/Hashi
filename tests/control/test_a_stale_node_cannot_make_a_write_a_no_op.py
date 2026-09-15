"""A write that reports success has to have written — M23.

WHAT: the three writes a node record admits after it exists — ``set_node_state``,
      ``set_resolver``, ``set_ssh_key`` — and the one that turns a transport on and off
      for friends (``set_transport_enabled``), each asked to change a row that has moved
      since the calling session last read it.
WHY:  all four decide whether to write by comparing the new value against the object
      their caller's session is holding, and skip the write when the two agree:
      a retried click is not an event, and a retry after a failed apply has to be safe.
      That is right, and the comparison was against the wrong thing. Sessions here keep
      what they loaded (``expire_on_commit=False``, ``control/app/db.py``), so once
      anything else has committed a change to that node the copy in hand is a
      photograph. The answer came back "no change", nothing was written, the caller was
      told it had worked, and the row still said what it said before — the same failure
      shape as the probe calling a crash-looping transport serving and the revoke saying
      a live link was dead.

      It is not only a lost write. ``set_node_state`` reads the same stale value to
      decide whether the transition is ALLOWED, so a node something else retired still
      looks draft — and ``retired -> active``, the one transition the state machine
      exists to refuse, goes through as ``draft -> active``, putting a destroyed host's
      address back into every friend's subscription.
HOW:  two sessions against one real Postgres, which is what this actually is: the test's
      own session holds the node, and the SECOND change arrives through the API or the
      panel, in the request's own session, the way it does in the field. What is
      asserted is always the row — read as a column rather than as an object, because a
      ``select(Node)`` in a session that is holding one hands back the copy it is
      holding and would agree with the bug.

Boundary: no host is dialled and nothing is rendered. The claim is about what is in the
database after a call that returned successfully.
"""

import asyncssh
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.errors import Conflict
from control.app.models import AuditEntry, Node, NodeState, NodeTransport
from control.app.services import nodes

from .conftest import GENERATED_SSH_KEY

# RFC 5737 documentation addresses, as everywhere in this zone.
NODE_ADDRESS = "192.0.2.70"
A_RESOLVER = "192.0.2.53"
ANOTHER_RESOLVER = "198.51.100.53"

# A second key, so "the key this session means" and "the key the row holds" can differ.
# Generated per run for the reason ``conftest.GENERATED_SSH_KEY`` is: a private key in a
# repository is a private key in a repository, even a useless one.
ANOTHER_SSH_KEY = (
    asyncssh.generate_private_key("ssh-ed25519").export_private_key("openssh").decode()
)

# A host key is the PUBLIC half — it is what a node presents, and it is the one piece of
# key material in this file that may safely be compared in an assertion.
A_LEARNED_HOST_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIexampleexampleexampleexample"


async def a_node(client, *, name: str) -> str:
    created = await client.post(
        "/api/nodes",
        json={"name": name, "address": NODE_ADDRESS, "location_label": "Testland"},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def in_the_row(session: AsyncSession, node_id: str, column) -> object:
    """One column as the database holds it, whatever this session is holding.

    A column select rather than ``select(Node)``: the ORM answers a whole-entity query
    out of the identity map when it already has the row, so an object read would return
    the very copy whose staleness is the subject and every assertion below would pass
    against the defect.
    """
    return (await session.execute(select(column).where(Node.id == node_id))).scalar_one()


async def in_the_transport_row(session: AsyncSession, node_transport_id: str, column) -> object:
    """The same read, for the row that decides whether a transport is offered."""
    return (
        await session.execute(select(column).where(NodeTransport.id == node_transport_id))
    ).scalar_one()


async def recorded(session: AsyncSession) -> list[str]:
    """Every action in the audit trail, oldest first."""
    result = await session.execute(select(AuditEntry.action).order_by(AuditEntry.at, AuditEntry.id))
    return list(result.scalars().all())


# --- the write reaches the row ------------------------------------------------

async def test_a_state_change_reaches_a_row_another_session_moved(client, session) -> None:
    """The failure as it was found: a panel POST degrades the node, the operator puts it
    back, and nothing happens.

    The second call is the one under test. Its caller is holding an ``active`` node, the
    row says ``degraded``, and ``active`` is what it asks for — so before this fix the
    comparison found no change, no ``UPDATE`` was emitted, the call returned the node it
    had been holding all along, and the node stayed out of every subscription.

    ``state_detail`` is asserted for the same reason and it is not decoration: the reason
    a node was degraded belongs to the state it was degraded in, and a row left reading
    ``active`` with a push failure still written on it is what the Nodes screen would
    then show the operator.
    """
    node_id = await a_node(client, name="leaf-1")
    # Bound, and it has to be: the identity map holds its objects WEAKLY, so an
    # unreferenced node is collected and the next read goes to the database by accident.
    # That is what made the defect look like a flake — it depended on a garbage
    # collection, and a test that does not hold the copy proves nothing on the mutation.
    held = await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)

    degraded = await client.post(
        f"/api/nodes/{node_id}/state",
        json={"state": "degraded", "detail": "the push never reached the host"},
    )
    assert degraded.status_code == 200, degraded.text

    moved = await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)

    assert moved is held
    assert await in_the_row(session, node_id, Node.state) == NodeState.ACTIVE
    assert await in_the_row(session, node_id, Node.state_detail) is None


async def test_a_resolver_reaches_a_row_another_session_moved(client, session) -> None:
    """The same hole in the first of the two fields a node record admits after it exists.

    An operator who set a resolver, had it changed elsewhere, and set it back to what
    they meant was told the record held their value while it held the other one — and a
    resolver is what decides whose network a friend's lookups leave through.
    """
    node_id = await a_node(client, name="leaf-2")
    held = await nodes.set_resolver(session, node_id=node_id, resolver=A_RESOLVER)

    changed = await client.post(
        f"/api/nodes/{node_id}/resolver", json={"resolver": ANOTHER_RESOLVER}
    )
    assert changed.status_code == 200, changed.text

    put_back = await nodes.set_resolver(session, node_id=node_id, resolver=A_RESOLVER)

    assert put_back is held
    assert await in_the_row(session, node_id, Node.resolver) == A_RESOLVER


async def test_an_ssh_key_reaches_a_row_another_session_moved(client, session) -> None:
    """And in the second — the credential that reaches every host in the fleet.

    The assertion is a boolean computed first rather than a comparison pytest would
    rewrite, because a failure here would otherwise print two private keys into the run's
    output. Nothing in this file may put key material on a screen.
    """
    node_id = await a_node(client, name="leaf-3")
    held = await nodes.set_ssh_key(session, node_id=node_id, ssh_private_key=GENERATED_SSH_KEY)

    replaced = await client.post(
        f"/panel/nodes/{node_id}/ssh-key",
        data={"ssh_private_key": ANOTHER_SSH_KEY},
        headers={"HX-Request": "true"},
    )
    assert replaced.status_code == 200, replaced.text

    await nodes.set_ssh_key(session, node_id=node_id, ssh_private_key=GENERATED_SSH_KEY)

    stored_is_the_one_just_set = (
        await in_the_row(session, node_id, Node.ssh_private_key) == GENERATED_SSH_KEY
    )
    assert held.id == node_id
    assert stored_is_the_one_just_set, (
        "the row still holds the key the other session wrote, and the call that replaced "
        "it reported success"
    )


async def test_a_withdrawal_reaches_a_row_another_session_moved(
    client, session, reality_params
) -> None:
    """The same shape one table over, and the half of criterion 3 it would cost.

    Enabling a transport from the panel reaches every friend's subscription; turning it
    off has to take it back out of every friend's subscription, with nobody touching
    their device. Decided against a copy that was withdrawn once already, the second
    withdrawal finds nothing to do and answers the operator with a toast while the row
    stays offered.
    """
    node_id = await a_node(client, name="leaf-7")
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text
    node_transport_id = enabled.json()["id"]
    held = await nodes.set_transport_enabled(
        session, node_transport_id=node_transport_id, enabled=False
    )

    offered_again = await client.post(
        f"/api/transports/{node_transport_id}/state", json={"enabled": True}
    )
    assert offered_again.status_code == 200, offered_again.text

    withdrawn = await nodes.set_transport_enabled(
        session, node_transport_id=node_transport_id, enabled=False
    )

    assert withdrawn is held
    assert await in_the_transport_row(session, node_transport_id, NodeTransport.enabled) is False


# --- and the refusal is decided against the row too ---------------------------

async def test_a_transition_the_machine_refuses_is_refused_against_the_row(
    client, session
) -> None:
    """The dangerous direction, and the reason this is a safety fix rather than a tidy-up.

    ``retired`` is terminal on purpose: a retired node's host has usually been destroyed,
    and re-activating the record would put an address that may now belong to a stranger
    back into every friend's subscription (``NodeState.allowed_from``). Decided against a
    copy loaded before the retirement, the machine is asked ``draft -> active`` instead —
    which it permits — and the write goes through.
    """
    node_id = await a_node(client, name="leaf-4")
    held = await nodes.get_node(session, node_id)
    assert held.state == NodeState.DRAFT

    retired = await client.post(f"/api/nodes/{node_id}/state", json={"state": "retired"})
    assert retired.status_code == 200, retired.text

    with pytest.raises(Conflict):
        await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)

    assert await in_the_row(session, node_id, Node.state) == NodeState.RETIRED


# --- without breaking either thing the comparison was there for ---------------

async def test_a_genuine_no_op_still_writes_nothing_and_records_nothing(
    client, session, reality_params
) -> None:
    """The property the fix must not buy its way out of, over all four writes.

    Writing unconditionally would close every hole above and cost the thing the
    comparison exists for: a retried click would become an event in the audit trail, and
    a retried apply would record a state change that never happened.
    """
    node_id = await a_node(client, name="leaf-5")
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text
    node_transport_id = enabled.json()["id"]

    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    await nodes.set_resolver(session, node_id=node_id, resolver=A_RESOLVER)
    await nodes.set_ssh_key(session, node_id=node_id, ssh_private_key=GENERATED_SSH_KEY)
    await nodes.set_transport_enabled(
        session, node_transport_id=node_transport_id, enabled=False
    )
    after_the_first_time = await recorded(session)

    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    await nodes.set_resolver(session, node_id=node_id, resolver=A_RESOLVER)
    await nodes.set_ssh_key(session, node_id=node_id, ssh_private_key=GENERATED_SSH_KEY)
    await nodes.set_transport_enabled(
        session, node_transport_id=node_transport_id, enabled=False
    )

    assert await recorded(session) == after_the_first_time


async def test_an_edit_this_session_has_not_flushed_yet_survives_the_re_read(
    client, session
) -> None:
    """The second thing it must not cost, and the one that would have been silent.

    These sessions are built ``autoflush=False`` on purpose, so re-reading a whole node
    would DISCARD a pending edit rather than write it first — and ``apply_node`` has one
    in flight exactly here: it puts a learned SSH host key on the node inside the
    connection block, and a failure after that reaches ``set_node_state`` through
    ``apply._record_failure``. Losing it means the next connection to that host is
    unpinned again, with nothing anywhere to say so.

    Which is why the re-read names the columns the decision reads and no others.
    """
    node_id = await a_node(client, name="leaf-6")
    node = await nodes.get_node(session, node_id)
    node.ssh_host_key = A_LEARNED_HOST_KEY

    await nodes.set_node_state(
        session, node_id=node_id, state=NodeState.DEGRADED, detail="the host said no"
    )

    assert await in_the_row(session, node_id, Node.ssh_host_key) == A_LEARNED_HOST_KEY
