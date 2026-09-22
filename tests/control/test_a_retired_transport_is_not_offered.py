"""What the panel stops doing with a retired transport, and what it must not stop — M20.

WHAT: every surface that proposes a transport, asked whether it proposes a retired one:
      the enable dialog, the establish-hop dialog, the submission handler behind each of
      those two, the operator API's listing and the Transports screen. Then the refusal
      itself, which is not a panel's but the operation's — no route creates such a row.
      And the other half, which is most of this file: a node already running one still
      renders, its users' configurations are unchanged, and it can still be removed.
WHY:  the owner asked for it in these words — *"just stop suggest the wireguard for
      users now… the admin panel do not even should show this protocol, for me in
      suggestions"* — after the transport was measured twice on a live node completing a
      handshake and carrying nothing. Their own leaf has a row of it today, so a change
      that stopped it being offered by breaking it would have cost them the node they
      were complaining about.

      M20'S ACCEPTANCE CLOSED THE OTHER HALF, and this file used to pin it open: the
      operator API went on answering ``POST /api/nodes/{id}/transports`` with 201 and
      ``enabled: true`` for a retired transport, and the complete credential it minted
      reached the next friend's archive. The reading that allowed it — that the owner's
      words were about SUGGESTIONS — understated them ("may be it's better to drop it?"),
      and the consequence is not a status code but a friend holding a tunnel that
      completes its handshake and carries nothing, with nothing on their device saying
      so. Refusing to CREATE is still not refusing to SERVE, which is the whole of the
      other half below.
HOW:  the in-process client from conftest, holding an operator session. Which transport
      is retired is read from the registry, never written here, and the tests that prove
      the panel needs no edit for the NEXT one fabricate a fleet in which an offered
      transport is retired — the only way to assert "no panel change" rather than to
      claim it. Two of those are the hop surfaces, which no shipped transport can reach:
      nothing here is both hop-capable and retired.

      THE SAME TOOL POINTED THE OTHER WAY is how a row of a retired transport comes to
      exist at all now that no route will make one — ``a_row_from_before_the_retirement``
      below, which lifts the declaration for the length of one API call and puts it back.
      That is not a workaround for the refusal: it is the history it was written for. The
      owner's leaf holds such a row because it was enabled before the transport was
      retired, and every assertion after that call runs in the real fleet, where it is.

Nothing here asserts that plain WireGuard is broken on a real network. That was measured
in the field and is recorded in the plan; a test run cannot reach a node.
"""

import html
import re
from dataclasses import replace

import pytest
from sqlalchemy import select

from control.app.models import NodeState, NodeTransport, User
from control.app.services import apply as apply_service
from control.app.services import nodes as nodes_service
from control.app.services import subscriptions as subscriptions_service
from control.app.services import transports as transports_service
from edge.registry import Retirement, discover, profile

RETIRED = transports_service.retired_transports()
HTMX = {"HX-Request": "true"}

# The group the enable dialog draws per transport it proposes, and the one it draws for
# a transport it does not. Read as markup rather than as text: the name also appears in
# the chooser, in a label and in the reading below each group, so a bare substring search
# would pass on a dialog that had merely stopped mentioning it in one of the three.
GROUP = re.compile(r'data-transport-group="([^"]+)"')


def reading(response) -> str:
    """What a person reads on the page: tags stripped, entities decoded, space collapsed.

    The entities matter here rather than being tidiness. Every sentence this file asserts
    is prose written by a transport or by this zone, and both contain apostrophes and
    dashes that Jinja escapes — so a comparison against the constant itself fails on a
    page that is perfectly correct, and the temptation is then to weaken the assertion to
    a substring that no longer pins the sentence.
    """
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", response.text)))


def a_pool_size(transport_name: str) -> int | None:
    """50 for a transport that hands each user an address, ``None`` for the rest."""
    from control.app.services import addresses

    return 50 if addresses.spec_for(transport_name) is not None else None


