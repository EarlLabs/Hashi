# M37 — step notes
Conventions established here. They bind later steps, and later milestones in
this codebase, until something supersedes them. Follow them; do not relitigate.

## From M37.1 (settings + Bot API client) — commit cd41641, review clean in round 1

- **Settings.** `settings.telegram_bot_token: SecretStr | None`, `settings.telegram_owner_id:
  int | None` (`gt=0`), `settings.telegram_api_url: str` (default Telegram's Bot API). Blank
  env (`""`) means off on both the env and the kwargs path. The bot is ON iff
  `settings.telegram_bot_token is not None` — the `model_validator` guarantees the owner id is
  then set too, and refuses one half without the other with `TelegramSettingsIncomplete`
  (a `RuntimeError`, deliberately not a pydantic `ValueError`: that would become a
  `ValidationError` quoting the whole input dict, secret key and operator hash included).
  The refusal sentence begins `HASHI_TELEGRAM_BOT_TOKEN and HASHI_TELEGRAM_OWNER_ID are set
  together or not at all: ...` and ends `Refusing to start.`
- **Client.** `control.app.services.telegram_api.TelegramApi(token=settings.telegram_bot_token
  .get_secret_value(), api_url=settings.telegram_api_url)`; an async context manager, also
  `aclose()`. One `httpx.AsyncClient` bound to `<api_url>/bot<token>/`, redirects not followed.
  - `await api.get_me() -> dict` (has `"username"`).
  - `await api.get_updates(offset: int | None, timeout: int, allowed_updates=("message",)) ->
    list[dict]` — `offset=None` on the first poll, else last `update_id + 1`; the HTTP read
    ceiling is `timeout + LONG_POLL_GRACE` (module constants: `CONNECT_TIMEOUT=10`,
    `CALL_TIMEOUT=30`, `LONG_POLL_GRACE=10` — not settings, by design).
  - `await api.send_message(chat_id: int, text: str) -> None` — plain text, NO `parse_mode`,
    link previews disabled (`link_preview_options.is_disabled`): a preview is Telegram's
    crawler fetching the `/sub/` link itself.
- **Failures.** Every failure is `TelegramCallFailed(DomainError)` (status 502, code
  `telegram_call_failed`), raised `from None`, with one of four composed sentences — never the
  URL, the token or remote text (Telegram's `description` is dropped on purpose, the
  `routing.FetchFailed` rule): `"Telegram could not be reached for getUpdates (ConnectError)."`,
  `"Telegram did not answer getUpdates within 40 seconds."`, `"Telegram answered HTTP 401 to
  sendMessage."`, `"Telegram answered getMe with a body that is not the Bot API's (HTTP 200)."`
  `str(exc)` is safe to log verbatim. `asyncio.CancelledError` is never wrapped. The module has
  no logger at all.
- **Logging pin.** `configure_logging` in `main.py` pins `httpx` and `httpcore` at WARNING
  (httpx logs `HTTP Request: POST <url>` at INFO, token in the path). The loggers test's
  `PINNED` tuple names both; the client test proves the pin is load-bearing. Do not log a
  request URL anywhere near this client.
- **Tests.** `TelegramApi(token=..., api_url=..., transport=httpx.MockTransport(handler))`; the
  handler receives the `httpx.Request` — body `json.loads(request.content)`, URL
  `str(request.url)`, per-call timeouts `request.extensions["timeout"]`; raise
  `httpx.ConnectError("...", request=request)` to fail a call. The no-leak pattern (report
  offending records by logger NAME, call `configure_logging()` first, drive root to DEBUG with
  `caplog.at_level`) and the `Recorded` helper are in
  `tests/control/test_the_telegram_client_never_shows_its_token.py`. Settings tests use the
  `environment` monkeypatch fixture from `tests/control/test_half_a_telegram_pair_stops_the_boot.py`.
- **Dependency.** `httpx` is a runtime dependency since this step (owner's decision 2026-11-01).

## From M37.2 (the owner's commands) — commit f33cb58, review clean in round 1

- **Entry point.** `await telegram_bot.handle_update(session, api, update, owner_id=settings.telegram_owner_id, base_url=settings.public_base_url)` → `None`. One fresh `AsyncSession` per update from the app's sessionmaker; `api` is the one `TelegramApi` the caller holds. The module takes no lock: "one at a time, in order" is the caller's, by awaiting each call to completion before the next.
- **Gate, evaluated first, from the update alone, before any call and any log line:** `message.from.id == owner_id`, `message.chat.id == owner_id`, `chat.type == "private"`, no `forward_origin`/`forward_date`; ids must be strict `int`; `owner_id` must be a positive strict `int` (so `None`, `0`, `True` make a bot that answers nobody). Everything else is silence — no reply, no log line, never the sender's id.
- **Raises vs swallows.** Raises `TelegramCallFailed` when the reply before/instead of the add could not be sent (the add was then NOT started) and any non-domain exception out of the add (no reply sent). Swallows only a failed post-add links reply, logging one WARNING (`str(exc)` + a count). A refusal is answered, never raised. The caller: catch `Exception`, log one line with `str(exc)`, acknowledge.
- **Commands.** `_COMMANDS` dict (`"/adduser": _adduser`, handler `(session, api, chat_id, argument, *, base_url)`); M38 adds `/nodes` and `/apply` as one entry + one function each. Token match is exact (`/adduser`, no case folding, no `@bot` suffix). `/adduser` text is split like `panel/routes.py create_user` (one nickname per line, blanks dropped).
- **Words a person sees** (module constants): `ADDING = "adding, about a minute per node"`; `USAGE = "/adduser <nickname> — one nickname per line — adds them, pushes them to every serving node and replies with their links. Everything else is on the panel."`; `NOTHING_ADDED = "Nothing was added. The panel shows every user and their links; the bot never re-sends a link."` (appended under every refusal, which is how "points at the panel" is honoured); links reply is `"<nickname>\nsubscription link: <url>"` with one `"<heading>: <url>"` line per shape, blocks separated by a blank line; `AddOutcome.summary()` verbatim as a trailing block when not complete or nothing was serving.
- **4096 cap.** `TELEGRAM_MESSAGE_LIMIT = 4096`; `_messages(blocks, *, limit)` packs whole blocks (a person's links never straddle two messages), then lines, then a hard slice. M38's `/nodes` reply goes through `_messages` too.
- **Test harness to reuse** (`tests/control/test_the_bot_answers_the_owner_and_nobody_else.py`): `FakeTelegram` (MockTransport handler recording `.requests`, `.sends`, `.texts`; `.failing` = set of 0-based sendMessage indices answered 502), `an_update(text, sender=, chat=, chat_type=, key=, **extra)`, `a_serving_node(client, reality_params, name=, address=)` + `hosts_down`, `links_in(text, base_url)` for the `anonymous` client; no-leak pattern = `configure_logging()` + `caplog.at_level(DEBUG)` + the autouse `restore_levels` fixture.
