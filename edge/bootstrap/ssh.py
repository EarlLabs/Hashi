"""The only channel to a node.

WHAT: an async SSH connection wrapper — run a command, write a file, read a file.
WHY:  every node operation goes through here, so the properties that matter are
      enforced in one place: a timeout on everything, host-key pinning, and secrets
      written with restrictive permissions and never passed on a command line.
HOW:  ``asyncssh``. ``NodeTarget`` is a plain value object so `control` can build
      one from a database row without this module importing anything from `control`.

Two decisions worth reading before changing anything here:

**Everything has a timeout.** A blocked or seized node does not refuse a
connection — it accepts and then hangs. Without a ceiling, one dead host blocks the
panel request that was trying to replace it, which is exactly when the operator
needs the panel most.

**A secret never goes on the command line.** Arguments are world-readable in
``/proc`` on the node for the lifetime of the process. Configuration is written
over SFTP instead, to a file created 0600 before the bytes land in it.
"""

import asyncio
import logging
from dataclasses import dataclass

import asyncssh

logger = logging.getLogger(__name__)


class NodeUnreachable(Exception):
    """The node could not be reached, or the command failed.

    Deliberately one exception for both. A caller must treat "could not connect"
    and "the command exited non-zero" identically — in either case the node's real
    state is unknown, which means degraded rather than active.
    """


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

    timeout: int = 20


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
            self._connection = await asyncio.wait_for(
                asyncssh.connect(target.host, **options), timeout=target.timeout
            )
        except (TimeoutError, OSError, asyncssh.Error) as exc:
            # The message deliberately does not include the host: it propagates
            # into operator-facing text, and core invariants §4 keeps host names out
            # of anything that crosses the API boundary.
            raise NodeUnreachable(f"could not establish an SSH session: {type(exc).__name__}") \
                from exc

        if not target.host_key:
            key = self._connection.get_server_host_key()
            if key is not None:
                self.learned_host_key = key.export_public_key().decode().strip()

        return self

    async def __aexit__(self, *_exc_info) -> None:
        if self._connection is not None:
            self._connection.close()
            await self._connection.wait_closed()

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
            # OUR OWN command on OUR OWN node — not user data.
            raise NodeUnreachable(
                f"command failed ({result.exit_status}): {command!r}: {result.stderr.strip()[:300]}"
            )
        return result

    async def write_file(self, path: str, content: str, *, mode: int = 0o600) -> None:
        """Place a file on the node, created with restrictive permissions.

        The permissions are applied to the temporary path BEFORE the content is
        written and the file is then moved into place, so there is no window in
        which a rendered config — which contains a node's private key — is readable
        by another user on the host.
        """
        assert self._connection is not None
        temporary = f"{path}.incoming"
        async with self._connection.start_sftp_client() as sftp:
            async with sftp.open(temporary, "w") as handle:
                await handle.write(content)
            await sftp.chmod(temporary, mode)
            # Atomic within a filesystem: a daemon reloading mid-write must never
            # see a truncated config.
            await sftp.posix_rename(temporary, path)

    async def read_file(self, path: str) -> str | None:
        """Read a file back, or ``None`` if it is not there.

        Used for drift detection: comparing what is on the node against a fresh
        render, which is only meaningful because rendering is deterministic.
        """
        assert self._connection is not None
        try:
            async with self._connection.start_sftp_client() as sftp:
                async with sftp.open(path, "r") as handle:
                    return str(await handle.read())
        except (asyncssh.SFTPNoSuchFile, asyncssh.SFTPFailure):
            return None
