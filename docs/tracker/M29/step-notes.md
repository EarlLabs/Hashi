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

## M29.4 — `control`: the API and the panel, broken cleanly

**The routes are `/api/users/*` and `/panel/users/*`, with nothing left serving the
old ones.** `make test-control` against a real database: **910 passed, 2 skipped, 0
failed** (the 2 being the baseline `wireguard declares it cannot carry a hop` pair),
ruff clean over `control`, `tests/control` and `tests/e2e/control`.
`tests/e2e/control`: **66 passed**. Live-checked: `/api/friends` and
`/panel/friends` 404; `/api/users` 401 and `/panel/users` 303 — gone, not
auth-gated.

1. **The half-state M29.3 left is closed.** The ORM attribute, the API field, the
   route path parameter, `RevocationOutcome.friend_id`, `RevocationResponse.friend_id`
   and `services/friends.py` (now `services/users.py`, with `get_user` /
   `create_user` / `list_users` / `revoke` / `claim_withdrawal` / `grant_everywhere`
   / `grant_on`) all say `user`. Nothing in `control` mixes the two vocabularies.

2. **A SECOND persisted column value, in the same shape as `TransportPurpose.FRIENDS`
   and on nobody's list.** `AuditAction.FRIEND_ADDED = "friend-added"` and
   `FRIEND_REVOKED = "friend-revoked"` (`models/audit.py:59-60`) are stored in
   `audit_entries.action`, `VARCHAR(32)` since `0003`, read back through `EnumText` —
   so a rename is a data migration, reversible, exactly like M29.4b's. Left
   untouched, member AND value. **M29.4b was widened to cover them**, or M29 would
   close against a value an operator reads on the audit screen.

3. **`panel/wording.py` keeps its `friend` → `user` filter, deliberately, and this is
   the one thing a later grep will misread.** The module exists because decision 9
   made the code's word differ from the page's; M29 reverses that, so the
   substitution now fires on nothing. Removing it means removing `keeping` and the
   quote protection, threaded through ~25 `_mutation(...)` call sites in
   `panel/routes.py` — a redesign of that module, not a vocabulary swap. So
   `control/` still contains the string `friend` in `wording.py` and ~10 test
   literals. **Those are the word being FILTERED, not the word for the concept** (the
   same class as `edge/health/listening.py:36`), and "`control` has no `friend` left"
   is therefore the wrong closing check for M29's second Done-when. Its five tests
   were reframed so none is a no-op — they plant the OLD word and watch the boundary
   still convert it; the reviewer confirmed each tests real behaviour.

4. **A blind swap inverts every forbidden-word assertion, and there are thirteen.**
   `assert "friend" not in _visible_text(...)` becomes `assert "user" not in ...`,
   i.e. the panel must never say `user` — green only because nothing is checked.
   Sites: `test_the_console.py` ×5, `test_every_user_holds_their_own_address.py` ×5,
   `test_a_retired_node_is_never_applied_back_into_service.py`, and two in
   `tests/e2e/control/`. Two forbidden-word TUPLES also collapsed to a duplicate
   entry (`("user", "friend", …)` → `("user", "user", …)`). **Any later bulk rename
   must grep for the old word inside negative assertions before trusting a green
   run.** The reviewer swept the fence for the inverted form and found zero
   survivors.

5. **~28 comments stated decision 9 as live law and became self-contradictory.**
   "the code says friend, the page says user" word-swaps into "the code says user,
   the page says user". Each was rewritten to state the M29 fact. These are the only
   paragraphs in the step that are not word-in-place. **Three of those rewrites
   smuggled in a symbol that does not exist yet** — they cited `` `USERS` `` as a
   live `TransportPurpose` member — and were caught in review and reverted. A
   comment rewrite during a rename can name the future by accident; grep comments for
   symbols, not just code.

6. **The carry-over flake is fixed, not carried.**
   `test_a_daemon_that_did_not_come_back_on_this_config_fails_loudly` was a stale
   identity-map read, exactly where `carry-over.md` said to look:
   `a_node_with_a_transport` sets the node ACTIVE through the TEST's session, the
   apply writes DEGRADED through the request's own session, and
   `expire_on_commit=False` (`control/app/db.py`) makes the closing `get` return the
   stale copy. One `session.expire_all()` before the re-read — this zone's idiom, 98
   occurrences across 22 files, and
   `test_a_retired_node_is_never_applied_back_into_service.py:134-135` is the same
   three lines for the same reason.

   **It is not reachable in production and that was checked, not assumed.** Every
   route gets a new session per request with an empty identity map
   (`control/app/db.py:53-66`), so a `GET` after a `POST` always issues a real query;
   the staleness needs the test harness's two-session setup. The reviewer also
   patched the service to write the wrong state and confirmed the fixed test fails
   loudly, so the assertion still means something.

   **Causation is unsettled and moot.** HEAD failed 5/5, baseline `c3fa3b0` failed
   2/3 — the builder reproduced it at baseline, the reviewer did not. Timing- or
   environment-sensitive either way. The fix belongs in this fence regardless of who
   exposed it.

7. **M29.4a is twice the size its plan text said.** Besides the five `/api/friends`
   sites in `tests/e2e/infra/test_restore_proves_the_backup.py` (237, 240, 331, 404,
   476), **`scripts/security/seed.py` has five more** (157, 160, 166, 173, 188).
   `scripts/**` is the `infra` zone, no static target runs it, and both files 404
   from `e02fbe5` onward. M29.4a was widened to name them.

8. **Records that now cite paths which no longer exist, accepted rather than fixed.**
   `docs/PLAN.md:1130` (`## ✅ M9`) and `:1913` (`## ✅ M17`) name
   `test_a_hop_never_reaches_a_friend.py`; `docs/tracker/M8/step-notes.md:26` and
   `docs/tracker/M9/fix-notes.md:53,134` name `panel/friends_table.html` and
   `hx-push-url="/panel/friends"`. All record. M29.2's item 6 precedent.

