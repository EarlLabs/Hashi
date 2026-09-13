# M9 — step notes

Conventions established here. They bind later steps, and later milestones in
this codebase, until something supersedes them. Follow them; do not relitigate.

## Read M8's notes first — they bind this milestone

**`docs/tracker/M8/step-notes.md` is the console's rulebook and it binds M9 and
M10 until something supersedes it.** Read it before the first line of any M9
step. It carries, in its own words rather than a paraphrase:

- **how a screen is added** — `_screen(request, screen=…, current=…, title=,
  subtitle=, context=)` in `control/app/panel/routes.py`, the `NAV` entry with
  `boost: True`, and the screen-template shape (`console_header.html` include,
  then `<div class="panel">`), with the collection in its own self-swapping
  fragment;
- **the mutation and OOB-swap rules** — `_mutation(...)` returning
  `panel/mutation_result.html`; **OOB swaps must be `innerHTML:#slot`, never
  `hx-swap-oob="true"`**, because outerHTML replaces the slot node and kills
  `app.js`'s MutationObserver; field validation returns **422** with the dialog
  re-rendered, and `app.js` allows exactly that one status to swap;
- **the fragment shape**, the existing CSS vocabulary, and **"do not add a
  breakpoint"** — there is one, at 900px, per UI-PATTERNS §12;
- **THE LIST IS THE TEST** —
  `tests/e2e/control/test_the_panel_fetches_nothing_from_a_third_party.py` holds
  `PANEL_PAGES`, `PANEL_FRAGMENTS` and a `surfaces` fixture. **Every new screen,
  dialog or self-refreshing table joins one of them in the same change that adds
  it.** M9 adds four screens and two dialogs; that is six or more entries, and
  the first version of that list omitting the dialogs — including the one
  carrying the bearer credential — was itself the finding;
- **the wording a person sees**, which acceptance judges;
- the "do not relitigate" list, including decision 9 (`friend` stays in routes,
  services, schemas and tests; only the rendered page says "users") and the note
  that **the Overview's node preview repoints to the Nodes screen when M9 lands**.

An implementer who has not read that file will reinvent the console's
conventions, and the reviewer will be right to reject it.

## Carried into M9 by the owner, 2026-09-10 — a refusal must look like one

`docs/tracker/M8/acceptance-verdict.md` left two "works, but awkward" findings
open. **The first one is folded into M9**, because M9 extends the same palette
across four more screens and is the right place to settle it once:

> A failure now sits in its own treatment rather than in the neutral notice
> banner, but it still carries no error colour: the dialog's refusal is drawn as
> `.field-error` with a 2px left rule in `rgb(65,97,128)` — **the same slate blue
> as the primary "add user" button** and as the accent on the ordinary NOTE
> banner — over dark navy text on no background. Nothing about the colour says
> "wrong"; the only signal that this is a failure is the wording. The old
> un-redesigned fleet page does use red for its warning, so the palette has a
> danger hue available and the new console does not reach for it.

Whichever step first draws a refusal on a new screen owns this. Settle it once,
in the shared CSS, so every M9 screen and every later one inherits it — do not
give one screen its own error colour.

**The second M8 finding is NOT M9's** and must be left alone: a row that goes
stale on a second session when another device revokes a user. The owner has
ruled it out of this milestone.

## Decisions already taken that M9 must not re-open

- **Decision 6** (`docs/decisions.md`, 2026-09-09) — the four cells that measure
  people are replaced by facts the control plane already holds, and the Traffic
  screen is dropped outright, its sidebar slot given to nothing.
- **Decision 9** — the panel says "users"; the code keeps `friend`. No
  `friend` → `user` rename may travel past the rendered page.
- **The test for whether a cell belongs on a screen** (`docs/decisions.md`,
  2026-09-09): *does it move when a friend **connects**?* If it moves only when
  the **operator** acts, it is a fact about our own configuration and may be
  shown. If it moves because a person *used* the service, it is an analytic about
  them and may not exist at all. That line was written for M8 and explicitly kept
  "because it will be needed again on every screen M9 and M10 add".

---

# Established by M9.1 — the Nodes screen

Everything below was invented by M9.1 and binds M9.2–M9.6. Follow it; do not
relitigate. It supplements M8's rulebook rather than replacing it — where this
file is silent, M8's notes still govern.

## Adding a screen (M8's shape, as M9.1 actually used it)

Route → `_screen(screen="panel/screens/<x>.html", current=<NAV key>, title=,
subtitle=, context=)`. Template = `{% include "panel/console_header.html" %}`
then `<div class="panel">`. The collection lives in its own **self-swapping
fragment**: `hx-target="this"`, `hx-swap="outerHTML"`, `hx-indicator="this"`,
**`hx-disinherit="hx-indicator"`**, `hx-trigger="<thing>-changed from:body"`.
M9.1's is `panel/nodes_table.html`, event `nodes-changed`.

## New CSS vocabulary — reuse it, do not reinvent it

- `.section-head` — explainer on the left, the screen's secondary creation
  button on the right. Built with the Hops screen's explainer row in mind.
- `.section-note` — the explainer text itself.
- `.tag-row` — wrapping tags inside a table cell.
- `.dialog-form` — flex column at `--space-3`, for any dialog with more than one
  field.
