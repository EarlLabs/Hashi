"""The boundary where the code's word becomes the panel's word.

WHAT: rewrites a sentence composed under this codebase's vocabulary — ``friend`` —
      into the word an operator reads on the console: ``user``; and composes the one
      sentence per recorded change that the audit screen puts in front of the operator.
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

import dataclasses
import datetime
import re
from collections.abc import Sequence

from control.app.models import AuditAction
from control.app.services import console

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


# --- what a recorded change says on the audit screen (M10.4) -----------------

# One sentence per action in ``AuditAction``, composed HERE because the database holds a
# machine key and nothing else: decision 8 (docs/decisions.md, 2026-09-11) stores an
# enum value and two labels read off inventory rows, so the readable sentence has to be
# rendered rather than written down — which is also what keeps a row from ever being a
# place somebody types prose into.
#
# The vocabulary is the console's existing one, deliberately: these are the words the
# toast used at the moment the change was made (services/console.py's summaries, and
# panel/routes.py's own toasts), so the trail reads like the panel the operator was
# looking at rather than like a second dialect of it.
#
# ``{first}`` and ``{second}`` are the two label columns. The order in the sentence is
# not always the order in the row — a transport's entry stores the NODE first and reads
# "<transport> enabled on <node>" — and a hop's labels are always entry first, which is
# what lets both hop sentences say which end is which without storing a side.
#
# Nothing in here is a country, an address, a port or a transport's name: every varying
# word arrives as a label, which is a value the operator or the registry already chose.
_EVENTS: dict[AuditAction, str] = {
    AuditAction.FRIEND_ADDED: "user {first} added",
    AuditAction.FRIEND_REVOKED: "user {first} revoked — link is dead",
    AuditAction.NODE_ADDED: "node {first} added",
    AuditAction.NODE_STATE_CHANGED: "{first} is now {second}",
    AuditAction.NODE_APPLIED: "config applied to {first}",
    AuditAction.TRANSPORT_ENABLED: "{second} enabled on {first}",
    AuditAction.TRANSPORT_OFFERED: "{second} offered again on {first}",
    AuditAction.TRANSPORT_WITHDRAWN: "{second} withdrawn on {first}",
    # Deliberately unlike the withdrawal above rather than a synonym of it: the two are
    # different changes with different blast radii, and the trail is read after the row
    # it describes is gone, so the sentence is the only thing left saying which happened.
    AuditAction.TRANSPORT_REMOVED: "{second} removed from {first}",
    AuditAction.HOP_ESTABLISHED: "hop established from {first} to {second}",
    AuditAction.HOP_DISSOLVED: "hop torn down from {first} to {second}",
    AuditAction.KEYS_ROTATED: "keys rotated for {second} on {first}",
    AuditAction.PARAMS_REPLACED: "parameters replaced for {second} on {first}",
}

# The one recorded change that legitimately arrives with a single label: tearing down a
# hop whose other end was already gone, which is the case the second label being
# nullable exists for (services/relay.py). It cannot say which end this was — a half hop
# has no far end to compare against and the row stores no side — so it says what is
# true instead.
_HALF_HOP_DISSOLVED = "hop torn down at {first} — the other end was already missing"


@dataclasses.dataclass(frozen=True, slots=True)
class TrailLine:
    """One row of the audit screen: when, and what happened, in words.

    No actor field. There is one operator and the trail stores none, so the screen's
    actor column is rendered from ``settings.operator_username``, which every console
    screen already carries — see ``console.TrailEntry``.
    """

    at: datetime.datetime
    event: str


def the_trail(entries: Sequence[console.TrailEntry]) -> list[TrailLine]:
    """Every recorded change as the sentence the operator reads.

    Here rather than in ``services/console.py``, which is where the console's other
    prose lives, for the reason this module exists at all: these sentences are the
    PANEL's vocabulary. ``user {first} added`` is decision 9's rendered word for a row
    the code calls a friend, and a service composing it would be a service speaking the
    page's dialect — the exact direction this module was written to stop.
    """
    return [
        TrailLine(
            at=entry.at,
            event=an_event(entry.action, entry.first_label, entry.second_label),
        )
        for entry in entries
    ]


def an_event(
    action: AuditAction, first_label: str | None, second_label: str | None
) -> str:
    """One recorded change in plain words, from its machine key and its labels.

    A NEW action with no sentence here falls back to its own machine key rather
    than raising: this screen is a record of what the operator changed, and answering a
    request for it with a 500 because somebody added an action last week is the wrong
    failure. ``test_every_recorded_change_is_said_in_plain_words`` requires a sentence
    for every declared action, so the fallback is unreachable in this image — it is
    there for the version of this file that is one merge behind the enum.
    """
    if action is AuditAction.HOP_DISSOLVED and second_label is None:
        sentence = _HALF_HOP_DISSOLVED
    else:
        sentence = _EVENTS.get(action)
    if sentence is None:
        labels = " ".join(label for label in (first_label, second_label) if label)
        return f"{action.value} {labels}".strip()
    return sentence.format(first=first_label or "", second=second_label or "")
