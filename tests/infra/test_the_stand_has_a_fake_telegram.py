"""The stand's fake Telegram, held to what the control plane and the scenarios rely on — M37.4.

WHAT: that the e2e overlay runs a fake Bot API beside the control plane and points the
      control plane at it, that the fake is in the e2e overlay and nowhere else, that
      its injection side is published on this project's e2e block and driven the way
      every other port is, that ``.env.example`` names the three settings an operator
      fills — and that the fake itself behaves the way the comments in it claim.
WHY:  the whole of M37 is proven on the stand through this fake. A fake that dropped an
      update on read, answered a poll only when its timeout ran out, or wrote the bot
      token into the container log would make ``make verify`` pass for the wrong reason
      or fail for one the control zone did not cause — and the scenario that uses it
      would be the only place to find out, ten minutes into a run.
HOW:  static over the compose files, ``.env.example`` and the Makefile, like the rest of
      this tier; and LIVE against the fake, which is one standard-library file: starting
      it on an ephemeral port inside this process costs milliseconds and proves the long
      poll, the acknowledgement semantics and the silence directly, with no engine.
"""

import ast
import contextlib
import importlib.util
import io
import json
import pathlib
import re
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
DEPLOY = REPO / "deploy"
BASE = DEPLOY / "docker-compose.yml"
E2E = DEPLOY / "docker-compose.e2e.yml"
# Every compose file that is not the e2e overlay: the fake belongs in none of them.
OTHER_COMPOSE_FILES = sorted(p for p in DEPLOY.glob("docker-compose*.yml") if p != E2E)
CONTROL_DOCKERFILE = DEPLOY / "docker" / "control.Dockerfile"
FAKE = REPO / ".e2e" / "fake_telegram.py"
ENV_EXAMPLE = REPO / ".env.example"
MAKEFILE = REPO / "Makefile"
BOTMAIN = REPO / "control" / "app" / "botmain.py"

TELEGRAM_SETTINGS = (
    "HASHI_TELEGRAM_BOT_TOKEN",
    "HASHI_TELEGRAM_OWNER_ID",
    "HASHI_TELEGRAM_API_URL",
)

# This project's e2e half of its published-port block, loopback only (.env.example).
E2E_BLOCK = range(54200, 54300)


def load(path: pathlib.Path) -> dict:
    return yaml.safe_load(path.read_text())


@pytest.fixture(scope="module")
def overlay() -> dict:
    return load(E2E)["services"]


@pytest.fixture(scope="module")
def telegram(overlay: dict) -> dict:
    assert "telegram" in overlay, "the e2e overlay runs no `telegram` service"
    return overlay["telegram"]


@pytest.fixture(scope="module")
def bot(overlay: dict) -> dict:
    """The bot service the overlay switches on — M39. It is the process that polls now,
    so the fixtures that pointed the stand at the fake live on it, not on `control`."""
    assert "telegram-bot" in overlay, "the e2e overlay runs no `telegram-bot` service"
    return overlay["telegram-bot"]


# --- the wiring ---------------------------------------------------------------------


def test_the_fake_runs_on_the_control_images_own_python(telegram: dict) -> None:
    """One Python pin for the stand, not two that drift.

    The fake is standard-library only, so it needs nothing the control image's base
    does not have — and a second pin would be a second place to forget on a bump.
    """
    froms = [
        line.split()[1]
        for line in CONTROL_DOCKERFILE.read_text().splitlines()
        if line.upper().startswith("FROM ")
    ]
    assert telegram.get("image") in froms, (
        f"the fake runs on {telegram.get('image')!r}; the control image is built from "
        f"{froms} — one pin, written in deploy/docker/control.Dockerfile"
    )


def test_the_fake_is_mounted_read_only_and_exists(telegram: dict) -> None:
    mounts = telegram.get("volumes", [])
    assert mounts == ["../.e2e/fake_telegram.py:/srv/fake_telegram.py:ro"], mounts
    assert FAKE.is_file(), "the mount's source is not in the checkout"
    assert "/srv/fake_telegram.py" in " ".join(telegram["command"]), telegram["command"]


