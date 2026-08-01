# =============================================================================
# hashi Warden — deploy/warden/warden.py
# =============================================================================
# WHAT: The project side of Kaizen's tracker v2 contract. It enrolls with the
#       Hub, accepts Directives, runs THIS repo's real agent fleet by invoking
#       the `claude` CLI with the matching slash command, mirrors the fleet's
#       own status files to the Hub, and reports the outcome.
#
# WHY it runs the CLI instead of reimplementing a pipeline: the fleet already
#       exists in `.claude/` — personas, commands, rulebooks, the review loop.
#       A Warden that re-encoded any of that would be a second, worse copy that
#       drifts the first time someone edits a persona. Its whole job is
#       translation: Directive in, slash command out, Status back.
#
# WHY status is MIRRORED rather than pushed by the agents: the fleet writes
#       `docs/tracker/{task_id}/status/*.yml` because that is what its personas
#       already do (and what `infra/wardenkit/trackerfiles.py` standardises).
#       Those agents cannot reach the Hub and should not learn how. So the
#       Warden tails the directory and forwards what changed — one integration
#       point instead of eight.
#
# WHY there is no `/next` in this project: work ARRIVES by Dispatch. `/next`
#       polls a tracker CLI for a queue to pop, and hashi has no such CLI — the
#       Hub pushes, the Warden runs. Installing it would mean two competing
#       sources of work.
#
# HOW:  docker compose -f deploy/warden/docker-compose.yml up -d --build
#       then approve the project (Кая, the panel's Fleet view, or curl).
#       See deploy/warden/README.md.
# =============================================================================

import asyncio
import logging
import os
import shlex

from infra.wardenkit import (
    DirectiveJob,
    HubClient,
    JobResult,
    WardenServicer,
    make_manifest,
    serve,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("hashi-warden")

HUB_ADDR = os.environ.get("HUB_ADDR", "tracker:9104")
NAME = os.environ.get("PROJECT_NAME", "hashi")
GRPC_ADDR = os.environ.get("GRPC_ADDR", "hashi-warden:9200")
BIND_ADDR = os.environ.get("BIND_ADDR", "0.0.0.0:9200")
REPO_ROOT = os.environ.get("REPO_ROOT", "/repo")
STATE = os.environ.get("STATE_DIR", "/state")
# One Directive at a time by default. The fleet edits a real working tree and
# has no worktree isolation, so two concurrent Directives would interleave
# their diffs — the merge-conflict problem the tracker exists to avoid.
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "1"))
# A `/develop` run is an architect, a security pass, a developer and up to three
# review rounds. Minutes, not seconds — but not unbounded either.
RUN_TIMEOUT = float(os.environ.get("RUN_TIMEOUT_S", "5400"))
# No stream event for this long means the CLI is wedged rather than working.
IDLE_TIMEOUT = float(os.environ.get("IDLE_TIMEOUT_S", "600"))
# How often the kit's status relay sweeps docs/tracker/{task_id}/status/ and
# pushes what changed. The fleet's sub-agents write those files with a file tool
# and cannot call back into this process, so this poll is the ONLY thing that
# makes them look busy in the panel instead of idle.
STATUS_POLL = int(os.environ.get("STATUS_POLL_S", "5"))
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "opus")

# The fleet needs to read, write, run tests and spawn its own subagents — this
# is a development fleet in its own repo, not an assistant handling untrusted
# messages. We still allow-list rather than using --dangerously-skip-permissions:
# that flag is refused when running as root, and an explicit list is something a
# reviewer can actually check.
ALLOWED_TOOLS = os.environ.get(
    "ALLOWED_TOOLS", "Read Write Edit Bash Glob Grep Task TodoWrite WebSearch WebFetch"
)

# Directive kind -> the slash command that already implements it.
KIND_TO_COMMAND = {
    "develop": "/develop",
    "fix": "/fix",
    "refactor": "/refactor",
    "epic": "/epic",
    "review": "/review",
    "research": "/research",
    "product": "/product",
}

# The Warden's own slug, used ONLY for the file it writes into the task's status
# directory. It is deliberately NOT in the roster: the roster is the fleet, and
# the panel draws it as an org chart, so a dispatch bridge listed there renders
# as a person — and since none of the five tiers describes infrastructure, any
# tier we gave it would be a lie. What the project is doing is already visible
# as the Directive's own state; what the CLI is doing is in this file and in
# `make warden-logs`.
WARDEN = "warden"

