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
      5. verify the daemon came back ON THIS CONFIG — not merely that a container
         exists, which is what M1 proved says nothing (see ``loaded_digests``);
      6. record the digest, so drift is detectable afterwards.

      Any failure from step 3 onward marks the node DEGRADED, never active — core
      invariants §4. A node that is half-configured and reported as fine gets
      friends routed onto it, and the bug report is about their client.
"""

import datetime
import enum
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.crypto import SecretUnreadable
from control.app.errors import (
    ConfigRefused,
    Conflict,
    DomainError,
    NodeOperationFailed,
    NothingToApply,
)
from control.app.models import (
    AuditAction,
    Credential,
    Node,
    NodeState,
    NodeTransport,
    TransportPurpose,
)
from control.app.services import addresses, audit, nodes, relay
from control.app.settings import Settings
from edge import checker
from edge.bootstrap import NodeConnection, NodeTarget, NodeUnreachable, node_stack
from edge.egress import ResolverMissing
from edge.registry import profile

logger = logging.getLogger(__name__)

# Where an operator finishes a push that did not land. A SCREEN, named in words, and
# never a page or a URL — that is the whole point of this constant existing rather than
# the sentence being written three times.
#
# It exists because the sentence it replaced outlived the surface it named. "Retry from
# the node's page" was true until M9.6 deleted that page, and it was still being drawn
# on the console afterwards: on an INCOMPLETE REVOCATION, which is the moment somebody
# who should be cut off is still connected, the operator was sent to a URL that 404s.
# A docstring naming a dead template is a nuisance; a live sentence naming one is the
# operator standing still at the only moment that matters.
#
# Every service sentence that tells an operator where to go uses this. A screen that
# moves moves here, and nothing composed in ``services/`` may name a page again.
#
# EXCEPT THE THREE REFUSALS BELOW, since M18's acceptance: they are answered to an API
# consumer as well as to the console, and naming a screen is the one thing an API message
# must not do. Their directions are written in the clauses under this and become the
# console's own words at ``panel/wording.for_the_page`` — the same seam decision 9 sends
# ``friend`` across, for the same reason. This constant stays because the sentences that
# are ONLY ever read on the console still use it (``services/console.py``, the incomplete
# revocation and rotation reports).
WHERE_TO_RETRY = "the Nodes screen"

# THE ONE CLAUSE PER REFUSAL THAT IS WRITTEN FOR A SCREEN — M18's acceptance, round 2.
#
# ``POST /api/nodes/{id}/apply`` was answering a script with "Enable a transport on it
# from the Nodes screen, then apply it" and "Nothing else in this panel stops a node
# serving what it was last given": right for the operator reading a banner, wrong in a
# JSON error body, where there is no panel and the caller is not looking at one.
#
# So the service says what is true of this control plane however it is driven, and the
# panel says it in its own words. Full sentences rather than fragments, because the
# translation is keyed on the whole of one: a clause that has to be spliced into another
# sentence is a mapping that goes stale silently the first time the sentence around it is
# rewritten, and these are keyed BY THE CONSTANT — the page's version is looked up with
# the value below, not with a copy of it (``panel/wording.py``).
#
# Nothing else in a refusal changes across the boundary. The substance — what was pushed,
# what the host is still running, what an apply can and cannot do — is the same fact for
# both readers and is written once.
ENABLE_ONE_HERE = "Enable a transport on this node, then apply it."
OFFER_ONE_AGAIN = (
    "Offer one of its transports again — which puts that transport back in every user's "
    "link — and apply."
)
NOTHING_STOPS_A_SERVING_HOST = (
    "Nothing else in this control plane stops a node serving what it was last given."
)

# What an operator is told when they press apply on a node that offers nothing — M18.1.
#
# This is the first button a new node's row invites, and until this sentence existed the
# answer to pressing it was a 502 quoting `services must be a mapping` from the node's
# own docker compose, with the node left degraded. Every part of that was working as
# designed: no enabled transport renders no config, no config makes an empty `services:`
# block, and M4 surfaces a node's real stderr verbatim rather than swallowing it. The
# situation is simply not a failure — a node with nothing enabled has nothing to serve —
# and the operator needed a sentence about transports, not about YAML.
#
# Refusal rather than a silent no-op, and the deciding case is not the console: the
# revocation fan-out re-pushes every node a withdrawn friend held a credential on, and a
# withdrawn row KEEPS its minted credentials, so a node whose last row was withdrawn
# arrives here with nothing to render while its container is still running the config
# that authorises that person. A no-op would report such a node as updated. It is
# reported as not updated instead, and ``why_not_updated`` calls it REFUSED.
#
# Where they send an operator is the clause above, translated into the console's own
# words at the panel boundary, so a screen that moves moves in one place and a caller
# that has no screen is not sent to one.
#
# Both named for the ACT rather than for the state, because ``console.NOTHING_ENABLED`` is
# the drift cell's two words for the same node and the two must not be mistaken for one
# another: that one is a table cell, these are refusals. What separates the pair is YET
# against LEFT — a node on its way to serving something, and a node that served something
# and was switched off.
#
# TWO SENTENCES, NOT ONE — M18.1's review. There was one, written for the deciding case
# above and delivered almost always in the other, and each half was wrong in the other's
# case:
#
#   * it said OFFER, which on the Nodes screen is a narrower control than it sounds: it
#     appears only on a row that was enabled and then withdrawn. A node with nothing on it
#     has no such row, and the console's word there is ENABLE — the select in the
#     transports dialog, the primary button beside it, and the Nodes empty state all say
#     so. A first-run operator sent to look for "offer" finds nothing named that.
#   * and on the withdrawn-row path it named the remedy without its cost. Offering the
#     row again grants every active user material on it and puts it back in every
#     subscription — a change to everyone's link, made to cut one person off — and it is
#     the only in-product way out: removing the row does not push, a state change does
#     not reach the host, and this apply refuses again.
#
# Which one an operator gets is decided by whether the node has any transport row at all,
# not by how many are enabled — an empty node and a node with every row withdrawn are two
# different situations with two different next actions.
#
# THREE SENTENCES, NOT TWO — M18's acceptance, and the second axis is whether a config
# this panel holds has ever actually REACHED the host (``NodeTransport.applied_at``, which
# a withdrawal leaves alone). Two of the three claims above turned out to be said in
# places they are not true:
#
#   * the withdrawn one asserts the host is still serving everyone who holds a credential
#     — read on a node whose own drift cell says `never applied`, which contradicts the
#     Users screen's "No node is serving yet" and is simply false. A node nothing was ever
#     pushed to is serving nobody.
#   * and the empty one said nothing about the host at all, which is the same defect from
#     the other side: REMOVING a node's last transport leaves it with no rows, so the
#     operator who removed it to cut everybody off lands here and reads "nothing on the
#     node was changed" as "there was nothing there". The row is gone from this panel and
#     the daemon on the host is not — and because the apply is refused, no apply is ever
#     going to stop it.
#
# So the two that cannot know say what is true either way — WHATEVER this host was last
# given, it keeps running — and only the one that does know (a surviving row carries an
# ``applied_at``) makes the stronger claim. A removed row takes its ``applied_at`` with
# it, which is why the empty case can never be certain and must not pretend to be.
#
# AND THE EMPTY ONE STOPS SAYING WHAT IT CANNOT KNOW — M18's acceptance, round 2. It
# opened "Whatever this host was last given it keeps running" on a node nothing had ever
# been pushed to, which reads as a report about a config that was delivered; the walk
# read it on a host whose address does not even resolve. The evidence that would settle
# it is ``applied_at`` and it is on the row that was removed — so this sentence says that
# it cannot tell, and why, rather than picking the half that is wrong on the node the
# operator is looking at. Both halves of what it is FOR survive that: an operator with
# nothing enabled is still told to enable something, and an operator who removed a
# transport to cut people off is still told that removing it did not stop the host.
NOTHING_TO_APPLY_YET = (
    "this node has no transports enabled, so there is nothing to apply — nothing was "
    f"pushed and nothing on the node was changed. {ENABLE_ONE_HERE} Whether anything was "
    "ever pushed to this host cannot be answered from here: a removed transport takes "
    "the record of its own apply away with it. What holds either way is that an apply "
    "with nothing to push cannot change what the host is running — so if a transport was "
    "removed here to cut people off, removing it did not stop the host serving it. "
    f"{NOTHING_STOPS_A_SERVING_HOST}"
)
NOTHING_LEFT_TO_APPLY = (
    "every transport on this node is withdrawn, so there is nothing to apply — nothing "
    "was pushed and nothing on the node was changed. The node is still running the "
    "config it was last given and still serving everyone who holds a credential on it: "
    "an apply cannot stop that, because there is nothing to push. "
    f"{OFFER_ONE_AGAIN} {NOTHING_STOPS_A_SERVING_HOST}"
)
NOTHING_LEFT_TO_APPLY_UNPUSHED = (
    "every transport on this node is withdrawn, so there is nothing to apply — nothing "
    "was pushed and nothing on the node was changed. No transport on this node has ever "
    "been applied: whatever this host was last given it keeps running, and an apply "
    "cannot change that while there is nothing to push. "
    f"{OFFER_ONE_AGAIN} {NOTHING_STOPS_A_SERVING_HOST}"
)

# The boundary between "this node failed" and "stop the whole operation".
#
# Everything ``apply_node`` does is work for ONE node — read its record, render its
# config, dial it, push, record what was pushed — so a failure of any kind there is a
# fact about that node, and the operator must be told it per node rather than losing
# the outcome for every other node to a 500 (criterion 6). The exceptions below are the
# ones that are NOT a fact about one node: they would be raised identically for every
# remaining node, and reporting them per node would say "3 nodes could not be updated"
# when the truth is "this control plane cannot read its own secrets". Worse, the one
# message that says so is written by a dedicated handler further out — catching it here
# would destroy the diagnosis while handling it, which is the exact fault M4 exists to
# fix, one level up.
#
# ``SecretUnreadable`` means HASHI_SECRET_KEY does not match the data. It is answered
# outward as a 409 with an explanation (see errors.SecretsUnreadable), not as a 500, so
# letting it through does not put an internal error in front of the operator.
#
# Note what is deliberately NOT listed: a programming error. A bug in one transport's
# renderer is still a fact about the node that uses it, and the other nodes' outcomes
# are worth more than an abort. It is logged with its traceback wherever it is caught,
# so it stays as visible as it is today.
#
# ``BaseException`` — ``asyncio.CancelledError`` above all — is excluded by using
# ``except Exception`` at the call sites and must stay excluded: a cancelled request or
# a shutting-down worker is not a per-node failure, and swallowing it hangs the loop.
_NOT_PER_NODE: tuple[type[BaseException], ...] = (SecretUnreadable,)

# The upstream image pins used to live here. They are now in
# ``edge/bootstrap/node_stack.py`` (``DATA_PLANES``), keyed by config FORMAT — naming a
# daemon is naming a protocol, and `control` is not allowed to do either.
async def render_for_node(session: AsyncSession, node: Node) -> dict[str, str]:
    """Every enabled transport's config for one node, keyed by the name it is placed under.

    Pure with respect to the node: it reads the database, then renders. Each
    transport gets exactly the friends who hold a live credential on it, which is
    what makes the rendered file the authoritative answer to "who can use this node".

    THE KEY IS ``config_name``, not the transport's name, and since M15 those can
    differ: a node may run a friend-facing AmneziaWG and the entry end of a hop over the
    same transport, and they are two files, two compose services and two interfaces. For
    every row written before M15 — and for every first instance since — the two strings
    are equal, which is why every caller indexing this by a transport's name still finds
    what it is looking for. A caller that needs the TRANSPORT behind a key (to resolve a
    config format, or to name it in a message) asks ``placed_transports``.
    """
    rendered: dict[str, str] = {}
    view = nodes.node_view(node)

    # This node's own way out, if it has one — M3. Read once per node rather than per
    # transport, because it is a property of the NODE: an entry node has a hop and its
    # friends leave through it; a leaf has none and its friends leave from it. What comes
    # back is an address and nothing else, so nothing below learns what carries the hop.
    hop_exit = await relay.exit_through_hop(session, node)

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
            rendered[node_transport.config_name] = relay.render_end(
                node_transport, peer
            )
            continue

        result = await session.execute(
            select(Credential).where(Credential.node_transport_id == node_transport.id)
        )
        # What this transport says about giving each consumer an address of its own,
        # resolved once per row rather than per credential — M17.
        spec = addresses.spec_for(node_transport.transport_name)
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
            #
            # Built through ``addresses.edge_credential``, which is also what the user's
            # own config file is built through: this config's ``AllowedIPs`` and that
            # file's ``Address`` are two renders of one allocation, and a second builder
            # here is how they would come to disagree.
            addresses.edge_credential(row, spec)
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
            rendered[node_transport.config_name] = transport.profile.render_server(
                view,
                nodes.render_params(node_transport),
                credentials,
                # Which way out this tunnel's traffic takes, from the purpose the row
                # already carries and from whether this node has a hop — M14.3 and M3,
                # and see ``nodes.egress_for``. Both are passed for every transport,
                # including those whose data plane forwards nothing in the kernel and
                # renders nothing for either, so this call stays blind to which is which.
                egress=nodes.egress_for(node_transport, hop_exit),
                exit_via=hop_exit,
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
            # rendered text is NOT included: it holds key material. ``ConfigRefused``
            # rather than its parent, so a fan-out can tell "nothing was pushed and a
            # retry changes nothing" from "unreachable" by type (``why_not_updated``).
            raise ConfigRefused(
                f"{node_transport.transport_name} could not be rendered for this node "
                f"— {type(exc).__name__}: {exc}"
            ) from exc

    return rendered


async def placed_transports(session: AsyncSession, node: Node) -> dict[str, str]:
    """Which transport each of this node's placed configs came from, by config name.

    The other half of ``render_for_node``'s key, and it exists because two of the three
    things done with a rendered config are the TRANSPORT's business rather than the
    file's: which upstream checker validates it, and which extension and data plane it
    gets (``edge.bootstrap.node_stack``). Before M15 the key was the transport's name and
    both were free.

    Its own query rather than a second return value, so no caller that indexes a config
    by name had to change. It is the same filter ``render_for_node`` runs, in the same
    transaction, against a database only the operator writes to — and the two are used
    together within one request.
    """
    listed = await session.execute(
        select(NodeTransport.config_name, NodeTransport.transport_name)
        .where(NodeTransport.node_id == node.id)
        .where(NodeTransport.enabled.is_(True))
    )
    return {config_name: transport_name for config_name, transport_name in listed.all()}


def target_for(node: Node, node_settings: Settings) -> NodeTarget:
    """How to reach a node over SSH, from its record.

    The two ways a node's record cannot produce a session at all are refused here, in
    the one function both the push and the probe build their target with, so neither has
    to recognise them separately.

    The key is the second of them and it was an internal error until this line existed:
    the SSH layer loads it OUTSIDE the block that turns a connection failure into
    ``NodeUnreachable``, so an unusable one escaped as an exception class — a 500 on the
    probe, and on the push a sentence saying "what reached the node is unknown", which
    is untrue when nothing was ever dialled. Refused before the connection is attempted,
    so both surfaces can say what is actually true: no session, nothing sent.

    Nodes registered before the panel started refusing such a key still hold one, which
    is why this is a check on the record and not only on the form.
    """
    if not node.ssh_host:
        raise NodeOperationFailed(
            "this node has no SSH address, so its configuration cannot be pushed"
        )
    if node.ssh_private_key and not nodes.ssh_key_is_usable(node.ssh_private_key):
        raise NodeOperationFailed(
            "the SSH private key stored for this node cannot be read, so no connection "
            "was attempted and nothing on the node was changed"
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

    # ``ConfigRefused``: nothing was pushed and a retry changes nothing — and this is the
    # message known to be able to carry key material, which is why a fan-out learns the
    # kind from the type rather than from these words (``NotUpdated``).
    raise ConfigRefused(
        f"the rendered configuration for {transport_name!r} was rejected by the "
        f"upstream checker, so it was NOT pushed: {result.output[:300]}"
    )


async def _nothing_to_apply(session: AsyncSession, node: Node) -> str:
    """Which of the three refusals this node gets.

    One query, on the refusal path only, and it reads both axes off one column.
    ``render_for_node`` already filtered to the enabled rows and came back empty, so
    what is left to learn is:

    * whether the node has any transport row AT ALL — which decides whether there is
      something here to OFFER again or nothing here to do but ENABLE one. The two
      answers send the operator to two different controls, and ``offer`` exists only on
      a row that was enabled once;
    * and whether any row that is still here has ever been APPLIED, which decides
      whether this panel may say what the host is still serving. ``applied_at`` survives
      a withdrawal (``nodes.set_transport_enabled`` touches only the flag) and is
      deleted with the row, so a TRUE here is knowledge and a FALSE is only the absence
      of it — which is exactly why the two sentences a FALSE leads to claim nothing
      about who the host is authorising.

    Queried rather than read off ``node.transports`` for the reason ``render_for_node``
    gives: this can be reached straight after a revocation deleted rows in the same
    session, where touching the collection is lazy IO on an async session.
    """
    applied_at = await session.execute(
        select(NodeTransport.applied_at).where(NodeTransport.node_id == node.id)
    )
    stamps = applied_at.scalars().all()
    if not stamps:
        return NOTHING_TO_APPLY_YET
    if any(stamp is not None for stamp in stamps):
        return NOTHING_LEFT_TO_APPLY
    return NOTHING_LEFT_TO_APPLY_UNPUSHED


async def _record_failure(session: AsyncSession, node: Node, reason: str) -> None:
    """Log why an apply failed, then mark the node degraded. In that order.

    The order is the whole point, and it was bought with an evening in the field on
    2026-09-08. Recording the failure is itself a write that can fail, and when it did
    — a first apply starts from ``draft``, which the state machine would not let become
    ``degraded`` — the recording's own error REPLACED the failure it was recording. The
    operator was handed "a node cannot go from draft to degraded"; the actual cause was
    a permission error on the host, and it existed nowhere afterwards, because
    ``domain_error_handler`` logs a code and never a message. Logging first means the
    reason survives even when everything after this line goes wrong.

    A refused transition is therefore swallowed here rather than raised. It is still
    possible (a ``retired`` node has nowhere to go) and it is still worth a log line,
    but the caller is about to raise the real reason and that is the more useful of the
    two errors to put in front of an operator.

    The reason is the node's own diagnostic — our command, its stderr, our timeout. It
    names no user and no connection, which is what makes it loggable at all (core
    invariants §6).
    """
    logger.error("apply failed for node %s: %s", node.id, reason)
    try:
        await nodes.set_node_state(
            session, node_id=node.id, state=NodeState.DEGRADED, detail=reason[:500]
        )
    except Conflict:
        logger.error(
            "node %s could not be marked degraded from %s; its state is unchanged and "
            "the line above is the whole record of what went wrong",
            node.id,
            node.state,
        )


async def apply_node(session: AsyncSession, *, node_id: str) -> dict[str, str]:
    """Render, validate, push and verify one node. Returns what was applied.

    Marks the node degraded on any failure after the first byte is written, and
    active only once it came back up serving every transport we expect.
    """
    node = await nodes.get_node(session, node_id)
    node_settings = settings()

    configs = await render_for_node(session, node)
    # NOTHING ENABLED IS NOT A FAILURE — M18.1, and the position of this check is the
    # whole of it. It sits where ``render_for_node`` returned, OUTSIDE both try blocks
    # below, so the node's recorded state is not touched: a draft stays a draft and an
    # already-active node keeps serving its last config, which is the same asymmetry a
    # render failure has always had. Inside either block it would degrade the node,
    # which is exactly the outcome this step exists to remove.
    #
    # Before validation and before the compose file, because the compose file is where
    # the old answer came from: zero services renders an empty ``services:`` mapping,
    # which the daemon rejects, and the operator was handed that rejection.
    if not configs:
        raise NothingToApply(await _nothing_to_apply(session, node))

    # Which transport is behind each placed config. Needed from here down wherever the
    # answer is the TRANSPORT's rather than the file's — the checker, the extension, the
    # data plane — because since M15 a config's name and its transport's name can differ.
    placed = await placed_transports(session, node)
    for config_name, config in configs.items():
        # The FORMAT comes from the transport's own declaration, so the right checker
        # runs without this module knowing which protocol it is looking at.
        transport_name = placed[config_name]
        validate_before_push(
            transport_name, config, profile(transport_name).meta.config_format
        )

    # The configs themselves, not their names: each service carries the digest of its
    # own config as a label, which is what makes `docker compose up -d` recreate a
    # container whose config changed. Sorted so the rendered compose file is byte-stable
    # regardless of the order the transports were read in — an unstable one would
    # recreate every container on every apply.
    compose = node_stack.render_compose(
        transports=node_stack.services_for(
            {name: configs[name] for name in sorted(configs)}, transports=placed
        )
    )

    # Built before the connection, and its refusal RECORDED. A record that cannot
    # produce a session at all — no address, or a stored key the SSH layer will not load
    # — is not the half-configured window below: nothing has been written to the host.
    # But the node is still one the operator cannot reach, and the reason on its row has
    # to be the current one rather than whatever the previous attempt left there (M4.5).
    # Re-raised unchanged, so what is recorded and what is answered are one sentence.
    try:
        target = target_for(node, node_settings)
    except NodeOperationFailed as exc:
        await _record_failure(session, node, exc.message)
        raise

    try:
        async with NodeConnection(target) as connection:
            # Persist a learned host key on the FIRST successful connection, so every
            # later connection is pinned and an interception fails loudly.
            if connection.learned_host_key and not node.ssh_host_key:
                node.ssh_host_key = connection.learned_host_key

            await node_stack.prepare(connection)
            for config_name, config in configs.items():
                await node_stack.place_config(
                    connection,
                    transport_name=placed[config_name],
                    config=config,
                    path=node_stack.config_path_of(config_name, placed[config_name]),
                )
            await node_stack.place_compose(connection, compose=compose)
            await node_stack.restart(connection)

            # Verify rather than assume, and verify the right thing. `docker compose
            # up -d` returns success as soon as the containers are created — a daemon
            # that starts and immediately exits on a bad config satisfies that and
            # serves nothing, and one that was never recreated satisfies it while
            # serving the PREVIOUS config, which is the fault M1 measured in the field.
            #
            # ``loaded_digests`` answers with the digest each running container was
            # created with, so the comparison below is against what the process was
            # started from rather than against what is on disk beside it. Without it
            # this function wrote an ``applied_digest`` recording a state the node was
            # not in — and a revoked friend stayed connected.
            loaded = await node_stack.loaded_digests(connection)
            not_running = sorted(set(configs) - set(loaded))
            stale = sorted(
                name
                for name, config in configs.items()
                if name in loaded and loaded[name] != node_stack.digest_of(config)
            )

    except (NodeUnreachable, node_stack.NodeStackUnsupported) as exc:
        await _record_failure(session, node, str(exc))
        raise NodeOperationFailed(
            f"the node could not be configured and has been marked degraded: {exc}"
        ) from exc
    except NodeOperationFailed:
        # Already carries a sentence written for the operator. Re-raised untouched so it
        # cannot fall into the arm below and be replaced by a type name — a failure
        # destroyed while being handled is the fault this whole milestone is about.
        raise
    except _NOT_PER_NODE:
        raise
    except Exception as exc:
        # This block is the ONLY window in which a node can be left half-configured: the
        # config files are placed one by one and the restart happens inside it. Core
        # invariants §4 is unconditional there — a partially applied node is marked
        # degraded, never left active — and it does not care whether the interruption
        # was a node that went quiet or a bug in this file. Without this arm an
        # unexpected error left the node ACTIVE and therefore still in every friend's
        # subscription, pointing them at a daemon that may be mid-swap.
        #
        # Logged with its traceback BEFORE it is converted, for the same reason
        # ``render_for_node`` does it: a DomainError reaches the operator without a
        # stack, so this is the only place the bug is recoverable from. It is not new
        # exposure — until now this exception escaped to ``unhandled_error_handler``,
        # which logged the same traceback and answered 500.
        logger.exception("unexpected failure while configuring node %s", node.id)
        # Only the exception's TYPE, never ``str(exc)``, unlike the neighbouring arms.
        # Their messages are written by us or by ``edge`` and name no host; an arbitrary
        # exception from the SSH layer routinely carries the node's address, and this
        # string is both an API response and a stored ``state_detail`` (core invariants
        # §4: no host names cross the boundary). The full text is in the log above.
        reason = (
            f"an unexpected internal error ({type(exc).__name__}) interrupted the push, "
            "so what reached the node is unknown; the traceback is in the control "
            "plane's log"
        )
        await _record_failure(session, node, reason)
        raise NodeOperationFailed(
            f"the node could not be configured and has been marked degraded: {reason}"
        ) from exc

    if not_running or stale:
        # Two different faults, named separately because they send the operator to
        # different places: a container that never came up is a config the daemon
        # rejected, and one still on an older config is a definition Compose did not
        # consider changed. Both leave the node degraded — core invariants §4, and the
        # loud failure M1's second "done when" asks for.
        detail = "pushed, but " + "; ".join(
            part
            for part in (
                f"these did not come up: {', '.join(not_running)}" if not_running else "",
                f"still running an older configuration: {', '.join(stale)}" if stale else "",
            )
            if part
        )
        await _record_failure(session, node, detail)
        raise NodeOperationFailed(
            f"configuration was applied but the node is not serving it — marked "
            f"degraded: {detail}"
        )

    now = datetime.datetime.now(datetime.UTC)
    # Queried rather than read off ``node.transports``, for the same reason as in
    # ``render_for_node`` and with the same shape. On the revocation path this node did
    # not arrive from a fresh SELECT: it was reached through the relationships the
    # revocation's own queries loaded, so its ``transports`` collection is unloaded and
    # touching it is lazy I/O — which on an async session raises MissingGreenlet
    # instead of issuing a query. That error is not a NodeOperationFailed, so it
    # escaped ``apply_many`` and the operator was handed a 500 in place of the
    # RevocationOutcome naming which nodes still carry the withdrawn credential.
    # ``apply_many`` now reports such an error per node instead of ending the fan-out,
    # but the explicit query stays: a caught bug is still a node that was not updated.
    #
    # Filtered on the rendered names rather than on ``enabled``: what is recorded here
    # is what was actually pushed, and a transport disabled between the render and now
    # must not be given an applied digest it never received.
    applied = await session.execute(
        select(NodeTransport)
        .where(NodeTransport.node_id == node.id)
        .where(NodeTransport.config_name.in_(sorted(configs)))
    )
    for node_transport in applied.scalars().unique():
        node_transport.applied_at = now
        node_transport.applied_digest = node_stack.digest_of(
            configs[node_transport.config_name]
        )

    node.state = NodeState.ACTIVE
    node.state_detail = None
    # Success only, and only here — past every failure arm above, which record nothing.
    # A push that failed is not a change that committed, and its reason is a sentence
    # that can come from a remote host; the node's own row carries it for the operator.
    # The node's name is the whole entry: not which transports, not their digests, not
    # how long it took.
    audit.record(session, AuditAction.NODE_APPLIED, first_label=node.name)
    await session.commit()
    logger.info("node applied: %s (%d transports)", node.id, len(configs))
    return configs


class NotUpdated(enum.StrEnum):
    """Why one node in a fan-out was not updated — a closed set, not a sentence.

    A caller that has to tell the operator what to DO about a node needs to know which of
    these it was, and it must not find out by reading the message: a refusal's message can
    carry an upstream checker's output, which is known to quote the node's private key
    (``validate_before_push``; docs/tracker/M9/carry-over.md). So the kind travels beside
    the message as a value, and a surface with nowhere safe for the message — the
    revocation banner — is composed from this and the node's name alone.
    """

    # The node dials a hop and its record names no resolver (M16): it cannot be rendered,
    # and nothing but setting the resolver changes that.
    NO_RESOLVER = "no-resolver"

    # Its configuration could not be produced, or the upstream checker refused it. Nothing
    # was pushed, and retrying changes nothing on its own.
    REFUSED = "refused"

    # Everything else: the host could not be reached, the push or its verification failed,
    # or something unexpected happened. The one kind a retry can fix.
    UNREACHED = "unreached"


@dataclass(frozen=True)
class NodeNotUpdated:
    """One node a fan-out did not update: the operator's sentence, and which kind it was."""

    # The DomainError's own message — what the API returns and rotation prints, as before.
    # Never composed into the revocation banner; see ``NotUpdated``.
    reason: str
    why: NotUpdated


