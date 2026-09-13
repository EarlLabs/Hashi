"""A WireGuard-family transport serves every user on its node — M17.

WHAT: two users on one such row receiving two different addresses, the pool refused
      before it can be saved too small, the pool filling up and being resized, and the
      three things that must never move an address somebody already holds — a rotation,
      a revocation and a hop end's dialog.
WHY:  the field found this transport serving exactly one friend: every user on a row was
      handed the row's own ``peer_tunnel_address``, and the second user made the node's
      configuration unrenderable (``AllowedIPs`` is the authorisation list and the
      routing table at once, so two peers on one address is a silent hijack of the first
      one's return path). The charter's scale is ~30–50 friends. This scenario walks the
      milestone's acceptance line against the booted stack — *"either both work, or the
      refusal arrived early enough that the operator never believed it would"*.
HOW:  the operator's own surfaces. The panel where the claim is about the panel — the
      pool box and the sentence under it — and the API where the same operation has a
      script for a caller and the scenario needs the row's id back. What a user receives
      is read the way their client reads it: an anonymous GET of
      ``/sub/{token}?format=client-config-file``, and the ``Address`` line of the file.

Boundary: real control + postgres + caddy. NO NODE AND NO TUNNEL. That two addresses are
configured is proven here; that both CARRY TRAFFIC is a field observation on real
hardware (``docs/tracker/field-checklist.md``) and nothing in this file may be reported
as covering it. Every push therefore fails and marks its node degraded, which is why each
mutation below is followed by putting the node back into service.
"""

import io
import re
import uuid
import zipfile

import pytest

OPERATOR = {"username": "owner", "password": "e2e-operator-password"}

# The console asks with htmx; the refusal this scenario reads is a dialog re-rendered at
# 422, which is the one status static/app.js allows to swap.
HTMX = {"HX-Request": "true"}
CONFIG_FILE_FORMAT = "client-config-file"

# The transport this is about, named for the reason the runbook scenario names one: it is
# the protocol the runbook tells an owner to give their friends, and it is the one the
# field ran into. What keeps the literal honest is the first assertion below — the enable
# dialog must still render a POOL BOX for this transport, which it does only for a
# transport whose own declaration says each of its consumers needs an address. If that
# declaration ever moves, this file fails instead of quietly testing a transport that
# hands out nothing.
FAMILY_TRANSPORT = "amneziawg"

# Ports and tunnel networks of this scenario's own, distinct from every other file in
# this directory: the stand is one fleet, and two scenarios colliding on a port would be
# a refusal that has nothing to do with what either is testing.
SERVES_PORT = 51941
REFUSED_PORT = 51942
FULL_POOL_PORT = 51943
ROTATE_PORT = 51944
HOP_PORT = 51945
ALSO_FRIENDS_PORT = 51946

# Room for far more people than this stand will ever hold. The stand is WARM — every
# scenario adds users to one control plane and none are removed — so a pool is measured
# against a fleet that only grows, and one that only just fitted would turn this file red
# on the day an unrelated scenario adds a user. The exception is the full-pool test,
# which sizes itself to the fleet on purpose and removes its row afterwards.
POOL_SIZE = 2000


@pytest.fixture
def unique() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture
async def operator(client):
    response = await client.post("/panel/login", data=OPERATOR)
    assert response.status_code == 303, response.text
    return client


def side(port: int, address: str, peer: str) -> dict:
    """This transport's operator-supplied parameters, as the API takes them.

    Values are arbitrary but fixed, and the tunnel networks are RFC 1918 — the
    transport's own model enforces private ranges, not this file.
    """
    return {
        "port": port,
        "tunnel_address": address,
        "peer_tunnel_address": peer,
        "mtu": 1280,
        "junk_packet_count": 4,
        "junk_packet_min_size": 40,
        "junk_packet_max_size": 80,
        "init_packet_magic_header": 1020327352,
        "response_packet_magic_header": 2060487442,
        "underload_packet_magic_header": 3679305607,
        "transport_packet_magic_header": 1436947798,
    }


def boxes(port: int, address: str, peer: str, *, pool_size: int) -> dict[str, str]:
    """The same parameters as the enable form submits them, plus M17's box.

    ``pool_size`` is not a parameter of the transport at all — it is a column on the
    node-transport record — but the form names every box for its group and submits them
    together, so it travels here with the rest.
    """
    typed = {key: str(value) for key, value in side(port, address, peer).items()}
    return {f"{FAMILY_TRANSPORT}-{key}": value for key, value in typed.items()} | {
        f"{FAMILY_TRANSPORT}-pool_size": str(pool_size),
        "transport_name": FAMILY_TRANSPORT,
    }


