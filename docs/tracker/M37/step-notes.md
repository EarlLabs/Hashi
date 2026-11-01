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