def operator_params(transport_name: str, **overrides: object) -> dict[str, object]:
    """Plausible values for every field this transport asks an operator for.

    Filtered against the transport's own model, so one literal serves the whole image and
    a transport that declares a field nobody here anticipated fails loudly on the enable
    rather than quietly on the assertion — and an override for a field this transport does
    not declare is dropped by the same filter rather than refused by its model.
    """
    supplied: dict[str, object] = {
        "port": 51820,
        "mtu": 1280,
        "tunnel_address": "10.91.0.1/24",
        "peer_tunnel_address": "10.91.0.2/24",
        "junk_packet_count": 4,
        "junk_packet_min_size": 40,
        "junk_packet_max_size": 80,
        "init_packet_magic_header": 1020327352,
        "response_packet_magic_header": 2060487442,
        "underload_packet_magic_header": 3679305607,
        "transport_packet_magic_header": 1436947798,
        "decoy_host": "www.example.com",
        "decoy_port": 443,
        "server_names": ["www.example.com"],
        "certificate_path": "/etc/ssl/example.crt",
        "certificate_key_path": "/etc/ssl/example.key",
        "server_name": "www.example.com",
    }
    declared = set(profile(transport_name).params_model.model_fields)
    return {key: value for key, value in (supplied | overrides).items() if key in declared}


