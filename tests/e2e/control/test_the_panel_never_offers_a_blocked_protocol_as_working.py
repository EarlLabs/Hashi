"""A protocol the censor identifies, presented honestly — backlog item 28.

WHAT: what the panel and the operator API say about a transport that declares itself
      identified on the wire, and what the hop form refuses to offer.
WHY:  the charter ships plain WireGuard first-class AND says it is protocol-blocked from
      Russia. Both halves are true and the second one is only useful if it reaches the
      owner at the moment they are choosing. A panel that lists it beside the obfuscated
      transports with no distinction is a panel that will hand a friend in Russia a
      protocol that cannot come up — and the friend reports it as "hashi is broken",
      which is the most expensive bug report this project can generate.
HOW:  read the Transports screen, the establish-hop dialog and /api/transports as the
      operator, against the booted stack.
      The declaration itself lives in `edge` and is asserted there; this is about whether
      the screen tells the truth.

Boundary: real control + postgres. Nothing here proves anything about a real network —
that plain WireGuard is blocked from a Russian mobile network is a charter statement and
a field observation, never a test result.
"""

import pytest

OPERATOR = {"username": "owner", "password": "e2e-operator-password"}


@pytest.fixture
async def operator(client):
    response = await client.post("/panel/login", data=OPERATOR)
    assert response.status_code == 303, response.text
    return client


async def listed(operator) -> dict[str, dict]:
    response = await operator.get("/api/transports")
    assert response.status_code == 200, response.text
    return {entry["name"]: entry for entry in response.json()}


async def test_the_api_reports_which_transports_a_filtering_network_identifies(
    operator,
) -> None:
    """The declaration reaches the operator's own tooling, not only the HTML."""
    entries = await listed(operator)
    assert entries, "no transports discovered"
    for entry in entries.values():
        assert isinstance(entry["blocked_by_inspection"], bool)
        assert isinstance(entry["hop_capable"], bool)
        # The one implication that must hold, restated where an operator could see it
        # break: a protocol the censor identifies must not be offered for the
        # border-crossing hop.
        if entry["blocked_by_inspection"]:
            assert not entry["hop_capable"], entry


async def test_the_transports_screen_marks_a_blocked_protocol_and_says_why(
    operator,
) -> None:
    """The screen the owner is looking at when they choose.

    Skips loudly rather than passing vacuously if this image ships no such transport:
    a green run here would otherwise mean "the warning is correct" when it means
    "there was nothing to warn about".
    """
    entries = await listed(operator)
    blocked = sorted(
        name for name, entry in entries.items() if entry["blocked_by_inspection"]
    )
    if not blocked:
        pytest.skip(
            "this image ships no transport that declares itself identified on the wire, "
            "so the panel has nothing to warn about and this scenario proves nothing"
        )

    # /panel/transports, not /panel/fleet. M9.3 moved the capability table off the
    # pre-redesign page and onto the console's own screen; the old page still exists
    # until M9.6 and still carries this warning, which is exactly why this assertion
    # had to move rather than stay green where it was. Relaxing it to "somewhere in
    # the panel" would be how a rewrite loses the cover this scenario provides.
    page = await operator.get("/panel/transports")
    assert page.status_code == 200, page.text
    body = page.text

    for name in blocked:
        assert name in body, f"{name} is not listed on the transports screen at all"
    # The warning is present, and it is about not offering it as a working exit rather
    # than a decorative label.
    assert "identified and blocked" in body
    assert "do not offer this as a working exit" in body
    # And the reason is there in words, which is what M9's acceptance line asks for: a
    # label an operator cannot act on is the state this screen was redesigned out of.
    assert "why:" in body
    assert "no camouflage" in body


async def test_the_hop_dialog_does_not_offer_a_blocked_protocol(operator) -> None:
    """The other half, on the form where the mistake would actually be made.

    Split from the assertion above when M9.3 moved the table, because the two facts no
    longer live on one page: the capability table is a console screen and the hop form
    is the establish-hop dialog. Asserted on the form's own <option> values rather than
    on a page containing the word — a screen that merely mentions the protocol proves
    nothing about what the form will accept.
    """
    entries = await listed(operator)
    blocked = sorted(
        name for name, entry in entries.items() if entry["blocked_by_inspection"]
    )
    if not blocked:
        pytest.skip(
            "this image ships no transport that declares itself identified on the wire, "
            "so there is nothing the hop form could wrongly offer"
        )

    dialog = await operator.get("/panel/hops/new")
    assert dialog.status_code == 200, dialog.text

    hop_options = _options_of(dialog.text, "hop-transport_name")
    # Before the loop, because ``_options_of`` answers "no such select" with an empty
    # list — a legitimate answer on a page with no hop form, and a vacuous pass here.
    # Since the split this assertion no longer shares a page with anything proving the
    # form rendered at all, so a rename of the select's id would turn the scenario
    # green while proving nothing.
    assert hop_options, "the hop dialog rendered no transport select"
    for name in blocked:
        assert name not in hop_options, (
            f"the hop form offers {name}, which the renderer refuses — the operator "
            "would fill in a whole form to be told no"
        )


def _options_of(html: str, select_id: str) -> list[str]:
    """The values of one <select>'s options.

    Hand-parsed rather than with a DOM library: this asserts what a browser will show for
    one known element, and adding a dependency to `control`'s test path is an architect
    decision, not a convenience.
    """
    import re

    match = re.search(
        rf'<select[^>]*id="{re.escape(select_id)}"[^>]*>(.*?)</select>', html, re.S
    )
    if match is None:
        # No hop form at all is a legitimate state — no transport can carry a hop — and
        # it satisfies "does not offer the blocked one".
        return []
    return re.findall(r'<option value="([^"]*)"', match.group(1))
