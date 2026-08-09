"""Minting the key material a transport declared it needs.

WHAT: one generator per ``KeyKind``, and ``mint()`` which walks a transport's
      declarations and produces values for them.
WHY:  backlog item 6a — generation was assumed by items 7, 8 and 9 and assigned to
      nobody. It lives in `control` because generating a key is I/O (it needs real
      randomness) and `edge` is pure: renderers take key material as an argument
      and never derive it.

      The shape of this module is the charter's fourth criterion in code. The
      table below is keyed by CRYPTOGRAPHIC KIND, never by transport name, so
      adding a protocol that needs an X25519 keypair and a UUID costs this file
      zero lines. ``vless-ws-tls`` was added after this was written and needed
      none — that is the intended arithmetic, and the tests assert it.
HOW:  ``mint(specs, scope)`` returns a ``Minted`` split into ``params`` (storable
      in clear, and needed by the client renderer) and ``secrets`` (encrypted at
      rest). Which is which is declared by the transport via ``KeySpec.secret``
      and ``KeySpec.public_name`` — not decided here.
"""

import base64
import secrets as secrets_module
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from edge.registry import KeyKind, KeyScope, KeySpec


class UnsupportedKeyKind(Exception):
    """A transport asked for a kind of material this control plane cannot make.

    Raised loudly, and it is the ONE thing a new transport may legitimately need
    from outside its own directory: a new generator below. It is still not a branch
    on a protocol — the generator is named after a cryptographic shape, and every
    transport that wants that shape gets it.
    """


@dataclass
class Minted:
    """Freshly generated material, already sorted into where each value belongs."""

    # Values safe to store in clear and needed by the client renderer: public key
    # halves, and generated values the transport marked as not secret.
    params: dict[str, str] = field(default_factory=dict)

    # Values that must be encrypted at rest.
    secrets: dict[str, str] = field(default_factory=dict)


def _x25519_keypair(*, urlsafe: bool = True) -> tuple[str, str]:
    """A fresh X25519 keypair, encoded the way the asking data plane expects.

    Always the RAW 32 bytes, never PEM: PEM is accepted by our own validation and
    rejected by both daemons, with an error that points at the config rather than at
    the encoding.

    ``urlsafe`` selects the alphabet and padding. Base64-URL unpadded is what
    ``xray x25519`` emits and the only form Reality accepts; standard padded base64
    is what ``wg genkey`` emits and the only form the WireGuard family accepts. The
    caller does not choose — the transport's declared ``KeyKind`` does.
    """
    private = X25519PrivateKey.generate()
    private_bytes = private.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )

    def encode(raw: bytes) -> str:
        if urlsafe:
            return base64.urlsafe_b64encode(raw).decode().rstrip("=")
        return base64.b64encode(raw).decode()

    return encode(private_bytes), encode(public_bytes)


def _generate(kind: KeyKind) -> tuple[str, str | None]:
    """One value for ``kind``, plus its public half when the kind is asymmetric.

    Every source of randomness here is ``secrets``/``os.urandom``-backed. Never
    ``random``: that module is seeded predictably and a node key drawn from it is
    guessable from any other key it produced.
    """
    match kind:
        case KeyKind.X25519_KEYPAIR:
            return _x25519_keypair(urlsafe=True)
        case KeyKind.X25519_KEYPAIR_BASE64:
            return _x25519_keypair(urlsafe=False)
        case KeyKind.UUID4:
            # uuid4 draws from os.urandom, so this is 122 bits of real entropy.
            return str(uuid.uuid4()), None
        case KeyKind.TOKEN_32:
            return secrets_module.token_urlsafe(32), None
        case KeyKind.SYMMETRIC_32_BASE64:
            # Standard base64 of 32 random bytes — 44 characters with padding.
            return base64.b64encode(secrets_module.token_bytes(32)).decode(), None
        case KeyKind.SHORT_ID:
            # 4 bytes as 8 hex characters. Short because the protocol requires it;
            # its job is to be unguessable to a prober who has not seen a real
            # client, not to be a key.
            return secrets_module.token_hex(4), None
        case _:
            raise UnsupportedKeyKind(
                f"no generator for key kind {kind!r}. A new transport needing a new "
                "cryptographic shape means adding a generator here — never a branch "
                "on which transport asked."
            )


def mint(specs: Iterable[KeySpec], scope: KeyScope) -> Minted:
    """Generate every declared piece of material for one scope.

    Filtered by scope rather than generating everything at once because the two
    happen at different times and for different reasons: node material is minted
    when a transport is enabled on a node, client material when a friend is granted
    access to it. Mixing them would mean re-keying a node every time a friend is
    added.
    """
    minted = Minted()
    for spec in specs:
        if spec.scope is not scope:
            continue
        value, public = _generate(spec.kind)

        if spec.secret:
            minted.secrets[spec.name] = value
        else:
            minted.params[spec.name] = value

        if public is not None:
            if spec.public_name is None:
                raise UnsupportedKeyKind(
                    f"{spec.kind!r} produces a public half but the transport did not "
                    f"declare a public_name for {spec.name!r} — the renderer would "
                    "have no way to reach it"
                )
            # The public half is never secret by definition, and it must be readable
            # without decryption because the CLIENT renderer needs it.
            minted.params[spec.public_name] = public

    return minted


def rotate(specs: Iterable[KeySpec], scope: KeyScope) -> Minted:
    """Fresh material for the same declarations — backlog item 23.

    Identical to ``mint`` today, and named separately because the CALLER's
    intent differs and the difference matters at the call site: rotating replaces
    material that friends' devices are currently using, so it is always followed by
    a re-render and a push to every affected node. See
    ``control/app/services/rotation.py``.
    """
    return mint(specs, scope)
