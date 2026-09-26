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

import ast
import inspect
import json
from dataclasses import replace

import pytest
from pydantic import ValidationError

from edge.registry import (
    SERIALISERS,
    ClientConfig,
    ClientEntry,
    ConfigFormat,
    ContractViolation,
    Datapath,
    FormatNotDeclared,
    KeyKind,
    KeyScope,
    Layer4,
    SubscriptionFormat,
    TransportMeta,
    discover,
    profile,
)

INSTALLED = sorted(discover())


# Transports that CAN appear in a v1 subscription. The client-entry assertions apply
# only to these — a transport declaring itself inexpressible is required to refuse, and
# that refusal has its own test rather than being an exception inside the shared ones.
DELIVERABLE = sorted(name for name, meta in discover().items() if meta.subscription_expressible)

# The credentials fixture differs per transport family: the WireGuard family needs a
# peer keypair in ``Credential.secrets``, which VLESS has no use for.


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
    # What its listener BINDS, which is a different question from the family above and
    # the only one `control` decides anything with: whether two transports on one node
    # may hold the same port number (M15, ``control/app/services/placement.py``). A
    # transport declaring none would be read as colliding with nothing, and the pair
    # would be found by a container that cannot bind.
    assert meta.listens_on, f"{name}: does not declare what its listener binds"
    assert all(isinstance(layer, Layer4) for layer in meta.listens_on), (
        f"{name}: listens_on must hold Layer4 members, got {meta.listens_on!r}"
    )
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

    If a transport's only material were node-scoped, every user on that node
    would share one credential — and revoking one user would mean re-keying
    everyone else, or not revoking at all.
    """
    scopes = {spec.scope for spec in discover()[name].key_material}
    assert KeyScope.CLIENT in scopes, (
        f"{name}: no client-scoped key material, so one user cannot be revoked "
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
    return request.getfixturevalue("transport_fixture")(name, "params")


def clients_for(name: str, request: pytest.FixtureRequest) -> list:
    """The credentials appropriate to this transport's family.

    The WireGuard family needs a peer keypair in ``Credential.secrets``; VLESS has no
    use for one. Both are just ``Credential`` as far as the contract is concerned.
    """
    return request.getfixturevalue("transport_fixture")(name, "credentials")


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
    # Both WireGuard-family formats are the same INI shape: one PublicKey per peer.
    if meta.config_format in (ConfigFormat.WG_QUICK, ConfigFormat.WG_QUICK_PLAIN):
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
    """A node with no users yet — or whose last user was just revoked — is a real state."""
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
def test_a_rendered_config_never_names_a_user(name: str, node, request) -> None:
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
    """A client entry goes to a user's device. Node secrets must not ride along."""
    transport = profile(name)
    validated = transport.validate(params_for(name, request))
    entry = transport.profile.render_client(node, validated, clients_for(name, request)[0])
    private = validated.get("private_key")
    if private:
        assert private not in entry.entry, f"{name}: the node's private key is in a client URI"


@pytest.mark.parametrize("name", DELIVERABLE)
def test_two_users_get_different_entries(name: str, node, request) -> None:
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
    a user's subscription their client cannot parse, and the symptom would be "the
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


# --- what a transport declares it serialises into, and produces (item 26) -----
#
# The contract used to carry one boolean: "expressible in the v1 subscription, yes or
# no". For every transport that is not a URI the answer was no, and "no" was the end of
# the conversation — which is precisely what kept AmneziaWG's user-facing form
# unbuildable rather than merely undelivered (backlog item 25). A transport now declares
# the SET of shapes it produces, and the assertions below are about the two halves of
# that: the declaration means something, and it obliges something.

CONFIG_FILE_TRANSPORTS = sorted(
    name
    for name, meta in discover().items()
    if SubscriptionFormat.CLIENT_CONFIG_FILE in meta.subscription_formats
)


@pytest.mark.parametrize("name", INSTALLED)
def test_declared_formats_come_from_the_shared_vocabulary(name: str) -> None:
    """A free-form string here would be a format `control` could never dispatch on."""
    meta = discover()[name]
    for declared in meta.subscription_formats:
        assert isinstance(declared, SubscriptionFormat), (
            f"{name}: {declared!r} is not a SubscriptionFormat, so delivery has "
            "nothing to dispatch on but the transport's name"
        )
        assert declared in SERIALISERS, f"{name}: no serialiser is mapped for {declared!r}"