async def a_node(client, *, name: str, address: str) -> str:
    created = await client.post(
        "/api/nodes",
        json={"name": name, "address": address, "location_label": "Testland"},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def a_row_from_before_the_retirement(client, node_id: str, name: str) -> str:
    """The row the owner's own leaf holds: enabled while the transport was still offered.

    No route makes one any more, which is the refusal below, so the only honest way to
    get the state this file's second half is about is to reproduce how it arose. The
    declaration is lifted for the length of ONE API call and restored before anything is
    asserted — ``MonkeyPatch.context`` rather than the ``nothing_retired`` fixture,
    because a fixture lasts the whole test and every assertion after this line has to run
    in the real fleet, where the transport IS retired and the panel does not offer it.

    The fabricated meta is the real one with a single field replaced, so the row that
    comes back was minted, validated and placed by the transport's own code exactly as
    the leaf's was.
    """
    fleet = dict(discover())
    fleet[name] = replace(fleet[name], retired=None)
    with pytest.MonkeyPatch.context() as before_the_retirement:
        before_the_retirement.setattr(transports_service, "discover", lambda: fleet)
        enabled = await client.post(
            f"/api/nodes/{node_id}/transports",
            json={
                "transport_name": name,
                "params": operator_params(name),
                **({"pool_size": a_pool_size(name)} if a_pool_size(name) else {}),
            },
        )
    assert enabled.status_code == 201, enabled.text
    return enabled.json()["id"]


# AT MODULE LEVEL, where an empty image is the only thing that can make this whole file
# meaningless. Everything below is about what happens to a retired transport, so an image
# with none is a file of vacuous passes — and a guard inside each test would be five
# sentences saying the same thing in a suite that had already gone green.
pytestmark = pytest.mark.skipif(
    not RETIRED, reason="this image retires no transport, so there is nothing to not offer"
)


# --- the surfaces that propose one --------------------------------------------

async def test_the_enable_dialog_does_not_propose_a_retired_transport(client) -> None:
    """The owner's own sentence, on the screen they said it about.

    Asserted over the GROUPS rather than over the page's text: the dialog names each
    transport three times in its own group — the chooser option, the label above the
    boxes and the reading under them — so a page that had merely dropped one of the
    three would pass a substring search while still offering the protocol.
    """
    node_id = await a_node(client, name="offer-1", address="192.0.2.70")

    dialog = await client.get(f"/panel/nodes/{node_id}/transports")

    assert dialog.status_code == 200, dialog.text
    proposed = GROUP.findall(dialog.text)
    assert proposed, "the dialog proposes nothing at all, so it proves nothing here"
    assert set(proposed).isdisjoint(RETIRED), (
        f"the enable dialog still proposes {sorted(set(proposed) & set(RETIRED))}"
    )
    assert set(proposed) == set(transports_service.offerable_transports())


async def test_the_enable_dialog_says_why_a_protocol_the_image_ships_is_not_on_it(
    client,
) -> None:
    """The chooser's own hint, which was silent about the gap it had just opened.

    An operator who knows the image ships four protocols and counts three here has one
    question, and a shorter list answers none of it — the same "sends them looking for
    the missing one" this milestone's row on the Transports screen exists to prevent.
    So the hint says a missing one has been retired and where the reason is, in the
    field's own help text, which is where a person looks before they go hunting.

    Asserted on the word rather than on the sentence: the wording is a person's to
    improve, and this dialog has no other source for it — no row on it renders
    ``retired_note``, so a green assertion here can only come from the hint.
    """
    node_id = await a_node(client, name="offer-hint", address="192.0.2.78")

    dialog = await client.get(f"/panel/nodes/{node_id}/transports")

    assert dialog.status_code == 200, dialog.text
    assert "retired" in reading(dialog).lower(), (
        "this image retires a transport, the dialog silently drops it, and nothing on "
        "the form says a protocol the operator can see elsewhere has been withheld"
    )


async def test_the_enable_dialog_loses_a_transport_retired_later(
    client, monkeypatch
) -> None:
    """THE CLAIM THAT THIS IS A DECLARATION AND NOT A NAME — asserted, not stated.

    A transport currently offered is retired in a fabricated fleet, and its group has to
    leave the dialog with no edit to any route, any template or any service. Without
    this, "retirable by setting the same field" is a sentence in a commit message: the
    test above would pass just as well against a panel that compared one name.

    The fabricated meta is a REAL transport's, with one field replaced, so ``profile()``
    still loads its renderers and its parameter model — a fleet of invented packages
    would fail for a reason that has nothing to do with retirement.
    """
    node_id = await a_node(client, name="offer-2", address="192.0.2.71")
    victim = transports_service.offerable_transports()[0]
    fleet = dict(discover())
    fleet[victim] = replace(
        fleet[victim], retired=Retirement(reason="fabricated for this test")
    )
    monkeypatch.setattr(transports_service, "discover", lambda: fleet)

    dialog = await client.get(f"/panel/nodes/{node_id}/transports")

    assert dialog.status_code == 200, dialog.text
    assert victim not in GROUP.findall(dialog.text), (
        f"{victim} was retired in the registry and the enable dialog still proposes it"
    )


async def test_the_hop_dialog_loses_a_transport_retired_later(
    client, monkeypatch
) -> None:
    """The second chooser, held to the same rule — and the one no shipped transport
    exercises.

    This image ships nothing that is both hop-capable and retired, so the hop dialog's
    filter is a door held shut rather than one already closed: only a fabricated fleet
    can prove it is there at all. The alternative was to add the filter and let a future
    retirement discover it was missing, on the one dialog whose transport crosses a
    border.
    """
    victim = transports_service.hop_transports()[0]
    fleet = dict(discover())
    fleet[victim] = replace(
        fleet[victim], retired=Retirement(reason="fabricated for this test")
    )
    monkeypatch.setattr(transports_service, "discover", lambda: fleet)

    dialog = await client.get("/panel/hops/new")

    assert dialog.status_code == 200, dialog.text
    assert victim not in GROUP.findall(dialog.text), (
        f"{victim} was retired in the registry and the hop dialog still proposes it"
    )


async def test_the_panel_refuses_a_submission_naming_a_retired_transport(
    client, session
) -> None:
    """The submission handler behind the dialog, which has no boxes to answer with.

    The dialog draws no group for a retired transport, so a submission naming one cannot
    have come from it — and every other refusal this form makes is shown UNDER the box it
    is about, of which there would be none. So it is answered above the form, in one
    sentence carrying the transport's own reason, and nothing is written.
    """
    node_id = await a_node(client, name="offer-3", address="192.0.2.72")
    name, reason = next(iter(RETIRED.items()))
    typed = {"transport_name": name} | {
        f"{name}-{field}": str(value) for field, value in operator_params(name).items()
    }

    refused = await client.post(
        f"/panel/nodes/{node_id}/transports", data=typed, headers=HTMX
    )

    assert refused.status_code == 422, refused.text
    said = reading(refused)
    assert transports_service.NO_LONGER_OFFERED.format(name=name, reason=reason) in said, said
    session.expire_all()
    assert (
        await session.execute(
            select(NodeTransport).where(NodeTransport.node_id == node_id)
        )
    ).scalars().unique().all() == [], "the refusal wrote a row anyway"


async def test_the_hop_form_refuses_a_submission_naming_a_transport_retired_later(
    client, session, monkeypatch
) -> None:
    """The OTHER submission handler, given the same answer in the same words.

    The enable form's refusal above is reachable today; this one is not, because no
    transport this image ships is both hop-capable and retired — so, like the hop dialog
    two tests up, only a fabricated fleet can reach it at all. It is asserted rather than
    left for the next retirement to discover, and the failure it prevents is specific:
    ``hop_transports`` already subtracts a retired transport, so without a refusal here
    the submission falls through with an EMPTY set of tuning boxes, reaches the hop
    renderer with no parameters, and comes back as a per-field complaint about boxes the
    dialog never drew — a message addressed to a form nobody can see, on the one dialog
    whose transport crosses a border.

    Every required box is answered, so the only thing left for the panel to object to is
    the name. Both node ids are real for the same reason: a refusal that merely said
    "required" would pass an assertion about a sentence it never composed.
    """
    entry_id = await a_node(client, name="hop-retired-entry", address="192.0.2.75")
    leaf_id = await a_node(client, name="hop-retired-leaf", address="192.0.2.79")
    victim = transports_service.hop_transports()[0]
    reason = "fabricated for this test"
    fleet = dict(discover())
    fleet[victim] = replace(fleet[victim], retired=Retirement(reason=reason))
    monkeypatch.setattr(transports_service, "discover", lambda: fleet)

    answers = operator_params(victim)
    boxes = transports_service.hop_tuning(victim)
    assert {box.name for box in boxes if box.required} <= set(answers), (
        f"{victim} requires a hop parameter this file has no value for, so the "
        "submission below would be refused for being incomplete rather than for naming "
        "a retired transport"
    )
    typed = {
        "entry_node_id": entry_id,
        "leaf_node_id": leaf_id,
        "transport_name": victim,
    } | {
        f"{side}-{box.name}": str(answers[box.name])
        for side in ("entry", "leaf")
        for box in boxes
        if box.name in answers
    }

    refused = await client.post("/panel/hops", data=typed, headers=HTMX)

    assert refused.status_code == 422, refused.text
    said = reading(refused)
    assert transports_service.NO_LONGER_OFFERED.format(name=victim, reason=reason) in said, said
    session.expire_all()
    assert (
        await session.execute(select(NodeTransport))
    ).scalars().unique().all() == [], "the refusal established half a hop anyway"


async def test_the_operator_api_says_which_transports_are_retired_and_why(
    client,
) -> None:
    """The same declaration where a script reads it.

    This endpoint lists the whole image on purpose — an inventory that silently dropped a
    package would leave an operator reading a node's existing row against a list that does
    not contain it — so the flag is what a chooser built on it filters by, and the
    sentence is what such a chooser shows instead.
    """
    listed = {entry["name"]: entry for entry in (await client.get("/api/transports")).json()}

    assert listed, "no transports discovered"
    assert set(RETIRED) <= set(listed), (
        "a retired transport is missing from the image's own inventory, so nothing can "
        "explain the row a node already runs"
    )
    for name, entry in listed.items():
        assert entry["retired"] is (name in RETIRED), entry
        assert entry["retired_because"] == RETIRED.get(name), entry


async def test_the_transports_screen_says_a_retired_transport_is_no_longer_offered(
    client,
) -> None:
    """The screen the operator learns the protocols from, which still lists it.

    Listing it is the point. A table showing four protocols beside a dialog offering
    three sends the operator looking for the missing one; the row that is no longer
    offered is the one that has to say so, in the transport's own words.
    """
    screen = await client.get("/panel/transports")

    assert screen.status_code == 200, screen.text
    said = reading(screen)
    for name, reason in RETIRED.items():
        assert name in said, f"{name} vanished from the capability table"
        assert reason in said, f"the screen does not say why {name} is not offered"
    assert "no longer offered when enabling a transport" in said, said


async def test_the_overview_counts_what_can_be_enabled_and_not_only_what_ships(
    client,
) -> None:
    """The first screen an operator sees, which counted the retired one.

    "transports serving: 1 — 4 in this image" reads as three left to enable when only
    two are, which is the identical effect the retired row above exists to prevent — a
    count the operator acts on by going looking for the protocols it implies. Both
    figures are asserted rather than the shipped one dropped: the package IS in the
    image, and a card that stopped saying so would be answering an honest question with
    less information instead of more.

    THE CARD SAYS "in this image" AND NOT "of 4 this image ships" SINCE M20's ACCEPTANCE:
    the "of" read as a denominator of the value above it, so a fleet serving everything it
    ships looked like an arithmetic error beside "3 can be enabled". Both figures here are
    counts of the IMAGE and the value is a count of the FLEET.

    Neither number is a name compared here. The card asks ``offerable_transports`` the
    same question the enable dialog asks, so a transport retired later moves this figure
    with nothing on this screen to edit.
    """
    installed = len(discover())
    offerable = len(transports_service.offerable_transports())
    assert installed != offerable, (
        "this image offers everything it ships, so the card cannot be wrong about a "
        "retirement and this test would pass on the sentence it exists to replace"
    )

    screen = await client.get("/panel/")

    assert screen.status_code == 200, screen.text
    said = reading(screen)
    assert f"{installed} in this image, {offerable} can be enabled" in said, said


async def test_removing_a_retired_row_does_not_promise_it_can_be_enabled_again(
    client,
) -> None:
    """M20's acceptance, on the last surface that had not been told — the remove dialog.

    *"There is no undo, and enabling it here again mints new material"* is two claims and
    only the first survives a retirement: the walk removed a retired row and the enable
    dialog went on offering three, so the sentence described a form that is not there.
    The destructive half is untouched and asserted here too — a confirmation that lost its
    warning while gaining a correction would be a worse dialog than the one that was
    wrong.

    BOTH KINDS OF ROW, in one scenario, because the claim is a difference and a test that
    looked only at the retired one would pass on a dialog that had simply deleted the
    promise for everybody. The offered transport is read from
    ``offerable_transports`` rather than named, the same way the retired one is.

    Both rows are made by the same helper, which is a no-op for a transport that is not
    retired — so the only difference between the two readings below is the declaration on
    one of them.
    """
    offered = [
        name for name in transports_service.offerable_transports()
        if name not in RETIRED
    ]
    assert offered, "this image offers nothing, so there is no contrast to draw"

    said = {}
    for index, (name, node) in enumerate(
        ((next(iter(RETIRED)), "retired-row"), (offered[0], "offered-row"))
    ):
        node_id = await a_node(client, name=node, address=f"192.0.2.{80 + index}")
        row_id = await a_row_from_before_the_retirement(client, node_id, name)
        dialog = await client.get(f"/panel/transports/{row_id}/remove", headers=HTMX)
        assert dialog.status_code == 200, dialog.text
        said[name] = reading(dialog)

    retired, offerable = said[next(iter(RETIRED))], said[offered[0]]

    # The stale promise is gone from the retired row and still there for the one the
    # panel would really offer again.
    assert "mints new material" not in retired, retired
    assert "mints new material" in offerable, offerable
    assert "would not offer this protocol again" in retired, retired
    assert "would not offer this protocol again" not in offerable, offerable

    # And the destructive warning is on BOTH, which is the half that was never wrong.
    for reads in (retired, offerable):
        assert "there is no undo" in reads, reads
        assert "the material every user holds on it goes with it" in reads, reads


# --- and what retiring one may not do -----------------------------------------

async def test_a_node_already_running_a_retired_transport_still_renders(
    client, session
) -> None:
    """THE HALF THE OWNER'S OWN LEAF DEPENDS ON — done-when 3, end to end.

    The row is created the way theirs was — through the operator API, while the transport
    was still offered — and then every surface that has to keep working is asked, in the
    real fleet where it is retired: the node's own transports dialog, the config the node
    is pushed, and the file the user's device holds. A retirement that took any of those
    with it would have turned a protocol that carries nothing into a node that serves
    nothing.

    THE FRIEND IS MADE AFTER THE RETIREMENT IS BACK, which is the sharper half: this is
    somebody who joined the fleet today, on a node whose row predates the withdrawal, and
    the archive they are handed still has to contain that row's configuration. Refusing to
    create a row is not refusing to serve the one that exists, and nothing about the
    refusal may reach the fan-out that grants a new person material on it.
    """
    name = next(iter(RETIRED))
    node_id = await a_node(client, name="already-running", address="192.0.2.73")
    await a_row_from_before_the_retirement(client, node_id, name)
    await nodes_service.set_node_state(
        session, node_id=node_id, state=NodeState.ACTIVE
    )
    friend = await client.post("/api/friends", json={"nickname": "vera"})
    assert friend.status_code == 201, friend.text

    dialog = await client.get(f"/panel/nodes/{node_id}/transports")
    assert dialog.status_code == 200, dialog.text
    assert name in reading(dialog), (
        "the row on this node is not on the dialog that lists what it runs"
    )
    assert name not in GROUP.findall(dialog.text), (
        "the row renders AND the transport is proposed again — the second is what M20 "
        "stopped"
    )

    node = await nodes_service.get_node(session, node_id)
    rendered = await apply_service.render_for_node(session, node)
    assert rendered.get(name, "").strip(), "the node's own config no longer renders"

    session.expire_all()
    person = (await session.execute(select(User))).scalars().unique().one()
    files = await subscriptions_service.config_files_for(session, person)
    assert files, "the user on this node was handed nothing"
    assert any(rendered[name].strip() and file.content.strip() for file in files), (
        "the node renders the transport and the user's own file is empty"
    )


async def test_the_api_refuses_a_transport_the_registry_has_retired(
    client, session
) -> None:
    """THE ROUTE THAT USED TO SAY 201 — M20's acceptance, and the reason this file moved.

    An operator naming a retired transport outright was obeyed here: a row, ``enabled:
    true``, and a complete credential for it in the next friend's archive. What that costs
    is not a status code. It is a person on a tunnel whose handshake completes and which
    carries nothing on every host this project prepares, with nothing on their device
    saying so — and they would have no reason to suspect the protocol rather than the
    network they are on, which is the failure this whole product is built against.

    The sentence is the one the console answers with, character for character, because an
    API caller and an operator are learning the same fact: both read the transport's own
    reason, and both are told that a node already running it is untouched. It is asserted
    against the constant rather than against a copy of its words — a sentence pinned by a
    literal here is one that drifts out of the panel's the first time either is edited.

    Nothing is written, and that is asserted rather than assumed: this refusal is raised
    before the node is loaded and before any material is minted, so a partial row is not
    a thing that can be left behind.
    """
    name, reason = next(iter(RETIRED.items()))
    node_id = await a_node(client, name="named-outright", address="192.0.2.74")

    refused = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": name,
            "params": operator_params(name),
            **({"pool_size": a_pool_size(name)} if a_pool_size(name) else {}),
        },
    )

    assert refused.status_code == 422, refused.text
    envelope = refused.json()["error"]
    assert envelope["code"] == "transport_retired", envelope
    assert envelope["message"] == transports_service.NO_LONGER_OFFERED.format(
        name=name, reason=reason
    ), envelope
    session.expire_all()
    assert (
        await session.execute(select(NodeTransport))
    ).scalars().unique().all() == [], "the refusal enabled it anyway"


