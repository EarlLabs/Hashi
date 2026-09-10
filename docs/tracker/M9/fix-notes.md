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
