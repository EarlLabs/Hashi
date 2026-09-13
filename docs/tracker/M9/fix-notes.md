# M9 — fix notes

What a post-step fix loop changed, and what it left. Read this the way you read
`carry-over.md`: background, not instruction.

## The banner scan, hardened after M9.1 closed (2026-09-10)

M9.1 converged on three clean rounds, and two of its final Mediums were sent
through a **fresh fix step-loop** (cap 2, both rounds clean) rather than banked.
The reason was not tidiness: M9.2–M9.6 add four more screens, and the scan those
screens rely on was blind to the syntax this codebase actually writes.

**What it now is.** `test_no_refusal_anywhere_in_the_panel_is_drawn_as_an_ordinary_notice`
no longer regexes template *text*. Each template is lexed with **Jinja's own
lexer**, every non-`data` token is blanked character-for-character into spaces, a
per-character line map is kept, and a quote-aware tag pattern runs over the
flattened result. `_unparsed_elements()` then searches the gaps between matched
tags for anything still `<element`-shaped and **faults on it** — that is the part
that closes the class rather than the instances: an element the scan cannot parse
fails the file instead of passing through it.

`jinja2` is already the stack's templating engine, so no dependency was added.
Rendering was rejected as the instrument (an untaken `{% if %}` branch is exactly
what a class-level guard must inspect, and rendering needs per-template context);
`html.parser` was rejected because it chokes on the same Jinja the old regex did.

**How hard it was attacked.** Round 1 threw 28 shapes at it and found one that got
through; round 2 threw 26 more and **could not find a new silent pass**. Between
them they turned up eight blind shapes the original scan had, four of which the
first rewrite still had. The mutation evidence now lives in the repository as
`AWKWARD_BANNERS` (defective by the rule) and `SOUND_BANNERS` (awkward but
correct, and asserted to be *read* rather than merely not-flagged), with
per-entry provenance — which scan version each shape got past.

**The one hole that survives, and why it was left.** A failure class that arrives
through a **name rather than a literal** — `class="banner {{ css }}"`, or a
`{% set cls = 'banner-failure' %}` three lines up in the same template — is
invisible to the scan. Closing it would mean faulting on any unresolvable
variable in a banner's class, which also rejects the perfectly legitimate
`class="banner {{ extra }}"`. A scan that flags everything gets loosened, and
this file exists because a scan that gets believed beyond its proof is worse than
none. **The accurate, current record of what the scan cannot see is
`_banner_faults`'s own docstring** — read that, not this paragraph, before you
rely on a green run.

**Two rules this leaves for every later screen:**

- **One element, one banner.** A banner declaring `class` or `role` more than
  once is a fault in its own right — including once per Jinja branch. A browser
  keeps the first attribute and drops the second, so one element that renders as
  either banner cannot have the role it renders paired with the class it renders.
  Write two banners as two elements, the way `panel/banner.html` and
  `panel/friends_table.html` do.
- **Put the literal class name in the attribute.** `{{ 'banner-failure' if failed
  else '' }}` is seen. A variable holding the same string is not.

`_attribute` no longer exists; it is `_attributes(tag, name) -> list[str]`.
`_html_only(source) -> (markup, line_of)` is now the way to read a template in a
test — the sibling scan `test_no_console_template_names_a_transport_a_country_an_address_or_a_port`
still reads raw text and could reuse it.

## Left open by the fix loop, cap spent

All non-blocking; both rounds returned `VERDICT: 0 critical, 0 high`.

