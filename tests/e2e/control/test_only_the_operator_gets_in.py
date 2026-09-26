"""Everything except one link is closed — backlog items 5 and 19.

WHAT: what a stranger gets from the API, the panel and the delivery endpoint.
WHY:  the panel is on a public URL by necessity (the owner has to reach it from
      anywhere, including from inside Russia), so its only protection is the guard on
      every route. The failure mode of per-route checks is a single unguarded admin
      endpoint, and it is silent — nothing logs "this route had no dependency".
HOW:  every request here is made with no session at all, against the booted stack.
      Both a read and a write are tried on the API: a guard that covers GET and not
      POST is the version of this bug that a casual check misses.

Boundary: real control + postgres + caddy. This says nothing about brute force — there
is deliberately no lockout in v1 (backlog nit N6) — only about the unauthenticated
case.
"""

import uuid

import pytest

WRITE_PATHS = [
    ("/api/nodes", {"name": "x", "address": "192.0.2.1", "location_label": "x"}),
    ("/api/users", {"nickname": "x"}),
    ("/api/hops", {}),
]
READ_PATHS = ["/api/nodes", "/api/users", "/api/transports", "/api/hops"]


@pytest.mark.parametrize("path", READ_PATHS)
async def test_the_api_tells_a_stranger_nothing(client, path: str) -> None:
    response = await client.get(path)
    assert response.status_code in (401, 403), f"{path} answered {response.status_code}"
    # And the refusal itself must not describe the fleet.
    assert "node" not in response.text.lower() or "not authenticated" in response.text.lower()


@pytest.mark.parametrize("path,payload", WRITE_PATHS)
async def test_a_stranger_cannot_write_either(client, path: str, payload: dict) -> None:
    """A guard that covers reads and not writes is the dangerous half of this bug."""
    response = await client.post(path, json=payload)
    assert response.status_code in (401, 403), f"{path} answered {response.status_code}"


async def test_the_panel_sends_a_stranger_to_the_login_screen(client) -> None:
    """A redirect rather than a 401: this is a browser, and the owner needs the form."""
    response = await client.get("/panel/")
    assert response.status_code in (302, 303, 307)
    assert "/panel/login" in response.headers.get("location", "")


async def test_a_wrong_password_is_refused_without_saying_which_half_was_wrong(
    client,
) -> None:
    """Distinguishing the two would confirm the username to whoever is guessing."""
    wrong_password = await client.post(
        "/panel/login", data={"username": "owner", "password": "not-the-password"}
    )
    wrong_username = await client.post(
        "/panel/login", data={"username": "nobody", "password": "e2e-operator-password"}
    )

    assert wrong_password.status_code == 401
    assert wrong_username.status_code == 401
    assert wrong_password.text == wrong_username.text


async def test_the_delivery_endpoint_is_the_one_thing_open_and_only_with_a_token(
    client,
) -> None:
    """It carries no session by design — the token in the path IS the credential.

    Which is exactly why an unknown token must be indistinguishable from a revoked
    one: anything else turns this endpoint into an oracle for guessing.
    """
    assert (await client.get(f"/sub/{uuid.uuid4().hex}")).status_code == 404
    assert (await client.get("/sub/")).status_code in (307, 404)


async def test_logging_out_ends_the_session(client) -> None:
    """Otherwise a shared or stolen browser keeps the fleet for as long as it lives."""
    assert (await client.post(
        "/panel/login", data={"username": "owner", "password": "e2e-operator-password"}
    )).status_code == 303
    assert (await client.get("/api/nodes")).status_code == 200

    assert (await client.post("/panel/logout")).status_code in (302, 303)
    assert (await client.get("/api/nodes")).status_code in (401, 403)
