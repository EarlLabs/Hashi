"""Entry→leaf hops, from the control plane — backlog item 16.

WHAT: establishing, rendering, listing and dissolving the tunnel between the entry node
      friends dial and the leaf node their traffic leaves from.
WHY:  this is the charter's topology, and the two facts asserted hardest here are the
      ones a friend would otherwise pay for: a hop is never in anyone's subscription,
      and a hop that would not form a working tunnel is refused before either end is
      written. The first would route a friend straight past the entry node; the second
      would leave the operator with a node that looks configured and an exit that is
      unreachable.
HOW:  no node is contacted — nothing here pushes. The claim is about what the database
      holds and what would be rendered, which is exactly the half that can be proven
      without a host. That a hop actually carries packets is the owner's field check,
      and no test in this repository claims it.
"""

import base64
import json

import pydantic
import pytest
from sqlalchemy import select

from control.app.errors import DomainError, HopEndRefused
from control.app.models import NodeState, NodeTransport, TransportPurpose
from control.app.services import apply, keymaterial, nodes, relay

HOP_TRANSPORT = "amneziawg"


@pytest.fixture
def hop_params() -> dict[str, object]:
    """The operator-supplied half of one end. Key material is minted, never typed."""
    return {
        "port": 51820,
        "mtu": 1280,
        "junk_packet_count": 4,
        "junk_packet_min_size": 40,
        "junk_packet_max_size": 80,
        "init_packet_magic_header": 1020327352,
        "response_packet_magic_header": 2060487442,
        "underload_packet_magic_header": 3679305607,
        "transport_packet_magic_header": 1436947798,
    }


async def two_nodes(client):
    """An entry node and a leaf node, both draft."""
    ids = []
    for name, address, label in (
        ("entry-ru", "192.0.2.20", "Russia"),
        ("leaf-nl", "192.0.2.10", "Netherlands"),
    ):
        response = await client.post(
            "/api/nodes",
            json={"name": name, "address": address, "location_label": label},
        )
        ids.append(response.json()["id"])
    return ids


def hop_body(entry_id, leaf_id, hop_params, **overrides):
    entry_params = {**hop_params, "tunnel_address": "10.44.0.1/24",
                    "peer_tunnel_address": "10.44.0.2/24"}
    leaf_params = {**hop_params, "tunnel_address": "10.44.0.2/24",
                   "peer_tunnel_address": "10.44.0.1/24", **overrides}
    return {
        "entry_node_id": entry_id,
        "leaf_node_id": leaf_id,
        "transport_name": HOP_TRANSPORT,
        "entry_params": entry_params,
        "leaf_params": leaf_params,
    }


async def established(client, hop_params):
    entry_id, leaf_id = await two_nodes(client)
    response = await client.post("/api/hops", json=hop_body(entry_id, leaf_id, hop_params))
    assert response.status_code == 201, response.text
    return entry_id, leaf_id, response.json()


# --- establishing -------------------------------------------------------------

async def test_establishing_a_hop_writes_both_ends_linked_to_each_other(
    client, session, hop_params
) -> None:
    """A hop is only meaningful as a pair, so it is stored as one."""
    _, _, body = await established(client, hop_params)

    assert body["entry"]["purpose"] == TransportPurpose.RELAY_ENTRY
    assert body["leaf"]["purpose"] == TransportPurpose.RELAY_LEAF

    entry = await session.get(NodeTransport, body["entry"]["id"])
    leaf = await session.get(NodeTransport, body["leaf"]["id"])
    assert entry.peer_node_transport_id == leaf.id
    assert leaf.peer_node_transport_id == entry.id


async def test_the_symmetric_material_is_minted_once_and_shared(
    client, session, hop_params
) -> None:
    """Declared by the transport, not recognised by name here.

    Two independently minted pre-shared keys give two valid configuration files and a
    handshake that never completes — the exact silent failure this hop is full of.
    """
    _, _, body = await established(client, hop_params)

    entry = await session.get(NodeTransport, body["entry"]["id"])
    leaf = await session.get(NodeTransport, body["leaf"]["id"])
    entry_secrets = json.loads(entry.secrets)
    leaf_secrets = json.loads(leaf.secrets)

    assert entry_secrets["preshared_key"] == leaf_secrets["preshared_key"]
    # ...and the material that must NOT be shared is not.
    assert entry_secrets["private_key"] != leaf_secrets["private_key"]


