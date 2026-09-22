"""The second shape of a subscription — backlog item 27.

WHAT: the branchy parts of ``services/subscriptions``' file half — which credentials
      each shape includes, how the archive is built, and what happens when a user has
      nothing in a shape — plus the refusal that survived the change.
WHY:  the acceptance scenarios (``tests/e2e/control/test_the_same_token_serves_two_shapes.py``)
      drive the endpoint as a user's client does and cannot see any of this: the
      ZIP's entry metadata, a filename collision between two nodes, or a transport that
      declares no user-facing format at all — because none ships.
HOW:  real Postgres, real encryption, real rendering. No node is contacted.
"""

import base64
import io
import json
import re
import zipfile
from dataclasses import replace

import pytest
from sqlalchemy import select

from control.app.errors import NotDeliverable
from control.app.models import Credential, NodeState, User
from control.app.services import apply, nodes, subscriptions, users
from edge.addressing import host_of
from edge.registry import ClientConfig, SubscriptionFormat, discover

AWG_PARAMS: dict[str, object] = {
    "mtu": 1280,
    "junk_packet_count": 4,
    "junk_packet_min_size": 40,
    "junk_packet_max_size": 80,
    "init_packet_magic_header": 1020327352,
    "response_packet_magic_header": 2060487442,
    "underload_packet_magic_header": 3679305607,
    "transport_packet_magic_header": 1436947798,
}

# Which transport in this image serialises into a file. Resolved from the registry
# rather than named, so this file does not become the one place in `control`'s tests
# that knows a protocol by name — and it skips loudly if the image ships none.
FILE_TRANSPORTS = sorted(
    name
    for name, meta in discover().items()
    if SubscriptionFormat.CLIENT_CONFIG_FILE in meta.subscription_formats
)
URI_TRANSPORTS = sorted(
    name
    for name, meta in discover().items()
    if SubscriptionFormat.V1_URI_LIST in meta.subscription_formats
)


@pytest.fixture
def file_transport() -> str:
    if not FILE_TRANSPORTS:
        pytest.skip(
            "this image ships no transport that serialises into a config file, so "
            "item 27's second shape cannot be exercised at all"
        )
    return FILE_TRANSPORTS[0]


# How many users a transport that gives each of them an address may hand out here — M17.
# Far above anything this file creates: every test below is about which SHAPE a user
# receives, not about the pool's edges, and a size that only just fits would turn an
# unrelated test red the day somebody adds a user to it. The /24s below hold it easily.
POOL_SIZE = 200


async def serving_node(
    client,
    session,
    *,
    name: str,
    address: str,
    transport_name: str,
    params: dict,
    pool_size: int = POOL_SIZE,
) -> str:
    created = await client.post(
        "/api/nodes",
        json={"name": name, "address": address, "location_label": "Testland"},
    )
    assert created.status_code == 201, created.text
    node_id = created.json()["id"]

    # The size is sent for exactly the transports that declare each user needs an address
    # of their own, and refused for the rest — so this helper asks the registry rather
    # than being told, and every call site below is unchanged whichever kind it enables.
    body: dict[str, object] = {"transport_name": transport_name, "params": params}
    if discover()[transport_name].peer_address is not None:
        body["pool_size"] = pool_size

    enabled = await client.post(f"/api/nodes/{node_id}/transports", json=body)
    assert enabled.status_code == 201, enabled.text

    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    return node_id