async def test_a_retired_transport_is_refused_on_a_node_that_is_already_serving(
    client, session
) -> None:
    """The same refusal on the path that would have fanned out to everybody.

    Enabling on a SERVING node grants every active friend material in the same
    transaction (``enable_and_grant``), so this is the one call where a retired
    transport's credential reaches devices immediately rather than at the next apply. A
    refusal that only guarded the draft case would leave the worst version of the bug
    reachable, and the two paths share ``_enable`` precisely so that they cannot differ —
    which is a claim worth one scenario rather than a comment.

    The friend exists before the attempt and holds no credential after it: nothing was
    minted, nothing was granted, and nobody's archive changed.

    THE SECOND ROW ASKS FOR A PORT AND A TUNNEL OF ITS OWN, and that is what makes this
    test able to fail for its own reason. Two rows on one node may share neither, and this
    control plane refuses both on its own — so with the retirement check deleted the call
    would still not be a 201, and the scenario would be pinning a collision while claiming
    to pin a retirement. Every value below is dropped by ``operator_params`` for a
    transport that does not declare it, so no protocol is assumed to have either.
    """
    name = next(iter(RETIRED))
    node_id = await a_node(client, name="serving-already", address="192.0.2.77")
    offered = transports_service.offerable_transports()
    assert offered, "this image offers nothing, so no node here can reach service"
    await a_row_from_before_the_retirement(client, node_id, offered[0])
    await nodes_service.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    assert (await client.post("/api/friends", json={"nickname": "yura"})).status_code == 201

    refused = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": name,
            "params": operator_params(
                name,
                port=51899,
                tunnel_address="10.92.0.1/24",
                peer_tunnel_address="10.92.0.2/24",
            ),
            **({"pool_size": a_pool_size(name)} if a_pool_size(name) else {}),
        },
    )

    assert refused.status_code == 422, refused.text
    session.expire_all()
    rows = (
        await session.execute(
            select(NodeTransport).where(NodeTransport.transport_name == name)
        )
    ).scalars().unique().all()
    assert rows == [], "the refusal enabled it on a serving node anyway"


