"""The key the add-node dialog calls optional can actually be supplied — M23.

WHAT: ``/panel/nodes/{id}/ssh-key`` and ``nodes.set_ssh_key``, and what an apply and a
      probe say about a node whose record holds no key at all.
WHY:  found on the owner's real hosts. The add-node dialog invites a node without a key
      — *"Optional now — without it the node can be registered but its configuration
      cannot be applied"* — and every route that could have supplied one afterwards
      answered 404: ``edit``, ``credentials``, ``ssh``, ``key``, ``access``, ``delete``,
      ``remove``, ``retire``, and ``DELETE`` on the node itself. A node registered on
      that invitation was unappliable for ever and unreachable by a revocation for ever.

      The second half is the sentence such a node produced. Both the apply banner and
      the probe banner read *"the node refused the key this control plane holds for
      it"* — over a control plane holding none — which sends the operator to debug the
      host's ``authorized_keys`` for a fault that is entirely on this side.
HOW:  real Postgres, real encryption, the real panel routes. No host is dialled: every
      path here is refused before a connection is attempted, which is the whole point
      of the refusal being where it is.
"""

import pytest
from sqlalchemy import select

from control.app.models import AuditAction, AuditEntry
from control.app.services import apply, nodes

from .conftest import GENERATED_SSH_KEY

# RFC 5737 documentation address, as everywhere in this zone.
NODE_ADDRESS = "192.0.2.80"

# The sentence ``edge`` produces when a host really did refuse our key — right where it
# fires, and the one a keyless node must never reach. Written out rather than imported:
# what is asserted is that this panel does not SAY it, and importing it from the module
# that owns it would make the assertion agree with a rename instead of with the words.
THE_HOSTS_REFUSAL = "the node refused the key this control plane holds for it"


async def a_keyless_node(client, reality_params, *, name: str = "keyless-1") -> str:
    """A node registered exactly as the add-node dialog invites: no key, one transport."""
    created = await client.post(
        "/api/nodes",
        json={"name": name, "address": NODE_ADDRESS, "location_label": "Testland"},
    )
    assert created.status_code == 201, created.text
    node_id = created.json()["id"]
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text
    return node_id


# --- the key can be supplied --------------------------------------------------

async def test_the_dialog_exists_and_stores_what_is_pasted_into_it(
    client, session, reality_params
) -> None:
    """The finding, closed: the node that could never be given a key is given one.

    ``target_for`` is asserted rather than the column, because what the operator needs
    is not a row that changed — it is the next connection using the key. Reading the
    column would pass over a store that never reached the thing that dials.

    Red against the previous commit: the GET is a 404 and so is the POST.
    """
    node_id = await a_keyless_node(client, reality_params)

    dialog = await client.get(f"/panel/nodes/{node_id}/ssh-key")
    assert dialog.status_code == 200, dialog.text
    assert "has no key on its record" in dialog.text, dialog.text

    stored = await client.post(
        f"/panel/nodes/{node_id}/ssh-key",
        data={"ssh_private_key": GENERATED_SSH_KEY},
        headers={"HX-Request": "true"},
    )

    assert stored.status_code == 200, stored.text
    assert "ssh key stored for keyless-1" in stored.text, stored.text
    node = await nodes.get_node(session, node_id)
    assert apply.target_for(node, apply.settings()).private_key == GENERATED_SSH_KEY


async def test_a_paste_this_control_plane_cannot_read_is_refused_under_its_own_box(
    client, session, reality_params
) -> None:
    """The same sentence the add-node dialog refuses a bad paste with, and no value back.

    The refusal may not quote what was pasted, and the box may not be refilled with it:
    this is the one credential that reaches every host in the fleet, and putting it in
    the markup would make the panel a place key material appears — which is the rule the
    add-node dialog states for the same box.
    """
    node_id = await a_keyless_node(client, reality_params)
    typed = "-----BEGIN OPENSSH PRIVATE KEY----- TRUNCATED-PASTE-0123456789"

    refused = await client.post(
        f"/panel/nodes/{node_id}/ssh-key",
        data={"ssh_private_key": typed},
        headers={"HX-Request": "true"},
    )

    assert refused.status_code == 422, refused.text
    assert "not a private key this control plane can read" in refused.text
    if "TRUNCATED-PASTE-0123456789" in refused.text:
        # ``pytest.fail`` rather than ``assert``: a rewritten assertion prints both
        # operands, and this one stands in for a private key.
        pytest.fail("the refusal handed the pasted key back into the markup")
    assert (await nodes.get_node(session, node_id)).ssh_private_key is None


async def test_an_empty_submission_never_clears_a_stored_key(
    client, session, reality_params
) -> None:
    """Submitting nothing is a mistake, not an instruction to make a node unreachable.

    There is no in-product reason to take a node's key away, and doing it by pressing
    the primary button on an empty form is the accident version of it — the node would
    go unappliable with nothing on screen saying why.
    """
    node_id = await a_keyless_node(client, reality_params)
    await nodes.set_ssh_key(session, node_id=node_id, ssh_private_key=GENERATED_SSH_KEY)

    refused = await client.post(
        f"/panel/nodes/{node_id}/ssh-key",
        data={"ssh_private_key": ""},
        headers={"HX-Request": "true"},
    )

    assert refused.status_code == 422, refused.text
    assert (await nodes.get_node(session, node_id)).ssh_private_key == GENERATED_SSH_KEY