def test_the_fake_has_a_healthcheck_and_a_restart_policy(telegram: dict) -> None:
    """The rule the base file's services are held to, for the one the overlay adds."""
    assert "healthcheck" in telegram, "telegram: no healthcheck"
    assert "restart" in telegram, "telegram: no restart policy"


def test_the_bot_is_pointed_at_the_fake_and_the_control_plane_is_not(
    overlay: dict, telegram: dict, bot: dict
) -> None:
    """The three variables, set to the fake, the fixture token and the fixture id — on the
    BOT service now (M39), the one process that polls, and gone from `control`."""
    environment = bot["environment"]
    control = overlay["control"]["environment"]
    port = telegram["environment"]["FAKE_TELEGRAM_PORT"]
    # Dialled by ADDRESS on the isolated egress network, not by the `telegram` name — M40.
    # The bot shares the egress sidecar's namespace and the fake sits on the internal egress
    # network, reachable only through the leaf; so the bot dials the fake's egress IP, which
    # has no connected route from the sidecar and therefore leaves through the tunnel. Read
    # from the overlay's own network assignment so the two cannot drift.
    egress_ip = telegram["networks"]["egress"]["ipv4_address"]
    assert environment["HASHI_TELEGRAM_API_URL"] == f"http://{egress_ip}:{port}", (
        "the bot dials somewhere other than the fake's address on the egress network, on the "
        "port the fake was told to listen on — it must reach the fake only past the leaf"
    )
    assert environment["HASHI_TELEGRAM_BOT_TOKEN"], "no token, so the bot is off on the stand"
    owner = str(environment["HASHI_TELEGRAM_OWNER_ID"])
    assert owner.isdigit() and int(owner) > 0, f"the owner id {owner!r} is not a positive integer"
    for name in TELEGRAM_SETTINGS:
        assert name not in control, (
            f"{name} still reaches the control service on the stand — the web process must "
            "not poll (a second poller on one token is a 409 from Telegram)"
        )
    # Links the bot renders must match what this plain-HTTP stand serves, or the scenario's
    # link-equality check fails: the overlay sets HASHI_PUBLIC_HTTPS=false on control and the
    # bot has to carry the same, since the base anchor leaves it at the shipped https default.
    assert environment["HASHI_PUBLIC_HTTPS"] == "false", (
        "the bot would render https links the stand does not serve"
    )
    # The mapping's container side and the healthcheck have to name the same port.
    (mapping,) = telegram["ports"]
    assert str(mapping).endswith(f":{port}"), mapping
    assert f":{port}/" in " ".join(telegram["healthcheck"]["test"]), telegram["healthcheck"]


def test_the_bot_waits_for_the_fake(bot: dict) -> None:
    """So the poller's first call lands and its ready line is in the log from boot."""
    assert bot["depends_on"]["telegram"]["condition"] == "service_healthy"


