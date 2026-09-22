"""The control plane's HTTP surface, as the network sees it.

WHAT: what the booted control plane answers on the ports a client can reach.
WHY:  tests/control/ proves the same rules against an in-process ASGI app. That
      is not the same claim: the container runs a different interpreter, a
      different uvicorn invocation and a real socket, and the app is built by
      ``--factory`` rather than by a test. Every one of those has broken a
      service that passed its unit tests.
HOW:  real HTTP against the stack from `make e2e-up`. No fixtures inside the
      application, no database access.

Boundary: real control + postgres + caddy; nothing stubbed; nothing external.
          Says nothing about tunnels, nodes, or Russian networks.
"""

import pytest

# A path shaped like the subscription URLs this project will serve. The token is
# fake, and it is deliberately distinctive so a log grep cannot match it by
# accident.
FAKE_TOKEN = "e2e-not-a-real-token-4f3a9c1b"
SUBSCRIPTION_PATH = f"/sub/{FAKE_TOKEN}"


async def test_healthz_answers_over_real_http(client) -> None:
    """Liveness through the published port: the image boots and serves."""
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_healthz_says_nothing_about_the_fleet(client) -> None:
    """Liveness is liveness. It must not become a free inventory of the system.

    Anyone who can reach the delivery endpoint can reach this route, and it is
    unauthenticated on purpose (the container healthcheck uses it).
    """
    body = (await client.get("/healthz")).json()
    assert body == {"status": "ok"}, f"/healthz leaked extra fields: {sorted(body)}"


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
async def test_api_schema_is_not_served(client, path: str) -> None:
    """The panel is the highest-value target; a public schema is free recon."""
    assert (await client.get(path)).status_code == 404


async def test_unknown_path_is_a_plain_404(client) -> None:
    """A 404 must not describe the application that produced it.

    Not a style preference: a stack trace or a framework banner tells an attacker
    which versions to look up, and this endpoint is reachable from inside Russia
    by anyone who guesses the host.
    """
    response = await client.get(SUBSCRIPTION_PATH)
    assert response.status_code == 404
    body = response.text.lower()
    for leak in ("traceback", "fastapi", "uvicorn", "starlette", "/app/"):
        assert leak not in body, f"404 body mentions {leak!r}: {response.text[:200]}"


@pytest.mark.parametrize("path", ["/panel/login", "/panel/users"])
async def test_a_console_url_is_not_storable_over_real_http(client, path: str) -> None:
    """The headers that stop a browser rendering a fragment as a whole document.

    Asserted here as well as in ``tests/control/`` because this is the only place the
    claim is made about what leaves the SOCKET: the container builds the app through
    ``--factory``, from the installed distribution, behind a proxy — and a header set
    by a middleware is exactly the kind of thing that survives an in-process client
    and not a deployment.

    ``/panel/users`` needs no session for this: an unauthenticated request is
    redirected to the login form, and the redirect is a response the browser stores
    under that URL too.
    """
    response = await client.get(path)

    assert response.headers["cache-control"] == "no-store"
    assert "HX-Request" in response.headers["vary"]
