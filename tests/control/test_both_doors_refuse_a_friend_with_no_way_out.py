"""A node that dials a hop offers its friends only a transport that can reach it — M25.

WHAT: the two doors that would otherwise create the one combination this product cannot
      render — enabling a kernel tunnel for the friends of a node whose way out is a hop,
      and giving a hop to a node that already offers them one — and the three
      arrangements beside it that must keep working untouched.
WHY:  M25's walk proved route A carries on the owner's real leaf, and found this on the
      way. ``POST /panel/nodes/{id}/transports`` accepted the row without a word, the
      friend was granted a credential on it, and ``GET /sub/{token}`` handed over a
      complete, importable 2077-byte configuration file — for a node whose own renderer
      then refused it outright. The refusal at the apply is correct and fail-closed and
      is not what was wrong: what was wrong is that three surfaces said yes first, one of
      them to a friend, and the operator found out at the end.

      So the refusal moves to the doors, where nothing has been written yet. Both of
      them, because the same mistake arrives from either side — the transport added to a
      node that has the hop, or the hop added to a node that has the transport — and an
      operator who met it only one way round would simply do it the other.
HOW:  real Postgres, real encryption, the real services, through the same API and the
      same console an operator uses. No node is contacted and nothing here says anything
      about a tunnel carrying traffic; what is proven is what this control plane accepts,
      what it refuses, and what it has written when it refuses.

      Every transport question is asked of the registry —
      ``TransportMeta.serves_users_through_a_hop``, which is derived from what a package
      declares its data plane does — so nothing here names a protocol and a transport
      added later is covered by arriving rather than by being listed.
"""

import io
import zipfile

import pytest
from sqlalchemy import select

from control.app.errors import NodeOperationFailed
from control.app.models import Credential, NodeState, NodeTransport, TransportPurpose
from control.app.services import apply, nodes, subscriptions
from edge.registry import discover, profile

# The two halves of the fleet, by the declaration and never by a name. A transport that
# re-originates terminates a friend's connection and opens its own from whatever address
# the egress policy names, so a hop is expressible for it; one whose packets the node's
# kernel routes has no way to send somebody else's out through a different interface.
KERNEL_TUNNELS = sorted(
    name
    for name, meta in discover().items()
    if not meta.serves_users_through_a_hop and meta.subscription_formats
)
RE_ORIGINATING = sorted(
    name
    for name, meta in discover().items()
    if meta.serves_users_through_a_hop and meta.subscription_formats
)

# The transport the hop itself is built over, asked of the declaration for the same
# reason: ``hop_expressible`` is "can this BE a hop", which is a different question from
# either column above and today has exactly one answer in this image.
HOP_TRANSPORTS = sorted(
    name for name, meta in discover().items() if meta.hop_expressible
)

# Every operator-typed knob any shipped transport takes, filtered per transport against
# its own model by ``params_for``. One literal serves the whole image, so a test here
# reads as "this transport on this node" rather than as a form.
KNOBS: dict[str, object] = {
    "mtu": 1280,
    "junk_packet_count": 4,
    "junk_packet_min_size": 40,
    "junk_packet_max_size": 80,
    "init_packet_magic_header": 1020327352,
    "response_packet_magic_header": 2060487442,
    "underload_packet_magic_header": 3679305607,
    "transport_packet_magic_header": 1436947798,
    "decoy_host": "www.example.com",
    "decoy_port": 443,
    "server_names": ["www.example.com"],
    "server_name": "front.example.com",
    "certificate_path": "/etc/hashi/certs/fullchain.pem",
    "certificate_key_path": "/etc/hashi/certs/privkey.pem",
}

# Room for far more users than this file creates: a pool sized to exactly what a test
# needs is one that turns red when an unrelated assertion adds a person.
ROOMY = 50

# The resolver an entry node's record names — M16: a node that dials a hop does not
# render without one, so every node here that dials one is registered the way the product
# asks. RFC 5737 documentation address.
RESOLVER = "192.0.2.53"

# Two ports, because two data planes on one host cannot share one. Typed here the way an
# operator types them into the form rather than taken from anything this codebase ships.
FRIEND_PORT = 51820
HOP_PORT = 51821