- `.dialog-wide` — 560px plus `max-height: 86vh` with `overflow-y`. **The hop
  dialog's 620px needs its own class**; do not widen this one.

**No new breakpoint was added and none may be.** There is one, at 900px,
per UI-PATTERNS §12.

## Multi-field dialogs, and how a refusal is shaped

Copy `add_node_dialog.html`'s `{% macro field(...) %}` — it wires
`aria-describedby`, `aria-invalid`, the hint and the error in one place.

Context shape is `{"values": {...}, "errors": {field: sentence}, "defaults":
{...}}`, built by `_node_form()`. **A refusal is a 422 with the dialog
re-rendered, per field** — `app.js` allows exactly that one status to swap.
`_refuse_node` / `_refused_field` are the pattern. `_mutation(keeping=…)` carries
state across a refusal.

**Secrets are not refilled on a refusal, and the operator is told at the moment
it happens.** The add-node dialog empties the SSH private key on a 422 and
renders a `.field-error` in that field — *"the key you pasted was not kept —
paste it again before you submit, or this node is registered without one"* —
wired into the textarea's `aria-describedby`, and shown **only** when a key was
actually pasted. A later dialog handling a secret copies this behaviour rather
than "fixing" it. Silently emptying the box is how an operator registers a node
with no key and learns at apply.

## A refusal must look like one — settled here, for every later screen

`--color-danger-100/700/900` are tokens in `:root` in `app.css`; the 700 is the
hue the pre-redesign page already used, so console and old page agree on what red
means. They are applied to `.field-error`, `.banner-failure`,
`.banner-failure .banner-label` and `.input[aria-invalid]` — **every place a
request was refused or failed, and nowhere else.** Status tags and destructive
buttons stay steel: UI-PATTERNS §4 holds everywhere it was written about, and
this is its one exception, **recorded in `docs/decisions.md` (2026-09-10)**, not
merely in a comment.

**Every `.banner` must declare `role="alert"` (a refusal) or `role="status"` (a
notice), and must carry a `banner-label`.** This is mechanical, not advisory:
`test_no_refusal_anywhere_in_the_panel_is_drawn_as_an_ordinary_notice` scans
every template under `control/app/templates/` and fails on a banner that declares
neither, or that wears `role="alert"` without `banner-failure`, or that carries no
label. `alert` vs `status` is the live-region distinction, so the a11y contract
and the visual contract are the same assertion.

**Two rules, and one place to check before you add a banner.** *One element, one
banner* — declaring `class` or `role` twice, including once per Jinja branch, is
a fault, because a browser keeps the first and drops the second. And *put the
literal class name in the attribute*: `{{ 'banner-failure' if failed else '' }}`
is seen by the scan, a variable holding the same string is not. The scan was
hardened after M9.1 closed and now lexes each template with Jinja's own lexer and
faults on any element it cannot parse — **the accurate record of what it still
cannot see is `_banner_faults`'s own docstring**, which is the thing to read
before you rely on a green run. `fix-notes.md` has the history.

## Mutations

Success → `toast=`. Anything failed, partial, or needing to survive the next
click → `banner=` (persistent, and now red). **OOB swaps are `innerHTML:#slot`,
never `hx-swap-oob="true"`** — outerHTML replaces the slot node and kills
`app.js`'s MutationObserver. Node-summary prose lives in
`console.health_summary()`, never in a route or a template.

## Never name a port, country, address, domain or transport in a template

`test_no_console_template_names_a_transport_a_country_an_address_or_a_port` scans
every `templates/panel/**.html`. Defaults come from service constants —
`nodes.DEFAULT_SSH_USER` / `DEFAULT_SSH_PORT` is the pattern. **That scan has
known holes too; see `carry-over.md`.** It is a backstop, not a licence.

## Testing

`tests/control/test_the_console.py`, standard `client` fixture, no chdir. Reach a
node with `a_serving_node(client, reality_params)`. For apply/probe, monkeypatch
`apply_service.apply_node` / `health_service.check_node` — a real one costs a 5s
SSH timeout. `_css_rules()` reads `app.css` as `selector -> declarations` for
assertions about how something looks.

**THE LIST IS THE TEST.** `NODE_SURFACES` in `test_the_console.py` feeds the
decision-9 sweep. `PANEL_PAGES` / `PANEL_FRAGMENTS` in
`tests/e2e/control/test_the_panel_fetches_nothing_from_a_third_party.py` gained
`/panel/nodes`, `/panel/nodes/new`, `/panel/nodes/table`. **Add yours in the same
change that adds the surface** — the first version of that list omitted the
dialogs, including the one carrying a bearer credential, and that gap was the
finding.

## Wording acceptance will judge

Sidebar `Nodes`. Title `Nodes`, subtitle *"the machines a user's link resolves
to, and whether each is running what you told it to"*. Buttons `add node`,
`probe`, `apply`, `cancel`. Dialog title `Add a node`. Toasts `<name> added — a
draft until you apply it`, `config applied to <name> — <transports>`, `<name> is
serving <transports>`. Empty state `No nodes yet`. Columns `name / exit / address
/ state / config / transports / actions`. A degraded node's reason on its own row
as `why: <detail>`.

## Do not relitigate

