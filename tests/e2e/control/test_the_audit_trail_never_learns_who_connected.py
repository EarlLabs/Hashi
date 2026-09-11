"""The audit trail holds no token, no subscription URL, and nothing about a fetch.

WHAT: drives the real control plane — add a user, add a node, enable a protocol,
      apply, revoke — then reads the trail straight out of Postgres, and finally
      fetches a real subscription the way a friend's client does and requires the
      trail not to have grown by a single row.
WHY:  M10's "done when": *"if an audit trail exists, it holds no token, no
      subscription URL and nothing about who connected."* The trail is the one durable
      record this project adds that names people and times, and the way it turns into
      the connection log the charter says is absent is not a decision anybody makes —
      it is a ``details`` column, or one write on the delivery path. The second is what
      this file is named after, and it is asserted the strong way: not "no row mentions
      a token" but **no row at all**, because a row saying only "something happened" at
      the second a friend refreshed is already the record.
HOW:  over real HTTP against the booted stack, and over ``psql`` inside the database
      container for the reading — deliberately, and still deliberately now that M10.4
      has given the trail a screen: the claim here is about what is ON DISK, not about
      what a page renders, and a scenario that read the screen would be blind to a row
      the screen does not show. What the screen says is
      ``test_the_audit_screen_names_what_changed_in_plain_words``.

      The instrument proves itself inside the scenario. Every count below is taken with
      the same query, and the operator's own actions demonstrably move it — so when the
      subscription fetch does not, that is a fact about the fetch rather than about a
      query that reads nothing.

Boundary: real control, postgres, caddy. No node is contacted (the apply here fails on
purpose and the trail's treatment of that failure is part of the claim), no tunnel
exists, and nothing here says anything about a real network.
"""

import uuid

import pytest

OPERATOR = {"username": "owner", "password": "e2e-operator-password"}

# Every column the trail is allowed to have. The same whitelist the zone's unit tests
# assert against the model, asserted here against the SCHEMA THAT IS ACTUALLY
# DEPLOYED — a migration that added a column the model does not have would pass there
# and fail here, and a blob is how this table would acquire a token.
PERMITTED_COLUMNS = {"id", "at", "action", "first_label", "second_label"}

# Every action the vocabulary declares. Written out rather than imported, because
# nothing in this directory imports the application — a scenario that reads the answer
# out of the code under test is a scenario that agrees with it by construction. The
# duplication is the point: a thirteenth action has to be written down twice, once in
# the enum and once here, and the second time is where somebody asks what it records.
PERMITTED_ACTIONS = {
    "friend-added",
    "friend-revoked",
    "node-added",
    "node-state-changed",
    "node-applied",
    "transport-enabled",
    "transport-offered",
    "transport-withdrawn",
    "hop-established",
    "hop-dissolved",
    "keys-rotated",
    "params-replaced",
}


@pytest.fixture
def unique() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture
async def operator(client):
    response = await client.post("/panel/login", data=OPERATOR)
    assert response.status_code == 303, (
        f"the operator could not log in ({response.status_code}) — check "
        "deploy/e2e.env against deploy/docker-compose.e2e.yml"
    )
    return client


def query(exec_in, sql: str) -> str:
    """One SELECT inside the database container, as plain text.

    The credentials come from the container's own environment rather than from this
    file: they are the same variables the service was started with, so this cannot
    drift away from the stack it is reading.
    """
    result = exec_in(
        "db",
        "sh",
        "-c",
        f'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "{sql}"',
    )
    assert result.returncode == 0, f"psql failed: {result.stdout}\n{result.stderr}"
    return result.stdout.strip()


def trail_size(exec_in) -> int:
    return int(query(exec_in, "select count(*) from audit_entries"))


def trail_text(exec_in) -> str:
    """Every label and every action in the table, as one blob to search."""
    return query(
        exec_in,
        "select coalesce(action,'') || '|' || coalesce(first_label,'') || '|' || "
        "coalesce(second_label,'') from audit_entries",
    )


