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
