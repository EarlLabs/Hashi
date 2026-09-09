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