9. **`control/app/services/addresses.py:467` keeps "Counts ACTIVE USERS".** English
   emphasis contrasted with "credentials held", not a code reference — and since this
   step renamed the model to `User`, it is now the correct name of the entity being
   counted as well. Reverting it would have been the error. Do not "fix" it.

### How to test what M29.4 built

Two gates, and **the zone's own gate cannot see a route rename at all**:

```sh
docker run -d --name hashi-db -p 127.0.0.1:54132:5432 \
  -e POSTGRES_USER=hashi -e POSTGRES_PASSWORD=replace-me -e POSTGRES_DB=hashi \
  postgres:16.4-alpine
# drop the schema first if it predates this branch:
docker exec hashi-db psql -U hashi -d hashi -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'
make test-control                                  # 910 passed, 2 skipped — CHECK THE SKIP COUNT
make e2e-up
.venv/bin/python -m pytest tests/e2e/control -q     # 66 passed, ~25s
make e2e-down
```

**A full `make test-control` run leaves schema behind that breaks the NEXT run's
seven migration tests** with `relation "…" already exists` — drop the schema between
runs, not only before the first. This cost a whole 7-minute run to diagnose.

`make e2e-up` rebuilds the control image from the working tree, so the 66 scenarios
are the real proof that the panel and the API agree on the new paths. Do not gate on
`make verify` — still red for M29.7's runbook quotation.

### Wording a person will see

- **Routes, and they are the break:** `/api/users`,
  `/api/users/{user_id}/subscription`, `/api/users/{user_id}/revoke`, `/panel/users`,
  `/panel/users/table`, `/panel/users/new`, `/panel/users/{user_id}/subscription`,
  `/panel/users/{user_id}/revoke`. **The runbook's M29.7 sentence — "anything
  scripted against the old paths stops working" — is about exactly these.**
- **API response fields:** `RevocationResponse.user_id` (was `friend_id`). A consumer
  reading the old key gets `None`, silently.
- `"this user has no live subscription"` — `NotFound` from
  `GET /api/users/{id}/subscription`.
- Audit screen sentences: `user {first} added`, `user {first} revoked — link is dead`.
- The Users screen: title `Users`, subtitle *"who can dial the mesh, and the one URL
  each of them holds"*, and *"A user gets one subscription URL covering every serving
  node. Nothing else is stored about them."*
- HTMX events, renamed on both sides: `users-changed`, `users-created`. A template
  still listening for `friends-changed` would silently stop refreshing.

## M29.4a — `infra`: the restore scenario and the audit seed call the routes that exist

**All ten sites move, and both files were RUN, not read.** The five in
`tests/e2e/infra/test_restore_proves_the_backup.py` (3 passed) and the five in
`scripts/security/seed.py` (executed on a real stand, identities read back through
the read-only role) now call `/api/users/*`.

1. **The roles-file key stays `friend_id`, and it is not an oversight.**
   `scripts/security/role.sh` reads `role['friend_id']` out of
   `.acceptance/security/roles.json`, so the key is a two-file contract while the
   locals around it are not. The locals moved to `user_id`; the key did not, with a
   comment at the assignment saying why. **Renaming it means editing `role.sh` in the
   same commit and re-seeding — a stale roles file from an older stand carries the
   old key and would `KeyError`.** M29.4c takes the whole contract at once.

2. **`make test-infra` is now 2 failed / 239 passed, not 1 / 240.** The second failure
   is M29.4's, not M29.4a's, and both agents confirmed it predates this step's
   baseline (`relay.py` is byte-identical across `00ef7da..94cdb53`):
   `tests/infra/test_deploy_runbook.py:1107` walks the AST of `relay.establish_hop`
   for calls to `nodes.friend_facing_on`, which M29.4 renamed to `user_facing_on`.
   The set comes back empty and
   `test_the_growth_path_sends_the_box_that_already_serves_friends_to_the_leaf_end`
   fails. **A rename that a test reaches by `ast`/`inspect` is invisible to a grep
   for the call site — grep for the bare symbol.** M29.4c takes it.

3. **Neither file read `RevocationResponse.friend_id`** — checked rather than
   assumed, by both agents. `revoke()` ignores the body, `token_of` reads `["url"]`,
   creation reads `["id"]`. The silent-`None` failure M29.4 warned about was not
   present in this fence.

4. **Completeness, verified twice.** A grep over `tests/e2e/`, `scripts/`, `deploy/`,
   `.e2e/`, `.github/`, `Makefile` and `tests/infra/` for `api/friends`,
   `panel/friends`, `friends-changed`, `friends-created` and `friends_table` returns
   zero hits, as does one for `COPY public.friends`, `friends_pkey`,
   `friends_nickname_key` and the old index and constraint names.

### How to test what M29.4a built

The zone gate executes **neither** file. What does:

```sh
.venv/bin/python -m pytest tests/e2e/infra/test_restore_proves_the_backup.py -q  # 3 passed, ~2-3 min
.venv/bin/python -m ruff check tests/e2e/infra/ scripts/security/seed.py         # no Make target does this

scripts/security/stand.sh up     # = acceptance stand, browser off, + seed.py; ~2 min
.venv/bin/python scripts/acceptance/query.py \
  "SELECT nickname, revoked_at IS NOT NULL AS revoked FROM users ORDER BY nickname"
scripts/security/stand.sh down
```

`stand.sh up` prints `[seed] 3 friends seeded (…), one of them revoked` — **a green
line is not the proof**, because a seed that 404s exits 1 and takes `stand.sh` with
it, while a half-seeded one would not. Read the three rows back through `query.py`'s
read-only role instead; that is the stand's own truth source and the audit's. Verify
the boundary the way it broke: anonymous `curl` gives 404 on `/api/friends` and 401
on `/api/users`.

**`role.sh <role>` prints a bearer token to stdout — redact it before it reaches a
transcript**; nothing in a report may carry one. Both stands are self-contained: the
restore scenario builds its own projects on 54300/54301/54305, the security stand is
the e2e stand on 54200/54232, and neither reads the repository `.env`.

