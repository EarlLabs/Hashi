"""Where does the traffic come out, and where was the NAME looked up? — M5.4 and M16.

WHAT: builds one real entry→leaf hop out of ``edge.relay.render_hop`` — two containers,
      two rendered configs, freshly minted keys, a real AmneziaWG handshake — and then
      asks two questions of it that no rendered config can answer. First, of a third host
      which is only reachable past the leaf and also reachable directly from the entry:
      **which address did it see**. Then, with a friend's own client dialling the entry's
      friend-facing proxy and asking for a NAME: **which address did the RESOLVER see**.
WHY:  M3, and then M16 — the same failure asked twice, because the first answer hid the
      second. Before M3, every signal this product has was green while every friend
      exited in Russia: two ``active`` nodes, ``healthy: true``, ``drifted: []``,
      ``stale: []``, a hop with both ends and a nine-second-old handshake. Reading the
      rendered config would have shown the cause and not the fault. As the field proof
      puts it: *"the proof is the address, and only the internet can say it."*

      M16 is what that proof did not cover, found by M3's own reviewer minutes after it
      landed. "What address does the internet see" and "who resolved the name" are
      different questions, and only the first had ever been asked: the exit moved to
      Amsterdam while the list of names a friend asked for, in order and with timing,
      was still resolved by a resolver on the Russian side of the hop. A proxy hands the
      name to its host's resolver before it dials, and ``sendThrough`` binds the dial.
      So the second half of this file watches WHERE THE LOOKUP GOES, and it is built so
      that the config which leaks and the config which does not are indistinguishable
      from the friend's seat — same page, same exit address, same everything except the
      one packet the resolver saw.

      Both halves are deliberately built so that a wrong render produces a WRONG ADDRESS
      rather than no answer. The entry has its own route to the destination AND to the
      resolver — exactly as a real entry node does — so "the exit is the leaf's" and "the
      lookup left by the leaf" are discriminating claims and not properties of the
      topology.
HOW:  two networks the scenario creates and destroys. The hop runs over the first, whose
      subnet is docker's own choice so that nothing on the host can collide; the
      destination, the resolver and the friend sit on the second, which BOTH nodes can
      reach and which is addressed in ``THE_INTERNET`` — reserved, and globally routable,
      because since M23's tenth round a friend's proxy refuses what is not. The exit
      measurement is made from inside the entry container with its own ``nc``, bound to
      the address the entry's config says its way out is (``relay.exit_via``) — the
      kernel path the field proof measured on the live host. The lookup measurement needs
      a friend, because only a friend's connection carries a name into the proxy: an Xray
      client configured from the product's OWN ``render_client`` output, handed a name
      rather than an address, dialling a proxy whose config is the product's own
      ``render_server`` under ``Egress.HOP``.

Nothing here logs, records or infers who connected to what. The only requests made are
this scenario's own, from containers it started, about a synthetic friend that does not
exist. The destination is configured to discard its access log (``log { output
discard }``) and the resolver is configured with ``access: none`` and ``dnsLog: false``,
precisely so that observing traffic does not create the one record the charter forbids.

**What the lookup instrument retains, exactly.** Not the query. The resolver ANSWERS from
a fixed table and writes nothing; what is read back is three integers held in the
resolver container's own kernel — a count of UDP packets to port 53 from the leaf, from
the entry, and from anything else (``LOOKUP_COUNTERS``). A packet counter cannot hold a
name, an asker or a time, which is why it was chosen over anything that parses a query:
the strongest form of "we looked at where it went and not at what it was". The counters
live in a container this fixture destroys, for the length of one test, and the only name
ever looked up is ``LOOKUP_NAME`` — a reserved example domain belonging to nobody.

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
  * **The resolver here is one container away, not one country away.** The lookup half
    proves the query left by the leaf and not by the entry. It cannot prove the resolver
    a node's record actually names is reachable THROUGH a real hop, that it answers in
    time across a tunnel inside a tunnel, or that the node's own ``/etc/resolv.conf`` is
    not consulted by something else on a real host. Those are field observations — M16's
    acceptance walk, on the owner's two hosts.

What it does prove is the two things M3 and M16 shipped without: that these rendered
configs, run, carry a friend's traffic out at the far end and never out of the near one
— that when the far end stops, nothing comes out at all — and that a friend who asks for
a NAME has that name looked up from the far end too, where a config one key different
looks identical from every seat but the resolver's.
"""

import base64
import dataclasses
import ipaddress
import json
import pathlib
import re
import subprocess
import textwrap
import time
import urllib.parse
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from edge import relay
from edge.bootstrap import node_stack
from edge.egress import NOT_THE_INTERNET, Egress
from edge.node import Credential, NodeView
from edge.registry import SubscriptionFormat, discover, profile

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

