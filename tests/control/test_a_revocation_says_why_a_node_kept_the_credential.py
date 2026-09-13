"""A revocation that could not reach a node says why, per node — never in the node's words.

WHAT: the sentence an operator reads when a revocation left someone's credential live on a
      node, for the three reasons a node is not updated: its record names no resolver, so
      it cannot be rendered at all (M16); its configuration was refused before anything was
      pushed; or it could not be reached.
WHY:  M16's review. A node that dials a hop and has no resolver cannot be rendered, so a
      revocation's re-push never reaches it and the revoked user keeps working there. The
      banner said one thing about every failure — the credential is live "until they are
      reachable. Apply those nodes again" — which for this refusal is wrong twice: it is not
      about reachability, and applying again changes nothing until the record does.

      A node's own reason cannot simply be printed instead. A refusal's message can carry
      the upstream checker's output, and that output is known to quote the node's private
      key (docs/tracker/M9/carry-over.md) — off the screen today only because a
      300-character cut happens to fall short of it. So the banner is composed from each
      node's NAME and one fixed sentence per kind of failure, and nothing else; the tests
      below plant the node's real key where a message would carry it, and hunt for it.
HOW:  real Postgres, real rendering, a real revocation through the service and through the
      panel's route. No node is contacted: every failure here happens before a connection
      opens — the unreachable node has no SSH key, which is how the neighbouring revocation
      tests make one, and the refusing checker is replaced for the length of one test.
"""

import html
import types

import pytest
from sqlalchemy import select

from control.app.models import NodeState, NodeTransport
from control.app.services import apply, nodes, revocation
from control.app.services.apply import NotUpdated

HOP_TRANSPORT = "amneziawg"
FRIEND_TRANSPORT = "vless-reality"

# RFC 5737 documentation addresses, one per node.
ENTRY, LEAF, REFUSING, QUIET = "192.0.2.20", "192.0.2.10", "192.0.2.30", "192.0.2.40"
ENTRY_TUNNEL, LEAF_TUNNEL = "10.44.0.1/24", "10.44.0.2/24"

# How much of a key is enough to count as having leaked it. Short enough that a key cut in
# two by a wrap or a truncation is still caught, long enough that no English word in the
# banner could match by chance.
FRAGMENT = 12


@pytest.fixture
def hop_params() -> dict[str, object]:
    """One hop end's operator-supplied half, as in the entry-node file."""
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


def fragments(secret: str) -> list[str]:
    """Every run of ``FRAGMENT`` characters in ``secret`` — what a partial leak looks like."""
    return [secret[i : i + FRAGMENT] for i in range(len(secret) - FRAGMENT + 1)]


async def a_node(client, name: str, address: str) -> str:
    created = await client.post(
        "/api/nodes", json={"name": name, "address": address, "location_label": "Testland"}
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def serving_friends(client, session, node_id: str, reality_params) -> None:
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": FRIEND_TRANSPORT, "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)


