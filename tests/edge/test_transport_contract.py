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
    ConfigFormat,
    KeyKind,
    KeyScope,
    TransportMeta,
    discover,
    profile,
)

INSTALLED = sorted(discover())

PARAMS_FIXTURE = {
    "vless-reality": "reality_params",
    "vless-ws-tls": "ws_params",
    "amneziawg": "awg_params",
}

# Transports that CAN appear in a v1 subscription. The client-entry assertions apply
# only to these — a transport declaring itself inexpressible is required to refuse, and
# that refusal has its own test rather than being an exception inside the shared ones.
DELIVERABLE = sorted(name for name, meta in discover().items() if meta.subscription_expressible)

# The credentials fixture differs per transport family: the WireGuard family needs a
# peer keypair in ``Credential.secrets``, which VLESS has no use for.
CREDENTIALS_FIXTURE = {
    "vless-reality": "credentials",
    "vless-ws-tls": "credentials",
    "amneziawg": "awg_credentials",
}


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
#
# The assertions below are FORMAT-AWARE rather than protocol-aware, mirroring the
# production code: ``authorised_subjects`` knows how to read an Xray JSON config and a
# wg-quick config, and nothing here knows which protocol produced either. A transport
# rendering a third format fails on the extractor — loudly, in one place — rather than
# silently passing an assertion that never looked at anything.

def params_for(name: str, request: pytest.FixtureRequest) -> dict[str, object]:
    """The frozen parameter set for one transport, from conftest."""
    return request.getfixturevalue(PARAMS_FIXTURE[name])


def clients_for(name: str, request: pytest.FixtureRequest) -> list:
    """The credentials appropriate to this transport's family.

    The WireGuard family needs a peer keypair in ``Credential.secrets``; VLESS has no
    use for one. Both are just ``Credential`` as far as the contract is concerned.
    """
    return request.getfixturevalue(CREDENTIALS_FIXTURE[name])


def render(name: str, node, request, clients=None) -> str:
    """Validate this transport's parameters and render its server config."""
    transport = profile(name)
    validated = transport.validate(params_for(name, request))
    if clients is None:
        clients = clients_for(name, request)
    return transport.profile.render_server(node, validated, clients)


def authorised_subjects(name: str, config: str) -> set[str]:
    """Who this rendered config lets in, read back out of the config itself.

    Parsed rather than assumed, because "revocation is re-rendering" is only a real
    guarantee if the rendered file is what changes. For the WireGuard family the
    authorised identity is the peer's PUBLIC KEY (that is what the daemon
    authenticates); for Xray it is the client id.
    """
    meta = discover()[name]
    if meta.config_format is ConfigFormat.XRAY_JSON:
        document = json.loads(config)
        return {
            client["id"]
            for inbound in document["inbounds"]
            for client in inbound["settings"]["clients"]
        }
    if meta.config_format is ConfigFormat.WG_QUICK:
        return {
            line.split("=", 1)[1].strip()
            for line in config.splitlines()
            if line.strip().startswith("PublicKey")
        }
    raise AssertionError(
        f"{name} renders {meta.config_format!r}, which this test cannot read. Teach the "
        "extractor about the format rather than exempting the transport."
    )


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
def test_render_server_is_deterministic(name: str, node, request) -> None:
    """Identical inputs, identical bytes — core invariants §3, "rendering is idempotent".

    Not a style check: drift detection on a node is a byte comparison against a
    re-render, so a renderer that reorders a dict or stamps a timestamp makes every node
    look permanently drifted and the alarm gets ignored.
    """
    assert render(name, node, request) == render(name, node, request)


@pytest.mark.parametrize("name", INSTALLED)
def test_render_server_authorises_exactly_the_given_clients(name: str, node, request) -> None:
    """Revocation is re-rendering. The authorised set must follow its input exactly."""
    clients = clients_for(name, request)

    everyone = authorised_subjects(name, render(name, node, request, clients))
    assert len(everyone) == len(clients), (
        f"{name}: rendered {len(everyone)} authorised identities for {len(clients)} clients"
    )

    # One removed — the whole point of the fan-out in item 9.
    remaining = authorised_subjects(name, render(name, node, request, clients[:1]))
    assert len(remaining) == 1
    assert remaining < everyone, f"{name}: dropping a client did not shrink the config"


@pytest.mark.parametrize("name", INSTALLED)
def test_render_server_with_no_clients_authorises_nobody(name: str, node, request) -> None:
    """A node with no friends yet — or whose last friend was just revoked — is a real state."""
    assert authorised_subjects(name, render(name, node, request, [])) == set()