async def test_a_node_cannot_be_its_own_exit(client, hop_params) -> None:
    entry_id, _ = await two_nodes(client)
    response = await client.post(
        "/api/hops", json=hop_body(entry_id, entry_id, hop_params)
    )
    assert response.status_code == 400


async def test_ends_that_would_not_form_a_tunnel_are_refused_before_anything_is_written(
    client, session, hop_params
) -> None:
    """The refusal has to come BEFORE the write.

    Half a hop is a node holding a tunnel interface to nowhere, and the operator has no
    way to see it from the node's own page — the config it renders looks complete.
    """
    entry_id, leaf_id = await two_nodes(client)

    response = await client.post(
        "/api/hops",
        json=hop_body(
            entry_id, leaf_id, hop_params,
            # A different network: neither end would have a route to the other.
            tunnel_address="10.99.0.2/24", peer_tunnel_address="10.99.0.1/24",
        ),
    )

    assert response.status_code == 400, response.text
    rows = (await session.execute(select(NodeTransport))).scalars().unique().all()
    assert rows == [], "a refused hop still wrote an end"


async def test_a_hop_on_an_unknown_transport_is_a_404(client, hop_params) -> None:
    entry_id, leaf_id = await two_nodes(client)
    body = hop_body(entry_id, leaf_id, hop_params) | {"transport_name": "nope"}
    assert (await client.post("/api/hops", json=body)).status_code == 404


# --- what a hop must never do -------------------------------------------------

async def test_a_hop_never_reaches_a_friends_subscription(
    client, session, hop_params, reality_params
) -> None:
    """THE safety property of this feature.

    A friend handed the entry↔leaf tunnel would be routed straight past the entry node
    the topology exists to hide behind — and their client would happily use it, because
    it is a working configuration. So the assertion is not "the hop is filtered
    somewhere" but "the subscription contains exactly the friend-facing entries".
    """
    entry_id, leaf_id, _ = await established(client, hop_params)

    # A real, friend-facing transport on the entry node, so the subscription is not
    # empty for the trivial reason.
    await client.post(
        f"/api/nodes/{entry_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    for node_id in (entry_id, leaf_id):
        await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)

    friend_id = (await client.post("/api/friends", json={"nickname": "kolya"})).json()["id"]
    url = (await client.get(f"/api/friends/{friend_id}/subscription")).json()["url"]
    document = base64.b64decode(
        (await client.get(f"/sub/{url.rsplit('/', 1)[-1]}")).text
    ).decode()

    assert len(document.splitlines()) == 1, document
    assert HOP_TRANSPORT not in document


async def test_a_hop_is_granted_to_nobody(client, session, hop_params) -> None:
    """No friend credential is ever created against a hop end."""
    from control.app.models import Credential

    _, _, body = await established(client, hop_params)
    await client.post("/api/friends", json={"nickname": "kolya"})

    held = await session.execute(
        select(Credential).where(
            Credential.node_transport_id.in_([body["entry"]["id"], body["leaf"]["id"]])
        )
    )
    assert held.scalars().unique().all() == []


# --- rendering ----------------------------------------------------------------

async def test_each_end_renders_with_the_other_as_its_only_peer(
    client, session, hop_params
) -> None:
    """Rendered through the apply path, so this is not a test-only render."""
    entry_id, leaf_id, _ = await established(client, hop_params)

    entry_config = (await apply.render_for_node(
        session, await nodes.get_node(session, entry_id)
    ))[HOP_TRANSPORT]
    leaf_config = (await apply.render_for_node(
        session, await nodes.get_node(session, leaf_id)
    ))[HOP_TRANSPORT]

    assert entry_config.count("[Peer]") == 1
    assert leaf_config.count("[Peer]") == 1
    # Only the entry dials: the leaf cannot reach a node behind a Russian carrier NAT.
    assert "Endpoint = 192.0.2.10:51820" in entry_config
    assert "Endpoint" not in leaf_config


