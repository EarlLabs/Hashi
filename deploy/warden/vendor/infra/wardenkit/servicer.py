# =============================================================================
# Warden servicer — infra/wardenkit/servicer.py
# =============================================================================
# WHAT: The gRPC server every project runs: Dispatch / Cancel / Describe /
#       Health (infra/proto/warden.proto). It accepts Directives, runs ONE
#       handler coroutine per Directive, heartbeats while that handler lives,
#       and reports the outcome to the Hub. A project's `warden.py` is then
#       genuinely thin: a manifest, a handler, and `serve()`.
#
# WHY the Warden is plain infrastructure and NOT an LLM (architecture §1): it
#       must answer Health and accept a Cancel *while* a pipeline is running.
#       If the overseer persona and the daemon were the same process, a hung
#       Claude call would make the whole project look dead — and the Hub would
#       requeue work that is actually fine. Judgement lives in the handler; the
#       servicer only ever schedules, watches, and reports.
#
# WHY re-Dispatch of a running Directive is ACCEPTED, not rejected: after a lease
#       expiry (case 8) or a Hub restart (case 9) the Hub may hand us something
#       we are already running. Rejecting it would fail a healthy Directive;
#       spawning a second pipeline would put two fleets in the same
#       docs/tracker/{task_id}/ tree, writing over each other. So we say "yes,
#       we have it" and keep the one pipeline that already exists.
#
# WHY the kit heartbeats for the WHOLE life of a job, including while it is
#       blocked on a Question: the Hub's sweeper treats `dispatched`, `running`
#       and `blocked` as leased states. An agent waiting on the owner is still a
#       live process holding real work — if it stopped heartbeating, the sweeper
#       would requeue it out from under the owner who is mid-answer. "Alive"
#       and "busy" are different questions, and the lease asks the first one.
#
# HOW:  servicer = WardenServicer(manifest, handler, hub=hub, repo_root=".")
#       await serve(servicer, "0.0.0.0:9200")
# =============================================================================

import asyncio
import logging
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import grpc

from infra.proto.gen import warden_pb2, warden_pb2_grpc
from infra.wardenkit.client import CHANNEL_OPTIONS, HubClient
from infra.wardenkit.trackerfiles import TrackerFiles, slugify

logger = logging.getLogger(__name__)

# The two rejection reasons the Hub branches on (warden.proto DispatchAck).
REASON_AT_CAPACITY = "at_capacity"
REASON_UNSUPPORTED_KIND = "unsupported_kind"


@dataclass
class DirectiveJob:
    """One Directive, as the project's handler sees it.

    Carries the work AND the two things a pipeline needs to talk about it: the
    Hub client (status, questions) and the on-disk tracker tree (Handoffs).
    """

    id: int
    kind: str
    intent: str
    title: str
    task_id: str
    priority: int = 100
    auto_merge: bool = False
    meta: dict[str, str] = field(default_factory=dict)
    hub: HubClient | None = None
    files: TrackerFiles | None = None

    async def status(
        self,
        agent_slug: str,
        state: str,
        *,
        role: str = "",
        phase: str = "",
        progress: str = "",
        blockers: str = "",
    ) -> None:
        """Record one agent's Status in BOTH places at once — the project's own
        file and the Hub's mirror. Doing it in one call is what keeps the two
        from drifting; a project that wrote only the file would be invisible in
        the panel, and one that pushed only the row would leave its own agents
        unable to read each other's state."""
        if self.files is not None:
            self.files.write_status(
                agent_slug, state=state, role=role, phase=phase,
                progress=progress, blockers=blockers,
            )
        if self.hub is not None:
            await self.hub.push_status(
                self.id, agent_slug, state, task_id=self.task_id, role=role,
                progress=progress, blockers=blockers, phase=phase,
            )

    def handoff(self, from_agent: str, to_agent: str, body: str) -> None:
        """Write one agent's Handoff to the next, in this Directive's tree.

        The sibling of `status()` and `ask()`: the three things a pipeline does
        that are not its own work. Going through here rather than reaching for
        `job.files` means a handler never has to null-check the tree — and a
        Warden built without a repo_root simply skips the write instead of
        crashing a pipeline over a file it did not need.
        """
        if self.files is None:
            return
        self.files.write_handoff(from_agent, to_agent, body)

    async def ask(
        self,
        agent_slug: str,
        text: str,
        *,
        timeout_sec: int = 900,
        suggested: list[str] | None = None,
    ) -> warden_pb2.Answer:
        """Ask the owner. Returns an Answer whose `.answered` is False when
        nobody replied in time — never a silent guess."""
        if self.hub is None:
            return warden_pb2.Answer(answered=False)
        return await self.hub.ask_owner(
            self.id, agent_slug, text, timeout_sec=timeout_sec, suggested=suggested
        )