@pytest.mark.parametrize("name", INSTALLED)
def test_rendered_server_never_records_who_connected(name: str, node, request) -> None:
    """The charter's one unforgivable record, asserted in the rendered bytes.

    Checked on the OUTPUT rather than by reading the template, because a template is not
    what runs on a node — the rendered file is. Format-specific because the ways to
    enable logging differ: Xray has an access log and traffic sniffing; the WireGuard
    family has no logging directive at all, and the assertion is that none appeared.
    """
    config = render(name, node, request)
    meta = discover()[name]

    if meta.config_format is ConfigFormat.XRAY_JSON:
        document = json.loads(config)
        assert document["log"]["access"] == "none", f"{name}: Xray access log is not disabled"
        for inbound in document["inbounds"]:
            assert inbound.get("sniffing", {}).get("enabled") is False, (
                f"{name}: sniffing is enabled — that is a DNS record of who went where"
            )
    else:
        lowered = config.lower()
        for directive in ("log", "verbose", "debug"):
            assert directive not in lowered, (
                f"{name}: the rendered config mentions {directive!r}"
            )


@pytest.mark.parametrize("name", INSTALLED)
def test_a_rendered_config_never_names_a_friend(name: str, node, request) -> None:
    """Labels in a node's config are opaque subjects, never nicknames.

    A node can be seized. Anything in a file on it that identifies a person by a name
    the operator would recognise is the record the charter says must not exist.
    """
    config = render(name, node, request)
    for forbidden in ("kolya", "masha", "nickname", "@"):
        assert forbidden not in config.lower(), f"{name}: config contains {forbidden!r}"


# --- the client entry, only for transports that have one ---------------------

@pytest.mark.parametrize("name", DELIVERABLE)
def test_render_client_returns_a_labelled_entry(name: str, node, request) -> None:
    """The ``ClientEntry`` contract: finished text plus protocol-agnostic metadata."""
    transport = profile(name)
    validated = transport.validate(params_for(name, request))
    credential = clients_for(name, request)[0]
    entry = transport.profile.render_client(node, validated, credential)

    assert isinstance(entry, ClientEntry)
    assert entry.node_id == node.id
    assert entry.country_label == node.location_label
    assert entry.display_label
    assert credential.subject in entry.entry, "the entry authorises nobody"


@pytest.mark.parametrize("name", DELIVERABLE)
def test_client_entry_carries_no_display_fragment(name: str, node, request) -> None:
    """Labelling belongs to `control`, once, for every scheme in the format.

    If a transport appended its own fragment, `control` appending the shared one would
    produce two — and the charter's "pick an exit country" behaviour would be
    implemented once per protocol instead of once.
    """
    transport = profile(name)
    validated = transport.validate(params_for(name, request))
    entry = transport.profile.render_client(node, validated, clients_for(name, request)[0])
    assert "#" not in entry.entry, f"{name}: render_client appended a fragment itself"


@pytest.mark.parametrize("name", DELIVERABLE)
def test_client_entry_never_leaks_the_server_private_key(name: str, node, request) -> None:
    """A client entry goes to a friend's device. Node secrets must not ride along."""
    transport = profile(name)
    validated = transport.validate(params_for(name, request))
    entry = transport.profile.render_client(node, validated, clients_for(name, request)[0])
    private = validated.get("private_key")
    if private:
        assert private not in entry.entry, f"{name}: the node's private key is in a client URI"


@pytest.mark.parametrize("name", DELIVERABLE)
def test_two_friends_get_different_entries(name: str, node, request) -> None:
    """Shared entries would make individual revocation impossible."""
    transport = profile(name)
    validated = transport.validate(params_for(name, request))
    clients = clients_for(name, request)
    first = transport.profile.render_client(node, validated, clients[0])
    second = transport.profile.render_client(node, validated, clients[1])
    assert first.entry != second.entry


# --- and for transports that deliberately have none -------------------------

NOT_DELIVERABLE = sorted(set(INSTALLED) - set(DELIVERABLE))


@pytest.mark.parametrize("name", NOT_DELIVERABLE)
def test_an_inexpressible_transport_refuses_loudly(name: str, node, request) -> None:
    """A transport with no URI form must RAISE, not improvise.

    This is the charter's open question answered honestly (amendment A, and the debt
    named when AmneziaWG moved to M4). Emitting something URI-shaped would put a line in
    a friend's subscription their client cannot parse, and the symptom would be "the
    whole subscription is broken" rather than "one entry is unsupported".

    Parametrised over the registry, so it holds for any future transport that declares
    itself inexpressible — and the list being empty would simply mean no such transport
    ships, not that the rule went untested.
    """
    transport = profile(name)
    validated = transport.validate(params_for(name, request))
    with pytest.raises(Exception) as raised:
        transport.profile.render_client(node, validated, clients_for(name, request)[0])
    # The message has to tell an operator what to do, not just fail.
    assert "subscription" in str(raised.value).lower()


@pytest.mark.parametrize("name", NOT_DELIVERABLE)
def test_an_inexpressible_transport_still_renders_a_server_config(
    name: str, node, request
) -> None:
    """It is unusable in a SUBSCRIPTION, not unusable. It runs the entry-to-leaf hop."""
    assert render(name, node, request).strip()