async def test_rendering_says_so_when_the_far_end_is_gone(
    client, session, hop_params
) -> None:
    """A half hop must fail loudly rather than render as a server with no peers.

    That would be a valid file, a daemon that starts, and an exit that carries nothing
    — the failure mode with no symptom.
    """
    entry_id, _, body = await established(client, hop_params)

    entry = await session.get(NodeTransport, body["entry"]["id"])
    entry.peer_node_transport_id = None
    await session.commit()

    with pytest.raises(DomainError):
        await apply.render_for_node(session, await nodes.get_node(session, entry_id))


async def test_the_hops_config_is_placed_where_its_daemon_will_look_for_it(
    client, session, hop_params
) -> None:
    """wg-quick derives the interface name from the file name and refuses a .json."""
    entry_id, _, _ = await established(client, hop_params)

    configs = await apply.render_for_node(
        session, await nodes.get_node(session, entry_id)
    )
    from edge.bootstrap import node_stack

    services = node_stack.services_for(configs)
    assert services[0]["config_path"].endswith(".conf")
    # And the container that loads it is not the proxy image the VLESS transports use.
    assert services[0]["command"][-1] == services[0]["config_path"]
    assert "NET_ADMIN" in services[0]["capabilities"]


# --- dissolving ---------------------------------------------------------------

async def test_dissolving_removes_both_ends(client, session, hop_params) -> None:
    """Both, always: one end left behind is a tunnel to a decommissioned exit."""
    _, _, body = await established(client, hop_params)

    response = await client.delete(f"/api/hops/{body['entry']['id']}")

    assert response.status_code == 200
    assert len(response.json()["needs_apply"]) == 2
    rows = (await session.execute(select(NodeTransport))).scalars().unique().all()
    assert rows == []


