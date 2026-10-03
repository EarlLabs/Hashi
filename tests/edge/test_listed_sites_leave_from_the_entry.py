"""Listed destinations leave an entry by its own route; everything else through the hop — M34.

WHAT: what a splitting transport renders when it is handed an ``edge.direct.DirectRoutes``
      on an entry node, what it renders when it is not (byte for byte the file it rendered
      before M34), the refusals, the canonical form of a list, and — when the pinned Xray
      is present — the rendered file run as a live proxy on loopback, with every way out
      and every resolver watched.
WHY:  the owner's three hard lines for this feature are each a property of one file, and
      each is invisible on a screen: "off" must be off (a single byte of drift is a
      restart of every entry for nothing, and a rule that leaks is worse); *never direct*
      must beat every source; and an unlisted destination must keep exactly one way out,
      the hop, so that a hop that is down still means nothing leaves from Russia.
HOW:  parsed JSON for the structure, golden files written by the code BEFORE M34 for the
      "off" claim (``golden/*-server-hop.json``, rendered at ``ecd15c5`` and copied in
      unchanged), and the measurement harness at the bottom for the claims a structure
      cannot prove — which resolver a name is asked at, and which address a connection
      leaves from. Every address in a render is a documentation range; the harness swaps
      them for loopback ones and changes nothing else that decides a route.
"""

import ast
import json
import pathlib
import socket
import socketserver
import struct
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler

import pytest

from edge import direct as direct_module
from edge.checker import validate, xray_binary
from edge.direct import (
    Destinations,
    DirectRoutes,
    NotADestination,
    direct_resolver_problem,
    match,
    normalise_name,
    normalise_network,
)
from edge.egress import Egress, EgressNotRenderable
from edge.registry import ContractViolation, Datapath, discover, profile

GOLDEN = pathlib.Path(__file__).parent / "golden"

# The transports that declare they can split. Derived, so a transport that starts
# declaring it later is held to every assertion here by arriving.
SPLITTING = sorted(name for name, meta in discover().items() if meta.splits_by_destination)

HOP_ADDRESS = "10.44.0.1"

# The entry-side resolver. A documentation address (RFC 5737), never a real one.
DIRECT_RESOLVER = "198.51.100.53"

ROUTES = DirectRoutes(
    resolver=DIRECT_RESOLVER,
    direct=Destinations.of(
        suffixes=["direct.example", "госуслуги.example"],
        names=["exact.example"],
        networks=["203.0.113.0/25"],
    ),
    never=Destinations.of(
        suffixes=["never.direct.example"],
        networks=["203.0.113.7/32"],
    ),
)


def render(name: str, node, request, **extra) -> str:
    transport = profile(name)
    fixture = request.getfixturevalue("transport_fixture")
    validated = transport.validate(fixture(name, "params"))
    return transport.profile.render_server(
        node, validated, fixture(name, "credentials"), **extra
    )


def hop(name, node, request, **extra) -> str:
    return render(name, node, request, egress=Egress.HOP, exit_via=HOP_ADDRESS, **extra)


def test_both_proxies_split() -> None:
    """The two Xray transports declare it, and nothing else does."""
    assert SPLITTING == ["vless-reality", "vless-ws-tls"]


# --- off is off --------------------------------------------------------------------


@pytest.mark.parametrize("name", SPLITTING)
def test_off_renders_the_file_the_entry_had_before_m34(name, node, request) -> None:
    """The golden file was rendered by the code at ecd15c5, before this feature existed."""
    golden = (GOLDEN / f"{name}-server-hop.json").read_text()
    assert hop(name, node, request) == golden
    assert hop(name, node, request, direct=None) == golden


@pytest.mark.parametrize("name", SPLITTING)
def test_an_empty_direct_list_is_off_too(name, node, request) -> None:
    """Nothing listed renders no rule at all — never a rule with an empty condition."""
    golden = (GOLDEN / f"{name}-server-hop.json").read_text()
    nothing = DirectRoutes(
        resolver=DIRECT_RESOLVER,
        direct=Destinations(),
        never=Destinations.of(suffixes=["never.example"]),
    )
    assert hop(name, node, request, direct=nothing) == golden


