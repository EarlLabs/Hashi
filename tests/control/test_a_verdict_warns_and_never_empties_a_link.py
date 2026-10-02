"""A health verdict warns the operator; it is never why a user's link comes back empty.

WHAT: M26's fourth acceptance walk, fix round 5 — every finding the walk left open but
      the 14 hand-typed numbers: an apply's measurement no longer demotes a node that was
      serving (so it no longer empties anybody's link); an apply and a probe ask a
      wg-family transport whether its interface holds the peers it was given rather than
      whether its port is held; an apply that could not take its reading says so instead
      of printing the healthy line; and a finding on a node in service is re-measured
      without anybody pressing probe.
WHY:  the walk's own measurements, one per section below:

      * a ~20-second false red on the entry made ``GET /sub/{token}`` return NOTHING for
        every user, while that host's Xray was listening and the hop handshake was 27
        seconds old. The owner's rule: a health verdict may warn the operator, it may
        never be why a user's link comes back empty.
      * ``nc`` squatting on a wg-family node's port, and — contriving nothing — the real
        daemon with its peer removed (``peers=[]``, 100% loss): apply said success and
        the probe said green, because both asked whether the PORT was held.
      * with ``ss`` removed the apply's success line was byte-identical to a healthy run.
      * 35 seconds after a refusal the node was serving at 0% loss and the panel still
        read the verdict: nothing re-measured until a human pressed probe.
HOW:  against ``_serving_host.ServingHost`` — the real render, parsers and settle loop,
      with only what the host prints invented. Every refusal has its accept twin beside
      it, because a check that refuses everything passes every refusal test.

      Boundary: nothing here moves a packet. The walk measured loss on real hosts; what
      these establish is what the panel SAYS and what a subscription CONTAINS given what
      a host answers. A real-host walk is what confirms the answers are the real ones.
"""

import base64

import pytest

from control.app.models import NodeState
from control.app.services import apply, health, nodes
from edge.registry import discover

from ._serving_host import NO_INTERFACE, NO_TOOL, PEERS_EMPTY, PEERS_HELD, ServingHost
from .conftest import GENERATED_SSH_KEY

# RFC 5737 documentation addresses, never dialled — the connection is replaced. IP
# literals on purpose: a host registered by name would be a delivery host in this suite
# (``delivery_certificate`` is configured), which is a different apply.
ENTRY_ADDRESS = "192.0.2.61"
WG_ADDRESS = "192.0.2.62"

REALITY = "vless-reality"
AWG = "amneziawg"

# One node's worth of operator input for the wg-family transport — the same values the
# neighbouring files write down, because no API can invent a port or an address.
AWG_PARAMS: dict[str, object] = {
    "port": 51820,
    "tunnel_address": "10.91.0.1/24",
    "peer_tunnel_address": "10.91.0.2/24",
    "mtu": 1280,
    "junk_packet_count": 4,
    "junk_packet_min_size": 40,
    "junk_packet_max_size": 80,
    "init_packet_magic_header": 1020327352,
    "response_packet_magic_header": 2060487442,
    "underload_packet_magic_header": 3679305607,
    "transport_packet_magic_header": 1436947798,
}


def reach(monkeypatch: pytest.MonkeyPatch, host: ServingHost) -> ServingHost:
    """Every dial an apply or a probe makes lands on ``host``."""
    for module in (apply, health):
        monkeypatch.setattr(module, "NodeConnection", lambda target: host)
    return host


async def a_node(client, *, name: str, address: str, transport: str, params: dict) -> str:
    created = await client.post(
        "/api/nodes",
        json={
            "name": name,
            "address": address,
            "location_label": "Testland",
            "ssh_host": address,
            "ssh_private_key": GENERATED_SSH_KEY,
        },
    )
    assert created.status_code == 201, created.text
    node_id = created.json()["id"]
    body: dict[str, object] = {"transport_name": transport, "params": params}
    # Sent for exactly the transports that declare each user an address of their own,
    # asked of the registry rather than of the transport's name.
    if discover()[transport].peer_address is not None:
        body["pool_size"] = 50
    enabled = await client.post(f"/api/nodes/{node_id}/transports", json=body)
    assert enabled.status_code == 201, enabled.text
    return node_id


