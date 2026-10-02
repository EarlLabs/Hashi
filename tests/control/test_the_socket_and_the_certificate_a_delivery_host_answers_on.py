"""What a delivery host answers on, and what it is answered under — M27.6.

WHAT: the socket the listener holds and the refusal that keeps a transport off it; the
      name a host is reached under; the certificate this control plane pushes; and what
      an apply does when there is no usable one.
WHY:  a delivery host always carries a user-facing transport — that is the first half of
      the question which chooses it — so the listener and that transport are on one
      machine and contend for one socket. The owner settled it on 2026-09-27: the socket
      is delivery's, and a transport that wants it is refused with a sentence. And a
      public certificate authority will not issue for an address, so the name is derived
      from the node's own record and a host that has none serves nothing.
HOW:  the refusal through the API, because a refusal an operator never meets is not one;
      the listener through an apply against the shared ``accepting_nodes`` harness, whose
      connection records the three files this step places.

Boundary: nothing here runs a listener, reaches a host or validates a certificate chain.
That the rendered site binds one socket and serves what it says is a real engine's
answer and is measured in ``tests/e2e/infra/``; what is asked here is which hosts are
given one, under what name, and what happens when the certificate runs out.
"""

import datetime
import pathlib

import pytest

from control.app.services import delivery
from control.app.settings import Settings
from edge.bootstrap import delivery_site, node_stack
from edge.registry import Layer4, discover, profile

from .conftest import GENERATED_SSH_KEY, a_delivery_certificate

# The name the suite's wildcard covers. A host reached under it is a delivery host; the
# address beside it is the same machine spelled the way a public certificate authority
# cannot issue for, which is the whole of why one of the two serves delivery.
NODE_NAME = "entry.example.test"
NODE_ADDRESS = "192.0.2.61"

# A transport that binds TCP and one that binds UDP, resolved from the registry rather
# than named — the pair is the point, because the rule is about a SOCKET and not about a
# number, and a transport added later joins whichever side it declares.
TCP_TRANSPORTS = sorted(
    name
    for name in discover()
    if Layer4.TCP in profile(name).meta.listens_on
    and delivery_site.DELIVERY_PORT >= profile(name).meta.port_range[0]
)
UDP_ONLY_TRANSPORTS = sorted(
    name
    for name in discover()
    if profile(name).meta.listens_on == frozenset({Layer4.UDP})
)

PARAMS: dict[str, object] = {
    "decoy_host": "www.example.com",
    "decoy_port": 443,
    "server_names": ["www.example.com"],
    "server_name": "front.example.com",
    "certificate_path": "/etc/hashi/certs/fullchain.pem",
    "certificate_key_path": "/etc/hashi/certs/privkey.pem",
    "tunnel_address": "10.61.0.1/24",
    "peer_tunnel_address": "10.61.0.2/24",
    "mtu": 1280,
    "junk_packet_count": 4,
    "junk_packet_min_size": 40,
    "junk_packet_max_size": 80,
    "init_packet_magic_header": 1020327352,
    "response_packet_magic_header": 2060487442,
    "underload_packet_magic_header": 3679305607,
    "transport_packet_magic_header": 1436947798,
}


def params_for(transport_name: str, port: int) -> dict[str, object]:
    declared = set(profile(transport_name).params_model.model_fields)
    supplied = {**PARAMS, "port": port}
    return {key: value for key, value in supplied.items() if key in declared}


async def a_node(client, *, name: str = "entry", address: str = NODE_NAME) -> str:
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
    return created.json()["id"]


async def enable(client, node_id: str, transport_name: str, port: int):
    return await client.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": transport_name,
            "params": params_for(transport_name, port),
        },
    )


# --- the socket, and who may hold it -------------------------------------------------


@pytest.mark.skipif(not TCP_TRANSPORTS, reason="this image ships no TCP transport")
async def test_a_transport_cannot_take_the_port_this_hosts_users_refresh_on(
    client,
) -> None:
    """The owner's decision of 2026-09-27, met where an operator meets it.

    This is the cost of the milestone as well as its mechanism: on an entry node the
    transport being refused is usually the one whose camouflage is being on the port an
    ordinary website is on, and the refusal says so rather than only saying no.
    """
    node_id = await a_node(client)
    refused = await enable(client, node_id, TCP_TRANSPORTS[0], delivery_site.DELIVERY_PORT)
    assert refused.status_code == 409, refused.text
    message = refused.json()["error"]["message"]
    assert str(delivery_site.DELIVERY_PORT) in message
    assert "refresh" in message


