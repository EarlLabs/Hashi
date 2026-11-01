# M37 — carry-over
Non-blocking findings left open, with the reason each was left. Read them as
BACKGROUND: they tell you what is known-wrong so you do not mistake it for the
intended design. Do not fix them as part of another step.

## M37.1 (review round 1: clean; 3 Low from the reviewer, 4 notes from the implementer)

- Low — `services/telegram_api.py` `send_message` sends `link_preview_options` beyond the
  plan's "plain text with no parse mode". Judged in scope and right (the preview would be
  Telegram's crawler fetching `/sub/`); the module comment records it. Kept.
- Low — `services/telegram_api.py` `_call`: the `except Exception` is broad; bounded to the
  request and every raise is `from None`. Note only.
- Low — the settings validator also normalises `Settings(telegram_bot_token="")` through a
  before-validator, slightly beyond the plan; harmless and tested.
- Note — two existing tests mute/exempt the `httpx` logger by hand
  (`test_a_subscription_issued_before_the_rename_still_resolves.py`,
  `test_the_panel_hands_over_the_config_file_link.py`); the new WARNING pin makes that
  redundant but harmless. Not touched.
- Note — the client has no response-size cap (the routing fetcher has one); the API host is
  owner-configured. Not added.
- Note — Telegram caps a message at 4096 characters; the client does not split. M37.2 decides
  what a reply that long does.
- Note — the client's timeouts are module constants, not settings; a field run from the entry
  box is what would justify promoting them.
