"""A user whose material predates the declaration is named, not left to report it — M23.

WHAT: what happens to a credential that does not carry everything its transport now
      declares a consumer's material is — in the archive a user downloads, and on the
      screen the operator rotates from.
WHY:  the WireGuard family gained a per-pair pre-shared key, because every user on a
      node had been handed the node's own one: a single leaked config exposed the
      symmetric layer protecting everybody else's handshake, and revoking that person
      rotated nothing. New credentials carry it. **Every credential minted before that
      declaration does not**, and the renderer refuses to build a file for one rather
      than hand the shared key out again — correctly. The owner has exactly such a
      credential on their live leaf.

      Two things followed from that refusal and neither had an owner. A refusal inside
      the loop that builds a user's archive answers their WHOLE subscription with a 500,
      taking away every node they hold for the sake of one stale row. And nothing in the
      panel said a word about it: the refusal is written where only a user's client can
      read it, so the operator's first notice would be somebody reporting a download
      that gives them nothing.
HOW:  real Postgres, real encryption, real rendering. The pre-declaration credential is
      made by taking the value back out of a freshly minted one, which is exactly the
      shape of the rows already on the owner's node. No host is contacted.
"""

import io
import json
import zipfile

import pytest
from sqlalchemy import select

from control.app.models import Credential, NodeState
from control.app.services import console, keymaterial, nodes, rotation, subscriptions, users
from edge.registry import KeyScope, SubscriptionFormat, discover

NODE_ADDRESS = "192.0.2.95"
SECOND_ADDRESS = "192.0.2.96"
POOL_SIZE = 50

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


@pytest.fixture
def file_transport() -> str:
    """The transport a user receives as a file, resolved from the registry."""
    shapes = sorted(
        name
        for name, meta in discover().items()
        if SubscriptionFormat.CLIENT_CONFIG_FILE in meta.subscription_formats
        and meta.retired is None
    )
    if not shapes:
        pytest.skip("this image ships no transport a user receives as a file")
    return shapes[0]


@pytest.fixture
def a_client_scoped_value(file_transport: str) -> str:
    """One name this transport declares per consumer, other than the subject.

    Read off the declaration rather than written down, so this file names no protocol
    and no field — and skips loudly on an image whose file transport declares only the
    subject, where there would be nothing to take away.
    """
    names = sorted(
        spec.name
        for spec in discover()[file_transport].key_material
        if spec.scope is KeyScope.CLIENT and spec.name != "subject" and spec.secret
    )
    if not names:
        pytest.skip(f"{file_transport} declares no per-consumer secret to take away")
    # The LAST one, so this does not silently become a test about the private key: that
    # value is what the renderer has always refused on, and the value M23 added is the
    # one nothing in the panel knew about.
    return names[-1]


async def a_serving_node(client, session, *, name, address, transport_name, tunnel) -> str:
    created = await client.post(
        "/api/nodes",
        json={"name": name, "address": address, "location_label": "Testland"},
    )
    assert created.status_code == 201, created.text
    node_id = created.json()["id"]
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": transport_name,
            "params": {
                **AWG_PARAMS,
                "port": 51820,
                "tunnel_address": f"{tunnel}.1/24",
                "peer_tunnel_address": f"{tunnel}.2/24",
            },
            "pool_size": POOL_SIZE,
        },
    )
    assert enabled.status_code == 201, enabled.text
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    return enabled.json()["id"]


async def take_the_value_back_out(session, row_id: str, name: str) -> None:
    """Make every credential on one row look the way the owner's live ones do."""
    credentials = (
        await session.execute(
            select(Credential).where(Credential.node_transport_id == row_id)
        )
    ).scalars().unique().all()
    assert credentials, "nothing to make stale, so this test proves nothing"
    for credential in credentials:
        held = json.loads(credential.secrets)
        assert name in held, f"{name} was never minted, so taking it out proves nothing"
        del held[name]
        credential.secrets = json.dumps(held)
    await session.commit()