@pytest.mark.skipif(not TCP_TRANSPORTS, reason="this image ships no TCP transport")
async def test_the_same_transport_on_any_other_port_is_accepted(client) -> None:
    """The refusal is about one socket and not about the transport, and a rule that
    refused more would be one an operator works around by leaving the feature off."""
    node_id = await a_node(client)
    accepted = await enable(
        client, node_id, TCP_TRANSPORTS[0], delivery_site.DELIVERY_PORT + 1
    )
    assert accepted.status_code == 201, accepted.text


@pytest.mark.skipif(
    not UDP_ONLY_TRANSPORTS, reason="this image ships no UDP-only transport"
)
async def test_a_udp_transport_may_hold_the_same_number(session, settings) -> None:
    """A PORT NUMBER IS NOT A PORT, and this is the measurement that makes it true here.

    The rendered site binds TCP alone — ``protocols h1 h2`` takes HTTP/3's UDP listener
    away, measured on the pinned image — so an obfuscated tunnel on the same number is
    two sockets and no conflict, which is the rule this module has always applied to two
    transports. Had the listener kept HTTP/3, this pair would have contended over a
    socket no table in the product names, on a host nobody gets a shell on easily.

    Asked of the service and not through the API, because every UDP transport this image
    ships declares a port range that starts above this socket — so the state is
    unreachable from a form today, and a rule that is only true because a validator
    happens to refuse the input first is a rule that stops being true when one does not.
    """
    from control.app.services import placement  # noqa: PLC0415

    await placement.delivery_socket_is_free(
        session,
        node=a_record(NODE_NAME),
        transport_name=UDP_ONLY_TRANSPORTS[0],
        port=str(delivery_site.DELIVERY_PORT),
        settings=settings,
    )


@pytest.mark.skipif(not TCP_TRANSPORTS, reason="this image ships no TCP transport")
async def test_a_host_registered_by_address_keeps_the_port_for_its_transport(
    client,
) -> None:
    """A host no certificate can be issued for serves no delivery, so nothing on it is
    holding that socket and refusing the transport would be a refusal for nothing."""
    node_id = await a_node(client, address=NODE_ADDRESS)
    accepted = await enable(client, node_id, TCP_TRANSPORTS[0], delivery_site.DELIVERY_PORT)
    assert accepted.status_code == 201, accepted.text


@pytest.mark.skipif(not TCP_TRANSPORTS, reason="this image ships no TCP transport")
async def test_retyping_a_port_onto_the_delivery_socket_is_refused_too(client) -> None:
    """The third path this family of rules is asked on. A row that was created legally
    and then retyped onto the socket is the same collision arriving later, and the
    rotation path is the only place it can be caught."""
    node_id = await a_node(client)
    created = await enable(
        client, node_id, TCP_TRANSPORTS[0], delivery_site.DELIVERY_PORT + 1
    )
    assert created.status_code == 201, created.text
    row_id = created.json()["id"]
    refused = await client.post(
        f"/api/transports/{row_id}/params",
        json={"params": params_for(TCP_TRANSPORTS[0], delivery_site.DELIVERY_PORT)},
    )
    assert refused.status_code == 409, refused.text
    assert str(delivery_site.DELIVERY_PORT) in refused.json()["error"]["message"]


# --- the name this host is reached under ----------------------------------------------


def a_record(address: str):
    from control.app.models import Node  # noqa: PLC0415

    return Node(id="n", name="n", address=address, location_label="nowhere")


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("entry.example.test", "entry.example.test"),
        ("192.0.2.61", None),
        ("2001:db8::1", None),
        ("[2001:db8::1]", None),
        ("entry", None),
        ("", None),
    ],
)
def test_the_name_a_delivery_host_is_reached_under_is_its_own_address(
    address: str, expected: str | None
) -> None:
    """Derived from the record and never a second field — M27.6.

    A bare label is refused with the addresses: a public authority issues for neither,
    and this product does not check that a name resolves anywhere, which is the
    operator's to arrange and this repository touches no record to do.
    """
    assert delivery.delivery_site_address(a_record(address)) == expected


# --- the certificate, and what happens when it runs out --------------------------------


