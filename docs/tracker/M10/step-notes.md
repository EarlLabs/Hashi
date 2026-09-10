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
