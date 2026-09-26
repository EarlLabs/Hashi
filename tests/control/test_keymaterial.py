"""Key material — backlog item 6a.

WHAT: that generation is keyed by cryptographic KIND, produces the right shapes, and
      never repeats itself.
WHY:  item 6a existed because generation was assumed by items 7, 8 and 9 and assigned
      to nobody. These tests pin the two properties everything downstream relies on:
      the material is the shape the data plane expects, and no two nodes or users
      ever share any of it.
HOW:  pure unit tests. No database, no application.
"""

import base64

import pytest

from control.app.services import keymaterial
from edge.registry import KeyKind, KeyScope, KeySpec, discover


def test_every_kind_has_a_generator() -> None:
    """A declared kind with no generator would fail at node-creation time, in the panel.

    Parametrised over the enum rather than a list, so adding a kind without a generator
    fails here instead of in front of the operator.
    """
    for kind in KeyKind:
        spec = KeySpec(name="value", kind=kind, scope=KeyScope.NODE, public_name="value_public")
        minted = keymaterial.mint([spec], KeyScope.NODE)
        assert minted.params or minted.secrets, f"{kind}: generated nothing"


def test_an_unknown_kind_fails_loudly() -> None:
    """Never a silent empty value: an empty private key renders a node that serves nobody."""

    class Fake:
        pass

    with pytest.raises(keymaterial.UnsupportedKeyKind):
        keymaterial.mint(
            [KeySpec(name="x", kind=Fake(), scope=KeyScope.NODE)], KeyScope.NODE
        )


def test_x25519_is_encoded_the_way_the_data_plane_expects() -> None:
    """Raw 32 bytes, base64-url, unpadded — what ``xray x25519`` emits.

    The specific failure this prevents: PEM output here is accepted by our own
    validation and rejected by the daemon, with an error that points at the config
    rather than at the encoding.
    """
    spec = KeySpec(
        name="private_key",
        kind=KeyKind.X25519_KEYPAIR,
        scope=KeyScope.NODE,
        public_name="public_key",
    )
    minted = keymaterial.mint([spec], KeyScope.NODE)

    private = minted.secrets["private_key"]
    public = minted.params["public_key"]

    for label, value in (("private", private), ("public", public)):
        assert "=" not in value, f"{label} half is padded"
        assert "-----BEGIN" not in value, f"{label} half is PEM, not raw"
        # Unpadded base64url of 32 bytes is 43 characters.
        assert len(value) == 43, f"{label} half is {len(value)} chars, expected 43"
        decoded = base64.urlsafe_b64decode(value + "=")
        assert len(decoded) == 32, f"{label} half decodes to {len(decoded)} bytes"

    assert private != public


def test_the_public_half_goes_to_params_and_the_private_half_to_secrets() -> None:
    """The split that keeps a node's private key out of every client URI and API response."""
    spec = KeySpec(
        name="private_key",
        kind=KeyKind.X25519_KEYPAIR,
        scope=KeyScope.NODE,
        public_name="public_key",
    )
    minted = keymaterial.mint([spec], KeyScope.NODE)

    assert "private_key" in minted.secrets
    assert "private_key" not in minted.params, "the private key landed in plain parameters"
    assert "public_key" in minted.params


def test_a_keypair_without_a_declared_public_name_is_refused() -> None:
    """Otherwise the public half is generated and then unreachable by any renderer."""
    with pytest.raises(keymaterial.UnsupportedKeyKind):
        keymaterial.mint(
            [KeySpec(name="k", kind=KeyKind.X25519_KEYPAIR, scope=KeyScope.NODE)],
            KeyScope.NODE,
        )


def test_a_non_secret_value_is_not_encrypted() -> None:
    """A Reality short id travels to every user in their URI; encrypting it is wrong."""
    spec = KeySpec(name="short_id", kind=KeyKind.SHORT_ID, scope=KeyScope.NODE, secret=False)
    minted = keymaterial.mint([spec], KeyScope.NODE)
    assert "short_id" in minted.params
    assert not minted.secrets


def test_scope_filtering_keeps_node_and_client_material_apart() -> None:
    """Mixing them would mean re-keying a node every time a user is added."""
    specs = [
        KeySpec(name="node_value", kind=KeyKind.TOKEN_32, scope=KeyScope.NODE),
        KeySpec(name="client_value", kind=KeyKind.UUID4, scope=KeyScope.CLIENT),
    ]

    node_material = keymaterial.mint(specs, KeyScope.NODE)
    client_material = keymaterial.mint(specs, KeyScope.CLIENT)

    assert set(node_material.secrets) == {"node_value"}
    assert set(client_material.secrets) == {"client_value"}


@pytest.mark.parametrize("kind", list(KeyKind))
def test_material_is_never_repeated(kind: KeyKind) -> None:
    """Never reuse key material across nodes — the edge rulebook's trap.

    One seized node must reveal nothing about another. 200 draws rather than 2, because
    a generator seeded once per process would pass a two-sample test.
    """
    spec = KeySpec(name="v", kind=kind, scope=KeyScope.NODE, public_name="v_public")
    drawn = set()
    for _ in range(200):
        minted = keymaterial.mint([spec], KeyScope.NODE)
        drawn.add(minted.secrets.get("v") or minted.params.get("v"))
    assert len(drawn) == 200, f"{kind}: only {len(drawn)} distinct values in 200 draws"


def test_short_id_is_hex_a_transport_will_accept() -> None:
    """Reality short ids are hex; a non-hex one is rejected by the daemon at load."""
    spec = KeySpec(name="short_id", kind=KeyKind.SHORT_ID, scope=KeyScope.NODE, secret=False)
    value = keymaterial.mint([spec], KeyScope.NODE).params["short_id"]
    assert len(value) == 8
    int(value, 16)  # raises if it is not hex


def test_every_installed_transports_declaration_can_actually_be_minted() -> None:
    """The integration point: what each shipped transport asks for, we can produce.

    Parametrised over the registry, so a transport declaring material this control
    plane cannot make fails here — at test time — rather than the first time the owner
    tries to enable it on a node.
    """
    for name, meta in discover().items():
        for scope in (KeyScope.NODE, KeyScope.CLIENT):
            minted = keymaterial.mint(meta.key_material, scope)
            expected = {spec.name for spec in meta.key_material if spec.scope is scope}
            produced = set(minted.params) | set(minted.secrets)
            assert expected <= produced, (
                f"{name}: declared {sorted(expected)} at {scope}, produced {sorted(produced)}"
            )


def test_rotation_produces_different_material() -> None:
    """Item 23's premise: rotating must actually change what users are using."""
    specs = [
        KeySpec(
            name="private_key",
            kind=KeyKind.X25519_KEYPAIR,
            scope=KeyScope.NODE,
            public_name="public_key",
        )
    ]
    first = keymaterial.mint(specs, KeyScope.NODE)
    second = keymaterial.rotate(specs, KeyScope.NODE)
    assert first.secrets["private_key"] != second.secrets["private_key"]
