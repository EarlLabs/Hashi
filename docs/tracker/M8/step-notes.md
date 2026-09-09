# M8 — step notes

Conventions established here. They bind later steps, and M9/M10, until something
supersedes them. Follow them; do not relitigate.

## Adding a screen

A route calls `_screen(request, screen="panel/screens/<x>.html", current=<nav key>,
title=, subtitle=, context=)` in `control/app/panel/routes.py`. It renders
`pages/console.html` for a browser and `panel/screen.html` (screen + nav
out-of-band) when `HX-Request: true`. Add the entry to `NAV`; `boost: True` for a
console screen.

**Screen template shape:** `{% include "panel/console_header.html" %}` then
`<div class="panel">…</div>`. Put the collection in its own fragment that swaps
itself (`hx-target="this" hx-swap="outerHTML" hx-indicator="this"`,
`hx-trigger="<thing>-changed from:body"`) so first paint and refresh are one
file — see `panel/friends_table.html`.

## Mutations

Return `panel/mutation_result.html` via `_mutation(request, dialog=…, toast=…,
banner=…, events=…)`. Toast for success, banner for a partial one. **OOB swaps
must be `innerHTML:#slot`, never `hx-swap-oob="true"`** — outerHTML replaces the
slot node and kills `app.js`'s MutationObserver.

**Field validation returns 422** with the dialog re-rendered; `app.js` allows
exactly that one status to swap. Anything else fires the failure banner.

## CSS

`.stack-6`/`.stack-8`, `.grid-2`/`.grid-4`, `.mono`, `.table-scroll`,
`.row-actions`, `.row-inert`, `.empty`/`.empty-title`/`.empty-body`,
`.skeleton-row`, `.banner`, `.field-error`, `.card-head`/`.all-link`,
`.stat-value` all live in `/static/app.css`. **Do not add a breakpoint** — there
is one, at 900px, per UI-PATTERNS §12.

## Tests

`tests/control/test_the_console.py` has `a_serving_node(client, reality_params)`
and `_visible_text(html)` (strips Jinja comments and tags — needed for the
decision-9 "no `friend` in visible copy" assertion). Standard `client` fixture,
no chdir.

**THE LIST IS THE TEST.** `tests/e2e/control/test_the_panel_fetches_nothing_from_a_third_party.py`
holds `PANEL_PAGES` (navigable documents), `PANEL_FRAGMENTS` and a `surfaces`
fixture for the id-parameterised ones. **Every new screen, dialog or
self-refreshing table joins one of them in the same change that adds it.** The
first version of that list omitted the dialogs — including the one carrying the
bearer credential — and an external reference planted there was invisible to the
runtime scenario while the source scan caught it. That gap was the finding.

Its `offenders()` returns **origins, not URLs**, and no assertion prints a
response body, because one of the fetched surfaces renders a live subscription
token and a scenario that leaked one into a CI log would be a worse defect than
the one it closes.

## Wording a person sees, which acceptance judges

Toasts `mira added`, `mira revoked — link is dead`, `link copied`. Dialog titles
`Add a user`, `<nick>'s link`, `Revoke <nick>?`. Buttons `add user`, `show link`,
`revoke`, `copy link`, `close`, `cancel`. Sidebar `Overview` / `Users` /
`Fleet (nodes · hops · transports)`. Footnote: *"A user gets one subscription URL
covering every serving node. Nothing else is stored about them."*

## Do not relitigate

- `friend` stays in routes, services, schemas and tests; only the rendered page
  says "users" (decision 9).
- The Overview's node preview links to `/panel/fleet` and repoints to the Nodes
  screen when M9 lands.
- `console.drift_of` is the local digest comparison; do not confuse it with the
  probe's `drifted`/`stale` (`docs/tracker/M1/step-notes.md`).
- `pages/index.html` and `pages/node.html` are **not** deleted until M9.5.
