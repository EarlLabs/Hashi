"""A pre-shared key belongs to a PAIR, not to a node — M23.

WHAT: which pre-shared key each consumer of a WireGuard-family transport is given, in
      the node's own config and in the file the friend imports.
WHY:  measured on the owner's real leaf on 2026-09-14, with two real clients connected:

          $ grep -c '^PresharedKey' /opt/hashi/conf/amneziawg.conf           -> 2
          $ grep '^PresharedKey' ... | sort -u | wc -l                       -> 1

      Two friends' configs differed only in private key and address. So one friend's
      leaked file exposed the symmetric layer protecting every other friend's handshake
      on that node, and revoking that friend rotated nothing — the one thing a pre-shared
      key is there to do, undone by the field being node-scoped.

      Nothing in a stand could see it: both configs are valid, both tunnels come up, both
      carry traffic. It is only visible by comparing two friends' files, which is what
      this module does.
HOW:  pure renders over the family DERIVED from what a transport declares — the set that
      serialises a friend's material into a config FILE — so a third member is held to
      this by arriving rather than by being listed. Never a hardcoded transport name.

What this does NOT prove is that the daemon rejects a mismatched pair; that is upstream's
own behaviour and is exercised by the validation tests when the binary is present.
"""

import dataclasses

import pytest

from edge.node import Credential
from edge.registry import KeyScope, SubscriptionFormat, discover, profile

# The transports that hand a friend a whole configuration file, derived the way
# tests/edge/test_golden_configs.py derives it. Deliberately NOT derived from "declares a
# per-pair key", which would be circular: a transport that dropped the declaration would
# drop out of this file's parameters and take its own failure with it.
CONFIG_FILE_TRANSPORTS = sorted(
    name
    for name, meta in discover().items()
    if SubscriptionFormat.CLIENT_CONFIG_FILE in meta.subscription_formats
)

# The parameter name a per-consumer pre-shared key arrives under. One place, because two
# spellings of it here would be a test that passes while the renderer reads nothing.
PER_PAIR = "peer_preshared_key"

DIRECTIVE = "PresharedKey = "


def preshared_keys(config: str) -> list[str]:
    """Every ``PresharedKey`` value in a rendered config, in the order it renders them."""
    return [
        line[len(DIRECTIVE):]
        for line in config.splitlines()
        if line.startswith(DIRECTIVE)
    ]


def rendered_pair(name: str, request):
    """One transport's validated parameters and its two fixture consumers."""
    transport = profile(name)
    fixture = request.getfixturevalue("transport_fixture")
    return (
        transport,
        transport.validate(fixture(name, "params")),
        list(fixture(name, "credentials")),
    )


@pytest.mark.parametrize("name", CONFIG_FILE_TRANSPORTS)
def test_the_transport_declares_a_pre_shared_key_per_consumer(name: str) -> None:
    """The declaration is what makes the rest of this possible, so it is asserted first.

    `control` mints from ``key_material`` and knows nothing else; a key declared at NODE
    scope is one value for the whole node however carefully the templates are written,
    and a key declared nowhere is one `control` never mints at all.
    """
    specs = {spec.name: spec for spec in profile(name).meta.key_material}

    assert PER_PAIR in specs, f"{name} declares no per-consumer pre-shared key"
    assert specs[PER_PAIR].scope is KeyScope.CLIENT
    assert specs[PER_PAIR].secret, "a pre-shared key that is not stored encrypted"


@pytest.mark.parametrize("name", CONFIG_FILE_TRANSPORTS)
def test_two_friends_on_one_node_hold_two_different_keys(name: str, node, request) -> None:
    """The grep from the walk, run against the bytes this project renders.

    Two peers, two ``PresharedKey`` lines, two distinct values — and neither of them the
    node's own, because the node's own is the value every friend used to be handed.
    """
    transport, params, credentials = rendered_pair(name, request)
    config = transport.profile.render_server(node, params, credentials)

    keys = preshared_keys(config)
    assert len(keys) == len(credentials), keys
    assert len(set(keys)) == len(keys), f"{name}: two peers share a pre-shared key: {keys}"
    assert params["preshared_key"] not in keys, (
        f"{name}: a peer was authorised with the NODE's own pre-shared key, which every "
        "other peer on it would also hold"
    )