def settings_with(base: Settings, **overrides) -> Settings:
    return base.model_copy(update=overrides)


def test_a_fleet_with_no_certificate_configured_stands_nothing_up(
    settings: Settings,
) -> None:
    """The supported default, and a state an operator can be in for a long time: every
    user refreshes against this control plane exactly as they did before."""
    bare = settings_with(settings, delivery_certificate_path="", delivery_key_path="")
    assert delivery.configured_certificate(bare) is None
    assert delivery.listener_for(a_record(NODE_NAME), bare) is None


def test_half_a_certificate_is_said_rather_than_ignored(settings: Settings) -> None:
    """One of the two configured is a mistake and not a mode, and a silent ``None``
    would leave the operator looking at a fleet that thinks it has an endpoint."""
    with pytest.raises(delivery.DeliveryCertificateUnusable):
        delivery.configured_certificate(
            settings_with(settings, delivery_key_path="")
        )


def test_a_certificate_that_is_not_one_is_said_rather_than_pushed(
    settings: Settings, tmp_path: pathlib.Path
) -> None:
    """The usual mistake is the key in the certificate's place, and pushing it would put
    a listener on a host that refuses every handshake."""
    wrong = tmp_path / "not-a-certificate.pem"
    wrong.write_text("-----BEGIN CERTIFICATE-----\nnope\n-----END CERTIFICATE-----\n")
    with pytest.raises(delivery.DeliveryCertificateUnusable):
        delivery.configured_certificate(
            settings_with(settings, delivery_certificate_path=str(wrong))
        )


def test_the_certificate_says_how_long_this_host_can_go_on_answering(
    settings: Settings,
) -> None:
    """The number the whole expiry answer rests on: delivery survives a shutdown only
    for as long as the certificate the host already holds, and the product's job is to
    make that visible before the border shuts rather than after."""
    certificate = delivery.configured_certificate(settings)
    assert certificate is not None
    assert datetime.timedelta(days=58) < certificate.remaining < datetime.timedelta(days=61)


def test_an_expired_certificate_stands_the_listener_down_rather_than_serving_it(
    settings: Settings, tmp_path: pathlib.Path
) -> None:
    """Every stock client refuses an expired certificate, so a listener serving one
    serves nobody — and the user cannot click through it inside a VPN client. Taking it
    down is the same outcome said honestly, and it takes the private key off the host."""
    expired = a_delivery_certificate(tmp_path / "expired", days=-1)
    stale = settings_with(
        settings, delivery_certificate_path=expired[0], delivery_key_path=expired[1]
    )
    assert delivery.configured_certificate(stale) is not None
    assert delivery.listener_for(a_record(NODE_NAME), stale) is None


def test_the_listener_is_rendered_for_this_hosts_own_name(settings: Settings) -> None:
    """One object, because the three pieces cannot be built apart without disagreeing:
    the service carries the digest of the site and the site carries the digest of the
    certificate."""
    listener = delivery.listener_for(a_record(NODE_NAME), settings)
    assert listener is not None
    assert NODE_NAME in listener.site
    assert delivery_site.DELIVERY_CERTIFICATE_PATH in listener.site
    # The service was built from THIS rendering and not from another one: its label is
    # the digest of the site above, which is what makes a changed site recreate the
    # container it is mounted into.
    assert listener.service["config_digest"] == node_stack.digest_of(listener.site)


def test_a_renewed_certificate_changes_what_the_node_is_handed(
    settings: Settings, tmp_path: pathlib.Path
) -> None:
    """Caddy reads its certificate once, at start, and ``up -d`` compares the service
    definition — so a renewal that did not change the definition would leave the
    container serving the expired one with the apply reporting success."""
    renewed = a_delivery_certificate(tmp_path / "renewed", days=90)
    before = delivery.listener_for(a_record(NODE_NAME), settings)
    after = delivery.listener_for(
        a_record(NODE_NAME),
        settings_with(
            settings, delivery_certificate_path=renewed[0], delivery_key_path=renewed[1]
        ),
    )
    assert before is not None and after is not None
    assert before.service["config_digest"] != after.service["config_digest"]


# --- what an apply puts on the host ----------------------------------------------------