# The transports whose data plane is a PROXY rather than a kernel tunnel — the only ones
# the lookup question is even about. Derived from the same declaration ``HOP_TRANSPORTS``
# reads, and its exact complement: a tool that takes its interface name from a config file
# makes an INTERFACE, and the kernel routes whatever leaves it, lookup and traffic alike.
# A proxy terminates a friend's connection and opens its own, so it must turn the name
# into an address ITSELF before it dials — which is the whole of M16, and is true of no
# kernel tunnel.
PROXY_TRANSPORTS = sorted(
    name
    for name, meta in discover().items()
    if not node_stack.DATA_PLANES[meta.config_format].interface_from_config_filename
)

# Of those, the ones a friend cannot be dialled into HERE, each with the reason. Written
# down rather than skipped: ``test_every_proxy_transport_is_measured_or_excused`` holds
# this against ``PROXY_TRANSPORTS``, so a proxy transport added later is either measured
# by arriving or turns this file red until somebody says why it cannot be.
NO_FRIEND_HERE = {
    "vless-reality": (
        "a Reality server dials its decoy `dest` for every connection and fails the "
        "connection when that dial fails — including for a client holding CORRECT keys. "
        "So no friend can be dialled into one here without also standing up a TLS 1.3 "
        "host for it to borrow: a second instrument, and a different question. "
        "MEASURED, not recalled, against the pinned binary in .tools/xray (1.8.24, the "
        "same version DATA_PLANES pins) on loopback, because an excuse resting on "
        "remembered protocol behaviour is worth nothing: with `dest` pointed at a closed "
        "port, a correctly-keyed client received NOTHING and the server logged "
        "`REALITY: failed to dial dest: ... connection refused`; with the same client, "
        "the same keys and the same config except a live TLS 1.3 `dest`, the request "
        "completed. The two runs differed in nothing but whether the decoy answered. "
        "(What is NOT established is the ordering — whether the dial strictly precedes "
        "authentication in the code. It does not need to be: what excuses this transport "
        "is that the decoy is required at all.) What this scenario measures with packets "
        "is asserted for this transport too, on the rendered config, by "
        "tests/edge/test_a_friends_lookup_leaves_through_the_hop.py, which is "
        "parametrised over every transport rather than over this shortlist."
    ),
}

# The proxy transports a friend is actually dialled into below.
FRIEND_TRANSPORTS = [name for name in PROXY_TRANSPORTS if name not in NO_FRIEND_HERE]

# The destination — "the internet", for the length of one test. Pinned to the exact tag
# ``deploy/docker/caddy.Dockerfile`` already pins, so this scenario introduces no
# upstream dependency the project did not already have. It is an INSTRUMENT and never
# part of a node: it exists to answer the one question a rendered config cannot.
ECHO_IMAGE = "caddy:2.8.4-alpine"

# The friend's own device — a container with a shell and a ``nc``, standing in for a
# phone. The same image as the destination and pinned for the same reason; named
# separately because it plays a different part, and because a reader replacing one of
# them should not silently replace the other. It holds the network namespace its Xray
# client runs in, so that a request can be made from the friend's seat with ``docker
# exec`` — the client's own image ships no shell at all.
DEVICE_IMAGE = ECHO_IMAGE

# The name a friend asks for, and the ONLY name anything in this file ever looks up. A
# reserved example domain (RFC 2606) belonging to nobody, like every fixture in this zone.
#
# It is also registered as the destination container's network alias, which is what makes
# the negative half of the lookup measurement sharp rather than merely red: with the
# product's ``domainStrategy`` taken out, the proxy asks its HOST's resolver — here
# docker's embedded one, which knows this name — and the friend's page still loads, from
# the leaf's address, with nothing anywhere saying the lookup went home. That is M16's
# bug reproduced exactly, not approximated.
LOOKUP_NAME = "destination.example.com"

# The chain in the resolver's own kernel that counts arriving lookups by source address,
# and the whole of the lookup measurement. Three rules, all ``RETURN``: this COUNTS, it
# does not filter, and every packet goes on to be answered exactly as it would without
# them. See this module's docstring for why a packet counter and not a parsed query —
# a counter cannot hold a name.
LOOKUP_COUNTERS = "lookups"

# The port a friend's own client listens on inside its own network namespace, and the
# port the proxy under test serves on. Fixed here because they are this fixture's choice
# and nothing else's; on a node both are operator data (``params.port``).
FRIEND_PORT = 1080
PROXY_PORT = 8443

# The range the "internet" of this scenario is addressed in, and the ONE address range
# this file writes down. Everything else still comes from the subnet docker chose.
#
# It has to be written down, and M23's tenth round is why. A friend's proxy now REFUSES
# every destination off the public internet (``edge.egress.NOT_THE_INTERNET``) and, since
# the same round, resolves a name before it decides — so a destination inside docker's own
# pool, which is RFC 1918 and therefore squarely inside that list, is a destination a
# friend can no longer reach. Left as it was, this scenario would go on passing for the
# wrong reason for exactly as long as it took somebody to notice: the friend's half asks
# for a NAME, and at the routing strategy this file's configs used to carry, a name was
# never compared against an address at all.
#
# So the stand's internet became genuinely globally-routable addressing, which is what it
# always claimed to be. ``192.88.99.0/24`` is the deprecated 6to4 relay anycast block: it
# is reserved, so it is nobody's host and no traffic can leave for it; it is GLOBAL by the
# standard library's own answer, which the guard below holds it to; and it is the same
# stand-in ``tests/edge`` already uses for the word.
#
# This is not the hardcoded address ``CLAUDE.md`` forbids, by the same argument
# ``NOT_THE_INTERNET`` carries: it names nothing of any node, it is a registry value
# identical everywhere, and no node this fleet can register is reachable at one of these
# addresses. It is a property of the instrument, never of the product.
THE_INTERNET = "192.88.99.0/24"