### Wording a person will see

None new. Every string changed is an operator-facing failure message inside a script
that only ever runs against a disposable stand. The audit's role names an agent types
— `anon`, `operator`, `friend_a`, `friend_b`, `friend_revoked` — are **unchanged**,
so a prompt or threat-model page naming them is still correct until M29.4c.

## M29.4b — `control`: the two persisted words a person reads

**The values are `users`, `user-added` and `user-revoked`, and they reverse exactly.**
`make test-control` against a real database: **913 passed, 2 skipped, 0 failed**,
ruff clean. `tests/e2e/control`: **66 passed**. This is the only step in M29 that
wrote to rows, and every claim below was reproduced by the reviewer independently.

1. **`0009_the_stored_words_a_person_reads.py`, revision `0009` on `0008`: four
   guarded `UPDATE`s plus one `SET DEFAULT`.** `TransportPurpose.FRIENDS = "friends"`
   → `USERS = "users"`, `AuditAction.FRIEND_ADDED` / `FRIEND_REVOKED` → `USER_ADDED =
   "user-added"` / `USER_REVOKED = "user-revoked"`, member AND value, with every
   comparison. No column changes type, width or nullability; nothing is renamed; no
   encrypted column is opened.

2. **NEITHER COLUMN IS A NATIVE POSTGRES `ENUM`, established rather than assumed.**
   `node_transports.purpose` is `character varying(16)` (`0002` wrote a plain
   `sa.String(16)`); `audit_entries.action` is `character varying(32)` (`0003`, read
   back through `EnumText`, which is Python-side only by design).
   `SELECT count(*) FROM pg_type WHERE typtype='e'` is **0** for the whole database.
   So no `ALTER TYPE … RENAME VALUE` anywhere, and a later step adding a member needs
   no migration.

3. **The `server_default` moves with the values, and nothing static would have caught
   it.** `0002` wrote `server_default="friends"` on `purpose`; the model declares only
   a Python-side default, and `test_migrations.py` runs `compare_metadata` with
   `compare_server_default` **off**. A row inserted without an explicit `purpose` by a
   restore, a seed or a `psql` session would otherwise arrive holding a retired word.
   The reviewer checked it the hard way, inserting a row with `purpose` omitted at
   each of the three states. **Any later value rename must check the DDL default
   separately from the model.**

4. **"Needs no `HASHI_SECRET_KEY`" means "needs no REAL key" — M29.5 must know the
   difference.** `control/migrations/env.py` builds the whole `Settings` object to get
   the URL, and `Settings` refuses a `secret_key` under 32 characters, so
   `HASHI_SECRET_KEY=''` dies on a Pydantic `string_too_short` **before Alembic
   touches the database** — which looks exactly like a migration failure and is not
   one. Any 32-character placeholder works, because neither `0008` nor `0009` opens an
   encrypted column. `HASHI_OPERATOR_PASSWORD_HASH` must likewise be a real-shaped
   scrypt string.

5. **Two cases decided in the migration header rather than discovered later.** A value
   that is neither the old nor the new one is **left exactly as found** — every
   statement carries a `WHERE`, so `relay-entry`, `relay-leaf`, `node-added` and an
   undeclared value survive both directions. Refusing on one would abort the `alembic
   upgrade head` that `deploy/docker/entrypoint.sh` runs on EVERY boot, over a row the
   application already cannot read back. An **empty table is a no-op**, and the
   statements are self-idempotent because the `WHERE` matches nothing on a second pass.

6. **The downgrade is exact, not approximately exact, and here is why it can be.** The
   new values could not have existed before the upgrade: `EnumText` raises on an
   undeclared value at the WRITE for `action`, and for `purpose` — which is a plain
   `String(16)`, enforced by application discipline rather than by the column type —
   `purpose=` is set only from `TransportPurpose` members throughout the services. So
   every row the downgrade moves back is a row the upgrade moved. **A later value
   rename that cannot make that argument is not reversible by a `WHERE` and needs a
   different design.**

7. **`AuditAction`'s docstring warned that a changed value orphans every row already
   written, and it now says these two changed anyway, once, with `0009`.** The rule
   stands; the price was paid deliberately, and the `UPDATE` is what avoided the
   orphaning.

8. **M29.4's item 5 is closed.** The three comments its review reverted to
   `` `FRIENDS` `` because `USERS` did not yet exist — `services/nodes.py:280`,
   `rotation.py:643`, `users.py:150` — now say `` `USERS` ``, which this step is what
   makes true.

9. **Nothing outside `control` referenced either enum.** Grepped `tests/infra/`,
   `tests/e2e/infra/`, `tests/edge/`, `edge/`, `scripts/`, `deploy/`, `.e2e/`,
   `.claude/` and `docs/` for `FRIEND_ADDED`, `friend-added`, `friend-revoked` and
   `TransportPurpose`: zero hits outside this step's own plan text. M29.4c and M29.7
   inherit nothing from this step.

### How to test what M29.4b built

```sh
docker run -d --name hashi-db -p 127.0.0.1:54132:5432 \
  -e POSTGRES_USER=hashi -e POSTGRES_PASSWORD=replace-me -e POSTGRES_DB=hashi postgres:16.4-alpine
docker exec hashi-db psql -U hashi -d hashi -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'
.venv/bin/python -m pytest tests/control/test_migrations.py -q   # 9 passed, ~18s, no app stack
make test-control                                                # 913 passed, 2 skipped — CHECK THE SKIP COUNT
make e2e-up && .venv/bin/python -m pytest tests/e2e/control -q && make e2e-down   # 66 passed
```

**Drop the schema between full runs**, still — M29.4's warning is unchanged.

The two new tests, which a later step extends rather than rewrites:

- `test_the_stored_words_go_forward_and_back_with_every_other_row_untouched` seeds rows
  **at `0008`, in the old vocabulary**, because that is the only way to watch an
  `UPDATE` move them — a schema comparison cannot see a value migration at all. It
  plants three kinds of row per column on purpose: one the rename covers, one from the
  same column's other members, and one nothing ever declared; the last two are what the
  migration must NOT touch. It also asserts the DDL default in all three states and
  asserts `data_type = 'character varying'` for both columns, which is item 2 pinned.
- `test_the_data_migration_names_no_row_in_what_it_prints` plants a nickname in
  `first_label` and asserts it appears in neither direction's stdout or stderr. The
  audit table is the one place a well-meant `logger.info(row)` turns a trail that holds
  no identity into a boot log that names a person.

**Seeding trap, cost one run:** `node_transports` carries
`uq_node_transport_config_name` over `(node_id, config_name)`, so several rows on one
node need **one `config_name` each**. The pre-existing downgrade tests each seed a
single row and so never met it.

**The schema diff is necessary but NOT sufficient here, and that is the whole
difference from `0008`** — it is empty even if every value is wrong. Compare the rows.
The strongest evidence is the stand's own database after `tests/e2e/control`, written
by the running application: `user-added` ×33, `user-revoked` ×4, `purpose = users` ×35.

### Wording a person will see

- **Stored values an operator can reach:** `user-added` and `user-revoked` in
  `audit_entries.action`, `users` in `node_transports.purpose`. `purpose` is returned
  verbatim by the API as `HopEndResponse.purpose` — **a consumer matching on the
  literal `"friends"` silently matches nothing.**
- The rendered audit sentences are **unchanged**: `user {first} added` and `user
  {first} revoked — link is dead` already said *user* (`panel/wording.py`). Only the
  key they are looked up by moved.
- The two `tests/e2e/control/` scenarios list every stored action as a literal, by
  design — `PERMITTED_ACTIONS` and `STORED_KEYS`. **A new action is written down
  twice, once in the enum and once there**, and that duplication is the point.

## M29.4c — `infra`: the scripts, and the test that reached into `control` by AST

**`scripts/**` carries no *friend*, and the security stand's cross-file contract moved
whole.** `make test-infra` went from **2 failed / 239 passed to 1 failed / 240
passed**; the one left is `test_the_runbook_quotes_the_refusal_a_node_without_a_resolver_gets`,
M29.7's, and it is now the only red test in this zone.

1. **The AST test is fixed and the lesson generalises.**
   `tests/infra/test_deploy_runbook.py` matches `node.func.attr == "user_facing_on"`
   now. **A symbol a test reaches by `ast` or `inspect` is invisible to a grep for its
   call site** — grep for the bare symbol name after any rename in `control` or `edge`.

2. **The role names ARE renamed: `user_a`, `user_b`, `user_revoked`.** M29.4a's item 1
   is closed. `seed.py`'s `FRIENDS`→`USERS`, the `audit-friend-*` nicknames →
   `audit-user-*`, the `roles.json` key `friend_id`→`user_id`, `role.sh`'s read of it
   and its usage line, `stand.sh`'s banner, and `aikit.yml`'s four `security.roles`
   entries — **one commit**, because a half-renamed contract is a stand that seeds
   nothing and an audit that finds nothing. `docs/security/threat-model.md` cites no
   role name today, so nothing downstream inherits a stale citation. **A roles file
   from an older stand carries the old key**, so a leftover
   `.acceptance/security/roles.json` must be deleted and re-seeded, not reused.

3. **`tests/infra/` is NOT finished, and roughly half of what is left CANNOT move
   until the documents do — verified by the reviewer, not merely claimed.**
   `test_deploy_runbook.py:779` and `:1187` do `if "friend-facing" in step` over
   `docs/deploy/runbook.md`'s own text, and
   `test_the_charter_states_what_the_scripts_deliver.py` quotes the charter's own
   prose (*"a friend's packets move…"*). **Renaming them before the documents move
   turns the gate red against a document nobody has reworded.** `docs/**` belongs to
   no zone, so a diff may carry the documents and these assertions together —
   **M29.7 was widened to take both in one commit.**

4. **Accepted residual, named so a later grep does not read it as an oversight**
   (review round 1, Low): pure docstrings still saying *friend* in
   `test_backup_script.py:51,75`, `test_panel_bootstrap_script.py:99,197,338`,
   `test_the_charter_states_what_the_scripts_deliver.py`,
   `test_management_tunnel_script.py`, `test_caddyfile.py` and `test_drive.py`. None
   is an assertion; nothing is functionally wrong. **M29.7 sweeps them with the
   documents.** `test_drive.py:194` says "a friendly" — English, a deliberate keep,
   same class as `edge/health/listening.py:36`.

5. **Two prose residuals outside this fence.** `aikit.yml` :191, :194 and :268 still
   say *friend* — :268 is the comment directly above the now-`user_*` roles list — and
   `deploy/docker-compose.e2e.yml:40` still says *"no real friends in it"*, the
   sentence `seed.py` and `scripts/acceptance/stand.sh` both mirror. Nothing parses
   either. **M29.7 was widened to take both.**

### How to test what M29.4c built

`make test-infra` proves item 1 and nothing else — **no target runs a single line of
`scripts/`**, which is the third zone this gap has appeared in (M29.2b item 4, M29.3b
item 2). What does:

```sh
scripts/security/stand.sh up          # acceptance stand, browser off, + seed.py; ~2 min
.venv/bin/python scripts/acceptance/query.py \
  "SELECT nickname, revoked_at IS NOT NULL AS revoked FROM users ORDER BY nickname"
scripts/security/stand.sh down

.venv/bin/python -m pytest tests/e2e/infra/test_restore_proves_the_backup.py \
  tests/e2e/infra/test_panel_bootstrap.py -q     # 10 passed, ~3.5 min — the only thing
                                                 # that executes backup.sh and panel-bootstrap.sh
.venv/bin/python -m ruff check scripts/security/seed.py scripts/acceptance/query.py
bash -n scripts/*.sh scripts/*/*.sh              # the shell half has no linter here
```