- **Medium** — `tests/control/test_the_console.py:1258-1261`: the group-1
  provenance comment describes a scan version that never existed, conflating two
  ("demanded `class` come first and be double-quoted, **then** read the file with
  `<div\b[^>]*>`" — those are `600845c` and `5438a93` respectively). **The
  per-entry claims themselves were replayed and are true**; it is the sentence
  explaining *why* they are true that is wrong. Same class of defect the table
  exists to prevent, which is why it is recorded rather than shrugged off.
- **Low** — `:1278-1280`: the "One the old scan already CAUGHT" comment sits above
  **four** entries; only the first belongs to it. Since grouping is how provenance
  is attached, a top-down reader mis-attributes 3 of 11 entries.
- **Low** — `:1598`: `_attributes` matches `class=`/`role=` anywhere in the tag
  text, including inside another attribute's value, so
  `data-x="role=alert"` trips the "declares role twice" fault. Fails **closed**
  (red, not silent), so it is noise rather than a hole.
- **Low** — `:1554-1573`: a legitimate Jinja idiom — branch only the opening tag
  and share one close — is reported as "a banner whose element never closes",
  because `_element_body` counts the second opening as a nesting level. Fails
  closed, and the fully-branched two-element shape the fault message recommends
  does pass; but this is exactly the over-flagging `SOUND_BANNERS` exists to guard
  against, and it is not in that table.

## The acceptance fixes, 2026-09-10 → 09-11

M9's acceptance walk came back **BLOCKED** with four defects. Two fix loops closed
them. Both root causes were more interesting than the symptoms, and both are the
kind of thing that would have been patched at the wrong layer by anyone in a
hurry.

### Loop A — rotation, probe, and a banner nobody ever saw

**A failed hop-end rotation said "Nothing was changed" and the key had changed.**
`rotate_keys` now treats a hop as one unit: mint once, copy every value the
transport **declares** `shared_between_peers` into the far end, render the pair
through `relay.check_renders_as_a_pair` **before anything is written**, write both
rows and commit **once**, then push both nodes. Attacked by review and not broken:
a failed commit writes nothing; a peer row deleted between read and write gives a
zero-row UPDATE → `StaleDataError` → full rollback; `apply_many` re-raises only
after a consistent commit. **There is no window in which one end holds new
material and the other does not.** That is why it is one transaction rather than a
reordering of commit and push — the half-written state *is* the bug, and no
sentence makes it safe.

**Probe reported nothing — and neither had anything else.** The cause was one
line: `app.js` cleared the banner slot on `htmx:afterRequest`, which fires
**after** the swap. Verified against the vendored htmx 2.0.4 source: `xhr.onload`
runs the response handling (performing the OOB swap synchronously at `swapDelay`
0) and only then fires `afterRequest`. So **every banner this panel ever sent on a
2xx was written and wiped in the same exchange** — probe, failed apply, incomplete
revocation, half-done rotation. The answer now owns the slot from the server;
`app.js` clears it only on sidebar navigation.

**A malformed SSH key was an internal error.** Refused before dialling now, at
registration and at `target_for`, in words under the key box.

### Loop B — two dialogs, two third-party behaviours

**The enable dialog stacked all four transports' boxes at once.** It already had
the hop dialog's mechanism verbatim — the markup was never the problem.
**`[hidden]` is a user-agent rule, and any author rule setting `display` beats it
regardless of specificity.** The groups wear `.dialog-form { display: flex }`, so
the attribute did nothing, and `app.js` was setting the same attribute the
stylesheet was overruling. The hop dialog escaped only by accident, because
`.disclosure` sets no `display`. Fix: `[hidden] { display: none !important; }` —
and the `!important` is load-bearing, not defensive: both rules are specificity
(0,1,0) and the class rule is 390 lines later, so source order alone would win.

**Opening a dialog rewrote the address bar.** `hx-push-url` is one of htmx's
**inherited** attributes, resolved by walking up from the requesting element, and
`#main` carried `hx-push-url="/panel/friends"` for one navigation — so every
control inside it pushed that URL. Fix: `hx-disinherit="hx-push-url"` on `#main`;
htmx exempts an element from its **own** disinherit (`if(e!==t)` in 2.0.4), so
that one navigation still pushes.

**Not pre-selecting the chooser was deliberate:** it would turn "submit without
choosing" from a refusal on the control into a real choice, and the refusal the
operator then gets would be about boxes rather than about the choice they never
made.

### Conventions this leaves

- **`[hidden] { display: none !important; }` is load-bearing.** Before giving a
  hideable group a class, check that rule.
  `test_a_group_the_server_hides_is_actually_hidden` asserts it *and* scans for
  classes that would overrule it, failing if the scan finds none — so it cannot
  rot into decoration.
- **`#main` disinherits `hx-push-url`.** A new screen control that needs to push
  one must declare it on itself. `_HtmxControls` models htmx's ancestor walk
  including `hx-disinherit` — reuse it for any other inherited-attribute question.
- **One string, two surfaces.** `console.HOP_PUSH_OUTCOME` /
  `HOP_ONE_END_TOOK_IT` / `HOP_NEITHER_END_TOOK_IT` is the pattern for any claim a
  dialog makes that an answer must repeat: compose it once in `console`, render it
  in the dialog, compose the answer from the same clauses. A phrase list is not
  enough — the first attempt was one, and a differently-worded contradiction
  walked straight through it.
- **`relay.check_renders_as_a_pair`** — call it between validating and committing
  on any path that rewrites one hop end.
- **`conftest.GENERATED_SSH_KEY`** is a real ed25519 key generated per run. Any
  fixture registering a node must use it; `"not-a-real-key"` is now refused.

### Left open by the acceptance fixes — all Low, both caps spent

- `tests/control/test_the_console.py:1165` — `_transport_groups` gives the **last**
  group a text region running to the end of the document, so it swallows the
  key-material paragraph and the dialog actions, and the refusal branch asserts on
  exactly that over-wide group. No false pass today; the instrument measures more
  than it claims.
- `tests/control/test_the_console.py:4253-4255` — the new push-url test holds only
  the negative half: controls targeting `#main` are skipped without asserting they
  still resolve a push. **The whole fix rests on htmx's self-exemption keeping
  `#main`'s own `hx-push-url` alive, and nothing pins it** — deleting the
  attribute, or disinheriting with `*`, stays green.
- `templates/panel/node_transports_dialog.html:181-183` — the comment says an
  accidental enable "mints key material"; for every shipped transport the
  empty-required-box refusal stops that first, so the claim only bites for a
  transport whose operator params are all defaulted. The decision is right, the
  reason is stated more strongly than it holds.
- `templates/panel/node_transports_dialog.html:185-190` — the group heading is a
  bare `<p>` beside the group rather than tied to it, so a screen-reader user
  landing in `port` hears `port` with no group context: the same orphaned-box
  problem the finding was about, in the one mode where visual proximity does not
  help. `<fieldset><legend>`, or an id plus `aria-labelledby`.
