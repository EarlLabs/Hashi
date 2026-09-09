"""Where does the traffic actually come out? — M5.4, and only an address can answer it.

WHAT: builds one real entry→leaf hop out of ``edge.relay.render_hop`` — two containers,
      two rendered configs, freshly minted keys, a real AmneziaWG handshake — and then
      asks a third host, which is only reachable past the leaf and also reachable
      directly from the entry, **which address it saw**.
WHY:  M3. Before it, every signal this product has was green while every friend exited
      in Russia: two ``active`` nodes, ``healthy: true``, ``drifted: []``, ``stale: []``,
      a hop with both ends and a nine-second-old handshake. Reading the rendered config
      would have shown the cause and not the fault. As the field proof puts it: *"the
      proof is the address, and only the internet can say it."*

      So this scenario asserts the address, and it is deliberately built so that a wrong
      render produces a WRONG ADDRESS rather than no answer. The entry has its own route
      to the destination — exactly as a real entry node does — so "the exit is the
      leaf's" is a discriminating claim and not a property of the topology.
HOW:  two networks the scenario creates and destroys, with docker choosing their subnets
      so nothing on the host can collide. The hop runs over the first; the destination
      sits on the second, which BOTH nodes can reach. The measurement is made from
      inside the entry container with its own ``nc``, bound to the address the entry's
      config says its way out is (``relay.exit_via``) — which is the kernel path the
      field proof measured on the live host, without a friend's client in the picture.

Nothing here logs, records or infers who connected to what. The only request made is
this scenario's own, from a container it started; the destination is configured to
discard its access log (``log { output discard }``) precisely so that observing traffic
does not create the one record the charter forbids.

Boundary — what a two-container relay on one host does NOT prove, stated plainly because
it is easy to over-read:

  * **No border is crossed.** Both "nodes" are on one kernel, one host and one clock.
    Nothing here says the hop survives a Russian carrier NAT, DPI, or a whitelist
    shutdown — that is charter criterion 1 and it is a field observation, forever.
  * **The obfuscation is not tested.** AmneziaWG's junk parameters are carried in the
    config and honoured by the daemon; whether they defeat an inspector is not a
    question a lab has.
  * **No MTU path.** A tunnel inside a tunnel across the real internet fragments; two
    containers on a bridge do not.
  * **The node's own kernel settings are given, not proven.** ``ip_forward`` and
    ``rp_filter`` are set on the containers here (see ``SYSCTLS``) because nothing in
    this project renders them — ``docs/tracker/M14/carry-over.md`` and
    ``docs/tracker/M3/carry-over.md`` say so. On a real node they are the host's own
    state, and this scenario cannot tell you they are right there.

What it does prove is the thing M3 shipped without: that these two rendered configs,
run, carry a friend's traffic out at the far end and never out of the near one — and
that when the far end stops, nothing comes out at all.
"""

import base64
import ipaddress
import pathlib
import subprocess
import textwrap
import time
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from edge import relay
from edge.bootstrap import node_stack
from edge.node import NodeView
from edge.registry import discover, profile

# The transports that can carry a hop AND whose data plane hands packets to the kernel.
# Derived, never named: ``hop_capable`` is the transport's own declaration, and a tool
# that takes its interface name from a config file is one that makes an interface. A
# proxy transport can also be an exit, but its way out is an address it binds rather than
# a route, which is a different measurement — ``exit_origin`` versus ``wg_quick_egress``.
HOP_TRANSPORTS = sorted(
    name
    for name, meta in discover().items()
    if meta.hop_capable
    and node_stack.DATA_PLANES[meta.config_format].interface_from_config_filename
)

# The destination — "the internet", for the length of one test. Pinned to the exact tag
# ``deploy/docker/caddy.Dockerfile`` already pins, so this scenario introduces no
# upstream dependency the project did not already have. It is an INSTRUMENT and never
# part of a node: it exists to answer the one question a rendered config cannot.
ECHO_IMAGE = "caddy:2.8.4-alpine"

# It answers with the source address it saw, and writes NOTHING down. Both halves matter:
# the address is the whole measurement, and a server that logged it would be the
# connection record this project may not create, in the test that proves the product does
# not create one.
ECHO_CONFIG = textwrap.dedent(
    """\
    {
    \tauto_https off
    }
    :80 {
    \tlog {
    \t\toutput discard
    \t}
    \trespond "{http.request.remote.host}"
    }
    """
)