@pytest.mark.skipif(not TCP_TRANSPORTS, reason="this image ships no TCP transport")
async def test_an_apply_stands_the_listener_up_on_a_host_of_its_own(
    client, accepting_nodes, monkeypatch
) -> None:
    """The whole of the wiring, end to end through the path an operator presses.

    The three files and the service, in the order they have to arrive: the certificate
    and the site are on the host before the compose file that mounts them, because a
    bind mount of a path nothing placed makes a DIRECTORY there and the container would
    not start.
    """
    placed = _watch_the_host(monkeypatch)
    node_id = await a_node(client)
    assert (
        await enable(client, node_id, TCP_TRANSPORTS[0], delivery_site.DELIVERY_PORT + 1)
    ).status_code == 201
    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 200

    assert placed.certificate is not None, "no certificate reached the host"
    assert "BEGIN CERTIFICATE" in placed.certificate[0]
    assert "PRIVATE KEY" in placed.certificate[1]
    assert placed.site is not None and NODE_NAME in placed.site
    assert delivery_site.DELIVERY_SERVICE in placed.compose
    assert placed.order == ["certificate", "site", "compose"]


@pytest.mark.skipif(not TCP_TRANSPORTS, reason="this image ships no TCP transport")
async def test_the_box_this_control_plane_runs_on_is_given_none_of_it(
    client, accepting_nodes, monkeypatch
) -> None:
    """Co-location, at the layer this step added to it — M27.4's requirement, applied to
    the three files M27.6 introduced. Absent rather than inert: no certificate, no site,
    no service in the compose file, and the private key taken back off."""
    from control.app.services import delivery as control_delivery  # noqa: PLC0415
    from edge.bootstrap import node_stack as stack  # noqa: PLC0415

    from .conftest import pinned  # noqa: PLC0415

    async def compose_projects(connection) -> frozenset[str]:
        return frozenset({control_delivery.CONTROL_STACK_PROJECT, "hashi-node"})

    pinned(monkeypatch, stack, "compose_projects", compose_projects)
    placed = _watch_the_host(monkeypatch)
    node_id = await a_node(client)
    assert (
        await enable(client, node_id, TCP_TRANSPORTS[0], delivery_site.DELIVERY_PORT + 1)
    ).status_code == 201
    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 200

    assert placed.certificate is None
    assert placed.site is None
    assert delivery_site.DELIVERY_SERVICE not in placed.compose
    assert placed.removals == 1


@pytest.mark.skipif(not TCP_TRANSPORTS, reason="this image ships no TCP transport")
async def test_an_expired_certificate_takes_the_private_key_off_the_host(
    client, accepting_nodes, monkeypatch, settings: Settings, tmp_path: pathlib.Path
) -> None:
    """The sharpest half of the expiry answer, and the reason it is a removal.

    A listener serving an expired certificate serves nobody, so what is left on the host
    is a private key for a name the fleet still uses and a listener that answers no
    handshake. The apply is NOT failed for it: an apply is how a blocked node's data
    plane is repaired, and a certificate is not a reason to refuse that.
    """
    expired = a_delivery_certificate(tmp_path / "expired", days=-1)
    monkeypatch.setattr(settings, "delivery_certificate_path", expired[0])
    monkeypatch.setattr(settings, "delivery_key_path", expired[1])
    placed = _watch_the_host(monkeypatch)
    node_id = await a_node(client)
    assert (
        await enable(client, node_id, TCP_TRANSPORTS[0], delivery_site.DELIVERY_PORT + 1)
    ).status_code == 201
    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 200

    assert placed.certificate is None
    assert delivery_site.DELIVERY_SERVICE not in placed.compose
    assert placed.removals == 1


class _Placed:
    """What the apply put on the host, in the order it put it there."""

    def __init__(self) -> None:
        self.certificate: tuple[str, str] | None = None
        self.site: str | None = None
        self.compose = ""
        self.order: list[str] = []
        self.removals = 0