def _load_gen():
    """The stand's egress-config generator, loaded from source (it is not a package)."""
    spec = importlib.util.spec_from_file_location(
        "gen_egress_configs", REPO / ".e2e" / "gen_egress_configs.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_sidecar_config_pins_the_endpoint_before_swapping_the_default() -> None:
    """The egress sidecar's own transport packets must not go through its own tunnel — M40.

    Swapping the default route to the tunnel without first pinning the leaf endpoint to the
    original gateway routes the WireGuard UDP to the leaf back INTO the tunnel, so no handshake
    completes on a real host (the stand hides it — its leaf is a connected route). Both the
    generated config and the operator README must pin the endpoint before the swap; the README's
    documented PostUp is held byte-for-byte against the generator so the two cannot drift.
    """
    gen = _load_gen()
    postup = gen.BOT_POSTUP
    pin_at = postup.find("via ")
    swap_at = postup.find("default dev %i")
    assert pin_at != -1, f"the sidecar PostUp pins no endpoint via a gateway:\n{postup}"
    assert swap_at != -1, f"the sidecar PostUp never swaps the default to the tunnel:\n{postup}"
    assert pin_at < swap_at, (
        "the sidecar PostUp swaps the default before pinning the endpoint, so the tunnel's own "
        f"transport packets route back into the tunnel and no handshake completes:\n{postup}"
    )
    # The generated config actually carries it, and the operator README documents the same line.
    conf = gen._bot_config("k" * 43 + "=", "p" * 43 + "=", "s" * 43 + "=", gen._obfuscation())
    assert gen.BOT_POSTUP in conf, "the generated awg0.conf does not use BOT_POSTUP"
    readme = (DEPLOY / "egress" / "README.md").read_text()
    assert gen.BOT_POSTUP in readme, (
        "deploy/egress/README.md's documented PostUp has drifted from the generator — the "
        "operator would write a config that pins the endpoint differently from the stand's"
    )


def test_the_sidecar_sends_dns_through_the_tunnel_not_the_host() -> None:
    """Name resolution must not leak — M40 round 1.

    Docker's embedded resolver forwards external lookups to the host resolver, so without this
    the bot would look up api.telegram.org in the clear from the Russian host. The sidecar's
    `dns:` repoints that upstream at a public resolver reached through the tunnel. The bot shares
    the sidecar's netns and resolv.conf, so this is the one place it is set. (The stand dials the
    fake by IP and makes no external lookup, so this is a static check; the field run validates
    the egress path — see deploy/egress/README.md.)
    """
    sidecar = load(BASE)["services"]["telegram-bot-egress"]
    assert sidecar.get("dns"), (
        "the egress sidecar sets no dns:, so the bot's external lookups leak to the host resolver"
    )


def test_the_fixture_values_are_not_the_shape_of_real_ones(bot: dict) -> None:
    """A token that could be mistaken for a real one is one somebody copies into .env.

    A real Bot API token is ``<digits>:<35 characters>``; the stand's must not be.
    """
    token = str(bot["environment"]["HASHI_TELEGRAM_BOT_TOKEN"])
    assert not re.fullmatch(r"\d+:[A-Za-z0-9_-]{35}", token), token
    assert "not-a-real" in token, "the token does not say what it is"


@pytest.mark.parametrize("path", OTHER_COMPOSE_FILES, ids=lambda p: p.name)
def test_the_fake_is_in_the_e2e_overlay_alone(path: pathlib.Path) -> None:
    """Nothing a developer or a deployed host brings up runs, or publishes, a fake."""
    assert "telegram" not in load(path).get("services", {}), (
        f"{path.name} knows a `telegram` service — the fake belongs to the stand only"
    )


def test_the_bot_service_carries_the_three_settings_and_control_does_not() -> None:
    """Each one explicitly on the bot, blank-tolerant, and none on the control plane — M39.1.

    The derived rule in test_compose.py demands every setting be reachable through either
    process; this names the three so the plan's own sentence is held by name, and pins WHICH
    process reads them: the bot alone, because a control plane that polled too would be a
    second poller on one token — 409 from Telegram, every update handled twice.
    """
    services = load(BASE)["services"]
    bot = services["telegram-bot"]["environment"]
    control = services["control"]["environment"]
    for name in TELEGRAM_SETTINGS:
        assert bot.get(name) == f"${{{name}:-}}", (
            f"{name} does not reach the telegram-bot container as `${{{name}:-}}`"
        )
        assert name not in control, (
            f"{name} still reaches the control service — the web process must not poll"
        )


def test_the_bot_runs_as_its_own_container_off_by_default() -> None:
    """The service that replaced the in-process bot — M39.1: the control image, the `bot`
    command, behind a profile so `make up` is unchanged, outbound-only, waiting for the
    control plane that runs the shared schema's migrations.
    """
    services = load(BASE)["services"]
    bot = services["telegram-bot"]
    assert bot["build"] == services["control"]["build"], (
        "the bot is not built from the control image"
    )
    assert bot["command"] == ["bot"], bot.get("command")
    assert bot.get("profiles") == ["telegram-bot"], (
        "the bot is not behind the telegram-bot profile, so `make up` would start it"
    )
    assert "ports" not in bot, "the bot publishes a port; it is outbound-only"
    assert bot["depends_on"]["control"]["condition"] == "service_healthy", (
        "the bot does not wait for the control plane, which runs the shared schema's migrations"
    )


def test_make_turns_the_bot_on_through_a_profile() -> None:
    """`make up PROFILES=telegram-bot` has to actually switch the profile on. A COMPOSE that
    did not carry PROFILES would take the variable and start nothing — the silent shape of
    the E2E_PROFILES bug this project already met once.
    """
    makefile = MAKEFILE.read_text()
    assert re.search(r"^PROFILES\s*\?=", makefile, re.M), "the Makefile declares no PROFILES"
    assert re.search(
        r"^COMPOSE\s*:?=.*foreach\s+\w+,\s*\$\(PROFILES\).*--profile", makefile, re.M
    ), "COMPOSE does not turn PROFILES into --profile flags, so `make up PROFILES=…` is a no-op"


def _heartbeat_path_in_botmain() -> str:
    """The ``HEARTBEAT_PATH`` literal in control/app/botmain.py, read from the source so this
    test needs none of the bot process's own imports."""
    tree = ast.parse(BOTMAIN.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "HEARTBEAT_PATH"
            for target in node.targets
        ):
            call = node.value
            assert isinstance(call, ast.Call) and call.args, (
                "HEARTBEAT_PATH is no longer pathlib.Path(<literal>)"
            )
            literal = call.args[0]
            assert isinstance(literal, ast.Constant), "HEARTBEAT_PATH is not a plain string literal"
            return str(literal.value)
    raise AssertionError("control/app/botmain.py no longer defines HEARTBEAT_PATH")


def test_the_bot_healthcheck_reads_the_heartbeat_the_bot_writes() -> None:
    """The one file botmain rewrites while polling and the one the healthcheck reads have to
    be the same — M39.1. They live in two files whose own comments say they must agree, and a
    drift would make the healthcheck read a file nothing writes and call a live bot unhealthy.
    """
    path = _heartbeat_path_in_botmain()
    test = load(BASE)["services"]["telegram-bot"]["healthcheck"]["test"]
    healthcheck = " ".join(test) if isinstance(test, list) else str(test)
    assert path in healthcheck, (
        f"botmain writes {path!r} but the telegram-bot healthcheck reads {healthcheck!r} — "
        "the two have drifted"
    )


def test_env_example_names_the_three_settings_and_leaves_them_blank() -> None:
    """Where the operator fills them in — and never with a value that could be real."""
    lines = ENV_EXAMPLE.read_text().splitlines()
    for name in TELEGRAM_SETTINGS:
        assert f"{name}=" in lines, f".env.example has no `{name}=` line"


def test_the_injection_port_is_on_the_e2e_block_and_driven_like_the_others() -> None:
    """One number in three places that have to agree, and all of them on the e2e block.

    The Makefile's default is what ``make e2e-up`` passes; ``.env.example`` is where the
    operator reads it; the overlay's ``:-`` default is what a hand-typed compose command
    gets. A disagreement is a scenario talking to the wrong port with no error.
    """
    makefile = MAKEFILE.read_text()
    declared = re.search(r"^E2E_TELEGRAM_PORT\s*\?=\s*(\d+)\s*$", makefile, re.M)
    assert declared, "the Makefile declares no E2E_TELEGRAM_PORT"
    port = int(declared.group(1))
    assert port in E2E_BLOCK, f"{port} is outside the e2e block {E2E_BLOCK}"
    # The assignment may continue over backslash-newlines; the variable may be on any of them.
    carried = r"^E2E_PORTS\s*:=[^\n]*(\\\n[^\n]*)*E2E_TELEGRAM_PORT=\$\(E2E_TELEGRAM_PORT\)"
    assert re.search(carried, makefile, re.M), (
        "E2E_PORTS does not carry E2E_TELEGRAM_PORT, so `make e2e-up E2E_TELEGRAM_PORT=…` "
        "changes nothing"
    )
    assert f"E2E_TELEGRAM_PORT={port}" in ENV_EXAMPLE.read_text().splitlines(), (
        ".env.example does not document E2E_TELEGRAM_PORT with the Makefile's default"
    )
    (mapping,) = load(E2E)["services"]["telegram"]["ports"]
    assert f"${{E2E_TELEGRAM_PORT:-{port}}}" in str(mapping), mapping


# --- the fake itself ----------------------------------------------------------------


def test_the_fake_imports_nothing_outside_the_standard_library() -> None:
    """It runs on a bare base image, so a third-party import is a stand that never starts."""
    tree = ast.parse(FAKE.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    outside = sorted(imported - set(sys.stdlib_module_names))
    assert outside == [], f"the fake imports {outside}, which the base image does not have"


def test_the_fake_silences_the_request_log() -> None:
    """The stock handler writes every request line to stderr, token and all."""
    tree = ast.parse(FAKE.read_text())
    handlers = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and any(getattr(base, "id", None) == "BaseHTTPRequestHandler" for base in node.bases)
    ]
    assert handlers, "no request handler in the fake"
    for handler in handlers:
        defined = {node.name for node in handler.body if isinstance(node, ast.FunctionDef)}
        assert "log_message" in defined, f"{handler.name} inherits the stdlib's request log"


@pytest.fixture
def fake():
    """The fake, live on an ephemeral port in this process, with its own fresh state."""
    spec = importlib.util.spec_from_file_location("fake_telegram", FAKE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    server = module.Server(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.port}"
    finally:
        server.shutdown()
        server.server_close()


def call(base: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    """One request; POST with a JSON body when one is given, else GET."""
    request = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode() if body is not None else None,
        method="POST" if body is not None else "GET",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as refused:
        return refused.code, json.loads(refused.read())


TOKEN = "/bot0000000000:infra-test-token-that-must-not-be-logged"


def test_get_me_answers_in_the_bot_apis_envelope(fake: str) -> None:
    status, answer = call(fake, f"{TOKEN}/getMe", {})
    assert status == 200 and answer["ok"] is True
    assert answer["result"]["is_bot"] is True and answer["result"]["username"]


def test_an_empty_poll_waits_its_timeout_and_answers_nothing(fake: str) -> None:
    started = time.monotonic()
    status, answer = call(
        fake, f"{TOKEN}/getUpdates", {"timeout": 1, "allowed_updates": ["message"]}
    )
    assert status == 200 and answer == {"ok": True, "result": []}
    assert time.monotonic() - started >= 0.9, "the poll answered before its timeout"


def test_an_injection_wakes_a_waiting_poll_at_once(fake: str) -> None:
    """The reason the e2e scenario waits for an add and never for a poll period."""
    answers: list[tuple[int, dict]] = []
    poll = threading.Thread(
        target=lambda: answers.append(call(fake, f"{TOKEN}/getUpdates", {"timeout": 20}))
    )
    poll.start()
    time.sleep(0.3)
    started = time.monotonic()
    status, injected = call(fake, "/_test/updates", {"from_id": 424242, "text": "/adduser mira"})
    assert status == 200 and injected["result"]["update_id"] == 1
    poll.join(timeout=5)
    assert not poll.is_alive(), "the poll sat on its timeout after an update was queued"
    assert time.monotonic() - started < 2
    ((status, answer),) = answers
    message = answer["result"][0]["message"]
    assert answer["result"][0]["update_id"] == 1
    assert message["from"]["id"] == 424242 and message["chat"] == {"id": 424242, "type": "private"}
    assert message["text"] == "/adduser mira"


def test_an_update_is_delivered_until_the_offset_passes_it(fake: str) -> None:
    """Telegram's semantics: reading is not acknowledging; the next offset is."""
    call(fake, "/_test/updates", {"from_id": 1, "text": "first"})
    call(fake, "/_test/updates", {"from_id": 1, "text": "second"})
    ids = lambda answer: [update["update_id"] for update in answer["result"]]  # noqa: E731

    _, answer = call(fake, f"{TOKEN}/getUpdates", {"timeout": 0})
    assert ids(answer) == [1, 2]
    _, answer = call(fake, f"{TOKEN}/getUpdates", {"timeout": 0})
    assert ids(answer) == [1, 2], "an update vanished because it was read"
    _, answer = call(fake, f"{TOKEN}/getUpdates", {"timeout": 0, "offset": 2})
    assert ids(answer) == [2], "an offset does not deliver from itself"
    _, answer = call(fake, f"{TOKEN}/getUpdates", {"timeout": 0})
    assert ids(answer) == [2], "an offset did not confirm what lies below it"
    _, answer = call(fake, f"{TOKEN}/getUpdates", {"timeout": 0, "offset": 3})
    assert ids(answer) == []


def test_a_full_update_is_queued_as_given_under_the_fakes_own_id(fake: str) -> None:
    update = {
        "update_id": 999,
        "message": {
            "message_id": 7,
            "date": 1,
            "from": {"id": 5, "is_bot": False, "first_name": "Someone"},
            "chat": {"id": 5, "type": "private"},
            "text": "hello",
            "forward_date": 1,
        },
    }
    status, injected = call(fake, "/_test/updates", update)
    assert status == 200 and injected["result"]["update_id"] == 1, "Telegram numbers updates"
    _, answer = call(fake, f"{TOKEN}/getUpdates", {"timeout": 0})
    assert answer["result"] == [{"message": update["message"], "update_id": 1}]


def test_send_message_is_recorded_verbatim_and_read_back(fake: str) -> None:
    body = {"chat_id": 424242, "text": "hi", "link_preview_options": {"is_disabled": True}}
    status, answer = call(fake, f"{TOKEN}/sendMessage", body)
    assert status == 200 and answer["ok"] is True
    assert answer["result"]["message_id"] == 1 and answer["result"]["chat"]["id"] == 424242
    status, recorded = call(fake, "/_test/sent")
    assert status == 200 and recorded == {"ok": True, "result": [body]}


def test_anything_else_is_refused_in_the_envelope(fake: str) -> None:
    for path, body in (
        (f"{TOKEN}/deleteWebhook", {}),
        ("/not-the-bot-api", {}),
        ("/_test/nothing", None),
    ):
        status, answer = call(fake, path, body)
        assert status == 404 and answer["ok"] is False and answer["description"], (path, answer)
    status, answer = call(fake, f"{TOKEN}/sendMessage", {"text": "no chat"})
    assert status == 400 and answer["ok"] is False
    status, answer = call(fake, "/_test/updates", {"text": "no sender"})
    assert status == 400 and answer["ok"] is False


def test_no_request_line_reaches_stderr(fake: str) -> None:
    """Live, not only by inspection: the token is in every path, and stderr is the log."""
    captured = io.StringIO()
    with contextlib.redirect_stderr(captured):
        call(fake, f"{TOKEN}/getMe", {})
        call(fake, f"{TOKEN}/nothing", {})
        call(fake, "/_test/sent")
        # The handler threads write after the response is on the wire; give them a beat.
        time.sleep(0.2)
    assert captured.getvalue() == "", f"the fake wrote to stderr:\n{captured.getvalue()}"
    assert TOKEN not in captured.getvalue()
