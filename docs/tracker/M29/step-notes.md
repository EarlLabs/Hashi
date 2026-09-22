# M29 — step notes
Conventions established here. They bind later steps, and later milestones in
this codebase, until something supersedes them. Follow them; do not relitigate.

## M29.1 — the line, and the decisions (renamed nothing)

**The record/living-document line lives in `docs/records-and-living-documents.md`.**
Read it before you touch anything in bulk. It is not a summary of this milestone;
it is the durable home, deliberately outside `docs/PLAN.md` because M29.1's own
plan text becomes a record the day M29 is marked `✅`, and a future bulk edit will
not look it up there.

The short of it, so you cannot miss it:

- **Never reworded:** `docs/tracker/**` (including this file once it is written),
  the existing rows of `docs/decisions.md`, the already-applied Alembic
  migrations, git history, and **three parts of `docs/PLAN.md`**: every `## ✅`
  milestone, `## Decisions needed from you`, and `## Where the field run left the
  plan, 2026-09-09`. The middle one is the easy miss — its decision 9, answered
  by the owner on 2026-09-08 with *"`friend` stays the word in the models, the
  services, the API and the tests"*, is the decision M29 reverses, and rewording
  it erases the fact that it was ever decided the other way.
- **Reworded:** the charter, `docs/deploy/runbook.md`, `docs/product/backlog.md`,
  `docs/security/threat-model.md`, `README.md`, `CLAUDE.md`, `.claude/**`, the
  plan's `## →` (open) milestones and its `## What this plan does not cover`, and
  all other code, templates and tests.
- **"Never touched" forbids rewording, not adding.** This milestone may add new
  files under `docs/tracker/M29/`; the check looks for *removed and changed
  lines*, never for a changed directory. `docs/decisions.md` shows as modified in
  every such diff because rows were appended — that is correct.

**M29.7 must verify the records by diff, not by intention.** Run this from the
repository root; M29's baseline is `1b60280`. Both must print nothing:

```sh
git diff 1b60280 -- docs/tracker/ | grep -E '^-[^-]'
git diff 1b60280 -- docs/decisions.md | grep -E '^-[^-]'
SLICE='/^## /{k = /^## ✅|^## Decisions needed from you|^## Where the field run left the plan/} k'
diff <(git show 1b60280:docs/PLAN.md | awk "$SLICE") <(awk "$SLICE" docs/PLAN.md)
```

Run them at the *start* of your step too, so a failure at the end is known to be
yours.

## Conventions every remaining M29 step follows

1. **The word is `user`.** Singular `user`, plural `users`, adjectivally
   `user_id`, `UserRow`, `users_table.html`. Owner-settled 2026-09-22; recorded
   in `docs/decisions.md`.
2. **A bare `user` means the person who uses hashi.** The other two meanings are
   never written bare and must not be "fixed" to look like it: a node's account
   stays `ssh_user`, the panel login stays `operator` / `HASHI_OPERATOR_USERNAME`
   / `--user` in `scripts/node-bootstrap.sh`. The three-way collision was put to
   the owner against `subscriber` and accepted knowingly — do not reopen it, and
   do not invent a fourth spelling to dodge it.
3. **No aliases, no deprecation window.** `/api/friends/*` → `/api/users/*`,
   `/panel/friends/*` → `/panel/users/*`. Do not leave a redirect, a second route
   or a compatibility shim "just for a while". `/sub/{token}` does not change.
4. **Already-applied migrations keep every word**, including their comments and
   docstrings, their file names and their revision ids. Six of the seven mention
   the old word (`0001`, `0002`, `0003`, `0004`, `0006`, `0007`); none of them is
   edited. M29.3's rename is a **new** migration on top of `0007`, reversible
   both ways. Rewording `0001` would make a fresh database disagree with a
   deployed one while both report the same revision.
5. **Prose is renamed with the same care as identifiers.** Most of the ~3650
   occurrences are comments and docstrings; a comment left saying *friend* beside
   a symbol saying `user` is the exact half-finished state this milestone exists
   to end.

## Things M29.7 will otherwise miss

The plan's living-document list is shorter than the corpus. Measured at baseline
`1b60280` with `grep -oi friend <file> | wc -l`:

