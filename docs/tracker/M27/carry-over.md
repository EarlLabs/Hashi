# M27 — carry-over
Non-blocking findings left open, with the reason each was left. Read them as BACKGROUND:
they tell you what is known-wrong so you do not mistake it for the intended design. Do not
fix them as part of another step.

## From M27.1 — OPEN, carried into M27.2

**1. A false security claim in the durable record.** `docs/decisions.md:159` says *"seizing
the control host yields ciphertext and seizing the delivery host yields the credential."*
**The first half is false.** `HASHI_SECRET_KEY` lives in `.env` **on the control host** —
`scripts/panel-bootstrap.sh` refuses to install unless it finds it there,
`docs/deploy/runbook.md` says *"`HASHI_SECRET_KEY` goes in `.env` here"*, and this same file's
2026-09-23 row records that `.env` holds the key and is excluded from the backup **for that
reason**. So seizing the control host yields the key beside the database, and therefore the
tokens in the clear.

The true property is about the **dump**, not the host: M28 built *two secrets that never meet
on the control host* about the age identity, not about the master key being absent. **It is
false in exactly the arrangement this milestone is about** — under Shape B the control host
*is* the Russian entry, which is why `panel-bootstrap.sh` has that refusal — and a later step
reading it would rank the control host as the ciphertext-only side when choosing where a token
store may live. **M27.2 corrects it while writing its own row.**

**2. The store shape is presumed in a neighbouring clause.** `docs/decisions.md:158` says a
host that stops serving keeps *"its token files"*, which presumes the naive one-file-per-token
store the next row says M27.2 may or may not land. Should read *"whatever token store M27.2
lands"*.

**3. The stop-case gap has no home outside one decisions row.** `docs/PLAN.md`'s M27.2 text
does not mention removing delivery material, and **none of M27's six done-when boxes covers a
host that stops being a delivery host.** The clause is correct; its carry is weaker than it
reads. Echo it in a step's text or as a done-when box.

## Not M27's — a gate-integrity finding, worth its own work

**`tests/control/conftest.py:107` skips per-test when Postgres is unavailable, and the victim
is whichever test runs first.** The fixture is function-scoped, so a slow container costs an
arbitrary number of tests and the run still **exits 0 with a green summary**. Observed once in
this milestone as 992 passed / 3 skipped where the real number is 993/2. The cited file:line
in the first report was just that run's draw, not a fixed location. A session-scoped
wait-for-Postgres, or a hard failure rather than a skip once the URL is explicitly configured,
would close it. Same family as everything M28 was about: a check that goes quiet rather than
red.
