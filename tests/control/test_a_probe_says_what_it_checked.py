"""What the probe measures, and what it tells the operator it measured — M22.

WHAT: the control-plane half. That the port expectation handed to `edge` is built from
      the operator's own parameter and the transport's own declaration and from nothing
      else; that a node whose transport holds no socket is not reported as serving; that
      a node which does is; and that the sentence the operator reads says which of the
      three answers it is — listening, running-but-unchecked, or not serving.
WHY:  acceptance, 2026-09-13. The panel said *"realhost is serving amneziawg,
      vless-ws-tls"* six times about a host where one of the two was exiting 23 every
      second on a missing certificate with nothing on its port. The verb was the defect
      as much as the measurement was: "serving" is read as "working", and this is the one
      instrument the operator has for that question.
HOW:  against a fake host at the SHELL, so the real ``running_containers``, the real
      socket parser and the real summary all run — the only thing invented is the node's
      two answers. Both directions every time: a probe that calls a working node broken
      is the same defect as one that calls a broken node working (M19's convention).

      The port is the fixture's own (``reality_params``), never a literal here: what a
      node listens on belongs to a node record, and a test that wrote the number down
      would pass the day the fixture changed and the product stopped agreeing with it.
"""

import pytest
import yaml

from control.app.models import NodeState
from control.app.services import apply, console, health
from edge.health import listening
from edge.registry import Layer4

from .conftest import GENERATED_SSH_KEY

# RFC 5737 documentation address, as everywhere in this zone. Never dialled: the
# connection is replaced.
NODE_ADDRESS = "192.0.2.10"

TRANSPORT = "vless-reality"

# A node's listening table as ``ss -l -n -t -u`` prints it. Only sshd, which every node
# this code is talking to has — the reading is taken over it.
SSH_ONLY = """Netid State  Recv-Q Send-Q    Local Address:Port  Peer Address:PortProcess
tcp   LISTEN 0      4096            0.0.0.0:22         0.0.0.0:*
tcp   LISTEN 0      4096               [::]:22            [::]:*
"""


def bound(port: int, protocol: str = "tcp") -> str:
    """The same table with one more socket on it — the transport's own."""
    state = "LISTEN" if protocol == "tcp" else "UNCONN"
    return SSH_ONLY + f"{protocol}   {state} 0      4096            0.0.0.0:{port}      0.0.0.0:*\n"


class _FakeHost:
    """A node that answers the two questions a probe asks, and holds the files it was sent.

    ``sockets`` is raw ``ss`` output so the product's own parser runs, or ``None`` for a
    host without the tool. ``restarting`` is the state the milestone is about, modelled
    the way the engine really answers it: ``Running: true`` and ``Restarting: true`` at
    the same instant.
    """

    learned_host_key = None

    def __init__(
        self,
        *,
        sockets: str | None = SSH_ONLY,
        restarting: tuple[str, ...] = (),
    ) -> None:
        self.files: dict[str, str] = {}
        self.services: list[str] = []
        self.sockets = sockets
        self.restarting = restarting

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info) -> bool:
        return False

    async def run(self, command: str, *, check: bool = True):
        from edge.bootstrap.ssh import CommandResult

        if "docker compose up -d" in command:
            from edge.bootstrap import node_stack

            self.services = list(
                yaml.safe_load(self.files[node_stack.COMPOSE_PATH])["services"]
            )
            return CommandResult(exit_status=0, stdout="", stderr="")

        if "docker inspect" in command:
            from edge.bootstrap import node_stack

            definitions = yaml.safe_load(self.files[node_stack.COMPOSE_PATH])["services"]
            lines = [
                f"{service}"
                f"|{definitions[service]['labels'][node_stack.CONFIG_DIGEST_LABEL]}"
                f"|true"
                f"|{'true' if service in self.restarting else 'false'}"
                for service in self.services
            ]
            return CommandResult(exit_status=0, stdout="\n".join(lines) + "\n", stderr="")

        if command == listening.LISTENING_SOCKETS:
            if self.sockets is None:
                return CommandResult(exit_status=127, stdout="", stderr="ss: not found")
            return CommandResult(exit_status=0, stdout=self.sockets, stderr="")

        if "docker version" in command:
            return CommandResult(exit_status=0, stdout="27.1.1\n", stderr="")

        return CommandResult(exit_status=0, stdout="", stderr="")

    async def write_file(self, path: str, content: str, *, mode: int = 0o600) -> None:
        self.files[path] = content

    async def read_file(self, path: str) -> str | None:
        return self.files.get(path)