async def a_node(operator, *, name: str, address: str, label: str) -> str:
    created = await operator.post(
        "/api/nodes",
        json={"name": name, "address": address, "location_label": label},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def enabled_over_the_api(
    operator, node_id: str, *, port: int, address: str, peer: str, pool_size: int = POOL_SIZE
) -> str:
    """One friend-facing row, and its id — which is what every later call addresses.

    Over the API rather than the panel wherever the id is needed: the panel answers with
    a dialog and no node endpoint lists a node's rows, so a scenario that enabled through
    the form would have to scrape an id out of a table to say anything about the row
    afterwards. What the FORM does with the pool box is asserted on its own, twice, in the
    two tests below that are about the form.
    """
    offered = await operator.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": FAMILY_TRANSPORT,
            "pool_size": pool_size,
            "params": side(port, address, peer),
        },
    )
    assert offered.status_code == 201, offered.text
    return offered.json()["id"]


async def serving(operator, node_id: str) -> None:
    """Put the node into service — and back into it after every failed push.

    No node exists, so every push fails and marks its node degraded, which correctly drops
    it out of every subscription. Without this, an assertion after a mutation would pass
    for the wrong reason: what a user receives changed because the node vanished from it.
    """
    state = await operator.post(f"/api/nodes/{node_id}/state", json={"state": "active"})
    assert state.status_code == 200, state.text


async def a_user(operator, nickname: str) -> tuple[str, str]:
    """One user, and the token their client fetches with."""
    created = await operator.post("/api/friends", json={"nickname": nickname})
    assert created.status_code == 201, created.text
    friend_id = created.json()["id"]
    url = (await operator.get(f"/api/friends/{friend_id}/subscription")).json()["url"]
    return friend_id, url.rsplit("/", 1)[-1]


async def active_users(operator) -> int:
    """How many people this control plane would have to find an address for.

    Read from the API rather than assumed: the stand is shared, so the fleet this
    scenario meets is whatever every scenario before it left behind.
    """
    listed = (await operator.get("/api/friends")).json()
    return len([friend for friend in listed if friend["revoked_at"] is None])


