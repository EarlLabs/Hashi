"""The routing lists, from a published list to the config an entry would be pushed — M34.

WHAT: the control half of "sites that only open from Russia leave from the entry": reading
      a published list, the rules a new version is held by, approving and rejecting, the
      last good version surviving a failed fetch, the owner's two lists (never beats
      everything), each node's switch, what reaches the renderer, the nightly run, the
      Routing screen and its lookup — and that none of it writes down who reached what.
WHY:  ``edge`` proves a renderer handed lists obeys them. Every claim the owner can be
      hurt by is on THIS side: that "off" hands the renderer nothing (so the file is the
      one the entry already runs), that a suspicious list never reaches a node without
      the owner, that a list host going dark leaves the entry on yesterday's list, and
      that this feature does not become the first record of use.
HOW:  real Postgres, real rendering, the panel's own routes. Fetching is replaced at
      ``routing.fetch_text`` except in the tests about fetching itself, which run a real
      HTTPS server on loopback with a certificate made for the test.
"""

import asyncio
import datetime
import http.server
import json
import logging
import ssl
import threading

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from sqlalchemy import func, select, text

from control.app.errors import ConfigRefused, DomainError
from control.app.models import (
    AuditAction,
    AuditEntry,
    Base,
    NodeState,
    OwnerList,
    RoutingListVersion,
    RoutingSource,
    VersionStatus,
)
from control.app.services import apply, console, nodes, routing, routing_refresh
from control.app.settings import Settings

HOP_TRANSPORT = "amneziawg"
USER_TRANSPORT = "vless-reality"
RESOLVER = "192.0.2.53"
DIRECT_RESOLVER = "198.51.100.53"

# A list shaped like the narrow default (itdoginfo's Russia/outside-raw.lst): one name per
# line. Reserved names (RFC 2606), never a real site.
NARROW = "\n".join(f"site{n}.example" for n in range(40)) + "\n"


@pytest.fixture
def hop_params() -> dict[str, object]:
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