async def a_user_token(client, nickname: str) -> str:
    created = await client.post("/api/users", json={"nickname": nickname})
    assert created.status_code == 201, created.text
    url = (await client.get(f"/api/users/{created.json()['id']}/subscription")).json()["url"]
    return url.rsplit("/", 1)[-1]


async def link(anonymous, token: str) -> str:
    """What a user's app gets from their link, decoded."""
    fetched = await anonymous.get(f"/sub/{token}")
    assert fetched.status_code == 200, fetched.text
    return base64.b64decode(fetched.content).decode()


async def reread(session, node_id: str):
    session.expire_all()
    return await nodes.get_node(session, node_id)


# --- blocker 1: a verdict never empties a link -------------------------------------------


async def test_a_false_red_on_a_serving_node_leaves_every_link_whole(
    client, session, anonymous, reality_params, monkeypatch
) -> None:
    """Walk 4's blocker, through the two requests it took.

    The entry was serving and every user's link carried it. One apply's wait ended a
    moment before the daemon held its port — a slow VPS — and the link came back empty.
    The verdict is still given (502, in the probe's words), and it is still kept on the
    row; what it no longer does is take the node out of users' links.

    Red on the commit before fix round 5: the node went ``degraded`` and the link was
    empty.
    """
    host = reach(monkeypatch, ServingHost(port=reality_params["port"], protocol="tcp"))
    node_id = await a_node(
        client, name="entry", address=ENTRY_ADDRESS, transport=REALITY, params=reality_params
    )
    token = await a_user_token(client, "olya")
    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 200
    before = await link(anonymous, token)
    assert "vless://" in before, "the premise: the link carries the entry"

    host.port_held = False
    verdict = await client.post(f"/api/nodes/{node_id}/apply")

    assert verdict.status_code == 502, verdict.text
    # The link first: it is the finding, and the assertion that is red on the old code.
    after = await link(anonymous, token)
    assert after == before, "a health verdict emptied a user's link"
    message = verdict.json()["error"]["message"]
    assert "nothing listening on the port for" in message, message
    assert "stays in users' links" in message, message
    node = await reread(session, node_id)
    assert node.state == NodeState.ACTIVE, node.state
    assert "nothing listening on the port for" in (node.last_probe_finding or ""), (
        "the verdict was not kept anywhere the operator will see it after the banner"
    )


async def test_a_red_verdict_never_adds_a_node_to_a_link(
    client, session, anonymous, monkeypatch
) -> None:
    """The other half of the rule, so it cannot be satisfied by ignoring verdicts.

    A node that was NOT serving before the press is refused into service by a red
    verdict exactly as before: degraded, and in nobody's link.
    """
    reach(
        monkeypatch,
        ServingHost(port=AWG_PARAMS["port"], protocol="udp", peers=PEERS_EMPTY),
    )
    node_id = await a_node(
        client, name="wg-new", address=WG_ADDRESS, transport=AWG, params=AWG_PARAMS
    )
    token = await a_user_token(client, "petya")

    refused = await client.post(f"/api/nodes/{node_id}/apply")

    assert refused.status_code == 502, refused.text
    assert (await reread(session, node_id)).state == NodeState.DEGRADED
    fetched = await anonymous.get(f"/sub/{token}", params={"format": "client-config-file"})
    assert fetched.status_code == 200
    assert b"[Interface]" not in fetched.content, (
        "a node refused into service by its own measurement is in a user's link"
    )