**The rows are the proof, not the `[seed]` line** — a seed that 404s exits 1 and takes
`stand.sh` with it; a half-seeded one does not. Stronger and cheap: compare every
`user_id` in `.acceptance/security/roles.json` against `users.id`, and check the
charter's revocation promise directly — live `/sub/…` **200**, revoked **404**,
never-issued **404**. Indistinguishable, which is the promise.

**`role.sh <role>` prints a bearer token to stdout — redact before quoting anywhere.**

### Wording a person will see

- `scripts/acceptance/stand.sh`: *"The control plane is empty — no nodes, no
  transports, no **users**, no hops."*
- `scripts/security/stand.sh` banner: `Roles  anon, operator, user_a, user_b, user_revoked`.
- `scripts/security/seed.py`: `[seed] 3 **users** seeded (audit-user-a, audit-user-b,
  audit-user-revoked), one of them revoked`.
- `scripts/backup.sh`, during a restore: *"Every current node, **user** and credential
  is overwritten by the dump"*, and *"If **users** cannot connect afterwards,
  HASHI_SECRET_KEY does not match…"*. `scripts/panel-bootstrap.sh`'s firewall refusal:
  *"this host is the one **users** dial for their subscriptions"*.

## M29.5 — the migration run against a copy of real data

**`0007`→`0008`→`0009`→`0007` is proven on real rows, and the copy is destroyed.**
The subject was a dump of a live control plane, restored onto a disposable local
stand, migrated both ways, served to a logged-in panel in both states, then shredded.
Nothing was committed; no defect was found in `0008` or `0009`. Every claim below was
independently re-checked by the reviewer.

1. **The live control plane was at `0002`, not `0007` — measured, and it changes what
   a rehearsal means.** Its control image predates `0003` (no `audit_entries` table,
   container up since 2026-09-09), and since `deploy/docker/entrypoint.sh:45` runs
   `alembic upgrade head` **unconditionally on every boot**, `0002` IS that
   deployment's head. The copy was walked `0002`→`0007` on the real chain before
   `0008` was touched. **Never assume a deployed chain is at the repository's head
   minus this milestone; ask `select version_num from alembic_version` first.**

2. **"Needs no `HASHI_SECRET_KEY`" is now measured, not argued.** md5 over every
   encrypted column — `subscriptions.token`, `token_digest`, `credentials.subject`,
   `credentials.secrets`, `node_transports.secrets`, `nodes.ssh_private_key` — is
   byte-identical at `0002`, at `0007`, at head and back. M29.4b item 4's empty-key
   trap reproduced exactly: `HASHI_SECRET_KEY=''` dies on a Pydantic
   `string_too_short` (`control/app/settings.py:48`, `min_length=32`) inside
   `env.py`'s `Settings()` call, **before Alembic opens a connection**.

3. **The real data carried the mixed `purpose` case the tests had to fabricate.**
   `friends`=3, `relay-entry`=1, `relay-leaf`=1 → `users`=3 with both relay values
   untouched, and back. The DDL default moved `'friends'`→`'users'`→`'friends'` with
   them. M29.4b items 3 and 5, confirmed on real rows rather than fixtures.

4. **`audit_entries` is EMPTY on a real control plane**, so half of `0009` proves
   nothing against real data. It was exercised by seeding five rows at `0007` in the
   old vocabulary on the same copy: `friend-added`×2 and `friend-revoked`×1 became
   `user-added`/`user-revoked`, while `node-added` and an undeclared value survived
   both directions. **Any later value migration rehearsed against real data must check
   whether the column it renames has any rows at all before calling the run evidence.**

5. **A WRONG KEY AND A BROKEN MIGRATION LOOK NOTHING ALIKE, and the 409 is how you
   tell.** A control plane serving a restored database with a foreign key answers
   `409 secrets_unreadable` — *"The data is intact; the key is wrong. Nothing has been
   changed."* — on every screen that loads a user or a node, because
   `User.credentials` and `User.subscriptions` are `lazy="selectin"`
   (`models/user.py:45,48`) and `EncryptedText.process_result_value`
   (`models/base.py:104-107`) decrypts at result materialisation, which only runs
   after the `SELECT` has found the table. A migration fault raises
   `UndefinedTable`/`UndefinedColumn` at the driver, first. **Do not report one as the
   other.**

6. **To see the panel actually work, re-key the copy — do not chase the owner's key,
   and keep the boundary explicit.** All migration evidence, and the Users and Nodes
   screens, were recorded on the owner's **untouched** ciphertext: those screens read
   only plaintext columns (nickname, node name, address, timestamps, `purpose`,
   `state`, `revoked_at`). Only the decryption-dependent screens needed the six
   encrypted columns overwritten with ciphertext of substitute plaintext under the
   stand's own key. **"The panel works" is therefore two claims, not one, and
   collapsing them into a single sentence would overstate it.** Expect
   `could not render node … for the drift cell` afterwards: that is the substitution,
   not the migration.

7. **A rollback to `0007` does not survive a container restart.** Database at `0007`,
   `compose up -d control` on the current image → `Running upgrade 0007 -> 0008`,
   `0008 -> 0009`. `deploy/docker/entrypoint.sh:45` is unconditional by design, so
   rolling the schema back without rolling the image back is undone by the next boot.
   **M29.7's runbook sentence about the break must say this.**

8. **`scripts/panel-bootstrap.sh` refuses to install on a host whose `ufw` logging is
   on**, including a developer workstation. That is the charter rule, not a bug. Bring
   a stand up with `docker compose -f deploy/docker-compose.yml -f
   deploy/docker-compose.dev.yml -f <plain-http overlay>` rather than turning a
   firewall's logging off to get past it.

### How to rehearse a migration against real data

Nothing was built. What this step established, for whoever does it next:

```sh
# 1. The dump, read-only, without reading an env file anywhere. NOTE: backup.sh uses
#    `docker compose exec -T`; a bare `docker exec` has no -T and will fail.
ssh <host> 'U=$(docker exec <db-container> printenv POSTGRES_USER | tr -d "\r\n")
            D=$(docker exec <db-container> printenv POSTGRES_DB   | tr -d "\r\n")
            docker exec <db-container> pg_dump --username="$U" --dbname="$D" \
              --clean --if-exists --format=plain | gzip -9' > copy.sql.gz

# 2. A disposable stand: own env file, own throwaway key and operator password,
#    loopback ports outside the dev (541xx) and e2e (542xx) blocks.
docker compose --env-file <scratch>/x.env -p <project> \
  -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml -f <plain-http>.yml up -d --build
docker compose … exec -T db psql -U hashi -d hashi -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'
ENV_FILE=<scratch>/x.env COMPOSE_PROJECT_NAME=<project> FORCE=1 scripts/backup.sh restore copy.sql.gz
```

**Drop the schema before restoring**: a pre-`0008` dump's `DROP TABLE IF EXISTS
friends` cannot remove the `users` table the stand's own boot just created, and `0008`
then fails with `relation "users" already exists`.

**Census by counts, histograms and md5 — never by printing a row.** The dump's
plaintext is a map of the fleet: every node address, how many users there are and when
each arrived. `md5(string_agg(col, '|' order by id))` per encrypted column is the whole
proof that a migration never opened one, and it names nobody.

**To serve the PRE-migration panel, export the old code rather than branching:**
`git archive <baseline> | tar -x -C <scratch>/pre`, then run uvicorn from there with
`HASHI_DATABASE_URL` pointing at the stand's published port. No worktree, no branch,
no second image build.

**Destroy with `compose down -v`, then shred every scratchpad file** — and check
`docker volume ls` and `docker images` for the project name afterwards.

## M29.6 — the promise to somebody's phone, as a test that can go red

**A subscription issued before the rename still resolves, returns the same material
and keeps the same token — asserted, not argued.** `make test-control` against a real
database: **914 passed, 2 skipped, 0 failed**, ruff clean. One new file, no product
code touched. The reviewer reproduced three deliberate breaks, one of its own
choosing.

1. **`tests/control/test_a_subscription_issued_before_the_rename_still_resolves.py`,
   one test, 4 seconds.** Two serving nodes (one URI-shaped transport, one file-shaped
   with an address per user), one user who keeps their link and one who is revoked,
   then `head → 0007 → head` underneath both. Three claims, three assertions: **200**
   on `/sub/{token}`, the SHA-256 of the body AND of the `?format=client-config-file`
   archive unchanged, and `/api/users/{id}/subscription` still ending in the same token
   with still one subscription row per person. The revoked link must still **404** —
   without it, a migration that resurrected withdrawn subscriptions passes everything
   else.

2. **THE PRE-MIGRATION WORLD IS BUILT BY THE DOWNGRADE, and that is checkable where
   hand-seeding is not.** Seeding a `friends` table by raw SQL (M29.3's pattern) cannot
   produce ciphertext for the encrypted columns without reimplementing the secret box,
   and leaves the "same material" claim with no baseline, because the application
   cannot read a `0007` schema at all. Issuing at head and pushing the row back gives
   both — and between the downgrade and the upgrade the test asserts the row really is
   in `friends`, under `friend_id`, on a transport whose `purpose` reads `friends`.
   **Not circular**: the comparison is against a response captured at head *before the
   downgrade*, so it is a genuine before/after over the whole round trip.

3. **Bodies are compared by DIGEST, never by bytes.** A failing
   `assert a.content == b.content` puts both operands into pytest's report, and those
   bytes are the user's key material. Same rule as M29.5's census. The eleven-column
   census (`md5(string_agg(col ORDER BY id))` over `subscriptions`, `credentials`,
   `node_transports`, `nodes`) is M29.5's by-hand md5 proof turned into an assertion; it
   works unchanged on both sides of `0008` because those tables keep their NAMES — only
   the foreign key column is renamed.

4. **`httpx` logs the bearer path and `control` does not — and the mute is
   load-bearing.** `httpx._client` writes `HTTP Request: GET
   http://control.test/sub/<token>` at INFO. With the mute deleted, the reviewer
   confirmed pytest's "Captured log call" section printed a **live token in
   plaintext**. Muted to WARNING inside the test rather than exempted from an
   assertion, so deleting the mute goes red.

   **The rest of `tests/control/` was swept and is NOT exposed today**: only this file
   and `test_revocation_push.py` call `caplog.set_level`, the latter never fetches
   `/sub/`, and nothing in `pyproject.toml` raises the default log level. On the
   application side, `api/delivery.py` has no logger call at all, `main.py:55` disables
   `uvicorn.access`, and the error handlers log `exc.code` and the endpoint name, never
   the path.

5. **A revocation in this zone degrades every node, and that silently empties the other
   user's subscription.** No node here has an SSH key, so the re-push a revocation fans
   out cannot land and both nodes go DEGRADED — at which point the surviving user's
   document renders EMPTY and every byte comparison compares nothing to nothing and
   passes. The test puts both nodes back ACTIVE after the revoke and asserts the
   document is non-empty before it measures anything. **Cost one debugging round; any
   later test that revokes one user and then reads another's subscription hits it.**

6. **The teardown drops tables by introspection, not through `Base.metadata`.** The
   metadata describes head and has never heard of `friends`; this is the one file that
   deliberately leaves the database calling the table that. A red run between the
   downgrade and the upgrade would leave `friends` standing, `drop_all` would walk past
   it, and the next run would die on `relation "friends" already exists` from `0001` —
   M29.3's "bites every developer once" trap, on every red run. Reproduced and fixed.
   **Cost: copied into a file sharing a database with a parallel run, it drops
   everything in the schema, not only the models' tables.**

