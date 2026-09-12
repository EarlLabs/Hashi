"""Two representations, one token, one route — backlog item 27.

WHAT: the delivery endpoint's second shape (``?format=client-config-file``) and the
      four properties it must not break.
WHY:  the charter calls "how does a protocol with no URI form reach a phone in one
      link" the largest open question of phase 1, and says it is a product decision.
      The owner made it on 2026-08-09: option (b), per-client config files behind the
      SAME token. "Same token" is the whole constraint — a second token or a second
      route would mean thirty friends re-importing something, which is precisely what
      this product promises never to require, and every rule that protects the token in
      the path is written for one route.
HOW:  driven exactly as a friend's client drives it: anonymous GETs against
      ``/sub/{token}``, with and without the parameter. The operator's setup goes
      through the panel, since that is where an owner does it.

Boundary: real control + postgres + caddy. No node, no tunnel: what is proven is which
bytes the endpoint hands over and what it refuses to say. Whether a client accepts the
file is the owner's field check, and whether the upstream tool parses it is
tests/edge/test_upstream_validation.py.
"""

import base64
import io
import re
import uuid
import zipfile

import pytest

OPERATOR = {"username": "owner", "password": "e2e-operator-password"}

# The console asks with htmx, and since M9.6 nothing here answers a header-less POST
# with a redirect to a page: the pre-redesign panel those two branches existed for is
# gone.
HTMX = {"HX-Request": "true"}
CONFIG_FILE_FORMAT = "client-config-file"

# Distinct per scenario. NOT used to identify this run's own entries, though — see
# ``mine_in``: a port is fixed in the source, so it identifies the scenario and not the
# RUN, and two runs against one stack would both match.
REALITY_PORT = 8471
AWG_PORT_SHAPES = 51931
AWG_PORT_UNTOUCHED = 51932

# How many users a friend-facing row of this transport may hand an address to — M17. The
# stand is WARM: every scenario in this directory adds users to one control plane and
# none are removed, so a pool is measured against a fleet that only grows. Low thousands
# against a /20 tunnel for that reason — the number is a ceiling on people, not a
# resource, and a pool that only just fitted would turn this file red on the day an
# unrelated scenario adds a user.
POOL_SIZE = 2000


@pytest.fixture
def unique() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture
async def operator(client):
    response = await client.post("/panel/login", data=OPERATOR)
    assert response.status_code == 303, response.text
    return client


def awg_params(port: int, address: str, peer: str) -> dict[str, str]:
    """A config-file transport's operator-supplied parameters, as form fields.

    Values are arbitrary but fixed, and the tunnel networks are RFC 1918 — the
    transport's own model enforces private ranges, not this file.
    """
    return {
        "port": str(port),
        "tunnel_address": address,
        "peer_tunnel_address": peer,
        # M17's box, which the enable form renders for exactly the transports that give
        # every user their own address. It is named for its group like every other box on
        # that form, so the caller's own ``f"{chosen}-{key}"`` mapping carries it without
        # knowing it is not a parameter of the transport.
        "pool_size": str(POOL_SIZE),
        "mtu": "1280",
        "junk_packet_count": "4",
        "junk_packet_min_size": "40",
        "junk_packet_max_size": "80",
        "init_packet_magic_header": "1020327352",
        "response_packet_magic_header": "2060487442",
        "underload_packet_magic_header": "3679305607",
        "transport_packet_magic_header": "1436947798",
    }


async def node_with(operator, *, name: str, address: str, country: str, transport: dict) -> str:
    """A serving node running one transport, created and switched on from the panel.

    200 is the success assertion on all three: every one of these refuses at 422 with its
    dialog re-rendered, so a refusal cannot be read as a success. The enable form names
    every box for its transport's GROUP — the dialog renders one group per transport and
    hides all but the chosen one, and a hidden input is still submitted — so the prefix is
    added here rather than written into each caller's parameter mapping.
    """
    created = await operator.post(
        "/panel/nodes",
        data={"name": name, "address": address, "location_label": country},
        headers=HTMX,
    )
    assert created.status_code == 200, created.text
    node_id = next(
        node["id"] for node in (await operator.get("/api/nodes")).json() if node["name"] == name
    )

    chosen = transport["transport_name"]
    enabled = await operator.post(
        f"/panel/nodes/{node_id}/transports",
        data={
            key if key == "transport_name" else f"{chosen}-{key}": value
            for key, value in transport.items()
        },
        headers=HTMX,
    )
    assert enabled.status_code == 200, enabled.text

    state = await operator.post(
        f"/panel/nodes/{node_id}/state", data={"state": "active"}, headers=HTMX
    )
    assert state.status_code == 200, state.text
    return node_id