| file | occurrences | on the plan's list? |
|---|---|---|
| `docs/PLAN.md` | 212, of which **151 are record and stay** (144 in `## ✅` milestones, 7 in the two dated tail sections) — **61 are movable** | yes, open milestones only |
| `docs/deploy/runbook.md` | 67 | yes |
| `docs/product/charter.md` | 15 | yes |
| `docs/product/backlog.md` | 8 | **no** — classified living by the test |
| `docs/security/threat-model.md` | 5 | **no** — classified living by the test |
| `.claude/projects/00-core-invariants.md` | 2 | **no** — classified living by the test |
| `CLAUDE.md` | 2 | yes |
| `README.md` | 1 | yes |

`CLAUDE.md` and `.claude/**` are owner/architect territory. They are on the
living side of the line and the owner put `CLAUDE.md` there explicitly, so M29.7
rewords them — but nothing beyond the vocabulary, and no new rule rides along.

**One accepted residual:** `docs/tracker/field-checklist.md` holds 56
occurrences and is a live instrument the owner carries to the hosts, not a
record of what happened. The owner drew the line by path (`docs/tracker/**`), so
the path wins and the checklist keeps the old word — a checklist saying *friend*
in front of a panel saying *user*. Closing that means promoting the file out of
`docs/tracker/`, which is the owner's call and is not M29's to take on the way
past.

## How to test what M29.1 built

Nothing to fixture: this step added two documents and four journal rows and
changed no code. Its gate was `make verify` (the whole gate, because `docs/**`
belongs to no zone), and nothing in it is specific to this step.

What the *later* steps should reuse is the three-command record check above —
paste it, do not re-derive it. The `awk` idiom turns the accumulator on at a
record heading and off at the next `## ` of any kind, which is what lets one file
be half record and half living document. Do not simplify it back to `## ✅` only:
that was the first version written here and it left 7 occurrences of the old word
exposed in two dated sections that must not move.

## Wording a person will see

M29.1 introduced none. The strings an operator reads are M29.4's (panel and API)
and M29.7's (charter, runbook, README); they must match the vocabulary above and
the runbook must state the API break in the words *"anything scripted against the
old paths stops working"*, per the owner's decision.

## M29.2 — `edge` renamed (the zone is done except its e2e scenarios)

**The vocabulary is proven.** `edge/**` and `tests/edge/**` carry no *friend*
except two deliberate keeps. `make test-edge` is green on it (911 passed, 3
skipped — `awg-quick` absent, the baseline skip).

1. **The public name is now `TransportMeta.serves_users_through_a_hop`**
   (`edge/registry.py`). `control` has NOT been updated and is red until it is.
   The complete list M29.3/M29.4 must change, measured and independently
   confirmed: `control/app/services/nodes.py:732` and
   `control/app/services/relay.py:425` (calls), `control/app/errors.py:250` and
   `control/app/services/transports.py:280` (prose), and
   `tests/control/test_both_doors_refuse_a_friend_with_no_way_out.py` (lines 48,
   53, 205, 457, 468 — and the file name itself). `grep -rn` over `control/`,
   `tests/control/` and `tests/e2e/` returns exactly those sites and no others.

2. **HOW RED THE TREE IS BETWEEN HERE AND M29.4 — measured, not estimated.**
   M29.2's own hand-off first said "one collection error and one runbook
   mismatch", and review round 1 disproved it. The true state after M29.2:

   - static: `tests/control` has **1 collection error** (the file above) and is
     otherwise green (216 passed, 670 skipped for want of Postgres — the
     baseline shape); `tests/infra` has **1 failure** (item 3 below), 240 passed;
     `make test-edge` is fully green.
   - e2e: **28 failed and 5 errors** across `tests/e2e/control/` and
     `tests/e2e/infra/`. Every one of them is the SAME root cause as the
     collection error — `control` calling the renamed property unconditionally
     on every "enable a transport" and "establish a hop" path. The container log
     carries the identical `AttributeError: 'TransportMeta' object has no
     attribute 'serves_friends_through_a_hop'` traceback on all 31
     `internal_error` 500s; the remaining 2 are `Server disconnected` cascading
     from the same crash, not a distinct defect.

   **So essentially all of `tests/e2e/control/` and `tests/e2e/infra/` is
   blocked until M29.3/M29.4 migrate the callers** — it is not "mostly green
   with two known failures", and nothing downstream should rely on it being so.
   Do not read a green-ish `make verify` summary as progress before M29.4.

