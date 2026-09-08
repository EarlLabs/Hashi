# Handoff: VPN admin panel (hashi)

## Overview
A redesign of the self-hosted VPN mesh admin panel. The original was a single scrolling page
mixing node management, hop configuration and user management. The redesign splits it into nine
screens behind a persistent sidebar, moves all creation flows into modals, and collapses the
24-field hop tuning form behind an "advanced tuning" disclosure with defaults pre-filled.

Primary job the design optimises for: **add a user, hand them their subscription link, and see at a
glance whether the mesh is healthy.**

## About the design files
The files in this bundle are **design references created in HTML** — a prototype showing the
intended look and behaviour, not production code to copy directly. The task is to **recreate this
design in your codebase's existing environment** (React, Vue, Svelte, server-rendered templates —
whatever the panel already uses), following its established patterns. If no frontend exists yet,
pick the framework that fits the backend and implement the screens there.

The prototype's data is hard-coded placeholder data. Every list, counter and log line must come
from the real API.

## Fidelity
**High fidelity.** Colors, type, spacing, borders and interaction states are final and come from
the Industry design system (`design-system/styles.css`, included). Recreate them exactly; the
stylesheet can be used as-is or ported to your styling layer. Layout proportions are final; copy
is final unless the API forces different terms.

## Screens / views

Shell (all screens):
- CSS grid, `218px minmax(0,1fr)`. Below 900px it collapses to one column and the sidebar becomes a
  horizontally scrolling top bar.
- **Sidebar**: sticky, full viewport height, 1px right divider (`--color-divider`), padding `--space-4`.
  Contains the wordmark (Barlow Condensed 21px) with the kicker "private mesh" (11px, uppercase,
  0.08em tracking, muted), the nav list, and a footer block ("signed in as root" + log out button)
  pushed down with `margin-top:auto`.
- **Nav item**: block link, padding 7px 9px, 14px, transparent 1px border. Hover: 6% text tint.
  Active (`aria-current="page"`): background `--color-accent-100`, text `--color-accent-800`,
  border `--color-divider`.
- **Header**: flex row, `--space-6` side padding, bottom divider. Left: h2 screen title + 13px muted
  subtitle. Right: "probe all nodes" (secondary) and "add user" (primary, blueprint marks).
- **Body**: `.panel`, padding `--space-6`.

1. **Overview** — health at a glance.
   Four stat cards in a 4-up grid (`.card.blueprint`): kicker (10px uppercase accent), value
   (Barlow Condensed 38px, line-height 1), meta line (11px muted). Values: nodes online, active
   users, throughput now, hops.
   Below: two-up grid of framed cards — Users preview table (nickname / status / last seen / link)
   and Nodes table (name / exit / state / load), each with an "all …" link in the card header.
   Below that: Recent activity table (time / actor / event), first six audit entries.

2. **Users** — the list of people who can dial the mesh.
   Full-width table: nickname, status tag, added, last seen, nodes served (`3 / 3`, monospace),
   right-aligned actions "show link" and "revoke" (label flips to "restore" when revoked).
   Footnote: "A user gets one subscription URL covering every serving node. Nothing else is stored
   about them."

3. **Nodes** — machines that serve or exit traffic.
   Right-aligned "add node" (secondary) above the table. Columns: name, exit country, address
   (monospace), state tag, transports (wrapping tag row; disabled transports render as
   `name (disabled)` in a neutral tag), actions "probe" and "apply".

4. **Hops** — entry node → leaf node.
   Explainer paragraph (max 60ch, muted) with "establish hop" (secondary) right-aligned on the same
   row. Table: entry node, leaf node, transport, state tag, established, "tear down".

5. **Transports** — read-only capability table discovered from the image.
   Columns: name (mono), family, ports (mono), how a user receives it, on a filtering network.
   The wireguard row's filtering cell reads "identified and blocked — never offer as an exit".
   Footnote: "Discovered from the image, not listed anywhere. A new protocol appears here on its own."

6. **Traffic** — a framed card with a 14-bar column chart (180px tall, 6px gap, bars
   `--color-accent-500`, day number under each bar at 10px muted), then a "By user, this month"
   table: nickname, down, up, sessions, busiest node.

7. **Keys & configs** — scope, transport, fingerprint (truncated, mono, muted), minted, rotates,
   "rotate" action. Lead paragraph: key material is generated on the node, minted once, never
   displayed again, never typed into the panel.

8. **Audit log** — time (mono, 160px), actor (140px), event, source (mono, 150px).

9. **Settings** — two-up: Admins table (user / role / last login) and a Panel form
   (mesh name, subscription base URL, log retention days) with a primary "save".

## Modals
Backdrop `.dialog-backdrop` (fixed, 50% `--color-neutral-900`), click-outside closes;
content click stops propagation. The dialog itself needs an **opaque background**
(`background: var(--color-bg)`) because the design system's `.dialog` is transparent by default.

