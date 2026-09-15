"""There is a setting in this panel that gives a user working DNS — M23.

WHAT: that every field a transport lets an operator supply has a box on the enable form
      and on the replace-parameters form, that a box the transport defaults may be left
      empty, and that answering the one a resolver is written from reaches the file a
      user's client downloads.
WHY:  measured on the owner's Amsterdam leaf with two real AmneziaWG clients. Both
      friends completed a handshake, exited at the leaf and moved five megabytes, and
      neither resolved a single name — because their config carried no ``DNS`` line
      while ``AllowedIPs`` routed every address into the tunnel, their own resolver
      included. The walk's verdict on the panel was the sentence this file exists
      against: *"There is no setting in the panel that gives a friend working DNS."*

      The renderer's half landed first: a friend's config now takes its ``DNS`` from the
      transport's ``client_dns``, falling back to the node record's own resolver. That
      changed nothing an operator could reach, because ``client_dns`` DECLARES A DEFAULT
      and both forms filtered their boxes on ``is_required``. The route had always
      accepted the value. No form had ever drawn the box.

      ROUND 2 ADDED THE OTHER HALF, and it is a regression this milestone introduced:
      the box exists, and an address in a family the tunnel cannot carry was ACCEPTED by
      it. The refusal lived at render, so the value was stored, the form answered 200, and
      the next download of every user on that node was a 500 — or, where it was their only
      node, a twenty-two-byte empty archive with nothing said. ``edge`` owns that rule and
      now answers it as a predicate both a form and a renderer can ask
      (``egress.client_resolver_problem``); what is asserted here is that the panel really
      does ask it, on both forms, and that a row already holding such a value no longer
      costs a user the nodes it is not about.
HOW:  real Postgres, real encryption, real rendering, and the panel's own forms — the
      value is typed into the dialog the operator uses rather than posted to the API,
      because the API was never the half that was broken.
"""

import html

import pytest

from control.app.models import NodeState
from control.app.services import friends, nodes, rotation, subscriptions
from control.app.services import transports as transports_service
from edge.registry import SubscriptionFormat, discover

# RFC 5737 documentation addresses, as everywhere in this zone.
NODE_ADDRESS = "192.0.2.90"
# A resolver outside the tunnel's own range — inside it is refused, and rightly: every
# address in that range is one a user's device holds.
A_RESOLVER = "192.0.2.53"
ANOTHER_RESOLVER = "198.51.100.53"

# An address a friend's device could never hear back from: their config routes every IPv6
# address into the tunnel and the node drops all of it. RFC 3849's documentation prefix,
# standing in for the public resolver an operator pastes in when their own machine happens
# to print the v6 form first — which is how the walk produced it.
A_RESOLVER_THE_TUNNEL_CANNOT_CARRY = "2001:db8::53"

# The one field name this file writes down, and it is the subject rather than an
# incidental: the walk's finding is about the parameter a user's resolver is written
# from. Everything structural below is driven off the registry instead.
RESOLVER_FIELD = "client_dns"

# One node's worth of operator input for the transport that serialises into a file, as
# the neighbouring file writes it: no API can invent a port or an address.
AWG_PARAMS: dict[str, object] = {
    "port": 51820,
    "tunnel_address": "10.90.0.1/24",
    "peer_tunnel_address": "10.90.0.2/24",
    "mtu": 1280,
    "junk_packet_count": 4,
    "junk_packet_min_size": 40,
    "junk_packet_max_size": 80,
    "init_packet_magic_header": 1020327352,
    "response_packet_magic_header": 2060487442,
    "underload_packet_magic_header": 3679305607,
    "transport_packet_magic_header": 1436947798,
}
POOL_SIZE = 50


@pytest.fixture
def file_transport() -> str:
    """The transport in this image a user receives as a file — resolved, never named."""
    shapes = sorted(
        name
        for name, meta in discover().items()
        if SubscriptionFormat.CLIENT_CONFIG_FILE in meta.subscription_formats
        and meta.retired is None
    )
    if not shapes:
        pytest.skip("this image ships no transport a user receives as a file")
    return shapes[0]