3. **A seam nobody predicted: `docs/deploy/runbook.md` quotes `edge`'s error
   strings verbatim and `tests/infra/` pins the quotation.**
   `tests/infra/test_deploy_runbook.py` imports `edge.egress.NO_RESOLVER` and
   asserts the runbook contains it word for word. `NO_RESOLVER` now says "the
   destinations its **users** ask for"; the runbook still says *friends*, so
   `make test-infra` fails one test and **`make verify` cannot be green until
   the runbook sentence moves, which is M29.7's**. Any step between M29.2 and
   M29.7 that gates on `make verify` is gating on something already red for a
   reason it did not cause. Gate on the zone's own verify instead.

4. **`tests/e2e/edge/**` is in the old vocabulary — 94 occurrences.**
   `CLAUDE.md` puts it in the `edge` zone, but M29.2's fence was `edge/**` +
   `tests/edge/**` and M29.7's E2E note named only `tests/e2e/control/`. It
   holds a file name (`test_a_friend_exits_at_the_leaf_and_not_at_the_entry.py`)
   and four identifiers (`NO_FRIEND_HERE`, `FRIEND_TRANSPORTS`, `FRIEND_PORT`,
   `FRIEND_ATTEMPTS`), so the milestone's "no identifier in `control` or `edge`
   still carries the old one" was not reachable by the seven steps as written.
   **M29.2b was added to the plan to take it**, rather than leaving a Done-when
   the milestone cannot satisfy.

5. **Two occurrences are KEPT and must not be "finished" by a later step.**
   `edge/health/listening.py:36` says "``/proc/net/tcp`` and friends" — English
   for "and similar files", not a person. And
   `tests/edge/test_a_tunnel_carries_traffic_off_the_node.py:583` cites the path
   `tests/e2e/edge/test_a_friend_exits_at_the_leaf_and_not_at_the_entry.py`,
   which must keep naming the file that actually exists — so it moves only when
   M29.2b renames that file, and then it moves with it.

6. **`docs/decisions.md:104,110` name `edge.egress._friend_rules`**, now
   `_user_rules`. Those rows are record and stay as written; the symbol they
   point at has moved. Accepted, not fixed.

### How to test what M29.2 built

`make test-edge` — ruff plus `pytest tests/edge`, no Docker, ~8s. Nothing was
fixtured or scaffolded: the existing `tests/edge/conftest.py` fixtures
(`clients`, `credentials`, the per-transport `node` fixtures) are unchanged in
shape and only their prose moved. The three golden files under
`tests/edge/golden/` are rendered from the `.j2` templates, so **a comment
reworded in `server.j2` or `client.j2` must be reworded identically in the
golden `.conf`** — `test_golden_configs.py` compares byte for byte and will say
so. A later step reworking edge prose changes the template and re-checks the
golden, never the other way round.

### Wording a person will see

Operator-facing strings in `edge` now say *user*. The ones that matter, because
they are quoted or asserted elsewhere:

- `edge.egress.NO_RESOLVER` — "…names no resolver for the destinations its
  **users** ask for…". **`docs/deploy/runbook.md` must be changed to match this
  exact sentence** (`tests/infra/test_deploy_runbook.py` enforces it).
- `edge.egress` hop refusal — "Give this node's **users** a transport that…".
- `edge.registry` — "no **user**-facing format at all"; "so no **user** can be
  given access to it individually — and therefore no **user** could be revoked
  from it without affecting the others."
- The WireGuard/AmneziaWG `Params` field descriptions (panel- and API-visible):
  "the resolver a **USER**'s device is told to use inside the tunnel", "the
  first address given out when this transport is offered to **users**".

## M29.2b — `edge`'s e2e scenarios renamed (the zone is now complete)

**`tests/e2e/edge/**` carries no *friend*.** With M29.2, the whole `edge` zone as
`CLAUDE.md`'s table defines it is in the new vocabulary.