async def a_revocation_that_cannot_finish(
    client, session, reality_params, hop_params, monkeypatch
) -> dict[str, str]:
    """Three serving nodes one friend holds a credential on, each failing its own way.

    ``entry-ru`` dials a hop and has no resolver — the state migration 0005 leaves every
    existing entry in. ``refused-1``'s configuration is refused by a checker whose output
    quotes that node's own private key, which is the shape the M9 carry-over measured.
    ``quiet-1`` has no SSH key. The friend is created last: that is the order that mints a
    credential on every serving node.
    """
    entry = await a_node(client, "entry-ru", ENTRY)
    await serving_friends(client, session, entry, reality_params)
    leaf = await a_node(client, "leaf-nl", LEAF)
    established = await client.post(
        "/api/hops",
        json={
            "entry_node_id": entry,
            "leaf_node_id": leaf,
            "transport_name": HOP_TRANSPORT,
            "entry_params": {
                **hop_params,
                "tunnel_address": ENTRY_TUNNEL,
                "peer_tunnel_address": LEAF_TUNNEL,
            },
            "leaf_params": {
                **hop_params,
                "tunnel_address": LEAF_TUNNEL,
                "peer_tunnel_address": ENTRY_TUNNEL,
            },
        },
    )
    assert established.status_code == 201, established.text

    refusing = await a_node(client, "refused-1", REFUSING)
    await serving_friends(client, session, refusing, reality_params)
    quiet = await a_node(client, "quiet-1", QUIET)
    await serving_friends(client, session, quiet, reality_params)

    row = (
        await session.execute(
            select(NodeTransport).where(NodeTransport.node_id == refusing)
        )
    ).scalars().one()
    secret = nodes.render_params(row)["private_key"]

    def the_checker(config: str, *, config_format):
        if secret in config:
            # What Xray's own checker prints about a Reality key, with the key FIRST so the
            # 300-character cut in ``apply.validate_before_push`` keeps all of it.
            return types.SimpleNamespace(
                available=True, ok=False, output=f'invalid "privateKey": {secret}'
            )
        return types.SimpleNamespace(available=True, ok=True, output="")

    monkeypatch.setattr(apply.checker, "validate", the_checker)

    friend = await client.post("/api/friends", json={"nickname": "kolya"})
    assert friend.status_code < 300, friend.text
    return {
        "entry": entry,
        "refusing": refusing,
        "quiet": quiet,
        "friend": friend.json()["id"],
        "secret": secret,
    }


# --- what each node is said to need -------------------------------------------------

async def test_each_node_is_named_with_what_is_actually_wrong_with_it(
    client, session, reality_params, hop_params, monkeypatch
) -> None:
    """Three nodes, three kinds, three different instructions — and the reachability
    sentence only where reachability is the problem."""
    fleet = await a_revocation_that_cannot_finish(
        client, session, reality_params, hop_params, monkeypatch
    )

    outcome = await revocation.revoke_friend(session, friend_id=fleet["friend"])

    assert outcome.why_failed == {
        fleet["entry"]: NotUpdated.NO_RESOLVER,
        fleet["refusing"]: NotUpdated.REFUSED,
        fleet["quiet"]: NotUpdated.UNREACHED,
    }
    summary = outcome.summary()
    assert "'entry-ru' has no resolver on its record" in summary
    assert "set its resolver on the Nodes screen, then apply it" in summary
    assert "'refused-1' could not be given a configuration" in summary
    assert "'quiet-1' could not be reached" in summary
    assert summary.count("could not be reached") == 1, summary


async def test_a_node_left_with_nothing_enabled_is_reported_as_refused_not_unreached(
    client, session, reality_params
) -> None:
    """The fourth way a node keeps a credential, and the one M18.1 created — M18.1.

    Withdrawing a transport does not take back a minted credential and does not touch the
    host: the daemon goes on serving the config it was last given, and everybody in it is
    still authorised. Revoke the last friend on a node whose only row was withdrawn and
    the re-push has nothing to render.

    That case used to push an empty compose file, be told ``services must be a mapping``,
    and be reported as UNREACHED — "apply it again once it can be", about a node that is
    up and that no retry will change. It is REFUSED: nothing was pushed and nothing but a
    change to the record will alter that. The credential is still live on it either way,
    which is why the kind has to be right rather than merely non-fatal.
    """
    node_id = await a_node(client, "withdrawn-1", LEAF)
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": FRIEND_TRANSPORT, "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    friend = await client.post("/api/friends", json={"nickname": "kolya"})
    assert friend.status_code < 300, friend.text
    withdrawn = await client.post(
        f"/api/transports/{enabled.json()['id']}/state", json={"enabled": False}
    )
    assert withdrawn.status_code == 200, withdrawn.text

    outcome = await revocation.revoke_friend(session, friend_id=friend.json()["id"])

    assert outcome.why_failed == {node_id: NotUpdated.REFUSED}, outcome.why_failed
    summary = outcome.summary()
    assert "'withdrawn-1' could not be given a configuration" in summary, summary
    assert "could not be reached" not in summary, summary