async def a_node(client, name: str = "leaf-nl") -> str:
    created = await client.post(
        "/api/nodes",
        json={"name": name, "address": NODE_ADDRESS, "location_label": "Testland"},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def form_for(transport_name: str, **overrides: object) -> dict[str, str]:
    """The enable dialog's submission for one transport: every box, named for its group."""
    values = {**AWG_PARAMS, "pool_size": POOL_SIZE, **overrides}
    return {
        "transport_name": transport_name,
        **{f"{transport_name}-{name}": str(value) for name, value in values.items()},
    }


async def a_user(client, *, nickname: str) -> str:
    created = await client.post("/api/friends", json={"nickname": nickname})
    assert created.status_code < 300, created.text
    return created.json()["id"]


async def the_file_for(session, friend_id: str) -> str:
    """The configuration file that user's client would download, as one string."""
    handle = await friends.get_friend(session, friend_id)
    configs = await subscriptions.config_files_for(session, handle)
    assert len(configs) == 1, [config.filename for config in configs]
    return configs[0].content


async def a_users_file(client, session, *, nickname: str) -> str:
    return await the_file_for(session, await a_user(client, nickname=nickname))


async def the_file_a_user_would_download(app, friend_id: str) -> str:
    """The same file, produced by a session that has been holding nothing.

    Which is what a friend's download actually is: a request of its own, with a session
    of its own, reading every row for the first time. THE TEST'S OWN ``session`` FIXTURE
    IS NOT THAT — it stays open across POSTs made in other sessions, and a session keeps
    what it loaded (``expire_on_commit=False``), so a node-transport it read before the
    replace still holds the parameters from before the replace. Asserting through it
    would be asserting that this test can see a change, not that a user can.

    Consumed with ``async for`` off the application's own generator, exactly as the
    retention sweeper consumes it (``services/audit.sweep_forever``) and as the fixtures
    do: one session, closed when the loop ends.
    """
    content = ""
    async for handle in app.state.database.session():
        content = await the_file_for(handle, friend_id)
    return content


# --- the boxes exist ----------------------------------------------------------

def test_at_least_one_shipped_transport_defaults_a_parameter() -> None:
    """The premise, stated first: without it every assertion below is vacuous.

    A transport whose every field is required cannot tell the two sets apart, so an
    image of only such transports would pass this file while the filter that caused the
    finding was back in place.
    """
    defaulted = {
        name: sorted(
            transports_service.supplied_params(name)
            - set(transports_service.operator_params(name))
        )
        for name in transports_service.offerable_transports()
    }
    assert any(defaulted.values()), (
        "no transport in this image defaults a parameter, so nothing here proves that a "
        "defaulted one gets a box"
    )


async def test_both_forms_draw_a_box_for_every_field_an_operator_may_supply(
    client, session, reality_params, file_transport: str
) -> None:
    """The fix, over every transport rather than over the one that was found.

    ``supplied_params`` is the widest set a form of ours may accept and is what the
    enable ROUTE has always read a submission against. Asserting the boxes against it —
    on both forms, for every offerable transport — is what makes "a parameter the
    transport defaults can be answered here" a property of the panel rather than of one
    protocol.

    The two forms are asserted together on purpose: they disagreed for a while, and the
    module that computes them exists because an operator reads that disagreement as a
    bug in the protocol.

    Red against the previous commit: the defaulted field has no box on either form.
    """
    node_id = await a_node(client)
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": file_transport,
            "params": AWG_PARAMS,
            "pool_size": POOL_SIZE,
        },
    )
    assert enabled.status_code == 201, enabled.text

    dialog = await client.get(f"/panel/nodes/{node_id}/transports")
    assert dialog.status_code == 200, dialog.text
    for name in transports_service.offerable_transports():
        for field in sorted(transports_service.supplied_params(name)):
            assert f'name="{name}-{field}"' in dialog.text, f"{name}.{field}"
        for minted in sorted(transports_service.key_material_names(name)):
            assert f'name="{name}-{minted}"' not in dialog.text, f"{name}.{minted}"

    replace = await client.get(f"/panel/keys/{enabled.json()['id']}/params")
    assert replace.status_code == 200, replace.text
    for field in sorted(transports_service.supplied_params(file_transport)):
        assert f'name="{field}"' in replace.text, field
    for minted in sorted(transports_service.key_material_names(file_transport)):
        assert f'name="{minted}"' not in replace.text, minted


async def test_a_box_the_transport_defaults_may_be_left_empty(
    client, session, file_transport: str
) -> None:
    """A box is not a demand: the enable form refuses only what the transport requires.

    Without this the widening would be worse than the filter it replaced — every new box
    would become a field nobody could leave alone, and an operator with no resolver to
    give would be unable to enable the transport at all.
    """
    node_id = await a_node(client)

    enabled = await client.post(
        f"/panel/nodes/{node_id}/transports",
        data=form_for(file_transport, **{RESOLVER_FIELD: ""}),
        headers={"HX-Request": "true"},
    )

    assert enabled.status_code == 200, enabled.text
    assert "enabled on leaf-nl" in enabled.text, enabled.text


