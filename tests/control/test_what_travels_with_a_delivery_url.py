"""What the Nodes screen may claim about a host, and what goes with a link — M27.7.

WHAT: the sentence chosen from what an apply RECORDED placing on a host, in each of the
      four states a host with a name and a usable certificate can be in; and the words
      that must travel with a delivery URL, which the product keeps in one string
      because it cannot keep them in the document.
WHY:  the sentence was chosen on ``any(row.applied_at …)`` — that some transport row had
      been pushed — and asserted that a listener was on the host and named its expiry.
      Both halves were false in the state every fleet is in the day a delivery
      certificate is first configured, and the renewal case pointed it at the one number
      the feature exists to show: after the operator replaces the pair, the host goes on
      holding the old one until an apply reaches it.
      The wording is the whole of the product's protection against a client REPLACING
      its subscription URL with a delivery URL, which silently drops every node on any
      other host and looks exactly like a revocation. M27.5 refused to put it in the
      artifact — a truthful per-user version writes "this person has other nodes" onto
      the most seizable box in the fleet — so this is the only place it can live.
HOW:  through the real screen, via an apply against the shared ``accepting_nodes``
      harness, because what is being checked is what an operator READS. The certificate
      is replaced on disk between applies, which is exactly how a renewal reaches this
      control plane (``services/delivery.configured_certificate`` reads the pair on every
      apply and never caches it).

Boundary: nothing here dials a host or serves a link. That a delivery host answers under
the placed certificate is measured in ``tests/e2e/infra/``; what is asked here is what
this control plane says about a host it cannot currently reach.
"""

import ast
import datetime
import pathlib

import pytest

from control.app.services import delivery, nodes
from control.app.settings import Settings
from edge.bootstrap import delivery_site
from edge.registry import Layer4, discover, profile

from .conftest import GENERATED_SSH_KEY, a_delivery_certificate

# The same pair of spellings the M27.6 suite uses: a name the fleet's wildcard covers,
# and the address that is the same machine written the way no public authority issues
# for. Duplicated rather than imported, because that file is about the socket and this
# one is about the sentence, and a shared constant would tie two subjects together.
NODE_NAME = "entry.example.test"

TCP_TRANSPORTS = sorted(
    name
    for name in discover()
    if Layer4.TCP in profile(name).meta.listens_on
    and delivery_site.DELIVERY_PORT >= profile(name).meta.port_range[0]
)

PARAMS: dict[str, object] = {
    "decoy_host": "www.example.com",
    "decoy_port": 443,
    "server_names": ["www.example.com"],
    "server_name": "front.example.com",
    "certificate_path": "/etc/hashi/certs/fullchain.pem",
    "certificate_key_path": "/etc/hashi/certs/privkey.pem",
    "tunnel_address": "10.71.0.1/24",
    "peer_tunnel_address": "10.71.0.2/24",
    "mtu": 1280,
    "junk_packet_count": 4,
    "junk_packet_min_size": 40,
    "junk_packet_max_size": 80,
    "init_packet_magic_header": 1020327352,
    "response_packet_magic_header": 2060487442,
    "underload_packet_magic_header": 3679305607,
    "transport_packet_magic_header": 1436947798,
}

pytestmark = pytest.mark.skipif(
    not TCP_TRANSPORTS, reason="this image ships no TCP transport"
)


async def a_delivery_node(client, *, address: str = NODE_NAME) -> str:
    """A node that carries users under a name — the two halves of "is this one"."""
    created = await client.post(
        "/api/nodes",
        json={
            "name": "entry",
            "address": address,
            "location_label": "Testland",
            "ssh_host": address,
            "ssh_private_key": GENERATED_SSH_KEY,
        },
    )
    assert created.status_code == 201, created.text
    node_id = created.json()["id"]
    declared = set(profile(TCP_TRANSPORTS[0]).params_model.model_fields)
    supplied = {**PARAMS, "port": delivery_site.DELIVERY_PORT + 1}
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": TCP_TRANSPORTS[0],
            "params": {key: value for key, value in supplied.items() if key in declared},
        },
    )
    assert enabled.status_code == 201, enabled.text
    return node_id


async def nodes_screen(client) -> str:
    screen = await client.get("/panel/nodes")
    assert screen.status_code == 200
    return screen.text


# --- what the screen may claim is on the host ----------------------------------------


async def test_a_host_applied_before_any_certificate_existed_is_not_said_to_serve(
    client, accepting_nodes, settings: Settings, tmp_path: pathlib.Path, monkeypatch
) -> None:
    """The state every fleet is in the moment a delivery certificate is configured.

    The apply happens with no certificate anywhere, so nothing is placed: no listener, no
    container, no key. Configuring the pair afterwards changes what this control plane
    WOULD place and nothing at all about the host — and the screen used to read the
    transport row's ``applied_at`` and announce a listener with an expiry date.
    """
    monkeypatch.setattr(settings, "delivery_certificate_path", "")
    monkeypatch.setattr(settings, "delivery_key_path", "")
    node_id = await a_delivery_node(client)
    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 200

    certificate = a_delivery_certificate(tmp_path / "issued", days=90)
    monkeypatch.setattr(settings, "delivery_certificate_path", certificate[0])
    monkeypatch.setattr(settings, "delivery_key_path", certificate[1])

    screen = await nodes_screen(client)
    assert "nothing on this host serves refreshes yet" in screen
    assert "the last apply put a listener on this host" not in screen