1. **Renamed, beyond the four constants the plan named.** The file (`git mv`,
   history follows — git records `R091`), the four constants —
   `NO_FRIEND_HERE` → `NO_USER_HERE`, `FRIEND_TRANSPORTS` → `USER_TRANSPORTS`,
   `FRIEND_PORT` → `USER_PORT`, `FRIEND_ATTEMPTS` → `USER_ATTEMPTS` — **and two
   the measurement missed**: the test
   `test_the_friend_still_reaches_the_name_they_asked_for` →
   `test_the_user_still_reaches_the_name_they_asked_for`, and the address-map key
   `addresses["friend"]` → `addresses["user"]`. **A later grep for identifiers
   should count test names and dict keys, not only `SCREAMING_CASE`.**

2. **M29.2's item 5 is closed.** The path citation at
   `tests/edge/test_a_tunnel_carries_traffic_off_the_node.py:583` moved with the
   file, in the same commit, as item 5 required. `edge/health/listening.py:36`
   ("``/proc/net/tcp`` and friends" — English for "and similar files") remains
   the **only** deliberate keep left in the whole `edge` zone. Nothing after this
   may "finish" it.

3. **A second stale path reference, found and fixed.** The `vless-reality` excuse
   inside `NO_USER_HERE` cited a `tests/edge/` file M29.2 had already renamed. It
   is a string in an assertion message, so nothing was ever red about it. **Any
   step that renames a test file must grep the tree for its old name as a
   STRING**, not only as an import.

4. **`tests/e2e/` is linted by no Makefile target.** `make test-edge` runs
   `ruff check edge tests/edge` and `pytest tests/edge` (Makefile:93); neither
   half reaches `tests/e2e/edge`. It carries **7 pre-existing ruff errors**
   (4 `E501`, 3 `F541`) in
   `test_a_crash_looping_container_is_not_reported_as_running.py` and
   `test_the_serving_check_meets_the_real_daemon.py`, present at M29's baseline
   and confirmed by the reviewer. Out of M29's scope; widening a lint target is
   an owner/architect call. Carried over.

5. **Style: word-in-place, no reflow.** M29.2's convention, followed here. A
   `friend` → `user` swap leaves some lines four characters short of their
   neighbours; that is accepted deliberately, because reflowing a paragraph turns
   a vocabulary diff into a rewrite nobody can review. **Every later step does the
   same.**

6. **`FRIEND_PORT` exists twice, and they are different constants.** This step's
   was `FRIEND_PORT = 1080` (a proxy port). `tests/control/test_what_collides_on_one_node.py`
   and `tests/e2e/control/test_the_runbook_shape_a_then_the_hop_it_mandates.py`
   each define their own module-local `FRIEND_PORT = 51820`, a WireGuard port.
   Those are M29.4's and are unrelated to this one.

### How to test what M29.2b built

Its zone gate is `make test-edge` — which **does not execute a single line of what
this step changed**, and saying so is the point. What was established instead, and
what a later step should re-run rather than re-derive:

```sh
.venv/bin/python -m ruff check tests/e2e/edge/test_a_user_exits_at_the_leaf_and_not_at_the_entry.py
.venv/bin/python -m pytest tests/e2e/edge --collect-only -q        # 94 tests, every module imports
.venv/bin/python -m pytest tests/e2e/edge/test_a_user_exits_at_the_leaf_and_not_at_the_entry.py \
  ::test_every_proxy_transport_is_measured_or_excused -q           # no Docker, 0.05s
```

`test_every_proxy_transport_is_measured_or_excused` is the cheap proof that a
constant rename in that file did not break its wiring: it asserts
`PROXY_TRANSPORTS - USER_TRANSPORTS - NO_USER_HERE` is empty, so a half-renamed
constant turns it red in fifty milliseconds without a docker engine. Collection
also pins the parametrisation ids (`[vless-ws-tls-amneziawg]`), which is how you
tell `USER_TRANSPORTS` still derives the same list rather than an empty one.

These scenarios cannot RUN green until M29.4 migrates `control`'s callers —
item 2 of M29.2 above is still the accurate picture of the tree.

### Wording a person will see

None. Every string this step touched is a test assertion message or a docstring;
nothing here reaches an operator, a panel screen or an API response.

## M29.3 — `control`: the table, the columns, and the migration both ways

**The schema is `users` and it reverses exactly.** `make test-control` green with a
real database: 910 passed, 2 skipped (the baseline `wireguard declares it cannot
carry a hop` pair), ruff clean. Reviewer reproduced every proof independently.

