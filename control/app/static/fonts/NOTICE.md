# Vendored fonts — provenance and licence

<!--
WHAT: where these ten woff2 files came from and under what terms they are here.
WHY:  a binary in a repository with no story attached is the thing nobody dares
      touch and nobody dares update. This is also the record of the one
      third-party download decision 7 authorised, so a later run can see that it
      happened once and does not need to happen again.
HOW:  read this before replacing or adding a face. `/static/fonts.css` is what
      declares them; nothing else references the filenames.
-->

## What they are

**Barlow** and **Barlow Condensed**, by Jeremy Tribby — the two families
`design/design-system/styles.css` names in `--font-body` and `--font-heading`.

| family | weights | subsets |
|---|---|---|
| Barlow | 400, 500, 700 | latin, latin-ext |
| Barlow Condensed | 400, 600 | latin, latin-ext |

Exactly the weights the deleted `@import` asked for:
`family=Barlow:wght@400;500;700&family=Barlow+Condensed:wght@400;600`.

The **vietnamese** subset Google also publishes is deliberately not vendored —
it is weight this panel will never spend. There is **no Cyrillic subset at all**
for these families upstream, which is why `--font-body` and `--font-heading`
carry real fallbacks (`system-ui, sans-serif`) rather than a bare `sans-serif`:
a Cyrillic nickname renders in the fallback and must still look like a font
somebody chose.

## Where they came from

Fetched once, on 2026-09-09, from the Google Fonts CSS API and the `fonts.gstatic.com`
URLs it returned for `css2?family=Barlow:wght@400;500;700&family=Barlow+Condensed:wght@400;600&display=swap`
(Barlow v13). `unicode-range` values in `/static/fonts.css` are upstream's, unedited.

**This was the single third-party fetch `docs/decisions.md` decision 7 authorised.**
Nothing in the panel fetches anything from anywhere but this host at runtime, and
`tests/e2e/control/test_the_panel_fetches_nothing_from_a_third_party.py` is what
keeps that true.

## Licence

SIL Open Font License, Version 1.1 — the licence every family on Google Fonts
carries, and the one Barlow ships under in its own repository.

The full OFL text is **not** vendored beside these files. Adding it would be a
second download, and decision 7 authorised exactly one. It belongs here and
should be added the next time this repository is on a machine with a network:
fetch `OFL.txt` from the Barlow source repository and drop it in this directory.