@dataclass
class JobResult:
    """What a handler returns: the Directive's terminal outcome.

    A handler that returns None is taken to mean a plain `done` — the common
    case shouldn't need ceremony.
    """

    state: str = "done"           # done | failed | review | cancelled
    summary: str = ""
    artifacts: list[dict] = field(default_factory=list)
    error: str = ""
    # For an `epic`: the ordered pieces it broke into, as
    # {"title", "intent", "kind"} dicts. The Hub queues them under this
    # Directive — a project reports work, it never creates it.
    children: list[dict] = field(default_factory=list)


def make_manifest(
    name: str,
    *,
    purpose: str = "",
    description: str = "",
    kinds: list[str] | None = None,
    roster: list[dict] | None = None,
    max_concurrent: int = 1,
    repo_url: str = "",
    default_branch: str = "main",
    grpc_addr: str = "",
) -> warden_pb2.ProjectManifest:
    """Build a ProjectManifest without the project touching protobuf types.

    `roster` entries are plain dicts: {"slug", "name", "role", "model"} — the
    same shape a project's .claude/agents/*.md front-matter already has — plus
    two optional keys that describe the SHAPE of the fleet rather than one
    member of it:

      "tier"       where it sits: owner | architect | lead | developer |
                   reviewer — the standard vocabulary the chart is drawn from
      "area"       which part of the project this persona works on
                   (backend, frontend, mobile, infra, security, design, …)
      "reports_to" the slug of the persona above it — a dev's lead, a lead's
                   architect. Omit it on whoever sits at the top.

    Both are optional and purely for display: the Hub dispatches to a PROJECT,
    never to a persona. Declaring them is what lets the panel draw the fleet as
    the tree it actually is; leave them out and it falls back to guessing from
    the slug, which is right often enough to be useful and wrong often enough
    to be worth two lines of manifest.
    """
    return warden_pb2.ProjectManifest(
        name=name,
        purpose=purpose,
        description=description,
        kinds=list(kinds or []),
        roster=[
            warden_pb2.AgentSpec(
                slug=a.get("slug", ""), name=a.get("name", ""),
                role=a.get("role", ""), model=a.get("model", ""),
                area=a.get("area", ""), reports_to=a.get("reports_to", ""),
                tier=a.get("tier", ""),
            )
            for a in (roster or [])
        ],
        max_concurrent=max_concurrent,
        repo_url=repo_url,
        default_branch=default_branch,
        grpc_addr=grpc_addr,
    )