# Kernel settings the two containers are given, because nothing in this project renders
# them and both are documented carry-overs rather than product behaviour:
#   * ``ip_forward`` — the leaf forwards what arrives over the hop. On a node this is
#     dockerd's side effect (docs/tracker/M14/carry-over.md).
#   * ``rp_filter`` — replies arrive on the hop interface from addresses the main table
#     would not route back that way, so strict reverse-path filtering drops them. Both
#     field hosts ship ``2`` (docs/tracker/M3/carry-over.md).
# Set here so this scenario measures the RENDERED CONFIG rather than the host it happens
# to run on. It follows that a green run says nothing about either being right on a node.
SYSCTLS = {
    "leaf": ["net.ipv4.ip_forward=1"],
    "entry": ["net.ipv4.conf.all.rp_filter=2", "net.ipv4.conf.default.rp_filter=2"],
}

# How long the two ends are given to complete a handshake before the measurement. A
# WireGuard handshake is one round trip on a local bridge; this is generous.
HANDSHAKE_SECONDS = 6

# The measurement's own timeout, and the value that makes "fail closed" observable: with
# the far end stopped, the request must run this out and return nothing.
REQUEST_SECONDS = 5


def run(arguments: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    """One docker command, captured. Each scenario in this directory carries its own."""
    return subprocess.run(arguments, capture_output=True, text=True, timeout=timeout)


def keypair() -> tuple[str, str]:
    """A real X25519 keypair, minted here and thrown away with the test.

    Real because the point is a real handshake: the frozen fixture keys in
    ``tests/edge/conftest.py`` are valid base64 of the right length and unrelated to each
    other, so two ends configured with them would come up and never agree.
    """
    private = X25519PrivateKey.generate()
    raw = private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return base64.b64encode(raw).decode(), base64.b64encode(public).decode()


@pytest.fixture(scope="module")
def amneziawg_hop_params() -> dict[str, object]:
    """The knobs one AmneziaWG hop end runs with, other than its keys and addresses.

    Named after the transport, by the same convention ``tests/edge/conftest.py`` uses:
    a transport that can carry a hop and arrives later needs a fixture named after
    itself here, and nothing else — the parametrisation below finds it or fails saying
    so. Every obfuscation value is arbitrary-but-fixed; in production they are per-node,
    because shared junk is itself a fingerprint.
    """
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


@pytest.fixture(scope="module")
def hop_tunnel() -> tuple[str, str]:
    """The two ends' addresses inside the tunnel. RFC 1918, and the operator's choice."""
    return "10.44.0.1/24", "10.44.0.2/24"


class Fleet:
    """Two nodes and a destination, on networks this object owns and destroys."""

    def __init__(self) -> None:
        self.tag = uuid.uuid4().hex[:12]
        self.containers: list[str] = []
        self.networks: list[str] = []

    def network(self, purpose: str) -> tuple[str, ipaddress.IPv4Network]:
        """Create one network and report the subnet DOCKER chose for it.

        Docker picks it from its own free pool, so this cannot collide with a network
        that already exists on the machine — and no address range is written down here.
        """
        name = f"hashi-m5-{purpose}-{self.tag}"
        created = run(["docker", "network", "create", name])
        assert created.returncode == 0, created.stderr
        self.networks.append(name)
        subnet = run(
            ["docker", "network", "inspect", "-f", "{{(index .IPAM.Config 0).Subnet}}", name]
        )
        assert subnet.returncode == 0, subnet.stderr
        return name, ipaddress.ip_network(subnet.stdout.strip())

    def start(self, purpose: str, arguments: list[str]) -> str:
        name = f"hashi-m5-{purpose}-{self.tag}"
        # Recorded BEFORE the attempt, not after it. A command the runtime cannot exec
        # leaves the container created and `docker run` reporting the failure itself, so
        # a name registered only on success is a container nothing ever removes.
        self.containers.append(name)
        created = run(["docker", "run", "-d", "--name", name, *arguments], timeout=900)
        assert created.returncode == 0, (
            f"could not start the {purpose} container:\n{created.stderr.strip()[:1000]}"
        )
        return name

    def attach(self, container: str, network: str, address: str) -> None:
        joined = run(["docker", "network", "connect", "--ip", address, network, container])
        assert joined.returncode == 0, joined.stderr

    def logs(self, container: str) -> str:
        result = run(["docker", "logs", "--tail", "40", container], timeout=60)
        return result.stdout + result.stderr

    def down(self) -> None:
        for container in self.containers:
            run(["docker", "rm", "-f", container], timeout=120)
        for network in self.networks:
            run(["docker", "network", "rm", network], timeout=120)


def address_seen_by(fleet: Fleet, node: str, destination: str, source: str | None) -> str:
    """Ask the destination which address it saw, from inside one node's own namespace.

    ``nc`` from the node's own image rather than a client container: this is the
    measurement the field proof made on the entry host itself, and it needs no tool the
    data-plane image does not already ship. ``-s`` binds the source address, which is
    what ``relay.exit_via`` names and what the entry's own ``ip rule`` selects on.

    Returns the body of the response — the address — or an empty string when nothing
    came back, which is what a hop that is down must produce.
    """
    bind = ["-s", source] if source else []
    request = run(
        [
            "docker",
            "exec",
            node,
            "sh",
            "-c",
            "printf 'GET / HTTP/1.0\\r\\n\\r\\n' | "
            f"nc {' '.join(bind)} -w {REQUEST_SECONDS} {destination} 80",
        ],
        timeout=REQUEST_SECONDS + 30,
    )
    # Everything after the first blank line is the body. Line endings are normalised
    # first because ``docker exec`` does not always hand back the CRLFs the server sent,
    # and a scenario that read an empty answer out of a successful request would report
    # "the hop is dead" about a hop that works.
    _, _, body = request.stdout.replace("\r\n", "\n").partition("\n\n")
    return body.strip()


@pytest.fixture(scope="module", params=HOP_TRANSPORTS)
def measured(request, engine, tmp_path_factory, hop_tunnel) -> dict:
    """One real hop, and every address measured across it — built once, read many times.

    Parametrised over the transports that can carry a hop, so one added later is measured
    by arriving. Its own ``<name>_hop_params`` fixture is resolved by convention; a
    transport that has none fails here, naming what to add, rather than being skipped.
    """
    transport_name = request.param
    params = request.getfixturevalue(f"{transport_name.replace('-', '_')}_hop_params")
    entry_tunnel, leaf_tunnel = hop_tunnel

    directory = tmp_path_factory.mktemp("hop")
    fleet = Fleet()
    try:
        transit, transit_subnet = fleet.network("transit")
        internet, internet_subnet = fleet.network("internet")
        addresses = {
            "entry_transit": str(transit_subnet[11]),
            "leaf_transit": str(transit_subnet[12]),
            "entry_internet": str(internet_subnet[11]),
            "leaf_internet": str(internet_subnet[12]),
            "destination": str(internet_subnet[20]),
        }

        entry_private, entry_public = keypair()
        leaf_private, leaf_public = keypair()
        # Symmetric by definition: two different values and the handshake never completes.
        preshared = base64.b64encode(uuid.uuid4().bytes * 2).decode()

        validate = profile(transport_name).validate
        ends = {}
        for role, own, far, private, public, address in (
            ("entry", entry_tunnel, leaf_tunnel, entry_private, entry_public, "entry_transit"),
            ("leaf", leaf_tunnel, entry_tunnel, leaf_private, leaf_public, "leaf_transit"),
        ):
            ends[role] = relay.HopEnd(
                node=NodeView(
                    id=str(uuid.uuid5(uuid.NAMESPACE_DNS, role)),
                    address=addresses[address],
                    location_label=role,
                    display_name=f"{role}-under-test",
                ),
                params=validate(
                    {
                        **params,
                        "tunnel_address": own,
                        "peer_tunnel_address": far,
                        "private_key": private,
                        "public_key": public,
                        "preshared_key": preshared,
                    }
                ),
            )

        # The product's own function, and the only place either config comes from.
        configs = dict(
            zip(
                ("entry", "leaf"),
                relay.render_hop(transport_name, entry=ends["entry"], leaf=ends["leaf"]),
                strict=True,
            )
        )

        service = node_stack.services_for({transport_name: configs["entry"]})[0]
        nodes = {}
        for role in ("leaf", "entry"):
            conf = directory / role
            conf.mkdir()
            (conf / pathlib.PurePosixPath(service["config_path"]).name).write_text(configs[role])
            arguments = [
                "--network", transit,
                "--ip", addresses[f"{role}_transit"],
                "-v", f"{conf}:{node_stack.CONFIG_DIR}:ro",
            ]
            for capability in service["capabilities"]:
                arguments += ["--cap-add", capability]
            for device in service["devices"]:
                arguments += ["--device", device]
            for sysctl in SYSCTLS[role]:
                arguments += ["--sysctl", sysctl]
            nodes[role] = fleet.start(role, [*arguments, service["image"], *service["command"]])
            fleet.attach(nodes[role], internet, addresses[f"{role}_internet"])

        fleet.start(
            "destination",
            [
                "--network", internet,
                "--ip", addresses["destination"],
                "-v", f"{_echo_config(directory)}:/etc/caddy/Caddyfile:ro",
                ECHO_IMAGE,
            ],
        )
        time.sleep(HANDSHAKE_SECONDS)

        for role in ("entry", "leaf"):
            running = run(["docker", "inspect", "-f", "{{.State.Running}}", nodes[role]])
            assert running.stdout.strip() == "true", (
                f"the {role}'s data plane is not running, so no address can be measured:\n"
                f"{fleet.logs(nodes[role])[-2000:]}"
            )

        # The near end of the hop, exactly as the entry's own config names it.
        exit_via = relay.exit_via(ends["entry"])
        measurements = {
            "through_the_hop": address_seen_by(
                fleet, nodes["entry"], addresses["destination"], exit_via
            ),
            "by_the_entrys_own_route": address_seen_by(
                fleet, nodes["entry"], addresses["destination"], None
            ),
            "main_route": run(
                ["docker", "exec", nodes["entry"], "ip", "route", "show", "table", "main"]
            ).stdout,
        }

        # Decision 3, measured: the far end goes away beneath a friend mid-session.
        run(["docker", "stop", "-t", "5", nodes["leaf"]], timeout=120)
        measurements["while_the_hop_is_down"] = address_seen_by(
            fleet, nodes["entry"], addresses["destination"], exit_via
        )
        run(["docker", "start", nodes["leaf"]], timeout=120)
        time.sleep(HANDSHAKE_SECONDS)
        measurements["after_the_hop_returns"] = address_seen_by(
            fleet, nodes["entry"], addresses["destination"], exit_via
        )

        yield {
            "transport": transport_name,
            "addresses": addresses,
            "exit_via": exit_via,
            **measurements,
        }
    finally:
        fleet.down()


def _echo_config(directory: pathlib.Path) -> pathlib.Path:
    path = directory / "Caddyfile"
    path.write_text(ECHO_CONFIG)
    return path


def test_the_traffic_comes_out_at_the_leaf(measured) -> None:
    """The whole charter, as one address. M3's measurement, in a lab.

    The entry can reach this destination by its own route — the next test proves it — so
    an entry that rendered no hop, or rendered it wrongly, answers here with its OWN
    address. That is the failure this project is most afraid of, and it is the one
    reading a config cannot see.
    """
    addresses = measured["addresses"]

    assert measured["through_the_hop"] == addresses["leaf_internet"], (
        f"traffic sourced from the entry's way out ({measured['exit_via']}) came out at "
        f"{measured['through_the_hop']!r}. It should have come out at the leaf "
        f"({addresses['leaf_internet']}); the entry's own address is "
        f"{addresses['entry_internet']}"
    )


def test_the_entry_could_have_reached_it_directly(measured) -> None:
    """The control, and without it the assertion above is about the topology, not the hop.

    A destination the entry cannot reach at all would make "the exit is the leaf's" true
    of any working tunnel and of nothing else. Here the entry has its own route to the
    same host — as a real entry node has to the whole internet — so the two answers are
    genuinely different and the measurement discriminates.
    """
    addresses = measured["addresses"]

    assert measured["by_the_entrys_own_route"] == addresses["entry_internet"], (
        "the entry cannot reach the destination by its own route, so this scenario "
        "cannot distinguish a hop that works from a destination that is simply not "
        "reachable except through one"
    )


def test_the_nodes_own_traffic_never_enters_the_hop(measured) -> None:
    """``Table = off`` plus source-based routing — the switch that saved the SSH session.

    The entry's peer is allowed ``0.0.0.0/0``, which is the only width that can carry a
    friend's traffic. What keeps that from swallowing the node itself is that wg-quick
    installs no routes: the main table still leaves by the node's own gateway, and only
    what is sourced from the tunnel's own address is diverted. On the field host this was
    the difference between a working apply and a node the control plane could no longer
    reach.
    """
    default = [
        line for line in measured["main_route"].splitlines() if line.startswith("default")
    ]

    assert default, "the entry has no default route in its main table at all"
    assert not any(measured["transport"] in line for line in default), (
        "the entry's MAIN routing table sends its default route into the hop, so the "
        f"node's own traffic — SSH above all — now leaves through it:\n{default}"
    )


def test_a_hop_that_is_down_takes_the_exit_with_it(measured) -> None:
    """Decision 3, fail closed: the friend loses their exit and gets NOTHING.

    The alternative — falling back to the entry's own route — is the failure this
    topology exists to prevent, and it would be invisible: pages would load.
    """
    addresses = measured["addresses"]

    assert measured["while_the_hop_is_down"] == "", (
        "something answered while the leaf was stopped: "
        f"{measured['while_the_hop_is_down']!r}"
    )
    assert measured["while_the_hop_is_down"] != addresses["entry_internet"], (
        "with its hop down, the entry answered with its OWN address — a friend in "
        "Russia exiting in Russia, with every screen still green"
    )
    assert measured["after_the_hop_returns"] == addresses["leaf_internet"], (
        "the exit did not come back when the leaf did, so a hop outage is permanent "
        "until somebody re-applies"
    )


def test_there_is_a_hop_capable_transport_to_measure() -> None:
    """An empty parametrisation would make every scenario above vacuously green."""
    assert HOP_TRANSPORTS, (
        "no installed transport declares itself hop-capable with a kernel data plane, so "
        "nothing above ran and the suite is green about a hop it never built"
    )
