"""Encryption at rest, and password verification.

WHAT: derives the data-encryption key from ``HASHI_SECRET_KEY``, and provides the
      two operations that use it — ``encrypt``/``decrypt`` for stored secrets —
      plus the operator password hash check.
WHY:  core invariants §3: node and friend secrets are encrypted at rest with a key
      supplied by the environment, and the application fails loudly at boot when
      the key is missing rather than starting in a mode that writes plaintext.
      Doing it in the application rather than in the database (pgcrypto) is the
      point: a stolen dump, a stolen volume and a stolen backup are then all
      equally useless, because the key never enters the database's process.
HOW:  Fernet (AES-128-CBC + HMAC-SHA256, with an authenticated timestamp) over a
      key derived from the configured secret with HKDF. Never the raw secret as a
      Fernet key: the same secret also signs session cookies, and one key doing
      two jobs means a weakness in either becomes a weakness in both.
"""

import base64
import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# Distinct, stable labels so two derivations from one secret cannot collide. They
# are domain separation, not secrets, which is why they are literals here.
_DATA_KEY_INFO = b"hashi/data-encryption/v1"
_SESSION_KEY_INFO = b"hashi/session-signing/v1"
_TOKEN_DIGEST_INFO = b"hashi/subscription-token-digest/v1"

# Chosen to be expensive enough that a leaked hash is not a password list, and
# cheap enough for one login on a small VPS. n=2**15 is roughly 100ms and ~32MB.
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_SALT_BYTES = 16
_SCRYPT_KEY_BYTES = 32


def _derive(secret_key: str, info: bytes, length: int = 32) -> bytes:
    """One purpose-specific key from the configured secret.

    No salt: HKDF's salt is optional and the input here is already high-entropy
    configuration rather than a password. The ``info`` label is what separates the
    two derived keys, and it must never be reused for a third purpose without a
    new label.
    """
    return HKDF(
        algorithm=hashes.SHA256(), length=length, salt=None, info=info
    ).derive(secret_key.encode())


class SecretBox:
    """Encrypts and decrypts the values that must not be readable in a dump.

    Constructed once per application from settings and handed to the services that
    need it, rather than reaching for configuration at each call site — that is
    what keeps the key out of every function signature in the codebase.
    """

    def __init__(self, secret_key: str) -> None:
        if len(secret_key) < 32:
            # Not a style check. This key protects every node credential in the
            # database; a short one makes the derivation's output guessable and
            # there is no recovering from having encrypted a fleet under it.
            raise ValueError("HASHI_SECRET_KEY must be at least 32 characters")
        self._fernet = Fernet(base64.urlsafe_b64encode(_derive(secret_key, _DATA_KEY_INFO)))
        # A THIRD derived key, for deterministic lookup digests. Kept separate from
        # the encryption key so that a digest, which is by design reproducible and
        # indexed, can never be used to say anything about the encryption key.
        self._digest_key = _derive(secret_key, _TOKEN_DIGEST_INFO)

    def digest(self, value: str) -> str:
        """A deterministic, keyed digest of ``value`` — for indexed lookup.

        Exists because an encrypted column cannot be searched: Fernet output is
        randomised, so the same subscription token encrypts differently every time
        and ``WHERE token = ...`` could never match. This gives an indexable
        equality key without storing the token in clear.

        KEYED (HMAC) rather than a plain hash, and that is the whole point: someone
        holding a database dump but not ``HASHI_SECRET_KEY`` cannot even test a
        guessed token against the stored digests. SHA-256 rather than a slow KDF is
        correct here — the input is 32 bytes of our own entropy, not a
        human-chosen password, so there is no dictionary to defend against.

        The raw secret is deliberately not reachable from outside this class; this
        method is how callers get a digest without ever holding the key.
        """
        return hmac.new(self._digest_key, value.encode(), hashlib.sha256).hexdigest()

    def encrypt(self, plaintext: str) -> str:
        """Ciphertext as text, so it stores in a plain column."""
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        """Recover a stored secret.

        Raises ``SecretUnreadable`` rather than returning None or "": a caller that
        silently gets an empty key renders a config that authorises nobody, pushes
        it to a node, and locks out every friend on it. Failing here is loud and
        recoverable; succeeding emptily is neither.
        """
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise SecretUnreadable(
                "a stored secret could not be decrypted — HASHI_SECRET_KEY does not "
                "match the one this row was written with"
            ) from exc


