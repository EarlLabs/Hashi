#!/usr/bin/env python3
"""A fake Telegram Bot API, for the e2e stand only.

WHAT: one HTTP server that answers the three Bot API methods the control plane's bot
      uses — ``getMe``, ``getUpdates`` (a real long poll) and ``sendMessage`` (recorded)
      — plus two test-only routes: ``POST /_test/updates`` puts a message in front of the
      bot as if a Telegram account had typed it, and ``GET /_test/sent`` reads back every
      message the bot sent.
WHY:  the stand cannot reach Telegram and must not pretend to. Without this, nothing
      outside unit tests ever runs the bot: ``make verify`` could prove the panel and the
      delivery endpoint and say nothing about the one new door into the control plane.
      With it, the stand's control plane polls here, an e2e scenario injects the owner's
      ``/adduser`` and a stranger's, and reads what came back — through the real client,
      the real poller and the real add, with only the far end replaced.
HOW:  standard library only, so the service that runs it is the control image's own
      Python with this one file mounted — no third image to build and nothing to install.
      ``ThreadingHTTPServer`` gives every connection its own thread, which is what lets a
      30-second long poll sit on one thread while an injection arrives on another; a
      ``threading.Condition`` wakes the poll the moment an update is queued, so a scenario
      waits milliseconds and not a poll period. Telegram's acknowledgement semantics are
      kept: ``getUpdates`` returns every update with ``update_id >= offset`` and forgets
      only the ones BELOW the offset — the ones the previous answer delivered and the
      caller has now confirmed. An update is never dropped by being read, and a control
      plane that restarts gets everything it had not confirmed, exactly as it would from
      Telegram. The listen port is ``FAKE_TELEGRAM_PORT`` from the environment and is
      compose's to decide, not this file's.

      Every answer is the Bot API's envelope, ``{"ok": true, "result": ...}`` — the two
      test routes too, so a reader has one shape to parse. The bot token sits in the
      request path (``/bot<token>/<method>``), which is why ``log_message`` is silenced:
      the stock handler writes every request line to stderr, and the container's log is
      the one place on the stand that outlives a scenario. The same rule as ``/sub/``.
"""

import json
import os
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

# What ``getMe`` answers. Fixture data for a bot that exists nowhere; the name is what
# ``control/app/services/telegram_poller.py`` reads out of the answer.
BOT_USERNAME = "hashi_e2e_bot"
BOT_ID = 1

# A long poll waits at most this long, whatever the request asked for. Telegram's own
# ceiling is undocumented; this one exists so a mistyped ``timeout`` cannot park a
# handler thread for an hour on a stand nobody is watching.
MAX_LONG_POLL_SECONDS = 60


class Exchange:
    """Everything the fake remembers: the queue in front of the bot, and what it sent.

    One lock around both, as a ``Condition`` so a waiting ``getUpdates`` can be woken by
    an injection. Every method takes the lock itself; callers never hold it.
    """

    def __init__(self) -> None:
        self._changed = threading.Condition()
        self._updates: list[dict[str, Any]] = []
        self._sent: list[dict[str, Any]] = []
        self._next_update_id = 1
        self._next_message_id = 1

    def inject(self, update: dict[str, Any]) -> int:
        """Queue one update under the next id and wake every poll waiting for one."""
        with self._changed:
            update_id = self._next_update_id
            self._next_update_id += 1
            self._updates.append({**update, "update_id": update_id})
            self._changed.notify_all()
            return update_id

    def updates(self, offset: int | None, timeout: float) -> list[dict[str, Any]]:
        """Telegram's ``getUpdates``: confirm below ``offset``, deliver from it, wait if empty.

        ``offset`` absent means "everything not yet confirmed", which is what a freshly
        started control plane asks for. Waiting is bounded by ``timeout`` and ends early
        the moment ``inject`` adds something this call would deliver.
        """
        with self._changed:
            if offset is not None:
                self._updates = [u for u in self._updates if u["update_id"] >= offset]
            if not self._updates and timeout > 0:
                self._changed.wait_for(lambda: bool(self._updates), timeout=timeout)
            return list(self._updates)

    def record_sent(self, body: dict[str, Any]) -> int:
        """Keep one ``sendMessage`` body verbatim and hand back the message id it got."""
        with self._changed:
            message_id = self._next_message_id
            self._next_message_id += 1
            self._sent.append(body)
            return message_id

    def sent(self) -> list[dict[str, Any]]:
        with self._changed:
            return list(self._sent)