def why_not_updated(exc: BaseException) -> NotUpdated:
    """Which kind of failure ``exc`` was, read off its TYPE and never off its text."""
    if isinstance(exc.__cause__, ResolverMissing):
        return NotUpdated.NO_RESOLVER
    # ``NothingToApply`` joins ``ConfigRefused`` here rather than falling through to
    # UNREACHED, and the case is real rather than defensive: a withdrawn row keeps its
    # minted credentials, so revoking the last friend on a node whose only transport was
    # withdrawn re-pushes a node with nothing to render. "Could not be reached — apply it
    # again once it can be" would send the operator to retry a button that will refuse
    # for the same reason for ever. Nothing was pushed and retrying changes nothing,
    # which is precisely what REFUSED means.
    if isinstance(exc, ConfigRefused | NothingToApply):
        return NotUpdated.REFUSED
    return NotUpdated.UNREACHED


async def apply_many(
    session: AsyncSession, node_transports: list[NodeTransport]
) -> dict[str, NodeNotUpdated | None]:
    """Apply every node named by a set of node-transports. Returns per-node outcome.

    Used by revocation, where several nodes must be re-pushed at once. Every node is
    attempted even if an earlier one failed — stopping at the first failure would
    leave a revoked friend live on nodes that were perfectly reachable, which is the
    exact failure criterion 6 forbids. Failures are collected and reported, each as its
    message and its kind (``NodeNotUpdated``).
    """
    outcomes: dict[str, NodeNotUpdated | None] = {}
    for node_id in dict.fromkeys(nt.node_id for nt in node_transports):
        try:
            await apply_node(session, node_id=node_id)
            outcomes[node_id] = None
        except DomainError as exc:
            # Recorded, not raised: the caller needs the whole picture to tell the
            # operator which nodes still carry the revoked credential.
            #
            # The whole family, not just ``NodeOperationFailed``: every DomainError
            # carries a message written for the operator, so reporting it costs nothing
            # and reveals nothing. ``NotFound`` — the node record deleted between the
            # revocation's query and its turn in the fan-out — used to end the fan-out
            # in a 500 for that reason alone.
            logger.error("apply failed for node %s during fan-out", node_id)
            outcomes[node_id] = NodeNotUpdated(reason=exc.message, why=why_not_updated(exc))
        except _NOT_PER_NODE:
            raise
        except Exception as exc:
            # Anything unexpected from OUTSIDE the push window: the queries and the
            # render before it, and the bookkeeping after it. ``apply_node`` handles the
            # window itself, where a half-configured node has to be degraded; here the
            # node is either untouched or fully configured, so its recorded state is not
            # wrong and nothing is written to it.
            #
            # The historical case is the second one and it is why this milestone exists:
            # a MissingGreenlet while recording what was applied ended the fan-out, and
            # the operator was handed a 500 instead of the RevocationOutcome naming
            # which nodes still carry the withdrawn credential. Every node after the
            # first failure went unreported and, as far as the operator could tell,
            # unattempted.
            #
            # Type only, no ``str(exc)``, for the reason given in ``apply_node``.
            logger.exception("unexpected failure applying node %s during fan-out", node_id)
            outcomes[node_id] = NodeNotUpdated(
                reason=(
                    f"this node was not updated because of an unexpected internal error "
                    f"({type(exc).__name__}); its state is unchanged and the traceback "
                    f"is in the control plane's log"
                ),
                why=NotUpdated.UNREACHED,
            )
            # Last, deliberately: the same ordering ``_record_failure`` uses. The
            # session is the only thing carried from one node to the next, and an
            # unexpected error can leave it needing a rollback — after which every
            # remaining node would fail with a database error that has nothing to do
            # with it. Rolling back discards nothing that matters: a successful apply
            # has already committed, and the revocation itself committed before the
            # fan-out started. If the rollback ITSELF fails the session is gone, and
            # that exception is left to propagate — no later node can even be read, so
            # continuing would invent failures rather than report them.
            await session.rollback()
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