def params_for(transport_name: str, **overrides) -> dict[str, object]:
    """The operator-supplied half for one transport, minus knobs it does not declare."""
    declared = set(profile(transport_name).params_model.model_fields)
    supplied = {**KNOBS, **overrides}
    return {key: value for key, value in supplied.items() if key in declared}


def pool_for(transport_name: str) -> int | None:
    """How many addresses this row may hand out, or ``None`` where it hands out none.

    Read off the transport's own declaration, because the enable route refuses a size on
    a transport that takes none as readily as it refuses a missing one on a transport
    that needs one.
    """
    return ROOMY if discover()[transport_name].peer_address is not None else None


async def a_node(client, name: str, address: str, *, resolver: str | None = None) -> str:
    created = await client.post(
        "/api/nodes",
        json={
            "name": name,
            "address": address,
            "location_label": "Testland",
            "resolver": resolver,
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def offer(client, node_id: str, transport_name: str, *, network="10.80.0", **overrides):
    """Enable one transport for a node's friends, the way both surfaces do.

    ``network`` is the friend-facing tunnel's own range, and it is a parameter because two
    tunnels on one node may not overlap (M17.1c) — a node here carries a hop as well.
    Filtered away for a transport that declares no tunnel of its own.
    """
    return await client.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": transport_name,
            "params": params_for(
                transport_name,
                port=FRIEND_PORT,
                tunnel_address=f"{network}.1/24",
                peer_tunnel_address=f"{network}.2/24",
                **overrides,
            ),
            "pool_size": pool_for(transport_name),
        },
    )


async def hop(client, entry_id: str, leaf_id: str, transport_name: str, *, network="10.81.0"):
    """Establish a hop between two nodes over the transport that can carry one."""
    return await client.post(
        "/api/hops",
        json={
            "entry_node_id": entry_id,
            "leaf_node_id": leaf_id,
            "transport_name": transport_name,
            "entry_params": params_for(
                transport_name,
                port=HOP_PORT,
                tunnel_address=f"{network}.1/24",
                peer_tunnel_address=f"{network}.2/24",
            ),
            "leaf_params": params_for(
                transport_name,
                port=HOP_PORT,
                tunnel_address=f"{network}.2/24",
                peer_tunnel_address=f"{network}.1/24",
            ),
        },
    )


@pytest.fixture(params=KERNEL_TUNNELS)
def kernel_tunnel(request, nothing_retired) -> str:
    """One transport whose packets a node's kernel routes, in a fleet with no retirement.

    ``nothing_retired`` for M20's acceptance reason: this image retires one member of the
    family, and a file about what a FAMILY cannot do that reached only its un-retired
    member would stop being about a family the day the other was removed. The retirement
    is a separate refusal with its own file; here it would simply hide this one.
    """
    return request.param


@pytest.fixture(params=RE_ORIGINATING)
def re_originating(request, nothing_retired) -> str:
    return request.param


# --- the premise -------------------------------------------------------------

def test_this_image_ships_both_kinds_of_data_plane() -> None:
    """Said as an assertion rather than as a ``skipif``, and the difference is measured.

    A module-level skip is the shape ``test_every_user_holds_their_own_address`` uses for
    its own premise, and it is right there: a fleet with no pooled transport is a
    legitimate image. This one is not the same case. Every claim below is about the
    DIFFERENCE between two kinds of data plane, and the way the product can lose that
    difference is for the declaration to stop telling them apart — at which point one of
    these lists empties and a file guarded by a skip reports itself as inapplicable
    instead of as broken. That was measured while writing this: forcing
    ``serves_users_through_a_hop`` to ``True`` turned every test here from red to
    skipped.

    So the premise fails loudly, and the parametrised tests below empty out beside it.
    """
    assert KERNEL_TUNNELS, (
        "no installed transport declares a data plane whose packets the node's kernel "
        "routes, so nothing here proves either door refuses anything"
    )
    assert RE_ORIGINATING, (
        "no installed transport declares that it re-originates a consumer's connection, "
        "so nothing here proves route A can still be built"
    )
    assert HOP_TRANSPORTS, "no installed transport can carry a hop, so there is no hop"


