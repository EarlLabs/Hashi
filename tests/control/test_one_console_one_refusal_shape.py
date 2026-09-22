"""Every form in this console refuses the same way — M23, round 8.

WHAT: what a panel form answers when the submission is refused before anything is
      written, for a caller that did not ask with htmx.
WHY:  measured on the owner's real hosts. ``POST /panel/nodes`` answered a submission
      with two boxes empty with **400 and the error envelope**, carrying the field
      sentences run together into one paragraph that named no field and said the same
      thing twice — *"required — a node cannot be registered without it required — a node
      cannot be registered without it"*. ``POST /panel/users``, one screen over,
      answered its own refusal with **422 and the dialog re-rendered**, message under the
      box. Two shapes for the same kind of refusal, in one console.

      The split was the last piece of the pre-redesign browser form: a caller that is not
      htmx has nowhere to render a field error, so it was handed an envelope instead. What
      it actually produced was a worse refusal for the caller it was written for, while the
      machine surface that answers refusals properly — ``/api/**``, per field through the
      request model — was sitting one prefix away.
HOW:  real Postgres, no host dialled, no htmx header on any request in this file. What is
      asserted is the SHAPE of the answer: its status, that it is the dialog, and that the
      message is under the box it is about.
"""

import json

from .conftest import GENERATED_SSH_KEY

# RFC 5737 documentation address, as everywhere in this zone.
NODE_ADDRESS = "192.0.2.90"

# The sentence the node form puts under a box that had to be filled in. Written out
# because the paragraph the old envelope made of it — this, twice, with nothing between —
# is the finding.
REQUIRED = "required — a node cannot be registered without it"


def is_the_error_envelope(response) -> bool:
    """Whether this is the JSON envelope, whatever the status line says."""
    try:
        return "error" in response.json()
    except (json.JSONDecodeError, ValueError):
        return False


async def test_a_node_form_refused_without_htmx_gets_the_dialog_and_not_an_envelope(
    client,
) -> None:
    """The finding itself: two empty boxes, no htmx header.

    Red against the previous commit: 400, ``{"error": {...}}``, and the two field
    sentences joined into one paragraph naming neither field.
    """
    refused = await client.post(
        "/panel/nodes", data={"name": "", "address": "", "location_label": "Testland"}
    )

    assert refused.status_code == 422, refused.text
    assert not is_the_error_envelope(refused), refused.text
    # The dialog, with the message under each box that was empty.
    assert "Add a node" in refused.text
    assert 'id="node-name-error"' in refused.text, refused.text
    assert 'id="node-address-error"' in refused.text, refused.text
    assert f"{REQUIRED} {REQUIRED}" not in " ".join(refused.text.split()), (
        "the refusal is still one paragraph of field sentences with no field named"
    )


async def test_the_user_form_answers_the_same_way_it_always_did(client) -> None:
    """The shape the console already had, asserted beside it — the pair IS the claim.

    ``POST /panel/users`` is the reference: it has never had the split, so a change that
    unified the two by giving this one an envelope would satisfy the test above and be the
    same finding pointing the other way.
    """
    refused = await client.post("/panel/users", data={"nickname": ""})

    assert refused.status_code == 422, refused.text
    assert not is_the_error_envelope(refused), refused.text
    assert "a nickname is required" in refused.text


async def test_the_transport_form_refuses_in_that_shape_too(client) -> None:
    """The other half of the one split, on the other route that carried it.

    ``POST /panel/nodes/{id}/transports`` is the second route the split was written for,
    and a fix that left it behind would leave the console with two shapes on a route the
    walk happened not to press.
    """
    node = await client.post(
        "/api/nodes",
        json={
            "name": "leaf-1",
            "address": NODE_ADDRESS,
            "location_label": "Testland",
            "ssh_private_key": GENERATED_SSH_KEY,
        },
    )
    assert node.status_code == 201, node.text

    refused = await client.post(
        f"/panel/nodes/{node.json()['id']}/transports",
        data={"transport_name": "vless-reality"},
    )

    assert refused.status_code == 422, refused.text
    assert not is_the_error_envelope(refused), refused.text
    # The dialog again, and the complaint under the boxes rather than in a paragraph.
    assert 'class="dialog-backdrop"' in refused.text, refused.text
    assert 'aria-invalid="true"' in refused.text, refused.text


async def test_the_machine_surface_still_refuses_per_field(client) -> None:
    """And nothing was taken away: the caller that wants a machine answer has one.

    This is what makes the change above a narrowing of the console rather than a loss.
    ``/api/nodes`` refuses the same submission through the request model, naming each
    field it refused — which is more than the envelope the panel used to raise ever said.
    """
    refused = await client.post(
        "/api/nodes", json={"name": "", "address": "", "location_label": "Testland"}
    )

    assert refused.status_code == 422, refused.text
    named = json.dumps(refused.json())
    assert "name" in named and "address" in named, named