async def test_the_sentence_cannot_carry_what_a_nodes_refusal_carries(
    client, session, reality_params, hop_params, monkeypatch
) -> None:
    """The premise first, then the claim — and neither ever prints the key.

    The premise is what makes the claim worth anything: this node's own refusal really
    does carry its private key, whole. ``pytest.fail`` with a label rather than ``assert``,
    because an assertion's failure message would print the value into the CI log.
    """
    fleet = await a_revocation_that_cannot_finish(
        client, session, reality_params, hop_params, monkeypatch
    )

    outcome = await revocation.revoke_friend(session, friend_id=fleet["friend"])

    if fleet["secret"] not in outcome.nodes_failed[fleet["refusing"]]:
        pytest.fail(
            "premise failed: the refusal did not carry the node's key, so nothing is proven"
        )
    summary = outcome.summary()
    for fragment in fragments(fleet["secret"]):
        if fragment in summary:
            pytest.fail("the revocation's summary carries part of a node's private key")


async def test_the_banner_names_each_node_and_carries_none_of_its_key(
    client, session, reality_params, hop_params, monkeypatch
) -> None:
    """The same, on the screen the operator actually reads — raw and unescaped, because
    the panel escapes its text and a raw search walks straight past an escaped value."""
    fleet = await a_revocation_that_cannot_finish(
        client, session, reality_params, hop_params, monkeypatch
    )

    response = await client.post(
        f"/panel/friends/{fleet['friend']}/revoke", headers={"HX-Request": "true"}
    )

    assert response.status_code == 200
    seen = html.unescape(response.text)
    assert "'entry-ru' has no resolver on its record" in seen
    assert "'refused-1' could not be given a configuration" in seen
    assert "'quiet-1' could not be reached" in seen
    for text in (response.text, seen):
        for fragment in fragments(fleet["secret"]):
            if fragment in text:
                pytest.fail("the revocation banner carries part of a node's private key")


# --- and it is made of nothing else --------------------------------------------------

def test_the_banner_is_made_of_node_names_and_fixed_sentences_and_nothing_else() -> None:
    """The whole sentence, literally — which is what proves nothing else is in it.

    Every message below carries a planted value, and the expected sentence has no place
    for any of them: a composition that let one node's message through would not equal
    this. Acceptance judges this wording; it is written out, not derived.
    """
    planted = "PLANTED-private-key-0123456789abcdef"
    outcome = revocation.RevocationOutcome(
        friend_id="f",
        nodes_updated=["n0"],
        nodes_failed={"n1": planted, "n2": f"refused: {planted}", "n3": f"ssh: {planted}"},
        why_failed={
            "n1": NotUpdated.NO_RESOLVER,
            "n2": NotUpdated.REFUSED,
            "n3": NotUpdated.UNREACHED,
        },
        names={"n1": "entry-ru", "n2": "refused-1", "n3": "quiet-1"},
    )

    assert outcome.summary() == (
        "access withdrawn in the database and on 1 node(s), but 3 node(s) could NOT be "
        "updated and the credential is still live on each until it is: "
        "'entry-ru' has no resolver on its record, so its configuration cannot be "
        "rendered and retrying will not change that — set its resolver on the Nodes "
        "screen, then apply it; "
        "'quiet-1' could not be reached — apply it again from the Nodes screen once it "
        "can be; "
        "'refused-1' could not be given a configuration: it was refused before anything "
        "was pushed, and retrying will not change that — apply it from the Nodes screen "
        "to read why."
    )
    assert revocation.RevocationOutcome(friend_id="f", nodes_updated=["a", "b"]).summary() == (
        "access withdrawn everywhere; 2 node(s) updated"
    )
