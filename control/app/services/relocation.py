"""Moving a node record onto a new host — M36.

WHAT: ``relocate_node`` (point an existing node at the host that replaced its old one:
      SSH host, account and port, optionally its address, and a fresh host-key pin) and
      ``host_plan`` (what a new host must be prepared with before that node can be
      applied onto it: the public half of the node's key and the ports it listens on).
WHY:  the charter's promise is that a lost host is replaced in minutes with no user
      touching a device. Until this module a node's ``ssh_host``, ``ssh_user`` and
      ``ssh_port`` were written once, at registration, and the pinned host key could
      not be reset — so the 2026-10-13 rebuild of a dead entry box was finished with a
      raw ``UPDATE nodes`` that bypassed the audit trail, and with an account named
      after the dead box re-created on the new one. Registering a second node instead
      would have handed every user a new node in their subscription and re-minted
      every credential on it.
HOW:  one service write, recorded in the trail by the node's NAME only (never an
      address, never a key — the trail's shape, ``models/audit.py``). It changes the
      record and not the host: the caller applies afterwards, and ``relocate_node``
      returns which nodes that apply has to include. Reached from the operator API
      (``POST /api/nodes/{id}/relocate``) and from ``control.cli relocate-node``.
"""

import dataclasses
import logging

import asyncssh
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.errors import DomainError, NotFound
from control.app.models import AuditAction, Node, TransportPurpose
from control.app.services import apply, audit, delivery, nodes, placement, relay
from control.app.settings import Settings
from edge.bootstrap.delivery_site import DELIVERY_PORT

logger = logging.getLogger(__name__)

# The widths the node columns hold, stated at the layer that refuses a value — the same
# pairing ``nodes.STATE_DETAIL_MAX_LENGTH`` keeps with its column.
SSH_HOST_MAX_LENGTH = 255
SSH_USER_MAX_LENGTH = 32
ADDRESS_MAX_LENGTH = 255
HOST_KEY_MAX_LENGTH = 1024

HOST_KEY_UNUSABLE = (
    "that is not an SSH host public key this control plane can pin (expected one line "
    "such as the contents of /etc/ssh/ssh_host_ed25519_key.pub). Nothing was changed."
)


@dataclasses.dataclass(frozen=True)
class Relocated:
    """What a relocation changed, and what has to be applied because of it."""

    node: Node
    changed: bool
    # Node ids to apply, this node first. A partner is listed when this node's ADDRESS
    # changed and the partner holds the hop end that dials it — ``edge.relay`` renders
    # the dialling end with the far end's address in it, and only that end.
    needs_apply: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class HostPlan:
    """What a fresh host needs before this node can be applied onto it."""

    node: Node
    # The OpenSSH public half of the key on the node record, for the host's
    # authorized_keys. ``None`` when the record holds no key yet.
    public_key: str | None
    # ``<port>/<tcp|udp>`` for every socket an apply will bind on the host that someone
    # off it has to reach — sorted, so two runs print the same list.
    ports: tuple[str, ...]


async def node_by_name(session: AsyncSession, name: str) -> Node:
    """The node an operator named. Names are unique (``create_node`` refuses a repeat)."""
    found = await session.execute(select(Node).where(Node.name == name))
    node = found.scalars().first()
    if node is None:
        raise NotFound(f"no node named {name!r}")
    return node


def _host_key_line(host_key: str) -> str:
    """The pin as one canonical OpenSSH line, or a refusal.

    Imported with the SAME call ``edge.bootstrap.ssh`` makes when it pins, so a value
    accepted here is one the connection can use; stored without its comment, in the shape
    a connection learns one.
    """
    if len(host_key) > HOST_KEY_MAX_LENGTH or "\n" in host_key.strip():
        raise DomainError(HOST_KEY_UNUSABLE)
    try:
        key = asyncssh.import_public_key(host_key.strip())
    except (ValueError, asyncssh.KeyImportError):
        raise DomainError(HOST_KEY_UNUSABLE) from None
    # Type and body only. A comment names the machine the key was read on, and the pin is
    # compared as a whole line against what a connection learns, which carries none.
    return " ".join(key.export_public_key().decode().split()[:2])


def _refuse_bad_coordinates(ssh_host: str, ssh_user: str, ssh_port: int, address: str | None):
    """The record's own widths and ranges — refused, never clipped."""
    if not ssh_host.strip() or len(ssh_host) > SSH_HOST_MAX_LENGTH:
        raise DomainError(
            f"the SSH host must be 1 to {SSH_HOST_MAX_LENGTH} characters. Nothing was changed."
        )
    if not ssh_user.strip() or len(ssh_user) > SSH_USER_MAX_LENGTH:
        raise DomainError(
            f"the SSH account must be 1 to {SSH_USER_MAX_LENGTH} characters. "
            "Nothing was changed."
        )
    if not 1 <= ssh_port <= 65535:
        raise DomainError("the SSH port must be a number from 1 to 65535. Nothing was changed.")
    if address is not None and (not address.strip() or len(address) > ADDRESS_MAX_LENGTH):
        raise DomainError(
            f"the address must be 1 to {ADDRESS_MAX_LENGTH} characters. Nothing was changed."
        )


