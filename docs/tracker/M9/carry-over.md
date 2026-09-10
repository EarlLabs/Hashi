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

## From M9.4, review round 1 — a deferral, recorded rather than fixed

Background, like everything else in this file: it tells you what is known-wrong so
you do not mistake it for the intended design. Do not fix it as part of another
step.

- **Medium — rotating one end of a hop re-mints a SYMMETRIC value at that end
  only.** `control/app/services/rotation.py`'s `rotate_keys` mints node-scoped
  material for the one `node_transport` it was given and pushes that one node. On a
  hop end whose transport declares `KeySpec.shared_between_peers` — the shipped
  hop carrier declares it for its pre-shared key — that leaves the two ends holding
  different copies of a value they must share: **two individually valid
  configuration files and a handshake that never completes**, with nothing in any
  log to say why. `docs/decisions.md` (2026-08-09) records that the declaration
  exists *because* `control` mints each end separately, and `relay.establish_hop`
  already acts on it by minting once and copying; rotation reads it only to compose
  prose. Pre-existing — the API has behaved this way since item 23, and the
  pre-redesign node page offered the same button with no warning at all — so M9.4
  did not change the behaviour: it **states the consequence in the confirmation
  dialog** (`console.KEY_SHARED_WITH_PEER`, written from the declaration and never
  from a protocol's name) rather than hiding an action that M9.6 would otherwise
  leave without a home. **Do not read the current behaviour as the design.** The
  fix is to rotate BOTH ends in one transaction whenever any spec declares
  `shared_between_peers` — mint once, copy to the peer the way `establish_hop`
  does, then push both nodes and report honestly if either push failed — at which
  point the dialog's sentence changes from a consequence to a cost.


## From M9.4, review round 3 — THE RUN STOPPED HERE

**M9.4 did not converge.** Round 3 was the last of the cap and returned
`VERDICT: 0 critical, 1 high`. Under `step-loop` Phase 3 and `autopilot` §4 —
*"the round cap is spent, in review or in acceptance, with blocking issues
open"* — the run stops rather than working around it. Everything built is
committed and both gates are green (`make test-control` 391, `make e2e-verify`
147, both run by the reviewer, not claimed by the builder).

**Do not read the open High below as intended behaviour, and do not start M9.5
until it is settled.**

### HIGH, open — the console can render the node's decrypted private key

`control/app/panel/routes.py:971` with `control/app/services/rotation.py:261-270`.

The allow-list closes the class of **locations** and not the class of
**messages**. A `field_validator` on a field the form *does* have a box for reads
other already-validated fields through `info.data` — and `merged` at
`rotation.py:229` is `{**params, **typed, **stored_secrets}`, so
`info.data["private_key"]` is the decrypted secret. Pydantic locates that error
at `("decoy_host",)` → `"decoy_host"`, which **is** in `boxes`, so
`_refused_parameters` prints the sentence verbatim.

Reproduced by the reviewer against the shipped `vless-reality` row with only the
model swapped: `POST /panel/keys/{id}/params` answered 422 with
`<div class="field-error" id="param-decoy_host-error" role="alert">does not match
the key &lt;the node's real private key&gt;</div>` — **visible text, on the Keys &
configs screen's own dialog**, which is precisely where M9's acceptance line says
*"you must not find one"*.

**Latent today** — it needs a transport whose validator quotes `info.data`, and
none ships. By this milestone's own repeated standard (*guarded rather than
watched*) that is the reason to close it, not to leave it. Note the diff's own
reasoning already contains the answer and simply was not carried across:
`routes.py:812-818` argues that on the rotate path *"a complaint may be quoting
material whichever field it names."*

**The reviewer's proposed fix — redact rather than sort.** `replace_params` holds
`stored_secrets` at the moment it builds `fields`: strip any stored secret value
out of every `error["msg"]` (and out of `problems`) before either leaves the
service. One place, and it closes `fields`, `message`, the console, the old page
and the API at once — and closes the Medium below with it. Then widen
`test_no_answer_to_a_rotation_shows_what_it_minted` to sweep the **replace** POST
answer too, with a validator quoting `info.data` as the red-first case.

**The identical shape exists in `relay.py:230-244` for `HopEndRefused`** —
pre-existing, not this diff's, same fix location.

### Medium, open — the C split's stated reason does not hold

`control/app/services/rotation.py:265-270`. The comment argues *"every field a
caller can act on is a value the operator has just typed"* — but `problems` is
built from **all** of `fields`, unfiltered, so it carries the sentence for
`private_key`, for `""` (a model-level validator), and for anything else the
transport complains about, none of which any caller typed. The reviewer
reproduced both: with a model-level validator quoting `self.private_key`, the old
page's `/panel/transports/{id}/params` returned 200 with the key inside
`outcome.html`, and `POST /api/transports/{id}/params` returned 400 with the key
in the error envelope. The split is defensible in what it *keeps* (per-box
sentences, which M9.2's "each refusal arrives under its own box" needs) and not in
what it *says*. Also violates the control rulebook's *"secrets … never stored in a
variable that ends up in a log record, a template context, or an exception
message"* the moment a validator behaves this way. **Same single fix as the High.**

### Medium, open — a hop-end rotation is reported as if users were affected

`control/app/services/console.py:662` and `:678`. A **successful** rotation or
replacement on a hop end reports *"users keep the same link and pick this up the
next time their client refreshes it"*. Neither function branches on
`row.for_friends`, although every other string on this screen does —
`rotate_keys_dialog.html` deliberately says *"No user holds anything on it: this
is a tunnel between two of our own nodes"*. So the operator confirms a hop-end
rotation having read that no user is involved, and is then told about users'
links. `_unpushed` has the same shape. Fix: branch both summaries on
`row.for_friends`, the way the dialog does; the dialog's two sentences are the
model.

### Low, open — `KEY_MATERIAL_WITHHELD` is phrased about a form that is not there

`control/app/services/console.py:158`. The sentence hardcodes *"the transport also
refused something **this form** has no box for"*, and is used twice where that is
untrue: on the rotation path it is the **banner** text and there is no form on
screen at all (and *"also"* implies something else was reported when nothing was);
and for the falsy-message shape it names a field that **does** have a box. Fix:
two constants, or one sentence phrased about what was withheld rather than about a
form.

### Low, open — nothing sweeps the replace POST answer

`tests/control/test_the_console.py:1963` and `:2009`. The material sweep covers
every GET surface and the **rotate** POST answer; nothing sweeps the **replace**
POST answer, which is precisely the gap the High came through.
`test_a_refusal_prints_the_transport_s_words_only_under_a_box` plants markers, so
it proves the sorting, not the absence of real material. Fix: post to
`/panel/keys/{id}/params` with a validator quoting `info.data` and check the
answer against `stored_material(session)`, with `pytest.fail` rather than
`assert`.

### Cross-zone, recorded here so it is not lost — NOT M9's to fix

`tests/e2e/infra/test_restore_proves_the_backup.py:394-397` —
`assert stored.startswith("gAAAA"), f"…{stored[:40]!r}"` fires exactly when the
`secrets` column is **not** ciphertext, i.e. it prints 40 characters of plaintext
key material into the CI log, and pytest's rewriting adds the operand on top. The
same instrument M9.4 replaced in `tests/control/`. Synthetic stand data, so the
exposure is small. `infra` zone — CLAUDE.md keeps cross-zone work in separate
diffs, so it needs a task of its own. Fix: `pytest.fail("a node-transport's
secrets column is not ciphertext")` with no operand.