- **The Overview's node links were repointed to `/panel/nodes` by M9.1** — both
  `all nodes` and the empty state's `add a node`. The sidebar's Fleet entry stays
  until hops and transports move, with its note narrowed to `hops · transports`.
- **`POST /panel/nodes` serves two panels from one route** — htmx gets the console
  answer (dialog closes, toast, `nodes-changed`), a plain browser POST still gets
  its 303 to `/panel/fleet`, so the pre-redesign form keeps working until M9.6.
  `test_the_pre_redesign_form_still_gets_its_redirect` holds it. **Do not delete
  that branch before the page.**
- **The console's apply posts to `/panel/nodes/{id}/push`**, not `/apply`, because
  `/apply` still answers the old page with `panel/outcome.html`. **M9.6 should
  take the short name back** when it deletes those routes.
- `_refuse_node` **raises** `DomainError` for the non-htmx caller where its console
  sibling returns a 422 fragment — the old page has nowhere to render a field
  error, so it keeps the error envelope it already produced.
- **`design/UI-PATTERNS.md` is deliberately left contradicting the shipped
  console.** It is the designer's handoff record; `docs/decisions.md` is the
  override, and the rule is enforced by tests over `app.css`, every template and
  `app.js` rather than by prose in either file. Rewriting the handoff would erase
  that the departure was ours. Do not "fix" it.

## Existing e2e scenarios that still drive the old pages

Not M9.2–M9.4's to repoint; recorded so the right step picks each up.

- `test_the_panel_never_offers_a_blocked_protocol_as_working.py` GETs
  `/panel/fleet` — **repoint when M9.3 lands the Transports screen.**
- `test_a_replacement_node_and_a_protocol_from_the_panel.py` GETs
  `/panel/nodes/{id}` (the old detail page) and scrapes
  `data-transport=… hx-post="/panel/transports/{id}/state"` for the withdraw
  button's id — **repoint with M9.5**, which homes enable/withdraw.
- The other two drive POST routes only; none of those changed.

---

# Established by M9.2 — the Hops screen

Binds M9.3–M9.6. Supplements the M9.1 section; where this is silent, that governs.

## The one thing this step is about

Establishing a hop asks **three questions** — entry node, leaf node, transport —
and every other parameter lives behind `<details> advanced tuning`.
`test_establishing_a_hop_asks_three_questions` parses the **rendered** dialog
with a stdlib `HTMLParser` tracking `<details>` depth and asserts the controls
outside are exactly `(entry_node_id, leaf_node_id, transport_name)`. It catches a
fourth question added outside, a knob lifted out of the disclosure, one end's
boxes going missing, and the summary's count drifting from the transport's real
field count. **Do not add a control outside that disclosure.**

**Read the plan's corrected "done when" before you touch this screen.** The
original clause promised each box would show "its own transport's default as a
placeholder"; no shipped transport declares a default for a hop parameter it
*requires*, and `control` may not manufacture one. The full reasoning is
`docs/decisions.md` (2026-09-10) — field by field, and why. What the disclosure
does instead is state each field's requirement and say, **outside the shut
disclosure**, how many boxes are mandatory: `advanced tuning — 12 parameters per
end, 11 of them required by this transport`, both numbers derived via
`selectattr("required")`. **Derived, never written** — a literal count goes stale
the day a transport changes.

## Two service functions, two questions

- `transports.hop_parameters(name)` — **every field an operator may supply**
  (model fields minus key material and its `public_name`s). `hop_tuning` iterates
  this.
- `transports.operator_params(name)` — **every field an operator must supply**
  (adds an `is_required` filter). Its two callers are `/api/transports` and the
  old page's two forms. **Do not merge them**: filtering on required made the
  "declared default" branch unreachable and silently dropped a defaulted field's
  box entirely.

`TuningField.hint` is the field's `description`, **always, in full**, rendered
full-width under the row (`.field-hint { grid-column: 1 / -1 }`) and wired into
`aria-describedby`. `TuningField.placeholder` is **only ever a value or a
range** — never prose. The input is 136px; a 43-character sentence in it shows
about seventeen characters.

`transports.PORT_FIELD = "port"` is the one field name `control` knows. It is
hop-contract vocabulary, not a protocol's — `edge/relay.py` already reads
`end.params['port']`. `test_the_port_is_the_one_field_name_the_console_knows`
stands over it so a second cannot appear quietly.

## Refusals land on their own box

`control.app.errors.HopEndRefused(DomainError)` carries `purpose` and
`fields` (`{parameter: message}`). It **inherits `status_code=400` and
`code="bad_request"` deliberately**, so `POST /api/hops` and the old page's
`create_hop` get an identical envelope — the subclass only adds a second way to
read the same refusal. **This is the pattern for any service refusal that has
fields to land on:** subclass `DomainError`, inherit status and code, add
structure; callers that do not know about it are unaffected.

`HOP_SIDES` is the single table mapping form prefix ↔ `TransportPurpose`.
Anything mapping a service refusal back onto a hop form goes through it, so the
two mappings cannot disagree. `relay._plainly()` strips pydantic's
`Value error, ` / `Assertion failed, ` prefix — any surface showing a transport's
own validation message should use it. `_end_word()` turns `relay-entry` into
`entry`; **no operator-facing string may carry the internal purpose vocabulary.**

## Exactly one disclosure is ever on screen