class Handler(BaseHTTPRequestHandler):
    """One request at a time, on the connection's own thread."""

    # Keep-alive, so the control plane's client reuses one connection across polls the
    # way it does against Telegram. Every answer carries a Content-Length for that reason.
    protocol_version = "HTTP/1.1"
    server: Server  # defined below; the handler only ever runs on one

    def log_message(self, format: str, *args: Any) -> None:
        """Nothing, ever: the request line holds the bot token."""

    def do_GET(self) -> None:
        if self._route() == "/_test/sent":
            self._answer(HTTPStatus.OK, self.server.exchange.sent())
            return
        self._refuse(HTTPStatus.NOT_FOUND, "Not Found")

    def do_POST(self) -> None:
        body = self._json_body()
        if body is None:
            self._refuse(HTTPStatus.BAD_REQUEST, "Bad Request: the body is not a JSON object")
            return
        route = self._route()
        if route == "/_test/updates":
            self._inject(body)
            return
        method = _bot_method(route)
        if method == "getMe":
            self._answer(
                HTTPStatus.OK,
                {
                    "id": BOT_ID,
                    "is_bot": True,
                    "first_name": "hashi e2e",
                    "username": BOT_USERNAME,
                },
            )
        elif method == "getUpdates":
            self._get_updates(body)
        elif method == "sendMessage":
            self._send_message(body)
        else:
            self._refuse(HTTPStatus.NOT_FOUND, "Not Found")

    # --- the Bot API ---------------------------------------------------------------

    def _get_updates(self, body: dict[str, Any]) -> None:
        offset, timeout = body.get("offset"), body.get("timeout", 0)
        if offset is not None and type(offset) is not int:
            self._refuse(HTTPStatus.BAD_REQUEST, "Bad Request: offset must be an integer")
            return
        if type(timeout) is not int or timeout < 0:
            self._refuse(
                HTTPStatus.BAD_REQUEST, "Bad Request: timeout must be a non-negative integer"
            )
            return
        updates = self.server.exchange.updates(offset, min(timeout, MAX_LONG_POLL_SECONDS))
        self._answer(HTTPStatus.OK, updates)

    def _send_message(self, body: dict[str, Any]) -> None:
        chat_id, text = body.get("chat_id"), body.get("text")
        if type(chat_id) is not int or not isinstance(text, str) or not text:
            self._refuse(HTTPStatus.BAD_REQUEST, "Bad Request: chat_id and text are required")
            return
        message_id = self.server.exchange.record_sent(body)
        self._answer(
            HTTPStatus.OK,
            {
                "message_id": message_id,
                "date": int(time.time()),
                "chat": {"id": chat_id, "type": "private"},
                "text": text,
            },
        )

    # --- the test-only side --------------------------------------------------------

    def _inject(self, body: dict[str, Any]) -> None:
        """Queue a full update as given, or build a private message from the short form.

        The short form is ``{"from_id", "text"}`` with optional ``chat_id`` (defaults to
        the sender — a private chat) and ``chat_type`` (defaults to ``private``). Whatever
        is given, the ``update_id`` is this server's: Telegram numbers updates, not the
        account that typed them.
        """
        if "message" in body:
            update = {key: value for key, value in body.items() if key != "update_id"}
        elif type(body.get("from_id")) is int and isinstance(body.get("text"), str):
            sender = body["from_id"]
            update = {
                "message": {
                    "message_id": 1,
                    "date": int(time.time()),
                    "from": {"id": sender, "is_bot": False, "first_name": "Someone"},
                    "chat": {
                        "id": body.get("chat_id", sender),
                        "type": body.get("chat_type", "private"),
                    },
                    "text": body["text"],
                }
            }
        else:
            self._refuse(
                HTTPStatus.BAD_REQUEST,
                "Bad Request: give a full update under 'message', or 'from_id' and 'text'",
            )
            return
        update_id = self.server.exchange.inject(update)
        self._answer(HTTPStatus.OK, {"update_id": update_id})

    # --- plumbing ------------------------------------------------------------------

    def _route(self) -> str:
        """The path without its query string, which this server never reads."""
        return self.path.split("?", 1)[0]

    def _json_body(self) -> dict[str, Any] | None:
        """The request body as a JSON object, or ``None`` when it is not one."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            body = json.loads(raw) if raw else {}
        except ValueError:
            return None
        return body if isinstance(body, dict) else None

    def _answer(self, status: HTTPStatus, result: Any) -> None:
        self._write(status, {"ok": True, "result": result})

    def _refuse(self, status: HTTPStatus, description: str) -> None:
        self._write(status, {"ok": False, "error_code": int(status), "description": description})

    def _write(self, status: HTTPStatus, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode()
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _bot_method(route: str) -> str | None:
    """``/bot<token>/<method>`` → ``<method>``; anything else → ``None``.

    Any token is accepted: this fake stands in for the far end, and which token the
    control plane sends is the owner's business, not the stand's.
    """
    parts = route.split("/")
    if len(parts) == 3 and parts[1].startswith("bot") and len(parts[1]) > 3 and parts[2]:
        return parts[2]
    return None


class Server(ThreadingHTTPServer):
    """The HTTP server with the one ``Exchange`` every handler thread shares."""

    daemon_threads = True

    def __init__(self, port: int, exchange: Exchange | None = None) -> None:
        # Every interface: a container's listener has to be reachable from the compose
        # network and from whatever the engine publishes, and which of those exist is
        # compose's decision. An empty host is the standard library's "all IPv4".
        super().__init__(("", port), Handler)
        self.exchange = exchange or Exchange()

    @property
    def port(self) -> int:
        """The port actually bound — the one that matters when asked for 0."""
        return self.server_address[1]


def main() -> int:
    port = os.environ.get("FAKE_TELEGRAM_PORT", "")
    if not port.isdigit():
        print(
            "FAKE_TELEGRAM_PORT is not set to a port number; refusing to start.",
            file=sys.stderr,
        )
        return 2
    server = Server(int(port))
    print(f"fake telegram: listening on port {server.port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