# The real roster. Every slug is a persona FILENAME verbatim (`dev-anderson`,
# not `anderson`), because that is the join key for live status — see
# docs/agents/adopt-the-kit.md §7 in the Kaizen repo.
ARCHITECT = "architect-xavier"
ROSTER = [
    # tier "product", never "owner": `owner` is the HUMAN the work is for. The
    # Hub seeds that row itself, and claiming it makes the seeding check find a
    # row and never add you — so the owner would be missing from the chart and
    # the PO would be labelled human.
    {"slug": "product-owner-ohno", "name": "Taiichi Ohno", "role": "Product Owner",
     "tier": "product", "model": "opus"},
    # The chart reads owner → PO → architect → developers: Ohno decides WHAT,
    # Xavier decides HOW.
    {"slug": ARCHITECT, "name": "Charles Xavier", "role": "Solution Architect",
     "tier": "architect", "model": "opus", "reports_to": "product-owner-ohno"},
    {"slug": "dev-anderson", "name": "Thomas Anderson", "role": "Control-plane Developer",
     "tier": "developer", "area": "control", "model": "opus", "reports_to": ARCHITECT},
    {"slug": "dev-neumann", "name": "John von Neumann", "role": "Data-plane Developer",
     "tier": "developer", "area": "edge", "model": "opus", "reports_to": ARCHITECT},
    {"slug": "dev-potts", "name": "Pepper Potts", "role": "Infrastructure Developer",
     "tier": "developer", "area": "infra", "model": "opus", "reports_to": ARCHITECT},
    {"slug": "reviewer-granger", "name": "Hermione Granger", "role": "Code Reviewer",
     "tier": "reviewer", "model": "sonnet"},
    {"slug": "security-holmes", "name": "Sherlock Holmes", "role": "Security Reviewer",
     "tier": "reviewer", "model": "opus"},
    {"slug": "researcher-curie", "name": "Marie Curie", "role": "Research Analyst",
     "model": "opus"},
]

DESCRIPTION = """hashi — self-hosted multi-protocol VPN (control plane + node fleet).

Directive kinds: develop, fix, refactor, epic, review, research, product.
The intent is passed to the matching slash command verbatim, so phrase it the
way you would type it: "add the VLESS+Reality transport profile".

No leads and no queue: the Hub dispatches, the Warden runs one Directive at a
time against the working tree."""


# --------------------------------------------------------------------------
# Running the fleet
# --------------------------------------------------------------------------

def _env() -> dict:
    """Environment for the CLI. Two settings here are load-bearing."""
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    # Strip the API key so the CLI uses the Max login rather than API billing.
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR", f"{STATE}/claude")
    env["CLAUDE_CONFIG_DIR"] = config_dir
    env["PATH"] = f"{config_dir}/local:" + env.get("PATH", "")
    # CRITICAL: without this the CLI "migrates" itself into the mounted config
    # dir, and the next volume wipe deletes the binary.
    env["DISABLE_AUTOUPDATER"] = "1"
    return env


async def _run_claude(prompt: str, job: DirectiveJob) -> tuple[int, str]:
    """Run one slash command to completion. Returns (returncode, output tail).

    Idle timeout rather than a flat one: a working pipeline streams tool events
    continuously, so silence is the signal that it is stuck. A legitimate
    `/develop` run is long.
    """
    cmd = [
        "claude", "-p", prompt,
        "--model", CLAUDE_MODEL,
        "--allowedTools", ALLOWED_TOOLS,
        "--output-format", "stream-json",
        "--verbose",
    ]
    logger.info("#%s: %s", job.id, " ".join(shlex.quote(c) for c in cmd[:4]))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=REPO_ROOT,
        env=_env(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=8 * 1024 * 1024,
    )
    tail: list[str] = []
    try:
        async def drain() -> None:
            assert proc.stdout is not None
            while True:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=IDLE_TIMEOUT)
                if not line:
                    return
                text = line.decode("utf-8", "replace").rstrip()
                tail.append(text)
                del tail[:-40]          # keep only what a failure report needs

        await asyncio.wait_for(drain(), timeout=RUN_TIMEOUT)
        await proc.wait()
    except (TimeoutError, asyncio.CancelledError):
        # Both paths must kill the child: wait_for only cancels our reader, and
        # a cancelled Directive that leaves the CLI running keeps burning quota
        # and editing the repo behind us.
        logger.warning("#%s: killing the CLI (timeout or cancellation)", job.id)
        proc.kill()
        await proc.wait()
        raise
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
    return proc.returncode or 0, "\n".join(tail[-20:])