`shown = chosen if chosen in transports else transports[0]`, resolved **once
before the loop**; each `<details>` is `hidden` unless `name == shown`. The
earlier `not loop.first` form left the first transport's disclosure permanently
visible, so a refusal re-render showed two summaries with contradicting counts.
`app.js` only re-hides on a `change` event, which an htmx swap does not fire —
so the server, not the script, must decide this.

`app.js` gained one generic behaviour: a `change` listener showing the
`[data-transport-group]` matching a `[data-transport-select]` in the same form.
Presentation only — the server filters submitted fields to the chosen transport's
list, so it works with the script dead. Reuse it for any "one group of fields per
choice" form.

## Tuning inputs carry no `required` attribute, deliberately

A browser refuses to submit a form with an empty required field **it cannot
focus**, and a field inside a closed `<details>` is exactly that — the operator
would press submit and nothing would happen, with no message. The server refuses
per field at 422 instead. A screen copying this macro inherits *server-side
required*, not markup-required.

## Events

Every hop mutation fires `"hops-changed, nodes-changed"` — comma-separated in one
`HX-Trigger`. A hop is two node-transport rows, so the Nodes table must refresh
with it. **Copy this for any mutation touching two collections.**

## New CSS — reuse, do not reinvent

`.dialog-hop` (620px/86vh — the hop dialog's own class, as the M9.1 notes
required), `.disclosure` + `.disclosure > summary` for any `<details>`,
`.tuning-side`, `.tuning-field` (label 1fr | input 136px), `.grid-3` — added to
the **existing** 900px collapse rule. No new breakpoint.

## Testing