@pytest.mark.parametrize("name", SPLITTING)
def test_a_node_without_a_hop_is_unchanged_when_nothing_is_passed(
    name, node, request
) -> None:
    golden = (GOLDEN / f"{name}-server.json").read_text()
    assert render(name, node, request) == golden


@pytest.mark.parametrize("name", SPLITTING)
def test_a_list_without_a_hop_is_refused(name, node, request) -> None:
    with pytest.raises(EgressNotRenderable, match="no hop"):
        render(name, node, request, direct=ROUTES)


# --- the shape when on --------------------------------------------------------------


def on(name, node, request) -> dict:
    return json.loads(hop(name, node, request, direct=ROUTES))


@pytest.mark.parametrize("name", SPLITTING)
def test_the_rules_are_in_the_order_that_lets_never_win(name, node, request) -> None:
    rules = on(name, node, request)["routing"]["rules"]
    users = [rule for rule in rules if rule.get("inboundTag") == ["in"]]
    shape = [
        (
            rule["outboundTag"],
            "domain" if "domain" in rule else "ip" if "ip" in rule else "everything",
        )
        for rule in users
    ]
    assert shape == [
        ("refused", "ip"),
        ("hop", "domain"),
        ("hop", "ip"),
        ("direct", "domain"),
        ("direct", "ip"),
        ("hop", "everything"),
    ]
    assert users[1]["domain"] == ["domain:never.direct.example"]
    assert users[2]["ip"] == ["203.0.113.7/32"]
    assert users[3]["domain"] == [
        "domain:direct.example",
        "domain:xn--c1aapkosapc.example",
        "full:exact.example",
    ]
    assert users[4]["ip"] == ["203.0.113.0/25"]


@pytest.mark.parametrize("name", SPLITTING)
def test_no_rule_but_the_last_matches_everything(name, node, request) -> None:
    """A rule whose only condition is its inbound takes every connection after it."""
    rules = on(name, node, request)["routing"]["rules"]
    for tag in ("in", "lookup"):
        mine = [rule for rule in rules if rule["inboundTag"] == [tag]]
        for rule in mine[:-1]:
            condition = rule.get("domain") or rule.get("ip")
            assert condition, f"an unconditional rule before the last: {rule}"
        assert set(mine[-1]) == {"type", "inboundTag", "outboundTag"}
        assert mine[-1]["outboundTag"] == "hop"


@pytest.mark.parametrize("name", SPLITTING)
def test_the_one_unbound_outbound_is_direct_and_the_hop_stays_the_default(
    name, node, request
) -> None:
    outbounds = on(name, node, request)["outbounds"]
    assert outbounds[0]["tag"] == "hop"
    unbound = [o["tag"] for o in outbounds if "sendThrough" not in o]
    assert unbound == ["direct"]
    direct = next(o for o in outbounds if o["tag"] == "direct")
    # Resolved through the config's own dns object, never the host's resolver.
    assert direct["settings"]["domainStrategy"] == "UseIPv4"


@pytest.mark.parametrize("name", SPLITTING)
def test_direct_names_are_looked_up_at_the_entry_side_resolver_and_only_they_are(
    name, node, request
) -> None:
    config = on(name, node, request)
    servers = config["dns"]["servers"]
    # The hop's resolver comes first, so it answers every name no list claims.
    assert servers[0]["address"] == node.resolver
    assert servers[0]["domains"] == ["domain:never.direct.example"]
    assert servers[1] == {
        "address": DIRECT_RESOLVER,
        "domains": [
            "domain:direct.example",
            "domain:xn--c1aapkosapc.example",
            "full:exact.example",
        ],
        "skipFallback": True,
    }
    assert len(servers) == 2
    lookups = [r for r in config["routing"]["rules"] if r["inboundTag"] == ["lookup"]]
    assert lookups == [
        {"type": "field", "inboundTag": ["lookup"], "ip": [DIRECT_RESOLVER],
         "outboundTag": "direct"},
        {"type": "field", "inboundTag": ["lookup"], "outboundTag": "hop"},
    ]