1. **The migration is `0008_the_person_who_uses_hashi_is_a_user.py`, revision `0008`
   on top of `0007`, and it is RENAMES ONLY.** No row is read or written, no column
   changes type, width, nullability or default, and no encrypted column is opened —
   so it needs no `HASHI_SECRET_KEY` (which is what lets M29.5 rehearse it against a
   copy of real data without one), it cannot fail on data, and a subscription token
   already on somebody's phone is byte-identical on both sides of it.

2. **Two classes of name, renamed two different ways, and do not "simplify" this.**
   What `0001` named itself — the table, both `friend_id` columns,
   `ix_subscriptions_friend_id`, `ix_credentials_friend_id`,
   `uq_friend_node_transport` — is renamed unguarded: a database missing one is not
   one this chain produced, and stopping is correct. The four names POSTGRES chose
   (`friends_pkey`, `friends_nickname_key`, `subscriptions_friend_id_fkey`,
   `credentials_friend_id_fkey`) go through `_rename_constraint_if_present`, because
   `ALTER TABLE … RENAME CONSTRAINT` has no `IF EXISTS`, nothing in this repository
   reads those names, and an unguarded miss would abort the `alembic upgrade head`
   that `deploy/docker/entrypoint.sh` runs on **every boot**.

3. **The model is `control/app/models/user.py`, class `User`** (git mv, history
   follows). The persistence names moved with it: `Credential.user_id`,
   `Subscription.user_id`, the `user` relationship (`subscription.user`,
   `row.user.is_active`), `select(User)`.

4. **M29.3 STOPS at the persistence layer, and the residue is deliberate.**
   `services/friends.py` reads `async def get_friend(session, friend_id: str) ->
   User` — old module, old function, old parameter, new type — and the same in
   `subscriptions.py`, `console.py`, `delivery.py`. **The ORM attribute is `user_id`
   while the API field, the route path parameter and `RevocationOutcome.friend_id`
   are still `friend_id`**, so a query written by copying a neighbouring line picks
   the wrong one half the time and fails at attribute access rather than at review.
   M29.4 closes it; build nothing on the mixed state.

5. **M29.2's seam is closed.** All five measured sites, plus a sixth the measurement
   missed (a docstring at `test_both_doors_refuse_a_friend_with_no_way_out.py:25`),
   now call `TransportMeta.serves_users_through_a_hop`. `tests/control` collects
   again; item 2 of the M29.2 section no longer describes the tree.

6. **`tests/control/test_both_doors_refuse_a_friend_with_no_way_out.py` was NOT
   renamed as a file**, deliberately: its whole body still says *friend*, so the name
   moves with its contents in M29.4, along with the other `tests/control/test_a_friend_*.py`.

### How to test what M29.3 built

`make test-control` **skips ~670 tests when no Postgres answers**, so a green run is
not evidence on its own — **check the skip count.** Bring a database up matching
`tests/control/conftest.py`'s `DEFAULT_URL` exactly; do NOT use `make up-dev`,
because conftest hardcodes `hashi:replace-me@127.0.0.1:54132` while `up-dev` takes
its credentials from `.env`, which no agent may read:

```sh
docker run -d --name hashi-db -p 127.0.0.1:54132:5432 \
  -e POSTGRES_USER=hashi -e POSTGRES_PASSWORD=replace-me -e POSTGRES_DB=hashi \
  postgres:16.4-alpine
```

**If that database already existed before M29.3, drop its schema first.** The
`empty_database` and `clean_database` fixtures clear tables through
`Base.metadata.drop_all`, which now knows `users` and not `friends` — a leftover
`friends` table from a pre-M29 run survives and makes `0001` fail with
`relation "friends" already exists`. `psql -c 'DROP SCHEMA public CASCADE; CREATE
SCHEMA public;'`. This will bite every developer once.

The cheap proof — 13 seconds, no app stack: `pytest tests/control/test_migrations.py -q`
(7 passed). The one that reads best in a review, needing only `alembic` and `pg_dump`:

```sh
alembic -c control/alembic.ini upgrade 0007 && pg_dump --schema-only > at0007.sql
alembic -c control/alembic.ini upgrade head
alembic -c control/alembic.ini downgrade 0007 && pg_dump --schema-only > back.sql
diff at0007.sql back.sql      # empty — the round trip restores the schema exactly
```