def _watch_the_host(monkeypatch) -> _Placed:
    """Layered over ``accepting_nodes`` rather than replacing it, so ``pinned`` still
    compares each double against the real function it stands in for."""
    from edge.bootstrap import delivery_site as site_module  # noqa: PLC0415
    from edge.bootstrap import node_stack as stack  # noqa: PLC0415

    from .conftest import pinned  # noqa: PLC0415

    watched = _Placed()
    accepting_site = site_module.place_delivery_site
    accepting_certificate = site_module.place_delivery_certificate
    accepting_removal = site_module.remove_delivery_site
    accepting_compose = stack.place_compose

    async def place_delivery_site(connection, *, site: str) -> None:
        watched.site = site
        watched.order.append("site")
        await accepting_site(connection, site=site)

    async def place_delivery_certificate(connection, *, certificate: str, key: str) -> None:
        watched.certificate = (certificate, key)
        watched.order.append("certificate")
        await accepting_certificate(connection, certificate=certificate, key=key)

    async def remove_delivery_site(connection) -> None:
        watched.removals += 1
        await accepting_removal(connection)

    async def place_compose(connection, *, compose: str) -> None:
        watched.compose = compose
        watched.order.append("compose")
        await accepting_compose(connection, compose=compose)

    pinned(monkeypatch, site_module, "place_delivery_site", place_delivery_site)
    pinned(
        monkeypatch,
        site_module,
        "place_delivery_certificate",
        place_delivery_certificate,
    )
    pinned(monkeypatch, site_module, "remove_delivery_site", remove_delivery_site)
    pinned(monkeypatch, stack, "place_compose", place_compose)
    return watched


# --- what the operator is told, before the day it matters -------------------------------


@pytest.mark.skipif(not TCP_TRANSPORTS, reason="this image ships no TCP transport")
async def test_the_nodes_screen_says_how_long_this_host_can_go_on_answering(
    client, accepting_nodes
) -> None:
    """The owner's requirement of 2026-09-27: the remaining validity is VISIBLE before
    the border shuts, not discovered after.

    So it is on the row and not in a warning. A line that appeared only once something
    was wrong would first be read on the day it was already too late, and the bound it
    states is the honest one — delivery survives a shutdown for as long as the
    certificate the host is already holding, and no longer.
    """
    node_id = await a_node(client)
    assert (
        await enable(client, node_id, TCP_TRANSPORTS[0], delivery_site.DELIVERY_PORT + 1)
    ).status_code == 201
    unapplied = (await client.get("/panel/nodes")).text
    assert NODE_NAME in unapplied
    # BEFORE ANY APPLY there is no listener on the host, and the screen says which of the
    # two states this is rather than describing a machine that answers nothing.
    assert "nothing on this host serves refreshes yet" in unapplied
    assert "shutdown longer than that" not in unapplied

    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 200
    applied = (await client.get("/panel/nodes")).text
    assert "the last apply put a listener on this host" in applied
    assert "shutdown longer than that" in applied


@pytest.mark.skipif(not TCP_TRANSPORTS, reason="this image ships no TCP transport")
async def test_the_nodes_screen_says_why_a_host_serves_none(client) -> None:
    """The state an operator can sit in for months without noticing, so it gets a line
    of its own rather than the absence of one."""
    node_id = await a_node(client, address=NODE_ADDRESS)
    assert (
        await enable(client, node_id, TCP_TRANSPORTS[0], delivery_site.DELIVERY_PORT)
    ).status_code == 201
    body = (await client.get("/panel/nodes")).text
    assert "will not issue for an address" in body


async def test_a_node_nobody_fetches_from_is_told_nothing_about_delivery(client) -> None:
    """A leaf answers nobody, so a line saying it serves no refreshes would be a sentence
    about something that was never in question — and a screen of those is a screen an
    operator stops reading."""
    await a_node(client, name="leaf", address="leaf.example.test")
    assert "delivery —" not in (await client.get("/panel/nodes")).text


@pytest.mark.skipif(not TCP_TRANSPORTS, reason="this image ships no TCP transport")
async def test_a_user_facing_row_is_refused_where_something_already_holds_the_socket(
    session, settings
) -> None:
    """The other direction: a node becomes a delivery host by GAINING a user-facing row.

    Without this, the two rows could be created in the order that passes and the
    collision would appear on the node at apply, as a container that will not bind on a
    host nobody has a shell on.

    Asked of the service because the state it needs — a row already on the socket — is
    one the API now refuses to create, which is the point of the check above it.
    """
    from control.app.models import NodeTransport, TransportPurpose  # noqa: PLC0415
    from control.app.services import placement  # noqa: PLC0415

    node = a_record(NODE_NAME)
    session.add(node)
    session.add(
        NodeTransport(
            node_id=node.id,
            transport_name=TCP_TRANSPORTS[0],
            config_name=TCP_TRANSPORTS[0],
            purpose=TransportPurpose.RELAY_ENTRY,
            params={"port": delivery_site.DELIVERY_PORT},
        )
    )
    await session.flush()

    with pytest.raises(Exception, match="refresh"):
        await placement.delivery_socket_is_free(
            session,
            node=node,
            transport_name=TCP_TRANSPORTS[0],
            port=str(delivery_site.DELIVERY_PORT + 1),
            settings=settings,
            purpose=TransportPurpose.USERS,
        )