- **Add a user** — one nickname field + explanatory body. On submit: create the user, close, then
  immediately open the subscription-link modal for them and route to Users.
- **Subscription link** — the URL in a bordered monospace block (`word-break: break-all`,
  `--color-surface` fill), "copy link" primary. Copy: "One URL, every serving node. Sharing it
  again does not mint a new key."
- **Add a node** — 560px, two-column grid of fields (name, address clients dial, exit country label,
  ssh host, ssh user, ssh port) plus a full-width ssh private key textarea
  ("stored encrypted; never displayed again").
- **Establish a hop** — 620px, `max-height:86vh`, scrolls. Three fields across: entry node, leaf
  node, transport. Then `<details>` "advanced tuning — 12 parameters per end" containing two
  columns (entry end / leaf end), each an 11-parameter list rendered as
  `label 1fr | input 92px` rows at 28px height, placeholders carrying the transport default.
  Footnote: "Key material is generated for both ends and minted once. Never type a key here."

## Interactions & behaviour
- Sidebar navigation swaps the main region; no page reload. Modals close on route change.
- Every mutating action fires a **toast**: fixed bottom-right (24px), `--color-accent-900` ground,
  `--color-bg` text, 13px, registration marks, auto-dismiss after 2200ms, one at a time
  (a new toast clears the pending timer).
  Messages used: `probing 3 nodes…`, `probing <node>…`, `config applied to <node>`,
  `<nick> revoked — link is dead`, `<nick> restored`, `link copied`,
  `node queued — first probe in progress`, `hop establishing…`, `hop torn down`,
  `<node> key rotated`, `settings saved`.
- Revoke is a toggle in the prototype (revoke ⇄ restore). In production revoke should be
  confirmed and, if the key cannot be re-minted, irreversible — replace the toggle with a
  confirm dialog and a disabled row state.
- Adding a hop inserts it in state `pending`; the prober flips it to `established`.
- Tear down removes the row optimistically.
- Focus: 2px `--color-accent` outline, 2px offset, on every interactive element (design system
  default — do not override).
- Responsive: below 900px the sidebar becomes a top scroller and all multi-column grids collapse to
  one column. Tables scroll horizontally inside their panel.

## States not yet drawn (implement these)
Empty states (no nodes, no users, no hops), loading skeletons for tables, request failure banners,
field-level validation errors on the add-node and add-user forms, and a disabled/pending row
treatment while a probe or apply is in flight.

## State management
`route`, `dialog` (`null | 'friend' | 'node' | 'hop' | 'link'`), `linkFor` (user id),
`draftNick`, `toast`, plus the collections `users`, `nodes`, `hops`. Server-side these map to:
users (id, nickname, status, added, lastSeen, nodesServed), nodes (name, country, address, state,
load, transports[{name,enabled}]), hops (entry, leaf, transport, state, since), keys, audit log,
traffic series. Note: in the prototype code the users collection is still named `friends`
internally — rename on implementation.

## Design tokens
All tokens come from `design-system/styles.css`. Do not hard-code values that exist there.

Color — ground `#f2f2f3`, surface `#e9e9ea`, text `#1d1f20`, accent `#5980a6`,
divider `color-mix(in srgb, #1d1f20 16%, transparent)`.
Accent ramp 100→900: `#eef6ff #d6ebff #b5d9fd #94bce3 #749dc4 #597ea3 #416180 #2c455d #1d2d3d`.
Neutral ramp 100→900: `#f5f5f8 #e7e7ea #d4d4d7 #b7b7ba #98989b #7a7a7d #5d5d60 #424244 #2b2b2d`.

Spacing — 1: 3.4px, 2: 6.8px, 3: 10.2px, 4: 13.6px, 6: 20.4px, 8: 27.2px.

Type — headings Barlow Condensed 600, body Barlow 400, base 15px/1.55.
h1 42 · h2 32 · h3 25 · h4 20 · h5 16 · h6 13 (uppercase, 0.08em).
Monospace for addresses, ports, fingerprints, URLs and parameter names:
`ui-monospace, "SF Mono", Menlo, monospace` at 13px.

Radius — components are square (0). `--radius-sm/md/lg` = 2/4/7px exist but the blueprint layer
resets `.card .btn .input .tag .seg .dialog` to 0.

Shadow — `--shadow-sm/md/lg`; used only on the toast (md) and dialogs (lg).

## Assets
None. No images, no icon set is used in the prototype. If icons are added, use Lucide at
stroke-width 1.5 per the design system.

## Files
- `VPN Admin.dc.html` — the prototype, all nine screens and four modals.
- `UI-PATTERNS.md` — the pattern rules to follow when adding new screens or features.
- `design-system/styles.css` — the Industry token sheet and component layer. Link it, or port it.
- `design-system/readme.md` — the design system's own guide.
