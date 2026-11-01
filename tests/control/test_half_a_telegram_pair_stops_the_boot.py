"""The bot's settings come together or not at all, and the refusal never shows the token — M37.1.

WHAT: what ``Settings`` does with ``HASHI_TELEGRAM_BOT_TOKEN`` and ``HASHI_TELEGRAM_OWNER_ID``
      — both blank, both set, and each one on its own — and what the refusal says and
      does not say.
WHY:  both blank is OFF and is the default, which is what the stand and every existing
      install get without a change; one without the other is a bot that would answer
      anyone (a token with no owner) or one nobody can start (an owner with no token),
      and either is one typo away. The plan's rule is that it refuses to boot with a
      sentence naming both halves. And the token is a bearer credential: a boot message
      that printed it would publish it to whatever collects container output, which is
      the leak ``OperatorHashMalformed`` already guards for the operator's hash.
HOW:  pure construction of ``Settings`` from a patched environment, the way compose
      hands the values over, with a blank meaning "left out of .env"
      (``env_ignore_empty``). Nothing boots, nothing dials.
"""

import pytest
from pydantic import ValidationError

from control.app.settings import Settings, TelegramSettingsIncomplete

from .conftest import TEST_SECRET_KEY

REQUIRED = {
    "HASHI_SECRET_KEY": TEST_SECRET_KEY,
    "HASHI_DATABASE_URL": "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused",
    # The shape of a real hash; this file is not about it.
    "HASHI_OPERATOR_PASSWORD_HASH": "scrypt$32768$8$1$c2FsdHNhbHRzYWx0c2FsdA==$"
    "ZGlnZXN0ZGlnZXN0ZGlnZXN0ZGlnZXN0ZGlnZXN0ZGk=",
}

# The shape BotFather hands out — digits, a colon, a long alphabet — and plainly not one.
TOKEN = "110201543:TEST-TOKEN-NEVER-REAL-9f3b2c1d8e7a6b5c4d3e2f1a0b9c8d7e"
OWNER_ID = "987654321"


@pytest.fixture
def environment(monkeypatch: pytest.MonkeyPatch):
    for key, value in REQUIRED.items():
        monkeypatch.setenv(key, value)
    return monkeypatch


def test_both_blank_is_off_and_is_the_default(environment) -> None:
    """Set but empty — what ``${VAR:-}`` in the compose file passes — reads as unset."""
    environment.setenv("HASHI_TELEGRAM_BOT_TOKEN", "")
    environment.setenv("HASHI_TELEGRAM_OWNER_ID", "")
    settings = Settings()
    assert settings.telegram_bot_token is None
    assert settings.telegram_owner_id is None
    # The one default that is a domain, and it is a SETTING's default on purpose: the
    # plan's own words are that the API URL is configuration, overridable for a relay.
    assert settings.telegram_api_url == "https://api.telegram.org"


def test_both_set_boots_with_the_bot_on(environment) -> None:
    environment.setenv("HASHI_TELEGRAM_BOT_TOKEN", TOKEN)
    environment.setenv("HASHI_TELEGRAM_OWNER_ID", OWNER_ID)
    environment.setenv("HASHI_TELEGRAM_API_URL", "http://telegram.test:8081")
    settings = Settings()
    assert settings.telegram_bot_token is not None
    assert settings.telegram_bot_token.get_secret_value() == TOKEN
    assert settings.telegram_owner_id == int(OWNER_ID)
    assert settings.telegram_api_url == "http://telegram.test:8081"
    # The token is a ``SecretStr`` so that no ``repr`` of these settings — a debugger, a
    # stray log line — carries it. Asserted on the rendering, not on the type.
    assert TOKEN not in repr(settings)
    assert TOKEN not in str(settings)


@pytest.mark.parametrize(
    "present",
    ["HASHI_TELEGRAM_BOT_TOKEN", "HASHI_TELEGRAM_OWNER_ID"],
    ids=["token-without-owner", "owner-without-token"],
)
def test_half_a_pair_refuses_to_boot_naming_both(environment, present: str) -> None:
    """Either half alone is refused, and the sentence names BOTH variables: the fix is the
    line that is missing, and an operator who set one is looking at the wrong one."""
    environment.setenv(present, TOKEN if present.endswith("TOKEN") else OWNER_ID)
    with pytest.raises(TelegramSettingsIncomplete) as refusal:
        Settings()
    sentence = str(refusal.value)
    assert "HASHI_TELEGRAM_BOT_TOKEN" in sentence
    assert "HASHI_TELEGRAM_OWNER_ID" in sentence


def test_the_refusal_does_not_print_the_token(environment) -> None:
    """Why the refusal is a ``RuntimeError`` and not a pydantic ``ValueError``.

    Measured, not assumed: a ``ValueError`` out of a model validator becomes a
    ``ValidationError`` whose text quotes the whole input it was validating — the secret
    key, the operator's hash and this token — on every failed boot. Asserted on the
    rendering rather than on the type alone, for ``test_operator_hash_at_boot``'s reason:
    a future ``ValueError`` here would restore the leak without touching this file.
    """
    environment.setenv("HASHI_TELEGRAM_BOT_TOKEN", TOKEN)
    with pytest.raises(Exception) as refusal:  # noqa: B017 - the rendering is what is under test
        Settings()
    for rendering in (str(refusal.value), repr(refusal.value)):
        assert TOKEN not in rendering, "the boot failure prints the bot token"
    assert not isinstance(refusal.value, ValidationError)
    assert isinstance(refusal.value, TelegramSettingsIncomplete)


@pytest.mark.parametrize("owner_id", ["0", "-100123456", "not-a-number", "12.5"])
def test_an_owner_id_that_is_not_an_account_is_refused_without_the_token(
    environment, owner_id: str
) -> None:
    """Zero names nobody and a negative id names a group or a channel, which the bot must
    never take commands from; a positive integer is the only shape an account has. The
    refusal is pydantic's own, about THAT field, and must not quote the token beside it."""
    environment.setenv("HASHI_TELEGRAM_BOT_TOKEN", TOKEN)
    environment.setenv("HASHI_TELEGRAM_OWNER_ID", owner_id)
    with pytest.raises(ValidationError) as refusal:
        Settings()
    for rendering in (str(refusal.value), repr(refusal.value)):
        assert TOKEN not in rendering, "a refused owner id printed the token next to it"


def test_a_blank_token_passed_by_a_caller_is_also_off(environment) -> None:
    """One rule for both sources: a blank is OFF whether the environment or a caller said it.
    Without this, ``Settings(telegram_bot_token="")`` would be half a pair."""
    assert Settings(telegram_bot_token="").telegram_bot_token is None