@pytest.mark.parametrize("name", SPLITTING)
def test_nothing_about_use_is_switched_on(name, node, request) -> None:
    """No access log, no DNS log, no sniffing, no statistics, no policy counters."""
    config = on(name, node, request)
    assert config["log"] == {"loglevel": "warning", "dnsLog": False, "access": "none"}
    assert config["inbounds"][0]["sniffing"] == {"enabled": False}
    for key in ("stats", "api", "policy", "observatory", "metrics"):
        assert key not in config


@pytest.mark.parametrize("name", SPLITTING)
def test_the_same_lists_in_another_order_render_the_same_bytes(
    name, node, request
) -> None:
    shuffled = DirectRoutes(
        resolver=DIRECT_RESOLVER,
        direct=Destinations.of(
            suffixes=["XN--C1AAPKOSAPC.example.", "*.direct.example", "direct.example"],
            names=["exact.example"],
            networks=["203.0.113.5/25"],
        ),
        never=Destinations.of(
            suffixes=["never.direct.example"], networks=["203.0.113.7"]
        ),
    )
    assert hop(name, node, request, direct=shuffled) == hop(
        name, node, request, direct=ROUTES
    )


@pytest.mark.parametrize("name", SPLITTING)
@pytest.mark.parametrize(
    ("resolver", "why"),
    [
        ("192.0.2.53", "also this node's resolver"),
        ("127.0.0.53", "inside the data plane"),
        ("resolver.example", "not an IPv4 address"),
        ("2001:db8::53", "IPv6"),
    ],
)
def test_a_direct_resolver_that_cannot_be_told_apart_is_refused(
    name, resolver, why, node, request
) -> None:
    routes = DirectRoutes(resolver=resolver, direct=ROUTES.direct)
    with pytest.raises(EgressNotRenderable, match=why):
        hop(name, node, request, direct=routes)


# --- the canonical form and the one meaning of "on the list" ------------------------


def test_names_are_held_in_one_form() -> None:
    assert normalise_name(" *.GosUslugi.RU. ") == "gosuslugi.ru"
    assert normalise_name("госуслуги.рф") == "xn--c1aapkosapc.xn--p1ai"
    for bad in ("", "a..b", "-a.example", "a b.example", "198.51.100.1", "x" * 64 + ".ru"):
        with pytest.raises(NotADestination):
            normalise_name(bad)


def test_networks_are_held_in_one_form() -> None:
    assert normalise_network("5.8.43.1/24") == "5.8.43.0/24"
    assert normalise_network("198.51.100.7") == "198.51.100.7/32"
    for bad in ("0.0.0.0/0", "::/0", "300.1.1.1", "example.ru"):
        with pytest.raises(NotADestination):
            normalise_network(bad)


def test_destinations_refuse_anything_but_the_canonical_form() -> None:
    with pytest.raises(NotADestination):
        Destinations(suffixes=("b.example", "a.example"))
    with pytest.raises(NotADestination):
        Destinations(suffixes=("A.example",))


def test_match_is_xrays_meaning_of_the_two_name_rules() -> None:
    lists = ROUTES.direct
    assert match("direct.example", lists) == "direct.example"
    assert match("www.direct.example", lists) == "direct.example"
    assert match("notdirect.example", lists) is None
    assert match("exact.example", lists) == "exact.example"
    assert match("www.exact.example", lists) is None
    assert match("203.0.113.100", lists) == "203.0.113.0/25"
    assert match("203.0.113.200", lists) is None
    assert match("ГОСУСЛУГИ.example", lists) == "xn--c1aapkosapc.example"


