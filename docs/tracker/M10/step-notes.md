# M10 — step notes

Conventions established here. They bind later steps, and later milestones in
this codebase, until something supersedes them. Follow them; do not relitigate.

## Read M8's notes first — they bind this milestone

**`docs/tracker/M8/step-notes.md` is the console's rulebook and it binds M9 and
M10 until something supersedes it.** Read it before the first line of any M10
step: how a screen is added (`_screen(...)`, the `NAV` entry, the screen-template
shape, the self-swapping fragment), the mutation rules (`_mutation(...)`,
**OOB swaps are `innerHTML:#slot` and never `hx-swap-oob="true"`**, 422 for field
validation), the CSS vocabulary, **do not add a breakpoint** (there is one, at
900px), and **THE LIST IS THE TEST** —
`tests/e2e/control/test_the_panel_fetches_nothing_from_a_third_party.py`, which
every new screen, dialog or self-refreshing table joins in the same change that
adds it.

**Then read `docs/tracker/M9/step-notes.md`**, which will be ahead of this file:
M9 lands four screens before M10 starts, and anything it settled — the refusal
colour in particular — is the shape M10 matches rather than re-decides.

An implementer who has not read those files will reinvent the console's
conventions, and the reviewer will be right to reject it.

## Decision 8 is answered — both halves — and M10 must not re-open it

The owner answered **yes to both halves** (`docs/PLAN.md`, "Answered by the
owner"; reaffirmed by the owner on 2026-09-10 as settled and not to be
re-litigated):

> **8 — a simple audit log**, and a Settings screen to match.

So M10.3 and M10.4 are in, not conditional. What the milestone's own prose says
about the shape of each still governs, and it is the reason the answer is "a
*simple* one":

- The audit log **records what the operator did, never who dialled what.** It is
  not a connection log. It must hold **no token, no subscription URL and nothing
  about a connection** — that is a "done when" line and it is also the charter's
  one hard record. `tests/control/test_zone_invariants.py::test_no_model_records_anything_about_a_connection`
  already stands over any new model without being asked; the milestone's E2E line
  asks for one scenario asserting the trail contains none of the three.