async def test_the_screen_names_the_certificate_the_host_is_holding_after_a_renewal(
    client, accepting_nodes, settings: Settings, tmp_path: pathlib.Path, monkeypatch
) -> None:
    """The renewal case, which is the defect pointed at the number it exists to show.

    Replacing the pair on disk is the whole of a renewal (``.env.example``), and until an
    apply reaches the host the host is still answering with the old one. A screen that
    printed the NEW expiry would over-promise the shutdown horizon by however long the
    operator waits before pressing Apply — on the one screen the bound is stated.
    """
    node_id = await a_delivery_node(client)
    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 200
    placed = delivery.configured_certificate(settings)
    assert placed is not None
    held_until = placed.not_after.strftime("%Y-%m-%d %H:%M")

    renewed = a_delivery_certificate(tmp_path / "renewed", days=365)
    monkeypatch.setattr(settings, "delivery_certificate_path", renewed[0])
    monkeypatch.setattr(settings, "delivery_key_path", renewed[1])
    current = delivery.configured_certificate(settings)
    assert current is not None
    assert current.not_after != placed.not_after

    screen = await nodes_screen(client)
    assert "answering with what an earlier apply put there" in screen
    assert held_until in screen
    assert current.not_after.strftime("%Y-%m-%d %H:%M") in screen
    # And the claim that would have been false: the host was never given this one.
    assert "the last apply put a listener on this host" not in screen

    # The next apply is what makes the two one certificate again, and the screen says so
    # without being asked twice.
    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 200
    settled = await nodes_screen(client)
    assert "the last apply put a listener on this host" in settled
    assert "answering with what an earlier apply put there" not in settled


async def test_a_host_holding_an_expired_pair_is_told_it_is_failing_now(
    client,
    session,
    accepting_nodes,
    settings: Settings,
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    """A renewal the operator left unapplied until after the old pair ran out.

    Every stock client refuses an expired certificate, so this host stopped answering
    refreshes at that moment — a different sentence from one still working on an older
    pair, and the only one of the four that reports a fault rather than a bound.

    Reaching it costs the only two things that produce it, and neither is a shortcut past
    the code under test: the pair the apply placed is aged on the row, because time is
    the only way a placed certificate expires and a test cannot spend it; and a different
    pair is configured, which is the renewal that leaves the host behind.
    """
    node_id = await a_delivery_node(client)
    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 200

    node = await nodes.get_node(session, node_id)
    assert node.delivery_placed_until is not None, "the apply recorded no certificate"
    node.delivery_placed_until = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
        days=2
    )
    await session.commit()

    renewed = a_delivery_certificate(tmp_path / "renewed", days=90)
    monkeypatch.setattr(settings, "delivery_certificate_path", renewed[0])
    monkeypatch.setattr(settings, "delivery_key_path", renewed[1])

    screen = await nodes_screen(client)
    assert "answering with a certificate that expired" in screen
    assert "refreshes from here are failing now" in screen
    assert "alongside the link you already have" not in screen


async def test_the_box_this_control_plane_runs_on_is_never_said_to_serve(
    client, accepting_nodes, monkeypatch
) -> None:
    """Co-location, on the screen — the half the record closed for free.

    An apply places no listener on the box this control plane is on, so it records none,
    and the sentence that used to be chosen from ``applied_at`` — which that box's own
    transport rows carry like any other host's — cannot be reached for it at all.
    """
    from control.app.services import delivery as control_delivery  # noqa: PLC0415
    from edge.bootstrap import node_stack as stack  # noqa: PLC0415

    from .conftest import pinned  # noqa: PLC0415

    async def compose_projects(connection) -> frozenset[str]:
        return frozenset({control_delivery.CONTROL_STACK_PROJECT})

    pinned(monkeypatch, stack, "compose_projects", compose_projects)
    node_id = await a_delivery_node(client)
    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 200

    screen = await nodes_screen(client)
    assert "the last apply put a listener on this host" not in screen
    assert "nothing on this host serves refreshes yet" in screen
    assert "unless this is the box this control plane runs on" in screen


# --- the words that go with the link --------------------------------------------------


async def test_the_link_is_handed_over_with_the_sentence_that_protects_it(
    client, accepting_nodes
) -> None:
    """The requirement M27.5 handed this step: a delivery URL travels with that wording.

    On the row for a host that is actually answering, because that is where the operator
    is when they are about to send someone a link on it.
    """
    node_id = await a_delivery_node(client)
    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 200

    screen = await nodes_screen(client)
    assert "alongside the link you already have" in screen
    assert "do not replace it" in screen
    assert "handed over out of band" in screen


async def test_a_host_that_is_not_answering_yet_is_not_given_words_for_a_link(
    client, accepting_nodes
) -> None:
    """And nowhere else. A link on a host with no listener answers nothing, so sending
    one with instructions is a support conversation about a URL that never worked."""
    await a_delivery_node(client)
    screen = await nodes_screen(client)
    assert "nothing on this host serves refreshes yet" in screen
    assert "alongside the link you already have" not in screen


def test_this_panel_composes_no_delivery_url_anywhere() -> None:
    """The first clause of what the screen tells the operator, pinned against the source.

    A delivery URL's path is a per-host digest of a person's token
    (``services/delivery.artifact_name``), and the panel says it shows nobody one. That
    is a statement about this codebase, so it is checked against this codebase: the
    derivation has exactly one caller, the push, and the day a screen composes one this
    goes red — at which point the sentence has to change and the wording above has to
    travel with whatever that screen shows.
    """
    root = pathlib.Path(__file__).resolve().parents[2] / "control"
    users = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if any(
            isinstance(node, ast.Name | ast.Attribute)
            and getattr(node, "id", getattr(node, "attr", None)) == "artifact_name"
            for node in ast.walk(ast.parse(path.read_text()))
        )
    )
    # The name in code, never in prose: this module's own comments discuss the
    # derivation, and a substring search would make every explanation of it a finding.
    assert users == ["app/services/delivery.py"], users