class _UnreachableHost:
    """A node that cannot be dialled at all — the arm most likely to start guessing."""

    learned_host_key = None

    async def __aenter__(self):
        from edge.bootstrap import NodeUnreachable

        raise NodeUnreachable("this node's address could not be resolved")

    async def __aexit__(self, *_exc_info) -> bool:
        return False


def host_for(monkeypatch, host) -> object:
    """Point every node connection this control plane opens at one fake host.

    Both modules, because they import the class rather than the package: the apply that
    places the configs and the probe that reads them back have to reach the SAME host.
    """
    for module in (apply, health):
        monkeypatch.setattr(module, "NodeConnection", lambda target: host)
    return host


async def an_applied_node(client, session, params, *, transport=TRANSPORT) -> str:
    """One node with one transport, applied — so there is something to probe."""
    from control.app.services import nodes

    node_id = (
        await client.post(
            "/api/nodes",
            json={
                "name": "leaf-nl",
                "address": NODE_ADDRESS,
                "location_label": "Netherlands",
                "ssh_host": NODE_ADDRESS,
                "ssh_port": 22,
                "ssh_private_key": GENERATED_SSH_KEY,
            },
        )
    ).json()["id"]
    await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": transport, "params": params},
    )
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    await client.post(f"/api/nodes/{node_id}/apply")
    return node_id


# --- what `control` hands `edge` ---------------------------------------------------


async def test_the_port_expectation_is_the_operators_own_value(
    client, session, reality_params, monkeypatch
) -> None:
    """Built from the row's parameter and the transport's declaration, and nothing else.

    Not from a table in this zone, and not from the transport's name: `control` reads a
    port the operator typed and a ``listens_on`` the package declared. A fourth transport
    added tomorrow is probed by arriving.
    """
    from control.app.services import nodes

    host_for(monkeypatch, _FakeHost())
    node_id = await an_applied_node(client, session, reality_params)
    node = await nodes.get_node(session, node_id)

    listeners = await apply.placed_listeners(session, node)

    assert set(listeners) == {TRANSPORT}
    assert listeners[TRANSPORT].port == reality_params["port"]
    assert listeners[TRANSPORT].protocols == {Layer4.TCP}


async def test_a_row_whose_port_cannot_be_resolved_is_left_out(
    client, session, reality_params, monkeypatch
) -> None:
    """A row nothing can be said about produces no expectation, rather than a guess.

    Inventing one would report a node as silent on a port it was never given, which is
    the same defect as reporting a broken node as serving — one direction over.
    """
    from control.app.models import NodeTransport
    from control.app.services import nodes

    host_for(monkeypatch, _FakeHost())
    node_id = await an_applied_node(client, session, reality_params)

    from sqlalchemy import select

    row = (
        await session.execute(select(NodeTransport).where(NodeTransport.node_id == node_id))
    ).scalars().unique().one()
    # Written straight onto the row rather than through the API, which would refuse it:
    # what is modelled is a row this control plane cannot make sense of, however it got
    # that way — a transport that names its port something else, a shape pydantic no
    # longer produces, a value from a future migration.
    row.params = {key: value for key, value in row.params.items() if key != "port"}
    await session.flush()

    node = await nodes.get_node(session, node_id)

    assert await apply.placed_listeners(session, node) == {}


# --- what the node then reports ----------------------------------------------------


async def test_a_transport_holding_nothing_is_not_reported_as_serving(
    client, session, reality_params, monkeypatch
) -> None:
    """The acceptance finding, through the endpoint that produced it.

    The container is up on exactly the config we pushed. Nothing is on its port. Before
    M22 this node answered ``healthy: true`` and the panel said it was serving.
    """
    host_for(monkeypatch, _FakeHost(sockets=SSH_ONLY))
    node_id = await an_applied_node(client, session, reality_params)

    answer = (await client.get(f"/api/nodes/{node_id}/health")).json()

    assert answer["healthy"] is False, (
        "a node whose transport holds no socket at all reported healthy — the operator "
        "reads that as 'this node is working'"
    )
    assert answer["not_listening"] == [TRANSPORT]
    assert answer["listening"] == []


