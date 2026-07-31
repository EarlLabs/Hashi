"""Control-plane configuration.

WHAT: every environment variable this service reads, declared in one place.
WHY:  scattered ``os.environ`` lookups fail on the first request that needs
      them, in production, at night. Declaring them here makes a missing value a
      boot-time error instead — the "fail loudly, never start degraded" rule in
      .claude/projects/00-core-invariants.md §3.
HOW:  ``Settings()`` raises when a required value is absent. Nothing else in the
      codebase may read the environment directly.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from ``HASHI_``-prefixed environment vars."""

    model_config = SettingsConfigDict(env_prefix="HASHI_")

    # No default on purpose: this key encrypts node credentials at rest, and a
    # generated-on-boot fallback would silently make yesterday's backup
    # undecryptable.
    secret_key: str

    # The delivery endpoint's public hostname. Must be reachable from inside
    # Russia — see docs/product/charter.md, deployment topology.
    public_host: str = "localhost"