async def test_a_box_the_transport_requires_is_still_refused_when_it_is_empty(
    client, file_transport: str
) -> None:
    """The other side of the same line, so ``required`` is read rather than ignored."""
    node_id = await a_node(client)

    refused = await client.post(
        f"/panel/nodes/{node_id}/transports",
        data=form_for(file_transport, mtu=""),
        headers={"HX-Request": "true"},
    )

    assert refused.status_code == 422, refused.text
    assert f'id="enable-{file_transport}-mtu-error"' in refused.text, refused.text


# --- and answering one reaches the file a user downloads ----------------------

async def test_the_enable_form_can_give_a_user_a_resolver(
    client, session, file_transport: str
) -> None:
    """The walk's finding, end to end and on the surface the operator actually uses.

    What the walk's command proves is not that a column changed: it is that the file a
    user imports names a resolver, because the absence of that line is what left two
    real clients resolving nothing over a working tunnel. So the assertion is on the
    rendered file.

    Red against the previous commit: the form drew no box for the field, the submission
    below would be refused as a name this form cannot read, and no ``DNS`` line exists.
    """
    node_id = await a_node(client)
    enabled = await client.post(
        f"/panel/nodes/{node_id}/transports",
        data=form_for(file_transport, **{RESOLVER_FIELD: A_RESOLVER}),
        headers={"HX-Request": "true"},
    )
    assert enabled.status_code == 200, enabled.text
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)

    content = await a_users_file(client, session, nickname="kolya")

    assert f"DNS = {A_RESOLVER}" in content, content
    assert "NO RESOLVER WAS SET FOR THIS NODE" not in content, content


async def test_the_replace_form_can_give_a_resolver_to_a_row_that_has_none(
    client, session, app, file_transport: str
) -> None:
    """The repair path, which is the one the owner's fleet needs.

    Every row enabled before this change carries no resolver, and re-enabling a
    transport is not an option: it mints new material for everyone on it. So the
    replace-parameters form has to be able to set it on a row already serving people,
    and the file a user downloads has to change without them re-importing anything.
    """
    node_id = await a_node(client)
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": file_transport,
            "params": AWG_PARAMS,
            "pool_size": POOL_SIZE,
        },
    )
    assert enabled.status_code == 201, enabled.text
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)

    friend_id = await a_user(client, nickname="masha")
    before = await the_file_a_user_would_download(app, friend_id)
    assert "DNS = " not in before, before

    replaced = await client.post(
        f"/panel/keys/{enabled.json()['id']}/params",
        data={RESOLVER_FIELD: ANOTHER_RESOLVER},
        headers={"HX-Request": "true"},
    )
    assert replaced.status_code == 200, replaced.text
    # The replace commits and then pushes, and this node has no SSH key, so the push
    # leaves it degraded — which takes it out of every subscription. That is correct and
    # is not this test's subject: put it back in service, the way the operator would
    # after fixing whatever the push hit, and read the same person's file again.
    #
    # That put-back is decided against the ROW rather than against the node this session
    # was left holding (``nodes._node_to_write``). Until that fix it wrote nothing at all
    # — the degrade had happened in the request's session, this one still read ``active``,
    # and the line below then read an empty subscription for a node the database had
    # never taken out of ``degraded``.
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)

    after = await the_file_a_user_would_download(app, friend_id)
    assert f"DNS = {ANOTHER_RESOLVER}" in after, after


async def test_a_resolver_inside_the_tunnel_is_refused_under_its_own_box(
    client, file_transport: str
) -> None:
    """The one answer that would be worse than none, refused where it is typed.

    Every address in a row's tunnel range is one a user's device holds, so a resolver
    there would point every user's lookups at whichever person was given it — the record
    this project exists not to produce. The transport refuses it; what is asserted here
    is that the refusal lands under the box, which is only possible because the box now
    exists.
    """
    node_id = await a_node(client)

    refused = await client.post(
        f"/panel/nodes/{node_id}/transports",
        data=form_for(file_transport, **{RESOLVER_FIELD: "10.90.0.7"}),
        headers={"HX-Request": "true"},
    )

    assert refused.status_code == 422, refused.text
    assert f'id="enable-{file_transport}-{RESOLVER_FIELD}-error"' in refused.text


# --- and the two dialogs that gave the opposite advice ------------------------

async def test_the_node_dialogs_say_the_resolver_reaches_a_users_own_configuration(
    client
) -> None:
    """Both places an operator sets a resolver, and what they said before M23.

    The add-node dialog read *"Leave it empty on a node that will never dial one"* and
    the resolver dialog described the value as being about dialling a hop. A leaf dials
    nothing — so on the one node type where this field is now the difference between a
    user resolving names and not, both dialogs told the operator the box was not for
    them.
    """
    node_id = await a_node(client)

    adding = await client.get("/panel/nodes/new")
    editing = await client.get(f"/panel/nodes/{node_id}/resolver")

    for response in (adding, editing):
        assert response.status_code == 200, response.text
        # Unescaped, because the two dialogs carry the same sentence by two routes: the
        # resolver dialog writes it as template prose and the add-node dialog passes it
        # through a macro, which escapes the apostrophe. A raw search would pass on one
        # and fail on the other for a reason that has nothing to do with the wording.
        seen = html.unescape(response.text)
        assert "user's own configuration file" in seen, seen
        assert "no name resolves" in seen, seen
    assert "never dial one" not in html.unescape(adding.text), adding.text