# --- the door that adds a transport -------------------------------------------

async def test_a_node_that_dials_a_hop_refuses_a_kernel_tunnel_for_its_friends(
    client, kernel_tunnel: str
) -> None:
    """The first door, and the one the walk came in through.

    The node has a hop, so its friends leave through it and nowhere else; this transport
    cannot express that for somebody else's packets. Refused where the operator asked,
    naming the transport they named and saying what to do instead.
    """
    entry = await a_node(client, "entry-1", "192.0.2.20", resolver=RESOLVER)
    leaf = await a_node(client, "leaf-1", "192.0.2.21")
    assert (await hop(client, entry, leaf, HOP_TRANSPORTS[0])).status_code == 201

    refused = await offer(client, entry, kernel_tunnel)

    assert refused.status_code == 409, refused.text
    body = refused.json()["error"]
    assert body["code"] == "no_exit_through_the_hop"
    assert kernel_tunnel in body["message"], body["message"]
    # The two moves out of it, and the fact that neither has been made for them.
    assert "nothing was enabled" in body["message"], body["message"]
    assert "re-originates" in body["message"], body["message"]


async def test_the_refusal_mints_nothing_and_hands_a_friend_nothing(
    client, session, kernel_tunnel: str
) -> None:
    """What "nothing was enabled" has to mean — M25's own finding, from the other end.

    The walk's node was accepted, every active friend was granted a credential on it, and
    the delivery endpoint answered a friend's own bearer token with a complete config file
    for a node that can never be applied. So the row, the credential and the file are
    asserted absent together: each is a separate surface, and the one that mattered was
    the third.
    """
    entry = await a_node(client, "entry-2", "192.0.2.22", resolver=RESOLVER)
    leaf = await a_node(client, "leaf-2", "192.0.2.23")
    assert (await hop(client, entry, leaf, HOP_TRANSPORTS[0])).status_code == 201
    await nodes.set_node_state(session, node_id=entry, state=NodeState.ACTIVE)

    friend = (await client.post("/api/friends", json={"nickname": "masha"})).json()
    token = (
        await client.get(f"/api/friends/{friend['id']}/subscription")
    ).json()["url"].rsplit("/", 1)[-1]

    assert (await offer(client, entry, kernel_tunnel)).status_code == 409

    offered = await nodes.friend_facing_on(session, entry)
    assert offered == [], "a row was written for a transport that was refused"
    credentials = (await session.execute(select(Credential))).scalars().unique().all()
    assert credentials == [], "a credential was minted on a refused transport"

    delivered = await client.get(f"/sub/{token}", params={"format": "client-config-file"})
    assert delivered.status_code == 200
    with zipfile.ZipFile(io.BytesIO(delivered.content)) as archive:
        # The endpoint answers an archive holding its own "nothing here right now" note
        # rather than a 404, which is a friend who has not been revoked being told so.
        # What must not be in it is a configuration.
        assert archive.namelist() == [subscriptions.EMPTY_ARCHIVE_NOTE_NAME], (
            "a friend was handed a configuration file for a node that cannot render"
        )


# --- the door that adds a hop -------------------------------------------------

async def test_a_node_already_offering_a_kernel_tunnel_refuses_the_hop(
    client, kernel_tunnel: str
) -> None:
    """The second door. The same rule, approached from the side the panel said yes to.

    ``hop establishing — apply both nodes to bring it up`` was the answer here, and the
    node it described was one whose friend-facing row would not render from that moment
    on. The refusal names the node as well as the transport, because the operator is
    looking at a form with two nodes on it.
    """
    entry = await a_node(client, "entry-3", "192.0.2.24", resolver=RESOLVER)
    leaf = await a_node(client, "leaf-3", "192.0.2.25")
    assert (await offer(client, entry, kernel_tunnel)).status_code == 201

    refused = await hop(client, entry, leaf, HOP_TRANSPORTS[0])

    assert refused.status_code == 409, refused.text
    body = refused.json()["error"]
    assert body["code"] == "no_exit_through_the_hop"
    assert kernel_tunnel in body["message"], body["message"]
    assert "entry-3" in body["message"], body["message"]
    assert "no hop was established" in body["message"], body["message"]
    # The OFFERED half of the pair, pinned against its withdrawn twin below: this row is
    # in every user's link right now, and "already offers" is only true while it is.
    assert "already offers" in body["message"], body["message"]


