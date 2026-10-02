"""A setting compose passes through blank takes its default — M31.2.

WHAT: what ``Settings`` reads from the environment when an optional ``HASHI_`` variable
      is SET BUT EMPTY, which is what ``${VAR:-}`` in deploy/docker-compose.yml hands the
      container whenever the operator left that variable out of ``.env``.
WHY:  the field walk of 2026-10-02 set ``HASHI_FINDING_REMEASURE_INTERVAL`` in ``.env``
      and found nothing inside the container: the compose file did not pass it, and the
      compose file is the whole list of what this process can read. Passing an optional
      setting through means passing it blank when it is unset, and a blank float or int
      is a boot failure unless blank means "not set". The other half — that the compose
      file passes every such setting — is tests/infra/test_compose.py.
HOW:  pure construction of ``Settings`` from a patched environment; nothing boots.
"""

import pytest
from pydantic import ValidationError

from control.app.settings import Settings

from .conftest import TEST_SECRET_KEY

REQUIRED = {
    "HASHI_SECRET_KEY": TEST_SECRET_KEY,
    "HASHI_DATABASE_URL": "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused",
    # The shape of a real hash; this file is not about it.
    "HASHI_OPERATOR_PASSWORD_HASH": "scrypt$32768$8$1$c2FsdHNhbHRzYWx0c2FsdA==$"
    "ZGlnZXN0ZGlnZXN0ZGlnZXN0ZGlnZXN0ZGlnZXN0ZGk=",
}


@pytest.fixture
def environment(monkeypatch: pytest.MonkeyPatch):
    for key, value in REQUIRED.items():
        monkeypatch.setenv(key, value)
    return monkeypatch


def test_a_blank_interval_is_the_default_and_not_a_boot_failure(environment) -> None:
    """Red before M31.2: a blank float refused to parse, so the variable could not be
    passed through compose without a second copy of its default there."""
    environment.setenv("HASHI_FINDING_REMEASURE_INTERVAL", "")
    environment.setenv("HASHI_NODE_SETTLE_TIMEOUT", "")
    environment.setenv("HASHI_AUDIT_RETENTION_DAYS", "")
    settings = Settings()
    defaults = Settings.model_fields
    assert settings.finding_remeasure_interval == defaults["finding_remeasure_interval"].default
    assert settings.node_settle_timeout == defaults["node_settle_timeout"].default
    assert settings.audit_retention_days == defaults["audit_retention_days"].default


def test_a_value_that_is_set_is_the_value(environment) -> None:
    """The accept twin, and the case the walk needed: ``0`` switches re-measuring off."""
    environment.setenv("HASHI_FINDING_REMEASURE_INTERVAL", "0")
    assert Settings().finding_remeasure_interval == 0


def test_a_blank_required_setting_still_refuses_to_boot(environment) -> None:
    """Blank-means-unset loosens nothing a required field relies on."""
    environment.setenv("HASHI_SECRET_KEY", "")
    with pytest.raises(ValidationError):
        Settings()
