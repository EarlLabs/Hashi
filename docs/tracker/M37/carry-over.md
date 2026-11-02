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

## M37.2 (review round 1: clean; 2 Medium, 2 Low from the reviewer, 3 notes from the implementer)

- Medium — `services/telegram_bot.py` `_adduser` answers `exc.message` where the panel answers
  `wording.for_the_page(exc.message)`. Identical today (no add refusal carries a direction the
  console rewrites), but the coupling is implicit; a one-line comment naming it would help.
- Medium — `NOTHING_ADDED` is attached to every `DomainError` on the strength of a comment that
  `add_users` raises no `DomainError` after its commit (verified true: `apply_nodes` records
  per-node refusals in the outcome). No test pins that claim about another module; if `reach`
  ever raised one, the bot would say "Nothing was added" about users who exist.
- Low — `/adduser@BotName mira` parses as `/adduser` with argument `@BotName mira`. Telegram
  appends `@Bot` only in groups and menu picks, and groups are refused. Theoretical.
- Low — `_pieces`' hard-slice path (a single line over 4096) cannot occur for any block built
  here; tested with a synthetic limit, harmless.
- Note — the duplicate-name path sends two messages ("adding…" then the refusal) because
  validation lives inside `add_users`, per plan; a pre-check would duplicate the service.
- Note — a non-domain failure after "adding…" leaves the owner with no reply (the poller logs
  it); a fixed "the add did not complete" sentence would be a one-liner if ever wanted.
- Note — the `chat.type == "private"` check is pinned by a synthetic case; Telegram never sends
  `chat.id == owner_id` with a non-private type, so the chat-id check alone already refuses groups.

## M37.3 (round 1: clean + 2 Medium fixed in round-1 fixes; round 2: clean, 2 Low)

- Low — a recurring unexpected bug in a poll is one ERROR line per episode (the "failing" state resets only on success), the same rule as an unreachable Telegram; the ERROR level is what tells them apart. Judged right; recorded so nobody expects a line per retry.
- Low — `ScriptedApi` in the poller tests mirrors `TelegramApi`'s three methods but not `async with`; fine because those tests drive `poll_forever` directly.
- Low (round 1) — after a failed boot the "polling as" line is the only recovery signal; documented and tested.
- Note — `restore_levels` is copy-pasted in three test files (M37.1, M37.2, M37.3); a conftest fixture would fold them. Not this milestone's step.

## M37.4 (round 1: clean + 2 Medium fixed in round-1 fixes; round 2: clean, nothing open)

- Low (round 1, left) — `tests/infra/test_images_are_pinned` inspects only `BASE`; the e2e overlay's `python:3.14-slim` is held instead by `test_the_fake_runs_on_the_control_images_own_python`. Extending the pin test to overlays would be unrelated refactoring.
- Note — the fake is bind-mounted, not built: on a remote docker engine (the fleet's dind) the mount arrives empty and the stand fails loudly with `control` held down by `depends_on`. CI's local engine and laptops are unaffected. Recorded in the overlay comment; revisit if the fleet's engine ever runs the e2e stand.
- Note — nine pre-existing ruff E501s in `tests/e2e/**` files that no target lints (red on the untouched baseline too). Not this milestone's.
- Note — `aikit.yml`'s acceptance `entrypoints` and `stand.sh`'s banner do not mention the fake's injection endpoint (unzoned config; the orchestrator adds the entrypoint before acceptance).
- Note — the acceptance scenario's last line ("stop the stand's control plane with both settings blank and confirm no Telegram line") needs an env override on the stand, which the overlay sets; not provided by this step — the unit test for the unconfigured lifespan covers it.

## M37.5 (round 1: clean + 1 Medium fixed in round-1 fixes; round 2: clean)

- Low — the runbook's `curl getUpdates` recipe would answer 409 if a webhook were set on the token; a fresh BotFather bot has none.
- Low — the cheat-sheet bullet keeps the English section name in italics, as the cheat sheet already does for its cross-references.
- Note — the threat model's new row and intro clause are marked as added after the owner's 2026-10-03 approval; the owner has not approved them.
