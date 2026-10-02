"""An apply repairs a daemon its ``up -d`` could not touch, and says what it measured — M31.

WHAT: three defects from the real-host field walk of 2026-10-02, each through the API:

      * M31.3 — a wg-family daemon whose peer was removed LIVE on the host. Its file is
        unchanged, so its digest and compose definition are too, and ``docker compose up
        -d`` leaves the container alone: every apply pushed the same file over a daemon
        serving none of its peers, answered 502 and said "Probe it in a minute: a slow
        host often comes up just after this wait ends". Only ``docker compose restart``
        repaired it.
      * M31.4 — ``GET /api/nodes`` read ``active`` with ``state_detail: null`` while the
        apply had just said "the finding stays on its row": the row's finding was not in
        the response.
      * M31.5 — ``serving_unmeasured: []`` for ``vless-reality``, which nothing but its
        held port can confirm, under a schema that said an empty list meant "pushed and
        measured".
WHY:  each is the panel or the API saying something the host does not bear out — the
      defect class M26 is about.
HOW:  against ``_serving_host.ServingHost``, which since M31.3 keeps a LIFE per container
      the way the engine does: ``up -d`` starts a new one only for a changed definition,
      ``docker compose restart`` always does. ``peers_return_on_restart`` is the field
      walk's leaf — a peer removed live, which only the daemon re-reading its own file
      puts back.

      Boundary: what a real ``awg`` does on restart was observed on the walk, not here.
"""

import pytest

from control.app.models import NodeState
from control.app.services import apply, health, nodes

from ._serving_host import PEERS_EMPTY, ServingHost
from .test_a_verdict_warns_and_never_empties_a_link import (
    AWG,
    AWG_PARAMS,
    ENTRY_ADDRESS,
    REALITY,
    WG_ADDRESS,
    a_node,
    a_user_token,
)


def reach(monkeypatch: pytest.MonkeyPatch, host: ServingHost) -> ServingHost:
    for module in (apply, health):
        monkeypatch.setattr(module, "NodeConnection", lambda target: host)
    return host


async def a_serving_wg_node(client, monkeypatch) -> tuple[ServingHost, str]:
    host = reach(monkeypatch, ServingHost(port=AWG_PARAMS["port"], protocol="udp"))
    node_id = await a_node(
        client, name="wg-leaf", address=WG_ADDRESS, transport=AWG, params=AWG_PARAMS
    )
    await a_user_token(client, "kolya")
    first = await client.post(f"/api/nodes/{node_id}/apply")
    assert first.status_code == 200, first.text
    assert host.restarted == [], "the premise: a healthy first apply restarts nothing"
    return host, node_id


async def reread(session, node_id: str):
    session.expire_all()
    return await nodes.get_node(session, node_id)


# --- M31.3: what up -d left alone, the apply restarts -------------------------------------


async def test_a_peer_removed_live_is_repaired_by_the_next_apply(
    client, session, monkeypatch
) -> None:
    """The field walk, step for step: serving, peer removed live, apply.

    Red before M31.3: 502, "Probe it in a minute", and nothing restarted — the container
    was on the same definition, so ``up -d`` never touched it.
    """
    host, node_id = await a_serving_wg_node(client, monkeypatch)
    host.peers = PEERS_EMPTY
    host.peers_return_on_restart = True

    applied = await client.post(f"/api/nodes/{node_id}/apply")

    assert applied.status_code == 200, applied.text
    assert host.restarted == [AWG], host.restarted
    assert applied.json()["restarted_to_serve"] == [AWG], applied.json()
    node = await reread(session, node_id)
    assert node.state == NodeState.ACTIVE
    assert node.last_probe_finding is None, (
        "the repair was measured serving, and still did not clear the finding"
    )


async def test_a_restart_that_does_not_help_says_waiting_will_not_either(
    client, session, monkeypatch
) -> None:
    """Restarted once, still refused: the 502 names what was tried and does not send the
    operator to wait for a slow host — the advice the walk read and found wrong."""
    host, node_id = await a_serving_wg_node(client, monkeypatch)
    host.peers = PEERS_EMPTY

    applied = await client.post(f"/api/nodes/{node_id}/apply")

    assert applied.status_code == 502, applied.text
    assert host.restarted == [AWG], "restarted more than once, or not at all"
    message = applied.json()["error"]["message"]
    assert "restarted amneziawg on the configuration it already had" in message, message
    assert "waiting will not help" in message, message
    assert "Probe it in a minute" not in message, message
    assert "stays in users' links" in message, message
    assert (await reread(session, node_id)).state == NodeState.ACTIVE


