"""The routing lists: fetched, versioned, held when suspicious, and turned into render data — M34.

WHAT: everything `control` does with the lists that decide which destinations an entry node
      opens by its own route — parsing a published list, fetching one (``fetch_text``), the
      rules a new version is HELD by, approving and rejecting a held version, the owner's
      own two lists, each node's switch, ``direct_routes_for`` (what ``apply`` hands a
      splitting transport), the lookup ("where would this go?") and what the Routing screen
      shows.
WHY:  the owner's shape, settled 2026-10-03 (docs/PLAN.md, M34): the control plane fetches
      and the node never does; a list that cannot be fetched leaves the last good version in
      force; a change that trips a bound waits for the owner with its diff; *never direct*
      beats everything. Each of those is a rule about DATA the control database holds, so
      they live here and ``edge`` sees only the result, as plain values.
HOW:  the database is the source of truth: a version is a row (``models/routing.py``) whose
      content is already in ``edge.direct``'s canonical form, one entry per line, so what is
      diffed, shown and rendered is one text. A fetch runs in a worker thread
      (``asyncio.to_thread``) so it never holds the event loop, and never on a page
      render: the screen reads rows, and fetching is the nightly job's or the owner's
      "fetch now".

**Nothing here records use.** Nothing counts a match, keeps a "last hit" or asks a node what
it carried. The lookup answers from the lists alone and writes nothing.
"""

import asyncio
import dataclasses
import datetime
import hashlib
import ipaddress
import logging
import ssl
import urllib.error
import urllib.request
from collections.abc import Sequence
from urllib.parse import urlsplit

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.errors import ConfigRefused, Conflict, DomainError, NotFound
from control.app.models import (
    AuditAction,
    Node,
    OwnerList,
    RoutingListVersion,
    RoutingOwnerEntry,
    RoutingSource,
    VersionStatus,
)
from control.app.services import audit, relay
from edge.direct import (
    Destinations,
    DirectRoutes,
    NotADestination,
    direct_resolver_problem,
    match,
    normalise_name,
    normalise_network,
)

logger = logging.getLogger(__name__)

# How many versions of one source are kept beyond the one in force and any held one. Enough
# to read what a list looked like last week; a source refreshed nightly that changes nightly
# would otherwise grow without end.
KEPT_VERSIONS = 10

# How many added and removed entries a diff shows by name. The counts are always whole.
DIFF_SHOWN = 30

# The prefixes of the v2fly ``domain-list-community`` text format, which several published
# lists use. ``domain:`` and a bare line mean a name and everything under it, ``full:`` the
# name alone; the other three are forms no destination rule here can carry — a pattern, a
# substring, another file — and are COUNTED as skipped rather than guessed at.
_SUFFIX = "domain:"
_EXACT = "full:"
_UNCARRIED = ("keyword:", "regexp:", "include:")


class FetchFailed(Exception):
    """A list could not be fetched. ``str()`` is a sentence composed here, safe to show.

    Never the text a remote host sent and never an exception's own message, which can
    carry an address or a path: the screen shows this, and the log line beside it is
    written with nobody watching.
    """


# --- the version grammar ----------------------------------------------------------------


def _line_for_name(name: str, *, exact: bool) -> str:
    return f"={name}" if exact else name


def destinations_of(lines: Sequence[str]) -> Destinations:
    """The canonical lines of a version (or of the owner's lists) as ``edge`` values."""
    suffixes, names, networks = [], [], []
    for line in lines:
        if "/" in line:
            networks.append(line)
        elif line.startswith("="):
            names.append(line[1:])
        else:
            suffixes.append(line)
    return Destinations.of(suffixes=suffixes, names=names, networks=networks)


def _canonical_line(value: str) -> str:
    """One owner-typed destination as a version line: a network, or a name and below it."""
    text = value.strip()
    if not text:
        raise NotADestination("an empty entry")
    looks_like_address = text[0].isdigit() or ":" in text
    if looks_like_address:
        try:
            return normalise_network(text)
        except NotADestination:
            pass
    return normalise_name(text)