async def test_a_transport_holding_its_port_is_reported_as_serving(
    client, session, reality_params, monkeypatch
) -> None:
    """The accept case. Without it the check above could pass by refusing every node."""
    host_for(monkeypatch, _FakeHost(sockets=bound(reality_params["port"])))
    node_id = await an_applied_node(client, session, reality_params)

    answer = (await client.get(f"/api/nodes/{node_id}/health")).json()

    assert answer["healthy"] is True, answer
    assert answer["listening"] == [TRANSPORT]
    assert answer["not_listening"] == []


async def test_a_crash_looping_transport_is_reported_as_crash_looping(
    client, session, reality_params, monkeypatch
) -> None:
    """The other half, and the state the field host was actually in."""
    host_for(
        monkeypatch,
        _FakeHost(sockets=SSH_ONLY, restarting=(TRANSPORT,)),
    )
    node_id = await an_applied_node(client, session, reality_params)

    answer = (await client.get(f"/api/nodes/{node_id}/health")).json()

    assert answer["healthy"] is False
    assert answer["restarting"] == [TRANSPORT]
    assert answer["running"] == []
    assert answer["missing"] == [], (
        "a crash loop is reported as a transport that was never pushed, which sends the "
        "operator to apply the same configuration again"
    )


async def test_a_host_that_cannot_be_asked_is_not_reported_as_serving_nothing(
    client, session, reality_params, monkeypatch
) -> None:
    """"Nobody could ask" is not "nothing is listening".

    A host without the tool is one node's missing package, and reporting it as an outage
    would be the confident wrong answer this milestone exists to remove — pointed the
    other way.
    """
    host_for(monkeypatch, _FakeHost(sockets=None))
    node_id = await an_applied_node(client, session, reality_params)

    answer = (await client.get(f"/api/nodes/{node_id}/health")).json()

    assert answer["not_listening"] == []
    assert answer["listening"] == []
    assert answer["healthy"] is True


# --- and what the operator reads ---------------------------------------------------


async def test_an_unreachable_node_is_reported_as_nothing_at_all(
    client, session, reality_params, monkeypatch
) -> None:
    """A node that never answered told us nothing, and nothing is what it must report.

    The other three lists are already empty here for a reason that predates this
    milestone; these two are new and sit on the arm where "what we expected to find" is
    already in scope, one variable away from being reported as a finding.
    """
    host_for(monkeypatch, _FakeHost())
    node_id = await an_applied_node(client, session, reality_params)
    host_for(monkeypatch, _UnreachableHost())

    answer = (await client.get(f"/api/nodes/{node_id}/health")).json()

    assert answer["reachable"] is False
    assert answer["restarting"] == [], (
        "a node nobody could reach is reported as crash-looping, which is a finding "
        "about containers nobody looked at"
    )
    assert answer["listening"] == []
    assert answer["not_listening"] == []
    # And the one list that IS filled from what we expected, which is legitimate and is
    # why the three above are worth asserting: "we expected these and saw none of them".
    assert answer["missing"] == [TRANSPORT]


async def test_the_not_listening_sentence_says_nobody_can_reach_it(
    client, session, reality_params, monkeypatch
) -> None:
    """The failing answer has to say what the fault IS, not only that there is one.

    "nothing listening on the port for: x" is the reason; on its own it reads as a
    diagnostic about our own check. What the operator needs is the consequence — the
    container is up and there is nothing on that node for anyone to arrive at.
    """
    host_for(monkeypatch, _FakeHost(sockets=SSH_ONLY))
    node_id = await an_applied_node(client, session, reality_params)

    result = await health.check_node(session, node_id=node_id)
    summary = console.health_summary("leaf-nl", result)

    assert "nothing holds the port" in summary, summary
    assert "nothing on the node for anyone to reach" in summary, summary


