"""A protocol the censor identifies, presented honestly — backlog item 28.

WHAT: what the panel and the operator API say about a transport that declares itself
      identified on the wire, what the hop form refuses to offer, and — since M20 —
      what neither of them proposes once a transport declares itself retired.
WHY:  the charter ships plain WireGuard first-class AND says it is protocol-blocked from
      Russia. Both halves are true and the second one is only useful if it reaches the
      owner at the moment they are choosing. A panel that lists it beside the obfuscated
      transports with no distinction is a panel that will hand a user in Russia a
      protocol that cannot come up — and the user reports it as "hashi is broken",
      which is the most expensive bug report this project can generate.
HOW:  read the Transports screen, the establish-hop dialog, the enable dialog and
      /api/transports as the operator, against the booted stack.
      The declaration itself lives in `edge` and is asserted there; this is about whether
      the screen tells the truth.

Boundary: real control + postgres. Nothing here proves anything about a real network —
that plain WireGuard is blocked from a Russian mobile network is a charter statement and
a field observation, never a test result.
"""

import uuid

import pytest

OPERATOR = {"username": "owner", "password": "e2e-operator-password"}


@pytest.fixture
def unique() -> str:
    """A suffix per test. The stand is one warm fleet and a node name is unique in it."""
    return uuid.uuid4().hex[:8]


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
    # pre-redesign page and onto the console's own screen while both were still live,
    # which is exactly why this assertion had to move rather than stay green where it
    # was; M9.6 then deleted that page. Relaxing it to "somewhere in the panel" would be
    # how a rewrite loses the cover this scenario provides.
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


# --- and one it declares it has stopped being (M20) ----------------------------


async def _a_node(operator, name: str) -> str:
    """One draft node, so the enable dialog has something to be about.

    Its own helper rather than a shared one: pytest runs this suite with
    ``--import-mode=importlib``, under which importing across scenario modules is not
    reliable, and the stand is one fleet — so the name carries the scenario's own prefix
    and the address is out of the documentation range like every other file here.
    """
    created = await operator.post(
        "/api/nodes",
        json={"name": name, "address": "192.0.2.99", "location_label": "Retiredland"},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def test_the_api_reports_which_transports_are_retired_and_why(operator) -> None:
    """The declaration, read out of the IMAGE rather than out of the source tree.

    The registry discovers packages at runtime, so what this repository declares and what
    the shipped image ships are two questions — the reason
    ``tests/e2e/edge/test_shipped_image_discovers_transports.py`` exists at all. A
    retirement that held on a laptop and not in the container would be a protocol the
    panel goes on offering to the only operator who matters.
    """
    entries = await listed(operator)
    assert entries, "no transports discovered"
    for entry in entries.values():
        assert isinstance(entry["retired"], bool), entry
        # The reason travels with the flag or neither is worth having: a chooser that
        # drops an option has to be able to say why it is gone.
        assert bool(entry["retired_because"]) is entry["retired"], entry


async def test_the_enable_dialog_does_not_offer_a_retired_protocol(
    operator, unique: str
) -> None:
    """The owner's own words, on the booted stack: *"the admin panel do not even should
    show this protocol, for me in suggestions"*.

    Asserted on the form's own ``<option>`` values, for the same reason the hop half
    above is: a screen that merely stops mentioning a protocol in one of the three places
    it names it proves nothing about what the chooser will offer.

    Skips loudly on an image that retires nothing, rather than passing over an empty set.
    """
    entries = await listed(operator)
    retired = sorted(name for name, entry in entries.items() if entry["retired"])
    if not retired:
        pytest.skip(
            "this image retires no transport, so the enable dialog has nothing it could "
            "wrongly offer"
        )

    node_id = await _a_node(operator, f"retired-{unique}")
    dialog = await operator.get(f"/panel/nodes/{node_id}/transports")
    assert dialog.status_code == 200, dialog.text

    offered = _options_of(dialog.text, "enable-transport_name")
    assert offered, "the enable dialog rendered no transport select"
    for name in retired:
        assert name not in offered, (
            f"the enable dialog still offers {name}, which the registry declares retired"
        )
    # The row is still ON the capability table, which is the other half: the operator
    # has a node running it and has to be able to find out what happened.
    screen = await operator.get("/panel/transports")
    for name in retired:
        assert name in screen.text, f"{name} vanished from the capability table"


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
