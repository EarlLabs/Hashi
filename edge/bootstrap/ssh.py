"""The only channel to a node.

WHAT: an async SSH connection wrapper — run a command, write a file, read a file.
WHY:  every node operation goes through here, so the properties that matter are
      enforced in one place: a timeout on everything, host-key pinning, and secrets
      written with restrictive permissions and never passed on a command line.
HOW:  ``asyncssh``. ``NodeTarget`` is a plain value object so `control` can build
      one from a database row without this module importing anything from `control`.

Two decisions worth reading before changing anything here:

**Everything has a timeout, and reaching a node has its own short one.** A
blocked or seized node does not refuse a connection — it accepts and then hangs.
Without a ceiling, one dead host blocks the panel request that was trying to replace
it, which is exactly when the operator needs the panel most. There are two ceilings
because they answer different questions: ``connect_timeout`` bounds getting a session
at all, ``timeout`` bounds one operation over a session that already exists. Every
``await`` that touches the network is under one of them — including the SFTP
transfers, which have no timeout of their own and are the way a node that answered
once can still hang a request forever.

**A secret never goes on the command line.** Arguments are world-readable in
``/proc`` on the node for the lifetime of the process. Configuration is written
over SFTP instead, to a file created 0600 before the bytes land in it.
"""

import asyncio
import errno
import logging
import socket
from dataclasses import dataclass

import asyncssh

logger = logging.getLogger(__name__)

# Why a session could not be opened, as a sentence rather than as the name of the class
# Python raised — M18's acceptance, and M9's before it, which filed the same leak and had
# it fixed in one place and not this one.
#
# ``could not establish an SSH session: gaierror`` is what an operator was reading on the
# apply, probe, rotate-keys and replace-params banners. Everything before the last word is
# plain English; the last word is ``socket.gaierror`` arriving through ``type(exc).__name__``
# and what it means is "this node's address does not resolve" — which is exactly the
# sentence the operator needed, and one they can act on without knowing what a gaierror is.
#
# ORDERED, AND SCANNED IN ORDER, because these are not disjoint: ``gaierror`` and
# ``ConnectionRefusedError`` are both ``OSError``. The list is short on purpose — one entry
# per cause an operator has a different next action for — and anything not on it falls
# through to the sentence below, which still names the class in brackets because on an
# unrecognised failure that is the only diagnostic there is.
#
# NOTHING HERE NAMES THE HOST, and nothing may: this text propagates into
# ``Node.state_detail`` and into an API response, where core invariants §4 keeps node
# addresses out. That is also why the exception's own message is never used — asyncssh's
# routinely carries the address it was dialling.
_WHY_NO_SESSION: tuple[tuple[type[BaseException], str], ...] = (
    (socket.gaierror, "this node's address could not be resolved"),
    (ConnectionRefusedError, "nothing accepted an SSH connection on that port"),
    (
        asyncssh.HostKeyNotVerifiable,
        "the node answered with a different host key than the one pinned for it, so the "
        "connection was abandoned rather than trusted",
    ),
    (
        asyncssh.PermissionDenied,
        "the node refused the key this control plane holds for it",
    ),
)

# The one cause an operator can act on that has no exception class of its own — M23,
# round 4, measured on a node registered with an address nothing routes to. ``could not
# establish an SSH session (OSError)`` was what the operator read — on the banner, in the
# node row's ``why:`` cell and in the probe — beside a neighbouring case that reads *"the
# node did not answer within 5s"*, which is what made this one stand out as the leak it is.
#
# Python gives ECONNREFUSED, ETIMEDOUT and their siblings a subclass each and gives these
# two nothing, so the table above cannot reach them by type and the fallback below is the
# only arm left. The errno IS the diagnosis: the network answered, and what it said was
# that there is no way to this address from here.
#
# BOTH, AND ONE SENTENCE FOR BOTH, on this file's own rule that the list carries one entry
# per cause an operator has a DIFFERENT next action for. ``EHOSTUNREACH`` is "that host,
# on a network we can reach" and ``ENETUNREACH`` is "that network"; the operator checks
# the same two things either way — the address on the record, and whether the host is up.
#
# NOTHING WIDER. An errno this control plane has no sentence for still falls through and
# still names its class, because the fallback exists so that an unknown cause is readable
# rather than silent, and a sentence invented for an errno nobody has met would be a guess
# printed with the confidence of a diagnosis.
_WHY_NO_ROUTE: frozenset[int] = frozenset({errno.EHOSTUNREACH, errno.ENETUNREACH})
_NO_ROUTE = "there is no route to this node's address from this control plane"

