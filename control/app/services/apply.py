"""Rendering a node's configuration and pushing it — backlog item 14.

WHAT: ``apply_node`` (render every enabled transport, validate, push, restart,
      verify) and ``apply_many`` (do that for a set of node-transports).
WHY:  this is the half of criterion 6 that the database cannot do. Deleting a
      friend's credential rows changes what we WOULD render; until the new config
      reaches every node, the running daemon still authorises them. It is also the
      half of criterion 2 that makes a replacement node real rather than recorded.
HOW:  the order is the contract, and every step exists because skipping it produces
      a specific failure:

      1. render from the database (pure, deterministic);
      2. validate with the upstream checker — never push a config the daemon will
         reject, because it restarts into a crash loop and the node is down;
      3. place the config and the compose file;
      4. restart;
      5. verify it came back;
      6. record the digest, so drift is detectable afterwards.

      Any failure from step 3 onward marks the node DEGRADED, never active — core
      invariants §4. A node that is half-configured and reported as fine gets
      friends routed onto it, and the bug report is about their client.
"""

import datetime
import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.errors import NodeOperationFailed
from control.app.models import (
    Credential,
    Node,
    NodeState,
    NodeTransport,
    TransportPurpose,
)
from control.app.services import nodes, relay
from control.app.settings import Settings
from edge import checker
from edge.bootstrap import NodeConnection, NodeTarget, NodeUnreachable, node_stack
from edge.node import Credential as EdgeCredential
from edge.registry import profile

logger = logging.getLogger(__name__)

# The upstream image pins used to live here. They are now in
# ``edge/bootstrap/node_stack.py`` (``DATA_PLANES``), keyed by config FORMAT — naming a
# daemon is naming a protocol, and `control` is not allowed to do either.
async def render_for_node(session: AsyncSession, node: Node) -> dict[str, str]:
    """Every enabled transport's config for one node, keyed by transport name.

    Pure with respect to the node: it reads the database, then renders. Each
    transport gets exactly the friends who hold a live credential on it, which is
    what makes the rendered file the authoritative answer to "who can use this node".
    """
    rendered: dict[str, str] = {}
    view = nodes.node_view(node)

    # Queried rather than read off ``node.transports``. The relationship loads eagerly
    # when the node is freshly selected, but this function is also called right after a
    # revocation has deleted rows in the same session — at which point touching the
    # collection can trigger a lazy refresh, and lazy I/O on an async session raises
    # MissingGreenlet rather than quietly issuing a query.
    listed = await session.execute(
        select(NodeTransport)
        .where(NodeTransport.node_id == node.id)
        .where(NodeTransport.enabled.is_(True))
        .order_by(NodeTransport.transport_name)
    )

    for node_transport in listed.scalars().unique():
        # A hop end is rendered as a PAIR with its far end, not as a server with a list
        # of friends — see services/relay.py. Dispatched on the stored purpose, which
        # is topology, never on the transport's name.
        if node_transport.purpose in TransportPurpose.relays():
            peer = await relay.peer_of(session, node_transport)
            rendered[node_transport.transport_name] = relay.render_end(
                node_transport, peer
            )
            continue

        result = await session.execute(
            select(Credential).where(Credential.node_transport_id == node_transport.id)
        )
        credentials = [
            # The friend's own client-scoped material travels with the subject, and it
            # has to. A VLESS server config needs only the subject, so this looked
            # unnecessary until a WireGuard-family transport became friend-facing (item
            # 27): its server config authorises each peer by the peer's PUBLIC key,
            # which lives here. Without it, applying such a node raised KeyError deep
            # in a renderer — and the first place that showed up was a revocation
            # returning 500, because revocation re-pushes every node the friend was on.
            #
            # Handed over whole rather than filtered: which parts of its own client
            # material belong in a server config is the transport's business, and
            # picking them here would mean `control` recognising field names. That a
            # friend's PRIVATE half never reaches a server config is asserted instead —
            # see tests/control/test_second_subscription_format.py.
            EdgeCredential(subject=row.subject, secrets=json.loads(row.secrets))
            for row in result.scalars().unique()
            # A revoked friend's rows are deleted rather than flagged, so this is a
            # belt-and-braces filter rather than the mechanism — see
            # services/friends.py:revoke for why deletion is the real guarantee.
            if row.friend.is_active
        ]
        # Sorted so the rendered config is byte-stable regardless of row order,
        # which is what makes the applied digest a drift signal rather than noise.
        credentials.sort(key=lambda credential: credential.subject)

        transport = profile(node_transport.transport_name)
        try:
            rendered[node_transport.transport_name] = transport.profile.render_server(
                view, nodes.render_params(node_transport), credentials
            )
        except NodeOperationFailed:
            raise
        except Exception as exc:
            # A renderer that refuses is a NODE-level failure, not a crash. Renderers
            # refuse on purpose — the WireGuard family, for one, refuses to write two
            # peers onto one tunnel address rather than emit a file where the second
            # silently takes over the first's route — and the operator has to read that
            # sentence, on the node's page, with the node left degraded.
            #
            # Before this, such a refusal escaped as a 500. The path it escaped through
            # was the worst available: revocation re-pushes every node the friend was
            # on, so an unrelated node's rendering problem made "remove this person's
            # access" answer "internal error" — and the operator has no way to tell
            # whether the removal happened.
            #
            # Logged with its traceback before it is converted, because the conversion
            # is deliberately broad: transport exceptions share no base class (giving
            # them one in `control` would mean importing a protocol's own module here),
            # so this arm also catches a genuine bug in a renderer. A domain error is
            # reported to the operator without a stack trace, so without this line a
            # typo in a template would leave no trace anywhere. No key material can
            # reach the log: the exception message is the transport's, and the rendered
            # config is not passed.
            logger.exception(
                "rendering %s for node %s failed", node_transport.transport_name, node.id
            )
            # The message is the transport's own; nothing here interprets it. Note the
            # rendered text is NOT included: it holds key material.
            raise NodeOperationFailed(
                f"{node_transport.transport_name} could not be rendered for this node "
                f"— {type(exc).__name__}: {exc}"
            ) from exc

    return rendered


