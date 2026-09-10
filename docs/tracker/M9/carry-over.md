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

## From M9.2, review round 3 — cap spent, left open

All non-blocking; every round returned `VERDICT: 0 critical, 0 high`, and round 3
ran both gates itself (`make test-control` 346, `make e2e-verify` 146).

- **Medium — a hop mistyped at BOTH ends reports only the entry one.**
  `control/app/services/relay.py:216-244` validates the entry end first and raises
  on the first failure, so with both `entry-tunnel_address` and
  `leaf-tunnel_address` set to a public range, the 422 marks
  `entry-tunnel_address` alone and **the leaf's equally-invalid value comes back
  unmarked, looking accepted.** The corrected acceptance line reads *"each refusal
  arrives under its own box"*; here one of two refusals silently does not arrive,
  and the operator pays a second round trip mid-rotation. Note the empty-box
  pre-check in the route DOES collect both ends at once — only transport-model
  refusals behave this way. **This is deferred, not intended: do not read the
  current behaviour as the design.** The fix is to accumulate `ValidationError`s
  per end into one `HopEndRefused` carrying `{purpose: fields}` and let
  `_on_their_boxes` place both prefixes.
- **Low — box counts in comments have drifted.** `hop_tuning` returns 12
  parameters per end, so the dialog renders 24 tuning boxes, but `_hop_form`'s
  docstring (`panel/routes.py:408`), the e2e comment
  (`test_the_panel_fetches_nothing_from_a_third_party.py:70`) and the template's
  macro comment (`establish_hop_dialog.html:32`) all still say twenty-two, while
  `errors.py:66` and `routes.py:353/501` correctly say twenty-four. The codebase
  states two different numbers for the same thing. (The template's "twenty-five
  things" for the *old* form is correct — that form uses `operator_params`, which
  drops `client_dns`.)
- **Low — `transports.py:240`'s `tuning_field` docstring** still says "no
  transport declares a default for a hop parameter" without the *requires*
  qualifier, which would tell a skimming reader the placeholder path is dead code.
  The journal headline was narrowed on 2026-09-10; this docstring was not.

## From M9.3, review round 1 — a contract gap, recorded rather than worked around

Not a defect in what shipped; a limit on what the Transports screen can honestly
say, and the reason it says less than the journal knows.

- **`TransportMeta` cannot express "proven on hardware" or "known packaging
  limitation".** The capability table projects declared fields only, so those two
  facts are absent from it by construction. `docs/decisions.md` (2026-09-09) holds
  both for the transports this image ships: `amneziawg` is proven end to end on
  real hardware, and a user-facing plain-WireGuard row is *not* proven and is
  likely to fail silently under the pinned `masipcat/wireguard-go` image on a
  `ufw` host — handshake completes, nothing moves, nothing logged. The screen
  therefore warns about that transport for the reason it *does* declare
  (`blocked_by_inspection`), and its "how a user receives it" cell already reads
  *"not in a user's link yet — this panel cannot hand it over"*, which is the
  narrow exposure the journal names. **Closing the gap properly is an `edge`-side
  declaration in a task of its own** — a new field the transport sets about
  itself. It is not a `control` special case, and `control` may not compare a
  protocol's name to close it. The same limit is why
  `TRANSPORT_WHY_IDENTIFIED` states a capability and recommends no action: advice
  has to be right about the whole stack, and for that transport it would not be.

## From M9.3, review round 2 — cap not spent, left open as a Low

- **Low — an unexercised branch behind a load-bearing docstring claim.**
  `control/app/services/console.py:437`'s `else TRANSPORT_NO_DELIVERY` never runs:
  every shipped transport declares a non-empty `subscription_formats` (the field
  defaults to `{V1_URI_LIST}`), and the synthetic meta in
  `test_the_warning_follows_a_declaration_and_never_a_protocol_s_name` takes that
  default too. `_transport_row`'s docstring makes *"these two conditions are not
  the same condition"* a load-bearing claim, and only the
  `subscription_expressible` half has a test standing over it — **a later edit
  collapsing the two would stay green.** Fix is one more call through the existing
  `a_fleet_of_one` harness with `subscription_formats=frozenset()`, asserting
  `TRANSPORT_NO_DELIVERY` is read and `TRANSPORT_UNDELIVERED` is not. Carried
  rather than fixed because both rounds returned clean and this is a Low; it is
  the same defect class as the rest of this milestone's findings, so it is worth
  doing when someone next touches that function.