# Every recognised cause reads as a whole sentence, so the fallback does too — with the
# class in brackets at the end, since an unrecognised failure has nothing else to offer
# and the alternative is an operator told only that something went wrong.
_NO_SESSION_UNKNOWN = "could not establish an SSH session ({name})"

# How much of a failed command's own output the operator is shown, and WHICH END of it —
# M18's acceptance. This used to be ``stderr.strip()[:300]``, the FIRST 300 characters,
# which on the one command this project runs most is the worst possible choice: a
# `docker compose up` that has to pull first writes a progress line per image layer, so
# the operator was handed a screenful of layer ids with the actual error — which the
# daemon prints last, as every Unix tool does — cut off past the limit.
#
# The tail, then, and flattened to one line, which also makes the reason the single
# sentence every surface downstream assumes it is: this text becomes ``Node.state_detail``
# and an API message, and a multi-line one puts a report where a sentence belongs.
#
# THE RULE IS "THE LAST FEW MEANINGFUL LINES" AND NAMES NOTHING. No pattern for a layer
# id, no knowledge of what docker prints: this module is the SSH channel and knows only
# that it ran a command and the command failed. A filter written against one tool's
# progress format is a filter that silently eats the next tool's error.
#
# AND THE CEILING IS SPENT FROM THE END, WITH THE CUT MARKED — M18's acceptance, round 2.
# Taking the last three lines and then the first 300 characters OF THEM is two rules
# pulling opposite ways, and the second won: a mount failure arrived as
# ``Container hashi-node-wireguard-1 Creating; Container hashi-node-wireguard-1 Error
# response from daemon: failed to mount ...`` ending on ``daemon/i``. The progress line
# got the budget, the diagnosis got what was left, and the operator was given a sentence
# that stops mid-word with nothing to say it had been cut.
#
# So the LAST line is served first and earlier ones only with what is left over, which is
# the same reasoning that takes the tail in the first place — a tool prints its diagnosis
# last — applied one level down. Within a single line the HEAD is kept instead, because
# that is where a tool writes what went wrong before the detail it went wrong on; a line
# too long for the ceiling is cut at the end, not at the front.
#
# Still nothing about docker, and still nothing about progress displays: "later lines
# matter more, and the start of a line matters more than its end" is a fact about how
# programs write to stderr, not about which program wrote it.
_STDERR_LINES = 3
_STDERR_MAX = 300

# Where output was dropped, said rather than left to look like the end of the sentence.
# One character, because this text is read inside a banner and inside ``state_detail``,
# and a parenthetical explaining itself would cost more of the ceiling than it buys.
#
# It sits OUTSIDE ``_STDERR_MAX``, which bounds how much of the command's own output the
# operator is shown: the mark is this module's word about that output, not part of it, so
# a marked reason is the ceiling plus two characters rather than the ceiling minus two.
_ELIDED = "…"


class NodeUnreachable(Exception):
    """The node could not be reached, or the command failed.

    Deliberately one exception for both. A caller must treat "could not connect"
    and "the command exited non-zero" identically — in either case the node's real
    state is unknown, which means degraded rather than active.
    """


def _why_no_session(exc: BaseException) -> str:
    """The reason a connect failed, in the words an operator can act on.

    By TYPE first and by ``errno`` second, which is the order the two are specific in: a
    type that is on the list above says what it means whatever errno it carries, and the
    errno arm exists only for the causes Python gives no type to at all. Reading the errno
    off anything, rather than off ``OSError`` alone, because ``asyncssh.Error`` wrappers
    carry one too and the number means the same thing wherever it came from.

    The number is never shown, only consulted: the text beside it is the C library's, and
    that text can name the address it failed on.
    """
    for kind, reason in _WHY_NO_SESSION:
        if isinstance(exc, kind):
            return reason
    if getattr(exc, "errno", None) in _WHY_NO_ROUTE:
        return _NO_ROUTE
    return _NO_SESSION_UNKNOWN.format(name=type(exc).__name__)