async def test_a_serving_node_nobody_could_reach_stays_in_every_link(
    client, session, anonymous, reality_params, monkeypatch
) -> None:
    """The owner's decision of 2026-10-02, on the residual round 5 left open.

    The user's only node is serving; the next apply cannot open a session at all (a
    connect timeout — a slow or briefly blocked path). Nothing was written, so the host
    is running exactly what it was, and the link must still carry it. The operator is
    still told, on the banner and on the row.

    Red on the commit before this change: the node went ``degraded`` and the link was
    empty.
    """
    host = reach(monkeypatch, ServingHost(port=reality_params["port"], protocol="tcp"))
    node_id = await a_node(
        client, name="entry", address=ENTRY_ADDRESS, transport=REALITY, params=reality_params
    )
    token = await a_user_token(client, "olya")
    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 200
    before = await link(anonymous, token)
    assert "vless://" in before, "the premise: the link carries the user's only node"

    host.unreachable = True
    unreached = await client.post(f"/api/nodes/{node_id}/apply")

    assert unreached.status_code == 502, unreached.text
    after = await link(anonymous, token)
    assert after == before, "not reaching a serving host emptied a user's link"
    message = unreached.json()["error"]["message"]
    assert "could not be reached" in message and "stays in users' links" in message, message
    node = await reread(session, node_id)
    assert node.state == NodeState.ACTIVE, node.state
    assert "could not reach" in (node.last_probe_finding or ""), node.last_probe_finding


async def test_an_unreachable_node_not_yet_serving_stays_out(
    client, session, anonymous, reality_params, monkeypatch
) -> None:
    """The half of the decision that does not change: a draft that could not be reached
    is not put into anybody's link by the attempt."""
    host = reach(monkeypatch, ServingHost(port=reality_params["port"], protocol="tcp"))
    host.unreachable = True
    node_id = await a_node(
        client, name="entry", address=ENTRY_ADDRESS, transport=REALITY, params=reality_params
    )
    token = await a_user_token(client, "olya")

    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 502

    assert (await reread(session, node_id)).state == NodeState.DEGRADED
    assert "vless://" not in await link(anonymous, token)


async def test_a_host_that_drops_after_the_session_opened_is_still_degraded(
    client, session, reality_params, monkeypatch
) -> None:
    """Core invariants §4 is untouched: a session that opened and died mid-push may have
    left a half-written host, and that is not a reading — it is still degraded."""
    host = reach(monkeypatch, ServingHost(port=reality_params["port"], protocol="tcp"))
    node_id = await a_node(
        client, name="entry", address=ENTRY_ADDRESS, transport=REALITY, params=reality_params
    )
    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 200

    host.drops_at_restart = True
    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 502

    assert (await reread(session, node_id)).state == NodeState.DEGRADED


# --- blocker 2: the port is held is not the node is serving ------------------------------


@pytest.mark.parametrize(
    ("peers", "what_the_walk_did"),
    [
        (PEERS_EMPTY, "the real daemon up, its port held, peers=[]"),
        (NO_INTERFACE, "nc squatting on the port, no interface at all"),
    ],
)
async def test_a_held_port_does_not_make_a_wg_node_serving(
    client, session, monkeypatch, peers: str, what_the_walk_did: str
) -> None:
    """Both of the walk's hosts, each through the apply button.

    The port IS held in both — the socket reading says yes. What refuses the node is the
    transport's own question: does the interface hold the peers this control plane
    rendered into its config. A user exists, so the config authorises somebody and the
    question has something to compare.

    Red on the commit before fix round 5: the apply answered 200 and the node went active.
    """
    host = reach(
        monkeypatch, ServingHost(port=AWG_PARAMS["port"], protocol="udp", peers=peers)
    )
    node_id = await a_node(
        client, name="wg-leaf", address=WG_ADDRESS, transport=AWG, params=AWG_PARAMS
    )
    await a_user_token(client, "kolya")

    applied = await client.post(f"/api/nodes/{node_id}/apply")

    assert applied.status_code == 502, f"{what_the_walk_did}: {applied.text}"
    assert "not serving what we gave them, by their own check: amneziawg" in applied.text
    assert AWG in host.asked, "the transport's own question was never put to the node"