def names_in(archive: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        return bundle.namelist()


# --- the download ------------------------------------------------------------

async def test_one_stale_credential_does_not_take_away_a_users_other_nodes(
    client, session, file_transport: str, a_client_scoped_value: str, anonymous
) -> None:
    """The regression the renderer's refusal created, closed where the loop is.

    One user, two nodes, one of them holding material minted before the declaration.
    Their subscription must still hand over the node that works — a 500 here is every
    exit they have, lost to one row, and it reaches them as "the VPN is down".

    Red against the previous commit: the endpoint answers 500 and the archive does not
    exist at all.
    """
    stale_row = await a_serving_node(
        client, session, name="old-leaf", address=NODE_ADDRESS,
        transport_name=file_transport, tunnel="10.95.0",
    )
    await a_serving_node(
        client, session, name="new-leaf", address=SECOND_ADDRESS,
        transport_name=file_transport, tunnel="10.96.0",
    )
    created = await client.post("/api/users", json={"nickname": "kolya"})
    assert created.status_code < 300, created.text
    token = (
        await client.get(f"/api/users/{created.json()['id']}/subscription")
    ).json()["url"].rsplit("/", 1)[-1]
    await take_the_value_back_out(session, stale_row, a_client_scoped_value)

    response = await anonymous.get(f"/sub/{token}?format=client-config-file")

    assert response.status_code == 200, response.text
    names = names_in(response.content)
    assert len(names) == 1, names
    assert "new-leaf"[:6] in names[0] or names[0], names


async def test_the_stale_credential_itself_is_the_one_that_is_left_out(
    client, session, file_transport: str, a_client_scoped_value: str
) -> None:
    """And it is left out because of what it holds, not because of which node it is on.

    Asserted through the same predicate the endpoint uses, over the same builder — so
    "what is skipped" and "what cannot be rendered" cannot come to mean two things.
    """
    stale_row = await a_serving_node(
        client, session, name="old-leaf", address=NODE_ADDRESS,
        transport_name=file_transport, tunnel="10.95.0",
    )
    created = await client.post("/api/users", json={"nickname": "masha"})
    handle = await users.get_user(session, created.json()["id"])
    assert await subscriptions.config_files_for(session, handle)

    await take_the_value_back_out(session, stale_row, a_client_scoped_value)

    assert await subscriptions.config_files_for(session, handle) == []
    row = (
        await session.execute(
            select(Credential).where(Credential.node_transport_id == stale_row)
        )
    ).scalars().one()
    missing = keymaterial.missing_client_material(
        discover()[file_transport].key_material,
        {**json.loads(row.secrets), "subject": row.subject},
    )
    assert missing == [a_client_scoped_value], missing


# --- and the operator is told, on the screen that repairs it ------------------

async def test_the_keys_screen_counts_them_and_names_the_button_that_fixes_it(
    client, session, file_transport: str, a_client_scoped_value: str
) -> None:
    """The half that had no owner: the refusal is written where only a client reads it.

    The count is what the operator acts on and the button is on the same row, so the
    sentence has to be on that row rather than in a log — otherwise the first notice is
    a user reporting a download that gives them nothing.

    Red against the previous commit: the Keys screen says nothing at all about this.
    """
    stale_row = await a_serving_node(
        client, session, name="old-leaf", address=NODE_ADDRESS,
        transport_name=file_transport, tunnel="10.95.0",
    )
    for nickname in ("kolya", "masha"):
        assert (
            await client.post("/api/users", json={"nickname": nickname})
        ).status_code < 300
    await take_the_value_back_out(session, stale_row, a_client_scoped_value)

    table = await client.get("/panel/keys/table")

    assert table.status_code == 200, table.text
    assert "material for 2 of the users on this row was minted before" in table.text
    assert "rotate keys" in table.text, table.text
    # The count is the whole of what it says about people: no nickname, and nothing
    # about what is missing — a field name here would be this panel knowing which
    # protocol it is looking at, and would tell the operator nothing they can act on.
    for nickname in ("kolya", "masha"):
        assert nickname not in table.text, table.text
    assert a_client_scoped_value not in table.text, table.text


async def test_a_row_whose_users_all_carry_it_says_nothing(
    client, session, file_transport: str
) -> None:
    """The cell exists only when there is something to do about it.

    A standing note on every row is a note nobody reads, which is how the one row that
    needs attention stops being visible.
    """
    await a_serving_node(
        client, session, name="fresh-leaf", address=NODE_ADDRESS,
        transport_name=file_transport, tunnel="10.95.0",
    )
    assert (await client.post("/api/users", json={"nickname": "kolya"})).status_code < 300

    rows = await console.key_rows(session)

    assert [row.stale_material for row in rows] == [None], rows
    table = await client.get("/panel/keys/table")
    assert "was minted before" not in table.text, table.text


async def test_rotating_the_row_is_what_the_sentence_says_it_is(
    client, session, file_transport: str, a_client_scoped_value: str
) -> None:
    """The action the note points at actually repairs what the note is about.

    A message telling the operator to press a button that does not fix it is worse than
    no message: they press it, the note stays, and they stop trusting the screen. The
    rotation's own push fails here (this node has no SSH key) and the material is
    re-minted anyway, which is the documented order — the database changes, and the
    operator is told the push did not land.
    """
    stale_row = await a_serving_node(
        client, session, name="old-leaf", address=NODE_ADDRESS,
        transport_name=file_transport, tunnel="10.95.0",
    )
    created = await client.post("/api/users", json={"nickname": "kolya"})
    handle = await users.get_user(session, created.json()["id"])
    await take_the_value_back_out(session, stale_row, a_client_scoped_value)
    assert (await console.key_rows(session))[0].stale_material is not None

    await rotation.rotate_keys(session, node_transport_id=stale_row)

    assert (await console.key_rows(session))[0].stale_material is None
    # The rotation's push left the node degraded, which takes it out of every
    # subscription. Put it back in service, the way the operator would once the push
    # lands, and the file that could not be built exists again.
    row = await nodes.get_node_transport(session, stale_row)
    await nodes.set_node_state(session, node_id=row.node_id, state=NodeState.ACTIVE)
    configs = await subscriptions.config_files_for(session, handle)
    assert len(configs) == 1, [config.filename for config in configs]