@dataclasses.dataclass(frozen=True)
class Parsed:
    """What one fetched body holds, in canonical form."""

    entries: tuple[str, ...]
    skipped: int
    invalid: int
    # The first few lines that were not a destination, cut short. Remote text — shown
    # escaped, like every value on the screen, and never written to the log.
    invalid_examples: tuple[str, ...] = ()


def parse_list(body: str) -> Parsed:
    """Read a published list: one destination per line, comments after ``#``.

    Every line is either a network (an address or a CIDR, either family), a name (the name
    and everything under it), or one of the v2fly prefixes (``domain:``, ``full:``; the
    uncarried ones are counted as skipped). v2fly attributes (`` @ads``) are dropped. A
    line that is none of those is INVALID, and any invalid line holds the version: a list
    host that answers with an error page in place of its list must not become a list.
    """
    entries: set[str] = set()
    skipped = invalid = 0
    examples: list[str] = []
    for raw in body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        head, *rest = line.split()
        if rest and not all(token.startswith("@") for token in rest):
            invalid += 1
            if len(examples) < 3:
                examples.append(line[:80])
            continue
        lowered = head.lower()
        try:
            if lowered.startswith(_UNCARRIED):
                skipped += 1
                continue
            if lowered.startswith(_SUFFIX):
                entries.add(normalise_name(head[len(_SUFFIX) :]))
            elif lowered.startswith(_EXACT):
                entries.add(_line_for_name(normalise_name(head[len(_EXACT) :]), exact=True))
            else:
                entries.add(_canonical_line(head))
        except NotADestination:
            invalid += 1
            if len(examples) < 3:
                examples.append(line[:80])
    return Parsed(
        entries=tuple(sorted(entries)),
        skipped=skipped,
        invalid=invalid,
        invalid_examples=tuple(examples),
    )


def digest_of(entries: Sequence[str]) -> str:
    return hashlib.sha256("\n".join(entries).encode()).hexdigest()


def hold_reason(
    parsed: Parsed, previous_count: int | None, *, max_change: float, max_entries: int
) -> str | None:
    """Why this version must wait for the owner, or ``None`` if it may go into force.

    The owner's three bounds: the FORMAT (any line that is not a destination, or no
    entries at all), the SIZE (more entries than a node's config is allowed to carry) and
    the RATIO (a list that grew or shrank by more than ``max_change`` in one fetch). The
    ratio is not asked of a source's first version — there is nothing to compare it with,
    and the owner has just added it on purpose.
    """
    count = len(parsed.entries)
    if parsed.invalid:
        shown = "; ".join(repr(example) for example in parsed.invalid_examples)
        return (
            f"{parsed.invalid} line(s) are not a name or a network ({shown}). A list host "
            "that answers with something other than its list looks exactly like this."
        )
    if count == 0:
        return "the list came back with no entries at all."
    if count > max_entries:
        return (
            f"it holds {count} entries, more than the {max_entries} a node's config may "
            "carry (HASHI_ROUTING_MAX_ENTRIES)."
        )
    if previous_count:
        change = (count - previous_count) / previous_count
        if abs(change) > max_change:
            verb = "grew" if change > 0 else "shrank"
            return (
                f"it {verb} from {previous_count} to {count} entries — more than "
                f"{max_change:.0%} in one fetch (HASHI_ROUTING_MAX_CHANGE)."
            )
    return None


# --- fetching -----------------------------------------------------------------------------


