"""Control-plane configuration.

WHAT: every environment variable this service reads, declared in one place.
WHY:  scattered ``os.environ`` lookups fail on the first request that needs
      them, in production, at night. Declaring them here makes a missing value a
      boot-time error instead — the "fail loudly, never start degraded" rule in
      .claude/projects/00-core-invariants.md §3.
HOW:  ``Settings()`` raises when a required value is absent. Nothing else in the
      codebase may read the environment directly.
"""

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from control.app.crypto import is_well_formed_hash

# The audit trail's window, in days, and the two ends of it. Named rather than written
# into the Field below, because the Settings screen states them to the operator
# ("anything from 1 to 365 days") and a screen that repeats a bound instead of reading
# it is a screen that goes false the day the bound moves. One definition, two readers —
# the validator and the sentence.
AUDIT_RETENTION_MIN_DAYS = 1
AUDIT_RETENTION_MAX_DAYS = 365
AUDIT_RETENTION_DEFAULT_DAYS = 30


class OperatorHashMalformed(RuntimeError):
    """The configured operator hash is not a hash, so nobody could ever log in.

    A plain exception rather than a pydantic ``ValueError``, and that is the whole
    reason it exists: pydantic puts the offending INPUT into the ``ValidationError``
    it raises, and this input is the operator's password hash. It would then be
    printed by the container on every failed boot and kept in whatever collects
    container output — an offline brute-force target, published by the code that was
    trying to protect it. Raising something pydantic does not wrap keeps the message
    to what an operator needs and no more.
    """


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

    # Ceiling on ONE operation over an SSH session that is already open — a command,
    # a file transfer — in seconds. Generous, because restarting a stack or pulling an
    # image legitimately takes time.
    node_ssh_timeout: int = 20

    # Ceiling on REACHING a node at all, in seconds. Separate from and much shorter
    # than the one above: a node that is blocked or seized does not refuse the
    # connection, it hangs, and the operator pressing apply during a block needs an
    # answer rather than a spinner. A setting rather than a constant because it is the
    # one ceiling a real network can force us to raise — a node behind a link so lossy
    # that five seconds is not enough is still a node worth reaching — and because the
    # test suite lowers it, which is how it stays honest that the value is used.
    node_connect_timeout: int = 5

    # How long an apply watches the daemon it just restarted before believing it, and
    # how far apart the readings are — both in seconds. M26's second acceptance walk.
    #
    # An apply used to look ONCE, straight after `docker compose up -d`, and a container
    # sampled in the first second of its first start is running and not yet restarting.
    # The walk read a node as serving while its container was in a crash loop, and read
    # another as degraded while its friend's ping was 0% loss. Both readings were true
    # about the instant they were taken and meant nothing about the node.
    #
    # Settings rather than constants for ``node_connect_timeout``'s reason: they are what
    # a real fleet can force us to raise — a node pulling an image over a slow link takes
    # longer to come back than a container on a laptop — and because the test suite lowers
    # them, which is how it stays honest that the values are used. Twenty seconds is the
    # window the walk itself watched before it concluded the panel was lying; two seconds
    # is long enough that a container which dies on its own configuration has died inside
    # it, and short enough that a healthy apply costs one of them.
    node_settle_timeout: float = 20.0
    node_settle_interval: float = 2.0

    # How long the audit trail keeps an entry, in days. Thirty rather than ninety or
    # forever: what the trail answers — did I do this, what did I change before it
    # broke — decays in days, while the risk it carries grows with every day it is
    # kept, on the one machine the charter calls most worth seizing.
    #
    # Bounded 1–365 with NO value meaning "forever", and that is the part to leave
    # alone. A record with no end is precisely what the charter objects to, so the
    # absence of an off switch is the decision (docs/decisions.md, 2026-09-11) rather
    # than a missing feature. A floor of one day rather than zero because zero would be
    # a trail that exists in the schema and holds nothing — if it should not exist, the
    # honest change is to stop writing it.
    audit_retention_days: int = Field(
        default=AUDIT_RETENTION_DEFAULT_DAYS,
        ge=AUDIT_RETENTION_MIN_DAYS,
        le=AUDIT_RETENTION_MAX_DAYS,
    )

    @field_validator("operator_password_hash")
    @classmethod
    def _hash_must_be_well_formed(cls, value: str) -> str:
        """Refuse to boot with a hash nobody could ever match.

        The failure this replaces was observed on a live host and cost the owner
        their panel: ``docker compose --env-file`` interpolates the values it reads,
        so an undoubled ``$`` in a scrypt hash starts a variable reference and the
        field after it is replaced with nothing. Compose exits 0, the health check
        passes, the panel serves a login form, and every attempt answers 401 — with a
        hash that looks perfectly correct sitting in the file. Whether it happens at
        all depends on the random salt and digest, so the same procedure works on one
        host and locks the owner out of the next.

        Nothing further down can catch it. ``verify_password`` cannot tell a damaged
        hash from a wrong password, and must not: authorisation fails closed. So the
        only place the shape can be judged is here, once, before anything serves.
        """
        if is_well_formed_hash(value):
            return value
        hint = (
            "It still has doubled dollars in it, so it was escaped for docker compose "
            "and then handed over without compose expanding it — undouble them if this "
            "process is not started by compose."
            if "$$" in value
            else "The usual cause is docker compose interpolation: compose expands the "
            "values it reads from an env file, so each `$` in the hash must be written "
            "`$$` in that file. `python -m control.cli hash-password` now prints the "
            "line already escaped — paste it exactly as it comes out."
        )
        raise OperatorHashMalformed(
            "HASHI_OPERATOR_PASSWORD_HASH is not a well-formed scrypt hash "
            f"(expected scrypt$n$r$p$salt$digest). {hint} Refusing to start: a panel "
            "that boots with a damaged hash answers 401 to its own operator forever, "
            "and there is nothing in the logs to grep for."
        )

    @property
    def public_base_url(self) -> str:
        """The origin a friend's client dials. Built here, so nothing hardcodes it."""
        scheme = "https" if self.public_https else "http"
        return f"{scheme}://{self.public_host}"