async def test_the_hop_refusal_writes_neither_end(
    client, session, kernel_tunnel: str
) -> None:
    """Refused before either end is minted, so there is no half a hop to tidy up.

    ``establish_hop`` validates both ends, mints material for both and renders them as a
    pair before it writes anything; this refusal is above all of that, which is what makes
    "no hop was established" true at the raise rather than true because something rolled
    back.
    """
    entry = await a_node(client, "entry-4", "192.0.2.26", resolver=RESOLVER)
    leaf = await a_node(client, "leaf-4", "192.0.2.27")
    assert (await offer(client, entry, kernel_tunnel)).status_code == 201

    assert (await hop(client, entry, leaf, HOP_TRANSPORTS[0])).status_code == 409

    ends = (
        await session.execute(
            select(NodeTransport).where(
                NodeTransport.purpose.in_(TransportPurpose.relays())
            )
        )
    ).scalars().unique().all()
    assert ends == [], "an end of the refused hop was written"
    assert (await client.get("/api/hops")).json() == []


async def test_an_offer_that_is_switched_off_still_refuses_the_hop(
    client, session, kernel_tunnel: str
) -> None:
    """The way round it that a flag would have left open.

    A friend-facing row switched off is still a row, and the control that switches it back
    on is about one row on one screen — it has no node in front of it and no hop to refuse
    about. So this door counts every offer the node holds rather than the ones that are
    live, which is the same reading ``exit_through_hop`` takes of a hop end for the same
    reason: what can be switched on again is part of what this node is.

    AND IT SAYS SO IN THE ROW'S OWN STATE — M25's second walk. The refusal was the offered
    sentence, so a panel that had just told the operator this transport was out of every
    user's link at their next refresh answered them, on the next screen, that the node
    "already offers" it. Both screens are about the same row and only one of them could be
    right. The withdrawn sentence says the row is withdrawn and then says why a row
    serving nobody still stands in the way, which is the question the offered one never
    has to answer.
    """
    entry = await a_node(client, "entry-5", "192.0.2.28", resolver=RESOLVER)
    leaf = await a_node(client, "leaf-5", "192.0.2.29")
    row = (await offer(client, entry, kernel_tunnel)).json()
    await nodes.set_transport_enabled(
        session, node_transport_id=row["id"], enabled=False
    )

    refused = await hop(client, entry, leaf, HOP_TRANSPORTS[0])

    assert refused.status_code == 409, refused.text
    message = refused.json()["error"]["message"]
    assert refused.json()["error"]["code"] == "no_exit_through_the_hop"
    assert "no hop was established" in message, message
    assert "withdrawn" in message, message
    assert "already offers" not in message, message


# --- what must still work -----------------------------------------------------

async def test_a_transport_that_re_originates_is_offered_on_a_node_with_a_hop(
    client, re_originating: str
) -> None:
    """Route A itself, in both orders — the arrangement M25 measured carrying traffic.

    A friend behind an entry, out through the hop, on at the leaf's address. Nothing in
    this milestone may make it harder to build, and it is built both ways round because
    the two doors are two orders of the same fleet.
    """
    entry = await a_node(client, "entry-6", "192.0.2.30", resolver=RESOLVER)
    leaf = await a_node(client, "leaf-6", "192.0.2.31")
    assert (await hop(client, entry, leaf, HOP_TRANSPORTS[0])).status_code == 201
    assert (await offer(client, entry, re_originating)).status_code == 201

    other = await a_node(client, "entry-7", "192.0.2.32", resolver=RESOLVER)
    far = await a_node(client, "leaf-7", "192.0.2.33")
    assert (await offer(client, other, re_originating)).status_code == 201
    assert (
        await hop(client, other, far, HOP_TRANSPORTS[0], network="10.82.0")
    ).status_code == 201