# --- and the answer that is worse than an empty box (round 2) -----------------

async def test_a_resolver_the_tunnel_cannot_carry_is_refused_by_the_enable_form(
    client, file_transport: str
) -> None:
    """The regression, on the first of the two forms that stored it.

    A hostname in this box was always refused clearly, so the box already knew how to
    refuse; an address of the wrong family was not, and the cost landed on the user's
    download rather than on the operator's screen.

    Red against the previous commit: the submission is accepted with a 200 toast.
    """
    node_id = await a_node(client)

    refused = await client.post(
        f"/panel/nodes/{node_id}/transports",
        data=form_for(
            file_transport, **{RESOLVER_FIELD: A_RESOLVER_THE_TUNNEL_CANNOT_CARRY}
        ),
        headers={"HX-Request": "true"},
    )

    assert refused.status_code == 422, refused.text
    assert f'id="enable-{file_transport}-{RESOLVER_FIELD}-error"' in refused.text
    # The reason names the family and what it costs, which is what makes the box
    # answerable rather than merely closed.
    assert "IPv6" in refused.text and "no name would resolve" in refused.text


async def test_a_resolver_the_tunnel_cannot_carry_is_refused_by_the_replace_form(
    client, session, file_transport: str
) -> None:
    """And on the form the owner's existing rows are repaired from.

    The enable form is where a new row gets it wrong; this one is where a row that is
    already serving people would — and a refusal here is the only thing standing between
    a typo and every one of those people losing their configuration file at once.
    """
    node_id = await a_node(client)
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": file_transport,
            "params": AWG_PARAMS,
            "pool_size": POOL_SIZE,
        },
    )
    assert enabled.status_code == 201, enabled.text

    refused = await client.post(
        f"/panel/keys/{enabled.json()['id']}/params",
        data={RESOLVER_FIELD: A_RESOLVER_THE_TUNNEL_CANNOT_CARRY},
        headers={"HX-Request": "true"},
    )

    assert refused.status_code == 422, refused.text
    assert f'id="param-{RESOLVER_FIELD}-error"' in refused.text, refused.text


async def test_one_row_that_cannot_be_rendered_does_not_take_away_the_others(
    client, session, app, file_transport: str
) -> None:
    """The general form of the finding, which is the half that outlives it.

    A row whose stored parameters cannot be rendered is not hypothetical on the owner's
    fleet: every value the two forms now refuse could have been stored before they did.
    What must not happen is what did — one such row answering a user's whole subscription
    with a 500, taking away every node they hold rather than the one it is about.

    The value is written straight onto the row, PAST the model, because that is exactly
    what an older fleet's database looks like and there is no other way to reach it now.
    """
    good = await a_node(client, "leaf-nl")
    bad = await a_node(client, "leaf-is")
    rows = []
    for node_id in (good, bad):
        enabled = await client.post(
            f"/api/nodes/{node_id}/transports",
            json={
                "transport_name": file_transport,
                "params": AWG_PARAMS,
                "pool_size": POOL_SIZE,
            },
        )
        assert enabled.status_code == 201, enabled.text
        rows.append(enabled.json()["id"])
        await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)

    friend_id = await a_user(client, nickname="kolya")
    row = await rotation.get_node_transport(session, rows[1])
    row.params = {**row.params, RESOLVER_FIELD: [A_RESOLVER_THE_TUNNEL_CANNOT_CARRY]}
    await session.commit()

    handle = await friends.get_friend(session, friend_id)
    configs = await subscriptions.config_files_for(session, handle)

    assert len(configs) == 1, [config.filename for config in configs]
    assert "leaf-nl" in configs[0].filename, configs[0].filename

    # And on the route a user's client actually fetches, which is where the 500 was.
    token = (
        await client.get(f"/panel/friends/{friend_id}/subscription")
    ).text
    assert "/sub/" in token, token
    path = token.split("/sub/")[1].split("<")[0].split('"')[0].strip()
    delivered = await client.get(f"/sub/{path}?format=client-config-file")
    assert delivered.status_code == 200, delivered.text
    assert len(delivered.content) > len(subscriptions.archive_of([])), (
        "the user was handed an empty archive over a node that renders perfectly well"
    )