@pytest.mark.parametrize(
    "sockets,expected,forbidden",
    [
        pytest.param(None, "whose port was not checked", "is listening for", id="unchecked"),
        pytest.param("bound", "is listening for", "was not checked", id="listening"),
    ],
)
async def test_the_sentence_says_how_much_was_established(
    client, session, reality_params, monkeypatch, sockets, expected, forbidden
) -> None:
    """A weaker measurement gets a weaker verb — M22.2.

    One sentence for both would mean the weaker of the two, always, and the operator
    would have no way to tell a node whose port was checked from one whose was not.
    """
    table = bound(reality_params["port"]) if sockets == "bound" else None
    host_for(monkeypatch, _FakeHost(sockets=table))
    node_id = await an_applied_node(client, session, reality_params)

    result = await health.check_node(session, node_id=node_id)
    summary = console.health_summary("leaf-nl", result)

    assert expected in summary, summary
    assert forbidden not in summary, summary


async def test_the_good_news_says_what_it_cannot_know(
    client, session, reality_params, monkeypatch
) -> None:
    """The narrowing itself — M22.2's whole point.

    "serving" was read as "working" about a node that was carrying nobody. The sentence
    now states where the reading was taken, because the probe never leaves the node and
    never asks whether a peer completed a handshake.
    """
    host_for(monkeypatch, _FakeHost(sockets=bound(reality_params["port"])))
    node_id = await an_applied_node(client, session, reality_params)

    result = await health.check_node(session, node_id=node_id)
    summary = console.health_summary("leaf-nl", result)

    assert console.WHAT_A_PROBE_CANNOT_SEE in summary, (
        "the sentence an operator reads about a healthy node claims more than the probe "
        "established, which is what made them stop looking"
    )
    assert "is serving" not in summary, (
        "the word the acceptance finding is about is back in the healthy sentence"
    )


async def test_the_crash_loop_sentence_does_not_send_the_operator_to_apply_again(
    client, session, reality_params, monkeypatch
) -> None:
    """The repair matters as much as the diagnosis.

    Applying a configuration the daemon refuses produces the same crash loop. The
    sentence has to say so, or the operator does the one thing that cannot help.
    """
    host_for(monkeypatch, _FakeHost(restarting=(TRANSPORT,)))
    node_id = await an_applied_node(client, session, reality_params)

    result = await health.check_node(session, node_id=node_id)
    summary = console.health_summary("leaf-nl", result)

    assert "keeps restarting" in summary
    assert "will not change that" in summary


async def test_no_probe_answer_carries_a_port_or_an_address(
    client, session, reality_params, monkeypatch
) -> None:
    """Core invariants §4, on a sentence that now has two more reasons to break it.

    This text becomes an API message and a banner. A port and an address are both the
    node's own details, and neither belongs in either — the transport's name is enough
    to find the row the answer is about.
    """
    host_for(monkeypatch, _FakeHost(sockets=SSH_ONLY, restarting=(TRANSPORT,)))
    node_id = await an_applied_node(client, session, reality_params)

    result = await health.check_node(session, node_id=node_id)
    body = (await client.get(f"/api/nodes/{node_id}/health")).text
    summary = console.health_summary("leaf-nl", result)

    for leak in (str(reality_params["port"]), NODE_ADDRESS, "0.0.0.0", "ss "):
        assert leak not in summary, f"the probe's sentence carries {leak!r}"
        assert leak not in body, f"the probe's answer carries {leak!r}"


async def test_no_probe_answer_learns_who_connected(
    client, session, reality_params, monkeypatch
) -> None:
    """The charter's rule, at the one surface most likely to grow a log by accident.

    The port question is asked of a LISTENING socket table, which has no peer in it by
    construction. Held here as well as at the command, because what reaches an operator
    is this answer rather than that command.
    """
    host_for(monkeypatch, _FakeHost(sockets=bound(reality_params["port"])))
    node_id = await an_applied_node(client, session, reality_params)

    body = (await client.get(f"/api/nodes/{node_id}/health")).text.lower()

    for cell in ("peer", "client", "connected", "handshake", "session"):
        assert cell not in body, f"a health answer names {cell!r}"