def _what_it_said(stderr: str) -> str:
    """A failed command's own output, reduced to what an operator can read.

    ``splitlines`` rather than a split on ``\n``: a progress display rewrites one line
    with carriage returns, and each rewrite becomes its own line here — so the final
    state of it survives and the states it passed through drop off the front with
    everything else that is not among the last few.

    Built from the END backwards, so the ceiling is spent on the diagnosis rather than on
    whatever the command was printing before it. Anything dropped — an earlier line, or
    the tail of a line longer than the whole budget — leaves ``_ELIDED`` where it was, so
    a reason that is a fragment cannot be read as a reason that is a sentence.
    """
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    if not lines:
        return ""

    kept: list[str] = []
    room = _STDERR_MAX
    for line in reversed(lines[-_STDERR_LINES:]):
        room -= len(line) + (2 if kept else 0)
        if room < 0:
            if not kept:
                # The diagnosis alone is longer than the ceiling: keep its head, which is
                # where the command says what went wrong, and mark the cut.
                kept.append(line[: _STDERR_MAX - len(_ELIDED)] + _ELIDED)
            break
        kept.insert(0, line)

    # One entry in ``kept`` per line of the original that reached the operator — the
    # head-truncated one included, since it is still that line — so a shorter list is
    # exactly "an earlier line is missing", and the mark goes where it went missing.
    said = "; ".join(kept)
    if len(kept) < len(lines):
        said = f"{_ELIDED} {said}"
    return said


@dataclass(frozen=True)
class NodeTarget:
    """Where a node is and how to authenticate to it."""

    host: str
    port: int
    username: str

    # OpenSSH private key text. Held in memory only for the duration of a
    # connection; it lives encrypted in the database the rest of the time.
    private_key: str | None = None

    # The node's expected host key, recorded on first connect. When set, a
    # mismatch aborts the connection: a censor who can reroute an address can also
    # answer on port 22, and pinning is what makes that fail loudly instead of
    # handing our SSH session to whoever answered.
    host_key: str | None = None

    # The ceiling on ESTABLISHING a session: name resolution, TCP handshake and SSH
    # key exchange. Deliberately far shorter than ``timeout`` below, because a healthy
    # node on the other side of the world answers in well under a second and a blocked
    # one answers never — waiting longer only makes the operator watch a spinner
    # during exactly the outage they are trying to fix. Five seconds still covers
    # ordinary packet loss: Linux retransmits a SYN at t=0, 1s and 3s, so a lossy path
    # gets three attempts before we call the node unreachable.
    connect_timeout: int = 5

    # The ceiling on ONE operation over a session that already opened: a command, a
    # file transfer. Larger on purpose — pulling an image or restarting a stack
    # legitimately takes time, and a node that has already answered has earned the
    # wait.
    timeout: int = 20


# How long a closing session is given to finish tearing down. A constant rather than a
# setting: nobody has a reason to tune it, and a session that will not close cleanly is
# not something the operator can act on.
CLOSE_TIMEOUT = 5


@dataclass(frozen=True)
class CommandResult:
    exit_status: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_status == 0


