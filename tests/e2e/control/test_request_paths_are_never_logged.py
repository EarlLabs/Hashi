"""The one record that can hurt a real person.

WHAT: proves that a request path never reaches the control plane's log.
WHY:  subscription tokens are bearer credentials carried IN THE URL PATH. An
      access log line is therefore a live key written to disk, and the charter
      forbids any record of who connected to what — not "off by default",
      absent. ``--no-access-log`` in the Dockerfile is the mechanism; a comment
      saying so is not proof, and the flag is one careless edit from vanishing.
HOW:  send requests whose path contains a distinctive fake token, then read the
      container's own log and require the token to be absent. Both a hit and a
      miss are sent: a 404 is exactly the case where a framework is most likely
      to log the path it could not route.

Boundary: real control + postgres + caddy; nothing stubbed. Proves the control
          container's log only — Caddy's is a separate scenario in
          tests/e2e/infra/, and both are needed because either alone leaks.
"""

import asyncio

FAKE_TOKEN = "e2e-token-9d21ce74-never-real"


async def test_no_request_path_reaches_the_control_log(client, logs_of) -> None:
    """Neither a routed request nor a 404 may leave the path behind."""
    before = len(logs_of("control"))

    assert (await client.get("/healthz")).status_code == 200
    assert (await client.get(f"/sub/{FAKE_TOKEN}")).status_code == 404
    assert (await client.get(f"/panel?token={FAKE_TOKEN}")).status_code == 404

    # uvicorn writes its log from a background thread; give it a moment so a
    # pass cannot come from reading the log too early.
    await asyncio.sleep(1.0)

    written = logs_of("control")[before:]
    assert FAKE_TOKEN not in written, (
        "a request path reached the control plane's log — subscription tokens "
        f"live in that path:\n{written[:2000]}"
    )
    assert "/sub/" not in written, f"request paths are being logged:\n{written[:2000]}"