def test_direct_resolver_problem_is_none_for_a_usable_one() -> None:
    assert direct_resolver_problem(DIRECT_RESOLVER, "192.0.2.53") is None


# --- purity and the contract --------------------------------------------------------


def test_the_list_module_imports_nothing_that_does_io() -> None:
    tree = ast.parse(pathlib.Path(direct_module.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"ipaddress", "collections", "dataclasses"}


@pytest.mark.parametrize("name", SPLITTING)
def test_rendering_with_lists_touches_no_network_clock_or_randomness(
    name, node, request, monkeypatch
) -> None:
    first = hop(name, node, request, direct=ROUTES)

    def forbidden(*args, **kwargs):
        raise AssertionError("rendering did I/O")

    import random
    import time as time_module

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(time_module, "time", forbidden)
    monkeypatch.setattr(random, "random", forbidden)
    assert hop(name, node, request, direct=ROUTES) == first


def test_a_kernel_routed_transport_cannot_declare_it() -> None:
    import dataclasses

    from edge.registry import _check_declaration

    meta = dataclasses.replace(
        profile("vless-reality").meta,
        splits_by_destination=True,
        datapath=Datapath.KERNEL_ROUTED,
    )
    with pytest.raises(ContractViolation, match="kernel"):
        _check_declaration("vless_reality", meta)


def test_a_renderer_that_cannot_receive_the_list_cannot_declare_it() -> None:
    from types import SimpleNamespace

    from edge.registry import _check_contract

    transport = profile("vless-reality")
    render_module = SimpleNamespace(
        render_server=lambda node, params, clients=(), *, egress=None, exit_via=None: "",
        render_client=lambda *a: None,
    )
    with pytest.raises(ContractViolation, match="direct"):
        _check_contract(transport.meta, render_module, transport.params_model)


@pytest.mark.parametrize("name", SPLITTING)
def test_the_pinned_xray_accepts_a_config_with_lists(
    name, node, request, tmp_path
) -> None:
    if xray_binary() is None:
        pytest.skip(
            "xray not present — that the daemon accepts a config with direct lists is NOT "
            "proven by this run. Install it: scripts/fetch-upstream-checkers.sh"
        )
    transport = profile(name)
    fixture = request.getfixturevalue("transport_fixture")
    materialise = request.getfixturevalue("checkable_params_for")
    validated = transport.validate(materialise(fixture(name, "params"), tmp_path))
    config = transport.profile.render_server(
        node,
        validated,
        fixture(name, "credentials"),
        egress=Egress.HOP,
        exit_via=HOP_ADDRESS,
        direct=ROUTES,
    )
    result = validate(config, config_format=transport.meta.config_format)
    assert result.ok, result.output


# --- measured: the rendered file run as a live proxy ---------------------------------
#
# The rendered config with four substitutions, each of which changes WHERE something is
# and nothing about how a route is chosen: the user-facing inbound becomes a SOCKS one on
# loopback (same tag), the two resolvers become loopback servers that record what they
# are asked, the hop's address becomes a second loopback address so a connection that
# took the hop is visible by its source, and the refusal's list — asserted on its own
# elsewhere — is narrowed so it does not refuse loopback, which is all this harness has.

HOP_RESOLVER_HERE = "127.0.0.4"
DIRECT_RESOLVER_HERE = "127.0.0.3"
HOP_SOURCE_HERE = "127.0.0.2"
DIRECT_SOURCE_HERE = "127.0.0.1"

# What the loopback resolvers answer. A listed name whose ADDRESS is on never-direct
# is the case that proves never beats a listing across the two kinds of rule.
ANSWERS = {
    "www.direct.example": "127.0.0.9",
    "exact.example": "127.0.0.9",
    "x.never.direct.example": "127.0.0.9",
    "elsewhere.example": "127.0.0.9",
    "pinned.direct.example": "127.0.0.11",
}

MEASURED_ROUTES = DirectRoutes(
    resolver=DIRECT_RESOLVER,
    direct=Destinations.of(
        suffixes=["direct.example"], names=["exact.example"], networks=["127.0.0.10/32"]
    ),
    never=Destinations.of(suffixes=["never.direct.example"], networks=["127.0.0.11/32"]),
)


def _free_port(kind=socket.SOCK_STREAM) -> int:
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Resolver:
    def __init__(self, address: str, port: int, seen: list) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((address, port))
        self.sock.settimeout(0.2)
        self.address, self.seen, self.running = address, seen, True
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while self.running:
            try:
                data, peer = self.sock.recvfrom(2048)
            except OSError:
                continue
            i, labels = 12, []
            while data[i]:
                labels.append(data[i + 1 : i + 1 + data[i]].decode())
                i += 1 + data[i]
            qtype = struct.unpack(">H", data[i + 1 : i + 3])[0]
            name = ".".join(labels)
            self.seen.append((self.address, name, peer[0]))
            answer = ANSWERS.get(name) if qtype == 1 else None
            header = data[:2] + b"\x81\x80" + struct.pack(">HHHH", 1, int(bool(answer)), 0, 0)
            body = data[12 : i + 5]
            if answer:
                body += b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, 60, 4)
                body += socket.inet_aton(answer)
            self.sock.sendto(header + body, peer)

    def close(self) -> None:
        self.running = False
        self.sock.close()