async def test_a_kernel_tunnel_is_untouched_on_a_node_with_no_hop(
    client, session, kernel_tunnel: str
) -> None:
    """Route B, which nine walks on real hardware were carried on.

    Every leaf and every single-box deployment is this node. The transport renders a local
    exit here and is exactly right, so the refusal above must not reach it — and a friend
    is granted on it and handed their file, which is the surface the other test asserts
    empty.
    """
    leaf = await a_node(client, "leaf-8", "192.0.2.34")
    assert (await offer(client, leaf, kernel_tunnel)).status_code == 201
    await nodes.set_node_state(session, node_id=leaf, state=NodeState.ACTIVE)

    friend = (await client.post("/api/friends", json={"nickname": "sasha"})).json()
    token = (
        await client.get(f"/api/friends/{friend['id']}/subscription")
    ).json()["url"].rsplit("/", 1)[-1]

    delivered = await client.get(f"/sub/{token}", params={"format": "client-config-file"})
    with zipfile.ZipFile(io.BytesIO(delivered.content)) as archive:
        assert archive.namelist(), "a node with no hop stopped delivering its own files"


async def test_a_kernel_tunnel_is_untouched_on_the_leaf_end_of_a_hop(
    client, session, kernel_tunnel: str
) -> None:
    """The far end of a hop serving friends of its own — the owner's live shape.

    A leaf holds the end of the hop that WAITS, and a node that waits has no way out of
    its own: its friends leave by its own route exactly as they always have. The refusal
    is about the node that DIALS, and asserting that here is what stops it being written
    against ``hop_ends`` — which would take the owner's own leaf out of service.
    """
    entry = await a_node(client, "entry-9", "192.0.2.35", resolver=RESOLVER)
    leaf = await a_node(client, "leaf-9", "192.0.2.36")
    assert (await hop(client, entry, leaf, HOP_TRANSPORTS[0])).status_code == 201

    assert (await offer(client, leaf, kernel_tunnel)).status_code == 201

    # And the other order, which is the one an operator following the runbook reaches:
    # the box is already serving friends when it is made the far end of somebody's hop.
    second = await a_node(client, "leaf-10", "192.0.2.37")
    assert (await offer(client, second, kernel_tunnel)).status_code == 201
    third = await a_node(client, "entry-11", "192.0.2.38", resolver=RESOLVER)
    assert (
        await hop(client, third, second, HOP_TRANSPORTS[0], network="10.84.0")
    ).status_code == 201, "a leaf that offers friends a kernel tunnel was refused a hop"


async def test_the_hop_itself_is_built_over_a_kernel_tunnel_and_always_was(
    client, session
) -> None:
    """The one thing this image's kernel tunnel is uniquely able to do.

    ``hop_expressible`` and ``serves_users_through_a_hop`` are opposite answers about
    the same transport, and this is the half that would be lost by conflating them: the
    hop is two ends of one tunnel network, each holding an address of its own, and a
    userspace proxy has no second end to agree with. The owner's live hop is this row.
    """
    entry = await a_node(client, "entry-12", "192.0.2.39", resolver=RESOLVER)
    leaf = await a_node(client, "leaf-12", "192.0.2.40")

    established = await hop(client, entry, leaf, HOP_TRANSPORTS[0])

    assert established.status_code == 201, established.text
    assert not discover()[HOP_TRANSPORTS[0]].serves_users_through_a_hop
    ends = await nodes.friend_facing_on(session, entry)
    assert ends == [], "a hop end was written as something friends are offered"


# --- and what the operator reads ----------------------------------------------

HTMX = {"HX-Request": "true"}


