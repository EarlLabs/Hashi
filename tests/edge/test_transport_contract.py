"""The transport profile contract, asserted against every installed transport.

WHAT: the rules in the edge rulebook's contract table, checked for each discovered
      transport rather than for a named one.
WHY:  this is the file that makes the charter's fourth criterion enforceable
      instead of aspirational. Every test here is parametrised over
      ``discover()``, so a new transport package is automatically held to the
      contract — nobody has to remember to add it to a list, and a transport that
      quietly breaks the shape fails on the day it lands.
HOW:  pure imports and pure calls. No Docker, no database, no upstream binary
      (that is ``test_upstream_validation.py``).
"""

import json

import pytest
from pydantic import ValidationError

from edge.registry import (
    ClientEntry,
    KeyKind,
    KeyScope,
    TransportMeta,
    discover,
    profile,
)

INSTALLED = sorted(discover())

# Every transport shipped today must be discoverable. An empty registry used to be
# a passing test (the scaffold had no transports), and the backlog names the
# consequence: item 7 and item 8's scenarios would go green vacuously against a
# registry with nothing in it. This is the assertion that closes that hole.
def test_registry_is_not_empty() -> None:
    """A registry with nothing in it makes every downstream test vacuous."""
    assert INSTALLED, (
        "no transports discovered — every subscription and node scenario "
        "downstream of this would pass against an empty fleet"
    )


@pytest.mark.parametrize("name", INSTALLED)
def test_meta_is_well_formed(name: str) -> None:
    """Name, family, port range: the metadata `control` is allowed to read."""
    meta = discover()[name]
    assert isinstance(meta, TransportMeta)
    assert meta.name == name
    assert meta.family, f"{name}: no protocol family declared"
    low, high = meta.port_range
    assert 1 <= low <= high <= 65535, f"{name}: nonsensical port range {meta.port_range}"


@pytest.mark.parametrize("name", INSTALLED)
def test_port_range_is_enforced_not_merely_declared(name: str) -> None:
    """A declared range that nothing checks is a comment."""
    meta = discover()[name]
    low, high = meta.port_range
    assert meta.clamp_port(low) == low
    with pytest.raises(ValueError):
        meta.clamp_port(low - 1)
    if high < 65535:
        with pytest.raises(ValueError):
            meta.clamp_port(high + 1)


@pytest.mark.parametrize("name", INSTALLED)
def test_key_material_uses_only_the_shared_vocabulary(name: str) -> None:
    """The one assertion that keeps `control` ignorant of protocol names.

    If a transport could invent its own key kind, `control` would need a branch to
    generate it, and that branch would be a branch on the protocol. So the kinds
    are a closed enum, and every declaration has to be a member of it.
    """
    for spec in discover()[name].key_material:
        assert isinstance(spec.kind, KeyKind), f"{name}: {spec.kind!r} is not a KeyKind"
        assert isinstance(spec.scope, KeyScope)
        assert spec.name, f"{name}: a key spec with no parameter name"


@pytest.mark.parametrize("name", INSTALLED)
def test_every_transport_needs_a_per_client_secret(name: str) -> None:
    """Charter criterion 6 is only expressible with client-scoped material.

    If a transport's only material were node-scoped, every friend on that node
    would share one credential — and revoking one friend would mean re-keying
    everyone else, or not revoking at all.
    """
    scopes = {spec.scope for spec in discover()[name].key_material}
    assert KeyScope.CLIENT in scopes, (
        f"{name}: no client-scoped key material, so one friend cannot be revoked "
        "without affecting the others"
    )


@pytest.mark.parametrize("name", INSTALLED)
def test_profile_exposes_both_renderers(name: str) -> None:
    """``profile()`` resolves a transport by its declared name, not its directory."""
    transport = profile(name)
    assert callable(transport.profile.render_server)
    assert callable(transport.profile.render_client)
    assert transport.meta.name == name


def test_unknown_transport_raises_rather_than_returning_none(name: str = "no-such") -> None:
    """A missing transport must not degrade into a node configured with nothing."""
    with pytest.raises(KeyError):
        profile(name)


# --- rendering, for every transport -----------------------------------------

def params_for(name: str, request: pytest.FixtureRequest) -> dict[str, object]:
    """The frozen parameter set for one transport, from conftest.

    Indirection through the fixture name keeps the per-transport literals in one
    file (conftest) while these tests stay parametrised over the registry.
    """
    fixture = {"vless-reality": "reality_params", "vless-ws-tls": "ws_params"}[name]
    return request.getfixturevalue(fixture)


@pytest.mark.parametrize("name", INSTALLED)
def test_params_validate_and_reject_extra_keys(name: str, request) -> None:
    """Validation is owned by the transport, and it is strict.

    ``extra="forbid"`` matters more than it looks: a mistyped knob that is silently
    ignored produces a node configured with the DEFAULT for the thing the operator
    thought they had just set, and nothing anywhere reports it.
    """
    transport = profile(name)
    validated = transport.validate(params_for(name, request))
    assert validated["port"] == params_for(name, request)["port"]
    with pytest.raises(ValidationError):
        transport.validate({**params_for(name, request), "unexpected_knob": "x"})


@pytest.mark.parametrize("name", INSTALLED)
def test_params_reject_a_port_outside_the_declared_range(name: str, request) -> None:
    """The range in META is enforced through the transport's own model too."""
    transport = profile(name)
    below = transport.meta.port_range[0] - 1
    with pytest.raises(ValidationError):
        transport.validate({**params_for(name, request), "port": below})