class NodeConnection:
    """One SSH session to one node, as an async context manager."""

    def __init__(self, target: NodeTarget) -> None:
        self._target = target
        self._connection: asyncssh.SSHClientConnection | None = None

        # Set when a connection succeeded and the node's key was not previously
        # pinned, so the caller can persist it. First-use trust: not as strong as an
        # out-of-band fingerprint, but it turns every LATER interception into a
        # visible failure, which is the property that matters for a node whose
        # address is in a country that rewrites routes.
        self.learned_host_key: str | None = None

    async def __aenter__(self) -> NodeConnection:
        target = self._target
        options: dict[str, object] = {
            "username": target.username,
            "port": target.port,
        }
        if target.private_key:
            options["client_keys"] = [asyncssh.import_private_key(target.private_key)]

        if target.host_key:
            options["known_hosts"] = ([asyncssh.import_public_key(target.host_key)], [], [])
        else:
            # No pin yet, so accept and LEARN it below. `None` disables
            # verification for this one connection; it is not a default we keep.
            options["known_hosts"] = None

        try:
            # ``wait_for`` rather than asyncssh's own connect option, because this way
            # the ceiling covers the whole call — name resolution included, which is
            # its own way of hanging when a node's address stops resolving.
            self._connection = await asyncio.wait_for(
                asyncssh.connect(target.host, **options), timeout=target.connect_timeout
            )
        except TimeoutError as exc:
            # A sentence, not a class name. This reaches the operator as the reason a
            # node was left degraded, and "TimeoutError" does not tell them whether we
            # gave up after a moment or after a minute. Listed before OSError on
            # purpose: TimeoutError is a subclass of it.
            raise NodeUnreachable(
                f"the node did not answer within {target.connect_timeout}s"
            ) from exc
        except (OSError, asyncssh.Error) as exc:
            # The message deliberately does not include the host: it propagates
            # into operator-facing text, and core invariants §4 keeps host names out
            # of anything that crosses the API boundary.
            raise NodeUnreachable(_why_no_session(exc)) from exc

        if not target.host_key:
            key = self._connection.get_server_host_key()
            if key is not None:
                self.learned_host_key = key.export_public_key().decode().strip()

        return self

    async def __aexit__(self, *_exc_info) -> None:
        if self._connection is not None:
            self._connection.close()
            try:
                await asyncio.wait_for(
                    self._connection.wait_closed(), timeout=CLOSE_TIMEOUT
                )
            except (TimeoutError, OSError, asyncssh.Error):
                # Swallowed rather than raised. We are usually unwinding a failure
                # that the operator needs to read, and a teardown that did not
                # complete would replace that reason with a less useful one. The
                # socket is already closed either way; what is bounded here is only
                # how long we wait to hear that it finished.
                pass

    async def run(self, command: str, *, check: bool = True) -> CommandResult:
        """Run a command on the node.

        ``command`` must never be built by interpolating a secret — see the module
        docstring. Callers pass configuration through ``write_file``.
        """
        assert self._connection is not None, "use NodeConnection as an async context manager"
        try:
            completed = await asyncio.wait_for(
                self._connection.run(command, check=False), timeout=self._target.timeout
            )
        except (TimeoutError, asyncssh.Error) as exc:
            raise NodeUnreachable(f"command timed out or failed to start: {command!r}") from exc

        result = CommandResult(
            exit_status=completed.exit_status or 0,
            stdout=str(completed.stdout or ""),
            stderr=str(completed.stderr or ""),
        )
        if check and not result.ok:
            # stderr is included because this is an operator-facing diagnostic about
            # OUR OWN command on OUR OWN node — not user data. Its TAIL, for the reason
            # ``_what_it_said`` gives.
            raise NodeUnreachable(
                f"command failed ({result.exit_status}): {command!r}: "
                f"{_what_it_said(result.stderr)}"
            )
        return result

    async def write_file(self, path: str, content: str | bytes, *, mode: int = 0o600) -> None:
        """Place a file on the node, created with restrictive permissions.

        The permissions are applied to the temporary path BEFORE the content is
        written and the file is then moved into place, so there is no window in
        which a rendered config — which contains a node's private key — is readable
        by another user on the host.

        ``bytes`` is placed as it is rather than being decoded — M27.2, which pushes a
        pre-rendered archive to a node. The mode is chosen from the type of the content
        rather than by a flag, so a caller cannot ask for one and pass the other: SFTP's
        text mode encodes on the way out and would raise on bytes, and its binary mode
        would raise on a str.
        """
        assert self._connection is not None
        temporary = f"{path}.incoming"
        opened_as = "wb" if isinstance(content, bytes) else "w"

        async def transfer() -> None:
            async with self._connection.start_sftp_client() as sftp:
                async with sftp.open(temporary, opened_as) as handle:
                    await handle.write(content)
                await sftp.chmod(temporary, mode)
                # Atomic within a filesystem: a daemon reloading mid-write must never
                # see a truncated config.
                await sftp.posix_rename(temporary, path)

        # Bounded as a whole rather than per SFTP call: SFTP carries no timeout of its
        # own, and a node that accepted the session and then stopped reading would
        # otherwise hang the panel request forever — the same failure this module
        # bounds at connect time, arriving one step later.
        try:
            await asyncio.wait_for(transfer(), timeout=self._target.timeout)
        except TimeoutError as exc:
            # No path in the message: it names a file on the node, and this text is
            # operator-facing.
            raise NodeUnreachable(
                f"the node stopped responding while a file was being placed on it "
                f"(after {self._target.timeout}s)"
            ) from exc

    async def read_file(self, path: str) -> str | None:
        """Read a file back, or ``None`` if it is not there.

        Used for drift detection: comparing what is on the node against a fresh
        render, which is only meaningful because rendering is deterministic.
        """
        assert self._connection is not None

        async def fetch() -> str | None:
            try:
                async with self._connection.start_sftp_client() as sftp:
                    async with sftp.open(path, "r") as handle:
                        return str(await handle.read())
            except (asyncssh.SFTPNoSuchFile, asyncssh.SFTPFailure):
                return None

        try:
            return await asyncio.wait_for(fetch(), timeout=self._target.timeout)
        except TimeoutError as exc:
            # Raised rather than returned as ``None``: ``None`` means "the file is not
            # there", which is a drift answer. A node that went silent mid-read has
            # told us nothing about the file, and reporting that as absence would make
            # drift detection invent a difference.
            raise NodeUnreachable(
                f"the node stopped responding while a file was being read back "
                f"(after {self._target.timeout}s)"
            ) from exc