def url_problem(url: str) -> str | None:
    """Why ``url`` cannot be a source, or ``None``. HTTPS only.

    A list fetched in the clear can be rewritten by any network between this control plane
    and the list's host — and on a control plane inside Russia that network is the one
    whose sites this list is about. The rewritten list would go into force at night.
    """
    text = url.strip()
    if len(text) > 2048:
        return "that address is longer than 2048 characters."
    parts = urlsplit(text)
    if parts.scheme != "https" or not parts.hostname:
        return "give an https:// address — a list fetched in the clear can be rewritten on the way."
    if parts.username or parts.password:
        return (
            "an address with a user name or password in it would put a credential in "
            "the database."
        )
    return None


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to another https address; refuse a downgrade."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != "https":
            raise FetchFailed("the list's host redirected to an address that is not https.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_text(url: str, *, timeout: float, max_bytes: int) -> str:
    """GET ``url`` and return its body as text, or raise ``FetchFailed``. Blocking.

    Called through ``asyncio.to_thread`` and nowhere else. The standard library's
    ``urllib`` rather than a dependency: one GET with a timeout and a size cap needs no
    more, and a new dependency is an architect's decision this feature does not need.
    No custom User-Agent — a header naming this project is a header that identifies every
    control plane running it.
    """
    opener = urllib.request.build_opener(_HttpsOnlyRedirects())
    try:
        with opener.open(urllib.request.Request(url), timeout=timeout) as response:
            if response.status != 200:
                raise FetchFailed(f"the list's host answered HTTP {response.status}.")
            body = response.read(max_bytes + 1)
    except FetchFailed:
        raise
    except urllib.error.HTTPError as exc:
        raise FetchFailed(f"the list's host answered HTTP {exc.code}.") from None
    except TimeoutError:
        raise FetchFailed(f"the list's host did not answer within {timeout:.0f} seconds.") from None
    except ssl.SSLError:
        raise FetchFailed(
            "the list's host did not present a certificate this machine trusts."
        ) from None
    except (urllib.error.URLError, OSError) as exc:
        raise FetchFailed(
            f"the list's host could not be reached ({type(exc).__name__})."
        ) from None
    if len(body) > max_bytes:
        raise FetchFailed(
            f"the list is larger than {max_bytes} bytes (HASHI_ROUTING_MAX_BYTES); nothing "
            "was kept from it."
        )
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise FetchFailed("the list is not text.") from None


@dataclasses.dataclass(frozen=True)
class Refreshed:
    """What one source's refresh did, in words the screen and the log can both carry."""

    source: str
    outcome: str  # "in force", "unchanged", "held", "failed", "rejected before", "still held"
    detail: str | None = None


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


async def in_force(session: AsyncSession, source_id: str) -> RoutingListVersion | None:
    result = await session.execute(
        select(RoutingListVersion)
        .where(RoutingListVersion.source_id == source_id)
        .where(RoutingListVersion.status == VersionStatus.IN_FORCE)
    )
    return result.scalars().first()


async def _versions(
    session: AsyncSession, source_id: str, status: VersionStatus
) -> list[RoutingListVersion]:
    result = await session.execute(
        select(RoutingListVersion)
        .where(RoutingListVersion.source_id == source_id)
        .where(RoutingListVersion.status == status)
        .order_by(RoutingListVersion.fetched_at)
    )
    return list(result.scalars())


async def take_in(
    session: AsyncSession,
    source: RoutingSource,
    body: str,
    *,
    max_change: float,
    max_entries: int,
    now: datetime.datetime,
) -> Refreshed:
    """Decide what one fetched body becomes, and write it. Does not commit.

    Split from the fetch so the rules can be stated without a network: the same body as
    the version in force changes nothing; a body the owner already rejected is not put in
    front of them again every night; anything else becomes a new version, in force or held.
    """
    parsed = parse_list(body)
    digest = digest_of(parsed.entries)
    current = await in_force(session, source.id)
    if current is not None and current.digest == digest:
        return Refreshed(source.name, "unchanged")
    for status, outcome in (
        (VersionStatus.HELD, "still held"),
        (VersionStatus.REJECTED, "rejected before"),
    ):
        if any(v.digest == digest for v in await _versions(session, source.id, status)):
            return Refreshed(source.name, outcome)

    reason = hold_reason(
        parsed,
        current.count if current is not None else None,
        max_change=max_change,
        max_entries=max_entries,
    )
    # One pending decision per source: a newer held version replaces an older one, and a
    # version that goes into force replaces both.
    for older in await _versions(session, source.id, VersionStatus.HELD):
        older.status = VersionStatus.SUPERSEDED
        older.decided_at = now
    if reason is None and current is not None:
        current.status = VersionStatus.SUPERSEDED
        current.decided_at = now
    # Flushed before the new row, because the index allows one version in force per source
    # and the old one has to have left that state first.
    await session.flush()
    session.add(
        RoutingListVersion(
            source_id=source.id,
            fetched_at=now,
            digest=digest,
            entries="\n".join(parsed.entries),
            count=len(parsed.entries),
            skipped=parsed.skipped,
            invalid=parsed.invalid,
            status=VersionStatus.HELD if reason else VersionStatus.IN_FORCE,
            hold_reason=reason,
            decided_at=None if reason else now,
        )
    )
    await session.flush()
    await _prune(session, source.id)
    if reason:
        return Refreshed(source.name, "held", reason)
    return Refreshed(source.name, "in force", f"{len(parsed.entries)} entries")


async def _prune(session: AsyncSession, source_id: str) -> None:
    """Keep the version in force, any held one, and the newest ``KEPT_VERSIONS`` others."""
    result = await session.execute(
        select(RoutingListVersion.id)
        .where(RoutingListVersion.source_id == source_id)
        .where(
            RoutingListVersion.status.in_(
                (VersionStatus.SUPERSEDED, VersionStatus.REJECTED)
            )
        )
        .order_by(RoutingListVersion.fetched_at.desc())
        .offset(KEPT_VERSIONS)
    )
    stale = list(result.scalars())
    if stale:
        await session.execute(
            delete(RoutingListVersion).where(RoutingListVersion.id.in_(stale))
        )


async def refresh_source(
    session: AsyncSession, source: RoutingSource, settings, *, now: datetime.datetime | None = None
) -> Refreshed:
    """Fetch one source and take in what came back. Commits.

    A failed fetch writes only the attempt and its sentence: the version in force is not
    touched, which is the owner's rule — the last good list stays.
    """
    now = now or _now()
    source.last_attempt_at = now
    try:
        body = await asyncio.to_thread(
            fetch_text,
            source.url,
            timeout=settings.routing_fetch_timeout,
            max_bytes=settings.routing_max_bytes,
        )
    except FetchFailed as exc:
        source.last_error = str(exc)
        await session.commit()
        logger.warning("routing source %s was not refreshed: %s", source.name, exc)
        return Refreshed(source.name, "failed", str(exc))
    source.last_error = None
    outcome = await take_in(
        session,
        source,
        body,
        max_change=settings.routing_max_change,
        max_entries=settings.routing_max_entries,
        now=now,
    )
    await session.commit()
    logger.info("routing source %s: %s", source.name, outcome.outcome)
    return outcome


async def refresh_all(session: AsyncSession, settings) -> list[Refreshed]:
    """Refresh every source that is switched on, one after another."""
    sources = await list_sources(session)
    return [
        await refresh_source(session, source, settings)
        for source in sources
        if source.enabled
    ]


# --- the owner's decisions ---------------------------------------------------------------


async def _held(session: AsyncSession, version_id: str) -> RoutingListVersion:
    version = await session.get(RoutingListVersion, version_id)
    if version is None:
        raise NotFound("that update no longer exists.")
    if version.status is not VersionStatus.HELD:
        raise Conflict("that update is no longer waiting for a decision.")
    return version


async def approve(session: AsyncSession, version_id: str) -> RoutingSource:
    """Put a held version into force. It renders at the next apply of each entry."""
    version = await _held(session, version_id)
    source = await session.get(RoutingSource, version.source_id)
    now = _now()
    current = await in_force(session, version.source_id)
    if current is not None:
        current.status = VersionStatus.SUPERSEDED
        current.decided_at = now
        await session.flush()
    version.status = VersionStatus.IN_FORCE
    version.decided_at = now
    audit.record(session, AuditAction.ROUTING_UPDATE_APPROVED, first_label=source.name)
    await session.commit()
    return source


async def reject(session: AsyncSession, version_id: str) -> RoutingSource:
    """Refuse a held version. The version in force stays, and this content is not asked again."""
    version = await _held(session, version_id)
    source = await session.get(RoutingSource, version.source_id)
    version.status = VersionStatus.REJECTED
    version.decided_at = _now()
    audit.record(session, AuditAction.ROUTING_UPDATE_REJECTED, first_label=source.name)
    await session.commit()
    return source


# --- sources -----------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Suggested:
    name: str
    url: str
    on: bool


def suggested_sources(configured: str) -> list[Suggested]:
    """``HASHI_ROUTING_SUGGESTED_SOURCES`` read: ``name|url|on-or-off`` entries split by ``;``.

    An entry that does not read — too few fields, a name that is not a name, an address
    that is not https — is left out and logged by its position only, so a typo in the env
    file costs one suggestion rather than the screen.
    """
    found: list[Suggested] = []
    for position, entry in enumerate(configured.split(";"), start=1):
        entry = entry.strip()
        if not entry:
            continue
        fields = [field.strip() for field in entry.split("|")]
        if len(fields) != 3 or fields[2] not in ("on", "off"):
            logger.warning("suggested routing source %d is not name|url|on-or-off", position)
            continue
        name, url, on = fields
        if name_problem(name) or url_problem(url):
            logger.warning("suggested routing source %d has an unusable name or address", position)
            continue
        found.append(Suggested(name=name, url=url, on=on == "on"))
    return found


def name_problem(name: str) -> str | None:
    text = name.strip()
    if not text:
        return "give the source a name."
    if len(text) > 64:
        return "a source's name is at most 64 characters."
    return None


async def list_sources(session: AsyncSession) -> list[RoutingSource]:
    result = await session.execute(select(RoutingSource).order_by(RoutingSource.name))
    return list(result.scalars())


async def add_source(
    session: AsyncSession, *, name: str, url: str, enabled: bool
) -> RoutingSource:
    """Add a source. Nothing is fetched here — "fetch now" or the nightly refresh does that."""
    problem = name_problem(name) or url_problem(url)
    if problem:
        raise DomainError(problem)
    name, url = name.strip(), url.strip()
    existing = await session.execute(select(RoutingSource).where(RoutingSource.name == name))
    if existing.scalars().first() is not None:
        raise Conflict(f"there is already a source called {name}.")
    source = RoutingSource(name=name, url=url, enabled=enabled)
    session.add(source)
    audit.record(session, AuditAction.ROUTING_SOURCE_ADDED, first_label=name)
    await session.commit()
    return source


async def get_source(session: AsyncSession, source_id: str) -> RoutingSource:
    source = await session.get(RoutingSource, source_id)
    if source is None:
        raise NotFound("that source no longer exists.")
    return source


async def switch_source(session: AsyncSession, source_id: str, *, enabled: bool) -> RoutingSource:
    source = await get_source(session, source_id)
    source.enabled = enabled
    audit.record(
        session,
        AuditAction.ROUTING_SOURCE_SWITCHED,
        first_label=source.name,
        second_label="on" if enabled else "off",
    )
    await session.commit()
    return source


async def remove_source(session: AsyncSession, source_id: str) -> str:
    """Remove a source and every version of it. Returns its name."""
    source = await get_source(session, source_id)
    name = source.name
    await session.delete(source)
    audit.record(session, AuditAction.ROUTING_SOURCE_REMOVED, first_label=name)
    await session.commit()
    return name


# --- the owner's two lists ---------------------------------------------------------------

LIST_NAMES = {OwnerList.ALWAYS: "always direct", OwnerList.NEVER: "never direct"}


async def owner_entries(session: AsyncSession) -> dict[OwnerList, list[RoutingOwnerEntry]]:
    result = await session.execute(
        select(RoutingOwnerEntry).order_by(RoutingOwnerEntry.value)
    )
    found: dict[OwnerList, list[RoutingOwnerEntry]] = {kind: [] for kind in OwnerList}
    for entry in result.scalars():
        found[entry.list].append(entry)
    return found


async def add_owner_entry(
    session: AsyncSession, *, which: OwnerList, value: str
) -> RoutingOwnerEntry:
    """Add a name (it and every name under it) or a network to one of the owner's lists."""
    try:
        line = _canonical_line(value)
    except NotADestination as exc:
        raise DomainError(f"{exc} — give a name such as gosuslugi.ru, or a network.") from None
    existing = await session.execute(
        select(RoutingOwnerEntry)
        .where(RoutingOwnerEntry.list == which)
        .where(RoutingOwnerEntry.value == line)
    )
    if existing.scalars().first() is not None:
        raise Conflict(f"{line} is already on {LIST_NAMES[which]}.")
    entry = RoutingOwnerEntry(list=which, value=line)
    session.add(entry)
    audit.record(
        session, AuditAction.ROUTING_LIST_CHANGED, first_label=LIST_NAMES[which]
    )
    await session.commit()
    return entry


async def remove_owner_entry(session: AsyncSession, entry_id: str) -> RoutingOwnerEntry:
    entry = await session.get(RoutingOwnerEntry, entry_id)
    if entry is None:
        raise NotFound("that entry is no longer on the list.")
    await session.delete(entry)
    audit.record(
        session, AuditAction.ROUTING_LIST_CHANGED, first_label=LIST_NAMES[entry.list]
    )
    await session.commit()
    return entry


# --- a node's switch, and what it renders -------------------------------------------------

NO_DIRECT_RESOLVER = (
    "this node sends listed sites out by its own route, and its record names no resolver "
    "for their names. Without one they would be looked up through the hop, abroad, and a "
    "site that answers foreign addresses differently would answer wrongly. Set one in "
    "this node's direct-sites dialog, or switch it off."
)


async def set_direct_routing(
    session: AsyncSession,
    *,
    node_id: str,
    on: bool,
    resolver: str,
    has_hop: bool,
) -> Node:
    """Switch a node's direct routing on or off, with its entry-side resolver.

    Switching ON needs a hop — without one every destination already leaves from this
    node, so there is nothing to choose — and a resolver ``edge`` will render
    (``direct_resolver_problem``). Switching off keeps the resolver, so switching back on is
    one press. This changes the record, not the host: the node's next apply carries it.
    """
    node = await session.get(Node, node_id)
    if node is None:
        raise NotFound("that node no longer exists.")
    resolver = resolver.strip()
    if on:
        if not has_hop:
            raise DomainError(
                "this node dials no hop, so every destination already leaves from its own "
                "address; there is nothing to send out directly. Establish a hop first."
            )
        if not resolver:
            raise DomainError(
                "give the resolver this node looks the listed sites up at — one on its own "
                "side of the border."
            )
    if resolver:
        problem = direct_resolver_problem(resolver, node.resolver)
        if problem:
            raise DomainError(problem)
    node.direct_routing = on
    node.direct_resolver = resolver or None
    audit.record(
        session,
        AuditAction.DIRECT_ROUTING_SET,
        first_label=node.name,
        second_label="on" if on else "off",
    )
    await session.commit()
    return node


@dataclasses.dataclass(frozen=True)
class Lists:
    """Every list in force right now, by where it came from."""

    sources: tuple[tuple[str, tuple[str, ...]], ...]  # (source name, lines), enabled only
    always: tuple[str, ...]
    never: tuple[str, ...]

    def direct_lines(self) -> list[str]:
        lines = {line for _, lines in self.sources for line in lines}
        lines.update(self.always)
        return sorted(lines)

    def size(self) -> int:
        return len(self.direct_lines()) + len(self.never)


async def lists_in_force(session: AsyncSession) -> Lists:
    sources = []
    for source in await list_sources(session):
        if not source.enabled:
            continue
        version = await in_force(session, source.id)
        lines = tuple(version.entries.splitlines()) if version and version.entries else ()
        sources.append((source.name, lines))
    owned = await owner_entries(session)
    return Lists(
        sources=tuple(sources),
        always=tuple(entry.value for entry in owned[OwnerList.ALWAYS]),
        never=tuple(entry.value for entry in owned[OwnerList.NEVER]),
    )


async def direct_routes_for(
    session: AsyncSession, node: Node, *, max_entries: int
) -> DirectRoutes | None:
    """What a splitting transport on ``node`` is handed, or ``None`` with the switch off.

    ``None`` is what every node renders with unless its owner switched this on, and it is
    what keeps such a node's config byte for byte what it was before M34. With the switch
    on and nothing in any list, the value is still built — ``edge`` renders an empty
    direct list as no list at all.
    """
    if not node.direct_routing:
        return None
    if not node.direct_resolver:
        raise ConfigRefused(NO_DIRECT_RESOLVER)
    lists = await lists_in_force(session)
    if lists.size() > max_entries:
        raise ConfigRefused(
            f"the routing lists in force hold {lists.size()} entries together, more than "
            f"the {max_entries} a node's config may carry (HASHI_ROUTING_MAX_ENTRIES). "
            "Switch a source off on the Routing screen, or raise the bound."
        )
    return DirectRoutes(
        resolver=node.direct_resolver,
        direct=destinations_of(lists.direct_lines()),
        never=destinations_of(lists.never),
    )


# --- where would it go? ------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Verdict:
    destination: str
    direct: bool | None  # None: not a destination at all
    sentence: str
    note: str | None = None


async def where(session: AsyncSession, destination: str) -> Verdict:
    """Where an entry with the switch on would send ``destination``, from the lists alone.

    The same precedence the rendered config has: *never direct* first, then *always
    direct*, then each source in force. A NAME is matched against names only; whether it
    also falls into a network depends on what it resolves to, which this panel does not
    ask (a lookup from here would be a query nobody needs, from the control plane's own
    network) — the note says so when any list holds networks.
    """
    text = destination.strip()
    if not text:
        return Verdict(text, None, "type a site's name or an address.")
    try:
        ipaddress.ip_address(text)
        is_address = True
    except ValueError:
        is_address = False
        try:
            normalise_name(text)
        except NotADestination as exc:
            return Verdict(text, None, f"{exc}.")
    lists = await lists_in_force(session)

    def first(lines: Sequence[str]) -> str | None:
        return match(text, destinations_of(lines))

    hit = first(lists.never)
    if hit:
        return Verdict(text, False, f"through the hop — on your never-direct list as {hit}.")
    hit = first(lists.always)
    if hit:
        return Verdict(
            text, True, f"directly from the entry — on your always-direct list as {hit}."
        )
    for name, lines in lists.sources:
        hit = first(lines)
        if hit:
            return Verdict(text, True, f"directly from the entry — listed by {name} as {hit}.")
    note = None
    every_line = (*lists.never, *lists.always, *lists.direct_lines())
    if not is_address and any("/" in line for line in every_line):
        note = (
            "a name is checked against names only: if it resolves to an address on a "
            "network list it follows that list. Type the address to check that."
        )
    return Verdict(text, False, "through the hop — on no list.", note)


# --- what the Routing screen shows --------------------------------------------------------
#
# The LISTS, never their use: a source, its versions, the owner's entries, which entries
# have the switch on. There is no count of anything a user did, here or anywhere a row
# below is read from.


def age(then: datetime.datetime | None, now: datetime.datetime) -> str:
    """How long ago, in the coarse words an owner reads a list's age in."""
    if then is None:
        return "never"
    seconds = (now - then).total_seconds()
    if seconds < 3600:
        return "less than an hour ago"
    if seconds < 86400:
        hours = int(seconds // 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = int(seconds // 86400)
    return f"{days} day{'s' if days != 1 else ''} ago"


@dataclasses.dataclass(frozen=True)
class Diff:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    added_count: int
    removed_count: int


def diff(old: str | None, new: str) -> Diff:
    before = set(old.splitlines()) if old else set()
    after = set(new.splitlines()) if new else set()
    added, removed = sorted(after - before), sorted(before - after)
    return Diff(
        added=tuple(added[:DIFF_SHOWN]),
        removed=tuple(removed[:DIFF_SHOWN]),
        added_count=len(added),
        removed_count=len(removed),
    )


@dataclasses.dataclass(frozen=True)
class SourceRow:
    id: str
    name: str
    url: str
    enabled: bool
    version: str | None  # the first 12 characters of the in-force digest
    count: int
    skipped: int
    fetched: str  # age of the version in force
    attempted: str  # age of the last attempt
    error: str | None
    changed: Diff | None  # the version in force against the one before it


@dataclasses.dataclass(frozen=True)
class HeldRow:
    id: str
    source: str
    fetched: str
    count: int
    reason: str
    diff: Diff


@dataclasses.dataclass(frozen=True)
class SwitchedOn:
    id: str
    name: str
    has_hop: bool
    resolver: str | None


@dataclasses.dataclass(frozen=True)
class RoutingScreen:
    switched_on: tuple[SwitchedOn, ...]
    sources: tuple[SourceRow, ...]
    held: tuple[HeldRow, ...]
    always: tuple[RoutingOwnerEntry, ...]
    never: tuple[RoutingOwnerEntry, ...]
    suggestions: tuple[Suggested, ...]
    size: int
    max_entries: int


async def screen(
    session: AsyncSession, settings, *, now: datetime.datetime | None = None
) -> RoutingScreen:
    now = now or _now()
    rows, held = [], []
    sources = await list_sources(session)
    for source in sources:
        result = await session.execute(
            select(RoutingListVersion)
            .where(RoutingListVersion.source_id == source.id)
            .order_by(RoutingListVersion.fetched_at.desc())
        )
        versions = list(result.scalars())
        current = next((v for v in versions if v.status is VersionStatus.IN_FORCE), None)
        before = None
        if current is not None:
            before = next(
                (
                    v
                    for v in versions
                    if v.status is VersionStatus.SUPERSEDED and v.fetched_at < current.fetched_at
                ),
                None,
            )
        rows.append(
            SourceRow(
                id=source.id,
                name=source.name,
                url=source.url,
                enabled=source.enabled,
                version=current.digest[:12] if current else None,
                count=current.count if current else 0,
                skipped=current.skipped if current else 0,
                fetched=age(current.fetched_at if current else None, now),
                attempted=age(source.last_attempt_at, now),
                error=source.last_error,
                changed=diff(before.entries, current.entries) if before and current else None,
            )
        )
        for version in versions:
            if version.status is VersionStatus.HELD:
                held.append(
                    HeldRow(
                        id=version.id,
                        source=source.name,
                        fetched=age(version.fetched_at, now),
                        count=version.count,
                        reason=version.hold_reason or "",
                        diff=diff(current.entries if current else None, version.entries),
                    )
                )
    switched = []
    for node in (await session.execute(
        select(Node).where(Node.direct_routing.is_(True)).order_by(Node.name)
    )).scalars().unique():
        switched.append(
            SwitchedOn(
                id=node.id,
                name=node.name,
                has_hop=await relay.exit_through_hop(session, node) is not None,
                resolver=node.direct_resolver,
            )
        )
    owned = await owner_entries(session)
    added = {source.name for source in sources}
    lists = await lists_in_force(session)
    return RoutingScreen(
        switched_on=tuple(switched),
        sources=tuple(rows),
        held=tuple(held),
        always=tuple(owned[OwnerList.ALWAYS]),
        never=tuple(owned[OwnerList.NEVER]),
        suggestions=tuple(
            suggestion
            for suggestion in suggested_sources(settings.routing_suggested_sources)
            if suggestion.name not in added
        ),
        size=lists.size(),
        max_entries=settings.routing_max_entries,
    )


async def add_suggested(session: AsyncSession, *, name: str, settings) -> RoutingSource:
    """Add one of the configured suggestions, switched on or off as configured."""
    for suggestion in suggested_sources(settings.routing_suggested_sources):
        if suggestion.name == name:
            return await add_source(
                session, name=suggestion.name, url=suggestion.url, enabled=suggestion.on
            )
    raise NotFound("that suggestion is not in this control plane's configuration.")


__all__ = [
    "FetchFailed",
    "Parsed",
    "Refreshed",
    "Suggested",
    "Verdict",
    "add_owner_entry",
    "add_source",
    "approve",
    "destinations_of",
    "direct_routes_for",
    "fetch_text",
    "hold_reason",
    "parse_list",
    "refresh_all",
    "refresh_source",
    "reject",
    "set_direct_routing",
    "suggested_sources",
    "take_in",
    "url_problem",
    "where",
]