def target_for(node: Node, node_settings: Settings) -> NodeTarget:
    """How to reach a node over SSH, from its record."""
    if not node.ssh_host:
        raise NodeOperationFailed(
            "this node has no SSH address, so its configuration cannot be pushed"
        )
    return NodeTarget(
        host=node.ssh_host,
        port=node.ssh_port,
        username=node.ssh_user,
        private_key=node.ssh_private_key,
        host_key=node.ssh_host_key,
        connect_timeout=node_settings.node_connect_timeout,
        timeout=node_settings.node_ssh_timeout,
    )


def validate_before_push(transport_name: str, config: str, config_format) -> None:
    """Refuse to push a config the daemon would reject.

    Treats "no checker installed" and "checker cannot open a referenced file" as
    NOT-CHECKABLE rather than as a rejection, and proceeds. That is a deliberate,
    narrow allowance, and the reasoning is in ``edge/checker.py``: ``xray -test``
    builds the TLS context, so a config naming a certificate file fails locally even
    when it is perfectly valid on the node where that file exists. Failing closed
    here would make the WS+TLS transport unpushable forever.

    What is never allowed through is a config the checker actually understood and
    rejected — a syntax or schema error, which would restart the node into a crash
    loop.
    """
    result = checker.validate(config, config_format=config_format)

    if not result.available:
        logger.warning(
            "pushing %s without upstream validation — no checker installed. Install it "
            "with scripts/fetch-upstream-checkers.sh",
            transport_name,
        )
        return

    if result.ok:
        return

    # A missing local file is the known not-checkable case, not a bad config.
    if "no such file or directory" in result.output.lower():
        logger.info(
            "%s references a file that exists only on the node; local validation "
            "skipped, node-side verification still applies",
            transport_name,
        )
        return

    raise NodeOperationFailed(
        f"the rendered configuration for {transport_name!r} was rejected by the "
        f"upstream checker, so it was NOT pushed: {result.output[:300]}"
    )