async def test_a_row_of_a_retired_transport_can_still_be_removed(
    client, session
) -> None:
    """The operator can get rid of it — the half a refusal must not take with it.

    A protocol nobody may enable any more is one every operator will eventually want off
    their nodes, and it is the single action they have left for it. Both surfaces are
    asked in one scenario because a console that could no longer do it would be the
    version of this bug an API check never sees, and the console is where an operator is.

    The row's material goes with it, which is ``remove_transport``'s own contract and is
    asserted here only as the absence of the row: what this test is about is that the
    refusal above reaches the CREATION and nothing else.
    """
    name = next(iter(RETIRED))
    first = await a_node(client, name="removable-api", address="192.0.2.81")
    second = await a_node(client, name="removable-panel", address="192.0.2.82")
    by_api = await a_row_from_before_the_retirement(client, first, name)
    by_panel = await a_row_from_before_the_retirement(client, second, name)

    removed = await client.delete(f"/api/transports/{by_api}")
    assert removed.status_code == 200, removed.text
    from_the_console = await client.post(
        f"/panel/transports/{by_panel}/remove", headers=HTMX
    )
    assert from_the_console.status_code == 200, from_the_console.text

    session.expire_all()
    assert (
        await session.execute(select(NodeTransport))
    ).scalars().unique().all() == [], "a retired transport's row cannot be removed"
