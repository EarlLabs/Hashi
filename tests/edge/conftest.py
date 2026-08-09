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


@pytest.fixture
def node() -> NodeView:
    """One fixed node. Reserved address, operator-chosen labels."""
    return NodeView(
        id="11111111-1111-4111-8111-111111111111",
        address=FAKE_ADDRESS,
        location_label="Netherlands",
        display_name="leaf-test-1",
    )


@pytest.fixture
def credentials() -> list[Credential]:
    """Two friends, so a rendered client list is provably a list and ordered."""
    return [
        Credential(subject="aaaaaaaa-0000-4000-8000-000000000001"),
        Credential(subject="bbbbbbbb-0000-4000-8000-000000000002"),
    ]


@pytest.fixture
def reality_params() -> dict[str, object]:
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
def ws_params() -> dict[str, object]:
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