async def test_a_container_this_apply_just_started_is_given_time_not_a_restart(
    client, session, monkeypatch
) -> None:
    """The guard that keeps the repair from becoming walk 4's false red, made worse.

    A user added changes the rendered config, so ``up -d`` recreates the container; one
    that has not served by the end of the wait is a slow start, and restarting it would
    throw that start away. Not restarted, and the advice is still to probe in a minute.
    """
    host, node_id = await a_serving_wg_node(client, monkeypatch)
    await a_user_token(client, "masha")
    host.peers = PEERS_EMPTY

    applied = await client.post(f"/api/nodes/{node_id}/apply")

    assert applied.status_code == 502, applied.text
    assert host.restarted == [], "a container this apply had just recreated was restarted"
    assert "Probe it in a minute" in applied.json()["error"]["message"]


async def test_a_healthy_apply_restarts_nothing(client, monkeypatch) -> None:
    """Accept direction: a second apply over a node that serves leaves every container
    alone — a restart is a dropped session for every user on that transport."""
    host, node_id = await a_serving_wg_node(client, monkeypatch)

    applied = await client.post(f"/api/nodes/{node_id}/apply")

    assert applied.status_code == 200, applied.text
    assert host.restarted == []
    assert applied.json()["restarted_to_serve"] == []


# --- M31.4: the row's finding is in the API -------------------------------------------------


async def test_the_api_shows_the_finding_an_apply_left_on_the_row(
    client, monkeypatch
) -> None:
    """``state_detail`` is only ever a demotion's reason; a node left in service carries
    its verdict as ``last_probe_finding``, and the API now says it. Red before M31.4: the
    field was not in ``NodeResponse`` at all."""
    host, node_id = await a_serving_wg_node(client, monkeypatch)
    host.peers = PEERS_EMPTY
    said = (await client.post(f"/api/nodes/{node_id}/apply")).json()["error"]["message"]

    listed = {row["id"]: row for row in (await client.get("/api/nodes")).json()}
    row = listed[node_id]
    assert row["state"] == "active" and row["state_detail"] is None, row
    assert row["last_probe_finding"], f"the finding the apply announced is not shown: {row}"
    assert "not serving what we gave them" in row["last_probe_finding"], row
    assert row["last_probe_at"] is not None, row
    assert "not serving what we gave them" in said


async def test_a_node_with_nothing_found_says_so(client, monkeypatch) -> None:
    """Accept twin: a healthy apply clears the row, and the API says null rather than
    leaving a stale sentence."""
    _host, node_id = await a_serving_wg_node(client, monkeypatch)
    row = {r["id"]: r for r in (await client.get("/api/nodes")).json()}[node_id]
    assert row["last_probe_finding"] is None, row


# --- M31.5: a port-only confirmation is named -----------------------------------------------


async def test_a_transport_only_its_port_can_confirm_is_named_as_such(
    client, reality_params, monkeypatch
) -> None:
    """Red before M31.5: ``serving_unmeasured: []`` and nothing else, which the schema
    said meant "pushed and measured" — measured, for VLESS, by "something holds 443"."""
    reach(monkeypatch, ServingHost(port=reality_params["port"], protocol="tcp"))
    node_id = await a_node(
        client, name="entry", address=ENTRY_ADDRESS, transport=REALITY, params=reality_params
    )
    applied = await client.post(f"/api/nodes/{node_id}/apply")

    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["serving_unmeasured"] == [], body
    assert body["serving_port_only"] == [REALITY], body


async def test_a_transport_that_answered_its_own_question_is_not_port_only(
    client, monkeypatch
) -> None:
    """Accept twin: a wg node holding its peers was measured by its own check."""
    host, node_id = await a_serving_wg_node(client, monkeypatch)
    body = (await client.post(f"/api/nodes/{node_id}/apply")).json()
    assert body["serving_port_only"] == [], body
    assert AWG in host.asked



def test_the_panel_says_a_restart_happened_and_says_nothing_when_none_did() -> None:
    """The panel's half of M31.3: a restart drops sessions, so the toast names it."""
    from control.app.services import console

    plain = console.applied_toast("wg-leaf", [AWG])
    assert plain == f"config applied to wg-leaf — {AWG}"
    after = console.applied_toast("wg-leaf", [AWG], (AWG,))
    assert after.startswith(plain) and f"restarted {AWG}" in after, after