async def _dialling_partners(session: AsyncSession, node: Node) -> list[str]:
    """Nodes whose hop end dials this one — the ends whose config carries its address."""
    partners: list[str] = []
    for end in await relay.hop_ends(session, node.id):
        if end.purpose != TransportPurpose.RELAY_LEAF or end.peer_node_transport_id is None:
            continue
        peer = await relay.peer_of(session, end)
        if peer.node_id not in partners:
            partners.append(peer.node_id)
    return partners


async def relocate_node(
    session: AsyncSession,
    *,
    node_id: str,
    ssh_host: str,
    ssh_user: str,
    ssh_port: int,
    address: str | None = None,
    host_key: str | None = None,
) -> Relocated:
    """Point a node record at the host that replaced its old one.

    THE PIN IS ALWAYS REPLACED, and that is the meaning of the operation rather than a
    side effect. A relocation is the operator saying "this node now lives on a different
    machine", and a different machine has a different host key by definition — that is
    true even when the new machine took over the old one's address, which is exactly the
    reinstalled-at-the-same-IP case. So the pin becomes ``host_key`` when one is given
    (the caller read it from the host over its own SSH session), and is cleared when none
    is — in which case the next apply learns it on first contact, as at registration.

    Rejected: keeping the old pin when the host did not change. A pin that no longer
    matches makes every apply fail with a host-key error, and "same coordinates, new
    machine" is the case this exists for.

    The node's STATE is not touched. Relocation changes where the control plane dials;
    whether the node serves is decided by the apply that follows, which degrades it on
    failure like any other apply.

    A call that changes nothing — same coordinates, same address, and the pin already
    equal to the ``host_key`` given — records nothing, like every other write here.
    """
    _refuse_bad_coordinates(ssh_host, ssh_user, ssh_port, address)
    pin = _host_key_line(host_key) if host_key else None

    node = await nodes._node_to_write(
        session, node_id, "ssh_host", "ssh_user", "ssh_port", "address", "ssh_host_key"
    )
    ssh_host, ssh_user = ssh_host.strip(), ssh_user.strip()
    new_address = address.strip() if address is not None else node.address
    address_changed = new_address != node.address

    changed = (
        ssh_host != node.ssh_host
        or ssh_user != node.ssh_user
        or ssh_port != node.ssh_port
        or address_changed
        or pin != node.ssh_host_key
    )
    partners = await _dialling_partners(session, node) if address_changed else []
    if changed:
        node.ssh_host = ssh_host
        node.ssh_user = ssh_user
        node.ssh_port = ssh_port
        node.address = new_address
        node.ssh_host_key = pin
        # The node's name and nothing else: an address against a time is the record this
        # trail was shaped to refuse, and an SSH host is an address.
        audit.record(session, AuditAction.NODE_RELOCATED, first_label=node.name)
        await session.commit()
        logger.info("node %s relocated", node.id)
    return Relocated(node=node, changed=changed, needs_apply=(node.id, *partners))


def _public_half(private_key: str | None) -> str | None:
    """The OpenSSH public line of the node's stored key. The private half stays here."""
    if not private_key:
        return None
    try:
        key = asyncssh.import_private_key(private_key)
    except ValueError:
        raise DomainError(nodes.SSH_KEY_UNUSABLE) from None
    return key.export_public_key().decode().strip()


async def host_plan(session: AsyncSession, node: Node, settings: Settings) -> HostPlan:
    """The key and the ports a fresh host needs for this node — asked of the record.

    PORTS, FROM WHAT AN APPLY WILL BIND: every enabled row users connect to, and every
    enabled hop end that WAITS to be dialled, each over the transport-layer protocols its
    transport declares (``placement.binds_of``). A dialling hop end binds nothing anyone
    reaches from outside. And the delivery listener's socket when this node would be
    given one (``delivery.listener_for``) — the same question the apply asks of the
    database, so the plan and the apply cannot disagree about it.

    What it does NOT include: the ports of anything else on the host — in particular a
    control plane sharing the box. That is a fact about the box, not the node record, and
    the command preparing the host reads it from the box.
    """
    enabled = await apply.enabled_transports(session, node)
    ports: set[str] = set()
    for row in enabled:
        if row.purpose == TransportPurpose.RELAY_ENTRY:
            continue
        port = placement.port_of(row.params or {})
        if port is None:
            continue
        for layer in placement.binds_of(row.transport_name):
            ports.add(f"{port}/{layer}")
    if delivery.may_serve_delivery(node, enabled) and delivery.listener_for(node, settings):
        ports.add(f"{DELIVERY_PORT}/tcp")
    return HostPlan(
        node=node,
        public_key=_public_half(node.ssh_private_key),
        ports=tuple(sorted(ports, key=lambda spec: (int(spec.split("/")[0]), spec))),
    )
