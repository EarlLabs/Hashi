"""Control-plane configuration.

WHAT: every environment variable this service reads, declared in one place.
WHY:  scattered ``os.environ`` lookups fail on the first request that needs
      them, in production, at night. Declaring them here makes a missing value a
      boot-time error instead — the "fail loudly, never start degraded" rule in
      .claude/projects/00-core-invariants.md §3.
HOW:  ``Settings()`` raises when a required value is absent. Nothing else in the
      codebase may read the environment directly.
"""

import pathlib
from typing import Self

from pydantic import Field, SecretStr, field_validator, model_validator
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


class TelegramSettingsIncomplete(RuntimeError):
    """A bot token without the owner's id, or the id without the token — M37.1.

    Refused at boot rather than tolerated, because the two halves only make sense
    together: a token with no owner is a bot that would answer whoever finds it, and an
    owner id with no token is a bot nobody can start. Either is one typo away from the
    other, and the sentence names both variables so the fix is the line that is missing.

    A ``RuntimeError`` and not a pydantic ``ValueError``, for ``OperatorHashMalformed``'s
    reason, measured again here: a ``ValueError`` out of a MODEL validator becomes a
    ``ValidationError`` whose text quotes the whole input it was validating — this
    process's secret key, the operator's hash and the bot token, on every failed boot,
    into whatever collects container output. Pydantic leaves any other exception alone.
    """