7. **It imports `run_alembic` from `.test_migrations`** — the first cross-test-module
   import in this zone, taken rather than keeping a second copy of the subprocess
   command the container entrypoint uses. Moving or renaming `run_alembic` now breaks
   two files.

### How to test what M29.6 built

```sh
docker run -d --name hashi-db -p 127.0.0.1:54132:5432 \
  -e POSTGRES_USER=hashi -e POSTGRES_PASSWORD=replace-me -e POSTGRES_DB=hashi postgres:16.4-alpine
docker exec hashi-db psql -U hashi -d hashi -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'
.venv/bin/python -m pytest \
  tests/control/test_a_subscription_issued_before_the_rename_still_resolves.py \
  tests/control/test_migrations.py -q          # 10 passed, ~22s, no app stack
make test-control                              # 914 passed, 2 skipped — CHECK THE SKIP COUNT
```

**Red-first, breaks that are known to work** (inject, run, then
`git checkout -- control/migrations/versions/`): `UPDATE friends SET revoked_at =
now()` in `0008` → *"stopped resolving after it"*, 404 vs 200; `UPDATE nodes SET
location_label` in `0009` → *"returned different bytes"*, two digests and no material;
`UPDATE subscriptions SET token_digest = md5(token_digest)` → the census tripwire
naming the column; an `INSERT … SELECT` reissuing every subscription → `assert 4 == 2`
on the row count; and `UPDATE subscriptions SET token = token || 'X'` in `0009` → the
census, catching a token-identity break before the panel is even re-queried.
**The census fires before the fetch assertions for anything it covers** — deliberate,
and why isolating the token assertion needs `subscriptions` lifted out of
`CARRIED_MATERIAL`.

### Wording a person will see

None. Every string in this step is a test docstring or an assertion message; nothing
reaches an operator, a panel screen, an API response or a log line.

## M29.7 — the living documents, and the gate goes green

**`make verify` is green: exit 0** — reproduced independently by the reviewer. control
`219 passed / 697 skipped` (no Postgres, the baseline shape), edge `911 passed /
3 skipped` (`awg-quick` absent, baseline), infra **`241 passed, 0 failed`** (was
1/240), e2e **`192 passed`**. M29.2's item 3 seam is closed and item 2's warning no
longer describes the tree.

1. **The records were proven untouched by diff at the START and at the END**, and
   again by the reviewer against baseline `1b60280`. All three commands printed
   nothing every time, and `git diff --name-only 1b60280..HEAD` over
   `control/migrations/`, `docs/tracker/` and `docs/decisions.md` returns only *added*
   files plus `decisions.md`'s appended rows. **Decision 9 — the owner's 2026-09-08
   answer that `friend` stays the word — is intact**, with M29's reversal recorded as
   an appended row dated 2026-09-22 rather than as an edit to it. **Run the check at
   both ends; a failure at the end is then known to be yours.**

2. **The plan's open milestones split into two classes and only one moves.** A *use* of
   the word (M24, M26, M27, M28 — 22 sites) is reworded. A *mention* is not: **M29's
   own `## →` section is 62 occurrences and every one names the identifier being
   renamed**, so a word swap would make the milestone specify renaming `user` to
   `user`. It also becomes a record the day M29 is ✅. Same reasoning kept
   `docs/PLAN.md:3108`, a dated quotation. **A later bulk rename over an open milestone
   must sort mention from use before it swaps anything.**

3. **`## Where things stand` is classified by nothing and was left alone.** In neither
   the plan's living list nor the records table's three slices. By the document's own
   test it reads living, and it holds **10** occurrences. M29.8 takes it.

4. **The runbook's new `## Upgrading an install that predates the rename` section is
   where the break lives.** It carries the before/after route table,
   `RevocationResponse.user_id` and the silent `None`, what `0008` and `0009` each do,
   the reversal, and **M29.5 item 7: a schema rollback does not survive a restart,
   because `deploy/docker/entrypoint.sh` runs `alembic upgrade head` unconditionally on
   every boot — roll the image back FIRST, then the schema, and check
   `select version_num from alembic_version` afterwards.** The section deliberately
   keeps 21 occurrences of the old word: a break table that does not name the old paths
   is not a break table.

5. **`_flat(NO_RESOLVER)` is asserted word for word and nothing else in the document
   is.** The runbook quotes four operator-facing strings; only this one, `TUNNEL_TAKEN`'s
   placeholder-free tail and `console.removal_summary`'s cost clause are pinned. **Any
   later rewording in `edge.egress` or `control.services.placement`/`console` turns
   `make test-infra` red against a document nobody edited** — that is the seam, by
   design.

6. **A docstring quoting a RETIRED runbook bullet was rewritten, not word-swapped.**
   Swapping falsifies a quotation of what a page used to say; the rewrite describes the
   retired rule instead. The original sentence survives in `git show` and in the plan's
   ✅ M15 section.

6b. **The narrowing that removed the retired word from a regex opened a silent skip,
   and review would not carry it.** `test_every_shape_that_adds_a_user_applies_afterwards`
   loops per shape and `continue`s past one it cannot recognise, so tightening
   `add (?:a )?(?:friend|user)` to `add (?:a )?user` meant a reverted step would go
   **uncovered rather than red**. Fixed in round 1 by bracketing the loop with two
   assertions that each fail on their own: no step may match the retired
   `add a friend` form (catches a reversion, **including a partial one**), and at least
   one shape must have matched at all (catches a rewording into a third form that would
   leave the whole test a no-op). The reviewer proved each is load-bearing — under a
   partial reversion the general check stays green at `covered = {'C'}` and misses it.
   **`docs/decisions.md` names "a verification that cannot fail" as this repository's
   signature defect — around seventeen instances — so any later rename that tightens a
   regex a test SKIPS on must add the assertion in the same diff.**

7. **The charter's one-liner is duplicated in two files nothing compares.**
   `project.json:3` and `deploy/warden/warden.py:320` both still carried *"for its
   owner and ~30-50 friends"*. M29.8 takes them.

### How to test what M29.7 built