async def an_entry_with_a_hop(client, session, reality_params, hop_params) -> str:
    created = await client.post(
        "/api/nodes",
        json={"name": "entry-ru", "address": "192.0.2.20", "location_label": "Russia",
              "resolver": RESOLVER},
    )
    entry_id = created.json()["id"]
    enabled = await client.post(
        f"/api/nodes/{entry_id}/transports",
        json={"transport_name": USER_TRANSPORT, "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text
    await nodes.set_node_state(session, node_id=entry_id, state=NodeState.ACTIVE)
    leaf = await client.post(
        "/api/nodes",
        json={"name": "leaf-nl", "address": "192.0.2.10", "location_label": "Netherlands"},
    )
    established = await client.post(
        "/api/hops",
        json={
            "entry_node_id": entry_id,
            "leaf_node_id": leaf.json()["id"],
            "transport_name": HOP_TRANSPORT,
            "entry_params": {**hop_params, "tunnel_address": "10.44.0.1/24",
                             "peer_tunnel_address": "10.44.0.2/24"},
            "leaf_params": {**hop_params, "tunnel_address": "10.44.0.2/24",
                            "peer_tunnel_address": "10.44.0.1/24"},
        },
    )
    assert established.status_code == 201, established.text
    return entry_id


async def rendered(session, node_id: str) -> str:
    node = await nodes.get_node(session, node_id)
    session.expire(node)
    node = await nodes.get_node(session, node_id)
    return (await apply.render_for_node(session, node))[USER_TRANSPORT]


def serving(body: str):
    """Replace the network with ``body`` for every fetch."""

    def fetch(url, *, timeout, max_bytes):
        return body

    return fetch


async def a_source_in_force(session, settings, monkeypatch, body: str = NARROW, name="narrow"):
    source = await routing.add_source(
        session, name=name, url=f"https://lists.example/{name}.lst", enabled=True
    )
    monkeypatch.setattr(routing, "fetch_text", serving(body))
    outcome = await routing.refresh_source(session, source, settings)
    assert outcome.outcome == "in force", outcome
    return source


async def switch_on(client, node_id: str, resolver: str = DIRECT_RESOLVER):
    return await client.post(
        f"/panel/nodes/{node_id}/direct", data={"on": "on", "resolver": resolver}
    )


# --- off is off ----------------------------------------------------------------------


async def test_with_the_switch_off_lists_change_nothing_in_the_render(
    client, session, settings, reality_params, hop_params, monkeypatch
) -> None:
    entry = await an_entry_with_a_hop(client, session, reality_params, hop_params)
    before = await rendered(session, entry)
    await a_source_in_force(session, settings, monkeypatch)
    await routing.add_owner_entry(session, which=OwnerList.ALWAYS, value="mine.example")
    await routing.add_owner_entry(session, which=OwnerList.NEVER, value="site1.example")
    assert await rendered(session, entry) == before

    # On, then off again: back to the same bytes.
    assert (await switch_on(client, entry)).status_code == 200
    assert await rendered(session, entry) != before
    off = await client.post(f"/panel/nodes/{entry}/direct", data={"on": "", "resolver": ""})
    assert off.status_code == 200
    assert await rendered(session, entry) == before


async def test_a_node_switched_on_whose_hop_is_gone_renders_as_off(
    client, session, settings, reality_params, hop_params, monkeypatch
) -> None:
    entry = await an_entry_with_a_hop(client, session, reality_params, hop_params)
    await a_source_in_force(session, settings, monkeypatch)
    assert (await switch_on(client, entry)).status_code == 200
    node = await nodes.get_node(session, entry)
    from control.app.services import relay

    monkeypatch.setattr(relay, "exit_through_hop", _no_hop)
    config = json.loads((await apply.render_for_node(session, node))[USER_TRANSPORT])
    assert [o["tag"] for o in config["outbounds"]] == ["direct", "refused"]
    assert "dns" not in config


async def _no_hop(session, node):
    return None


# --- on: what reaches the renderer ----------------------------------------------------


async def test_switched_on_the_lists_and_the_resolver_reach_the_config(
    client, session, settings, reality_params, hop_params, monkeypatch
) -> None:
    entry = await an_entry_with_a_hop(client, session, reality_params, hop_params)
    await a_source_in_force(session, settings, monkeypatch)
    await routing.add_owner_entry(session, which=OwnerList.ALWAYS, value="Mine.Example")
    assert (await switch_on(client, entry)).status_code == 200
    config = json.loads(await rendered(session, entry))
    direct_rule = next(
        r for r in config["routing"]["rules"]
        if r["outboundTag"] == "direct" and "domain" in r
    )
    assert "domain:site0.example" in direct_rule["domain"]
    assert "domain:mine.example" in direct_rule["domain"]
    assert len(direct_rule["domain"]) == 41
    assert config["dns"]["servers"][1]["address"] == DIRECT_RESOLVER


async def test_never_direct_beats_a_source(
    client, session, settings, reality_params, hop_params, monkeypatch
) -> None:
    entry = await an_entry_with_a_hop(client, session, reality_params, hop_params)
    await a_source_in_force(session, settings, monkeypatch)
    await routing.add_owner_entry(session, which=OwnerList.NEVER, value="site7.example")
    assert (await switch_on(client, entry)).status_code == 200
    rules = json.loads(await rendered(session, entry))["routing"]["rules"]
    tags = [(r["outboundTag"], r.get("domain")) for r in rules if r["inboundTag"] == ["in"]]
    never_at = tags.index(("hop", ["domain:site7.example"]))
    direct_at = next(i for i, (tag, d) in enumerate(tags) if tag == "direct" and d)
    assert never_at < direct_at, "never direct must be read before the source's listing"

    verdict = await routing.where(session, "www.site7.example")
    assert verdict.direct is False and "never-direct" in verdict.sentence
    verdict = await routing.where(session, "www.site8.example")
    assert verdict.direct is True and "listed by narrow" in verdict.sentence
    verdict = await routing.where(session, "elsewhere.example")
    assert verdict.direct is False and "on no list" in verdict.sentence


async def test_switching_on_needs_a_hop_and_a_resolver_that_is_not_the_hops(
    client, session, reality_params, hop_params
) -> None:
    lone = await client.post(
        "/api/nodes",
        json={"name": "lone", "address": "192.0.2.30", "location_label": "X",
              "resolver": RESOLVER},
    )
    refused = await switch_on(client, lone.json()["id"])
    assert refused.status_code == 422
    assert "dials no hop" in refused.text

    entry = await an_entry_with_a_hop(client, session, reality_params, hop_params)
    for resolver, why in ((RESOLVER, "also this node"), ("", "give the resolver"),
                          ("127.0.0.53", "container"), ("dns.example", "not an IPv4")):
        refused = await switch_on(client, entry, resolver)
        assert refused.status_code == 422, resolver
        assert why in refused.text, (resolver, refused.text)
    node = await nodes.get_node(session, entry)
    session.expire(node)
    assert not (await nodes.get_node(session, entry)).direct_routing


async def test_the_lists_together_are_bounded_at_render(
    client, session, settings, reality_params, hop_params, monkeypatch
) -> None:
    entry = await an_entry_with_a_hop(client, session, reality_params, hop_params)
    await a_source_in_force(session, settings, monkeypatch)
    await a_source_in_force(
        session, settings, monkeypatch,
        body="\n".join(f"other{n}.example" for n in range(40)), name="second",
    )
    assert (await switch_on(client, entry)).status_code == 200
    from control.app import settings as settings_module

    monkeypatch.setattr(
        settings_module.bound_settings(), "routing_max_entries", 60, raising=False
    )
    session.expire_all()
    node = await nodes.get_node(session, entry)
    with pytest.raises(ConfigRefused, match="80 entries together"):
        await apply.render_for_node(session, node)


# --- reading a list, and holding one -------------------------------------------------


def test_a_plain_list_and_the_domain_list_format_are_read() -> None:
    parsed = routing.parse_list(
        "# comment\n"
        "Gosuslugi.example\n"
        "*.wild.example\n"
        "domain:suffix.example @ads\n"
        "full:exact.example\n"
        "keyword:adobe\n"
        "regexp:^x\n"
        "include:other\n"
        "203.0.113.5/24\n"
        "198.51.100.7\n"
        "\n"
    )
    assert parsed.entries == (
        "198.51.100.7/32",
        "203.0.113.0/24",
        "=exact.example",
        "gosuslugi.example",
        "suffix.example",
        "wild.example",
    )
    assert parsed.skipped == 3
    assert parsed.invalid == 0


def test_an_error_page_in_place_of_a_list_is_invalid() -> None:
    parsed = routing.parse_list("<html><body>rate limited</body></html>\n")
    assert parsed.invalid == 1 and not parsed.entries
    reason = routing.hold_reason(parsed, 40, max_change=0.5, max_entries=100)
    assert "not a name or a network" in reason


@pytest.mark.parametrize(
    ("count", "previous", "held"),
    [(40, None, False), (60, 40, False), (61, 40, True), (19, 40, True), (20, 40, False),
     (101, None, True), (0, 40, True)],
)
def test_the_bounds_a_version_is_held_by(count, previous, held) -> None:
    parsed = routing.Parsed(
        entries=tuple(f"s{n}.example" for n in range(count)), skipped=0, invalid=0
    )
    reason = routing.hold_reason(parsed, previous, max_change=0.5, max_entries=100)
    assert (reason is not None) is held, reason


async def test_a_held_update_is_not_applied_until_the_owner_approves(
    client, session, settings, reality_params, hop_params, monkeypatch
) -> None:
    entry = await an_entry_with_a_hop(client, session, reality_params, hop_params)
    source = await a_source_in_force(session, settings, monkeypatch)
    assert (await switch_on(client, entry)).status_code == 200
    before = await rendered(session, entry)

    grown = NARROW + "".join(f"new{n}.example\n" for n in range(30))
    monkeypatch.setattr(routing, "fetch_text", serving(grown))
    outcome = await routing.refresh_source(session, source, settings)
    assert outcome.outcome == "held"
    assert await rendered(session, entry) == before

    screen = await client.get("/panel/routing")
    assert "Held: an update to narrow" in screen.text
    assert "+ new0.example" in screen.text
    assert "30 added" in screen.text

    # The same content fetched again is not a second prompt.
    assert (await routing.refresh_source(session, source, settings)).outcome == "still held"

    held = (await session.execute(
        select(RoutingListVersion).where(RoutingListVersion.status == VersionStatus.HELD)
    )).scalars().one()
    approved = await client.post(f"/panel/routing/updates/{held.id}/approve")
    assert approved.status_code == 200
    assert "new0.example" in await rendered(session, entry)


async def test_a_rejected_update_leaves_the_list_in_force_and_is_not_asked_again(
    client, session, settings, monkeypatch
) -> None:
    source = await a_source_in_force(session, settings, monkeypatch)
    monkeypatch.setattr(routing, "fetch_text", serving("only.example\n"))
    assert (await routing.refresh_source(session, source, settings)).outcome == "held"
    held = (await session.execute(
        select(RoutingListVersion).where(RoutingListVersion.status == VersionStatus.HELD)
    )).scalars().one()
    assert (await client.post(f"/panel/routing/updates/{held.id}/reject")).status_code == 200
    current = await routing.in_force(session, source.id)
    assert current.count == 40
    assert (await routing.refresh_source(session, source, settings)).outcome == "rejected before"


async def test_a_failed_fetch_keeps_the_last_good_version_and_says_how_old(
    client, session, settings, reality_params, hop_params, monkeypatch
) -> None:
    entry = await an_entry_with_a_hop(client, session, reality_params, hop_params)
    source = await a_source_in_force(session, settings, monkeypatch)
    assert (await switch_on(client, entry)).status_code == 200
    before = await rendered(session, entry)

    def unreachable(url, *, timeout, max_bytes):
        raise routing.FetchFailed("the list's host could not be reached (URLError).")

    monkeypatch.setattr(routing, "fetch_text", unreachable)
    later = datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=3)
    outcome = await routing.refresh_source(session, source, settings, now=later)
    assert outcome.outcome == "failed"
    assert await rendered(session, entry) == before
    assert (await routing.in_force(session, source.id)).count == 40

    view = await routing.screen(session, settings, now=later)
    row = view.sources[0]
    assert row.error.startswith("the list's host could not be reached")
    assert row.fetched == "3 days ago"


# --- fetching, for real, over HTTPS on loopback -----------------------------------------


@pytest.fixture
def https_lists(tmp_path, monkeypatch):
    """A loopback HTTPS server with a certificate this process is told to trust."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_file, key_file = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_file.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    pages = {"/narrow.lst": (200, NARROW.encode()), "/big.lst": (200, b"x.example\n" * 500)}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path == "/elsewhere":
                self.send_response(302)
                self.send_header("Location", "http://localhost/narrow.lst")
                self.end_headers()
                return
            status, body = pages.get(self.path, (404, b"no"))
            self.send_response(status)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_file, key_file)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("SSL_CERT_FILE", str(cert_file))
    yield f"https://localhost:{server.server_address[1]}"
    server.shutdown()


def test_fetching_reads_a_list_over_https(https_lists) -> None:
    body = routing.fetch_text(f"{https_lists}/narrow.lst", timeout=5, max_bytes=100_000)
    assert body == NARROW


@pytest.mark.parametrize(
    ("path", "max_bytes", "why"),
    [("/missing.lst", 100_000, "HTTP 404"), ("/big.lst", 1000, "larger than 1000 bytes"),
     ("/elsewhere", 100_000, "not https")],
)
def test_a_fetch_that_cannot_be_trusted_fails_in_words(https_lists, path, max_bytes, why) -> None:
    with pytest.raises(routing.FetchFailed, match=why):
        routing.fetch_text(f"{https_lists}{path}", timeout=5, max_bytes=max_bytes)


def test_an_untrusted_certificate_fails_in_words(https_lists, monkeypatch) -> None:
    monkeypatch.delenv("SSL_CERT_FILE")
    with pytest.raises(routing.FetchFailed, match="certificate|reached"):
        routing.fetch_text(f"{https_lists}/narrow.lst", timeout=5, max_bytes=100_000)


@pytest.mark.parametrize(
    "url", ["http://lists.example/a.lst", "ftp://lists.example/a", "https://u:p@lists.example/a"]
)
def test_only_an_https_address_without_a_credential_can_be_a_source(url) -> None:
    assert routing.url_problem(url) is not None


def test_suggested_sources_are_configuration() -> None:
    found = routing.suggested_sources(
        "narrow|https://lists.example/a.lst|on; broad|https://lists.example/b|off;"
        "broken|http://x|on;also-broken"
    )
    assert [(s.name, s.on) for s in found] == [("narrow", True), ("broad", False)]
    assert Settings.model_fields["routing_suggested_sources"].default == ""


async def test_fetch_now_answers_before_the_fetch_finishes(
    app, client, session, settings, monkeypatch
) -> None:
    await routing.add_source(session, name="slow", url="https://lists.example/s", enabled=True)
    release = threading.Event()

    def slow(url, *, timeout, max_bytes):
        release.wait(10)
        return NARROW

    monkeypatch.setattr(routing, "fetch_text", slow)
    answered = await client.post("/panel/routing/fetch")
    assert answered.status_code == 200
    assert app.state.routing_fetch.running
    body = await client.get("/panel/routing/body")
    assert "every 2s" in body.text
    release.set()
    await asyncio.wait_for(app.state.routing_fetch.task, 10)
    source_id = (await session.execute(select(RoutingSource.id))).scalar_one()
    session.expire_all()
    assert (await routing.in_force(session, source_id)).count == 40


# --- the nightly run -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("local", "last", "owed"),
    [("03:59", None, False), ("04:00", None, True), ("23:00", "yesterday", True),
     ("05:00", "today", False)],
)
def test_the_run_is_owed_once_a_day_from_the_backups_hour(local, last, owed) -> None:
    settings = Settings.model_construct(backup_at="04:00", backup_tz="Europe/Moscow")
    hours, minutes = map(int, local.split(":"))
    import zoneinfo

    zone = zoneinfo.ZoneInfo("Europe/Moscow")
    now = datetime.datetime(2026, 10, 3, hours, minutes, tzinfo=zone)
    days = {None: None, "today": now.date(), "yesterday": now.date() - datetime.timedelta(days=1)}
    assert routing_refresh.due(now.astimezone(datetime.UTC), settings, days[last]) is owed


async def test_the_nightly_run_fetches_and_applies_only_the_entries_that_changed(
    app, client, session, settings, reality_params, hop_params, monkeypatch
) -> None:
    entry = await an_entry_with_a_hop(client, session, reality_params, hop_params)
    source = await a_source_in_force(session, settings, monkeypatch)
    assert (await switch_on(client, entry)).status_code == 200
    # The entry holds exactly what it would be given: in sync.
    session.expire_all()
    node = await nodes.get_node(session, entry)
    configs = await apply.render_for_node(session, node)
    from control.app.models import NodeTransport
    from edge.bootstrap import node_stack

    rows = (await session.execute(
        select(NodeTransport).where(NodeTransport.node_id == entry)
    )).scalars().unique()
    for row in rows:
        row.applied_digest = node_stack.digest_of(configs[row.config_name])
    await session.commit()
    assert await console.drift_of(session, node) == console.IN_SYNC

    applied: list = []

    async def apply_nodes(session, node_ids):
        applied.append(list(node_ids))
        return {node_id: None for node_id in node_ids}

    monkeypatch.setattr(apply, "apply_nodes", apply_nodes)
    at = datetime.datetime(2026, 10, 3, 4, 30, tzinfo=datetime.UTC)
    run_settings = settings.model_copy(update={"backup_at": "04:00", "backup_tz": "Etc/UTC"})

    # Nothing changed: the run happens and restarts nothing.
    assert await routing_refresh.nightly_pass(app.state.database, run_settings, now=at)
    assert applied == []
    # Owed once a day.
    assert not await routing_refresh.nightly_pass(app.state.database, run_settings, now=at)

    # The list changes within the bounds; the next night applies the entry, once.
    monkeypatch.setattr(routing, "fetch_text", serving(NARROW + "new.example\n"))
    tomorrow = at + datetime.timedelta(days=1)
    assert await routing_refresh.nightly_pass(app.state.database, run_settings, now=tomorrow)
    assert applied == [[entry]]
    assert source


async def test_the_nightly_run_fetches_nothing_while_no_entry_uses_the_lists(
    app, session, settings, monkeypatch
) -> None:
    await routing.add_source(session, name="unused", url="https://lists.example/u", enabled=True)

    def must_not(url, *, timeout, max_bytes):
        raise AssertionError("fetched a list nobody uses")

    monkeypatch.setattr(routing, "fetch_text", must_not)
    at = datetime.datetime(2026, 10, 3, 5, 0, tzinfo=datetime.UTC)
    run = settings.model_copy(update={"backup_at": "04:00", "backup_tz": "Etc/UTC"})
    assert await routing_refresh.nightly_pass(app.state.database, run, now=at)


# --- nothing records use -----------------------------------------------------------------


async def test_no_table_this_feature_added_can_hold_who_reached_what() -> None:
    columns = {
        table.name: sorted(table.columns.keys())
        for table in Base.metadata.sorted_tables
        if table.name.startswith("routing_")
    }
    assert columns == {
        "routing_list_versions": sorted([
            "id", "source_id", "fetched_at", "digest", "entries", "count", "skipped",
            "invalid", "status", "hold_reason", "decided_at",
        ]),
        "routing_owner_entries": ["created_at", "id", "list", "updated_at", "value"],
        "routing_schedule": ["id", "last_run_on"],
        "routing_sources": sorted([
            "id", "name", "url", "enabled", "last_attempt_at", "last_error", "created_at",
            "updated_at",
        ]),
    }


async def test_a_lookup_writes_nothing_and_logs_nothing(
    client, session, settings, monkeypatch, caplog
) -> None:
    await a_source_in_force(session, settings, monkeypatch)

    async def row_counts() -> dict[str, int]:
        counts = {}
        for table in Base.metadata.sorted_tables:
            counts[table.name] = (
                await session.execute(select(func.count()).select_from(table))
            ).scalar_one()
        return counts

    before = await row_counts()
    caplog.set_level(logging.DEBUG)
    answer = await client.post(
        "/panel/routing/lookup", data={"destination": "secret-destination.site3.example"}
    )
    assert answer.status_code == 200
    assert "listed by narrow" in answer.text
    assert await row_counts() == before
    assert "secret-destination" not in caplog.text


async def test_refreshing_and_rendering_log_no_destination(
    client, session, settings, reality_params, hop_params, monkeypatch, caplog
) -> None:
    caplog.set_level(logging.DEBUG)
    entry = await an_entry_with_a_hop(client, session, reality_params, hop_params)
    await a_source_in_force(session, settings, monkeypatch, body="marker-destination.example\n")
    assert (await switch_on(client, entry)).status_code == 200
    assert "marker-destination" in await rendered(session, entry)
    await client.get("/panel/routing")
    assert "marker-destination" not in caplog.text


async def test_the_audit_trail_names_lists_and_nodes_never_a_destination(
    client, session, settings, reality_params, hop_params, monkeypatch
) -> None:
    entry = await an_entry_with_a_hop(client, session, reality_params, hop_params)
    await a_source_in_force(session, settings, monkeypatch)
    await switch_on(client, entry)
    await client.post("/panel/routing/entries", data={"which": "never", "value": "x.example"})
    rows = (await session.execute(
        select(AuditEntry).where(AuditEntry.action.in_([
            AuditAction.DIRECT_ROUTING_SET, AuditAction.ROUTING_SOURCE_ADDED,
            AuditAction.ROUTING_LIST_CHANGED,
        ]))
    )).scalars().all()
    labels = {(row.action, row.first_label, row.second_label) for row in rows}
    assert labels == {
        (AuditAction.ROUTING_SOURCE_ADDED, "narrow", None),
        (AuditAction.DIRECT_ROUTING_SET, "entry-ru", "on"),
        (AuditAction.ROUTING_LIST_CHANGED, "never direct", None),
    }
    dump = (await session.execute(text("select string_agg(coalesce(first_label,'') || "
                                       "coalesce(second_label,''), ' ') from audit_entries"))
            ).scalar_one()
    assert "x.example" not in dump


# --- the screen --------------------------------------------------------------------------


async def test_the_routing_screen_shows_the_lists_and_offers_the_configured_suggestions(
    app, client, session, settings, monkeypatch
) -> None:
    app.state.settings = settings.model_copy(update={
        "routing_suggested_sources": "narrow-list|https://lists.example/n.lst|on"
    })
    screen = await client.get("/panel/routing")
    assert screen.status_code == 200
    assert "narrow-list" in screen.text and "https://lists.example/n.lst" in screen.text
    added = await client.post("/panel/routing/suggestions", data={"name": "narrow-list"})
    assert added.status_code == 200
    source = (await session.execute(select(RoutingSource))).scalars().one()
    assert source.enabled and source.url == "https://lists.example/n.lst"

    entry = await client.post(
        "/panel/routing/entries", data={"which": "always", "value": "not a site!"}
    )
    assert entry.status_code == 422
    assert "is not a name" in entry.text


async def test_the_nodes_screen_offers_the_switch_and_says_when_it_is_on(
    client, session, settings, reality_params, hop_params, monkeypatch
) -> None:
    entry = await an_entry_with_a_hop(client, session, reality_params, hop_params)
    screen = await client.get("/panel/nodes")
    assert f"/panel/nodes/{entry}/direct" in screen.text
    assert "direct sites: on" not in screen.text
    await switch_on(client, entry)
    screen = await client.get("/panel/nodes")
    assert "direct sites: on" in screen.text
    dialog = await client.get(f"/panel/nodes/{entry}/direct")
    assert "those sites see it, not the leaf" in dialog.text


async def test_switching_a_source_off_takes_its_sites_out_of_the_render(
    client, session, settings, reality_params, hop_params, monkeypatch
) -> None:
    entry = await an_entry_with_a_hop(client, session, reality_params, hop_params)
    source = await a_source_in_force(session, settings, monkeypatch)
    await switch_on(client, entry)
    assert "site0.example" in await rendered(session, entry)
    switched = await client.post(
        f"/panel/routing/sources/{source.id}/switch", data={"enabled": "off"}
    )
    assert switched.status_code == 200
    session.expire_all()
    assert "site0.example" not in await rendered(session, entry)


async def test_an_owner_entry_that_is_not_a_destination_is_refused(session) -> None:
    with pytest.raises(DomainError):
        await routing.add_owner_entry(session, which=OwnerList.ALWAYS, value="0.0.0.0/0")


async def test_a_list_of_escape_heavy_garbage_is_held_and_written(session, settings, monkeypatch):
    """A remote body must not be able to make the hold itself fail to be written (review r1)."""
    source = await a_source_in_force(session, settings, monkeypatch)
    monkeypatch.setattr(routing, "fetch_text", serving(("\\" * 80 + " x\n") * 3))
    outcome = await routing.refresh_source(session, source, settings)
    assert outcome.outcome == "held"
    assert len(outcome.detail) <= 500