async def test_the_enable_dialog_states_the_refusal_above_its_form(
    client, kernel_tunnel: str
) -> None:
    """The console's own answer, in the console's own words.

    A refusal about the NODE has no box to sit under — every other sentence on this dialog
    is about a value the operator typed — so it is stated once above the form, which is
    where ``_refuse_enable`` puts a failure. ``friends`` becomes ``users`` on the way out
    (decision 9), and the sentence is otherwise the one the API answers with.
    """
    entry = await a_node(client, "entry-13", "192.0.2.41", resolver=RESOLVER)
    leaf = await a_node(client, "leaf-13", "192.0.2.42")
    assert (await hop(client, entry, leaf, HOP_TRANSPORTS[0])).status_code == 201

    submitted = {
        "transport_name": kernel_tunnel,
        **{
            f"{kernel_tunnel}-{field}": str(value)
            for field, value in params_for(
                kernel_tunnel,
                port=FRIEND_PORT,
                tunnel_address="10.80.0.1/24",
                peer_tunnel_address="10.80.0.2/24",
            ).items()
        },
        f"{kernel_tunnel}-pool_size": str(ROOMY),
    }
    refused = await client.post(
        f"/panel/nodes/{entry}/transports", data=submitted, headers=HTMX
    )

    assert refused.status_code == 422, refused.text
    assert "nothing was enabled" in refused.text
    assert "re-originates" in refused.text
    assert "a user&#39;s" in refused.text or "a user's" in refused.text


async def test_the_hop_dialog_states_the_refusal_above_its_form(
    client, kernel_tunnel: str
) -> None:
    """The same, on the form with twenty-four boxes and nothing wrong in any of them."""
    entry = await a_node(client, "entry-14", "192.0.2.43", resolver=RESOLVER)
    leaf = await a_node(client, "leaf-14", "192.0.2.44")
    assert (await offer(client, entry, kernel_tunnel)).status_code == 201

    carrier = HOP_TRANSPORTS[0]
    submitted = {
        "entry_node_id": entry,
        "leaf_node_id": leaf,
        "transport_name": carrier,
        **{
            f"entry-{field}": str(value)
            for field, value in params_for(
                carrier,
                port=HOP_PORT,
                tunnel_address="10.85.0.1/24",
                peer_tunnel_address="10.85.0.2/24",
            ).items()
        },
        **{
            f"leaf-{field}": str(value)
            for field, value in params_for(
                carrier,
                port=HOP_PORT,
                tunnel_address="10.85.0.2/24",
                peer_tunnel_address="10.85.0.1/24",
            ).items()
        },
    }
    refused = await client.post("/panel/hops", data=submitted, headers=HTMX)

    assert refused.status_code == 422, refused.text
    assert "no hop was established" in refused.text
    assert "entry-14" in refused.text


# --- and what the doors deliberately do not do --------------------------------

async def test_a_node_already_in_that_state_is_still_refused_at_the_apply(
    client, session, kernel_tunnel: str
) -> None:
    """Refusing to CREATE is not refusing to SERVE, and here that distinction has a cost.

    The doors above stop the combination being built; they do not go looking for a node
    that is already in it — a fleet that pre-dates this refusal, or a database edited by
    hand. So the fail-closed guarantee underneath them has to be exactly where it was:
    ``edge`` refuses to render such a node's friend-facing config at all, rather than
    writing one whose traffic surfaces in the country the hop exists to leave. That is
    the refusal M25's walk met, and it is correct; what this milestone changed is only
    how late it arrives.

    The state is reached by turning a hop round in the database — one column on each end,
    the same instrument ``test_a_hop_end_that_is_switched_off_is_still_the_way_out``
    uses, and for the same reason: no surface of this product will produce it now, and a
    guarantee that can only be asserted through a surface stops being asserted the day
    the surface refuses it.
    """
    dialler = await a_node(client, "entry-15", "192.0.2.45", resolver=RESOLVER)
    waiter = await a_node(client, "leaf-15", "192.0.2.46", resolver=RESOLVER)
    assert (await offer(client, waiter, kernel_tunnel)).status_code == 201
    assert (await hop(client, dialler, waiter, HOP_TRANSPORTS[0])).status_code == 201

    # The hop, reversed: the node serving friends becomes the end that DIALS.
    for end in await session.execute(
        select(NodeTransport).where(
            NodeTransport.purpose.in_(TransportPurpose.relays())
        )
    ):
        row = end[0]
        row.purpose = (
            TransportPurpose.RELAY_ENTRY
            if row.node_id == waiter
            else TransportPurpose.RELAY_LEAF
        )
    await session.commit()

    with pytest.raises(NodeOperationFailed) as refusal:
        await apply.render_for_node(session, await nodes.get_node(session, waiter))

    assert "terminates their connection" in str(refusal.value), refusal.value
