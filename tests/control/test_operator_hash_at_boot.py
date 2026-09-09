"""A damaged operator hash must stop the boot, not answer 401 forever — M6.4.

WHAT: what ``Settings`` does with a hash that is not one, and what it does not put in the
      message when it refuses.
WHY:  the failure this guards was silent from end to end. ``docker compose`` ate part of
      the hash, exited 0, the health check passed, the panel served its login form, and
      every attempt came back "Those credentials were not accepted" — with a
      correct-looking hash in the env file and nothing in any log to grep for. The login
      path cannot help: ``verify_password`` fails closed and must not distinguish a
      damaged hash from a wrong password, because that distinction is free information for
      a prober. So boot is the only place the shape can be judged.
HOW:  pure construction of ``Settings``; no database, no environment, no container. The
      other half of this — that the value survives the trip through compose at all — is
      ``tests/infra/test_operator_hash_survives_compose.py``, because proving that needs
      compose itself.
"""

import pytest
from pydantic import ValidationError

from control.app.crypto import hash_password, verify_password
from control.app.settings import OperatorHashMalformed, Settings

# Observed on the live host on 2026-09-09, verbatim: an 86-character hash that arrived as
# 42 because compose read `$<digest>` as a variable name. The salt survived only because
# base64 happened to give it a leading digit. Kept as a literal rather than reconstructed,
# so this test is anchored to something that really happened.
AS_IT_ARRIVED_ON_THE_LIVE_HOST = "scrypt$32768$8$1$469D1j8LwOnyngdRZyAHYA==="

PASSWORD = "a-fixture-password-nobody-uses"


def settings_with(hash_value: str) -> Settings:
    return Settings(
        secret_key="test-only-not-a-real-key-000000000000000000000000",
        database_url="postgresql+asyncpg://unused:unused@127.0.0.1:1/unused",
        operator_password_hash=hash_value,
    )


def test_a_real_hash_boots() -> None:
    """First, so that none of the refusals below can be passing vacuously."""
    real = hash_password(PASSWORD)
    assert settings_with(real).operator_password_hash == real


def test_the_hash_the_live_host_actually_received_refuses_to_boot() -> None:
    """The exact value, and the exact reason the owner was locked out."""
    with pytest.raises(OperatorHashMalformed) as refusal:
        settings_with(AS_IT_ARRIVED_ON_THE_LIVE_HOST)
    assert "HASHI_OPERATOR_PASSWORD_HASH" in str(refusal.value)
    assert "docker compose" in str(refusal.value), (
        "the refusal does not name the cause, so an operator reading it learns that "
        "something is wrong and not what to do about it"
    )


def test_a_hash_that_is_still_escaped_is_named_as_such() -> None:
    """The one case the pre-escaping in ``control.cli`` makes worse, so it is called out.

    An operator who exports the variable by hand instead of letting compose expand it gets
    the doubled form. That is a different mistake with a different fix, and a message that
    told them to double the dollars again would be actively misleading.
    """
    with pytest.raises(OperatorHashMalformed) as refusal:
        settings_with(hash_password(PASSWORD).replace("$", "$$"))
    assert "undouble" in str(refusal.value)


def test_the_refusal_does_not_print_the_hash() -> None:
    """A hash in a boot message is an offline brute-force target in the container's logs.

    This is why the refusal is a plain exception rather than a pydantic ``ValueError``:
    pydantic puts the offending input into the ``ValidationError`` it builds, and this
    input is a credential. Asserted on the message rather than on the exception type alone,
    because a future ``ValueError`` here would restore the leak without touching this file.
    """
    damaged = hash_password(PASSWORD).replace("$", "$$")
    with pytest.raises(OperatorHashMalformed) as refusal:
        settings_with(damaged)
    assert damaged not in str(refusal.value)
    assert not isinstance(refusal.value, ValidationError)


def test_the_login_path_still_fails_closed_on_the_same_value() -> None:
    """Both layers, and they must not disagree.

    Boot refuses so nobody is locked out silently; the login check still returns False
    rather than raising, because authorisation fails closed (core invariants §4) and a 500
    on a malformed hash is a signal a prober can read.
    """
    assert verify_password(PASSWORD, AS_IT_ARRIVED_ON_THE_LIVE_HOST) is False