class WardenServicer(warden_pb2_grpc.WardenServicer):
    """Serves the Warden contract for one project."""

    def __init__(
        self,
        manifest: warden_pb2.ProjectManifest,
        handler,
        *,
        hub: HubClient | None = None,
        repo_root: str | Path = ".",
        heartbeat_seconds: int = 30,
    ) -> None:
        self._manifest = manifest
        self._handler = handler
        self._hub = hub
        self._repo_root = Path(repo_root)
        self._heartbeat_seconds = heartbeat_seconds
        # An empty `kinds` list means "this project accepts anything" — a fresh
        # project shouldn't have to enumerate its pipelines before it can be
        # given its first Directive.
        self._kinds = set(manifest.kinds)
        self._capacity = max(1, manifest.max_concurrent or 1)
        self._jobs: dict[int, asyncio.Task] = {}
        self._task_ids: dict[int, str] = {}

    # -- the RPCs ----------------------------------------------------------
    async def Dispatch(self, request, context):
        if self._kinds and request.kind and request.kind not in self._kinds:
            logger.info("Rejecting #%s: kind '%s' unsupported", request.id, request.kind)
            return warden_pb2.DispatchAck(
                accepted=False, reason=REASON_UNSUPPORTED_KIND
            )

        running = self._jobs.get(request.id)
        if running is not None and not running.done():
            # Already ours — see the header. Echo the task_id so the Hub's row
            # matches what our files are actually called.
            return warden_pb2.DispatchAck(
                accepted=True, task_id=self._task_ids.get(request.id, request.task_id)
            )

        if len(self._live_jobs()) >= self._capacity:
            logger.info("Rejecting #%s: at capacity (%d)", request.id, self._capacity)
            return warden_pb2.DispatchAck(accepted=False, reason=REASON_AT_CAPACITY)

        # The task_id names a DIRECTORY under docs/tracker/, so slugify whatever
        # the Hub sent — not only the ids we derive ourselves. It reaches us as
        # free text the owner typed at Кая ("continue key rotation"), and
        # "../../etc" or "key rotation" must never become a path.
        if request.task_id:
            # The owner explicitly asked to continue an existing task. Sharing
            # that tree is the POINT, so it is used as given (slugified — it is
            # free text the owner typed at Кая, and "../../etc" must never
            # become a path).
            task_id = slugify(request.task_id, fallback=f"directive-{request.id}")
        else:
            # A DERIVED id must be unique per Directive, and a title alone is
            # not: two different requests routinely slugify to the same thing
            # (anything whose only ASCII is a shared keyword, and every pair of
            # non-Latin titles). Two Directives sharing a task_id means two
            # fleets in one docs/tracker/{task_id}/ tree, overwriting each
            # other's Handoffs and Status files — the exact collision
            # architecture §7 case 14 exists to rule out. The Hub's id is the
            # only thing guaranteed distinct, so it is always appended.
            base = slugify(request.title or request.intent, fallback="directive")
            task_id = f"{base}-{request.id}"
        job = DirectiveJob(
            id=request.id,
            kind=request.kind,
            intent=request.intent,
            title=request.title,
            task_id=task_id,
            priority=request.priority,
            auto_merge=request.auto_merge,
            meta=dict(request.meta),
            hub=self._hub,
            files=TrackerFiles(self._repo_root, task_id),
        )
        self._task_ids[request.id] = task_id
        self._jobs[request.id] = asyncio.create_task(self._run(job))
        logger.info("Accepted Directive #%s (%s) as task '%s'", request.id, request.kind, task_id)
        return warden_pb2.DispatchAck(accepted=True, task_id=task_id)

    async def Cancel(self, request, context):
        # Read the task_id BEFORE anything unwinds: `_run`'s finally drops it
        # the moment the job dies, so reading it after the await below would
        # always yield "" — losing the one field that tells the Hub which tree
        # on this project's disk holds the half-finished work.
        task_id = self._task_ids.get(request.directive_id, "")
        task = self._jobs.pop(request.directive_id, None)
        if task is None or task.done():
            return warden_pb2.CancelAck(accepted=False, reason="not running here")
        task.cancel()
        # Let it unwind before answering, so "cancelled" is true by the time the
        # Hub hears it rather than merely requested.
        await asyncio.gather(task, return_exceptions=True)
        logger.info("Cancelled Directive #%s: %s", request.directive_id, request.reason)
        # The report is pushed HERE and not from the cancelled coroutine: a task
        # being torn down is the one place where a further `await` may never get
        # a turn, and losing the report would leave the Directive stuck.
        if self._hub is not None:
            await self._hub.push_report(
                request.directive_id,
                "cancelled",
                summary=request.reason or "cancelled by the owner",
                task_id=task_id,
            )
        self._task_ids.pop(request.directive_id, None)
        return warden_pb2.CancelAck(accepted=True)

    async def Describe(self, request, context):
        return self._manifest

    async def Health(self, request, context):
        live = self._live_jobs()
        return warden_pb2.WardenHealth(
            ok=True,
            running=len(live),
            capacity=self._capacity,
            running_directives=sorted(live),
        )

    # -- internals ---------------------------------------------------------
    def _live_jobs(self) -> list[int]:
        """Directive ids we are actually running right now.

        Recomputed rather than trusted: a handler that finished between two
        Health calls must free its slot even if its done-callback hasn't run.
        """
        return [did for did, task in self._jobs.items() if not task.done()]

    async def _run(self, job: DirectiveJob) -> None:
        """Run one handler, heartbeating throughout, and report the outcome."""
        beat = asyncio.create_task(self._heartbeat_loop(job))
        try:
            result = await self._handler(job)
            outcome = result if isinstance(result, JobResult) else JobResult()
            if self._hub is not None:
                await self._hub.push_report(
                    job.id,
                    outcome.state,
                    summary=outcome.summary,
                    artifacts=outcome.artifacts,
                    error=outcome.error,
                    task_id=job.task_id,
                    children=outcome.children,
                )
            logger.info("Directive #%s finished: %s", job.id, outcome.state)
        except asyncio.CancelledError:
            # Cancel() owns the report for this path — see the comment there.
            logger.info("Directive #%s cancelled", job.id)
            raise
        except Exception as e:
            logger.exception("Directive #%s failed", job.id)
            if self._hub is not None:
                await self._hub.push_report(
                    job.id,
                    "failed",
                    summary=f"{type(e).__name__}: {e}",
                    # The tail, not the head: the last frames are where it
                    # actually broke, and the whole trace would flood Telegram.
                    error="".join(traceback.format_exc()).strip()[-2000:],
                    task_id=job.task_id,
                )
        finally:
            beat.cancel()
            self._jobs.pop(job.id, None)
            self._task_ids.pop(job.id, None)

    async def _heartbeat_loop(self, job: DirectiveJob) -> None:
        """Keep this Directive's lease alive for as long as the job exists."""
        if self._hub is None:
            return
        while True:
            await asyncio.sleep(self._heartbeat_seconds)
            await self._hub.heartbeat(job.id, job.task_id)