@pytest.mark.skipif(not TCP_TRANSPORTS, reason="this image ships no TCP transport")
async def test_a_hop_is_not_answered_about_a_transport_it_did_not_touch(
    session, settings
) -> None:
    """The narrowing, and the reason for it.

    A node whose rows already collide can only have been written before this check
    existed. Answering an operator laying a HOP with a sentence about a user-facing
    transport they did not submit, on a form that cannot fix it, is the defect M23's
    thirteenth round found in the revocation banner: a true sentence that sends
    somebody nowhere. The collision is still real and is met at the apply.
    """
    from control.app.models import NodeTransport, TransportPurpose  # noqa: PLC0415
    from control.app.services import placement  # noqa: PLC0415

    node = a_record(NODE_NAME)
    session.add(node)
    for purpose, port in (
        (TransportPurpose.USERS, delivery_site.DELIVERY_PORT),
        (TransportPurpose.RELAY_LEAF, delivery_site.DELIVERY_PORT + 2),
    ):
        session.add(
            NodeTransport(
                node_id=node.id,
                transport_name=TCP_TRANSPORTS[0],
                config_name=f"{TCP_TRANSPORTS[0]}-{purpose}",
                purpose=purpose,
                params={"port": port},
            )
        )
    await session.flush()

    await placement.delivery_socket_is_free(
        session,
        node=node,
        transport_name=TCP_TRANSPORTS[0],
        port=str(delivery_site.DELIVERY_PORT + 3),
        settings=settings,
        purpose=TransportPurpose.RELAY_ENTRY,
    )


@pytest.mark.skipif(not TCP_TRANSPORTS, reason="this image ships no TCP transport")
async def test_no_certificate_means_the_socket_is_the_transports(
    client, settings: Settings
) -> None:
    """The shipped default, and the refusal must not fire in it.

    With no certificate configured no host serves refreshes from anywhere — the Nodes
    screen says exactly that — so reserving the socket would tax every operator who
    never asked for the feature, and would answer them with a sentence the screen
    contradicts on the same host in the same second.
    """
    object.__setattr__(settings, "delivery_certificate_path", "")
    object.__setattr__(settings, "delivery_key_path", "")
    node_id = await a_node(client)
    accepted = await enable(client, node_id, TCP_TRANSPORTS[0], delivery_site.DELIVERY_PORT)
    assert accepted.status_code == 201, accepted.text
    body = (await client.get("/panel/nodes")).text
    assert "this control plane holds no delivery certificate" in body


@pytest.mark.skipif(not TCP_TRANSPORTS, reason="this image ships no TCP transport")
async def test_a_listener_that_will_not_come_up_degrades_the_node_and_names_the_port(
    client, accepting_nodes, monkeypatch
) -> None:
    """The one container a node runs for a PERSON was the only one nothing confirmed.

    It declares ``logging: driver: none``, so a listener that will not bind leaves no
    diagnostics anywhere — and before this the apply reported success over a host
    answering no refresh at all, while the Nodes screen said users could refresh from it.

    This is also what closes the hazard ``placement`` leaves open on purpose: a transport
    put on the socket before a certificate existed is met here, with the port named.
    """
    from edge.health import listening  # noqa: PLC0415

    from .conftest import pinned  # noqa: PLC0415

    async def bound_ports(connection):
        # Every port held EXCEPT the delivery listener's: a node whose data plane came
        # back and whose listener bound nothing, which is the state under test.
        return {Layer4.TCP: frozenset({delivery_site.DELIVERY_PORT + 1}), Layer4.UDP: frozenset()}

    pinned(monkeypatch, listening, "bound_ports", bound_ports)
    node_id = await a_node(client)
    assert (
        await enable(client, node_id, TCP_TRANSPORTS[0], delivery_site.DELIVERY_PORT + 1)
    ).status_code == 201
    refused = await client.post(f"/api/nodes/{node_id}/apply")
    assert refused.status_code != 200, refused.text
    assert delivery_site.DELIVERY_SERVICE in refused.json()["error"]["message"]