@pytest.mark.parametrize("name", CONFIG_FILE_TRANSPORTS)
def test_a_friends_own_file_carries_only_their_own_key(name: str, node, request) -> None:
    """And the pair agrees, which is the half that makes the tunnel come up at all.

    Asserted together on purpose: a per-peer key on the node and a shared one in the file
    would be two friends who cannot connect, and a shared one on the node with per-peer
    ones in the files would be two friends who can, both with the wrong key. The property
    is that the value in each friend's file is exactly the value their own peer block
    names, and nobody else's.
    """
    transport, params, credentials = rendered_pair(name, request)
    on_the_node = preshared_keys(transport.profile.render_server(node, params, credentials))

    in_the_files = [
        preshared_keys(transport.profile.render_client_config(node, params, credential).content)
        for credential in credentials
    ]

    assert all(len(keys) == 1 for keys in in_the_files), in_the_files
    assert [keys[0] for keys in in_the_files] == on_the_node


@pytest.mark.parametrize("name", CONFIG_FILE_TRANSPORTS)
def test_revoking_one_friend_takes_their_key_with_them(name: str, node, request) -> None:
    """The half the finding names as the cost: *revoking that friend does not rotate it*.

    With one shared value that sentence was true — the removed friend's copy went on
    protecting nothing, because it was everyone's. With a key per pair, the node stops
    naming it the moment the credential is gone, and the friend who stayed is untouched:
    no re-import, which is the charter's promise about their device.
    """
    transport, params, credentials = rendered_pair(name, request)
    before = transport.profile.render_server(node, params, credentials)
    kept = credentials[1:]

    after = transport.profile.render_server(node, params, kept)

    gone = preshared_keys(before)[0]
    assert gone not in after, f"{name}: a revoked consumer's pre-shared key is still named"
    assert preshared_keys(after) == preshared_keys(before)[1:], (
        "the friends who stayed were given a different key by someone else's revocation"
    )


@pytest.mark.parametrize("name", CONFIG_FILE_TRANSPORTS)
def test_a_credential_without_one_is_refused_a_file(name: str, node, request) -> None:
    """Refused rather than filled in from the node's key, which is the defect itself.

    A credential minted before the per-pair declaration existed carries none, and its
    friend's device holds a file naming the node's key. The node goes on authorising them
    — ``render_server`` falls back, so they are not cut off by an apply — but issuing that
    shared key AGAIN is the thing being stopped, so the download is where it stops. The
    message has to name the material, because the fix is to rotate this credential and
    nothing about the node.
    """
    transport, params, credentials = rendered_pair(name, request)
    legacy = dataclasses.replace(
        credentials[0],
        secrets={
            key: value
            for key, value in credentials[0].secrets.items()
            if key != PER_PAIR
        },
    )

    with pytest.raises(Exception) as refusal:
        transport.profile.render_client_config(node, params, legacy)

    assert PER_PAIR in str(refusal.value)


@pytest.mark.parametrize("name", CONFIG_FILE_TRANSPORTS)
def test_the_node_still_authorises_a_credential_minted_before_the_declaration(
    name: str, node, request
) -> None:
    """The deliberate asymmetry, asserted so it cannot be tidied away by accident.

    A friend whose file already names the node's key must keep connecting until they are
    re-issued; if the node's config refused to render over them, the next apply would cut
    off every friend on it — which is a worse outage than the defect. So ``render_server``
    falls back and ``render_client_config`` does not.
    """
    transport, params, credentials = rendered_pair(name, request)
    legacy = Credential(
        subject=credentials[0].subject,
        secrets={
            key: value
            for key, value in credentials[0].secrets.items()
            if key != PER_PAIR
        },
    )

    config = transport.profile.render_server(node, params, [legacy])

    assert preshared_keys(config) == [params["preshared_key"]]