@pytest.mark.parametrize("name", INSTALLED)
def test_every_declared_format_has_the_function_that_produces_it(name: str) -> None:
    """``profile()`` is where a declaration that obliges nothing is caught.

    Loading the transport is itself the assertion: ``profile()`` refuses a package whose
    render module does not provide the serialiser for a format it declared. Asserted
    per transport rather than once, so a package added later cannot skip it.
    """
    transport = profile(name)
    for declared in transport.meta.subscription_formats:
        assert callable(getattr(transport.profile, SERIALISERS[declared]))


@pytest.mark.parametrize("name", INSTALLED)
def test_expressibility_is_derived_from_the_declared_formats(name: str) -> None:
    """The name `control` has been reading since item 7 still means what it meant.

    ``subscription_expressible`` is now a property over the format set. It has to keep
    answering exactly "does this ride in the v1 URI list" — if it drifted into "is this
    deliverable at all", the panel would start offering a transport whose delivery does
    not exist yet, and a user would get a subscription one node short with nothing
    saying so.
    """
    meta = discover()[name]
    assert meta.subscription_expressible == (
        SubscriptionFormat.V1_URI_LIST in meta.subscription_formats
    )


@pytest.mark.parametrize("name", INSTALLED)
def test_a_format_the_transport_never_declared_is_refused(name: str, node, request) -> None:
    """Not "call whatever function happens to exist".

    A transport may grow a serialiser before the fleet is ready to offer it in that
    shape — that is exactly AmneziaWG's position between items 26 and 27 — and the
    declaration is what says it is ready. Dispatching on the presence of a function
    instead would make an unfinished serialiser reachable by accident.
    """
    transport = profile(name)
    validated = transport.validate(params_for(name, request))
    credential = clients_for(name, request)[0]
    undeclared = set(SubscriptionFormat) - transport.meta.subscription_formats
    for subscription_format in sorted(undeclared):
        with pytest.raises(FormatNotDeclared):
            transport.serialise(subscription_format, node, validated, credential)


@pytest.mark.parametrize("name", INSTALLED)
def test_serialise_returns_what_the_declared_format_promises(
    name: str, node, request
) -> None:
    """The dispatch produces the container the format is defined in terms of."""
    expected = {
        SubscriptionFormat.V1_URI_LIST: ClientEntry,
        SubscriptionFormat.CLIENT_CONFIG_FILE: ClientConfig,
    }
    transport = profile(name)
    validated = transport.validate(params_for(name, request))
    credential = clients_for(name, request)[0]
    for declared in sorted(transport.meta.subscription_formats):
        produced = transport.serialise(declared, node, validated, credential)
        assert isinstance(produced, expected[declared]), (
            f"{name}: {declared!r} produced {type(produced).__name__}"
        )


def test_a_package_that_declares_a_format_it_cannot_produce_is_refused() -> None:
    """The load-time refusal, provoked rather than assumed.

    Every installed transport keeps its declaration today, so the check above passes
    vacuously with respect to the FAILURE. This provokes the failure directly, because
    the value of the check is entirely in what it rejects — and what it rejects is the
    worst shape available: a transport that looks deliverable in the panel and raises
    an AttributeError deep inside one user's subscription render at refresh time.
    """
    from types import SimpleNamespace

    from edge.registry import _check_contract

    transport = profile(INSTALLED[0])
    meta = replace(
        transport.meta,
        subscription_formats=frozenset(
            {SubscriptionFormat.V1_URI_LIST, SubscriptionFormat.CLIENT_CONFIG_FILE}
        ),
    )
    with pytest.raises(ContractViolation) as refused:
        _check_contract(meta, SimpleNamespace(render_server=lambda: None,
                                              render_client=lambda: None),
                        transport.params_model)
    # The message has to name the missing symbol, or it is a puzzle rather than a report.
    assert "render_client_config" in str(refused.value)