def files_in(archive: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        return {name: bundle.read(name).decode() for name in bundle.namelist()}


async def address_of(client, token: str, port: int) -> str:
    """The address one user's own config file configures their interface with.

    Found by this scenario's own PORT rather than by a node name: a user is granted every
    serving node in a shared fleet, and the port is the marker that is certainly in the
    bytes. Whatever the file says, rather than a pattern — comparing two users' addresses
    is the assertion, and a helper that matched only the expected shape would make it
    green by returning nothing twice.
    """
    archive = await client.get(f"/sub/{token}", params={"format": CONFIG_FILE_FORMAT})
    assert archive.status_code == 200, archive.text
    ours = [body for body in files_in(archive.content).values() if f":{port}" in body]
    assert len(ours) == 1, f"expected one file for port {port}, got {len(ours)}"
    found = re.search(r"Address\s*=\s*(\S+)", ours[0])
    assert found, ours[0]
    return found.group(1)


def under_the_box(response, field: str) -> str:
    """One complaint on the enable dialog, read off the id its box is wired to."""
    found = re.search(
        rf'id="enable-{FAMILY_TRANSPORT}-{field}-error"[^>]*>(.*?)</div>',
        response.text,
        re.S,
    )
    assert found, response.text
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", found.group(1))).strip()


# --- the milestone's own line -------------------------------------------------

async def test_two_users_on_one_row_receive_two_addresses(
    operator, client, unique: str
) -> None:
    """The charter's scale against the field's finding: both users are configured.

    The pattern is not the assertion — the pre-M17 fallback wrote the row's own
    ``peer_tunnel_address`` into every user's file and satisfies any pattern. What catches
    that is the two files disagreeing.

    Enabled through the DIALOG, so the pool the addresses come out of is one an operator
    typed a number into rather than one a script set.
    """
    node_id = await a_node(
        operator, name=f"serves-{unique}", address="192.0.2.90", label=f"Everyland-{unique}"
    )
    # The two of them exist BEFORE the row does, which is both the ordinary case — the
    # fleet is already there when a node is added — and what makes the dialog's own count
    # below deterministic on a stand this scenario may be the first to touch.
    _, first = await a_user(operator, f"ann-{unique}")
    _, second = await a_user(operator, f"bob-{unique}")

    dialog = await operator.get(f"/panel/nodes/{node_id}/transports", headers=HTMX)
    assert dialog.status_code == 200, dialog.text
    # The box exists for this transport, and only for the ones that DECLARE an address per
    # consumer — which is what ties the literal at the top of this file to the registry.
    assert f'name="{FAMILY_TRANSPORT}-pool_size"' in dialog.text, dialog.text
    # And the dialog says how many people that number is about to be measured against,
    # before anything is submitted. The count is the whole stand's fleet, so it is read as
    # a shape rather than as a number this scenario could know.
    assert re.search(
        r"\d+ active users each take an address from it the moment this node serves",
        dialog.text,
    ), dialog.text

    enabled = await operator.post(
        f"/panel/nodes/{node_id}/transports",
        data=boxes(SERVES_PORT, "10.84.0.1/20", "10.84.0.2/20", pool_size=POOL_SIZE),
        headers=HTMX,
    )
    assert enabled.status_code == 200, enabled.text
    await serving(operator, node_id)

    hers = await address_of(client, first, SERVES_PORT)
    his = await address_of(client, second, SERVES_PORT)

    assert hers != his, "two users on one row were handed one address"
    for address in (hers, his):
        assert re.fullmatch(r"10\.84\.\d+\.\d+/20", address), address


async def test_a_pool_smaller_than_the_fleet_is_refused_under_its_own_box(
    operator, unique: str
) -> None:
    """The refusal arrives while the operator is still looking at the number they typed.

    Under the BOX and not as a banner: the complaint is about one value on the form, and a
    sentence at the top of a dialog naming a field sends the operator hunting for it.
    Nothing is enabled — this is refused before the row exists, which is the half of the
    milestone that is about what does NOT happen.

    Two users are created first rather than assumed: the stand is shared and may be empty,
    and a pool of one is a perfectly good pool for a fleet of one.
    """
    for nickname in (f"crowd-{unique}-a", f"crowd-{unique}-b"):
        await a_user(operator, nickname)
    node_id = await a_node(
        operator, name=f"tooshort-{unique}", address="192.0.2.91", label=f"Shortland-{unique}"
    )

    refused = await operator.post(
        f"/panel/nodes/{node_id}/transports",
        data=boxes(REFUSED_PORT, "10.85.0.1/20", "10.85.0.2/20", pool_size=1),
        headers=HTMX,
    )

    assert refused.status_code == 422, refused.text
    said = under_the_box(refused, "pool_size")
    assert "cannot hold" in said, said
    assert said.startswith("a pool of 1"), said
    # In the page's words, never the code's (decision 9).
    assert "friend" not in said.lower(), said
    # Nothing was written: a second node with the same port would collide if the refused
    # row had been created, and the key screen would carry it.
    keys = await operator.get("/panel/keys/table", headers=HTMX)
    assert f"tooshort-{unique}" not in keys.text, "a refused form enabled a transport"


async def test_a_full_pool_refuses_the_next_user_and_a_resize_lets_them_in(
    operator, unique: str
) -> None:
    """The pool fills, the next person is refused with nothing written, the size grows.

    Sized to the fleet OF THIS MOMENT, which is the one test in this file that cannot use
    a roomy pool: what is being proven is what happens when there is exactly no room left.
    The user created first is what makes that number at least one on an empty stand.

    THE ROW IS REMOVED IN ``finally``, and that is not tidiness. While it exists and
    serves, every other scenario's ``POST /api/friends`` meets this pool and is refused —
    the stand is one fleet, and this file would otherwise break the rest of the suite from
    three directories away.
    """
    await a_user(operator, f"first-{unique}")
    node_id = await a_node(
        operator, name=f"fullpool-{unique}", address="192.0.2.92", label=f"Fullland-{unique}"
    )
    fleet = await active_users(operator)
    row_id = await enabled_over_the_api(
        operator,
        node_id,
        port=FULL_POOL_PORT,
        address="10.86.0.1/20",
        peer="10.86.0.2/20",
        pool_size=fleet,
    )
    try:
        await serving(operator, node_id)

        refused = await operator.post(
            "/api/friends", json={"nickname": f"waiting-{unique}"}
        )

        assert refused.status_code == 409, refused.text
        assert f"{FAMILY_TRANSPORT} on fullpool-{unique}" in (
            refused.json()["error"]["message"]
        )
        # BEFORE ANYTHING IS WRITTEN: no user, no subscription, no credential. The refusal
        # says "nothing has been changed", and this is what makes that true.
        assert not [
            friend
            for friend in (await operator.get("/api/friends")).json()
            if friend["nickname"] == f"waiting-{unique}"
        ], "a refused creation left a user behind"

        resized = await operator.post(
            f"/api/transports/{row_id}/params", json={"pool_size": fleet + 10}
        )
        assert resized.status_code == 200, resized.text
        assert "pool_size" in resized.json()["rotated"], resized.text
        # The resize pushed and the push failed, so the node is degraded — put it back
        # before the grant below, which reaches SERVING rows and no others.
        await serving(operator, node_id)

        admitted = await operator.post(
            "/api/friends", json={"nickname": f"waiting-{unique}"}
        )
        assert admitted.status_code == 201, admitted.text
    finally:
        removed = await operator.delete(f"/api/transports/{row_id}")
        assert removed.status_code == 200, removed.text


async def test_a_rotation_keeps_every_address_and_a_revocation_frees_one(
    operator, client, unique: str
) -> None:
    """Two operations that must not reshuffle who holds what, on one row.

    An address a device already holds is never moved: nobody is going to reconfigure
    thirty phones because a key was re-minted. The material changes behind the same link —
    that is what rotation is for — and the addresses stay where they are.

    Then the other direction: a revoked person's address goes back to the pool and the
    next arrival gets it, because the allocator hands out the lowest free one. Stranding
    it instead would mean a pool that shrinks every time somebody leaves.
    """
    node_id = await a_node(
        operator, name=f"rotate-{unique}", address="192.0.2.93", label=f"Rotaland-{unique}"
    )
    row_id = await enabled_over_the_api(
        operator, node_id, port=ROTATE_PORT, address="10.87.0.1/20", peer="10.87.0.2/20"
    )
    await serving(operator, node_id)
    _, first = await a_user(operator, f"cat-{unique}")
    second_id, second = await a_user(operator, f"dan-{unique}")
    before = [
        await address_of(client, first, ROTATE_PORT),
        await address_of(client, second, ROTATE_PORT),
    ]
    assert before[0] != before[1], before

    rotated = await operator.post(f"/api/transports/{row_id}/rotate-keys")
    assert rotated.status_code == 200, rotated.text
    await serving(operator, node_id)

    after = [
        await address_of(client, first, ROTATE_PORT),
        await address_of(client, second, ROTATE_PORT),
    ]
    assert after == before, "a rotation moved somebody's address"

    revoked = await operator.post(f"/api/friends/{second_id}/revoke")
    assert revoked.status_code == 200, revoked.text
    await serving(operator, node_id)

    _, third = await a_user(operator, f"eve-{unique}")
    assert await address_of(client, third, ROTATE_PORT) == before[1], (
        "a revoked user's address was stranded rather than handed to the next arrival"
    )
    assert await address_of(client, first, ROTATE_PORT) == before[0], (
        "a revocation moved somebody else's address"
    )


async def test_a_hop_end_is_offered_no_pool_anywhere_in_the_console(
    operator, unique: str
) -> None:
    """Hop ends are unchanged by this milestone — the plan's own done-when.

    A hop's consumer is the far NODE, at the single address the row already names, so
    there is no pool to size on it. The transport the runbook mandates for a hop is also
    the one it recommends for friends, so deciding from the declaration alone would put a
    pool box on the runbook's own entry box; the row's PURPOSE decides it, which is why
    this is asserted against a real hop and against a friend-facing row of the same
    protocol on the same screen.
    """
    entry_id = await a_node(
        operator, name=f"hopentry-{unique}", address="192.0.2.94", label=f"Entryland-{unique}"
    )
    leaf_id = await a_node(
        operator, name=f"hopleaf-{unique}", address="192.0.2.95", label=f"Leafland-{unique}"
    )
    established = await operator.post(
        "/api/hops",
        json={
            "entry_node_id": entry_id,
            "leaf_node_id": leaf_id,
            "transport_name": FAMILY_TRANSPORT,
            "entry_params": side(HOP_PORT, "10.88.0.1/24", "10.88.0.2/24"),
            "leaf_params": side(HOP_PORT, "10.88.0.2/24", "10.88.0.1/24"),
        },
    )
    assert established.status_code == 201, established.text
    hop_end = established.json()["entry"]["id"]

    dialog = await operator.get(f"/panel/keys/{hop_end}/params", headers=HTMX)
    assert dialog.status_code == 200, dialog.text
    assert 'name="pool_size"' not in dialog.text, "a hop end was offered a pool to size"

    # The dialog a hop is established from has none either, and never did.
    new_hop = await operator.get("/panel/hops/new", headers=HTMX)
    assert new_hop.status_code == 200, new_hop.text
    assert "pool_size" not in new_hop.text, new_hop.text

    # And the box IS on a friend-facing row of the same transport, on the same screen — so
    # the absence above is about what the row is FOR and not about the dialog losing it.
    friend_facing = await a_node(
        operator, name=f"hopfriend-{unique}", address="192.0.2.96", label=f"Bothland-{unique}"
    )
    row_id = await enabled_over_the_api(
        operator,
        friend_facing,
        port=ALSO_FRIENDS_PORT,
        address="10.89.0.1/20",
        peer="10.89.0.2/20",
    )
    offered = await operator.get(f"/panel/keys/{row_id}/params", headers=HTMX)
    assert offered.status_code == 200, offered.text
    assert 'name="pool_size"' in offered.text, offered.text