async def serve(
    servicer: WardenServicer, bind_addr: str = "0.0.0.0:9200"
) -> grpc.aio.Server:
    """Start a gRPC server for this Warden and return it (already started).

    Keepalive is the SAME list the client uses (infra/wardenkit/client.py): the
    Hub dials us and holds the connection between dispatches, so both ends must
    agree both on how often a quiet connection is pinged and on that being
    welcome rather than abuse.
    """
    # so_reuseport=0 undoes a gRPC default that is wrong for us: with it ON
    # (the default on Linux) a second Warden process binds the SAME port
    # happily and the kernel round-robins Dispatches between the two, so a
    # stale container and a fresh one each run half the fleet. Off, the second
    # bind fails and the check below turns it into a loud boot error.
    server = grpc.aio.server(options=[*CHANNEL_OPTIONS, ("grpc.so_reuseport", 0)])
    warden_pb2_grpc.add_WardenServicer_to_server(servicer, server)
    if server.add_insecure_port(bind_addr) == 0:
        # grpc.aio raises on a failed bind, but the sync API (and older
        # grpcio) signals it by RETURNING 0 — and an unchecked 0 means a
        # Warden that comes up "fine", logs its address, registers with the
        # Hub, and is undialable: every Dispatch failing against a port nobody
        # listens on. Cheap to check, so check it.
        raise RuntimeError(f"Warden could not bind {bind_addr} — port in use?")
    await server.start()
    logger.info("Warden gRPC on %s", bind_addr)
    return server


__all__ = [
    "REASON_AT_CAPACITY",
    "REASON_UNSUPPORTED_KIND",
    "DirectiveJob",
    "JobResult",
    "WardenServicer",
    "make_manifest",
    "serve",
]
