"""The boundary where the code's word becomes the panel's word.

WHAT: rewrites a sentence composed under this codebase's vocabulary — ``friend`` —
      into the word an operator reads on the console: ``user``.
WHY:  ``docs/decisions.md`` decision 9 draws one line and it has two sides. Nothing
      may rename ``friend`` in a route, a schema field, a service name or a test —
      and, equally, nothing the code calls a friend may arrive on the rendered page
      under that name. The panel had held the first half and leaked the second: a
      duplicate nickname was refused with *"a friend called 'dima' already exists"*
      on a screen where every other word says user. A sentence composed in
      ``services/`` is written in the code's vocabulary by design, so the
      translation belongs at the moment that sentence becomes page copy.
HOW:  every server-composed sentence a CONSOLE template renders passes through
      ``for_the_page`` — the mutation result's toast and banner, and the add-user
      dialog's field error. Applying it in one helper each is what makes the rule
      checkable by reading ``panel/routes.py`` rather than every service.

      There is no longer anywhere it is NOT applied: it was held back from
      ``panel/outcome.html``, the pre-redesign fleet page's fragment, whose own prose
      said "friend" throughout — translating only its messages would have left one page
      speaking two vocabularies. M9.6 deleted that page and its fragment, so every
      server-composed sentence the panel renders now comes through here.

Two things are never translated, because they are not ours to rewrite:

* anything in QUOTES. Services quote operator data with ``{value!r}``, so a person
  nicknamed ``friend`` is refused with *"a user called 'friend' already exists"* —
  our word changed, theirs untouched.
* the value named by ``keeping``, for the sentences the PANEL composes itself with a
  bare interpolation — a toast reading ``{nickname} added``. There is no word of ours
  in those to confuse it with, which is why ``keeping`` is not used on a sentence a
  service wrote: there the quotes already say which part is data.
"""

import re

# ``friend``/``friends``/``friend's``/``friends'`` — the shapes a sentence in this
# codebase actually uses. Word-bounded on purpose: a nickname like ``friendly`` is
# not the code's word and must come through untouched.
_THE_CODES_WORD = re.compile(r"\b(friend)(s'|'s|s)?\b", re.IGNORECASE)

# A quoted value, in the shape ``{value!r}`` produces. The lookaround is what keeps an
# ordinary possessive out of it: in "every active friend's subscription" the
# apostrophe follows a letter, so it opens nothing, and the sentence still translates.
_QUOTED_DATA = r'''(?<![A-Za-z])'[^']*'(?![A-Za-z])|"[^"]*"'''


def for_the_page(sentence: str, *, keeping: str | None = None) -> str:
    """One sentence in the words the panel uses, leaving operator text alone.

    ``keeping`` is an unquoted value the panel itself interpolated — a nickname in a
    toast. Quoted values need no naming: they are recognised by their quotes.
    """
    protected = re.compile(
        f"{_QUOTED_DATA}|{re.escape(keeping)}" if keeping else _QUOTED_DATA
    )
    out: list[str] = []
    read = 0
    for match in protected.finditer(sentence):
        out.append(_translated(sentence[read:match.start()]))
        out.append(match.group(0))
        read = match.end()
    out.append(_translated(sentence[read:]))
    return "".join(out)


def _translated(text: str) -> str:
    return _THE_CODES_WORD.sub(_as_the_panel_says, text)


def _as_the_panel_says(match: re.Match[str]) -> str:
    word = "user" + (match.group(2) or "")
    return word.capitalize() if match.group(1)[0].isupper() else word