async def test_dissolving_something_that_is_not_a_hop_is_refused(
    client, session, hop_params, reality_params
) -> None:
    """A friend-facing transport must not be removable through the hop route."""
    entry_id, _ = await two_nodes(client)
    enabled = (await client.post(
        f"/api/nodes/{entry_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )).json()

    assert (await client.delete(f"/api/hops/{enabled['id']}")).status_code == 400


# --- from the panel -----------------------------------------------------------

async def test_the_panel_offers_a_hop_form_built_from_the_transports_declaration(
    client, hop_params
) -> None:
    """Named no protocol and no field in the template — both come from the registry."""
    await two_nodes(client)

    # The console's establish-hop dialog, which took this form over from /panel/fleet
    # when M9.2 landed the Hops screen and became its only home when M9.6 deleted that
    # page. The assertion moved with the fact rather than being relaxed to "somewhere":
    # BOTH ends get a box for a field neither this file nor the template names.
    page = (await client.get("/panel/hops/new")).text

    assert 'name="entry-tunnel_address"' in page
    assert 'name="leaf-tunnel_address"' in page


async def test_the_panel_establishes_and_dissolves_a_hop(
    client, session, hop_params
) -> None:
    entry_id, leaf_id = await two_nodes(client)
    fields = hop_body(entry_id, leaf_id, hop_params)

    form = {"entry_node_id": entry_id, "leaf_node_id": leaf_id,
            "transport_name": HOP_TRANSPORT}
    for side in ("entry", "leaf"):
        for key, value in fields[f"{side}_params"].items():
            form[f"{side}-{key}"] = str(value)

    # The console's own route since M9.6, which took this name back from the page it
    # belonged to. 200 IS the success assertion here: every way this form is refused
    # answers 422 with the dialog re-rendered, so the two cannot be confused — and the
    # database is what the claim is actually about.
    created = await client.post(
        "/panel/hops", data=form, headers={"HX-Request": "true"}
    )
    assert created.status_code == 200, created.text

    pairs = await relay.list_hops(session)
    assert len(pairs) == 1

    removed = await client.post(
        f"/panel/hops/{pairs[0][0].id}/dissolve", headers={"HX-Request": "true"}
    )
    assert removed.status_code == 200, removed.text
    assert await relay.list_hops(session) == []


async def test_the_panel_reports_a_refused_hop_rather_than_erroring(
    client, hop_params
) -> None:
    """A node that is its own exit is answered, not raised — reaching ``relay`` to do it.

    Every box is filled so the panel's own empty-field check cannot short-circuit this:
    the refusal under test is the SERVICE's, and it has to come back as something the
    operator can read rather than as an error page.
    """
    entry_id, _ = await two_nodes(client)
    fields = hop_body(entry_id, entry_id, hop_params)
    form = {"entry_node_id": entry_id, "leaf_node_id": entry_id,
            "transport_name": HOP_TRANSPORT}
    for side in ("entry", "leaf"):
        for key, value in fields[f"{side}_params"].items():
            form[f"{side}-{key}"] = str(value)

    response = await client.post(
        "/panel/hops", data=form, headers={"HX-Request": "true"}
    )

    # 422 with the dialog back, which is how this console refuses: app.js allows exactly
    # that one status to swap, and the sentence is above the form because a pair that
    # cannot form a tunnel is about no single box.
    assert response.status_code == 422, response.status_code
    assert "Establish a hop" in response.text
    assert "a node cannot be its own exit" in response.text


@pytest.mark.parametrize("method,path", [("post", "/panel/hops"), ("get", "/api/hops")])
async def test_hop_routes_need_an_operator(anonymous, method: str, path: str) -> None:
    response = await getattr(anonymous, method)(path)
    assert response.status_code in (302, 303, 401, 403), response.status_code


# --- what a refused end may never carry ---------------------------------------

# A hop end is validated together with the private keys minted for BOTH ends moments
# earlier, and a transport's own validator may quote what it was handed. None of the
# shipped ones does, which is why this is guarded rather than watched — and why the
# guard lives in ``relay.refused_fields``, one function shared with rotation, rather
# than as a rule each caller applies its own way. ``docs/decisions.md`` (2026-09-10).
VALIDATOR_QUOTED = "QUOTED-BY-A-VALIDATOR"


class _QuotesTheWholeMapping(pydantic.BaseModel):
    """A model-level validator: Pydantic locates this at ``()``, which joins to ``""``.

    The shape that matters most here, because a refusal at an empty location is
    flattened into ``HopEndRefused.message`` — which ``POST /api/hops`` returns in its
    envelope, and which the pre-redesign page printed until M9.6 deleted it. Neither
    could sort anything, which is why the sorting happens where the values are.
    """

    model_config = pydantic.ConfigDict(extra="allow")

    @pydantic.model_validator(mode="after")
    def _refuse(self):
        given = " ".join(str(value) for value in self.model_dump().values())
        raise ValueError(f"these ends disagree: {VALIDATOR_QUOTED} {given}")


class _RefusingProfile:
    """Whatever ``profile()`` hands back, narrowed to the one call this path makes."""

    def __init__(self, model) -> None:
        self._model = model

    def validate(self, values: dict) -> dict:
        self._model(**values)
        raise AssertionError("this model was supposed to refuse and did not")


async def test_a_refused_hop_end_carries_none_of_the_material_it_minted(
    client, session, monkeypatch, hop_params
) -> None:
    """The twin of the rotation guard, closed in the same place and proved the same way.

    Nothing is written before this refusal, so the keys the validator quoted exist only
    in memory — they are recorded off ``keymaterial.mint`` rather than read back from a
    row, which is what makes the assertion exact rather than a guess at what a key looks
    like.
    """
    entry_id, leaf_id = await two_nodes(client)
    monkeypatch.setattr(relay, "profile", lambda name: _RefusingProfile(_QuotesTheWholeMapping))

    minted: list = []
    freshly = keymaterial.mint

    def recording(specs, scope):
        fresh = freshly(specs, scope)
        minted.append(fresh)
        return fresh

    monkeypatch.setattr(keymaterial, "mint", recording)

    body = hop_body(entry_id, leaf_id, hop_params)
    with pytest.raises(HopEndRefused) as refused:
        await relay.establish_hop(
            session,
            entry_node_id=entry_id,
            leaf_node_id=leaf_id,
            transport_name=HOP_TRANSPORT,
            entry_params=body["entry_params"],
            leaf_params=body["leaf_params"],
        )

    assert minted, "nothing was minted, so this run proves nothing"
    held = {
        f"the {name} minted for an end": value
        for fresh in minted
        for name, value in fresh.secrets.items()
    }
    assert held

    sentences = [refused.value.message, *refused.value.fields.values()]
    for label, value in held.items():
        for sentence in sentences:
            if value in sentence:
                # The label, never the value: a rewritten assertion prints both operands.
                pytest.fail(f"a refused hop end carried {label}")

    # The transport's own words still travel, and something was struck out of them.
    assert VALIDATOR_QUOTED in refused.value.message
    assert relay.WITHHELD in refused.value.message
