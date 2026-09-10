# M9 — carry-over

Non-blocking findings left open, with the reason each was left. Read them as
BACKGROUND: they tell you what is known-wrong so you do not mistake it for the
intended design. Do not fix them as part of another step.

## From M9.1, review round 1 — deliberately carried

- **Low — the template scanner has holes.**
  `test_no_console_template_names_a_transport_a_country_an_address_or_a_port`
  catches the shapes these values usually take, but a **port named in prose**
  (`"Leave empty for port 22."`), a **domain** (`fra-1.example.com`), and any
  **country outside its closed seven-word list** (`Sweden`, `Kazakhstan`) all
  pass. `CLAUDE.md` also names "domain" and "provider", neither of which is
  checked. Verified by mutation — both prose forms scanned clean. **Treat that
  scan as a backstop, not a licence:** it will not tell you that your new screen
  named a port. Suggested fix: a bare-word port pattern (`\bport\s+\d{2,5}\b`), a
  hostname pattern with a TLD, and a docstring saying the country list is
  illustrative rather than exhaustive.
- **Low — `.row-detail` has no rule.** `panel/nodes_table.html`'s "why this node
  is degraded" row carries `class="row-detail"`, which exists in neither
  `app.css` nor `styles.css`, so it is visually indistinguishable from a data
  row. The class reads as intent that did not land. Either give it a rule (no top
  border, indented, smaller type) or drop it and rely on `.text-muted`.
- **Low — two sources of truth for the SSH defaults.**
  `control/app/services/nodes.py`'s `DEFAULT_SSH_USER` / `DEFAULT_SSH_PORT` were
  introduced as the single place these live, but `api/schemas.py`'s `NodeCreate`
  keeps its own `default=22` / `default="root"`, and that is what `POST
  /api/nodes` actually applies. Change the constant and the two surfaces
  disagree — the exact drift the constant was added to prevent.

## From M9.1, review round 3 — sent to a fix step-loop, not carried

Round 3 was the last of the cap and returned `VERDICT: 0 critical, 0 high`, so
M9.1 converged. Two of its Mediums were nonetheless sent through a **fresh fix
step-loop** rather than banked, because M9.2–M9.6 add four more screens and both
findings mislead the implementer who reads them:

1. the banner scan is sound against a banner that *replaces* an existing one but
   blind to four shapes of banner *added* alongside them — a non-`div` element,
   unquoted attribute values, a `>` inside the opening tag, and a
   Jinja-conditional failure class. The last two are the plausible ones here: the
   class attribute is already Jinja-assembled in `nodes_table.html` and
   `overview_body.html`;
2. `panel/banner.html`'s own header comment still asserted the rule this step
   superseded (*"Not red: UI-PATTERNS §4"*), so the next implementer reading it at
   the point of use was told the opposite of the decision.

See `fix-notes.md` for how they landed. **Until that loop closed, a green run of
the banner scan was not proof your new banner was inspected.**