```sh
make test-infra    # 241 passed, ~4s — ruff + pytest tests/infra
.venv/bin/python -m pytest tests/infra/test_deploy_runbook.py -k "quotes_the_refusal" -q   # 2 passed, <1s
```

There is nothing to fixture: every test here reads files and imports `control`/`edge`,
so a documentation change is executed by the suite the moment it runs. `make verify` is
the milestone's Done-when, ~8–15 minutes, and needs a docker engine and **no Postgres
on 54132** — the control zone's 697 skips are the baseline shape, not a regression.

### Wording a person will see

- **The charter's one-liner:** *"A self-hosted, multi-protocol VPN for its owner and
  ~30–50 users"*, followed by a new paragraph stating plainly the three things
  `friends` used to carry on its own: **no public signup**, **no payments and no
  billing**, **never advertised** (art. 14.3 KoAP). `CLAUDE.md` and `README.md` match.
- **The break, as the owner asked for it:** *"**Anything scripted against the old paths
  stops working** the day this lands. There is no alias, no redirect and no deprecation
  window — the old paths answer `404`."*
- **The rollback sentence:** *"**A schema rollback does not survive a restart** …
  **Roll the image back first, then the schema**, in that order."*
- The runbook says *user-facing transport* everywhere it said *friend-facing*; two
  `tests/infra` step filters key off that exact hyphenated string, so **a shape
  reworded away from "user-facing" turns the gate red**.

## M29.8 — the last places a person reads the old word

**`make verify` is green: exit 0** — control `219 passed / 697 skipped` (no Postgres,
the baseline shape), edge `911 / 3 skipped`, infra `241 passed`, e2e `192 passed`. The
same shape M29.7 reported, unchanged by this step.

1. **The record check is now FOUR commands, not three.** Check 4 was added to
   `docs/records-and-living-documents.md`: the same `awk` slice idiom against
   `docs/product/backlog.md`'s `## Журнал решений`. Copy all four; do not re-derive
   them. All four printed nothing at both ends, against baseline `1b60280` — the
   milestone's branch point, not the step's.

2. **`docs/product/backlog.md` is settled and M29.1's carry-over is closed.** The
   journal is a record; the roadmap above it is living. **An id moves too** — the
   backlog's own header calls ids, zones, dependencies and statuses *«изменяемое
   состояние»* and freezes only the goal and acceptance **text** in `research.md` §3.
   The one exception is an id that is *also a heading in that frozen §3*:
   `control-node-and-friend-records` is (`research.md:1026`) and keeps the old word;
   `control-per-friend-tunnel-address` was not — zero hits in `research.md`, filed by
   the backlog under *«Заведено во время исполнения очереди»* — and became
   `control-per-user-tunnel-address`. **The test is the frozen counterpart, not the
   `done` status and not that the string is written in code font.** Review round 1
   caught the exception being applied one row too wide on the strength of a premise
   verified on the other row; **check each id against the frozen document
   individually.**

3. **The Russian noun `друг` in the backlog is unswept, and the reason is an open
   question rather than a rule.** Only two or three sites have a line-based defence:
   the M2 milestone heading is verbatim-identical to the frozen criterion at
   `research.md:382` and `:809` (verified by direct comparison, twice). The other ten —
   lines 165, 214, 237, 273, 301, 361, 368, 370, 423, 456 — are ordinary retrospective
   prose with **no record/living argument at all**; item 33's note reads *"AmneziaWG
   как user-facing транспорт … для одного друга на узел"*, one word swept and the other
   left in one sentence. They stay because **the owner settled an English word and
   nobody has asked whether that reaches a second document's Russian vocabulary.**
   That question is with the owner. **Do not close it inside a step.**

4. **`## Where things stand` is living, and the reason it was missed is that it opens
   on a date.** *"Run stopped by the owner on 2026-09-16"* made it look like the two
   dated record sections beside it. **A date at the top is not what makes a record** —
   the test is whether the section is rewritten when the facts change, and this one is.
   All 10 occurrences moved; the check-2 `awk` slice needed no change, because its
   accumulator turns on only at the three record headings.

5. **`pyproject.toml:19` quotes `00-core-invariants.md` §2 and the quotation is now
   stale.** The invariants say *"every user is locked out"*; the dependency comment
   still says *friend* and cites §2. Two more of the same shape at `:16` and `:23`.
   `pyproject.toml` is architect territory, so M29.8 named it rather than editing it.
   **A stale quotation is arguably worse than a stale noun, because quote marks carry
   an implicit claim of current accuracy** — a reader who trusts them will misquote the
   invariants back. One line each; it needs one architect decision.

6. **The charter's one-liner is now identical in three files and still nothing compares
   them.** `docs/product/charter.md`, `project.json:3`, `deploy/warden/warden.py:320`.
   The classification document now says all three move together, but that is prose, not
   a test. **If a fourth copy appears, nothing will catch the drift.**

### How to test what M29.8 built

```sh
make test-infra    # 241 passed, ~4s
# plus the FOUR record checks from docs/records-and-living-documents.md § "Proving it"
```

Nothing to fixture and no new test: every file here is prose or config the existing
suites already read. **No test reads `docs/records-and-living-documents.md` or
`docs/product/backlog.md`** — grepped across tests, tooling, `.e2e/` and `deploy/` —
so `make verify` is the only gate that covers this step, and it covers it by not
breaking.

### Wording a person will see

- **The one-liner, now in all three copies:** *"A self-hosted, multi-protocol VPN for
  its owner and ~30-50 users: a Russian entry node fronting foreign exit nodes, where
  both nodes and protocols are data."* (`project.json` and `warden.py` use an ASCII
  hyphen, the charter an en dash — deliberate; it was the noun that had to agree.)
- **The threat model's boundary 2** reads *"user A → user B."*
- **The backlog and the runbook both say `user-facing`** where they said
  *friend-facing*. Two `tests/infra` step filters key off the runbook's exact
  hyphenated string.