async def friend_token(operator, nickname: str) -> str:
    friend_id = (
        await operator.post("/api/friends", json={"nickname": nickname})
    ).json()["id"]
    url = (await operator.get(f"/api/friends/{friend_id}/subscription")).json()["url"]
    return url.rsplit("/", 1)[-1]


def files_in(archive: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        return {name: bundle.read(name).decode() for name in bundle.namelist()}


def mine_in(archive: bytes, unique: str) -> dict[str, str]:
    """Only the files this run's own fleet produced.

    Matched on the FILENAME, because that is the one part of a config file carrying
    anything the scenario chose: the transport derives it from the node's operator-given
    name. Hence the node names below start with ``unique`` — the name is slugged and
    truncated to fit an interface name, so a marker at the end would be cut off.

    Necessary because the stack outlives one run unless it is torn down with its
    volumes, and every active friend is granted every serving node — including the ones
    an earlier run left behind.
    """
    return {name: body for name, body in files_in(archive).items() if unique in name}


# --- S1: one token, two shapes, chosen explicitly ----------------------------

async def test_the_same_token_serves_both_shapes_and_the_caller_chooses(
    operator, client, unique: str
) -> None:
    """S1. Two forms of one subscription, selected by the request and nothing else.

    The negative half is the one worth stating: the shape must NOT depend on who is
    asking. A response that varies by User-Agent is one nobody can reproduce — the
    friend describing a problem and the operator looking at it would be discussing
    different documents. So the same token is fetched twice with two different
    User-Agents and the bytes are required to be identical.
    """
    await node_with(
        operator,
        name=f"{unique}-two",
        address="192.0.2.81",
        country=f"Shapeland-{unique}",
        transport={
            "transport_name": "amneziawg",
            **awg_params(AWG_PORT_SHAPES, "10.81.0.1/20", "10.81.0.2/20"),
        },
    )
    token = await friend_token(operator, f"twoshapes-{unique}")

    document = await client.get(f"/sub/{token}")
    assert document.status_code == 200, document.text
    assert document.headers["content-type"].startswith("text/plain")
    # Still base64 of URIs, and still decodable — the default shape did not become the
    # new one just because the new one exists.
    base64.b64decode(document.text)

    archive = await client.get(f"/sub/{token}", params={"format": CONFIG_FILE_FORMAT})
    assert archive.status_code == 200, archive.text
    assert archive.headers["content-type"] == "application/zip"
    assert "hashi-configs.zip" in archive.headers["content-disposition"]
    # The token must not be in the filename a browser saves or in a downloads list.
    assert token not in archive.headers["content-disposition"]

    mine = mine_in(archive.content, unique)
    assert len(mine) == 1, mine
    assert f":{AWG_PORT_SHAPES}" in next(iter(mine.values()))
    body = next(iter(mine.values()))
    assert "[Interface]" in body and "[Peer]" in body
    # AN address out of this transport's pool, written with the prefix the operator typed
    # — M17, where this used to name the one address every user shared. Deliberately not
    # the pool's first: this stand is WARM, so every user an earlier scenario created was
    # granted this transport the moment its node started serving, and they hold the
    # addresses below this one. That is the behaviour, not a nuisance — what a friend's
    # file must carry is an address of their own inside the tunnel this node was given.
    assert re.search(r"Address\s*=\s*10\.81\.\d+\.\d+/20", body), body

    # The credential-protecting headers are on BOTH shapes. A second shape that lost
    # no-store would be a bearer-credential body sitting in someone else's cache, and
    # nothing would fail.
    for response in (document, archive):
        assert response.headers["cache-control"] == "no-store, max-age=0"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"

    # Same token, different caller, same bytes.
    as_a_browser = await client.get(
        f"/sub/{token}",
        params={"format": CONFIG_FILE_FORMAT},
        headers={"User-Agent": "Mozilla/5.0"},
    )
    as_a_client = await client.get(
        f"/sub/{token}",
        params={"format": CONFIG_FILE_FORMAT},
        headers={"User-Agent": "AmneziaWG/1.0"},
    )
    assert as_a_browser.content == as_a_client.content, (
        "the response depends on who asked, so nobody can reproduce a friend's report"
    )
    # And it is byte-stable between refreshes: an archive stamped with the build clock
    # would differ on every fetch, which hides a real change in noise.
    assert as_a_browser.content == archive.content


# --- S2: the link a friend already holds does not change ---------------------

async def test_a_friend_on_uri_transports_only_sees_no_change_at_all(
    operator, client, unique: str
) -> None:
    """S2. Adding a second shape to the fleet does not touch the first one's bytes.

    Captured before and compared after, on the same token, with the config-file
    transport switched on in between. Not "the response still parses" — the same bytes,
    because the promise is that a friend never re-imports anything and never notices an
    operator's change.
    """
    country = f"Unchanged-{unique}"
    await node_with(
        operator,
        name=f"{unique}-uri",
        address="192.0.2.82",
        country=country,
        transport={
            "transport_name": "vless-reality",
            "port": str(REALITY_PORT),
            "decoy_host": "www.example.com",
            "decoy_port": "443",
            "server_names": "www.example.com",
        },
    )
    token = await friend_token(operator, f"uri-only-{unique}")
    before = (await client.get(f"/sub/{token}")).text

    # A config-file transport arrives in the fleet, on its own node, and this friend is
    # granted it like every active friend.
    await node_with(
        operator,
        name=f"{unique}-fil",
        address="192.0.2.83",
        country=country,
        transport={
            "transport_name": "amneziawg",
            **awg_params(AWG_PORT_UNTOUCHED, "10.82.0.1/20", "10.82.0.2/20"),
        },
    )

    after = await client.get(f"/sub/{token}")
    assert after.status_code == 200
    assert after.text == before, (
        "the v1 subscription changed when a config-file transport was enabled — the "
        "friend's client would re-read a document it had no reason to re-read"
    )
    # And what they DO now have is reachable, in the other shape only.
    archive = await client.get(f"/sub/{token}", params={"format": CONFIG_FILE_FORMAT})
    assert any(
        f":{AWG_PORT_UNTOUCHED}" in body for body in mine_in(archive.content, unique).values()
    ), "the friend was granted a config-file transport and cannot fetch it"


# --- S4: an unknown token is a 404, identically in both shapes ---------------

async def test_an_unknown_token_is_the_same_404_in_both_shapes(client) -> None:
    """S4. Which formats a token supports must not be probeable either.

    A 200-with-an-empty-archive for a nonexistent token, or a different status per
    shape, would let a stranger learn that a token exists — the same thing the
    404-not-403 rule exists to prevent, arriving through the new parameter.
    """
    nonsense = "e2e-not-a-real-token-" + uuid.uuid4().hex

    plain = await client.get(f"/sub/{nonsense}")
    archived = await client.get(f"/sub/{nonsense}", params={"format": CONFIG_FILE_FORMAT})

    assert plain.status_code == 404
    assert archived.status_code == 404
    assert plain.content == archived.content == b""
    # Nothing in either answer describes what was wrong with the token.
    for response in (plain, archived):
        assert "token" not in response.text.lower()


async def test_a_format_nobody_ships_is_refused_without_revealing_anything(
    operator, client, unique: str
) -> None:
    """An unknown ``format`` is about the parameter, never about the token.

    Refused before any lookup, so the answer is identical for a live token and a dead
    one — otherwise the new parameter would become an oracle for token existence.
    """
    token = await friend_token(operator, f"badformat-{unique}")
    nonsense = "e2e-not-a-real-token-" + uuid.uuid4().hex

    live = await client.get(f"/sub/{token}", params={"format": "carrier-pigeon"})
    dead = await client.get(f"/sub/{nonsense}", params={"format": "carrier-pigeon"})

    assert live.status_code == dead.status_code == 422
    assert token not in live.text, "a 422 echoed the subscription token"
