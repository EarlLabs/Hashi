"""An operator who follows only the panel gives a config-file user something that works — M24.

WHAT: the M24 acceptance line, as far as a stand can walk it: a node serving only a
      config-file transport, a user added from the panel, and the URL the panel's link
      dialog prints under its config-file heading fetched anonymously, exactly as shown.
      It must be an archive holding this user's configuration for THIS node; the
      subscription link must be printed beside it under its own heading; and neither
      link may reach the control plane's log.
WHY:  until M24 no screen printed the ``?format=client-config-file`` URL, so an operator
      following the panel handed such a user a link that answers an empty document. The
      owner chose one URL per config shape (``docs/decisions.md``, 2026-10-02).
HOW:  operator actions through the panel's own htmx routes; the user's side through a
      second, cookie-less client, because that is what a user's app is. No URL is
      composed here — every one is read off the dialog.

The stand is WARM: other scenarios leave serving nodes behind, and a new user is
granted on all of them, so what this person's links carry beyond this node is not
asserted here — the cold, every-combination proof is
``tests/control/test_the_panel_hands_over_the_config_file_link.py``. This file finds its
own node's file by the port it was given.

Boundary: real control + postgres + caddy; no node, no tunnel. Whether the AmneziaWG app
on a real device imports the archive is the real-host walk's, not this file's.
"""

import asyncio
import html
import io
import re
import uuid
import zipfile
from urllib.parse import urlsplit

import httpx

OPERATOR = {"username": "owner", "password": "e2e-operator-password"}
HTMX = {"HX-Request": "true"}

# Distinct from every other scenario's port on the warm stand.
AWG_PORT = 51951
POOL_SIZE = 2000


def _reading(markup: str) -> str:
    text = re.sub(r"<[^>]+>", " ", markup)
    return " ".join(html.unescape(text).split())


def _shown(dialog: str) -> list[tuple[str, str]]:
    """Each (heading, URL) pair the dialog prints, in order."""
    return [
        (html.unescape(heading).strip(), html.unescape(url).strip())
        for heading, url in re.findall(
            r'<strong>([^<]*)</strong>\s*</div>\s*'
            r'<div class="mono dialog-code"[^>]*>([^<]*)<',
            dialog,
        )
    ]


def _path(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.path}?{parts.query}" if parts.query else parts.path


async def test_the_config_file_link_the_panel_prints_delivers_the_file(
    client, base_url, logs_of
) -> None:
    unique = uuid.uuid4().hex[:8]
    assert (await client.post("/panel/login", data=OPERATOR)).status_code == 303

    name = f"m24-awg-{unique}"
    created = await client.post(
        "/panel/nodes",
        data={"name": name, "address": "192.0.2.151", "location_label": "Testland"},
        headers=HTMX,
    )
    assert created.status_code == 200, created.text
    node_id = next(
        node["id"] for node in (await client.get("/api/nodes")).json() if node["name"] == name
    )
    transport = "amneziawg"
    params = {
        "port": str(AWG_PORT),
        "tunnel_address": "10.151.0.1/20",
        "peer_tunnel_address": "10.151.0.2/20",
        "pool_size": str(POOL_SIZE),
        "mtu": "1280",
        "junk_packet_count": "4",
        "junk_packet_min_size": "40",
        "junk_packet_max_size": "80",
        "init_packet_magic_header": "1020327352",
        "response_packet_magic_header": "2060487442",
        "underload_packet_magic_header": "3679305607",
        "transport_packet_magic_header": "1436947798",
    }
    enabled = await client.post(
        f"/panel/nodes/{node_id}/transports",
        data={"transport_name": transport, **{f"{transport}-{k}": v for k, v in params.items()}},
        headers=HTMX,
    )
    assert enabled.status_code == 200, enabled.text
    state = await client.post(
        f"/panel/nodes/{node_id}/state", data={"state": "active"}, headers=HTMX
    )
    assert state.status_code == 200, state.text

    before = len(logs_of("control"))
    nickname = f"m24-{unique}"
    added = await client.post("/panel/users", data={"nickname": nickname}, headers=HTMX)
    assert added.status_code == 200, added.text
    assert "no-store" in added.headers["cache-control"]

    shown = dict(_shown(added.text))
    assert set(shown) == {"subscription link", "config-file link"}, shown
    said = _reading(added.text)
    file_says = said[said.index("config-file link") :]
    assert re.search(rf"Carries for {re.escape(nickname)}: [^.]*\b{transport}\b", file_says), (
        file_says
    )
    assert shown["config-file link"] == f"{shown['subscription link']}?format=client-config-file"

    async with httpx.AsyncClient(base_url=base_url, timeout=60.0) as device:
        archive = await device.get(_path(shown["config-file link"]))
        assert archive.status_code == 200, archive.text
        assert archive.headers["content-type"] == "application/zip"
        held = zipfile.ZipFile(io.BytesIO(archive.content))
        mine = [
            held.read(n).decode()
            for n in held.namelist()
            if n.endswith(".conf") and f":{AWG_PORT}" in held.read(n).decode()
        ]
        assert len(mine) == 1, held.namelist()
        assert "[Interface]" in mine[0] and "PrivateKey" in mine[0]

        plain = await device.get(_path(shown["subscription link"]))
        assert plain.status_code == 200, plain.text

    await asyncio.sleep(1.0)
    written = logs_of("control")[before:]
    token = urlsplit(shown["subscription link"]).path.rsplit("/", 1)[-1]
    assert token not in written, written[:2000]
    assert "format=client-config-file" not in written, written[:2000]
