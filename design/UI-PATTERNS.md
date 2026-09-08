# UI patterns — VPN admin panel

How to add a screen or a feature without the panel drifting. Read this with
`design-system/readme.md`; that file governs the visual language, this one governs
how the panel applies it.

## 1. Screen anatomy
Every screen is: sidebar entry → header (title + one-line subtitle) → `.panel` body.
The subtitle states what the screen *is*, in lowercase prose, not a marketing line.
Nothing else lives in the header except global actions.

## 2. One primary action per screen, in the header
"add user" is the panel's global primary and stays in the header everywhere.
A screen's own creation action ("add node", "establish hop") is **secondary**, right-aligned
directly above its table. Never two solid accent buttons on screen at once.

## 3. Tables are the default layout
Any collection is a `.table`. Column order: identity → status → context → numbers →
right-aligned actions. Row actions are `.btn.btn-secondary` in an inline-flex group with
`--space-2` gap; destructive actions are not colored red — they read as plain secondary buttons
and confirm in a dialog.

## 4. Status is a tag, never colored text
- `tag-accent` — good and current: active, established, online.
- `tag-outline` — needs attention or in flight: degraded, pending, probing.
- `tag-neutral` — inert: revoked, disabled, expired.
There is no red. The steel accent is the only color; severity is carried by the word and by the
tag's weight. A blocked capability (like wireguard) states the fact in prose in its own cell.

## 5. Creation happens in a dialog, never inline on the page
The original panel put a full form under every table. Dialogs keep the list readable. A dialog is:
title → fields → one-sentence body explaining consequences → actions (cancel secondary,
confirm primary, right-aligned). Always set `background: var(--color-bg)` on `.dialog`.

## 6. Progressive disclosure for expert parameters
If a form has more than about eight fields, the first block holds the decisions
(which node, which transport) and everything else goes into a `<details>` disclosure labelled with
its cost — "advanced tuning — 12 parameters per end". Every advanced field carries its default as
the placeholder, so an empty field visibly means "use the default".

## 7. Machine values are monospace
Addresses, ports, fingerprints, subscription URLs, parameter names, ratios like `3 / 3`.
Human values (names, countries, dates, prose) are Barlow. This is the fastest way to tell
"the admin typed this" from "the mesh reported this".

## 8. Feedback is a toast, and it names the object
Lowercase, present tense, the object named: `config applied to fra-1`, not `Success!`.
An action with a delayed real-world effect says so: `hop establishing…`,
`node queued — first probe in progress`. 2200ms, bottom right, one at a time.

## 9. Secrets are stated, never shown
Anywhere key material could appear, the panel prints the rule instead:
generated on the node, minted once, never displayed again, never typed here.
Fingerprints are truncated (`9f3c…a17d`). Subscription URLs are the one shareable secret and get
their own dialog with a copy button.

## 10. Frames carry meaning
`.blueprint` + four `<i class="corner">` marks go on: stat cards, dialogs, the toast, and framed
panels on Overview and Settings. Plain full-width tables inside `.panel` are not framed — framing
everything makes framing say nothing.

## 11. Density
Comfortable is default. A compact mode exists (`data-density="compact"` on the app root) that
tightens table cell padding to `4px var(--space-2)` and panel padding to `--space-4`. New tables
must respect it; do not hard-code cell padding.

## 12. Responsive rule
Single breakpoint at 900px: sidebar → horizontal top scroller, all multi-column grids → one column.
Do not introduce new breakpoints; build grids as
`repeat(N, minmax(0, 1fr))` so they collapse with the existing rule.

## 13. Copy
Lowercase for actions and system messages ("add user", "probe all nodes", "tear down").
Sentence case for headings and explanatory prose. Say what a thing does to the mesh, not what the
button does: "A hop sends traffic from the node users dial into a second node that carries the
exit." No exclamation marks, no emoji.

## Checklist for a new screen
- [ ] Sidebar entry, title, one-line subtitle
- [ ] Collection rendered as `.table`, actions right-aligned
- [ ] Status shown as a tag from the three roles above
- [ ] Creation in a dialog with an opaque background
- [ ] Expert fields behind `<details>` with defaults as placeholders
- [ ] Machine values in monospace
- [ ] Every mutation emits a toast naming the object
- [ ] Empty, loading and error states drawn
- [ ] Works at 900px with no new breakpoint
- [ ] No color outside the steel accent ramp
