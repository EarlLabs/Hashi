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
  scans **templates only**, so prose moved into the service is outside that
  backstop. M9.6's `test_no_sentence_this_panel_hands_an_operator_names_a_surface_that_is_gone`
  does walk every `.py` under `control/app`, which is the cover that exists.
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
