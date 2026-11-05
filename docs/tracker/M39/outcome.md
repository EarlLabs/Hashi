# M39 — outcome

**Landed on `task/M39` (2026-11-04), stacked on task/M38.** The owner-only add-user
Telegram bot moved out of the control-plane process into its own container, co-located on
the host and tied to the panel ONLY by the shared Postgres on the local docker network —
no gRPC, no mTLS (both dropped on the owner's instruction, "just make it work"; a
separate-machine deploy and any secured remote tie are future milestones). The bot's
M37/M38 code is reused verbatim: a bot-only entrypoint (`control/app/botmain.py`) runs just
the poller against the shared database; the in-process poller left the web app's lifespan so
only the container polls (no double-poll); a `telegram-bot` compose service (off by default
behind the `telegram-bot` profile, `make up PROFILES=telegram-bot`) carries the Telegram env
the control service no longer holds. The e2e stand runs the bot as its container and the
runbook describes the container deploy.

**Steps and review.** M39.1 (the container + entrypoint, poller out of the lifespan): 2
review rounds (round 1 clean; two Mediums — botmain had no tests, the heartbeat path could
drift from the healthcheck — fixed and verified). The stand re-point + docs step: 1 round,
clean (one out-of-baseline e2e failure judged a pre-existing relative-date flake; it did not
recur in the close gate). Nothing stopped at a cap; no reviewer disagreement. Two agent
interruptions (a network drop, the user's own stop of the earlier gRPC attempt) were handled
by discarding the aborted work and resuming cleanly.

**Acceptance.** One round on the stand, verdict GOOD. The walk confirmed the bot works as a
container exactly as before (add, /nodes, /apply, silence for strangers, no secrets in chat
or logs), and the structural change: the control container logs no "polling as" line, and
stopping the bot container stops the bot while the panel and `/sub/` keep working, with the
control plane not taking over polling. One clumsy line (the "adding…" before validation) is
pre-existing from M37, not a regression.

**Close gate (final tree).** control 1336, edge 1025, infra 654 (edge/infra in a Linux
container with CI's pins), e2e 226 passed with the failing set exactly this Mac's host-bound
baseline and nothing new. The real `make verify` is the PR's CI run.

**Not covered, by design:** the bot reaching Telegram from the blocked Russian host — that is
M40's leaf egress. Until M40, the bot on a real Russian host sits in "polling is failing";
the runbook says so.