@pytest.mark.parametrize("peers", [PEERS_EMPTY, NO_INTERFACE])
async def test_the_probe_asks_the_same_question_and_says_what_a_no_means(
    client, session, monkeypatch, peers: str
) -> None:
    """The node goes wrong AFTER a good apply — the walk removed the peer from a running
    daemon — and the probe, not only the apply, catches it, in the transport's own words.
    """
    host = reach(monkeypatch, ServingHost(port=AWG_PARAMS["port"], protocol="udp"))
    node_id = await a_node(
        client, name="wg-leaf", address=WG_ADDRESS, transport=AWG, params=AWG_PARAMS
    )
    await a_user_token(client, "kolya")
    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 200

    host.peers = peers
    probed = (await client.get(f"/api/nodes/{node_id}/health")).json()

    assert probed["healthy"] is False, probed
    assert probed["not_serving"] == [AWG], probed
    assert AWG in probed["listening"], "the premise: its port IS held"
    finding = (await reread(session, node_id)).last_probe_finding or ""
    assert "failed its own serving check" in finding, finding
    assert "does not hold the peers" in finding, finding


async def test_a_wg_node_holding_its_peers_applies_and_probes_green(
    client, session, monkeypatch
) -> None:
    """The accept direction, without which the refusals above refuse every wg node."""
    reach(monkeypatch, ServingHost(port=AWG_PARAMS["port"], protocol="udp"))
    node_id = await a_node(
        client, name="wg-leaf", address=WG_ADDRESS, transport=AWG, params=AWG_PARAMS
    )
    await a_user_token(client, "kolya")

    applied = await client.post(f"/api/nodes/{node_id}/apply")
    probed = (await client.get(f"/api/nodes/{node_id}/health")).json()

    assert applied.status_code == 200, applied.text
    assert applied.json()["serving_unmeasured"] == []
    assert probed["healthy"] is True, probed
    assert probed["serving"] == [AWG], probed
    assert "holds every peer" in probed["serving_means"][AWG]


async def test_the_transports_own_check_confirms_where_the_socket_table_cannot(
    client, session, monkeypatch
) -> None:
    """What "use the transport's check, not port occupancy" means when ``ss`` is gone.

    The socket table cannot be read here, so the port says nothing either way — and the
    node is still MEASURED, because the question that decides a wg-family node is the
    transport's own and it was answered yes.
    """
    reach(
        monkeypatch,
        ServingHost(port=AWG_PARAMS["port"], protocol="udp", no_ss=True, peers=PEERS_HELD),
    )
    node_id = await a_node(
        client, name="wg-leaf", address=WG_ADDRESS, transport=AWG, params=AWG_PARAMS
    )
    await a_user_token(client, "kolya")

    applied = await client.post(f"/api/nodes/{node_id}/apply")

    assert applied.status_code == 200, applied.text
    assert applied.json()["serving_unmeasured"] == [], applied.json()


# --- high: an apply that could not take the reading does not say what one that did says --


async def test_an_apply_without_ss_does_not_print_the_healthy_line(
    client, session, reality_params, monkeypatch
) -> None:
    """The walk's exact case: ``ss`` removed, apply pressed, success line unchanged.

    Both presses succeed — refusing a host for a missing tool is the failure surface
    walk 2 was right to refuse — but they no longer SAY the same thing: the API names
    what was not measured and the panel answers with a standing note instead of the
    healthy toast.

    Red on the commit before fix round 5: the two panel answers were identical.
    """
    host = reach(monkeypatch, ServingHost(port=reality_params["port"], protocol="tcp"))
    node_id = await a_node(
        client, name="entry", address=ENTRY_ADDRESS, transport=REALITY, params=reality_params
    )
    measured = await client.post(f"/panel/nodes/{node_id}/apply")
    api_measured = await client.post(f"/api/nodes/{node_id}/apply")

    host.no_ss = True
    unmeasured = await client.post(f"/panel/nodes/{node_id}/apply")
    api_unmeasured = await client.post(f"/api/nodes/{node_id}/apply")

    assert measured.status_code == unmeasured.status_code == 200
    assert api_measured.json()["serving_unmeasured"] == []
    assert api_unmeasured.json()["serving_unmeasured"] == [REALITY]
    said = " ".join(unmeasured.text.split())
    assert "Not measured serving: vless-reality" in said, said
    assert "Not measured serving" not in " ".join(measured.text.split())