class SecretUnreadable(Exception):
    """A stored secret cannot be decrypted with the configured key."""


def session_secret(secret_key: str) -> str:
    """The cookie-signing key, derived separately from the data key."""
    return base64.urlsafe_b64encode(_derive(secret_key, _SESSION_KEY_INFO)).decode()


# --- operator password ------------------------------------------------------

def hash_password(password: str) -> str:
    """Hash a password for ``HASHI_OPERATOR_PASSWORD_HASH``.

    scrypt from the standard library rather than a new dependency, and rather than
    a bare SHA-256: the whole value of a slow KDF here is that the panel's single
    credential cannot be brute-forced offline from a leaked environment file.

    Format: ``scrypt$<n>$<r>$<p>$<salt-b64>$<hash-b64>``. The parameters are IN the
    string so raising the cost later does not invalidate existing hashes.
    """
    salt = secrets.token_bytes(_SCRYPT_SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P,
        dklen=_SCRYPT_KEY_BYTES, maxmem=64 * 1024 * 1024,
    )
    return "$".join(
        [
            "scrypt",
            str(_SCRYPT_N),
            str(_SCRYPT_R),
            str(_SCRYPT_P),
            base64.b64encode(salt).decode(),
            base64.b64encode(derived).decode(),
        ]
    )


def _decoded(encoded: str) -> tuple[int, int, int, bytes, bytes] | None:
    """Split a stored hash into its parts, or None if it is not one.

    One parser, used by ``verify_password`` and by ``is_well_formed_hash``, so that
    "a hash the login can check" and "a hash the boot check accepts" cannot become
    two different answers — which would be a control plane that starts happily and
    then rejects every password.

    ``validate=True`` on the base64 matters here and is not tidiness: without it
    ``b64decode`` silently drops characters outside the alphabet, so a value that
    has been chewed by an interpolating tool still decodes to *something* and looks
    like a hash. The point of this function is to notice exactly that.
    """
    try:
        scheme, n, r, p, salt_b64, hash_b64 = encoded.split("$")
        if scheme != "scrypt":
            return None
        salt = base64.b64decode(salt_b64, validate=True)
        expected = base64.b64decode(hash_b64, validate=True)
    except (ValueError, TypeError):
        # binascii.Error is a ValueError, so a malformed base64 lands here too.
        return None
    if not salt or not expected:
        # An empty field is the signature of the damage this guards against: a
        # `$name` swallowed by an interpolating tool leaves the separators behind
        # and takes the value.
        return None
    if int(n) <= 1 or int(r) < 1 or int(p) < 1:
        return None
    return int(n), int(r), int(p), salt, expected


def is_well_formed_hash(encoded: str) -> bool:
    """Whether ``encoded`` has the shape ``hash_password`` produces.

    Shape only — it says nothing about which password the hash is of, which is why
    it is safe to call at boot with no secret to hand.

    It exists because the one way this value is known to arrive damaged is silent:
    ``docker compose`` interpolates the values it reads from an env file, so an
    undoubled ``$<salt>`` or ``$<digest>`` is read as a variable name and replaced
    with nothing. The result still starts with ``scrypt`` and still looks plausible
    in the file, and the only symptom is a login that answers 401 forever. Nothing
    else in the system is in a position to notice, because verifying a password
    cannot distinguish "wrong password" from "hash arrived in pieces".
    """
    return _decoded(encoded) is not None


def verify_password(password: str, encoded: str) -> bool:
    """Check a password against a stored hash, in constant time.

    Returns False on a malformed hash rather than raising: authorisation fails
    closed (core invariants §4), and a misconfigured hash must deny the login
    rather than produce a 500 that a prober can distinguish from a wrong password.
    """
    parts = _decoded(encoded)
    if parts is None:
        return False
    n, r, p, salt, expected = parts
    try:
        derived = hashlib.scrypt(
            password.encode(), salt=salt, n=n, r=r, p=p,
            dklen=len(expected), maxmem=64 * 1024 * 1024,
        )
    except ValueError:
        # Parameters that parse as integers but that scrypt itself refuses — an `n`
        # that is not a power of two, a cost beyond `maxmem`. Still a denial, never
        # a 500.
        return False
    return hmac.compare_digest(derived, expected)