async def apply_node(session: AsyncSession, *, node_id: str) -> dict[str, str]:
    """Render, validate, push and verify one node. Returns what was applied.

    Marks the node degraded on any failure after the first byte is written, and
    active only once it came back up serving every transport we expect.
    """
    node = await nodes.get_node(session, node_id)
    node_settings = settings()

    configs = await render_for_node(session, node)
    for transport_name, config in configs.items():
        # The FORMAT comes from the transport's own declaration, so the right checker
        # runs without this module knowing which protocol it is looking at.
        validate_before_push(
            transport_name, config, profile(transport_name).meta.config_format
        )

    compose = node_stack.render_compose(
        transports=node_stack.services_for(sorted(configs))
    )

    try:
        async with NodeConnection(target_for(node, node_settings)) as connection:
            # Persist a learned host key on the FIRST successful connection, so every
            # later connection is pinned and an interception fails loudly.
            if connection.learned_host_key and not node.ssh_host_key:
                node.ssh_host_key = connection.learned_host_key

            await node_stack.prepare(connection)
            for transport_name, config in configs.items():
                await node_stack.place_config(
                    connection,
                    transport_name=transport_name,
                    config=config,
                    path=node_stack.config_path_for(transport_name),
                )
            await node_stack.place_compose(connection, compose=compose)
            await node_stack.restart(connection)

            # Verify rather than assume. `docker compose up -d` returns success as
            # soon as the containers are created — a daemon that starts and
            # immediately exits on a bad config satisfies that and serves nothing.
            running = await node_stack.running_services(connection)
            not_running = sorted(set(configs) - set(running))

    except (NodeUnreachable, node_stack.NodeStackUnsupported) as exc:
        await nodes.set_node_state(
            session, node_id=node.id, state=NodeState.DEGRADED, detail=str(exc)[:500]
        )
        raise NodeOperationFailed(
            f"the node could not be configured and has been marked degraded: {exc}"
        ) from exc

    if not_running:
        detail = f"pushed, but these did not come up: {', '.join(not_running)}"
        await nodes.set_node_state(
            session, node_id=node.id, state=NodeState.DEGRADED, detail=detail
        )
        raise NodeOperationFailed(
            f"configuration was applied but the node is not serving it — marked "
            f"degraded: {detail}"
        )

    now = datetime.datetime.now(datetime.UTC)
    for node_transport in node.transports:
        if node_transport.transport_name in configs:
            node_transport.applied_at = now
            node_transport.applied_digest = node_stack.digest_of(
                configs[node_transport.transport_name]
            )

    node.state = NodeState.ACTIVE
    node.state_detail = None
    await session.commit()
    logger.info("node applied: %s (%d transports)", node.id, len(configs))
    return configs


async def apply_many(
    session: AsyncSession, node_transports: list[NodeTransport]
) -> dict[str, str | None]:
    """Apply every node named by a set of node-transports. Returns per-node outcome.

    Used by revocation, where several nodes must be re-pushed at once. Every node is
    attempted even if an earlier one failed — stopping at the first failure would
    leave a revoked friend live on nodes that were perfectly reachable, which is the
    exact failure criterion 6 forbids. Failures are collected and reported.
    """
    outcomes: dict[str, str | None] = {}
    for node_id in dict.fromkeys(nt.node_id for nt in node_transports):
        try:
            await apply_node(session, node_id=node_id)
            outcomes[node_id] = None
        except NodeOperationFailed as exc:
            # Recorded, not raised: the caller needs the whole picture to tell the
            # operator which nodes still carry the revoked credential.
            logger.error("apply failed for node %s during fan-out", node_id)
            outcomes[node_id] = exc.message
    return outcomes


# Set once by the application factory. A module-level accessor rather than a
# parameter on every function because these are called from routes, from the panel
# and from revocation, and threading settings through all three adds a parameter
# nobody reads.
_settings_instance: Settings | None = None


def bind_settings(settings: Settings) -> None:
    global _settings_instance
    _settings_instance = settings


def settings() -> Settings:
    """The bound settings, or a loud failure. Public: services/health.py uses it."""
    if _settings_instance is None:
        raise RuntimeError("bind_settings() must run before any node operation")
    return _settings_instance