class _Web(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _web(address: str, port: int, seen: list) -> _Web:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — the stdlib's name
            seen.append((address, self.client_address[0]))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = _Web((address, port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _for_loopback(config: dict, *, socks: int, dns: int, hop_source: str) -> dict:
    config["inbounds"] = [
        {
            "tag": "in",
            "listen": "127.0.0.1",
            "port": socks,
            "protocol": "socks",
            "settings": {"auth": "noauth", "udp": False},
        }
    ]
    swap = {"192.0.2.53": HOP_RESOLVER_HERE, DIRECT_RESOLVER: DIRECT_RESOLVER_HERE}
    servers = []
    for server in config["dns"]["servers"]:
        server = {"address": server} if isinstance(server, str) else dict(server)
        server["address"] = swap[server["address"]]
        server["port"] = dns
        servers.append(server)
    config["dns"]["servers"] = servers
    for rule in config["routing"]["rules"]:
        if rule["outboundTag"] == "refused":
            rule["ip"] = ["198.18.0.0/15"]
        if rule["inboundTag"] == ["lookup"] and "ip" in rule:
            rule["ip"] = [swap[address] for address in rule["ip"]]
    for outbound in config["outbounds"]:
        if "sendThrough" in outbound:
            outbound["sendThrough"] = hop_source
    return config


def _ask(socks: int, host: str, port: int) -> bool:
    """Open ``host:port`` through the proxy and GET /; whether it answered."""
    try:
        with socket.create_connection(("127.0.0.1", socks), timeout=5) as s:
            s.sendall(b"\x05\x01\x00")
            s.recv(2)
            try:
                packed = b"\x01" + socket.inet_aton(host)
            except OSError:
                packed = b"\x03" + bytes([len(host)]) + host.encode()
            s.sendall(b"\x05\x01\x00" + packed + struct.pack(">H", port))
            if s.recv(10)[1:2] != b"\x00":
                return False
            s.sendall(f"GET / HTTP/1.0\r\nHost: {host}\r\n\r\n".encode())
            return s.recv(64).startswith(b"HTTP/1.0 200")
    except OSError:
        return False


@pytest.fixture
def live_proxy(node, request, tmp_path):
    """Start the rendered config in the pinned Xray; yield (ask, lookups, arrivals)."""
    binary = xray_binary()
    if binary is None:
        pytest.skip(
            "xray not present — WHERE a listed name is looked up and which address its "
            "connection leaves from are NOT measured by this run. Install it: "
            "scripts/fetch-upstream-checkers.sh"
        )
    lookups, arrivals = [], []
    dns, web_port, socks = _free_port(socket.SOCK_DGRAM), _free_port(), _free_port()
    resolvers = [
        _Resolver(address, dns, lookups) for address in (HOP_RESOLVER_HERE, DIRECT_RESOLVER_HERE)
    ]
    webs = [_web(a, web_port, arrivals) for a in ("127.0.0.9", "127.0.0.10", "127.0.0.11")]
    processes = []

    def start(hop_source: str):
        rendered = json.loads(
            hop("vless-reality", node, request, direct=MEASURED_ROUTES)
        )
        path = tmp_path / f"live-{len(processes)}.json"
        path.write_text(
            json.dumps(_for_loopback(rendered, socks=socks, dns=dns, hop_source=hop_source))
        )
        process = subprocess.Popen(
            [binary, "run", "-c", str(path)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        processes.append(process)
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", socks), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)

        def ask(host: str) -> bool:
            lookups.clear()
            arrivals.clear()
            ok = _ask(socks, host, web_port)
            time.sleep(0.2)
            return ok

        return ask, process

    yield start, lookups, arrivals
    for process in processes:
        process.terminate()
        process.wait(timeout=5)
    for resolver in resolvers:
        resolver.close()
    for web in webs:
        web.shutdown()
        web.server_close()


def _stopped(process) -> str:
    process.terminate()
    return process.communicate(timeout=5)[0].decode()


def test_measured_a_listed_name_is_looked_up_and_opened_from_the_entry(live_proxy) -> None:
    start, lookups, arrivals = live_proxy
    ask, _ = start(HOP_SOURCE_HERE)
    assert ask("www.direct.example")
    assert lookups == [(DIRECT_RESOLVER_HERE, "www.direct.example", DIRECT_SOURCE_HERE)]
    assert arrivals == [("127.0.0.9", DIRECT_SOURCE_HERE)]
    assert ask("exact.example")
    assert arrivals == [("127.0.0.9", DIRECT_SOURCE_HERE)]


def test_measured_an_unlisted_name_still_goes_through_the_hop(live_proxy) -> None:
    start, lookups, arrivals = live_proxy
    ask, _ = start(HOP_SOURCE_HERE)
    assert ask("elsewhere.example")
    assert lookups == [(HOP_RESOLVER_HERE, "elsewhere.example", HOP_SOURCE_HERE)]
    assert arrivals == [("127.0.0.9", HOP_SOURCE_HERE)]


def test_measured_never_direct_beats_a_listing_by_name_and_by_address(live_proxy) -> None:
    start, lookups, arrivals = live_proxy
    ask, _ = start(HOP_SOURCE_HERE)
    # A never-direct name UNDER a listed suffix: looked up at the hop's resolver too.
    assert ask("x.never.direct.example")
    assert lookups == [(HOP_RESOLVER_HERE, "x.never.direct.example", HOP_SOURCE_HERE)]
    assert arrivals == [("127.0.0.9", HOP_SOURCE_HERE)]
    # A listed name whose address is on never-direct.
    assert ask("pinned.direct.example")
    assert arrivals == [("127.0.0.11", HOP_SOURCE_HERE)]


def test_measured_a_listed_network_is_opened_from_the_entry(live_proxy) -> None:
    start, _, arrivals = live_proxy
    ask, _ = start(HOP_SOURCE_HERE)
    assert ask("127.0.0.10")
    assert arrivals == [("127.0.0.10", DIRECT_SOURCE_HERE)]


def test_measured_hop_down_listed_still_open_and_nothing_else_falls_back(
    live_proxy,
) -> None:
    """The hop's address gone from the host is what a hop that is down looks like here."""
    start, _, arrivals = live_proxy
    ask, process = start("10.255.255.254")
    assert ask("www.direct.example")
    assert arrivals == [("127.0.0.9", DIRECT_SOURCE_HERE)]
    assert not ask("elsewhere.example")
    assert arrivals == []
    output = _stopped(process)
    # And the daemon wrote none of the destinations it was asked for.
    for name in ANSWERS:
        assert name not in output