async def test_an_image_without_the_transports_tool_is_unmeasured_not_refused(
    client, session, monkeypatch
) -> None:
    """The serving question's own "nobody could ask" — exit 127 from the engine.

    A fact about the image, not about the protocol: the apply succeeds, names the config
    as unmeasured, and clears nothing it could not contradict.
    """
    reach(
        monkeypatch,
        ServingHost(port=AWG_PARAMS["port"], protocol="udp", peers=NO_TOOL),
    )
    node_id = await a_node(
        client, name="wg-leaf", address=WG_ADDRESS, transport=AWG, params=AWG_PARAMS
    )

    applied = await client.post(f"/api/nodes/{node_id}/apply")

    assert applied.status_code == 200, applied.text
    assert applied.json()["serving_unmeasured"] == [AWG]


# --- medium: a verdict improves on its own -------------------------------------------------


async def test_a_finding_on_a_serving_node_is_re_measured_without_a_press(
    app, client, session, reality_params, monkeypatch
) -> None:
    """The walk's 35 seconds: the host came up after the wait ended and the panel went on
    reading the verdict. One pass of the re-measure loop probes it, finds it holding its
    port, and the finding goes — by a measurement of the same kind, as the apply's own
    clearing rule requires.
    """
    host = reach(monkeypatch, ServingHost(port=reality_params["port"], protocol="tcp"))
    node_id = await a_node(
        client, name="entry", address=ENTRY_ADDRESS, transport=REALITY, params=reality_params
    )
    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 200
    host.port_held = False
    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 502
    assert (await reread(session, node_id)).last_probe_finding, "the premise: a finding"

    host.port_held = True
    remeasured = await health.remeasure_findings(app.state.database)

    assert remeasured == 1
    node = await reread(session, node_id)
    assert node.last_probe_finding is None, node.last_probe_finding
    assert node.last_probe_at is not None, "cleared without a measurement standing behind it"
    assert node.state == NodeState.ACTIVE


async def test_a_degraded_node_is_not_re_measured_or_promoted(
    app, client, session, monkeypatch
) -> None:
    """The half that is decided NOT to happen (docs/decisions.md, 2026-10-02).

    A degraded node's way back into users' links is an apply, which grants, pushes and
    measures in one act. A timer that found it serving could only promote it with no
    operator act, or write beside a state it cannot change — so it does not dial it.
    """
    host = reach(
        monkeypatch,
        ServingHost(port=AWG_PARAMS["port"], protocol="udp", peers=PEERS_EMPTY),
    )
    node_id = await a_node(
        client, name="wg-new", address=WG_ADDRESS, transport=AWG, params=AWG_PARAMS
    )
    await a_user_token(client, "petya")
    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 502
    host.peers = PEERS_HELD
    dialled = host.dialled

    assert await health.remeasure_findings(app.state.database) == 0
    assert host.dialled == dialled, "the re-measure dialled a node that is not in service"
    assert (await reread(session, node_id)).state == NodeState.DEGRADED


def test_the_re_measure_can_be_turned_off() -> None:
    """``0`` is off, and off means no task at all rather than a task that sleeps for ever."""
    assert health.start_remeasurer(None, interval=0) is None  # type: ignore[arg-type]