async def test_no_surface_of_this_dialog_renders_the_key_it_holds(
    client, session, reality_params
) -> None:
    """A stored key is never displayed again, including by the form that stored it."""
    node_id = await a_keyless_node(client, reality_params)
    await nodes.set_ssh_key(session, node_id=node_id, ssh_private_key=GENERATED_SSH_KEY)

    dialog = await client.get(f"/panel/nodes/{node_id}/ssh-key")

    assert dialog.status_code == 200
    assert "A key is already stored for keyless-1" in dialog.text
    for line in GENERATED_SSH_KEY.splitlines():
        if len(line) > 16 and line in dialog.text:
            pytest.fail("the ssh-key dialog rendered the key it is holding")


async def test_the_change_is_recorded_by_the_nodes_name_and_nothing_else(
    client, session, reality_params
) -> None:
    """One entry, one label, and nothing about the key — not even that it replaced one.

    A retried paste of the same key records nothing, exactly as a resolver already in
    place records nothing: a retried click is not an event.
    """
    node_id = await a_keyless_node(client, reality_params)

    await nodes.set_ssh_key(session, node_id=node_id, ssh_private_key=GENERATED_SSH_KEY)
    await nodes.set_ssh_key(session, node_id=node_id, ssh_private_key=GENERATED_SSH_KEY)

    entries = (
        await session.execute(
            select(AuditEntry).where(AuditEntry.action == AuditAction.NODE_SSH_KEY_SET)
        )
    ).scalars().all()
    assert len(entries) == 1, [entry.action for entry in entries]
    assert entries[0].first_label == "keyless-1"
    assert entries[0].second_label is None
    for line in GENERATED_SSH_KEY.splitlines():
        if len(line) > 16 and line in (entries[0].first_label or ""):
            pytest.fail("the audit trail carries part of an SSH private key")


# --- and until it is, the reason given names the right side -------------------

async def test_an_apply_on_a_keyless_node_does_not_blame_the_host(
    client, session, reality_params
) -> None:
    """M23's seventh finding, first half: the control plane holds no key and said the
    host refused one.

    The console version of the sentence names the control that fixes it, because the
    operator is looking at the row it is on. The API's version says only what has to
    happen — there is no screen on that side to send anybody to.

    Red against the previous commit: the apply dialled with no credential, the host
    answered ``PermissionDenied``, and the banner carried ``THE_HOSTS_REFUSAL``.
    """
    node_id = await a_keyless_node(client, reality_params)

    banner = await client.post(
        f"/panel/nodes/{node_id}/apply", headers={"HX-Request": "true"}
    )

    assert banner.status_code == 200, banner.text
    assert "this node has no SSH key on its record" in banner.text, banner.text
    assert "the host refused nothing, because nothing was offered to it" in banner.text
    assert THE_HOSTS_REFUSAL not in banner.text, (
        "the operator was sent to debug the host's authorized_keys for a key this "
        "control plane never had"
    )
    assert "ssh key" in banner.text and "the Nodes screen" in banner.text, banner.text

    envelope = (await client.post(f"/api/nodes/{node_id}/apply")).json()["error"]["message"]
    assert "this node has no SSH key on its record" in envelope
    assert "the Nodes screen" not in envelope, (
        "a caller with no panel was sent to a screen"
    )


async def test_a_probe_on_a_keyless_node_does_not_blame_the_host_either(
    client, reality_params
) -> None:
    """The same node, the other button — and it was the same wrong sentence.

    The probe is where an operator goes to find out what is wrong, so it is the surface
    on which a misattributed cause costs the most: it is read as a measurement.
    """
    node_id = await a_keyless_node(client, reality_params)

    banner = await client.post(
        f"/panel/nodes/{node_id}/probe", headers={"HX-Request": "true"}
    )

    assert banner.status_code == 200, banner.text
    assert "this node has no SSH key on its record" in banner.text, banner.text
    assert THE_HOSTS_REFUSAL not in banner.text, banner.text


async def test_the_node_is_appliable_the_moment_it_has_a_key(
    client, session, reality_params
) -> None:
    """The refusal is about the record and nothing else, so supplying one lifts it.

    What follows is an ordinary failure to reach a documentation address, which is a
    different sentence and a different next action — and is what the operator was owed
    all along.
    """
    node_id = await a_keyless_node(client, reality_params)
    await nodes.set_ssh_key(session, node_id=node_id, ssh_private_key=GENERATED_SSH_KEY)

    node = await nodes.get_node(session, node_id)
    target = apply.target_for(node, apply.settings())

    assert target.private_key == GENERATED_SSH_KEY
    assert target.host == NODE_ADDRESS