def test_a_transport_whose_pool_names_a_field_its_params_lack_is_refused() -> None:
    """The other half of the same load-time check — M17.

    ``PeerAddress`` names two PARAMETERS, and a name the model does not have is a pool
    whose bounds nothing can read: `control` would size it against a field that is not
    there, and every user would be allocated an address out of nowhere. Checked against
    the loaded model rather than at discovery, because ``meta.py`` alone cannot see it.
    """
    from types import SimpleNamespace

    from edge.registry import PeerAddress, _check_contract

    transport = profile(INSTALLED[0])
    real_field = next(iter(transport.params_model.model_fields))
    meta = replace(
        transport.meta,
        subscription_formats=frozenset(),
        peer_address=PeerAddress(name="no_such_field", within=real_field),
    )
    with pytest.raises(ContractViolation) as refused:
        _check_contract(meta, SimpleNamespace(), transport.params_model)
    assert "no_such_field" in str(refused.value)


@pytest.mark.parametrize("name", CONFIG_FILE_TRANSPORTS)
def test_a_client_config_file_is_complete_and_named(name: str, node, request) -> None:
    """The metadata `control` needs in order to hand a file over generically."""
    transport = profile(name)
    validated = transport.validate(params_for(name, request))
    produced = transport.profile.render_client_config(
        node, validated, clients_for(name, request)[0]
    )

    assert produced.content.strip(), f"{name}: an empty config file is not a config file"
    assert produced.media_type, f"{name}: no media type, so delivery has to guess"
    # A plain name: it reaches an HTTP header and a user's filesystem, and one family
    # derives the interface name from it and rejects a name it considers invalid.
    assert produced.safe_filename() == produced.filename
    assert produced.node_id == node.id
    assert produced.country_label == node.location_label


@pytest.mark.parametrize("name", CONFIG_FILE_TRANSPORTS)
def test_a_client_config_file_never_carries_the_servers_private_key(
    name: str, node, request
) -> None:
    """The same rule as for a client entry, and it matters more in a file.

    A file is saved, synced and forwarded. The node's own private key in it would be a
    seizure of one user's phone compromising the node for everybody on it.
    """
    transport = profile(name)
    raw = params_for(name, request)
    validated = transport.validate(raw)
    produced = transport.profile.render_client_config(
        node, validated, clients_for(name, request)[0]
    )
    assert str(raw["private_key"]) not in produced.content


@pytest.mark.parametrize("name", CONFIG_FILE_TRANSPORTS)
def test_two_users_get_different_config_files(name: str, node, request) -> None:
    """Otherwise one revocation cannot be told from another, and neither is total."""
    transport = profile(name)
    validated = transport.validate(params_for(name, request))
    clients = clients_for(name, request)
    first, second = (
        transport.profile.render_client_config(node, validated, credential).content
        for credential in clients[:2]
    )
    assert first != second


@pytest.mark.parametrize("name", CONFIG_FILE_TRANSPORTS)
def test_rendering_a_config_file_is_deterministic(name: str, node, request) -> None:
    """Purity, asserted where it is easiest to lose: a file with more lines to drift."""
    transport = profile(name)
    validated = transport.validate(params_for(name, request))
    credential = clients_for(name, request)[0]
    render_once = transport.profile.render_client_config(node, validated, credential)
    render_again = transport.profile.render_client_config(node, validated, credential)
    assert render_once == render_again


def test_a_filename_with_a_path_component_is_refused() -> None:
    """Refused rather than silently stripped, so the mistake is readable.

    A transport is trusted code in this image, so this is not a defence against a
    hostile package — it is a defence against a plausible mistake reaching an HTTP
    header and a user's filesystem.
    """
    for bad in ("../etc/passwd", "sub/dir.conf", "", ".", ".."):
        with pytest.raises(ValueError):
            ClientConfig(
                content="x", filename=bad, media_type="text/plain",
                display_label="l", country_label="c", node_id="n",
            ).safe_filename()


# --- the two constraints the charter puts on a transport, as contract fields ---
# (backlog item 28)

@pytest.mark.parametrize("name", INSTALLED)
def test_a_transport_the_censor_identifies_is_never_allowed_on_a_hop(name: str) -> None:
    """The one implication between the two new declarations, asserted rather than trusted.

    ``blocked_by_inspection`` and ``hop_capable`` are independent fields, and for one
    combination that independence is wrong: a protocol a filtering network identifies
    must never be allowed to carry the entry-to-leaf hop, because that hop crosses
    exactly such a network by definition. A package declaring both True would compile,
    read plausibly, and hand the fleet a topology that cannot come up.

    Asserted over the registry rather than about one transport, so it holds for the next
    package too.
    """
    meta = discover()[name]
    if meta.blocked_by_inspection:
        assert not meta.hop_capable, (
            f"{name} declares that a filtering network identifies it AND that it may "
            "carry an entry-to-leaf hop. That hop crosses such a network, so this "
            "combination configures both nodes correctly and never forms a tunnel."
        )


