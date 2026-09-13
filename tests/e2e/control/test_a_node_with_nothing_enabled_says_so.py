"""Pressing apply on a node that has nothing on it yet — M18.1.

WHAT: what the control plane answers when the very first thing an operator does after
      registering a node is press the button its row invites.
WHY:  this is the product's first-run experience and it was a parser error. Register a
      node, press apply, and the answer was

          502  the node could not be configured and has been marked degraded: command
               failed (1): 'cd /opt/hashi && docker compose up -d --remove-orphans':
               services must be a mapping

      with the node left ``degraded``. Nothing had gone wrong: a node with no enabled
      transport renders no config, no config makes an empty ``services:`` block, and the
      push layer faithfully reported what the node said about it. The operator was
      handed a sentence about YAML at the moment they needed one about transports, and a
      node in a state that means "this host is broken" when it had never been dialled.
HOW:  against the booted stack, through the real API and the real console — and this is
      the one apply scenario that needs no host at all, because the refusal happens
      before anything is dialled. That is the property under test as much as the words
      are.

Boundary: real control + postgres + caddy. There is no node host, and none is needed:
a successful apply is not provable here and is not claimed.
"""

import uuid

import pytest


@pytest.fixture
def unique() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture
async def operator(client):
    response = await client.post(
        "/panel/login", data={"username": "owner", "password": "e2e-operator-password"}
    )
    assert response.status_code == 303, response.text
    return client


async def a_registered_node(operator, unique: str) -> str:
    """A node as registration leaves it, with nothing enabled on it."""
    created = await operator.post(
        "/api/nodes",
        json={
            "name": f"empty-{unique}",
            "address": "192.0.2.10",
            "location_label": f"Testland-{unique}",
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def test_applying_a_node_with_nothing_enabled_is_not_a_parser_error(
    operator, unique: str
) -> None:
    """The milestone's own line: the answer must not be about the node's YAML."""
    node_id = await a_registered_node(operator, unique)

    refused = await operator.post(f"/api/nodes/{node_id}/apply")

    assert refused.status_code == 409, refused.text
    message = refused.json()["error"]["message"]
    # Not the old answer. Each of these words belongs to the layer that used to answer
    # this request, and none of them is something an operator can act on here.
    #
    # Stated as a standing guard rather than as the measurement: there is no host in this
    # stack, so the words a node's own compose produces cannot appear here today whatever
    # the control plane does. What actually fails if the refusal is removed is the status
    # and the line below — verified by deleting the raise and watching all three tests in
    # this file go red. This loop is what keeps a future change from reaching for the
    # node's stderr again on a node that was never dialled.
    for parser in ("mapping", "compose", "docker", "yml", "command failed"):
        assert parser not in message.lower(), (
            f"the answer still quotes the node's own stack ({parser!r}): {message}"
        )
    # And it IS about the thing the operator has to do next.
    assert "no transports enabled" in message, message


async def test_the_node_is_not_degraded_by_an_apply_that_pushed_nothing(
    operator, unique: str
) -> None:
    """The other half, and the one with a lasting cost.

    ``degraded`` means a host was written to and is not serving what it was given. A
    node in that state is out of every subscription and reads, to the operator who just
    registered it, as a machine that is already broken — before it has been dialled once.
    """
    node_id = await a_registered_node(operator, unique)

    await operator.post(f"/api/nodes/{node_id}/apply")

    node = (await operator.get(f"/api/nodes/{node_id}")).json()
    assert node["state"] == "draft", node
    assert node["state_detail"] is None, node


async def test_the_console_says_it_where_the_operator_pressed(
    operator, unique: str
) -> None:
    """The acceptance walk goes through the Nodes screen, not through the API.

    The refusal has to arrive as the console's own answer — a fragment the screen swaps
    in — rather than as an error envelope or a spinner that stops.
    """
    node_id = await a_registered_node(operator, unique)

    pressed = await operator.post(
        f"/panel/nodes/{node_id}/apply", headers={"HX-Request": "true"}
    )

    assert pressed.status_code == 200, pressed.text
    assert "no transports enabled" in pressed.text, pressed.text
    assert "the Nodes screen" in pressed.text, (
        "the refusal does not tell the operator where to offer the node a transport"
    )
    assert "config applied" not in pressed.text
