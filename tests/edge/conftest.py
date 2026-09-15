"""Fixtures for the edge zone's unit and golden-file tests.

WHAT: a fixed node, fixed parameters and fixed credentials for every transport,
      plus the locator for the upstream Xray checker.
WHY:  golden-file tests are only meaningful if their inputs are frozen in one
      place. If each test built its own node, a "golden file changed" failure
      would be ambiguous — did the renderer change, or the input?
HOW:  every value is fake and uses reserved example ranges (RFC 2606 / RFC 5737),
      per the edge rulebook: never a real decoy host, never a real key.
"""

import datetime
import pathlib

import pytest

from edge.node import Credential, NodeView

GOLDEN = pathlib.Path(__file__).parent / "golden"

# RFC 5737 documentation address. Never a real node.
FAKE_ADDRESS = "192.0.2.10"

# A syntactically valid, PUBLICLY KNOWN X25519 test keypair. Safe to commit
# precisely because it is worthless: base64 of 32 zero bytes and its public half
# would be rejected by validation, so these are real-shaped but fixed. A generated
# key here would make every golden file change on every run.
FAKE_PRIVATE_KEY = "wEJ0aXpBQlFtNVFDbEZLTFVqRXFRUlRLZXJhcXZJZ0k"
FAKE_PUBLIC_KEY = "0Rf8h2v0aFVQVGxLZ0VNQmxwQVVCMFJmOGgydjBhRlY"

# RFC 5737 documentation address, standing in for the resolver a node's record names —
# M16, and since M23 the fallback a friend's own config file names when the transport
# sets none (``egress.client_resolvers``). Outside every tunnel range in this file on
# purpose: a resolver inside one is an address some friend's device holds, and the
# renderer refuses it.
FAKE_RESOLVER = "192.0.2.53"


@pytest.fixture
def node() -> NodeView:
    """One fixed node. Reserved addresses, operator-chosen labels."""
    return NodeView(
        id="11111111-1111-4111-8111-111111111111",
        address=FAKE_ADDRESS,
        location_label="Netherlands",
        display_name="leaf-test-1",
        resolver=FAKE_RESOLVER,
    )


@pytest.fixture
def vless_reality_credentials() -> list[Credential]:
    """Two friends, so a rendered client list is provably a list and ordered."""
    return [
        Credential(subject="aaaaaaaa-0000-4000-8000-000000000001"),
        Credential(subject="bbbbbbbb-0000-4000-8000-000000000002"),
    ]


@pytest.fixture
def vless_reality_params() -> dict[str, object]:
    """Valid VLESS + Reality parameters. `example.com` is reserved (RFC 2606)."""
    return {
        "port": 8443,
        "decoy_host": "www.example.com",
        "decoy_port": 443,
        "server_names": ("www.example.com",),
        "private_key": FAKE_PRIVATE_KEY,
        "public_key": FAKE_PUBLIC_KEY,
        "short_id": "0123abcd",
        "fingerprint": "chrome",
    }


@pytest.fixture
def vless_ws_tls_credentials(vless_reality_credentials) -> list[Credential]:
    """The same two friends. A VLESS client needs nothing but its subject.

    Named after the transport rather than shared under a generic name, so the
    convention in ``transport_fixture`` holds without exception — an exception there
    would be a lookup table again, one entry long.
    """
    return vless_reality_credentials


@pytest.fixture
def vless_ws_tls_params() -> dict[str, object]:
    """Valid VLESS + WS + TLS parameters.

    The certificate paths are FIXED, fictional node paths, not paths on this
    machine — golden files have to be byte-stable, and a real temporary directory
    would change on every run. Where a test needs the files to actually exist (the
    upstream checker opens them), it substitutes real paths via
    ``with_real_certificate``.
    """
    return {
        "port": 8444,
        "server_name": "front.example.com",
        "certificate_path": "/etc/hashi/certs/fullchain.pem",
        "certificate_key_path": "/etc/hashi/certs/privkey.pem",
        "ws_path_secret": "TESTwsPATHsecret0123456789",
    }


