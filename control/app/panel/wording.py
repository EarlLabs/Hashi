"""The boundary where the code's word becomes the panel's word.

WHAT: rewrites a sentence composed under this codebase's vocabulary — ``friend`` —
      into the word an operator reads on the console: ``user``; puts a refusal's
      directions into the console's own words, where a service wrote them for any
      caller; and composes the one sentence per recorded change that the audit screen
      puts in front of the operator.
WHY:  ``docs/decisions.md`` decision 9 draws one line and it has two sides. Nothing
      may rename ``friend`` in a route, a schema field, a service name or a test —
      and, equally, nothing the code calls a friend may arrive on the rendered page
      under that name. The panel had held the first half and leaked the second: a
      duplicate nickname was refused with *"a friend called 'dima' already exists"*
      on a screen where every other word says user. A sentence composed in
      ``services/`` is written in the code's vocabulary by design, so the
      translation belongs at the moment that sentence becomes page copy.
HOW:  every server-composed sentence a CONSOLE template renders passes through
      ``for_the_page`` — the mutation result's toast and banner, the add-user dialog's
      field error, and, since M17.1b, a tuning box's HINT (``panel/routes.py``'s
      ``_in_the_pages_words``, wired into the establish-hop, enable-transport and
      replace-parameters dialogs). Applying it in one helper each is what makes the rule
      checkable by reading ``panel/routes.py`` rather than every service.

      The hint was the one that had been missed, and it went unnoticed while no shipped
      transport's ``description`` used the word: a box's hint is written in a transport's
      own package and rendered straight onto a dialog, which makes it as much page copy
      as any sentence a service composes. M17 widened ``peer_tunnel_address``'s
      description and three dialogs started saying "friends" at once. So the claim this
      header used to make — that there is nowhere it is NOT applied — is not made any
      more: it was true of the surfaces M9.6 left, and a new surface is how it stops
      being true. What replaces it is the list above and the audit of it in
      ``tests/control/test_the_console.py``.

The two translations are the same boundary seen from two sides. ``friend`` is a word of
ours a page must not show; "the Nodes screen" is a word of the PAGE's that a service must
not compose, because the same sentence is answered to ``POST /api/nodes/{id}/apply``,
where there is no screen and the caller is not looking at one. Both are fixed at the
moment a sentence becomes page copy, and nowhere else.

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
from control.app.services import apply, console

# ``friend``/``friends``/``friend's``/``friends'`` — the shapes a sentence in this
# codebase actually uses. Word-bounded on purpose: a nickname like ``friendly`` is
# not the code's word and must come through untouched.
_THE_CODES_WORD = re.compile(r"\b(friend)(s'|'s|s)?\b", re.IGNORECASE)

# A quoted value, in the shape ``{value!r}`` produces. The lookaround is what keeps an
# ordinary possessive out of it: in "every active friend's subscription" the
# apostrophe follows a letter, so it opens nothing, and the sentence still translates.
_QUOTED_DATA = r'''(?<![A-Za-z])'[^']*'(?![A-Za-z])|"[^"]*"'''

# Where an operator is sent, in the console's own words — M18's acceptance, round 2.
#
# The second thing this boundary translates, and it crosses it for the same reason
# ``friend`` does. ``POST /api/nodes/{id}/apply`` was answering a script with "Enable a
# transport on it from the Nodes screen, then apply it" and "Nothing else in this panel
# stops a node serving what it was last given": correct prose for a banner, and directions
# to a place the caller of an API is not in. A service composing panel copy is the exact
# direction this module exists to stop, so the service states what is true of this control
# plane however it is driven and the console says it the console's way.
#
# KEYED BY THE CONSTANT, never by a copy of its text: ``services/apply.py`` owns the
# sentence, and a mapping keyed on a literal here would stop matching — silently, with the
# API's wording appearing on the console — the first time that sentence is edited.
#
# The values are the console's existing words, unchanged from what M18's acceptance walked
# and approved. What moves between the two versions is only where the operator is sent;
# every other clause of a refusal is the same fact for both readers and is written once.
_THE_CONSOLES_DIRECTIONS: dict[str, str] = {
    apply.ENABLE_ONE_HERE: (
        f"Enable a transport on it from {apply.WHERE_TO_RETRY}, then apply it."
    ),
    apply.OFFER_ONE_AGAIN: (
        f"Offer one of its transports again from {apply.WHERE_TO_RETRY} — which puts "
        "that transport back in every user's link — and apply."
    ),
    apply.NOTHING_STOPS_A_SERVING_HOST: (
        "Nothing else in this panel stops a node serving what it was last given."
    ),
    # M23. The console can name the control the operator presses; an API caller has no
    # row and no button, so the service's own clause says only what has to happen.
    apply.GIVE_IT_A_KEY: (
        f'Give it one with "ssh key" on its row on {apply.WHERE_TO_RETRY}, then apply it.'
    ),
}


def for_the_page(sentence: str, *, keeping: str | None = None) -> str:
    """One sentence in the words the panel uses, leaving operator text alone.

    ``keeping`` is an unquoted value the panel itself interpolated — a nickname in a
    toast. Quoted values need no naming: they are recognised by their quotes.

    The directions are replaced before anything else runs, on the whole sentence: they are
    this codebase's own clauses, containing nothing an operator typed, so there is nothing
    in them for the quote protection below to be protecting.
    """
    for written_for_any_caller, on_the_console in _THE_CONSOLES_DIRECTIONS.items():
        sentence = sentence.replace(written_for_any_caller, on_the_console)
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
    AuditAction.NODE_RESOLVER_SET: "resolver set for {first}",
    AuditAction.NODE_SSH_KEY_SET: "ssh key set for {first}",
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