@pytest.mark.parametrize("name", INSTALLED)
def test_each_config_format_has_a_data_plane_that_can_run_it(name: str) -> None:
    """A rendered config nothing is pinned to run is a node that boots without a daemon.

    The pin lives with the transport's FORMAT (``edge/bootstrap/node_stack.py``), so a
    transport declaring a format with no data plane is a KeyError at apply time — on the
    node, after the operator was told the transport was enabled. That the pinned tags
    actually EXIST is a separate question, asked against a real registry in
    ``tests/e2e/edge/test_every_image_pin_resolves.py``.
    """
    from edge.bootstrap.node_stack import DATA_PLANES

    meta = discover()[name]
    assert meta.config_format in DATA_PLANES, (
        f"{name} renders {meta.config_format!r} and nothing is pinned to run it"
    )
    assert DATA_PLANES[meta.config_format].image


# --- what a transport does with what it decrypts, as a contract field (M25) -----

def _egress_expression(transport_name: str) -> str:
    """Which of ``edge.egress``'s two expressions this transport's renderer calls.

    Read off the render module's imports rather than off the declaration, because the
    declaration is the thing under test. The two are one fact seen from two sides: a
    package that calls ``wg_quick_egress`` hands what it decrypts to the node's kernel,
    and one that calls ``exit_origin`` terminates the consumer's connection and opens its
    own from the address the policy names.

    PARSED RATHER THAN SCANNED. Both WireGuard-family render modules explain at length
    why they are not the other kind, and both name the other function while doing it — so
    a substring search over the source reads a docstring as an import and reports the
    opposite answer with total confidence.
    """
    tree = ast.parse(inspect.getsource(profile(transport_name).profile))
    imported = {
        alias.name
        for statement in ast.walk(tree)
        if isinstance(statement, ast.ImportFrom) and statement.module == "edge.egress"
        for alias in statement.names
    }
    kernel = "wg_quick_egress" in imported
    re_originating = "exit_origin" in imported
    assert kernel != re_originating, (
        f"{transport_name}'s renderer imports neither of edge.egress's two expressions "
        f"of one policy, or both — it imports {sorted(imported)} — so there is no fact "
        "for its declaration to be checked against"
    )
    return Datapath.KERNEL_ROUTED if kernel else Datapath.RE_ORIGINATING


@pytest.mark.parametrize("name", INSTALLED)
def test_the_declared_datapath_is_the_one_the_renderer_expresses(name: str) -> None:
    """A package's ``datapath`` against what its own render module actually does — M25.

    This is the assertion that makes the declaration worth reading. `control` refuses two
    operations on the strength of it — offering this transport to the users of a node
    that dials a hop, and giving such a node a hop — and a package whose declaration
    disagreed with its renderer would move that refusal onto the wrong transport in
    whichever direction it lied: a kernel tunnel claiming to re-originate is accepted at
    every door and refused at the apply, which is the exact defect the field found, and a
    proxy claiming the opposite is refused an arrangement that has been measured carrying
    traffic.

    The default is the restrictive answer, so a package that simply forgets fails only in
    the safe direction — and fails HERE, at once, rather than on an operator's dialog.
    """
    assert discover()[name].datapath == _egress_expression(name), (
        f"{name} declares datapath={discover()[name].datapath!r} and its renderer "
        f"expresses {_egress_expression(name)!r}"
    )


@pytest.mark.parametrize("name", INSTALLED)
def test_only_a_re_originating_transport_may_carry_users_through_a_hop(name: str) -> None:
    """The derived answer `control` reads, pinned to the declaration it comes from.

    Derived in ``edge`` and asked there by both doors, so that neither service holds an
    opinion about what a data plane can do. Asserted rather than assumed because the
    property is what two refusals are written against, and a property that quietly became
    ``True`` for everything would take both of them off without failing anything else.
    """
    meta = discover()[name]
    assert meta.serves_users_through_a_hop == (
        meta.datapath is Datapath.RE_ORIGINATING
    )