@pytest.mark.parametrize("name", INSTALLED)
def test_render_server_is_deterministic(name: str, node, credentials, request) -> None:
    """Identical inputs, identical bytes — core invariants §3, "rendering is idempotent".

    Not a style check: drift detection on a node is a byte comparison against a
    re-render, so a renderer that reorders a dict or stamps a timestamp makes
    every node look permanently drifted and the alarm gets ignored.
    """
    transport = profile(name)
    validated = transport.validate(params_for(name, request))
    first = transport.profile.render_server(node, validated, credentials)
    second = transport.profile.render_server(node, validated, credentials)
    assert first == second


@pytest.mark.parametrize("name", INSTALLED)
def test_render_server_emits_valid_json(name: str, node, credentials, request) -> None:
    """Both transports render Xray configs, which are JSON documents.

    Parsing is the cheap half of validation and needs no binary; the expensive
    half — does the daemon accept it — is ``test_upstream_validation.py``.
    """
    transport = profile(name)
    validated = transport.validate(params_for(name, request))
    document = json.loads(transport.profile.render_server(node, validated, credentials))
    assert document["inbounds"][0]["port"] == validated["port"]


@pytest.mark.parametrize("name", INSTALLED)
def test_rendered_server_never_enables_a_record_of_who_connected(
    name: str, node, credentials, request
) -> None:
    """The charter's one unforgivable record, asserted in the rendered bytes.

    Checked on the OUTPUT rather than by reading the template, because a template
    is not what runs on a node — the rendered file is. Two settings matter: Xray's
    access log must be "none" (omitting the key sends it to stdout, and the
    container log is on disk), and sniffing must be off (it exists to extract the
    destination hostname from a client's traffic).
    """
    transport = profile(name)
    validated = transport.validate(params_for(name, request))
    document = json.loads(transport.profile.render_server(node, validated, credentials))
    assert document["log"]["access"] == "none", f"{name}: Xray access log is not disabled"
    for inbound in document["inbounds"]:
        assert inbound.get("sniffing", {}).get("enabled") is False, (
            f"{name}: sniffing is enabled — that is a DNS record of who went where"
        )


@pytest.mark.parametrize("name", INSTALLED)
def test_render_server_authorises_exactly_the_given_clients(
    name: str, node, credentials, request
) -> None:
    """Revocation is re-rendering. The client list must follow its input exactly."""
    transport = profile(name)
    validated = transport.validate(params_for(name, request))

    everyone = json.loads(transport.profile.render_server(node, validated, credentials))
    ids = {client["id"] for client in everyone["inbounds"][0]["settings"]["clients"]}
    assert ids == {c.subject for c in credentials}

    # One friend removed — the whole point of the fan-out in item 9.
    remaining = json.loads(
        transport.profile.render_server(node, validated, credentials[:1])
    )
    left = {client["id"] for client in remaining["inbounds"][0]["settings"]["clients"]}
    assert left == {credentials[0].subject}
    assert credentials[1].subject not in remaining["inbounds"][0]["settings"]["clients"][0]["id"]


@pytest.mark.parametrize("name", INSTALLED)
def test_render_server_with_no_clients_is_valid_and_authorises_nobody(
    name: str, node, request
) -> None:
    """A node with no friends yet is a real state, not an error."""
    transport = profile(name)
    validated = transport.validate(params_for(name, request))
    document = json.loads(transport.profile.render_server(node, validated, ()))
    assert document["inbounds"][0]["settings"]["clients"] == []


@pytest.mark.parametrize("name", INSTALLED)
def test_render_client_returns_a_labelled_entry(name: str, node, credentials, request) -> None:
    """The ``ClientEntry`` contract: finished text plus protocol-agnostic metadata."""
    transport = profile(name)
    validated = transport.validate(params_for(name, request))
    entry = transport.profile.render_client(node, validated, credentials[0])

    assert isinstance(entry, ClientEntry)
    assert entry.node_id == node.id
    assert entry.country_label == node.location_label
    assert entry.display_label
    assert entry.entry.startswith("vless://")
    # The friend's own credential must be in there, or the entry authorises nobody.
    assert credentials[0].subject in entry.entry


@pytest.mark.parametrize("name", INSTALLED)
def test_client_entry_carries_no_display_fragment(name: str, node, credentials, request) -> None:
    """Labelling belongs to `control`, once, for every scheme in the format.

    If a transport appended its own fragment, `control` appending the shared one
    would produce two — and the charter's "pick an exit country" behaviour would
    be implemented once per protocol instead of once.
    """
    transport = profile(name)
    validated = transport.validate(params_for(name, request))
    entry = transport.profile.render_client(node, validated, credentials[0])
    assert "#" not in entry.entry, f"{name}: render_client appended a fragment itself"


@pytest.mark.parametrize("name", INSTALLED)
def test_client_entry_never_leaks_the_server_private_key(
    name: str, node, credentials, request
) -> None:
    """A client entry goes to a friend's device. Node secrets must not ride along.

    The public half is supposed to be there (Reality's `pbk`); the private half
    would hand every friend the ability to impersonate the node.
    """
    transport = profile(name)
    validated = transport.validate(params_for(name, request))
    entry = transport.profile.render_client(node, validated, credentials[0])
    private = validated.get("private_key")
    if private:
        assert private not in entry.entry, f"{name}: the node's private key is in a client URI"


@pytest.mark.parametrize("name", INSTALLED)
def test_two_friends_get_different_entries(name: str, node, credentials, request) -> None:
    """Shared entries would make individual revocation impossible."""
    transport = profile(name)
    validated = transport.validate(params_for(name, request))
    first = transport.profile.render_client(node, validated, credentials[0])
    second = transport.profile.render_client(node, validated, credentials[1])
    assert first.entry != second.entry