class Settings(BaseSettings):
    """Runtime configuration, read from ``HASHI_``-prefixed environment vars."""

    # ``env_ignore_empty`` — M31.2: a variable that is SET BUT BLANK is read as not set,
    # so the field takes the default written below. That is what lets
    # deploy/docker-compose.yml pass an optional setting through as ``${VAR:-}``: the
    # compose file is the whole list of what this process can read, a setting missing
    # from it does not exist in here however carefully the operator set it (the field
    # walk set HASHI_FINDING_REMEASURE_INTERVAL and ``env`` inside the container showed
    # nothing), and a blank pass-through with the default kept HERE is one default
    # rather than a second copy in the compose file that drifts from this one.
    #
    # It loosens nothing a required field relies on: a blank ``HASHI_SECRET_KEY`` or
    # operator hash is now "missing" rather than "too short" or "malformed", which
    # refuses to boot exactly as loudly.
    model_config = SettingsConfigDict(env_prefix="HASHI_", env_ignore_empty=True)

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

    # The certificate every delivery host is served under, and its private key, by path
    # on THIS host — M27.6. One wildcard for the fleet: a certificate per delivery host
    # would publish each Russian entry's name in a Certificate Transparency log as it
    # was issued, which is a feed anyone can subscribe to.
    #
    # BOTH EMPTY IS A SUPPORTED MODE and is the default: no host then serves
    # subscription refreshes of its own, every user refreshes against this control plane
    # exactly as they did before, and the co-located arrangements — where that is the
    # same box anyway — need neither of these set. They are NOT the switch M27.4 forbids:
    # a certificate is material, like ``secret_key``, and setting one cannot produce the
    # wrong arrangement. Which hosts serve delivery is derived and has no setting.
    #
    # A PATH rather than the material, so that renewal replaces a file and needs no
    # migration, no screen and no restart — the pair is read per apply and never cached.
    delivery_certificate_path: str = ""
    delivery_key_path: str = ""

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
    # another as degraded while its user's ping was 0% loss. Both readings were true
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

    # How often, in seconds, this control plane re-measures a node that is IN SERVICE and
    # carries a finding — fix round 5, walk 4's fourth finding. The walk saw a node serving
    # at 0% loss 35 seconds after an apply's wait ended, with the panel still reading the
    # verdict, because nothing measured again until a human pressed probe. Sixty seconds
    # because a slow host's late start is the case, and it is measured in tens of seconds;
    # and because each pass dials only the nodes that carry a finding, so a healthy fleet
    # costs nothing. ``0`` turns it off — a setting rather than a constant for the
    # settle window's reason: it is what a real fleet (or this test suite) has to be able
    # to change. See ``services/health.remeasure_findings`` for what it may and may not do.
    finding_remeasure_interval: float = Field(default=60.0, ge=0)

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

    # Where this control plane READS the backup record from — M28.6. The file is written
    # on the host by scripts/backup-run.sh after every run and mounted in here read-only
    # (deploy/docker-compose.yml), which is what lets the panel report what the host
    # recorded while being unable to invent a success or erase a failure.
    #
    # The default IS the mount point, so nothing has to be added to an env file for the
    # panel to answer — and a machine where the mount arrived empty, or where this
    # process is not running beside the backups at all, is a file that is not there,
    # which the panel reads as "nothing recorded" rather than as an error.
    #
    # A setting rather than a constant for the reason the two node ceilings above are
    # settings: the suite points it at a record it wrote itself, which is how it stays
    # honest that the value is read at all.
    backup_record: pathlib.Path = pathlib.Path("/var/lib/hashi/backup/last-run.json")

    # THE BACKUP'S QUIET HOUR, read here too — M34. ``HASHI_BACKUP_AT`` (HH:MM) in
    # ``HASHI_BACKUP_TZ`` (an IANA zone name) is when scripts/backup-run.sh takes the day's
    # backup, and it is also when this control plane refreshes the routing lists and
    # applies the entries whose config they changed: applying restarts Xray, which drops
    # every connected user for a second or two, so it belongs in the one hour the owner
    # has already said is quiet. One setting for both, so the two jobs cannot drift into
    # two "quiet" hours.
    #
    # NOT VALIDATED HERE, and that is deliberate: scripts/backup-run.sh tolerates a
    # malformed hour (it uses 04:00) and an unknown or empty zone (it uses the host's
    # clock) and records which, so a typo there must not become a control plane that
    # refuses to boot. ``services/routing_refresh.quiet_hour`` reads them with the same
    # tolerance and the Routing screen says which fallback it took.
    backup_at: str = "04:00"
    backup_tz: str = ""

    # How often, in seconds, the routing refresh asks whether tonight's run is due. It
    # decides nothing about the hour — ``backup_at`` does — so a control plane that was
    # down at that hour still runs the day's refresh when it comes back that day. ``0``
    # turns the nightly refresh off entirely; "fetch now" on the Routing screen still works.
    routing_check_interval: float = Field(default=900.0, ge=0)

    # The bounds a fetched list is held by (``services/routing``). A version that breaks
    # one is HELD for the owner with its diff, never applied — the owner's rule for a
    # suspicious change. Settings rather than constants so a fleet can loosen them and the
    # suite can tighten them.
    #
    # ``routing_max_change``: the largest fraction a list may grow or shrink by in one
    # fetch. 0.5 means a list of 40 may become 20–60.
    routing_max_change: float = Field(default=0.5, gt=0)
    # ``routing_max_entries``: the most entries one list may hold, and the most a node's
    # rendered config may carry across every list together. The lists are written into
    # the config inline (``edge/direct.py``), twice for names (routing and lookup), so this
    # is what bounds the file a node is sent; 20000 was measured to load in the pinned Xray
    # in well under a second (docs/decisions.md, M34).
    routing_max_entries: int = Field(default=20000, ge=1)
    # ``routing_max_bytes``: the most a single fetch may download. A body past it is a
    # failed fetch and the version in force stays — never a truncated list.
    routing_max_bytes: int = Field(default=4_000_000, ge=1024)
    # ``routing_fetch_timeout``: seconds for one fetch, connect and read together.
    routing_fetch_timeout: float = Field(default=30.0, gt=0)

    # The sources the Routing screen OFFERS to add, as ``name|https-url|on-or-off`` entries
    # separated by ``;``. Configuration and not code (``CLAUDE.md``: no hardcoded domain):
    # the defaults are in deploy/docker-compose.yml, an empty value offers nothing, and an
    # entry becomes a source only when the owner adds it. ``on`` is whether it is switched
    # on once added — the narrow list is, the broader ones are not.
    routing_suggested_sources: str = ""

    # THE OWNER'S TELEGRAM BOT — M37. Both blank is the default and means OFF: no task
    # starts, nothing dials out, and the stand and every existing install change nothing.
    # Both set turns it on; one without the other is refused below.
    #
    # The token is a bearer credential — every Bot API call carries it in the URL path,
    # the way ``/sub/`` carries a subscription's — so it is a ``SecretStr``: ``repr`` of
    # these settings prints asterisks, and the one place that needs the value
    # (``services/telegram_api``) asks for it explicitly. ``secret_key`` and the hash
    # above predate this choice and are plain strings; nothing reads them through
    # ``repr`` either, but the bot's token travels through more code than they do.
    #
    # The owner is a NUMERIC ID, not a username: a username can be changed and reassigned,
    # the id cannot (docs/PLAN.md, M37). Positive because that is what a Telegram user's
    # id is — a negative id names a group or a channel, which the bot must never take
    # commands from, and zero names nobody.
    telegram_bot_token: SecretStr | None = None
    telegram_owner_id: int | None = Field(default=None, gt=0)

    # Where the Bot API is dialled. A SETTING with a default rather than a constant in the
    # client, because this process runs on the entry box, in Russia, and whether
    # Telegram's own endpoint answers from there is a field fact no stand can see; if it
    # does not, this is where a relay goes. The e2e stand points it at a fake.
    telegram_api_url: str = "https://api.telegram.org"

    @field_validator("telegram_bot_token", mode="before")
    @classmethod
    def _blank_token_is_no_token(cls, value: object) -> object:
        """A blank token is OFF on every path, not just the environment's.

        ``env_ignore_empty`` already reads a blank variable as unset; this makes a blank
        passed by a caller — ``Settings(telegram_bot_token="")`` — mean the same thing,
        so that "both blank means off" is one rule rather than one per source.
        """
        return None if value == "" else value

    @model_validator(mode="after")
    def _telegram_is_both_or_neither(self) -> Self:
        """Refuse half a pair at boot, naming both halves. See the exception."""
        if (self.telegram_bot_token is None) != (self.telegram_owner_id is None):
            raise TelegramSettingsIncomplete(
                "HASHI_TELEGRAM_BOT_TOKEN and HASHI_TELEGRAM_OWNER_ID are set together or "
                "not at all: the token is the bot and the id is the one account it answers, "
                "and one without the other is either a bot that would answer anyone or a "
                "bot nobody can start. Set the missing one, or blank both to leave the "
                "bot off. Refusing to start."
            )
        return self

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
        """The origin a user's client dials. Built here, so nothing hardcodes it."""
        scheme = "https" if self.public_https else "http"
        return f"{scheme}://{self.public_host}"


# The one ``Settings`` this process is running on, bound once at boot.
#
# IT LIVES HERE rather than beside any one service, which is where it used to be
# (``services/apply``), because more than one service now needs it and the import that
# would take: ``apply`` imports ``nodes``, ``placement`` and ``relay``, so any of those
# reaching back for it is a cycle. This module imports nothing from ``services`` and can
# never grow a cycle with one.
#
# WHAT READS IT IS A BOUNDARY AND NEVER A RULE. A service function that is the entry
# point of an operation reads the binding; the rule it then applies takes the value as an
# argument (``placement.delivery_socket_is_free``). A rule that read a process-wide global
# would be a rule no test could state a premise for.
_bound: Settings | None = None


def bind_settings(settings: Settings) -> None:
    global _bound
    _bound = settings


def bound_settings() -> Settings:
    """The bound settings, or a loud failure rather than a default nobody chose."""
    if _bound is None:
        raise RuntimeError("bind_settings() must run before any node operation")
    return _bound
