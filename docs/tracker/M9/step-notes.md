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

**Read `carry-over.md` before you add a banner:** that scan still has known holes
for banners *added* in unusual syntactic shapes. Do not take a green run as proof
your new banner was inspected.

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
