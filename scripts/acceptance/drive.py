#!/usr/bin/env python3
"""hashi — the acceptance agent's hands.

WHAT: one CLI verb per action (open, click, fill, snap …). Every call answers with
      an ACCESSIBILITY TREE and leaves a screenshot on the host as evidence.
WHY:  a tree, not a picture. From `button "add user"` the agent addresses an
      element by exactly what it saw; from a screenshot it would be guessing
      coordinates — wrong more often, and several times the tokens. The screenshot
      is still taken every time, because the gate opens `.acceptance/<milestone>/`
      and a capture that is not on disk did not happen.
WHY the browser is in a container and not on the host. The stand owns the browser.
      Inside the compose network `control:8000` is reachable and an Origin means the
      right thing; on the host it would need a published debugging port, and this
      project publishes 54100–54299 loopback only. Nothing here publishes anything.
WHY a resident process. A browser that died between two CLI calls would put every
      `click` on a blank page. `__serve` holds the page open inside the container
      and the verbs talk to it over a unix socket that never leaves that container.
WHY the budget is counted here and not asked for. "Stop after 220 actions" written
      in a prompt is a wish. Counted in this file, an exhausted budget makes the
      next verb fail with a legible line, so the report says "got this far, and
      why" instead of trailing off.
HOW:  this file runs on BOTH sides. On the host it is a wrapper that re-executes
      itself inside the `browser` service with the same argv; inside the container
      (ACCEPTANCE_IN_CONTAINER=1) it does the work. The pure parts — target
      parsing, the budget, tree truncation, URL rewriting — are plain data and are
      unit-tested in tests/infra/test_drive.py.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

# Where the container keeps its working files. Disposable with the stand — anything
# that has to survive is copied to the host by `_collect`.
BOX = pathlib.Path("/tmp/acceptance")
SOCKET = BOX / "drive.sock"
STATE = BOX / "state.json"
SHOTS = BOX / "shots"
UPLOADS = BOX / "uploads"
# Everything the resident server writes while it starts. It used to go to
# /dev/null, which is how a missing `playwright` package looked like a broken
# stand for as long as anyone's patience lasted — see `startup_failure`.
SERVER_LOG = BOX / "serve.log"
SERVER_LOG_LINES = 40

# The compose service holding the browser, and the path this file is mounted at.
SERVICE = "browser"
IN_BOX = "/srv/acceptance/drive.py"

# The published address the stand prints, and the in-network address that means the
# same thing from inside the browser container. The agent is given one set of URLs
# (aikit.yml's `acceptance.entrypoints`) and must not have to hold two in its head.
PUBLISHED = re.compile(r"^https?://(127\.0\.0\.1|localhost|0\.0\.0\.0)(:\d+)?")
IN_NETWORK = "http://control:8000"

# A role from the accessibility tree, addressed as `kind=value`. Everything not in
# this set is a locator strategy instead — see `parse_target`.
ROLES = {
    "button", "link", "textbox", "checkbox", "radio", "combobox", "tab", "heading",
    "cell", "row", "table", "list", "listitem", "dialog", "alert", "img", "option",
    "menuitem", "switch", "spinbutton", "separator", "banner", "main", "navigation",
    "region", "form", "search", "status", "tooltip", "group", "columnheader",
    "rowheader", "paragraph", "code", "generic",
}
STRATEGIES = {"text", "label", "placeholder", "title", "testid", "css"}

# How much tree comes back. A nine-screen console's full snapshot is thousands of
# lines; the agent needs the shape of the screen it is on, not a DOM dump.
MAX_TREE_LINES = 220


def say(message: str) -> None:
    print(f"[drive] {message}")


def fail(message: str) -> int:
    """One line, never a traceback.

    A Playwright stack trace is twenty frames of somebody else's code, and the
    agent would read every one of them at our expense to learn "the button was not
    there". Say that instead.
    """
    print(f"[drive] action failed: {message}", file=sys.stderr)
    return 1


# --- the pure half: parsing, budget, truncation -------------------------------

def parse_target(target: str) -> tuple[str, str, str]:
    """`button=add user` → ("role", "button", "add user").

    Returns (mode, kind, value) where mode is "role" or "locator". A bare string
    with no `=` is treated as text, because that is what an agent types when it is
    in a hurry and it should work rather than lecture.
    """
    if "=" not in target:
        return ("locator", "text", target)
    kind, _, value = target.partition("=")
    kind = kind.strip().lower()
    value = value.strip()
    if kind in ROLES:
        return ("role", kind, value)
    if kind in STRATEGIES:
        return ("locator", kind, value)
    known = ", ".join(sorted(ROLES | STRATEGIES))
    raise ValueError(f"unknown target kind {kind!r}. Use one of: {known}")


def rewrite_url(url: str) -> str:
    """Point a published address at the service inside the compose network.

    The stand prints http://127.0.0.1:54200/panel/ and that is the address the
    agent is given. Inside the browser container nothing is listening there.
    """
    if not PUBLISHED.match(url):
        return url
    return PUBLISHED.sub(IN_NETWORK, url, count=1)


def startup_failure(log: str) -> str:
    """What `begin` says when the socket never appeared — cause first.

    The one place in this file that prints more than a line, and deliberately so
    (`fail` explains why everything else does not). The server used to be started
    with its stderr on /dev/null, so the single line that named the cause —
    `ModuleNotFoundError: No module named 'playwright'` — was thrown away one line
    above a message that blamed the stand. The stand was fine; an agent reading it
    debugs compose, the profile, the network and the health checks instead.

    Only what the server wrote while STARTING, and only the tail. Nothing has been
    opened in the browser at that point, so no URL — and therefore no subscription
    token — can be in it.
    """
    tail = "\n".join(log.splitlines()[-SERVER_LOG_LINES:]).strip()
    if not tail:
        return (
            "the browser did not come up inside the stand, and its server wrote "
            f"nothing at all — check that {SERVER_LOG} is writable and that the "
            "browser image has a python to start"
        )
    return (
        "the browser did not come up inside the stand. What its server wrote "
        f"before it stopped:\n{tail}"
    )


def truncate_tree(tree: str, max_lines: int = MAX_TREE_LINES) -> str:
    lines = tree.splitlines()
    if len(lines) <= max_lines:
        return tree
    kept = lines[:max_lines]
    dropped = len(lines) - max_lines
    kept.append(f"… {dropped} more lines. Narrow the screen or snap a region.")
    return "\n".join(kept)


class Budget:
    """Actions and minutes, counted where they cannot be talked out of."""

    def __init__(self, milestone: str, max_actions: int, minutes: float,
                 started: float | None = None, used: int = 0) -> None:
        self.milestone = milestone
        self.max_actions = max_actions
        self.minutes = minutes
        self.started = time.time() if started is None else started
        self.used = used

    def spend(self) -> None:
        if self.used >= self.max_actions:
            raise BudgetSpent(
                f"budget spent: {self.used} of {self.max_actions} actions used on "
                f"{self.milestone}. Report how far you got and why — this is "
                f"'could not', never 'good'."
            )
        elapsed = (time.time() - self.started) / 60
        if elapsed > self.minutes:
            raise BudgetSpent(
                f"budget spent: {elapsed:.0f} minutes of {self.minutes:.0f} on "
                f"{self.milestone}. Report how far you got and why."
            )
        self.used += 1

    @property
    def left(self) -> int:
        return max(0, self.max_actions - self.used)

    def to_dict(self) -> dict:
        return {
            "milestone": self.milestone, "max_actions": self.max_actions,
            "minutes": self.minutes, "started": self.started, "used": self.used,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> Budget:
        return cls(raw["milestone"], raw["max_actions"], raw["minutes"],
                   raw.get("started"), raw.get("used", 0))


class BudgetSpent(RuntimeError):
    pass


# --- the host half: hand the same argv to the container -----------------------

def compose(*args: str) -> list[str]:
    """The e2e stack's compose invocation, kept identical to the Makefile's.

    Both --env-file flags and the project name are load-bearing; see COMPOSE_E2E
    in the Makefile. Repeating them here rather than shelling out to make keeps
    `docker compose cp` available, which make does not expose.
    """
    return [
        "docker", "compose",
        "--env-file", ".env",
        "--env-file", "deploy/e2e.env",
        "-p", os.environ.get("E2E_PROJECT", "hashi-e2e"),
        "--profile", "browser",
        "-f", "deploy/docker-compose.yml",
        "-f", "deploy/docker-compose.dev.yml",
        "-f", "deploy/docker-compose.e2e.yml",
        *args,
    ]


def compose_env() -> dict[str, str]:
    """The port variables the dev overlay interpolates.

    Without them `${DEV_API_PORT}` becomes an empty string and compose rejects the
    port mapping — the same trap the Makefile's `--env-file` comment describes, one
    layer down. Defaults match E2E_PORTS in the Makefile.
    """
    return os.environ | {
        "DEV_API_PORT": os.environ.get("E2E_API_PORT", "54200"),
        "DEV_DB_PORT": os.environ.get("E2E_DB_PORT", "54232"),
        "DEV_BIND_ADDR": os.environ.get("E2E_BIND_ADDR", "127.0.0.1"),
    }


def evidence_dir(milestone: str) -> pathlib.Path:
    path = ROOT / ".acceptance" / milestone
    path.mkdir(parents=True, exist_ok=True)
    return path


SHOT_LINE = re.compile(r"^\[drive\] shot (?P<name>.+\.png)$", re.MULTILINE)


def relay(argv: list[str]) -> tuple[int, str | None]:
    """Run this same file inside the browser container, with the same arguments.

    Output is captured rather than streamed only so the shot line can be read back;
    everything is printed unchanged, in order, so the agent sees exactly what the
    container said.
    """
    command = compose(
        "exec", "-T", "-e", "ACCEPTANCE_IN_CONTAINER=1", SERVICE,
        "python", IN_BOX, *argv,
    )
    result = subprocess.run(
        command, cwd=ROOT, env=compose_env(), capture_output=True, text=True
    )
    said = result.stdout
    match = SHOT_LINE.search(said)
    if match:
        said = SHOT_LINE.sub("", said).rstrip() + "\n"
    sys.stdout.write(said)
    sys.stderr.write(result.stderr)
    return result.returncode, (match.group("name") if match else None)


def collect(milestone: str, filename: str) -> None:
    """Copy one screenshot out of the container before the stand takes it away."""
    target = evidence_dir(milestone) / filename
    result = subprocess.run(
        compose("cp", f"{SERVICE}:{SHOTS}/{filename}", str(target)),
        cwd=ROOT, capture_output=True, text=True, env=compose_env(),
    )
    if result.returncode != 0:
        say(f"warning: no screenshot came back for {filename} — {result.stderr.strip()}")
        return
    say(f"evidence: .acceptance/{milestone}/{filename}")


def push_upload(path: str) -> str:
    """Put a local file where the container's file input can reach it.

    The operating system's file picker is not a web page and cannot be clicked
    through; Playwright sets the input directly, so the file has to be on that
    side of the boundary first.
    """
    source = pathlib.Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"no such file to upload: {source}")
    subprocess.run(compose("exec", "-T", SERVICE, "mkdir", "-p", str(UPLOADS)),
                   cwd=ROOT, check=True, capture_output=True, env=compose_env())
    subprocess.run(compose("cp", str(source), f"{SERVICE}:{UPLOADS}/{source.name}"),
                   cwd=ROOT, check=True, capture_output=True, env=compose_env())
    return str(UPLOADS / source.name)


def browser_is_up() -> bool:
    result = subprocess.run(
        compose("ps", "-q", SERVICE), cwd=ROOT, capture_output=True, text=True,
        env=compose_env(),
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def on_host(args: argparse.Namespace, argv: list[str]) -> int:
    if shutil.which("docker") is None:
        return fail("docker is not on PATH — the browser lives in the stand")
    if not browser_is_up():
        return fail(
            "the browser service is not running. `scripts/acceptance/stand.sh up` "
            "starts it with the stand; nothing else needs to be installed."
        )

    if args.action == "upload":
        try:
            args_in_box = push_upload(args.file)
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            return fail(str(exc))
        argv = [a if a != args.file else args_in_box for a in argv]

    code, shot = relay(argv)
    # Evidence comes back even when the action failed: a screenshot of the screen
    # that would not do what was asked is the most useful one in the whole run.
    # The container decides the filename, because only it knows the action number
    # that keeps two unnamed `fill`s from writing the same file.
    if shot:
        with contextlib.suppress(Exception):
            collect(current_milestone(), shot)
    return code


def current_milestone() -> str:
    """Read the milestone the container recorded at `begin`."""
    result = subprocess.run(
        compose("exec", "-T", SERVICE, "cat", str(STATE)),
        cwd=ROOT, capture_output=True, text=True, env=compose_env(),
    )
    if result.returncode != 0:
        return "unknown"
    with contextlib.suppress(Exception):
        return json.loads(result.stdout)["milestone"]
    return "unknown"


# --- the container half: one resident browser, one socket ---------------------

def send(request: dict) -> dict:
    if not SOCKET.exists():
        raise RuntimeError("no session — run `begin <milestone>` first")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(SOCKET))
        client.sendall((json.dumps(request) + "\n").encode())
        chunks = []
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    return json.loads(b"".join(chunks).decode())


def serve(milestone: str, max_actions: int, minutes: float) -> int:
    """Hold one browser open and answer verbs until told to stop."""
    from playwright.sync_api import sync_playwright

    for path in (SHOTS, UPLOADS):
        path.mkdir(parents=True, exist_ok=True)
    budget = Budget(milestone, max_actions, minutes)
    STATE.write_text(json.dumps(budget.to_dict()))
    SOCKET.unlink(missing_ok=True)

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    # Open every shadow root. A closed root is invisible to the accessibility
    # snapshot, so a component built that way would simply not exist for the agent.
    page.add_init_script(
        "(() => { const attach = Element.prototype.attachShadow;"
        " Element.prototype.attachShadow = function (init) {"
        "   return attach.call(this, { ...init, mode: 'open' }); }; })()"
    )

    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(SOCKET))
    listener.listen(1)

    try:
        while True:
            connection, _ = listener.accept()
            with connection:
                raw = b""
                while not raw.endswith(b"\n"):
                    part = connection.recv(65536)
                    if not part:
                        break
                    raw += part
                request = json.loads(raw.decode() or "{}")
                if request.get("action") == "end":
                    connection.sendall(json.dumps({"ok": True}).encode())
                    break
                reply = perform(page, budget, request)
                STATE.write_text(json.dumps(budget.to_dict()))
                connection.sendall(json.dumps(reply).encode())
    finally:
        listener.close()
        SOCKET.unlink(missing_ok=True)
        with contextlib.suppress(Exception):
            browser.close()
            playwright.stop()
    return 0


def locate(page, target: str):
    mode, kind, value = parse_target(target)
    if mode == "role":
        return page.get_by_role(kind, name=value) if value else page.get_by_role(kind)
    match kind:
        case "text":
            return page.get_by_text(value)
        case "label":
            return page.get_by_label(value)
        case "placeholder":
            return page.get_by_placeholder(value)
        case "title":
            return page.get_by_title(value)
        case "testid":
            return page.get_by_test_id(value)
        case _:
            return page.locator(value)


def perform(page, budget: Budget, request: dict) -> dict:
    action = request["action"]
    try:
        budget.spend()
        match action:
            case "open":
                page.goto(rewrite_url(request["url"]), wait_until="domcontentloaded")
            case "click":
                locate(page, request["target"]).first.click(timeout=10_000)
            case "fill":
                locate(page, request["target"]).first.fill(request["value"], timeout=10_000)
            case "type":
                locate(page, request["target"]).first.type(request["value"], delay=20)
            case "press":
                page.keyboard.press(request["value"])
            case "upload":
                locate(page, request["target"]).first.set_input_files(request["file"])
            case "back":
                page.go_back(wait_until="domcontentloaded")
            case "reload":
                page.reload(wait_until="domcontentloaded")
            case "wait":
                page.wait_for_timeout(float(request.get("seconds", 1)) * 1000)
            case "snap":
                pass
            case _:
                return {"ok": False, "error": f"unknown action {action!r}"}
        # HTMX swaps a fragment in without a navigation, so "the page loaded" is not
        # the signal. Settle on the network instead, and do not treat a busy page as
        # a failure — a slow stand is still a working one.
        with contextlib.suppress(Exception):
            page.wait_for_load_state("networkidle", timeout=5_000)
    except BudgetSpent as exc:
        return {"ok": False, "error": str(exc), "spent": True}
    except Exception as exc:  # noqa: BLE001 - one line to the agent, by design
        # Name the target. Playwright's first line is "Timeout 10000ms exceeded",
        # which does not say WHAT was not there — and in the morning that is the
        # only thing the log needed to say.
        message = str(exc).splitlines()[0]
        if request.get("target"):
            message = f"{request['target']} — {message}"
        shot = capture(page, shot_name(request, budget, failed=True))
        return {"ok": False, "error": message, "tree": snapshot(page), "shot": shot}

    return {
        "ok": True,
        "url": page.url,
        "tree": snapshot(page),
        "shot": capture(page, shot_name(request, budget)),
        "left": budget.left,
    }


def shot_name(request: dict, budget: Budget, failed: bool = False) -> str:
    """A name no other action in this milestone can take.

    Naming an unnamed shot after its verb looked tidy until two `fill`s in one
    scenario wrote the same file: the gate then opens .acceptance/<milestone>/ and
    finds one screenshot where the checklist cited two. The action number is
    already counted for the budget, so it costs nothing and cannot collide.
    """
    stem = request.get("name") or request["action"]
    suffix = "-failed" if failed else ""
    return f"{stem}-{budget.used:03d}{suffix}"


def snapshot(page) -> str:
    with contextlib.suppress(Exception):
        return truncate_tree(page.locator("body").aria_snapshot())
    return "(no accessibility snapshot available)"


def capture(page, name: str) -> str:
    path = SHOTS / f"{name}.png"
    with contextlib.suppress(Exception):
        page.screenshot(path=str(path), full_page=True)
    return path.name


def in_container(args: argparse.Namespace) -> int:
    if args.action == "begin":
        BOX.mkdir(parents=True, exist_ok=True)
        if SOCKET.exists():
            with contextlib.suppress(Exception):
                send({"action": "end"})
        # The server outlives this process on purpose: the next verb needs the same
        # page, not a fresh one. Which is also why its output goes to a FILE rather
        # than to a pipe — a pipe whose reader has already exited fills up and
        # blocks the writer, and the writer here is the browser. `w` truncates, so
        # what the failure path below reads is this session's start-up and never a
        # previous one's. The file is disposable with the stand and never leaves
        # the container.
        with SERVER_LOG.open("w") as log:
            server = subprocess.Popen(
                [sys.executable, IN_BOX, "__serve", args.milestone,
                 "--max-actions", str(args.max_actions), "--minutes", str(args.minutes)],
                stdout=log, stderr=subprocess.STDOUT,
            )
        for _ in range(100):
            if SOCKET.exists():
                say(f"session open on {args.milestone}: "
                    f"{args.max_actions} actions, {args.minutes:g} minutes")
                return 0
            # It has already died: waiting out the rest of the ten seconds proves
            # nothing and only delays the diagnosis.
            if server.poll() is not None:
                break
            time.sleep(0.1)
        return fail(startup_failure(SERVER_LOG.read_text() if SERVER_LOG.exists() else ""))

    if args.action == "end":
        with contextlib.suppress(Exception):
            send({"action": "end"})
        say("session closed")
        return 0

    request = {"action": args.action, "name": args.name}
    for key in ("url", "target", "value", "file", "seconds"):
        if getattr(args, key, None) is not None:
            request[key] = getattr(args, key)

    try:
        reply = send(request)
    except Exception as exc:  # noqa: BLE001
        return fail(str(exc))

    if reply.get("tree"):
        print(reply["tree"])
    if not reply.get("ok"):
        if reply.get("shot"):
            print(f"[drive] shot {reply['shot']}")
        return fail(reply.get("error", "unknown failure"))
    say(f"{args.action} ok — {reply['url']} · {reply['left']} actions left")
    # The host half reads this line to know which file to copy out. It is the only
    # machine-readable thing this CLI prints, so it goes last and stays literal.
    print(f"[drive] shot {reply['shot']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="hashi acceptance hands")
    subs = parser.add_subparsers(dest="action", required=True)

    begin = subs.add_parser("begin", help="open a session for one milestone")
    begin.add_argument("milestone")
    begin.add_argument("--max-actions", type=int, default=220)
    begin.add_argument("--minutes", type=float, default=75)

    serve_parser = subs.add_parser("__serve", help=argparse.SUPPRESS)
    serve_parser.add_argument("milestone")
    serve_parser.add_argument("--max-actions", type=int, default=220)
    serve_parser.add_argument("--minutes", type=float, default=75)

    def with_name(sub: argparse.ArgumentParser) -> argparse.ArgumentParser:
        sub.add_argument("--name", help="what to call the screenshot this leaves")
        return sub

    with_name(subs.add_parser("open")).add_argument("url")
    for verb in ("click",):
        with_name(subs.add_parser(verb)).add_argument("target")
    for verb in ("fill", "type"):
        sub = with_name(subs.add_parser(verb))
        sub.add_argument("target")
        sub.add_argument("value")
    with_name(subs.add_parser("press")).add_argument("value", metavar="key")
    upload = with_name(subs.add_parser("upload"))
    upload.add_argument("target")
    upload.add_argument("file")
    wait = with_name(subs.add_parser("wait"))
    wait.add_argument("seconds", nargs="?", default=1, type=float)
    with_name(subs.add_parser("back"))
    with_name(subs.add_parser("reload"))
    with_name(subs.add_parser("snap"))
    subs.add_parser("end", help="close the session")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)
    for key in ("url", "target", "value", "file", "seconds", "name"):
        if not hasattr(args, key):
            setattr(args, key, None)

    if args.action == "__serve":
        return serve(args.milestone, args.max_actions, args.minutes)
    if os.environ.get("ACCEPTANCE_IN_CONTAINER"):
        return in_container(args)
    return on_host(args, argv)


if __name__ == "__main__":
    raise SystemExit(main())