# --- round 1: the shapes that are not compose's ------------------------------
#
# The refusals above are all shapes docker compose produces, which is how the one below
# got through: a hash can be malformed in ways that have nothing to do with interpolation
# — hand-typed, half-pasted, or written by a future version of this format.

MALFORMED = [
    # A cost field that is not a number. THE round-1 critical: `int(n)` used to sit
    # outside `_decoded`'s try, so this raised out of the pydantic validator and pydantic
    # wrapped it in a ValidationError carrying `input_value=<the whole hash>`.
    "scrypt$notanumber$8$1$c2FsdHNhbHQ=$aGFzaGhhc2g=",
    "scrypt$32768$eight$1$c2FsdHNhbHQ=$aGFzaGhhc2g=",
    "scrypt$32768$8$$c2FsdHNhbHQ=$aGFzaGhhc2g=",
    # A cost that parses but that scrypt itself cannot take. Well FORMED, so it boots —
    # see the totality test below for why that is still not a 500 on the login route.
    "scrypt$0$8$1$c2FsdHNhbHQ=$aGFzaGhhc2g=",
    "scrypt$-32768$8$1$c2FsdHNhbHQ=$aGFzaGhhc2g=",
    # Not base64 at all, and base64 that decodes to nothing.
    "scrypt$32768$8$1$not base64!$aGFzaGhhc2g=",
    "scrypt$32768$8$1$c2FsdHNhbHQ=$",
    # Not this format at all.
    "bcrypt$32768$8$1$c2FsdHNhbHQ=$aGFzaGhhc2g=",
    "scrypt$32768$8$1$c2FsdHNhbHQ=",
    "",
    "run-python--m-control.cli-hash-password-and-paste-the-output",
]


@pytest.mark.parametrize("hash_value", MALFORMED)
def test_no_malformed_hash_ever_reaches_a_message(hash_value: str) -> None:
    """The refusal must not carry the credential, whatever shape the damage took.

    Asserted on what the operator and the container's logs actually see — the string of
    the exception, however it was raised and whoever wrapped it — rather than on the
    exception's type. Type alone was the assertion that missed this: ``OperatorHashMalformed``
    was raised correctly for every shape anybody had tried, while one uncaught
    ``ValueError`` from a cost field turned into a pydantic ``ValidationError`` that
    printed the hash in full, salt and digest included, on every boot attempt.

    A hash is not a password, but it is an offline brute-force target, and putting one in
    a boot message publishes it to whatever collects container output.
    """
    with pytest.raises(Exception) as refusal:  # noqa: B017 - the type is what is under test
        settings_with(hash_value)

    for rendering in (str(refusal.value), repr(refusal.value)):
        assert hash_value == "" or hash_value not in rendering, (
            "the boot failure prints the configured hash — this is the leak "
            "OperatorHashMalformed exists to prevent, reintroduced through a wrapper"
        )
    assert isinstance(refusal.value, OperatorHashMalformed), (
        f"{type(refusal.value).__name__} escaped instead of the refusal, so the message "
        "is whatever the wrapper decided to say — which is how the credential got out"
    )


@pytest.mark.parametrize(
    "hash_value",
    [
        *MALFORMED,
        # Well formed, so `_decoded` returns parts and scrypt is actually called with
        # them. Each of these raises a DIFFERENT exception out of hashlib, and none of
        # them may reach the login route: the control rulebook's own trap is that a 500
        # here is a signal a prober can tell apart from a wrong password.
        "scrypt$3$8$1$c2FsdHNhbHQ=$aGFzaGhhc2g=",  # not a power of two -> ValueError
        "scrypt$1099511627776$8$1$c2FsdHNhbHQ=$aGFzaGhhc2g=",  # beyond maxmem -> ValueError
        "scrypt$" + "1" + "0" * 30 + "$8$1$c2FsdHNhbHQ=$aGFzaGhhc2g=",  # -> OverflowError
    ],
)
def test_verifying_a_password_is_total(hash_value: str) -> None:
    """``verify_password`` returns False for any string, and never raises.

    A guarantee about the function, not about the order it is called in. It used to hold
    only because the configured hash had already been through ``_decoded`` at boot, which
    is an invariant no caller could see — and the login route is exactly the place where
    an exception becomes a 500 that fails open-ish rather than closed.
    """
    assert verify_password(PASSWORD, hash_value) is False
