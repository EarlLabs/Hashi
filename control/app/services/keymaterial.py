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

``fingerprint`` is the other direction and belongs beside ``mint`` for the same reason:
it is the only function in this codebase that turns key material into something a
person reads, so it lives next to the one that makes it. What it will and will not
accept as input is the whole of it — see its own docstring.

``missing_client_material`` is ``mint`` asked backwards — does a stored credential carry
what its transport declares a consumer's material IS — and it is here so that "what a
credential should hold" has one definition rather than one per reader. M23, where a
transport declared a new per-consumer value and every credential minted before it
stopped being renderable into a file.
"""

import base64
import hashlib
import secrets as secrets_module
import uuid
from collections.abc import Iterable, Mapping
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


def missing_client_material(
    specs: Iterable[KeySpec], held: Mapping[str, object]
) -> list[str]:
    """Which CLIENT-scoped values a transport declares that this credential does not hold.

    The mirror of ``mint`` and it belongs beside it: one says what a consumer's material
    is, the other says whether a stored credential actually carries it. Empty for a
    credential minted against the current declaration, and non-empty for one minted
    before a transport declared a new piece — which is not hypothetical. M23 gave the
    WireGuard family a per-pair pre-shared key, and every credential minted before that
    carries none, so the renderer refuses to build a configuration file for it rather
    than hand out the node-wide key again.

    ``held`` is the material as ``edge`` would see it: the credential's own secrets, with
    the ``subject`` column under the name the contract requires. ``addresses.edge_credential``
    is the one builder of that mapping for the two renders that must agree, and a caller
    here passes the same thing — which is what makes this answer the same question the
    download does rather than one near it.

    Both halves of a spec, like ``transports.key_material_names``: a renderer reads the
    public counterpart of an asymmetric value by the name the transport declared for it,
    so a credential holding the private half alone is as unrenderable as one holding
    neither.

    NOTHING IS RETURNED BUT NAMES — never a value, and never a count of characters. A
    name is a field of a declaration that is already in the tree; the value is the
    credential.

    What this deliberately does NOT answer is whether a given renderer would actually
    refuse: one may fall back for a value another insists on, and asking that here would
    mean `control` recognising fields. The question it answers is the declaration's —
    this credential does not carry what the transport says a consumer's material is —
    and the repair is the same either way, which is why one predicate serves both the
    screen that reports it and the endpoint that skips it.
    """
    return sorted(
        name
        for spec in specs
        if spec.scope is KeyScope.CLIENT
        for name in (spec.name, spec.public_name)
        if name and not held.get(name)
    )


# How much of a digest a fingerprint shows at each end — ``9f3c…a17d``, the shape
# UI-PATTERNS §9 draws. Four and four rather than the whole hash because the job is
# to tell two pieces of material apart at a glance and to survive being read out loud,
# not to be a checksum: thirty-two bits is far more than a fleet of a handful of nodes
# needs to distinguish, and a 64-character run in a table cell is unreadable.
FINGERPRINT_ENDS = 4


def fingerprint(specs: Iterable[KeySpec], params: Mapping[str, object]) -> str | None:
    """A short, one-way name for the node material a transport currently holds.

    WHAT GOES IN, and nothing else: the values stored under the ``public_name`` a
    transport declared for its node-scoped asymmetric material. ``None`` when a
    transport declares no public half at all — a real answer, and the caller states
    the rule rather than inventing something to show.

    Three things this deliberately does NOT take, each for its own reason:

    * **the secret half.** It is not reachable from here: this function is handed the
      row's ``params`` column, which is the CLEAR one, and never ``secrets``. That is
      structural rather than careful — there is no decryption anywhere on this path,
      so no edit to this function alone could start showing a private value.
    * **a minted value that is merely non-secret** — a short random identifier a
      transport marks ``secret=False``. Those are low entropy by design (a few bytes),
      and a hash of a few bytes is recoverable by hashing every candidate. Feeding one
      in would turn a fingerprint into a way to READ something back, which is the one
      property this function exists to not have.
    * **anything a friend holds.** Client-scoped material is per person, so a value
      derived from it would be a per-person figure on a screen whatever it was called.

    Why hashing the public half is safe, and why showing that hash is: the value is
    already published — it travels to every user's device inside their own
    configuration, and to the far end of a hop — so the digest reveals strictly less
    than what is already handed out. It cannot be turned back into the private half
    either: that direction is the discrete logarithm the key exchange is built on, and
    what is displayed is eight hex characters of a SHA-256 digest rather than the value.

    Deterministic and sorted, because the operator compares this cell against itself
    after a rotation: a fingerprint that moved because a mapping iterated differently
    would read as material that changed.
    """
    published = sorted(
        spec.public_name
        for spec in specs
        if spec.scope is KeyScope.NODE and spec.public_name
    )
    named = [
        f"{name}={params[name]}"
        for name in published
        if params.get(name) not in (None, "")
    ]
    if not named:
        return None
    digest = hashlib.sha256("\n".join(named).encode()).hexdigest()
    return f"{digest[:FINGERPRINT_ENDS]}\u2026{digest[-FINGERPRINT_ENDS:]}"