# How long a userspace proxy is given to load its config and bind. Xray reports "started"
# in well under a second on an idle engine; this is generous.
PROXY_SECONDS = 3

# How many times a friend's request is attempted before it is believed to have failed.
# A retry rather than a longer sleep because the first attempt after a container starts
# is the one that races, and because a lookup that succeeded is cached by the proxy — so
# extra attempts cost nothing and prove nothing extra either way.
FRIEND_ATTEMPTS = 3

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

    def network(
        self, purpose: str, subnet: str | None = None
    ) -> tuple[str, ipaddress.IPv4Network]:
        """Create one network and report the subnet it ended up with.

        Docker picks it from its own free pool unless a subnet is named, which means a
        network created here cannot collide with one that already exists on the machine,
        and no address range has to be written down.

        ``subnet`` is named for exactly one of the two networks below — see
        ``THE_INTERNET``, and read its reasoning before removing the argument. The cost of
        naming one is real and is accepted rather than unnoticed: two runs of this file at
        the same time would both ask for that range and the second would fail here, loudly
        and with docker's own message, instead of quietly sharing a bridge.
        """
        name = f"hashi-m5-{purpose}-{self.tag}"
        created = run(
            ["docker", "network", "create", *(["--subnet", subnet] if subnet else []), name]
        )
        where = subnet or "the pool docker chooses from"
        assert created.returncode == 0, (
            f"could not create the {purpose} network on {where}:\n"
            f"{created.stderr.strip()}\nA named range is in use by something else on this "
            "machine — another run of this scenario, or a route that already exists."
        )
        self.networks.append(name)
        reported = run(
            ["docker", "network", "inspect", "-f", "{{(index .IPAM.Config 0).Subnet}}", name]
        )
        assert reported.returncode == 0, reported.stderr
        return name, ipaddress.ip_network(reported.stdout.strip())

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
        # The transit link keeps docker's own pool: it is the path the hop itself runs
        # over, carried by a kernel tunnel no routing rule of ours is anywhere near. The
        # other one is where a friend's traffic goes, so it has to BE the internet.
        transit, transit_subnet = fleet.network("transit")
        internet, internet_subnet = fleet.network("internet", THE_INTERNET)
        addresses = {
            "entry_transit": str(transit_subnet[11]),
            "leaf_transit": str(transit_subnet[12]),
            "entry_internet": str(internet_subnet[11]),
            "leaf_internet": str(internet_subnet[12]),
            "destination": str(internet_subnet[20]),
            # The lookup half's two, derived here with the rest so that every address in
            # this scenario comes from the subnet docker chose and none is written down.
            # The resolver is on the internet network and NOT behind the leaf, which is
            # what makes "the lookup left by the leaf" a discriminating claim: the entry
            # can reach it perfectly well by its own route, and a proxy that resolved at
            # home would be seen doing exactly that rather than seen failing.
            "resolver": str(internet_subnet[30]),
            "friend": str(internet_subnet[40]),
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
                    resolver=None,
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
                # Registered under the name a friend asks for, so that a proxy which
                # resolves through its HOST — the M16 leak — finds it and succeeds.
                # Nothing in the exit half uses this; see ``LOOKUP_NAME``.
                "--network-alias", LOOKUP_NAME,
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
            # The live fleet itself, so the lookup half can add its own containers to
            # THIS hop instead of building a second one — see ``looked_up``. Handed over
            # rather than rebuilt because a hop costs two images, two keypairs and a
            # handshake, and because the question M16 asks is about this hop and not
            # about one that resembles it.
            "fleet": fleet,
            "nodes": nodes,
            "ends": ends,
            "networks": {"transit": transit, "internet": internet},
            "directory": directory,
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


def test_the_internet_in_this_scenario_is_actually_the_internet() -> None:
    """The assumption the friend half rests on since M23's tenth round, held not assumed.

    A friend's proxy refuses every destination in ``NOT_THE_INTERNET`` and, since the same
    round, resolves a NAME to an address before it decides — so if this scenario's
    "internet" were addressed out of docker's own pool, which is RFC 1918, the friend
    would be refused by the product and every assertion about the lookup would be about a
    request that never happened. That is not hypothetical: it is what this file did until
    that round, and it passed, because a name was never compared against an address.

    Asserted against the same list the proxy refuses rather than against ``is_global``
    alone, so a range added to that list which happened to cover this one turns this file
    red here — with a sentence — instead of turning it red four fixtures later with a
    friend who cannot reach anything.
    """
    internet = ipaddress.ip_network(THE_INTERNET)

    assert internet.is_global, (
        f"{THE_INTERNET} is not globally routable, so a friend's proxy is entitled to "
        "refuse everything this scenario calls the internet"
    )
    for refused in NOT_THE_INTERNET:
        assert not internet.overlaps(ipaddress.ip_network(refused)), (
            f"this scenario's internet ({THE_INTERNET}) is inside {refused}, which every "
            "friend-facing config this project renders refuses. Nothing below measures "
            "what it claims to"
        )


# ── M16: and where was the name looked up? ────────────────────────────────────────────


def resolver_config(answer: str) -> str:
    """The instrument a node's record points at, and the reason it can leak nothing.

    An Xray in the same pinned image the node itself runs — taken from the product's own
    ``DATA_PLANES`` declaration rather than pinned again here, so this scenario still
    introduces no upstream dependency the project did not already have. It is an
    INSTRUMENT and never part of a node.

    It ANSWERS, which matters more than it looks. A resolver that stayed silent would
    make the two halves of this measurement differ in what a friend sees — one page
    loading and one not — and the whole point of M16 is that the leak is invisible from
    the friend's seat. It also leaves Xray in the timeout-and-fall-back path, which is
    behaviour nobody wants a proof to depend on. So it answers, from ``hosts``, in
    memory, for exactly one name, with no upstream configured and nothing to forward to.

    What it writes down is nothing. ``access: none`` and ``dnsLog: false`` are the same
    two settings the product renders on a node with a hop, for the same reason, and
    ``warning`` is below the level at which this daemon reports a query at all.
    """
    return json.dumps(
        {
            "log": {"loglevel": "warning", "access": "none", "dnsLog": False},
            # One name, one answer, held in memory for the length of one test. Every
            # other name would fall through to this container's own resolver, which is a
            # path nothing here ever takes: ``LOOKUP_NAME`` is the only name a friend in
            # this scenario ever asks for.
            "dns": {"hosts": {LOOKUP_NAME: answer}, "queryStrategy": "UseIPv4"},
            "inbounds": [
                {
                    "tag": "queries",
                    "listen": "0.0.0.0",
                    "port": 53,
                    "protocol": "dokodemo-door",
                    "settings": {"address": "127.0.0.1", "port": 53, "network": "udp"},
                }
            ],
            "outbounds": [{"tag": "answers", "protocol": "dns"}],
            "routing": {
                "rules": [
                    {"type": "field", "inboundTag": ["queries"], "outboundTag": "answers"}
                ]
            },
        },
        indent=2,
    )


def in_the_resolvers_namespace(image: str, capabilities: list[str], resolver: str, script: str):
    """Run one command inside the RESOLVER container's network namespace.

    ``--network container:`` is the same namespace sharing a real node uses: under
    ``network_mode: host`` every data-plane container on a node is already in one
    namespace, which is how a proxy's ``sendThrough`` can name an address a different
    container's tunnel created. Here it is what lets the counting rules be installed by
    an image that ships ``iptables`` — which the resolver's own image does not, and must
    not: it answers queries and does nothing else.

    The image is the HOP's data plane, already running in this fleet and already
    declaring ``iptables`` among its executables, so nothing new is pulled to count
    three numbers.
    """
    return run(
        [
            "docker", "run", "--rm",
            "--network", f"container:{resolver}",
            *[argument for capability in capabilities for argument in ("--cap-add", capability)],
            "--entrypoint", "sh",
            image, "-c", script,
        ],
        timeout=120,
    )


# One rule per bucket, all ``RETURN``. ``iptables-save -c`` writes each back with its
# packet count in front of it, which is the whole of what this instrument reads.
COUNTED = re.compile(rf"^\[(\d+):\d+\]\s+-A\s+{LOOKUP_COUNTERS}\b")
COUNTED_SOURCE = re.compile(r"-s\s+(\S+)")

# The bucket for a lookup that came from neither node — nothing should ever land in it,
# and a test says so, because a query arriving from somewhere this scenario did not
# predict means the measurement is about something other than what it claims.
ELSEWHERE = "elsewhere"


def install_lookup_counters(image, capabilities, resolver: str, sources: dict[str, str]) -> None:
    """Teach the resolver's own kernel to count arriving lookups by source address.

    Chosen over any instrument that reads a query, and that is a charter decision rather
    than a convenience: a packet counter is physically incapable of holding a name, an
    asker or a time, so the one record this project may never create cannot be created
    here even by accident, even "temporarily, while debugging". What comes back is three
    integers. See this module's docstring.
    """
    rules = [
        f"iptables -N {LOOKUP_COUNTERS}",
        f"iptables -A INPUT -p udp --dport 53 -j {LOOKUP_COUNTERS}",
    ]
    rules += [
        f"iptables -A {LOOKUP_COUNTERS} -s {address} -j RETURN"
        for address in sources.values()
    ]
    # The catch-all last, so it counts what the named sources did not.
    rules.append(f"iptables -A {LOOKUP_COUNTERS} -j RETURN")
    installed = in_the_resolvers_namespace(image, capabilities, resolver, "; ".join(rules))
    assert installed.returncode == 0, (
        f"the lookup counters could not be installed, so nothing below measures "
        f"anything:\n{installed.stderr.strip()[:1000]}"
    )


def lookups_by_source(
    image, capabilities, resolver: str, sources: dict[str, str]
) -> dict[str, int]:
    """How many lookups have arrived from each named source since the last zeroing.

    Keyed by the scenario's own name for each address (``leaf``, ``entry``) plus
    ``ELSEWHERE``, so an assertion reads as the question it is asking rather than as a
    comparison of two strings that happen to be addresses.
    """
    saved = in_the_resolvers_namespace(image, capabilities, resolver, "iptables-save -c")
    assert saved.returncode == 0, f"the lookup counters could not be read:\n{saved.stderr[:1000]}"

    by_address: dict[str, int] = {}
    for line in saved.stdout.splitlines():
        counted = COUNTED.match(line.strip())
        if not counted:
            continue
        found = COUNTED_SOURCE.search(line)
        # ``iptables`` writes a bare address back with its prefix; the catch-all rule has
        # no ``-s`` at all and is the only one that does not.
        key = found.group(1).split("/")[0] if found else ELSEWHERE
        by_address[key] = int(counted.group(1))

    counts = {name: by_address.get(address, 0) for name, address in sources.items()}
    counts[ELSEWHERE] = by_address.get(ELSEWHERE, 0)
    return counts


def zero_lookup_counters(image, capabilities, resolver: str) -> None:
    """Forget everything counted so far, so each half is measured from nothing."""
    in_the_resolvers_namespace(image, capabilities, resolver, f"iptables -Z {LOOKUP_COUNTERS}")


def without_the_keys_that_resolve_a_name_here(config: str) -> tuple[str, int]:
    """The product's config with every ``domainStrategy`` removed, and how many there were.

    The mutation the negative half is built on, and the key is chosen because it is the one
    that does nothing visible. ``sendThrough`` still binds, the ``dns`` object is still in
    the file naming the node record's own resolver, the routing rule still sends the
    resolver's queries through the hop — and with this key gone nothing ever consults any
    of it: the name is handed to the HOST's resolver and the address that comes back is
    dialled through the hop exactly as before. Everything a person could look at still says
    the lookup goes through the hop.

    IT IS BOTH COPIES OF THAT KEY SINCE M23'S TENTH ROUND, and the change is a measurement
    rather than a tidy-up. The outbound's ``settings.domainStrategy`` used to be the only
    thing that made this file's own resolver be asked. That round added
    ``routing.domainStrategy`` — so that a refusal written about ADDRESSES is not walked
    past by a NAME — and it resolves through the same ``dns`` object one step earlier.
    Measured against the pinned Xray: with only the outbound's key removed the node
    record's resolver is STILL asked, by routing, and this fixture's counters could no
    longer tell the leaking config from the product's. Removing both restores the
    comparison the scenario was written to make, and the removal is still invisible from
    every seat but the resolver's.

    The count comes back so the caller can refuse to believe a mutation that mutated
    nothing. A template change that renamed or moved these keys would otherwise leave the
    negative half passing about a config identical to the positive one.
    """
    document = json.loads(config)
    removed = 0
    for outbound in document.get("outbounds", []):
        if "domainStrategy" in outbound.get("settings", {}):
            del outbound["settings"]["domainStrategy"]
            removed += 1
    if "domainStrategy" in document.get("routing", {}):
        del document["routing"]["domainStrategy"]
        removed += 1
    return json.dumps(document, indent=2), removed


def ask_for_the_name(device: str) -> str:
    """One request from the friend's seat, for a NAME rather than for an address.

    The distinction is the entire scenario. The friend's client is given a name and no
    way to resolve it — it forwards the name itself — so the proxy on the entry is the
    first thing in the chain that has to turn it into an address, which is the moment
    M16 is about.

    Returns the body the destination answered with, which is the address IT saw, or an
    empty string when nothing came back.
    """
    for _ in range(FRIEND_ATTEMPTS):
        request = run(
            [
                "docker", "exec", device, "sh", "-c",
                "printf 'GET / HTTP/1.0\\r\\n\\r\\n' | "
                f"nc -w {REQUEST_SECONDS} 127.0.0.1 {FRIEND_PORT}",
            ],
            timeout=REQUEST_SECONDS + 30,
        )
        _, _, body = request.stdout.replace("\r\n", "\n").partition("\n\n")
        if body.strip():
            return body.strip()
    return ""


@pytest.fixture(scope="module")
def vless_ws_tls_proxy_params() -> dict[str, object]:
    """What one friend-facing VLESS-over-WebSocket proxy runs with, other than its keys.

    Named after the transport, by the same convention ``amneziawg_hop_params`` above and
    ``tests/edge/conftest.py`` use: a proxy transport that arrives later brings its own
    fixture of this name and its own ``<name>_client_config``, and nothing else.

    ``front.example.com`` is the common name ``throwaway_certificate`` issues for, and a
    reserved example domain like every other name in this zone's fixtures. The two
    certificate paths are the same file deliberately — see ``files_the_config_names``.
    """
    return {
        "port": PROXY_PORT,
        "server_name": "front.example.com",
        "certificate_path": "/etc/hashi/tls/front.pem",
        "certificate_key_path": "/etc/hashi/tls/front.pem",
        "ws_path_secret": "m16lookupfixture01",
    }


@pytest.fixture(scope="module")
def vless_ws_tls_client_config():
    """Build a friend's client out of the product's OWN client entry, and nothing else.

    A real friend is handed a URI by the subscription and pastes it into a client; what
    this builds is that client, from that URI, parsed the way one would. Deriving it from
    ``serialise`` rather than from the parameters beside it is what makes the measurement
    a statement about the product: if the entry a friend is given did not actually dial
    the config a node is given, every assertion below would fail rather than silently
    measure a connection this test had arranged by hand.

    ``allowInsecure`` is the one thing a real client would not carry, and it is here
    because the certificate is a throwaway self-signed one minted for this run. Nothing
    about TLS trust is being measured; the name being looked up is.
    """

    def build(entry: str) -> str:
        uri = urllib.parse.urlsplit(entry)
        query = dict(urllib.parse.parse_qsl(uri.query))
        return json.dumps(
            {
                "log": {"loglevel": "warning", "access": "none", "dnsLog": False},
                # A NAME, not an address, and no way to resolve it: this inbound forwards
                # whatever it is given, so the name travels to the proxy untouched.
                "inbounds": [
                    {
                        "tag": "device",
                        "listen": "0.0.0.0",
                        "port": FRIEND_PORT,
                        "protocol": "dokodemo-door",
                        "settings": {"address": LOOKUP_NAME, "port": 80, "network": "tcp"},
                    }
                ],
                "outbounds": [
                    {
                        "tag": "entry",
                        "protocol": uri.scheme,
                        "settings": {
                            "vnext": [
                                {
                                    "address": uri.hostname,
                                    "port": uri.port,
                                    "users": [
                                        {
                                            "id": uri.username,
                                            "encryption": query["encryption"],
                                        }
                                    ],
                                }
                            ]
                        },
                        "streamSettings": {
                            "network": query["type"],
                            "security": query["security"],
                            "wsSettings": {
                                "path": query["path"],
                                "headers": {"Host": query["host"]},
                            },
                            "tlsSettings": {
                                "serverName": query["sni"],
                                "alpn": ["http/1.1"],
                                "allowInsecure": True,
                            },
                        },
                    }
                ],
            },
            indent=2,
        )

    return build


@pytest.fixture(scope="module", params=FRIEND_TRANSPORTS)
def looked_up(request, measured, material_a_config_names) -> dict:
    """A friend on the hop ``measured`` already built, asking for a name — twice.

    Added to THAT fleet rather than to one of its own: the question M16 asks is about
    this hop, and a second one would cost two more images, two more keypairs and another
    handshake to be a slightly different hop. It depends on ``measured`` and nothing
    depends on it, so a failure in any of the machinery below leaves the exit half —
    M3's proof, which was green before this milestone — reporting for itself.

    Twice, because one measurement proves nothing. The first run is the product's own
    rendered config. The second is that config with ``domainStrategy`` removed from its
    outbound and NOTHING else changed, which is the shape M16 found in the field. The
    two runs are the same friend, the same name, the same hop and the same resolver.
    """
    transport_name = request.param
    key = transport_name.replace("-", "_")
    transport = profile(transport_name)
    params = transport.validate(request.getfixturevalue(f"{key}_proxy_params"))
    build_client = request.getfixturevalue(f"{key}_client_config")

    fleet = measured["fleet"]
    addresses = measured["addresses"]
    internet = measured["networks"]["internet"]
    directory = measured["directory"] / f"lookup-{key}"
    directory.mkdir()

    # The node's record, as the control plane would hold it for an entry that dials a
    # hop: its friend-facing address, and a resolver. The resolver is REQUIRED here and
    # is never defaulted — a hop-dialling node without one does not render at all (M16.1,
    # ``EgressNotRenderable(NO_RESOLVER)``), which is asserted in ``tests/edge/``.
    node = dataclasses.replace(
        measured["ends"]["entry"].node,
        address=addresses["entry_internet"],
        resolver=addresses["resolver"],
    )
    credential = Credential(subject=str(uuid.uuid4()))

    # The product's own two outputs, from one node record and one credential: what the
    # node is given, and what the friend is given.
    proxy_config = transport.profile.render_server(
        node, params, [credential], egress=Egress.HOP, exit_via=measured["exit_via"]
    )
    client_entry = transport.serialise(
        SubscriptionFormat.V1_URI_LIST, node, params, credential
    )

    service = node_stack.services_for({transport_name: proxy_config})[0]
    config_name = pathlib.PurePosixPath(service["config_path"]).name
    hop_plane = node_stack.DATA_PLANES[profile(measured["transport"]).meta.config_format]
    counting = (hop_plane.image, list(hop_plane.capabilities))

    def daemon(purpose: str, config: str, placement: list[str]) -> str:
        """One Xray, with one config, wherever it is told to run."""
        own = directory / purpose
        own.mkdir()
        (own / config_name).write_text(config)
        mounts = [f"{own}:{node_stack.CONFIG_DIR}:ro", *material_a_config_names(config, own)]
        return fleet.start(
            purpose,
            [
                *placement,
                *[argument for mount in mounts for argument in ("-v", mount)],
                service["image"],
                *service["command"],
            ],
        )

    resolver = daemon(
        "resolver",
        resolver_config(addresses["destination"]),
        ["--network", internet, "--ip", addresses["resolver"]],
    )
    # The friend's device holds the namespace; its client runs inside it. The same shape
    # a node has — a container with the tools and a container with the daemon — and the
    # only way to make a request from the friend's seat, because the client's own image
    # ships no shell.
    device = fleet.start(
        "device",
        [
            "--network", internet,
            "--ip", addresses["friend"],
            "--entrypoint", "sh",
            DEVICE_IMAGE, "-c", "tail -f /dev/null",
        ],
    )
    client = daemon(
        "client", build_client(client_entry.entry), ["--network", f"container:{device}"]
    )
    # The three that stand for the length of both measurements, tracked so they can be
    # taken down again at the end. Read the teardown's comment before simplifying it.
    borrowed = [resolver, device, client]

    sources = {"leaf": addresses["leaf_internet"], "entry": addresses["entry_internet"]}
    time.sleep(PROXY_SECONDS)
    install_lookup_counters(*counting, resolver, sources)

    mutated_config, mutations = without_the_keys_that_resolve_a_name_here(proxy_config)
    runs = {}
    for half, config in (("product", proxy_config), ("mutated", mutated_config)):
        # In the ENTRY's own network namespace, which is where a node's proxy runs: under
        # ``network_mode: host`` it shares the namespace the hop's interface lives in, and
        # that is the only reason ``sendThrough`` can name that interface's address.
        proxy = daemon(half, config, ["--network", f"container:{measured['nodes']['entry']}"])
        time.sleep(PROXY_SECONDS)
        running = run(["docker", "inspect", "-f", "{{.State.Running}}", proxy])
        assert running.stdout.strip() == "true", (
            f"the {half} proxy is not running, so no lookup can be measured:\n"
            f"{fleet.logs(proxy)[-2000:]}"
        )
        zero_lookup_counters(*counting, resolver)
        runs[half] = {
            "seen_by_the_destination": ask_for_the_name(device),
            "lookups": lookups_by_source(*counting, resolver, sources),
        }
        # Removed rather than stopped, and before the next one starts: both halves bind
        # the same port in the same namespace, and a proxy left behind would serve the
        # half that was meant to replace it.
        run(["docker", "rm", "-f", proxy], timeout=120)

    yield {
        "transport": transport_name,
        "addresses": addresses,
        "mutations": mutations,
        "config": proxy_config,
        **runs,
    }

    # Given back, because this fixture BORROWS the single ``Fleet`` that ``measured``
    # built rather than owning one. It is parametrised over ``FRIEND_TRANSPORTS``, and
    # every instantiation shares that one fleet's tag, its container names and its
    # addresses — so three containers left standing are three collisions for the next
    # friend-facing transport to be added, which is exactly the day
    # ``test_every_proxy_transport_is_measured_or_excused`` exists to bring about.
    #
    # Removing them is the fix rather than giving each a per-transport NAME, and the
    # difference matters: ``Fleet.start`` composes a name with nothing per-transport in
    # it, but the resolver and the device also hold a FIXED ``--ip`` from the internet
    # subnet, which a unique name does not free. The two proxies above are removed one
    # step sooner for the same kind of reason — both halves bind one port in one
    # namespace. ``Fleet.down()`` is the backstop if this is never reached.
    for container in borrowed:
        run(["docker", "rm", "-f", container], timeout=120)


def test_the_lookup_leaves_by_the_leaf_and_not_by_the_entry(looked_up) -> None:
    """M16, as one address: the resolver saw the far end of the hop.

    The question M3's proof never asked. The entry can reach this resolver by its own
    route — the next test proves it — so a proxy that resolved at home would be seen
    doing it, from its own address, rather than seen failing.
    """
    addresses = looked_up["addresses"]
    lookups = looked_up["product"]["lookups"]

    assert lookups["leaf"] > 0, (
        "the resolver on this node's record was never asked anything from the far end of "
        f"the hop. It saw {lookups['entry']} lookup(s) from the entry's own address "
        f"({addresses['entry_internet']}) and {lookups[ELSEWHERE]} from elsewhere — a "
        "friend's destination names being resolved on the near side of the hop is M16 "
        "exactly, and it is invisible from every screen this product has"
    )
    assert lookups["entry"] == 0, (
        f"{lookups['entry']} lookup(s) reached the resolver from the entry's own address "
        f"({addresses['entry_internet']}) rather than through the hop. Some of a friend's "
        "names are being resolved from the network the hop exists to leave"
    )


def test_the_friend_still_reaches_the_name_they_asked_for(looked_up) -> None:
    """The control for the test above, and the reason the measurement is not vacuous.

    A lookup that left by the leaf and then resolved to nothing would satisfy the
    counters and serve the friend a blank page. This asserts the whole chain instead: the
    name was resolved, the connection was opened through the hop, and the address the
    destination saw is the leaf's — which is M3's claim, now made about a request that
    began as a NAME rather than as an address.
    """
    addresses = looked_up["addresses"]
    seen = looked_up["product"]["seen_by_the_destination"]

    assert seen == addresses["leaf_internet"], (
        f"a friend asking for {LOOKUP_NAME!r} was answered by {seen!r}. It should have "
        f"been the leaf's address ({addresses['leaf_internet']}); the entry's own is "
        f"{addresses['entry_internet']}, and an empty answer means the name never "
        "resolved at all"
    )


def test_the_entry_could_have_resolved_it_at_home_and_did_not(looked_up) -> None:
    """The mutation, and the only half of this file that can fail for the right reason.

    ``domainStrategy`` is taken out of the outbound and nothing else is touched. That one
    key is the whole of M16: with it gone the proxy never consults the ``dns`` object,
    hands the name to its host's resolver — here docker's, which knows this name — and
    dials the address that comes back through the hop exactly as before.

    So this asserts what the product's own screens would show: the friend's page still
    loads, from the leaf's address, and the resolver the node's record names was not
    asked anything at all. Everything green, and the list of names gone home.
    """
    addresses = looked_up["addresses"]
    mutated = looked_up["mutated"]

    assert mutated["seen_by_the_destination"] == addresses["leaf_internet"], (
        "the mutated config did not keep working, so this test is no longer the "
        "comparison it claims to be: the point is that removing the lookup wiring is "
        f"INVISIBLE to a friend. It answered {mutated['seen_by_the_destination']!r}"
    )
    assert sum(mutated["lookups"].values()) == 0, (
        "with the outbound's domainStrategy removed, the resolver on the node's record "
        f"was still asked something: {mutated['lookups']}. Either the mutation is not the "
        "key that decides where a lookup goes, or something other than the proxy is "
        "talking to it, and the positive half above is measuring the wrong thing"
    )


def test_the_mutation_actually_removed_something(looked_up) -> None:
    """Without this, a template change turns the negative half green by doing nothing.

    ``domainStrategy`` renamed, moved into another object or dropped from the template
    would leave ``without_the_keys_that_resolve_a_name_here`` returning the config
    unchanged — and a "mutated" run identical to the product one would then pass the test
    above only when the product itself had already broken.

    TWO and not one since M23's tenth round: the rendered config now says where a name is
    resolved in two places, and a mutation that found only one of them leaves the other
    still sending the query to the node record's resolver — which is measured, and is
    exactly the state in which the counters below stop discriminating.
    """
    assert looked_up["mutations"] > 1, (
        "the negative half did not remove BOTH places this config says how a name is "
        f"resolved (it found {looked_up['mutations']}), so it did not test the mutation "
        "it claims to. Find where the outbound and the routing section now say it:\n"
        f"{looked_up['config']}"
    )


def test_no_lookup_arrived_from_anywhere_this_scenario_did_not_expect(looked_up) -> None:
    """The measurement is about two addresses, so a third one invalidates it.

    Nothing else in this fleet is configured to ask this resolver anything. A count here
    means something is — the friend's own client, the destination, a stray container —
    and the two counts above are then not the two facts they are read as.
    """
    for half in ("product", "mutated"):
        strays = looked_up[half]["lookups"][ELSEWHERE]
        assert strays == 0, (
            f"in the {half} half, {strays} lookup(s) reached the resolver from neither "
            "node. This scenario's two counts are not the whole of what arrived, so "
            "neither says what it claims"
        )


def test_every_proxy_transport_is_measured_or_excused() -> None:
    """A proxy transport added later must not be silently unmeasured — which is M16.

    The milestone exists because a question was never asked, not because an answer was
    wrong. A new transport that terminates a friend's connection has the same question to
    answer, and the way this file could stop asking it is by quietly parametrising over a
    list the transport is not in.
    """
    assert PROXY_TRANSPORTS, (
        "no installed transport has a proxy data plane, so nothing above ran and this "
        "file is green about a lookup it never made"
    )
    unaccounted = set(PROXY_TRANSPORTS) - set(FRIEND_TRANSPORTS) - set(NO_FRIEND_HERE)
    assert not unaccounted, (
        f"{sorted(unaccounted)} terminate a friend's connection and so must resolve a "
        "name before dialling, but no friend is dialled into them here and no reason is "
        "written down. Give each a `<name>_proxy_params` and a `<name>_client_config` "
        "fixture, or add it to NO_FRIEND_HERE saying what a lab cannot build for it"
    )
