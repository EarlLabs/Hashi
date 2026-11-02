# M37 — outcome

**Landed on `task/M37` (2026-11-01 → 2026-11-02).** An owner-only Telegram bot inside the
control plane: three settings (`HASHI_TELEGRAM_BOT_TOKEN`, `HASHI_TELEGRAM_OWNER_ID`,
`HASHI_TELEGRAM_API_URL`, both-or-neither at boot), a Bot API client whose failures never
carry the URL or the token, the `/adduser` handler (same add service as the panel, same
`user-added` trail entry, same push to every serving node, same links in the reply,
silence for every other account), a long-polling lifespan task that acknowledges each
update after one attempt and backs off to a minute with one line per episode, a fake
Telegram on the e2e stand with an e2e scenario that `make verify` runs, the runbook
section, four journal rows and one threat-model row. `httpx` is a runtime dependency
since this milestone (the owner's decision of 2026-11-01).

**Review rounds.** M37.1: 1 (clean). M37.2: 1 (clean). M37.3: 2 (round 1 clean with two
Mediums fixed on the orchestrator's call — the task could die on a non-dict update or an
unexpected exception). M37.4: 2 (round 1 clean with two Mediums fixed — a race in the e2e
scenario, an ordering note). M37.5: 2 (round 1 clean with one Medium fixed — the threat
model's intro). Acceptance fix step: 2 (round 1 clean with one Medium fixed — the
taken-name refusal told apart by an exception subclass). Nothing stopped at a cap; no
reviewer disagreement.

**Acceptance.** Round 1: GOOD with three "works, but awkward" lines; two were fixed
(`/adduser@botname`, the over-long refusal's closing sentence) and the third is the plan's
own design (the "adding…" line before validation). Round 2 on a fresh stand: GOOD — may
merge, both fixes verified, three clumsy lines left for the owner (see `carry-over.md`).
Could not be observed on a stand: the two boot behaviours (unit-tested), the Bot API from
a Russian box (the owner's field check), a push to a real serving node (no node on the
stand), channel-post and edited-message silence and error statuses (unit-tested).

**Gate on this machine.** CI runs the three zone suites and the e2e half on Ubuntu; this
Mac cannot run edge or infra green natively, so they ran in a Linux container with the
same pins, and the e2e half ran natively with a recorded host-bound failing set that must
not grow (details in the final report and in the orchestrator's gate note). The real
`make verify` is the PR's CI run.