- **Settings is read-only wherever the value comes from the environment.** There
  is one operator, configured from `HASHI_OPERATOR_USERNAME` /
  `HASHI_OPERATOR_PASSWORD_HASH`; more than one is a charter non-goal ("one
  operator, one fleet"), and there is no log to retain, by construction. **A form
  that saves a value the process only reads from the environment at boot is a lie
  told in a text field** — so the screen shows what this control plane is actually
  configured with and **names where each value is changed** when the panel cannot
  change it. The design's Admins table becomes a single row.
- **Write decision 8 down in `docs/decisions.md`** whichever way it went — that
  is a "done when" line, and the answer being already given does not discharge
  it. The journal's own rule: append at the bottom, never rewrite a line.

## Decisions already taken that M10 must not re-open

- **Decision 9** — the panel says "users"; the code keeps `friend`. No rename
  travels past the rendered page.
- **The test for whether a cell belongs on a screen** (`docs/decisions.md`,
  2026-09-09): *does it move when a friend **connects**?* Operator action may be
  shown; a person's use of the service may not be recorded at all. An audit log
  is exactly the screen where that line is easiest to cross, and it is the reason
  the charter's argument is that such records are **absent, so there is nothing
  to subpoena**.

---

# Established by M10.1 — decision 8's shape

**The decision itself is `docs/decisions.md`, 2026-09-11, two rows. Read them
before you write a line.** This section is a pointer and a summary, not a
substitute — where they disagree, the journal wins.

M10.1 added **no code** except six terms to
`test_no_model_records_anything_about_a_connection` (`last_login`, `source_ip`,
`remote_addr`, `client_address`, `actor_ip`, `user_agent`), which makes two of the
decision's refusals enforceable before the model they guard exists.

## For M10.2 — Settings

- Render the **live `Settings` object** (`control/app/settings.py`), never
  `os.environ`, never `.env`. Shown: subscription base URL, operator username,
  session lifetime, the two node-reach ceilings — each beside its `HASHI_*`
  variable, with **one line saying a change takes effect at the next boot**.
- **A secret is the single word `configured`** — not redacted, not a prefix, not a
  length, not a digest. That is `HASHI_SECRET_KEY`,
  `HASHI_OPERATOR_PASSWORD_HASH`, and the database URL.
- **No form, no save button, no `settings saved` toast, no mesh name.** Nothing
  reads a mesh name. A form that saves a value the process only reads at boot is
  the lie M10's prose names.
- **No audit-retention row.** That arrives with M10.3, which enforces it — a
  retention figure on a control plane with no trail is the same lie in a different
  field.
- **The Admins table is one row**: username, role `operator`, where it is
  configured. **No last login** — dropped, not blanked.
- **Do not name any new module `settings.py`.**
  `test_only_settings_reads_the_environment` keys its allow-list on the
  *filename*, so `control/app/panel/settings.py` would silently exempt itself at
  the one milestone leaning on the rule. That test is also narrower than it looks
  (it greps `os.environ`/`os.getenv` only) — do not lean on it.

## For M10.3 — the trail

- **One append-only table**: a time, an `action`, and **two nullable label
  columns** (a row carries one label or two). That is exactly the set the
  column-whitelist test asserts.
- **`action` is a Python enum through `EnumText`, never a bare `str`** — a value
  nobody declared fails at the **write**, not at review.
- **A label is EQUAL to a value read off an inventory row** (`Node.name`,
  `Friend.nickname`, a transport name, a `NodeState`) — **never composed from
  one.** The concrete hole that rule closes: `Node.state_detail` is 500 characters
  of free text that can carry a remote host's words, and it sits one attribute
  away from `state`, which the decision permits.
- **No `TimestampMixin`** — an `updated_at` on an append-only row invites the idea
  one can be edited.
- **Written by the service, in the same transaction as the change** — never by a
  route (both `/panel` and `/api` mutate through the same services), and **never
  by `/sub/{token}`**.
- **The `/sub/{token}` check is a named deliverable:** M10's e2e scenario
  **fetches a real subscription and then asserts the trail gained no row at all** —
  not merely that no row mentions a token. One tests the write path; the other only
  tests the column set, which the whitelist already covers.
- Recording points, all in `services/`: `friends.create_friend`,
  `revocation.revoke_friend`, `nodes.create_node`, `nodes.enable_transport`,
  `nodes.set_transport_enabled`, `nodes.set_node_state`, `apply.apply_node`
  (success only), `relay.establish_hop`, `relay.dissolve_hop`,
  `rotation.rotate_keys`, `rotation.replace_params`. One helper, one call per
  service.
- **Only changes that committed.** No probes (a probe changes nothing), no logins,
  no failures, no refusals — a refusal's text can come from a remote host and the
  row has nowhere safe to put it.
- **Retention: `HASHI_AUDIT_RETENTION_DAYS`, default 30, bounded 1–365, no value
  meaning "forever"**, swept **hourly** by an `asyncio` task started in the
  application lifespan (`create_app`'s `lifespan` currently only disposes the
  pool — that is where it goes). No new dependency. It sweeps from the lifespan
  and **not only on write**: a trail that expires only when the operator acts is
  not retention on an idle machine. Nothing sweeps while the host is off; that gap
  is stated, not hidden.

## For M10.4 — the screen

- Columns are **time / actor / event**. `actor` is `settings.operator_username`,
  **rendered, not stored**. The design's fourth column, `source`, does not exist.
- Event sentences reuse the existing toast vocabulary (`<nick> added`, `<nick>
  revoked — link is dead`, `config applied to <node>`, …): the **stored value is a
  machine key**, the sentence is rendered in `panel/wording.py`.

## Three things flagged to the owner rather than settled

Each reversible with one line, each recorded in the journal: **the 30-day
default**, **the refused `source` column**, and **the refused `last login`**. The
charter reserves "any change to what data is collected or retained" to the owner;
decision 8 already granted the log and left its shape to this step, so they were
decided rather than blocked on — but they are the three worth a glance.

## Not being added, so the omission is not read as an oversight

The Overview's "Recent activity" card (`design/README.md` §1). No M10 step asks
for it.

---

# Established by M10.2 — the Settings screen

Binds M10.3 and M10.4.

## What it is

A **read-only statement of what this control plane is running with**. One route on
the operator-only `router`, one screen template, rows composed in
`services/console.py` off `request.app.state.settings` — the **live object**,
never `os.environ`, never a file. No form, no save control, no POST beside it.

Shows: subscription base URL (`HASHI_PUBLIC_HOST · HASHI_PUBLIC_HTTPS` — both,
because the URL is composed from both), panel session lifetime, and the two
node-reach ceilings. Durations print in the unit the variable takes with an exact
human reading beside them (`28800 seconds (8 hours)`) — **derived, never
written**. Admins is one row: username / `operator` / `HASHI_OPERATOR_USERNAME`,
**no last login**. No mesh name. **No retention row — that is M10.3's**, and two
assertions in `test_nothing_on_the_settings_screen_offers_to_save_anything` exist
to be **deleted by M10.3** (they assert no row names `RETENTION`). They are the
boundary marker, not an obstacle.

`HASHI_SECRET_KEY`, `HASHI_OPERATOR_PASSWORD_HASH` and `HASHI_DATABASE_URL` render
as the single word **`configured`**. The password row additionally names
`python -m control.cli hash-password`, because "edit this variable" is not
actionable on its own.

## The secret sweep — reuse it, and read its contract

Two complementary instruments, because neither is the other's superset:

1. **Structural** — the rendered *value cell* of every row marked `secret` must
   **equal** `configured`. A prefix, a length, a digest and the value all fail one
   assertion, reported with `pytest.fail(label)`, never an `assert` that would
   print the operand.
2. **Document-wide** — `_forms_a_secret_could_take()` expands each configured
   secret into prefixes/suffixes of ≥`SECRET_FRAGMENT` characters **after the
   value's scheme**, its length with a unit, and a digest under **every algorithm
   `hashlib` guarantees**, whole / truncated to 8 / in the console's `abcd…ef01`
   fingerprint shape — hunted over `response.text` **and**
   `html.unescape(response.text)` across every URL in `every_console_surface()`.

**The `html.unescape` half is load-bearing, not belt-and-braces.** Jinja
autoescapes; a secret containing `&`, `'`, `<` or `>` is present in the markup as
`&amp;` and a raw substring search walks straight past a fully rendered secret.
Proven both directions.

**`_forms_a_secret_could_take`'s docstring carries a `NOT HUNTED` list — that list
is the instrument's contract.** A value re-encoded rather than digested; a value
split across two elements outside a secret row's own cell; a scheme plus fewer
than `SECRET_FRAGMENT` characters of what follows; a secret described in prose.
**Extend that list rather than quietly relying on the sweep being exhaustive**,
and put any new disclosure shape in that one function so every caller inherits it.

`SCHEME` and `DIGESTS` live beside `SECRET_FRAGMENT` and are reusable.
**`SECRET_SETTINGS` must gain any new secret setting in the same change**, or
`test_every_secret_the_settings_screen_names_is_one_this_sweep_holds` goes red —
by design, in both directions.

## Proving "the live object" rather than a declared default

`conftest` builds the app with `node_connect_timeout=1` against a declared default
of `5`, and the test **asserts that premise** before asserting the screen shows
`1 second` and not `5 second`. **Do not remove that override** — it is what makes
the claim provable, and the premise assertion is what stops the test going vacuous
the day the default changes. A second test plants contradicting `HASHI_*`
variables in the environment and asserts the screen ignores them.

## Divergences worth knowing

- **The screen has no database session** — the second such screen, so M9.3's note
  calling Transports "the only" one is superseded. It is still operator-only:
  `router` carries `Depends(auth.require_operator_page)`. A later step wanting a
  fleet fact here must add the session back, and at that point *"does it move when
  a friend connects?"* applies again.
- **Its standing prose lives in `services/console.py`, not the template.** That
  follows the stronger rule (console sentences live in the service) and lets tests
  assert a constant rather than a copy — but
  `test_no_console_template_names_a_transport_a_country_an_address_or_a_port`
  scanned **templates only**, so prose moved into the service was outside that
  backstop. **Closed by M10.4 on 2026-09-11:** that scan now also walks
  `PANEL_PROSE_MODULES` — `services/console.py` and `panel/wording.py` — reading
  **non-docstring literals**, which is what makes it safe to point a markup scan
  at a `.py` (a comment there legitimately names protocols and addresses). Proven
  both directions: five offender shapes in a literal are all reported with file
  and line; the same five in a comment produce nothing. `panel/routes.py` stays
  out deliberately — its literals are template paths, event names and form field
  names, and a scan that flagged those is one that gets turned off. **A route
  composing a sentence is a reason to move that sentence into one of the two
  scanned files, not a reason to widen the tuple.**
- **All-caps is a comment convention in this codebase and must not reach the
  screen.** One shouted word leaked into the footnote and was caught in review; it
  was the only all-caps emphasis in any rendered panel string.

## Wording acceptance will judge

Sidebar `Settings`. Title `Settings`, subtitle *"what this control plane is
running with, and where each value is changed"*. Section heads `This control
plane` and `Admins`. Columns `setting / value / where it is changed` and `user /
role / where it is configured`. The secret cell reads exactly `configured`; role
reads `operator`.

**M10.4's Audit log entry goes into `NAV` *before* `settings`** (design order), and
the sidebar becomes eight entries.

## A live gap this screen names but cannot close

`docs/tracker/M10/infra-followup.md` — four of the variables the screen names are
never passed into the container by `deploy/docker-compose.yml`, so editing them in
`.env` is silent. The footnote was narrowed to be honest about it; the compose fix
is `infra` and deferred.

---

# Established by M10.3 — the audit trail

Binds M10.4 and anything that later records an operator action.

## The table

`audit_entries`: `id` (String 36, PK), `at` (timestamptz, `server_default now()`,
indexed), `action` (`EnumText(AuditAction, 32)`), `first_label`, `second_label`
(String 64, nullable). **No `TimestampMixin`** — an `updated_at` on an append-only
row invites the idea one can be edited. Migration `0003`, chain `0001→0002→0003`,
single head.

`test_the_trail_holds_exactly_these_columns_and_no_others` asserts the set is
**exactly** that — proven to catch an appended `details` column, which is how a
trail acquires a token in eighteen months without anyone deciding to.

## The two rules that keep it out of charter territory

**`action` is an enum through `EnumText`.** `process_bind_param` calls
`AuditAction(value)`, so an undeclared value raises **at bind, before the
statement is sent** — not at review. Twelve members: `friend-added`,
`friend-revoked`, `node-added`, `node-state-changed`, `node-applied`,
`transport-enabled`, `transport-offered`, `transport-withdrawn`,
`hop-established`, `hop-dissolved`, `keys-rotated`, `params-replaced`.

**Every label is READ off an inventory row, never COMPOSED.** The four permitted
sources are `Node.name`, `Friend.nickname`, `NodeTransport.transport_name` and
`str(NodeState)`. The concrete hole this closes: `Node.state_detail` is 500
characters of free text that can carry a remote host's words, one attribute away
from `state`. **The 64-character guard is not what carries this** — a composed
`f"{node.name}: refused"` fits — the inventory-equality test does. Proven: wrapping
`record` to compose put 8 tests red on `first_label` and 5 on `second_label`.

`test_both_labels_are_exactly_as_wide_as_the_values_they_may_hold` guards all four
sources in the other direction: **widen a source column and `record()` starts
raising a 500 on a legitimate operation**, so that test tells whoever widens one to
widen the label column in the same change.

## Writing

**Service, in the same transaction as the change. Never a route, never
`/sub/{token}`.** `test_no_route_writes_the_trail` greps `api/` and `panel/` for
`services import audit`, `services.audit` **and `AuditEntry`** — the last catches a
hand-built `session.add(...)`, including through an alias.

**Only changes that committed.** No probes, no logins, no failures, no refusals — a
refusal's text can come from a remote host and the row has nowhere safe to put it.

`revocation.revoke_friend` is the one non-obvious placement: `friends.revoke` owns
the commit, so it records into the session **before** calling it and the
revocation's own commit carries the entry. One transaction; a raised revocation
takes the pending entry with it.

**Fetch the node by id (`session.get`/`get_node`), not through
`node_transport.node`.** The eager relationship is unloaded on a row the same
session just created and reaching it is `MissingGreenlet`. Neighbouring code gets
away with it only because those requests loaded the row with a fresh query.
**Copy this line, not the neighbour's.**

## The named deliverable

`tests/e2e/control/test_the_audit_trail_never_learns_who_connected.py` **fetches a
real subscription and asserts the trail gained no row at all** — not merely that no
row mentions a token. One tests the write path; the other only the column set.
Proven red twice, independently: by patching `delivery.py` in the repo, and by the
reviewer patching it **inside the running container** (`assert 10 == 7`).

## Retention

`HASHI_AUDIT_RETENTION_DAYS`, default 30, bounded 1–365 — all three from
`AUDIT_RETENTION_{MIN,MAX,DEFAULT}_DAYS` in `settings.py`, which are **the single
source** for the `Field` bounds, the validator, the bounds test and the screen's
sentence. Swept hourly by an `asyncio` task started in `create_app`'s lifespan and
cancelled before the pool is disposed. A failing pass logs its traceback and the
loop continues; `CancelledError` is re-raised so shutdown is immediate.

**Nothing sweeps while the host is off** — stated in three places a reader will
hit. **The operator cannot currently change the window at all**: the variable is
not passed into the container — see `infra-followup.md`, where it is listed first
because it governs how long the only record naming friends is kept.

## Prose is derived, and there is now a test saying so

`console._how_often(seconds)` sits beside `_seconds()`. The article travels with
the noun (`(3600, "an", "hour")`, `(60, "a", "minute")`, `(1, "a", "second")`), so
`60 → once a minute` rather than "once an minute".
`test_the_retention_row_states_the_intervals_this_process_actually_uses` plants a
20-minute sweep and a 2–90 day window and requires the screen to follow — with
premise assertions first, in M10.2's shape, so it cannot go vacuous if the screen
stops reading the constants.

## What M10.4 must know

- **Order by `(at, id)`.** `at` is `server_default=func.now()`, which in Postgres
  is **transaction-start** time. No operation writes two entries in one transaction
  today, so no two rows can tie — but a later step that records twice in one
  transaction would need `clock_timestamp()` in a migration rather than assuming
  per-statement ordering it does not have.
- **The stored value is a machine key; the sentence is M10.4's**, rendered in
  `panel/wording.py` from the existing toast vocabulary. **Hop labels are always
  entry first**; `node-state-changed`'s second label is the `NodeState` value.
- **No read helper exists yet** — `services/audit.py` has `record`, `sweep`,
  `sweep_forever`, `start_sweeper`, `stop_sweeper` only. M10.4 adds the query.
- The screen **has no session today** (neither does Settings), so M10.4 must add
  one back — and at that point *"does it move when a friend connects?"* applies
  again.
- **M10.4's route must call a console/service function, not `audit` directly**, or
  `test_no_route_writes_the_trail` goes red.
- Test helpers in `tests/control/test_the_audit_trail.py`: `trail(session)` (**read
  its docstring before adding an `expire_all`** — expiring detaches objects the
  test still holds), `entries_for(session, action)`, `a_node(client, name,
  with_key=)`, a local `hop_params`, and a `_FakeHost` that makes `apply_node`
  succeed.

---

# Established by M10.4 — the audit log screen

## What it is

`/panel/audit`, the **eighth** sidebar entry (`Audit log`, before `Settings`). A
read-only three-column table — `time / actor / event` — newest first. `actor` is
`settings.operator_username`, **rendered from the shell's `operator` context
value, never stored**. No `source` column. No fragment, no dialog, no control of
its own.

The route reaches the trail through `console.trail_entries`, **never
`services.audit` directly** — `test_no_route_writes_the_trail` greps for that.

## The twelve sentences

Stored value is a machine key; the sentence is rendered in `panel/wording.py`.

| stored | rendered |
|---|---|
| `friend-added` | `user <nick> added` |
| `friend-revoked` | `user <nick> revoked — link is dead` |
| `node-added` | `node <name> added` |
| `node-state-changed` | `<node> is now <state>` |
| `node-applied` | `config applied to <node>` |
| `transport-enabled` | `<transport> enabled on <node>` |
| `transport-offered` | `<transport> offered again on <node>` |
| `transport-withdrawn` | `<transport> withdrawn on <node>` |
| `hop-established` | `hop established from <entry> to <leaf>` |
| `hop-dissolved` | `hop torn down from <entry> to <leaf>` |
| `hop-dissolved`, one label | `hop torn down at <node> — the other end was already missing` |
| `keys-rotated` | `keys rotated for <transport> on <node>` |
| `params-replaced` | `parameters replaced for <transport> on <node>` |

Title `Audit log`, subtitle *"what you changed, and when — never who connected to
what"*. Times print `12 Sep 2026 14:03`, normalised to UTC **in the service**, so
the footnote's claim is true of every cell.

`EVENT_SENTENCES` in the test is **written out literally and driven off
`AuditAction`**, so a thirteenth member fails there rather than rendering blank.

## Order, cap, and the three footnote readings

Ordered `(at, id)` **descending**, capped at `TRAIL_LIMIT = 200` in one query.
`at` is Postgres **transaction-start** time, so entries written in one transaction
tie and the `id` tiebreaker decides — a test planting several must commit each one.

`trail_window` has **three** readings, each true of the screen it sits under:
`shown == 0` (the retention half, **without** the `Times are UTC.` clause, since
no clock is on screen), `shown < limit`, and `shown == limit` (gains *"shows the
most recent 200 changes — anything older than that is not on it"*, which is honest
at exactly 200 because it asserts nothing about rows existing).

**Every number in it is derived** from the live settings and
`audit.SWEEP_INTERVAL_SECONDS`, and `conftest` now builds with
`audit_retention_days=9` against a declared default of 30 so the derivation test
has a premise to assert. **Do not remove that override** — it is the same guard as
`node_connect_timeout=1`, and adding it revealed that the Settings screen's own
retention assertion had been vacuous.

**The cap was chosen knowing its cost:** a fleet busy enough to write more than 200
entries inside the retention window leaves entries 201..N on disk and unreachable
from the product until the sweep deletes them. A second page is a second place the
record of what the operator did can be read from, which is why a count was
preferred to paging. **If revisited, bound by the retention window rather than a
count** — `trail_entries` already takes `limit` as a keyword and `trail_window`
already composes from what it was given, so the change is the query predicate and
one sentence, not the screen.

## How "no token, no link" is held

Three ways, and a reviewer could not find a path past them: the screen is handed
**pre-composed lines, never the model**, so nothing in template reach can look a
friend up; a unit test issues a real subscription and hunts the raw **and
unescaped** page for the live URL and token with `pytest.fail` (never `assert`,
which would print the credential); and an e2e scenario does the same against the
booted stack, plus `"/sub/" not in body`. Mutations that injected a live decrypted
token into a label, and that taught the delivery path to write a row, were both
caught.

**Nothing moves when a friend connects:** a unit test renders the fragment,
fetches a real subscription three times, re-renders and requires **byte
equality**; the e2e scenario does the same. That is the screen-level twin of
M10.3's "no row is written".

**A populated trail is among the swept surfaces** —
`test_the_swept_console_walks_a_trail_that_is_not_empty` asserts the fleet
`every_console_surface` builds leaves ≥6 rows, so the secret and key-material
sweeps are not passing over an empty state.

## Testing

`tests/control/test_the_console.py`, section `# --- Audit log (M10.4) ---`.
`a_trail(client, reality_params)` performs one walk of the product and returns the
five sentences it should leave, newest first.

- **Never sweep a console page for the word "friend" in e2e** — the stand has a
  user nicknamed `hopfriend-…` and that is the operator's own text, handed back
  untouched on purpose. Assert on the sentence the panel composed instead.
- **A failed revocation push marks the node degraded**, which itself records
  `node-state-changed` — so a revocation in a fixture leaves **two** entries.
- `console.trail_entries(session, limit=…)` takes the cap as a keyword so a test
  need not plant 201 rows.

## What acceptance meets

**The stand starts empty**, so the first thing a walk sees is the empty state:
title `Nothing changed yet`, and a body that now also states the retention window
and the sweep gap. **Change two things first**, then open it.
