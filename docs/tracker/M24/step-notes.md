# M24 — step notes (2026-10-02)

The panel never showed the URL that delivers a config-file transport. Built under the
owner's decision of 2026-10-02 — **one URL per config shape, not one polymorphic link**.
Branch `task/M24`, stacked on `task/M31` (baseline `c5aa953`). Solo topology; closed with
the review-loop skill (`reviewer-strict`). **No real host was touched.**

| step | what changed | test red before it |
|---|---|---|
| M24.1 (control) | `console.links_for` / `shapes_held` / `_link_url`: the one composer of a user's URLs (replaces `console.subscription_url` and the API route's own f-string). Link dialog: one labelled block per link, its own copy button. API: `config_file_url`. Nodes row, enable dialog, re-offer toast, Transports screen name the config-file link. Five "one subscription URL" sentences rewritten. | `tests/control/test_the_panel_hands_over_the_config_file_link.py` — 8 of 9 red on `c5aa953` (with the new constants stubbed in so it collects; the 9th is the registry-wide label guard); e2e `tests/e2e/control/test_the_panel_hands_over_the_link_that_delivers_a_config_file.py` |
| M24.2 (docs) | Runbook Shape A step 4 and "The two families are delivered differently"; PLAN M24 premise corrected; decisions row; this tracker. | docs only |
| M24.3 (control) | Review round 1 (medium): a link no longer says it *carries* a transport on a draft/degraded node — "…once its node is serving". | the degraded step of `test_a_withdrawn_config_file_row_…` |

Which rows count (decision row, 2026-10-02): enabled, user-facing, node not retired
(`apply.cannot_serve_again`), transport declares the shape. Draft and degraded nodes
count so that a link handed over during a bad minute is still the right one.

Bearer-credential check — every new place a URL now exists: the dialog's text (same
`no-store` fragment as before, never an attribute); the API response (same route as
before). No logger call, audit row, error message or `title` carries either. Tested:
`test_no_new_place_records_either_link` (app log records, audit rows, attributes,
`Cache-Control`), and the e2e scenario reads the control container's own log.

Tests changed rather than added: none. `console.subscription_url` had no test callers.