`a_hop_transport()` (discovered, never a literal), `hop_side(address, peer,
port=51820)`, `two_nodes(client)` (`entry-1`/`exit-1`, deliberately not colliding
with `a_serving_node`'s `leaf-1` in the shared database), `a_hop(client)`.
`_render_hop_dialog(**context)` renders the dialog through a `FileSystemLoader`
with **no app and no database** — use it to try a fleet this image does not ship.
`_read(markup)` returns `.controls`, `.visible`, `.opened`; `_field_errors()` and
`_hints()` read off the `aria-describedby` ids.

**A test picking "a tuning box" must pick a *required* one** — the first entry is
now a defaulted field that is correctly accepted empty.

**RFC 5737 documentation ranges are `is_private == True` to Python's
`ipaddress`** and pass tunnel-address validation. To test a rejected address use
`172.15.0.1/24` — one digit off RFC 1918, which is the mistake a rotation
actually produces.

## Wording acceptance will judge

Sidebar `Hops`. Title `Hops`, subtitle *"which node a user's traffic arrives at,
and which node it leaves from"*. Buttons `establish hop`, `tear down`, `cancel`.
Dialog titles `Establish a hop`, `Tear down this hop?`. Summary `advanced tuning
— N parameters per end, M of them required by this transport`. Toasts `hop
establishing — apply both nodes to bring it up`, `hop torn down — re-apply N
nodes so they stop holding a tunnel to an exit that is no longer configured`.
Empty state `No hops yet`. Columns `entry / leaf / transport / state /
established / actions`. A half hop reads `missing — this hop leads nowhere`; an
unapplied hop's date cell reads `not yet — apply both nodes`.

The tear-down confirmation **states decision 3 in words** — an entry that fails
closed looks like a broken node from outside, so the operator is told that before
they confirm.

## Do not relitigate

- **`AllowedIPs` is not surfaced and cannot be** — it is rendered by `edge` from
  the peer block and is not in any params model, so the dialog can never present
  the old narrow value the plan's M3 prose still describes.
- **Key material is absent by construction** — `hop_parameters` subtracts
  everything in `meta.key_material` including `public_name`s.
  `test_the_hop_dialog_never_asks_for_key_material` holds it.
- **`client_dns` is offered although it is inert at a hop end.** Recorded in
  `docs/decisions.md` (2026-09-10) with its trap named. Do not "fix" it in
  `control` — closing it needs an `edge`-side declaration.
- **New routes took new names** because `POST /panel/hops` and
  `/hops/{id}/dissolve` still belong to the old page and **both call it with
  htmx**, so unlike the add-node form they cannot be told apart by a header.
  **M9.6 takes `/hops` and `/dissolve` back.**
- The sidebar's Fleet note narrowed to `transports`. **M9.3 empties it entirely.**
- Hop prose lives in `services/console.py` (`hop_rows`, `hop_row`,
  `tear_down_summary`, `HOP_ESTABLISHED/PENDING/INCOMPLETE`) — never in a route or
  a template.

---

# Established by M9.3 — the Transports screen

Binds M9.4–M9.6. Supplements the M9.1 and M9.2 sections.

## A capability table states capabilities. It does not give advice.

This is the rule M9.3 was corrected into and the one most likely to be broken
again, because a helpful sentence is always tempting. Every string on this screen
is **projected from a declared property of `TransportMeta`** — and the moment a
cell recommends an *action*, it has to be right about the whole stack, which a
capability declaration cannot be.

The concrete case: the `why:` sentence used to end *"Enable it only where nothing
is filtering."* `docs/decisions.md` (2026-09-09) contradicts that for the only
transport it can apply to — under the pinned legacy-iptables image on a `ufw`
host you get *"handshake completes, nothing moves, nothing logged"* — and it sat
one cell from *"this panel cannot hand it over"*. It was dropped and **nothing
replaced it**. Do not add advice to a capability cell.

## Where every cell comes from

| cell | source |
|---|---|
| name | `meta.name` |
| family | `meta.family` |
| ports | `meta.port_range`, as `low–high` |
| how a user receives it | `meta.subscription_formats`, sorted and joined |
| …second line | `meta.subscription_expressible` |
| on a filtering network | `meta.blocked_by_inspection` |
| …second line | `meta.hop_capable` |
| the `why:` row | present iff `blocked_by_inspection` |

`console.TRANSPORT_*` constants hold the prose. **A new capability sentence goes
beside them, keyed on a declared property, never on a name.** Reuse
`console.transport_rows()` / `TransportRow`; add a field there rather than
reading `discover()` in a route.

`test_the_warning_follows_a_declaration_and_never_a_protocol_s_name` renders two
fabricated single-transport fleets differing only in the declared booleans, so a
`meta.name == …` branch fails it. To try a fleet this image does not ship:
`monkeypatch.setattr(console_service, "discover", lambda: {name: meta})` and GET
the screen — no database rows needed.

## Testing

`TRANSPORT_SURFACES` joined the decision-9 sweep. `_identified()` finds the
blocked transport **by declaration, never by name**. `_reading(markup)` is
`_visible_text` plus `html.unescape` — needed because these sentences contain
apostrophes Jinja escapes, so a raw-constant assertion against `response.text`
fails.

`TWO_REPRESENTATION_URLS` is now **all five** console URLs. Its premise assertion
(`<!doctype html>` present in the document, absent from the `HX-Request` fetch) is
what makes each entry non-vacuous — the `no-store` header itself comes from
`main.py`'s `/panel`-prefix middleware and is inherited. **Add your screen to it.**

## Divergences to know about

- **No self-swapping fragment and no `-changed` trigger.** Nothing this panel can
  do changes which packages the image ships. **So do not assume every screen has a
  `…/table` URL to fire an event at** — a mutation wanting this table to repaint
  has nothing to fire at and would have to add the fragment first.
- **The only console screen with no `session` dependency.** Its route takes just
  `request` (it is still on `router`, so still operator-only). A later step
  wanting a fleet fact on it must add the session back — and at that point *"does
  it move when a friend connects?"* applies again.
- **`nav.html` omits an empty `<span class="nav-note">` entirely.** The Fleet note
  is now empty and `test_the_sidebar_no_longer_sends_the_operator_to_the_old_page_for_a_list`
  asserts `"nav-note" not in body`. **A later screen wanting a note must change
  that line deliberately.**

## Wording acceptance will judge

Sidebar `Transports`. Title `Transports`, subtitle *"the protocols this image can
speak, and which of them survives a network that inspects traffic"*. Columns
`name / family / ports / how a user receives it / on a filtering network`. The
cell `identified and blocked — do not offer this as a working exit`. Sub-lines
`never on an entry→leaf hop` and `not in a user's link yet — this panel cannot
hand it over`. Footnote begins *"Discovered from the image, not listed
anywhere."* Empty state `No transports in this image`.

The `why:` row, verbatim — acceptance reads this exact text:

> why: it has no camouflage. The wire format is fixed and looks like itself, so a
> network that inspects traffic can name the protocol and drop it: both ends stay
> correctly configured, no tunnel comes up, and nothing on the user's device says
> what happened.

## The scenario that was split, and why

`test_the_panel_never_offers_a_blocked_protocol_as_working.py` used to drive
`/panel/fleet`, where both facts shared one page. They no longer do, so it is two
scenarios: the capability half on `/panel/transports`, and
`test_the_hop_dialog_does_not_offer_a_blocked_protocol` asserting the option
values of `hop-transport_name` at `/panel/hops/new`. Both were proven red-first by
mutation against a rebuilt stand.

---

# Established by M9.4 — Keys & configs

Binds M9.5–M9.6. **M9.4 did NOT converge — read `carry-over.md` first for the one
High left open.**

## The fingerprint

`keymaterial.fingerprint(specs, params)` → first 4 + last 4 hex of
`sha256("<public_name>=<value>\n"…)`, rendered `9f3c…a17d`.

Its input is **only** values stored under a `KeySpec.public_name` for
`KeyScope.NODE` specs, read from the **clear** `params` column. `secrets` is
never read on that path and nothing decrypts in `key_rows`. A merely-non-secret
minted value is **deliberately excluded** — `short_id` is `secret=False` but
declares no `public_name`, and hashing a few bytes is reversible by enumeration.
**The rule is "what the transport declared public", never "what is not
encrypted".** Irreversible because the preimage already ships inside every user's
config, so the digest reveals strictly less than what is handed out.

No public half declared → **no fingerprint**, and the cell prints the rule.

## How a refusal is sorted, and the rule that replaced the message

`_refused_parameters(exc, boxes)` is an **allow-list**: a transport's own sentence
is printed **only** for a `loc` that is exactly one of this form's boxes.
Everything else — key material, an unrendered field, a nested `loc`, an empty
`loc` — is named with the rule instead. The earlier deny-list keyed on an exact
top-level field name was one `loc` shape from open.

It is airtight *because* Pydantic field names are Python identifiers: a
`".".join`ed multi-element `loc` can never equal a box name, and `loc == ()`
joins to `""`, which is never a box. **Do not "simplify" that join to
`error["loc"][0]`** — that collapses `server_names.0` onto a real box and starts
printing a nested validator's message.

**A refusal is never silent, and that invariant lives in the sorter, not the
caller.** A falsy message is treated as unprintable and named with the rule; a
`ParamsRefused` carrying no field at all is stated as a complaint about the
parameters as a whole. Both callers inherit it, so the next caller cannot forget.

`rotate_keys` passes `boxes=set()`. **The reason is not "nothing in that mapping
was typed"** — the operator's own parameters are validated alongside the new
material, so some of it was. The reason is that the rotate answer is a
**confirmation dialog with no boxes**, so there is nowhere for a message about one
parameter to belong, and the mapping was validated *together with* material
minted three lines earlier, so a complaint may be quoting material whichever
field it names.

`rotation.MATERIAL_NOT_REPEATED` / `WHOLE_MAPPING` / `_named()` are the vocabulary
for any service refusal whose mapping holds minted material: **name the
parameters, state the rule, keep the sentences on `fields`** for a caller that has
somewhere safe for them.

## Testing this

- **Never `assert secret not in body`.** Pytest's assertion rewriting prints both
  operands, i.e. the key into the CI log. Use `pytest.fail(label)`.
- **`session.expunge_all()` before re-reading after a mutation.** SQLAlchemy's
  identity map returned the same values twice, and the sweep passed against a
  deliberately-leaking route until this was added.
- **A marker must be a token only the message could carry.** The first attempt
  used the operator's own typed value, which a 422 legitimately hands back into
  its box — proving nothing.
- `every_console_surface()` is the single list feeding **both** sweeps (decision-9
  and key material). Add your screen and dialogs there.
- `stored_material(session)` reads the decrypted values the fleet actually holds.
- `a_node_holding_material(client, reality_params)` → a serving node with a
  transport enabled and one user credential, returning the node-transport id.
- Rotation POSTs run the real push (~1s SSH failure) on purpose — the failure
  branch is the thing under test.

## Reusable

`transports.key_material_names(name)` is **the one place minted names are
subtracted** (`operator_params` and `hop_parameters` both use it).
`transports.replaceable_params(name, current) -> ParamBox` — empty box means
*keep*. **Do not reuse `TuningField`**, whose `required` means the opposite here.
`.param-field` (label `auto`, input `minmax(0, 1fr)`) is the replace form's row
class — on that form the **input** is the thing being read, since its placeholder
is the current value. `.tuning-field` is the hop dialog's, sized for 24 short
numeric boxes. `ParamsRefused` is the pattern for a single-object per-field
refusal; it is a **sibling** of `HopEndRefused`, not a merge — `purpose` is hop
vocabulary and a node-transport has one end.

## Known narrowing, permanent after M9.6

`replaceable_params` is built from `operator_params`, which filters on
`is_required()`, so **a parameter the transport defaults can never be replaced
from the panel** — `decoy_port` and `fingerprint` on the shipped Reality
transport — while `POST /api/transports/{id}/params` will change either. Parity
with the old form today, so M9.6's "every action has a home" still holds, but it
becomes a permanent narrowing the moment that page goes.

## Wording acceptance will judge

Sidebar `Keys & configs`. Title `Keys & configs`, subtitle *"what each node holds,
and how to replace it without anyone re-importing their link"*. Columns `node /
transport / scope / fingerprint / on the node / users on it / actions`. Buttons
`rotate keys`, `replace params`, `replace`, `cancel`. Dialog titles `Rotate these
keys?`, `Replace parameters`. Empty state `Nothing minted yet`. Cells `held, never
shown — …`, `not in this image — …`, `never pushed — apply this node`, `hop —
none`, `no actions`.

## Do not relitigate

- **The handoff is contradicted twice, deliberately, and journalled**
  (`docs/decisions.md`, 2026-09-10): design §7's `minted`/`rotates` columns became
  `on the node`/`users on it` (no column records when material was minted; nothing
  rotates on a schedule), and **UI-PATTERNS §9's "generated on the node" is false**
  — `edge` is pure, so the panel says "minted by the control plane". A later
  screen copying §9's wording would describe our key handling wrongly.
- `rotation.py` reaches `relay._plainly` across modules rather than copying it,
  per M9.2's note naming it the shared helper.
- The console's key routes took new names because the old `/panel/transports/{id}/…`
  pair is also htmx-driven and cannot be told apart by a header. **M9.6 has
  nothing to take back here** — only `/nodes/{id}/apply`, `/hops` and `/dissolve`.

---

# Established by M9.5 — enable, withdraw, set state

Binds M9.6.

## Where the three actions live, and why

A node's row on `/panel/nodes` carries four buttons: `probe`, `apply`,
**`transports`**, **`set state`**. `transports` opens *Transports on \<node\>* — a
line per transport with its standing and one button (`withdraw` / `offer` / none
for a hop end) plus the enable form under it. `set state` opens *Set this node's
state* with only `NodeState.allowed_from`, each showing what it does to a user's
link.

**One dialog owns one subject.** A withdraw button beside each transport chip
would put controls in a *data* cell, which nothing else in this console does
(UI-PATTERNS §3), so the list and its creation form share one dialog. State is its
own dialog because it is about the node, not about what it runs.

## The enable route accepts DECLARED FIELDS, not rendered boxes

This is the guarantee that changed, and the old one must not be relied on again.

`transports.supplied_params(name) -> frozenset` is *every field an operator may
supply* — model fields **minus** `key_material_names(name)`. `hop_parameters` is
`sorted(supplied_params(name))`, so the hop form and the enable form cannot drift
about it. `operator_params` is untouched and remains the **required-only** subset.

`POST /panel/nodes/{id}/transports` reads a submitted name **prefixed for its own
group first, bare second**, over `supplied_params` — not over the boxes the dialog
drew. Why it had to change: the form renders a box per *required* field, so a
parameter the transport **defaults** was being silently discarded, and on the
shipped Reality transport that field is the **decoy port** — an operator's chosen
value replaced by the fleet-wide default, silently, on the wrong side of
`CLAUDE.md`'s *"never ship a shared default Reality decoy destination"*.

**A name the form cannot read is REFUSED (`NOT_ITS_PARAMETER`), not dropped** —
including a minted one — because the baseline refused it (`extra="forbid"`) and a
misspelled parameter silently becoming the default is the same defect one layer
down. The one exception is `<other-transport>-field`, which is **skipped**: a
hidden input is the dialog's own markup, not something the operator typed.

**`supplied_params(name) & key_material_names(name) == ∅` is what the widened
route rests on.** It has a per-transport test and a route-level one. The old
guarantee — *"the form renders no box for it"* — no longer holds.

**The bare shape of that POST is the non-htmx caller**, so its refusal is a **400
envelope**, not a 422 fragment. A test driving both shapes must expect both.

## Reusable

`console.offers_on(session, node_id)` / `offer_row(session, nt_id)` →
`OfferRow(id, node, transport, offered, for_friends, standing)`;
`console.state_choices(node)` → `StateChoice(state, means)` from
`NODE_STATE_MEANS`; `console.withdrawal_summary` / `offer_summary`;
`console.OFFER_HOP_END` — **the console's sentence for "this row is one end of a
hop"**, used by both the dialog row and the refusal banner, so the two cannot
disagree. A service message that names an API path does not reach the console.
`transports.offerable_transports()`, `transports.operator_tuning(name)` (a
`TuningField` tuple — `required` means the same as on the hop form, the **opposite**
of `ParamBox`).

**`offers_on` queries `NodeTransport` rather than reading `node.transports`,
deliberately.** Reached from a route that already loaded the node-transport,
`session.get(Node, …)` hands back an identity-mapped Node whose collection was
never loaded — `Node.transports` is `selectin` and the eager loader does not chain
to a joined-loaded parent — so touching it is `MissingGreenlet` at runtime.
Verified by a standalone repro. **Do not "simplify" it back.**

## Testing

`a_node_with_an_offer(client, reality_params)` → `(node_id, node_transport_id)`.
`_enable_boxes(markup, transport)` strips the group prefix. Refusals read with
`_described(response, "error", prefix="enable")` (keys are
`<transport>-<field>`) and `prefix="node"` for the state dialog. **Enable-form
boxes are named `<transport>-<field>`; a bare name is the old page's shape.**
Monkeypatch `nodes_service.profile` for a refusing transport on this path.
`MATERIAL_NODE = "keys-1"` is named once beside `a_node_holding_material` — select
by name, never by `/api/nodes` ordering.

## Wording acceptance will judge

Buttons `transports`, `set state`, `withdraw`, `offer`, `enable`. Dialog titles
`Transports on <node>`, `Withdraw <transport>?`, `Set this node's state`. Toasts
`<transport> enabled on <node> — apply the node to push it`; `<transport>
withdrawn on <node> — out of every user's link at their next refresh. The node is
still configured to serve it: apply it to stop that.`; `<transport> offered again
on <node> — …nobody re-imports anything.`; `<node> is now <state>`. Empty states
`Nothing is enabled on <node> yet…` and `Every protocol this image can hand to a
user is already enabled on <node>.`

## WHAT M9.6 MUST KNOW

**Routes to take back** (all took long names only because the old page drives the
same job *with htmx* and cannot be told apart by a header):

- `/nodes/{id}/push` → `/apply`
- `/hops/establish` + `/hops/{id}/tear-down` → `/hops` + `/dissolve`
- `/nodes/{id}/set-state` → `/nodes/{id}/state`
- `/nodes/transports/{id}/withdraw|offer` → the old `/transports/{id}/state`
- M9.4's key routes take nothing back — they already own good names.

**Two routes are SHARED, not duplicated.** `POST /panel/nodes` and `POST
/panel/nodes/{id}/transports` each keep a 303 branch for the plain browser form.
Deleting the pages means deleting those branches, plus
`test_the_pre_redesign_form_still_gets_its_redirect`,
`test_the_pre_redesign_enable_form_still_gets_its_redirect`, and the bare-name
fallback in `supplied()` inside the enable route.

**Still driving old routes after M9.6 deletes them:**
`tests/e2e/control/test_a_replacement_node_and_a_protocol_from_the_panel.py` —
`reality_from_the_panel` (expects 303) and `state_from_the_panel` (`POST
/nodes/{id}/state`, expects an `outcome.html` fragment). The withdraw half is
already repointed and now walks button → confirmation → POST rather than assuming
a URL.

## Do not relitigate

- `establish_hop_dialog.html` names all its boxes `entry-<field>` regardless of
  transport, so two hop-capable transports sharing a field name would collide.
  Latent — one carrier ships. M9.2's, not M9.5's.
- `server_names` has no `description`, so its enable box shows no hint. Same as the
  old page; closing it is an `edge`-side declaration.

---

# Established by M9.6 — the old pages are gone

Binds M10 and everything after.

## What no longer exists

`pages/index.html`, `pages/node.html`, `pages/base.html`, `panel/outcome.html`,
`panel/health.html`; `GET /panel/fleet`, `GET /panel/nodes/{id}`, and the eight
action routes that only answered them. **Both old URLs are 404**, asserted — and
the `/panel/nodes/{id}` assertion is written against a node the test creates,
because a random id would 404 through `NotFound` anyway and prove nothing.

**The console routes took their short names back:** `/nodes/{id}/apply`,
`POST /hops`, `/hops/{id}/dissolve`, `/nodes/{id}/state`. The long names existed
only because the old pages drove the same jobs *with htmx* and could not be told
apart by a header. Withdraw and offer stayed **two routes**, not one toggle — the
namespace was freed, but M9.5's split (one destructive and confirming, one not) is
on the do-not-relitigate list.

**`boost` and `note` are gone from `NAV` and from `nav.html`.** The Fleet entry
was the only unboosted, noted one. Every console entry is boosted now, so there is
nothing to set — **M8's step-notes still say `boost: True` and now carry a
supersession note.** Passing it is harmless and does nothing.

**The 303 branches are gone** from `POST /panel/nodes` and
`POST /panel/nodes/{id}/transports`, with their two tests and the bare-name
fallback in `supplied()`. **A bare field name is now refused** (`NOT_ITS_PARAMETER`),
not merely unread: deleting the fallback alone would have told an operator who
filled a bare `port` that they left the box *empty*, which is a lie about what
happened.

## Never let a sentence name a surface that is gone

This is the High this step shipped and had to fix, and it is the one a deletion
diff will produce again.

An **incomplete revocation** — the moment somebody who should be cut off is still
connected — drew a banner ending *"Retry from the node's page."* on the Users
screen. That page had just been deleted. Every docstring and `hx-*` attribute was
swept; this survived because it is **service prose that nothing asserted**.

**`apply.WHERE_TO_RETRY = "the Nodes screen"`** is now the one place that names
where to finish a half-done push. `RevocationOutcome.summary()`,
`RotationOutcome.summary()` and `console._unpushed` all read it, so the console
and the API envelope cannot drift. It lives in `apply.py` because finishing a push
is that module's subject and all three already import it — no new edge, no cycle.

**`test_no_sentence_this_panel_hands_an_operator_names_a_surface_that_is_gone`**
parses every module under `control/app/` with `ast` and sweeps every
**non-docstring** string literal against `DELETED_SURFACES`. The docstring
exclusion is the instrument, not an oversight: a comment about a page that once
existed is history and belongs in the file; a **literal** is something the code
hands somebody. `main.py` sets `docs_url`/`redoc_url`/`openapi_url` to `None`, so
no docstring is ever served — verified, not assumed. 823 literals scanned; it
reaches `Constant` nodes inside f-strings, which is the shape these sentences now
use.

**Read `carry-over.md` before you trust it** — `DELETED_SURFACES` is
hand-maintained and does not cover everything the docstring implies.

## Templates and e2e

**The template scan now walks `TEMPLATES.rglob("*.html")`, not just
`templates/panel`.** Its old exclusion — *"the pre-redesign pages carry all four
and M9.6 deletes them"* — went void the moment those pages went, leaving
`console.html` and `login.html`, two **live** templates, silently outside a scan
standing over M9's own "done when".

**The e2e standard is: read the URL off the rendered dialog, never write it
down.** `form_action(operator, dialog_url, opened_by=…)` and `button_in(…)`
generalise the walk `withdraw_button` established. Seven e2e files were repointed;
`reality_from_the_panel` now asserts `200` + no `<html>` (unambiguous, because
every refusal on that route is 422 or 400, never 200), and `state_from_the_panel`
keeps both original assertions against `mutation_result.html`.

**Send `HX-Request: true` on every panel POST** — nothing answers a header-less
one with a redirect any more.

## What acceptance will meet

- **Nothing outside the console shell exists.** Every job is reachable from a
  sidebar entry or a row button; there is no URL to type.
- **The sidebar is six entries** — Overview, Users, Nodes, Hops, Transports,
  Keys & configs. No Fleet, no note under any label.
- **Two refusal statuses:** 422 re-renders a dialog; 400 is what a caller that is
  not the console gets. `app.js` swaps only 422.
- **After a partial revocation, rotation or replacement**, the operator is told to
  *"apply those nodes again from the Nodes screen once they can be reached"* — a
  screen that exists, one sidebar click away.
- No other operator-visible wording changed. Everything acceptance judges is what
  M9.1–M9.5's notes recorded.
