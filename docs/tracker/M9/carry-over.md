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
findings misled the implementer who read them: the banner scan was blind to
shapes of banner *added* alongside the existing three, and `panel/banner.html`'s
own header comment still asserted the rule M9.1 superseded.

**Both are now fixed and the loop has closed** — see `fix-notes.md` for what the
scan became, how hard it was attacked, and the four non-blocking findings left
open there. Two things from it bind every later screen:

- **One element, one banner.** Declaring `class` or `role` twice — including once
  per Jinja branch — is a fault.
- **Put the literal class name in the attribute.** A failure class arriving
  through a variable or a `{% set %}` is invisible to the scan.

**The accurate record of what the scan still cannot see is `_banner_faults`'s own
docstring in `tests/control/test_the_console.py`.** Read that before you rely on
a green run — not this file, which will age.