def with_real_certificate(
    params: dict[str, object], directory: pathlib.Path
) -> dict[str, object]:
    """Same parameters, but pointing at a throwaway self-signed certificate.

    Needed because ``xray run -test`` does not merely parse a config — it builds
    the TLS context, which means it OPENS the certificate named in it. A transport
    whose config references files on disk therefore cannot be fully validated
    anywhere but on a machine where those files exist.

    That is a real constraint rather than a test inconvenience, and it shapes the
    apply path: for such a transport, `control` validating locally before pushing
    proves less than validating on the node after placing the files. See
    ``edge/checker.py``.

    The certificate is generated here and thrown away with ``directory``. Never
    committed, never reused, and 1024-bit because it exists for a few milliseconds
    to satisfy a parser — not to protect anything.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "front.example.com")])
    # Fixed validity dates rather than "now": nothing about this certificate should
    # depend on when the suite runs.
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC))
        .not_valid_after(datetime.datetime(2100, 1, 1, tzinfo=datetime.UTC))
        .sign(key, hashes.SHA256())
    )

    certificate_path = directory / "fullchain.pem"
    key_path = directory / "privkey.pem"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return {
        **params,
        "certificate_path": str(certificate_path),
        "certificate_key_path": str(key_path),
    }


# Parameters that name a file the daemon will OPEN while loading the config.
# Discovered by running the real checker rather than reasoned about in advance:
# `xray run -test` does not merely parse a config, it builds the TLS context.
FILE_BACKED_PARAMS = frozenset({"certificate_path", "certificate_key_path"})


@pytest.fixture
def checkable_params_for():
    """Make a transport's parameters loadable by the upstream checker.

    Substitutes a throwaway certificate for any file-backed parameter, and passes
    everything else through untouched — so a transport that references no files
    (VLESS + Reality) is validated exactly as it renders in production.
    """

    def materialise(params: dict[str, object], directory: pathlib.Path) -> dict[str, object]:
        if FILE_BACKED_PARAMS & set(params):
            return with_real_certificate(dict(params), directory)
        return dict(params)

    return materialise


# WireGuard-family keys are STANDARD base64 (44 chars, padded) — a different encoding
# from Reality's, and the wrong one is rejected by the daemon rather than by us.
FAKE_WG_PRIVATE_KEY = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVphYmNkZWY="
FAKE_WG_PUBLIC_KEY = "Z2hpamtsbW5vcHFyc3R1dnd4eXpBQkNERUZHSElKS0w="
FAKE_WG_PRESHARED_KEY = "bW5vcHFyc3R1dnd4eXpBQkNERUZHSElKS0xNTk9QUVI="

# A peer's own private key, DISTINCT from the node's. Distinct on purpose rather than
# for tidiness: reusing the node's value here made the assertion "a friend's config
# file never carries the SERVER's private key" compare a string to itself, so it could
# not fail. The test found this fixture, which is the right order of events.
FAKE_WG_PEER_PRIVATE_KEY = "cGVlckFCQ0RFRkdISUpLTE1OT1BRUlNUVVZXWFlaMDE="
FAKE_WG_PEER_PUBLIC_KEY = "cGVlclpZWFdWVVRTUlFQT05NTEtKSUhHRkVEQ0JBOTg="

# One pre-shared key PER PEER — M23. Distinct from each other and from the node's, for
# the same reason the peer private key above is distinct from the node's: with one value
# reused, "no two peers share a pre-shared key" compares a string to itself and cannot
# fail. These are what a golden file has to show, because the defect they pin was two
# identical PresharedKey lines in a real node's config.
FAKE_WG_PEER_PRESHARED_KEY_ONE = "cGVlck9ORXByZXNoYXJlZEFCQ0RFRkdISUpLTE1OMDE="
FAKE_WG_PEER_PRESHARED_KEY_TWO = "cGVlclRXT3ByZXNoYXJlZEFCQ0RFRkdISUpLTE1OMDI="


@pytest.fixture
def amneziawg_params() -> dict[str, object]:
    """Valid AmneziaWG parameters for one end of a hop.

    Every obfuscation value is arbitrary-but-fixed. In production they must differ per
    node — shared junk is itself a fingerprint — which is why the model requires them
    and provides no defaults.
    """
    return {
        "port": 51820,
        # RFC 1918. Private is enforced by the model, not merely suggested.
        "tunnel_address": "10.44.0.1/24",
        "peer_tunnel_address": "10.44.0.2/24",
        "private_key": FAKE_WG_PRIVATE_KEY,
        "public_key": FAKE_WG_PUBLIC_KEY,
        "preshared_key": FAKE_WG_PRESHARED_KEY,
        "mtu": 1280,
        "junk_packet_count": 4,
        "junk_packet_min_size": 40,
        "junk_packet_max_size": 80,
        "init_packet_magic_header": 1020327352,
        "response_packet_magic_header": 2060487442,
        "underload_packet_magic_header": 3679305607,
        "transport_packet_magic_header": 1436947798,
    }


@pytest.fixture
def amneziawg_credentials() -> list[Credential]:
    """Two peers for the AmneziaWG hop, each with its own keypair.

    Peers rather than friends: this transport runs between our own nodes. The contract
    calls the scope CLIENT and does not need to know the difference.
    """
    return [
        Credential(
            subject="cccccccc-0000-4000-8000-000000000003",
            secrets={
                "peer_private_key": FAKE_WG_PEER_PRIVATE_KEY,
                "peer_public_key": FAKE_WG_PEER_PUBLIC_KEY,
                # Its OWN pre-shared key, like every consumer of this transport since
                # M23. The hop is the one peer that still has none of its own, and
                # ``tests/edge/test_relay.py`` is where that case is held.
                "peer_preshared_key": FAKE_WG_PEER_PRESHARED_KEY_ONE,
            },
        ),
        Credential(
            subject="dddddddd-0000-4000-8000-000000000004",
            secrets={
                "peer_private_key": FAKE_WG_PRESHARED_KEY,
                "peer_public_key": FAKE_WG_PRESHARED_KEY,
                "peer_preshared_key": FAKE_WG_PEER_PRESHARED_KEY_TWO,
                # Its OWN tunnel address. Two peers sharing one would make the second
                # silently take over the first's route, which the renderer refuses.
                "peer_tunnel_address": "10.44.0.3/24",
            },
        ),
    ]


@pytest.fixture
def wireguard_params() -> dict[str, object]:
    """Valid plain WireGuard parameters.

    Shorter than AmneziaWG's by exactly the obfuscation knobs, which is the difference
    between the two protocols rather than an omission here.
    """
    return {
        "port": 51821,
        # RFC 1918. Private is enforced by the model, not merely suggested.
        "tunnel_address": "10.55.0.1/24",
        "peer_tunnel_address": "10.55.0.2/24",
        "private_key": FAKE_WG_PRIVATE_KEY,
        "public_key": FAKE_WG_PUBLIC_KEY,
        "preshared_key": FAKE_WG_PRESHARED_KEY,
        "mtu": 1380,
    }


@pytest.fixture
def wireguard_credentials() -> list[Credential]:
    """Two friends, each with their own keypair and their own tunnel address.

    Their own addresses, unlike the AmneziaWG hop fixture's fallback: this transport is
    friend-facing only, and two friends sharing an address is the state the renderer
    refuses (see backlog item 33 for why nothing allocates them yet).
    """
    return [
        Credential(
            subject="eeeeeeee-0000-4000-8000-000000000005",
            secrets={
                "peer_private_key": FAKE_WG_PEER_PRIVATE_KEY,
                "peer_public_key": FAKE_WG_PEER_PUBLIC_KEY,
                "peer_preshared_key": FAKE_WG_PEER_PRESHARED_KEY_ONE,
                "peer_tunnel_address": "10.55.0.2/24",
            },
        ),
        Credential(
            subject="ffffffff-0000-4000-8000-000000000006",
            secrets={
                "peer_private_key": FAKE_WG_PRESHARED_KEY,
                "peer_public_key": FAKE_WG_PRESHARED_KEY,
                "peer_preshared_key": FAKE_WG_PEER_PRESHARED_KEY_TWO,
                "peer_tunnel_address": "10.55.0.3/24",
            },
        ),
    ]


@pytest.fixture
def transport_fixture(request):
    """Resolve a transport's ``params`` or ``credentials`` fixture BY CONVENTION.

    A CONVENTION rather than a lookup table, and the change is not tidying. Three test
    modules each carried their own ``{"vless-reality": "reality_params", ...}`` map, so
    adding a transport package meant editing three files outside its directory before
    the suite would even collect it — which is the surgery charter criterion 4 is
    written against, appearing in the tests that are supposed to prove criterion 4.

    With this, a new package under ``edge/transports/`` needs two fixtures named after
    itself in this file and nothing anywhere else.

    A fixture rather than an importable helper because pytest runs with
    ``--import-mode=importlib``, under which importing across test modules is not
    reliable — and doing it anyway once broke an unrelated scenario in another file.
    """

    def resolve(transport_name: str, kind: str):
        return request.getfixturevalue(f"{transport_name.replace('-', '_')}_{kind}")

    return resolve
