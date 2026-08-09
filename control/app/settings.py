"""Control-plane configuration.

WHAT: every environment variable this service reads, declared in one place.
WHY:  scattered ``os.environ`` lookups fail on the first request that needs
      them, in production, at night. Declaring them here makes a missing value a
      boot-time error instead — the "fail loudly, never start degraded" rule in
      .claude/projects/00-core-invariants.md §3.
HOW:  ``Settings()`` raises when a required value is absent. Nothing else in the
      codebase may read the environment directly.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from ``HASHI_``-prefixed environment vars."""

    model_config = SettingsConfigDict(env_prefix="HASHI_")

    # No default on purpose: this key encrypts node credentials at rest, and a
    # generated-on-boot fallback would silently make yesterday's backup
    # undecryptable.
    secret_key: str = Field(min_length=32)

    # The delivery endpoint's public hostname. Must be reachable from inside
    # Russia — see docs/product/charter.md, deployment topology.
    public_host: str = "localhost"

    # Whether subscription URLs are built with https. On by default because a
    # subscription token is a bearer credential in a URL path, and http would put
    # it on the wire in clear. Off only for the e2e stack, which talks to the
    # control plane directly rather than through Caddy.
    public_https: bool = True

    # SQLAlchemy URL for the control database, e.g.
    # postgresql+asyncpg://hashi:...@db:5432/hashi
    #
    # No default. A default of localhost would mean a misconfigured container
    # starts up, finds no database, and reports itself unhealthy in a way that
    # looks like a database outage rather than a missing variable.
    database_url: str

    # The operator's credentials. There is exactly one operator (the charter's
    # "one operator, one fleet"), so they come from the environment rather than
    # from a users table — a table would imply the signup flow the charter names
    # as a non-goal.
    #
    # The PASSWORD IS NEVER HERE, only its hash. Generate one with:
    #   python -m control.cli hash-password
    operator_username: str = "owner"
    operator_password_hash: str

    # How long an operator's session cookie stays valid, in seconds. Eight hours:
    # long enough to work through a node rotation without re-authenticating,
    # short enough that a forgotten browser tab is not a permanent key to the
    # panel. There is deliberately no "remember me".
    session_max_age: int = 8 * 60 * 60

    # SSH connect/exec timeout when talking to a node, in seconds. A node that is
    # blocked or seized does not refuse the connection — it hangs, so every node
    # operation needs a ceiling or the panel blocks on a dead host.
    node_ssh_timeout: int = 20

    @property
    def public_base_url(self) -> str:
        """The origin a friend's client dials. Built here, so nothing hardcodes it."""
        scheme = "https" if self.public_https else "http"
        return f"{scheme}://{self.public_host}"