async def test_the_trail_records_what_the_operator_did_and_nothing_a_friend_did(
    operator, client, exec_in, unique: str
) -> None:
    """One walk of the product, then the two questions M10 asks of the answer."""
    columns = query(
        exec_in,
        "select column_name from information_schema.columns "
        "where table_name = 'audit_entries' order by column_name",
    ).split()
    assert set(columns) == PERMITTED_COLUMNS, (
        "the deployed audit table's columns are not the ones decision 8 permits — a "
        "free-text or JSON column here is how this record grows a token without "
        f"anybody deciding to: {columns}"
    )

    before = trail_size(exec_in)

    # --- the operator changes things ----------------------------------------
    node = await operator.post(
        "/api/nodes",
        json={
            "name": f"leaf-{unique}",
            "address": "192.0.2.10",
            "location_label": f"Testland-{unique}",
        },
    )
    assert node.status_code == 201, node.text
    node_id = node.json()["id"]

    enabled = await operator.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": "vless-reality",
            "params": {
                "port": 8443,
                "decoy_host": "www.example.com",
                "decoy_port": 443,
                "server_names": ["www.example.com"],
            },
        },
    )
    assert enabled.status_code == 201, enabled.text
    assert (
        await operator.post(f"/api/nodes/{node_id}/state", json={"state": "active"})
    ).status_code == 200

    friend = await operator.post("/api/friends", json={"nickname": f"kolya-{unique}"})
    assert friend.status_code == 201, friend.text
    friend_id = friend.json()["id"]

    url = (await operator.get(f"/api/friends/{friend_id}/subscription")).json()["url"]
    token = url.rsplit("/", 1)[-1]

    # A second user, withdrawn again — so the walk covers the entry that names somebody
    # who no longer exists in the fleet, which is the trail's one genuine marginal
    # disclosure over the rows it describes, and the reason retention is measured in
    # days. The first user stays live, because the fetch below needs a real link.
    withdrawn = await operator.post(
        "/api/friends", json={"nickname": f"masha-{unique}"}
    )
    assert withdrawn.status_code == 201, withdrawn.text
    revoked = await operator.post(
        f"/api/friends/{withdrawn.json()['id']}/revoke"
    )
    assert revoked.status_code == 200, revoked.text

    # An apply that cannot reach the host: the node in this stack answers nothing. It
    # is here because the failure path is where a trail grows a reason — the node is
    # marked degraded with a diagnostic on it, and that diagnostic can come from a
    # remote host. The state change is recorded; the sentence is not.
    await operator.post(f"/api/nodes/{node_id}/apply")

    after_operator = trail_size(exec_in)
    assert after_operator > before, (
        "the operator added a node, a protocol and a user and the trail did not grow — "
        "either nothing is being recorded or this query is reading the wrong table, and "
        "the assertion below would then pass without meaning anything"
    )

    # --- the trail holds none of the three things M10 names -----------------
    recorded = trail_text(exec_in)
    assert token not in recorded, "a subscription token reached the audit trail"
    assert url not in recorded, "a subscription URL reached the audit trail"
    assert "/sub/" not in recorded and "http" not in recorded
    # Every address this stack's scenarios give a node is in the reserved documentation
    # range, so one prefix covers the fleet rather than only the node added above.
    assert "192.0.2." not in recorded, "a node address reached the audit trail"

    # And every action in the table is one somebody declared. This is the half a label
    # check cannot make: a row saying nothing but "subscription-fetched" against a time
    # carries no label at all and is still the record this project must not keep.
    actions = set(query(exec_in, "select distinct action from audit_entries").split())
    assert actions <= PERMITTED_ACTIONS, (
        f"the trail holds an action nobody declared: {sorted(actions - PERMITTED_ACTIONS)}"
    )

    # --- and the delivery endpoint writes nothing at all --------------------
    served = await client.get(f"/sub/{token}")
    assert served.status_code == 200, "the premise: a real subscription was served"
    assert (await client.get(f"/sub/{token}")).status_code == 200
    assert (await client.get("/sub/a-token-that-does-not-exist-at-all")).status_code == 404

    assert trail_size(exec_in) == after_operator, (
        "fetching a subscription wrote to the audit trail. /sub/{token} writes nothing "
        "there, ever — a row against a time is a record that a person used the "
        "service, which is exactly the record this project exists not to keep"
    )