def names_in(archive: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        return bundle.namelist()


async def test_each_shape_includes_only_the_transports_that_declare_it(
    client, session, file_transport: str, reality_params
) -> None:
    """One user, one node of each kind, and neither shape carries the other's.

    The failure this catches is not cosmetic. Before item 27, ``entries_for`` met only
    URI transports, because a file transport could not be enabled for users at all.
    Now one user can hold both, and a v1 render that did not filter would call
    ``render_client`` on a transport that raises — turning that user's ORDINARY
    subscription link into a 500 because of a node they were merely also given.
    """
    await serving_node(
        client, session, name="uri-node", address="192.0.2.20",
        transport_name=URI_TRANSPORTS[0], params=reality_params,
    )
    await serving_node(
        client, session, name="file-node", address="192.0.2.21",
        transport_name=file_transport,
        params={**AWG_PARAMS, "port": 51820,
                "tunnel_address": "10.20.0.1/24", "peer_tunnel_address": "10.20.0.2/24"},
    )

    user = (await client.post("/api/users", json={"nickname": "kolya"})).json()
    handle = await users.get_user(session, user["id"])

    entries = await subscriptions.entries_for(session, handle)
    assert len(entries) == 1, [entry.entry for entry in entries]

    configs = await subscriptions.config_files_for(session, handle)
    assert len(configs) == 1
    assert "[Interface]" in configs[0].content

    # And the document itself still decodes and holds exactly the URI half.
    document = base64.b64decode(await subscriptions.render(session, handle)).decode()
    assert len(document.splitlines()) == 1


async def test_a_user_with_nothing_in_this_shape_gets_an_archive_that_says_so(
    client, session, reality_params
) -> None:
    """Empty, not an error — the same rule as the empty v1 document.

    A user whose nodes are momentarily degraded has not been revoked. An error here
    would make a node outage look like a withdrawal of access, which is the one thing
    their client reports to them directly.

    AND IT SAYS SO IN WORDS — M23, round 1's item 4, re-confirmed on the real hosts in
    round 3. The answer was a 22-byte ZIP: an empty central directory and nothing else,
    which a user's unarchiver opens as an empty folder without comment. The walk watched
    one person's archive go 3897 B to 22 B after a failed revocation degraded both nodes,
    with nothing anywhere telling them their link was still good. So an empty archive
    holds exactly one file, named for the answer, because a listing is often all a user
    sees before deciding the download failed.
    """
    await serving_node(
        client, session, name="uri-only", address="192.0.2.22",
        transport_name=URI_TRANSPORTS[0], params=reality_params,
    )
    user = (await client.post("/api/users", json={"nickname": "masha"})).json()
    handle = await users.get_user(session, user["id"])

    configs = await subscriptions.config_files_for(session, handle)
    assert configs == []
    archive = subscriptions.archive_of(configs)

    assert names_in(archive) == [subscriptions.EMPTY_ARCHIVE_NOTE_NAME]
    with zipfile.ZipFile(io.BytesIO(archive)) as opened:
        note = opened.read(subscriptions.EMPTY_ARCHIVE_NOTE_NAME).decode()
    assert note == subscriptions.EMPTY_ARCHIVE_NOTE
    # What it may not say. This text is served on a bearer path to whoever holds the
    # token, so it names nothing about the fleet and nothing about this person.
    for said in ("uri-only", "masha", "192.0.2.22", "node", "revoke"):
        assert said not in note.lower(), note
    # And what it must: the link is fine and nothing on the device needs changing, which
    # is the whole reason a user can tell this from a download that went wrong.
    assert "your link is not dead" in note
    # Byte-stable like every other archive: no clock inside the response.
    assert subscriptions.archive_of([]) == subscriptions.archive_of([])


async def test_an_archive_that_holds_configs_carries_no_note(
    client, session, file_transport: str, anonymous
) -> None:
    """The note is what an EMPTY archive is, and nothing else — and the route serves it.

    Both halves in one place because they are one decision. A note that also rode along
    with a working archive would be a file every user unpacks beside their configs and
    has to wonder about; and the fetch that matters is the one a user's client actually
    makes, which is the route rather than the builder.
    """
    await serving_node(
        client, session, name="has-configs", address="192.0.2.26",
        transport_name=file_transport,
        params={**AWG_PARAMS, "port": 51823,
                "tunnel_address": "10.26.0.1/24", "peer_tunnel_address": "10.26.0.2/24"},
    )
    user = (await client.post("/api/users", json={"nickname": "grisha"})).json()
    token = (
        await client.get(f"/api/users/{user['id']}/subscription")
    ).json()["url"].rsplit("/", 1)[-1]

    served = await anonymous.get(f"/sub/{token}", params={"format": "client-config-file"})
    assert served.status_code == 200
    assert subscriptions.EMPTY_ARCHIVE_NOTE_NAME not in names_in(served.content)

    # And the same token once nothing is serving: the link still works, the archive still
    # opens, and what it holds is the sentence rather than nothing at all.
    node_id = (await client.get("/api/nodes")).json()[0]["id"]
    await nodes.set_node_state(
        session, node_id=node_id, state=NodeState.DEGRADED, detail="taken out for the test"
    )

    empty = await anonymous.get(f"/sub/{token}", params={"format": "client-config-file"})

    assert empty.status_code == 200, empty.text
    assert empty.headers["content-type"] == "application/zip"
    assert names_in(empty.content) == [subscriptions.EMPTY_ARCHIVE_NOTE_NAME], (
        "a link that resolves to nothing still answers with an archive a user cannot "
        "tell from a download that went wrong"
    )


async def test_the_archive_is_byte_stable_across_builds(
    client, session, file_transport: str
) -> None:
    """No clock inside the response.

    ``ZipInfo`` defaults to the current time, which would make two refreshes of an
    unchanged fleet differ — noise that hides a real change, and a timestamp inside a
    file a user keeps.
    """
    await serving_node(
        client, session, name="stable", address="192.0.2.23",
        transport_name=file_transport,
        params={**AWG_PARAMS, "port": 51821,
                "tunnel_address": "10.23.0.1/24", "peer_tunnel_address": "10.23.0.2/24"},
    )
    user = (await client.post("/api/users", json={"nickname": "pyotr"})).json()
    handle = await users.get_user(session, user["id"])

    configs = await subscriptions.config_files_for(session, handle)
    assert configs
    assert subscriptions.archive_of(configs) == subscriptions.archive_of(configs)


def test_two_nodes_that_suggest_one_filename_both_survive() -> None:
    """A collision is resolved, never overwritten.

    Two names the same in a ZIP is an archive a client unpacks into one file, and the
    user is silently missing an exit — with a valid-looking download to show for it.
    Resolved with the node id rather than a counter, so the same fleet names the same
    file the same way on every refresh.
    """
    def config(node_id: str, content: str) -> ClientConfig:
        return ClientConfig(
            content=content,
            # Deliberately identical, which is realistic: a transport derives the name
            # from the node's operator-chosen label, and labels get truncated.
            filename="awg-leaf-node.conf",
            media_type="text/plain; charset=utf-8",
            display_label="leaf-node-one",
            country_label="Testland",
            node_id=node_id,
        )

    archive = subscriptions.archive_of(
        [
            config("11111111-1111-4111-8111-111111111111", "first"),
            config("22222222-2222-4222-8222-222222222222", "second"),
        ]
    )
    names = names_in(archive)
    assert len(names) == 2, names
    assert len(set(names)) == 2, names
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        assert sorted(bundle.read(name).decode() for name in names) == ["first", "second"]


async def test_the_endpoint_serves_both_shapes_behind_one_token(
    client, session, file_transport: str, anonymous
) -> None:
    """The route, end to end, without a booted stack.

    Duplicated deliberately with the acceptance scenario: this one runs on every
    `make test-control`, so a regression in the route is caught before anyone remembers
    to boot the e2e stack.
    """
    await serving_node(
        client, session, name="both-shapes", address="192.0.2.24",
        transport_name=file_transport,
        params={**AWG_PARAMS, "port": 51822,
                "tunnel_address": "10.24.0.1/24", "peer_tunnel_address": "10.24.0.2/24"},
    )
    user = (await client.post("/api/users", json={"nickname": "sveta"})).json()
    token = (
        await client.get(f"/api/users/{user['id']}/subscription")
    ).json()["url"].rsplit("/", 1)[-1]

    plain = await anonymous.get(f"/sub/{token}")
    assert plain.status_code == 200
    assert plain.headers["content-type"].startswith("text/plain")

    archived = await anonymous.get(f"/sub/{token}", params={"format": "client-config-file"})
    assert archived.status_code == 200
    assert archived.headers["content-type"] == "application/zip"
    assert names_in(archived.content), "the user's only transport produced no file"
    for response in (plain, archived):
        assert response.headers["cache-control"] == "no-store, max-age=0"


async def test_a_transport_with_no_user_facing_format_is_still_refused(
    client, session, monkeypatch, reality_params
) -> None:
    """The refusal item 27 narrowed but did not remove.

    No installed transport declares an empty format set, so the only way to assert the
    refusal is to present one. Worth asserting rather than assuming: the condition moved
    from "not a URI" to "nothing a user can consume", and if that move had gone one
    step too far, enabling such a transport would deliver a user a subscription that
    is quietly one node short.
    """
    created = await client.post(
        "/api/nodes",
        json={"name": "no-format", "address": "192.0.2.25", "location_label": "Testland"},
    )
    node_id = created.json()["id"]

    name = URI_TRANSPORTS[0]
    stripped = dict(discover())
    stripped[name] = replace(stripped[name], subscription_formats=frozenset())
    monkeypatch.setattr(nodes, "discover", lambda: stripped)

    with pytest.raises(NotDeliverable) as refused:
        await nodes.enable_transport(
            session, node_id=node_id, transport_name=name, params=reality_params
        )
    # The message has to tell the operator what is wrong with the transport, not just
    # that something was refused.
    assert "consume" in str(refused.value)


# --- what making a file transport user-facing exposed in the APPLY path -----
#
# Both of the following were found by running item 27's acceptance scenarios, not by
# reading. Both are recorded here rather than only fixed, because each is a class of
# failure rather than one instance.

async def test_a_users_private_material_never_reaches_a_server_config(
    client, session, file_transport: str
) -> None:
    """The server needs a user's PUBLIC half. It must never get the private one.

    ``render_for_node`` now hands each credential's whole client-scoped mapping to the
    renderer, because a WireGuard-family server authorises peers by their public keys
    and those live there. Handing it over whole is the right call — which parts belong
    in a server config is the transport's business, and picking them here would mean
    `control` recognising field names — but it makes this assertion load-bearing rather
    than decorative: the file this produces is pushed to a host that may be seized.
    """
    node_id = await serving_node(
        client, session, name="privacy", address="192.0.2.26",
        transport_name=file_transport,
        params={**AWG_PARAMS, "port": 51823,
                "tunnel_address": "10.26.0.1/24", "peer_tunnel_address": "10.26.0.2/24"},
    )
    await client.post("/api/users", json={"nickname": "ira"})

    stored = (await session.execute(select(Credential))).scalars().unique().all()
    assert stored, "no credential was minted, so this assertion would be vacuous"
    private_values = [
        str(value)
        for row in stored
        for name, value in json.loads(row.secrets).items()
        if "private" in name
    ]
    assert private_values, (
        "this transport's client material has no private half, so the leak this test "
        "guards against is not possible for it — pick a transport where it is"
    )

    node = await nodes.get_node(session, node_id)
    configs = await apply.render_for_node(session, node)
    whole = "\n".join(configs.values())
    for secret in private_values:
        assert secret not in whole, "a user's private key reached a node's config file"


@pytest.mark.parametrize("people", [2, 3])
async def test_every_user_on_one_wireguard_row_renders_at_an_address_of_their_own(
    client, session, file_transport: str, people: int
) -> None:
    """THE PINNED REFUSAL, INVERTED — M17, and the whole reason the milestone exists.

    This test used to assert the opposite: two users on one config-file transport
    could not be rendered at all, and the value of the test was that the refusal reached
    the operator as a NODE failure carrying the transport's own sentence rather than as
    a 500. That refusal is still right and is still pinned — by
    ``tests/control/test_every_user_holds_their_own_address.py``'s
    ``test_a_row_from_before_this_milestone_with_two_users_still_refuses``, which drives
    a row into the state the migration leaves one in and asserts both that it refuses and
    that the sentence carries no key material. It is no longer what `control` produces
    from any state a surface can create, because `control` no longer hands two people one
    address.

    What it asserts now is the charter's scale: every user on the row holds their own
    address, and the node's config routes each of them separately. A ``/32`` per peer is
    the transport's own arithmetic; what is checked here is that there are as many
    DISTINCT ones as there are people, because one repeated address is exactly the silent
    hijack ``AmbiguousPeerRoute`` exists to refuse.

    RED WITHOUT THE ALLOCATOR: remove the ``settle`` call from
    ``users.grant_everywhere`` and this fails at ``render_for_node`` with the old
    refusal, for every value of ``people``.
    """
    node_id = await serving_node(
        client, session, name="two-users", address="192.0.2.27",
        transport_name=file_transport,
        params={**AWG_PARAMS, "port": 51824,
                "tunnel_address": "10.27.0.1/24", "peer_tunnel_address": "10.27.0.2/24"},
    )
    for nickname in ("first", "second", "third")[:people]:
        assert (
            await client.post("/api/users", json={"nickname": nickname})
        ).status_code == 201

    node = await nodes.get_node(session, node_id)
    config = (await apply.render_for_node(session, node))[file_transport]

    routes = re.findall(r"AllowedIPs\s*=\s*(\S+)", config)
    assert len(routes) == people, config
    assert len(set(routes)) == people, (
        f"{people} users share {len(set(routes))} routes — the second one silently takes "
        "over the first's return path"
    )
    # Each of them is one host and not a range: AllowedIPs is the authorisation list as
    # well as the routing table, so a wide entry lets that user source traffic as anybody.
    for route in routes:
        assert route.endswith("/32"), route


async def test_each_users_own_file_names_the_address_the_node_authorises_for_them(
    client, session, file_transport: str
) -> None:
    """The two renders of one allocation, compared — M17.

    A node's config and a user's own file are produced by two different services, from
    the same row, and they answer two halves of one question: which address may this
    person send as, and which address is their device configured with. If those disagree
    the tunnel comes up, the handshake completes, and nothing moves — with every screen
    green, which is the failure M14 spent an evening on.

    So this walks BOTH builders: ``apply.render_for_node`` for the node and
    ``subscriptions.config_files_for`` for each person, and asserts the host in their
    file's ``Address`` is the host the node routes to them and to nobody else.

    RED WITH ONE BUILDER OVERLAID: overlay the allocation in ``render_for_node`` alone
    and this fails — the second user's file still carries the first's address, which is
    precisely the state that looks correct from every screen.
    """
    node_id = await serving_node(
        client, session, name="both-ends", address="192.0.2.29",
        transport_name=file_transport,
        params={**AWG_PARAMS, "port": 51825,
                "tunnel_address": "10.29.0.1/24", "peer_tunnel_address": "10.29.0.2/24"},
    )
    people = ["olya", "petya"]
    for nickname in people:
        assert (
            await client.post("/api/users", json={"nickname": nickname})
        ).status_code == 201

    node = await nodes.get_node(session, node_id)
    server = (await apply.render_for_node(session, node))[file_transport]
    authorised = {
        host_of(route) for route in re.findall(r"AllowedIPs\s*=\s*(\S+)", server)
    }

    theirs = set()
    for nickname in people:
        handle = (
            await session.execute(select(User).where(User.nickname == nickname))
        ).scalars().one()
        configs = await subscriptions.config_files_for(session, handle)
        assert len(configs) == 1, configs
        address = re.search(r"Address\s*=\s*(\S+)", configs[0].content).group(1)
        theirs.add(host_of(address))

    assert len(theirs) == len(people), "two users were handed one address"
    assert theirs == authorised, (
        "what the node authorises and what the devices are configured with are two "
        f"different sets: {sorted(authorised)} against {sorted(theirs)}"
    )


# --- a database restored with the wrong key (item 32's control half) ----------

async def test_an_unreadable_secret_is_a_sentence_the_operator_can_act_on(
    client, session, reality_params, monkeypatch
) -> None:
    """The moment this exists for: a restore onto a new host with the key mistyped.

    Everything about such a restore looks perfect — every user and node is listed — and
    the only thing wrong is one line in an env file. As an opaque 500 the available
    reading was "the restore lost my data", and the operator would go looking for another
    dump instead of fixing the key.

    Provoked by making the crypto layer refuse, which is exactly what a wrong key does:
    the raise happens inside SQLAlchemy's type decorator, on every read of an encrypted
    column, so there is no single call site to wrap and the handler is the right shape.
    """
    from control.app import crypto
    from control.app.models import base as models_base

    node_id = await serving_node(
        client, session, name="unreadable", address="192.0.2.28",
        transport_name=URI_TRANSPORTS[0], params=reality_params,
    )

    class WrongKeyBox:
        def decrypt(self, ciphertext: str) -> str:
            raise crypto.SecretUnreadable(
                "a stored secret could not be decrypted — HASHI_SECRET_KEY does not "
                "match the one this row was written with"
            )

        def encrypt(self, plaintext: str) -> str:
            return plaintext

        def digest(self, token: str) -> str:
            return token

    monkeypatch.setattr(models_base, "secret_box", WrongKeyBox)

    response = await client.post(f"/api/nodes/{node_id}/apply")

    assert response.status_code == 409, response.text
    body = response.json()
    assert body["error"]["code"] == "secrets_unreadable"
    message = body["error"]["message"]
    # The three things the operator needs: which setting, that the data is fine, and that
    # nothing was changed by the attempt.
    assert "HASHI_SECRET_KEY" in message
    assert "intact" in message
    assert "Nothing has been changed" in message
    # And nothing about the data itself.
    for leak in ("BEGIN", "gAAAA", "192.0.2.28"):
        assert leak not in message