`test_the_rename_to_users_goes_forward_and_back_without_moving_a_token` is the
regression that matters and the one a later step extends rather than rewrites: the
pre-existing `test_the_migration_can_be_reversed` unwinds an EMPTY database, which a
rename passes trivially, so the new test puts a subscription in and compares its
`token` and `token_digest` byte for byte at head, at `0007`, and at head again.
Seeded through raw SQL, in the shape the two 0006 downgrade tests already use,
because the models describe HEAD and the test has to speak to both sides of one
migration.

### Wording a person will see

None. Every string this step touched is a comment, a docstring or a migration
header; the migration logs only Alembic's own revision line and **prints no row, no
nickname and no token**. The operator- and API-facing wording is M29.4's.

## M29.3b — `infra`: the restore scenario counts rows in `users`

**`tests/e2e/infra/**` carries no *friend* except five `/api/friends` URL paths,
which are M29.4's.** `make test-infra` is unchanged at 1 failed / 240 passed (the
M29.7 runbook quotation) — and that is the point of item 2 below.

1. **The rename broke the scenario in TWO places, not one.** The plan named
   `test_restore_proves_the_backup.py:389` (`rows_in(..., "friends")`). The second
   is S3 at :456: it cuts its damaged dump at `text.rfind("COPY public.friends")`
   and asserts the marker was found, so a post-`0008` `pg_dump` — which writes
   `COPY public.users` — fails it too. **A table rename must be grepped for as a
   `pg_dump` artefact, not only as a query.** The reviewer swept the directory for
   a third such artefact (index, constraint and sequence names, other `COPY`
   markers) and found none.

2. **`make test-infra` never ran this file and cannot have.** It is
   `ruff check tests/infra deploy/warden .e2e` + `pytest tests/infra`
   (Makefile:96-99); `tests/e2e/infra/` is in neither half. So the before/after
   counts are identical (1 failed, 240 passed, the same runbook test) and **the
   zone gate is not evidence for this step** — the only evidence is running the
   scenario. This is M29.2b's item 4 recurring in a second zone: the run/lint gap
   is now confirmed for `infra` as well as `edge`.

3. **The `/api/friends/*` paths in this file are deliberately NOT renamed.**
   `control` still serves them until M29.4. The file therefore reads
   `user = client.post("/api/friends", ...)` — local names in the new vocabulary,
   routes in the old. **M29.4 must re-run this file after flipping the routes**;
   no static target will catch it, and M29.3's item 4 trap applies here too.

4. **Prose in four other `tests/e2e/infra/` files moved too** (9 occurrences in
   `test_a_client_that_sends_no_sni_can_reach_the_sites.py`,
   `test_caddy_discards_access_logs.py`, `test_panel_bootstrap.py`,
   `test_the_console_is_not_on_the_public_site.py`) — comments and assertion
   messages only, no executable change. `test_caddy_discards_access_logs.py`'s
   own assertions are byte-for-byte unchanged, verified: it still proves what it
   exists to prove.

### How to test what M29.3b built

The zone gate does not execute it. What does, with docker and nothing else:

```sh
.venv/bin/python -m pytest tests/e2e/infra/test_restore_proves_the_backup.py -q   # 3 passed, 2-3 min
.venv/bin/python -m ruff check tests/e2e/infra/                                   # no Make target does this
```

**It needs no `make e2e-up`.** The file installs two disposable compose projects of
its own (`hashi-restore-src-<run>` / `-dst-<run>`) through
`scripts/panel-bootstrap.sh` on ports **54300/54301/54305** — a third block, clear
of dev (541xx) and e2e (542xx) — with an env file it generates in `tmp_path`
(`env_file()`, which doubles every `$` so the scrypt hash survives compose
interpolation). **It never reads the repository `.env`**: every invocation passes
`--env-file` or sets `ENV_FILE` explicitly, overriding `panel-bootstrap.sh`'s own
default — verified line by line, and it matters, because no agent may read that
file. Most of the runtime is image build. `docker volume ls | grep restore` should
be empty afterwards.

### Wording a person will see

None. Every string this step touched is a comment, a docstring or a test assertion
message.