def _note(job: DirectiveJob, state: str, progress: str) -> None:
    """Record what the Warden itself is doing, in the task's status directory.

    Deliberately `files.write_status` and not `job.status()`: the latter also
    pushes a row to the Hub, and the Hub joins those rows onto roster members.
    The Warden is not one — pushing under a slug the manifest never declared
    either lands on nobody or, if declared, draws plumbing onto the fleet's org
    chart. The file is the right home: greppable, in the repo, next to the
    agents' own.
    """
    if job.files is not None:
        job.files.write_status(
            WARDEN, state=state, role="warden", phase="dispatch", progress=progress
        )


async def _git(*args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", REPO_ROOT, *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    return out.decode("utf-8", "replace").strip()


# --------------------------------------------------------------------------
# The handler
# --------------------------------------------------------------------------

async def run_pipeline(job: DirectiveJob) -> JobResult:
    """Translate one Directive into one slash-command run of the real fleet."""
    logger.info("=== #%s (%s) task '%s': %s", job.id, job.kind, job.task_id, job.intent)

    command = KIND_TO_COMMAND.get(job.kind)
    if command is None:
        return JobResult(
            state="failed",
            summary=f"kind {job.kind!r} is not something hashi knows how to run",
            error=f"supported kinds: {', '.join(sorted(KIND_TO_COMMAND))}",
        )

    if job.files is not None:
        job.files.ensure()

    # The fleet picks its own task-id by default; pin it to the Directive's so
    # the Handoffs and Status land in the tree the Hub is already watching.
    prompt = (
        f"{command} {job.intent}\n\n"
        f"Use task-id `{job.task_id}` for this work — the tracker directory "
        f"docs/tracker/{job.task_id}/ already exists and is being watched.\n"
        f"You are running unattended: nobody can answer a question right now. "
        f"If you hit a decision that genuinely needs the owner, stop and report "
        f"it rather than guessing."
    )

    before = await _git("rev-parse", "HEAD")
    _note(job, "in_progress", f"running {command}")

    # No status mirroring here on purpose: wardenkit's own status relay polls
    # docs/tracker/{task_id}/status/ every `status_poll_seconds` for the life of
    # the job and sweeps once more after it ends. Running a second poller
    # alongside it would double-push and race it — and the kit's handles the
    # `status:`/`updated:` aliases and change-detection that this one did not.
    try:
        code, tail = await _run_claude(prompt, job)
    except TimeoutError:
        _note(job, "done", "timed out")
        return JobResult(
            state="failed",
            summary=f"{command} did not finish within the time limit",
            error="the CLI was killed after the run or idle timeout expired",
        )

    _note(job, "done", f"{command} exited {code}")

    if code != 0:
        return JobResult(
            state="failed",
            summary=f"{command} exited with code {code}",
            error=tail or "no output captured",
        )

    after = await _git("rev-parse", "HEAD")
    dirty = await _git("status", "--porcelain")
    diffstat = await _git("diff", "--stat", f"{before}..{after}") if after != before else ""

    if after == before and not dirty:
        # A clean run that changed nothing is a real outcome, not a failure —
        # a `/review` or a `/research` Directive ends exactly here.
        return JobResult(state="done", summary=f"{command} finished; no changes to the tree")

    summary = f"{command} finished. "
    summary += f"{len(dirty.splitlines())} file(s) uncommitted. " if dirty else ""
    summary += f"Commits:\n{diffstat}" if diffstat else ""
    # `review`, never `done`: the changes are in the working tree and no human
    # has looked at them. Only the owner closes that gap.
    return JobResult(state="review", summary=summary.strip())


async def main() -> None:
    hub = HubClient(HUB_ADDR, token_path=f"{STATE}/hub_token")
    manifest = make_manifest(
        NAME,
        purpose="Self-hosted multi-protocol VPN: control plane, node fleet, admin panel",
        description=DESCRIPTION,
        kinds=sorted(KIND_TO_COMMAND),
        roster=ROSTER,
        max_concurrent=MAX_CONCURRENT,
        grpc_addr=GRPC_ADDR,
    )

    # Serve before enrolling: the Hub may dispatch the moment the owner
    # approves, and a project registered but not yet listening is
    # indistinguishable from one that is down.
    servicer = WardenServicer(
        manifest, run_pipeline, hub=hub, repo_root=REPO_ROOT, heartbeat_seconds=10,
        status_poll_seconds=STATUS_POLL,
    )
    server = await serve(servicer, BIND_ADDR)
    logger.info("hashi Warden listening on %s, enrolling with %s", BIND_ADDR, HUB_ADDR)

    await hub.enroll(manifest, poll_seconds=5)
    logger.info("Enrolled as '%s'. Waiting for Directives.", NAME)
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(main())
