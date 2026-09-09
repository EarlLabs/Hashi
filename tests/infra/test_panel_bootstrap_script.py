"""The panel bootstrap's contract, read rather than run — backlog item 31.

WHAT: static checks over ``scripts/panel-bootstrap.sh`` and the Make target that calls it.
WHY:  the acceptance scenario runs the script for real (``tests/e2e/infra/``), which is
      the only way to prove it works. These are the properties whose absence a passing run
      would not reveal: the script could grow a ``read``, or a key generator, or the dev
      overlay, and still install a working panel on the machine it was tested on — and
      then hang, or leak, or publish a database on the host it was written for.
HOW:  the script is read, not run. Same division as ``test_backup_script.py``: what is
      provable by the tree is proven here, and running belongs to the e2e tier.

      Stated plainly: nothing here proves a panel comes up. It proves the script cannot
      quietly do the dangerous version of each step.
"""

import pathlib
import re
import stat

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "panel-bootstrap.sh"
MAKEFILE = REPO / "Makefile"


@pytest.fixture(scope="module")
def script() -> str:
    return SCRIPT.read_text()


@pytest.fixture(scope="module")
def script_without_comments(script: str) -> str:
    """The same script with its comment lines removed.

    For the assertions that say "this script must not DO x", where x is also something the
    comments explain at length. Anchoring on command position is the rule here (M11's
    notes), and a comment that quotes the line a step deleted is prose — matching it makes
    the test fail for describing its own reason, which teaches the next editor to delete
    the explanation rather than keep the property.
    """
    return "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("#")
    )


@pytest.fixture(scope="module")
def script_commands(script_without_comments: str) -> str:
    """Comments and the bodies of ``say`` / ``fail`` removed — what the shell would run.

    Needed because this script's refusals name the very commands the operator should run
    next: the ``sudo ufw logging off`` remedy sits indented inside a ``fail "..."``, at a
    column that reads as a command to any anchored regex. M11 solved the same problem in
    ``node-bootstrap.sh`` by anchoring on its ``as_root`` helper; there is no such helper
    here, because this script runs nothing as root at all.

    Only those two constructs, not every quoted string: the health probe is a quoted
    Python program and has to survive, and a general quote-stripper mis-pairs on the
    single quotes inside it. "What does it do" and "what does it say" are two questions,
    and they read two different fixtures.
    """
    return re.sub(r"\b(?:fail|say)\s+\\?\s*\"[^\"]*\"", " ", script_without_comments)


def test_the_script_exists_and_is_executable() -> None:
    """A script that has to be invoked via `bash` is one an operator mistypes."""
    assert SCRIPT.is_file(), "the charter's second deployment script does not exist"
    assert SCRIPT.stat().st_mode & stat.S_IXUSR


def test_it_fails_the_whole_run_on_any_error(script: str) -> None:
    """``set -euo pipefail``, and each letter earns its place here.

    Without ``-e`` a failed ``compose up`` is a log line and the script goes on to report
    success. Without ``-u`` a typo in a variable name becomes an empty string, which is
    how a stack gets built from a half-empty configuration.
    """
    assert re.search(r"^set -euo pipefail$", script, re.M), (
        "the script does not abort on the first error"
    )


def test_it_asks_no_questions(script: str) -> None:
    """Not one interactive prompt — the charter's second requirement.

    This script runs over a flaky SSH session while the owner is replacing a host. A
    prompt is not an inconvenience there: it is a run that hangs until the session dies,
    leaving a half-installed stack and no output to say how far it got.
    """
    for forbidden in (r"\bread\s+-", r"^\s*read\s", r"\bselect\s+\w+\s+in\b"):
        assert not re.search(forbidden, script, re.M), (
            f"the script contains an interactive construct matching {forbidden!r}"
        )


def test_it_never_generates_the_secret_key(script: str) -> None:
    """THE rule. It may TELL the operator how to make one; it may not make one.

    ``HASHI_SECRET_KEY`` decrypts every friend's credentials and every node's private
    key. Generated on the host being installed — which may be the Russian entry node — it
    would sit on the machine most likely to be seized, beside the data it opens.

    The distinction the assertion has to make is real: the refusal message deliberately
    contains a ``python3 -c 'secrets.token_urlsafe'`` line for the operator to run
    ELSEWHERE. So what is forbidden is assigning the variable or writing to the env file,
    not mentioning the words.
    """
    assert "HASHI_SECRET_KEY" in script, "the script does not check for the key at all"

    # No assignment of the key, exported or otherwise.
    assert not re.search(r"^\s*(export\s+)?HASHI_SECRET_KEY=", script, re.M), (
        "the script assigns HASHI_SECRET_KEY"
    )
    # And nothing appends to the env file.
    assert not re.search(r">>?\s*[\"']?\$\{?ENV_FILE", script), (
        "the script writes to the env file"
    )
    # Nor assigns it by default-expansion, nor in a command prefix, nor injects it into a
    # container without ever touching a shell variable. Each of these would slip past the
    # line-anchored check above, which is the gap this closes.
    assert "HASHI_SECRET_KEY:=" not in script, (
        "the script defaults HASHI_SECRET_KEY through parameter expansion"
    )
    assert not re.search(r"HASHI_SECRET_KEY=\$\(", script), (
        "the script assigns HASHI_SECRET_KEY from a command substitution"
    )
    assert not re.search(r"-e\s+HASHI_SECRET_KEY", script), (
        "the script injects HASHI_SECRET_KEY into a container directly"
    )
    # No generator anywhere near it. The refusal message names a command for the operator
    # to run ELSEWHERE, so this looks for the ones a script would use on itself.
    for generator in (r"openssl rand", r"pwgen", r"head -c \d+ /dev/urandom", r"uuidgen"):
        assert not re.search(generator, script), (
            f"the script contains a key generator ({generator!r})"
        )


def test_it_refuses_rather_than_defaulting_the_other_required_keys(script: str) -> None:
    """A default here would be the same value on every host that runs this script."""
    for key in (
        "HASHI_PUBLIC_HOST",
        # M7's two: the Caddyfile has a private site block now and compose
        # interpolates both values into the caddy service, so the stack does not
        # start at all without them.
        "HASHI_PRIVATE_HOST",
        "HASHI_PRIVATE_PORT",
        "HASHI_OPERATOR_USERNAME",
        "HASHI_OPERATOR_PASSWORD_HASH",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
    ):
        assert key in script, f"{key} is not checked before the stack is built"
        assert not re.search(rf"^\s*(export\s+)?{key}=", script, re.M), (
            f"the script supplies a default for {key}"
        )


def test_it_never_sources_the_env_file(script: str) -> None:
    """Sourcing runs it. A stray backtick in a password becomes a command on this host."""
    assert not re.search(r"^\s*(\.|source)\s+[\"']?\$\{?ENV_FILE", script, re.M), (
        "the script sources the env file instead of reading it"
    )


def test_it_uses_the_base_compose_file_and_not_the_dev_overlay(script: str) -> None:
    """The dev overlay is the only file that publishes ports.

    A panel host that published its database because a command was copied from a laptop is
    exactly the failure the split between the two compose files exists to prevent.
    """
    assert "deploy/docker-compose.yml" in script
    assert "docker-compose.dev.yml" not in script, (
        "the bootstrap uses the dev overlay, which publishes ports"
    )
    assert "docker-compose.e2e.yml" not in script


def test_nothing_in_it_is_destructive(script: str) -> None:
    """Idempotence, checked as the absence of the operations that would break it.

    ``compose up -d`` converges, so a second run is safe *as long as nothing else in the
    script undoes state*. A ``down`` before the ``up`` would make every re-run a restart
    of the database — the one service whose loss cannot be repaired by rebuilding a node.
    """
    for forbidden in (r"\bdown\b", r"\bvolume\s+rm\b", r"\brm\s+-rf\b", r"\bdocker\s+rm\b"):
        assert not re.search(rf"compose[^\n]*{forbidden}|^\s*{forbidden}", script, re.M), (
            f"the script contains a destructive operation matching {forbidden!r}, so a "
            "second run would not be a no-op"
        )


def test_it_probes_the_running_plane_rather_than_declaring_victory(script: str) -> None:
    """The charter's third requirement: it verifies BEFORE it reports success.

    Both questions matter. ``/healthz`` proves the process is serving; the 404 on the
    delivery route proves the route a friend uses is actually wired — a live process with
    an unrouted ``/sub`` is a panel that looks up and delivers nothing.
    """
    assert "/healthz" in script
    assert "/sub/" in script, "the delivery route is never probed"
    assert re.search(r"HEALTH_TIMEOUT", script), "the wait is unbounded"
    # The probe runs INSIDE the network, because the production stack publishes nothing.
    assert re.search(r"compose\[@\]\}\"?\s+exec", script) or "exec -T control" in script, (
        "the probe does not run inside the stack, so it must be relying on a published port"
    )


def test_the_probe_carries_no_real_token(script: str) -> None:
    """A probe of the delivery route must never send a live credential.

    The path is the credential on that route, so a probe built from a real token would put
    one into this script, into shell history, and into anything that records the command.
    """
    match = re.search(r"/sub/([^\s'\"]+)", script)
    assert match, "no delivery-route probe found"
    assert "not-a-real-token" in match.group(1) or "probe" in match.group(1), (
        f"the delivery probe uses {match.group(1)!r}, which does not read as fake"
    )


def test_the_owner_has_a_make_target_for_it() -> None:
    """The infra rulebook: an operation without a Make target is a bug in this zone."""
    makefile = MAKEFILE.read_text()
    assert re.search(r"^panel-bootstrap:", makefile, re.M), (
        "there is no `make panel-bootstrap`"
    )
    assert "panel-bootstrap" in re.search(
        r"^\.PHONY:.*$", makefile, re.M | re.S
    ).group(0) or re.search(r"^\.PHONY:[^\n]*panel-bootstrap", makefile, re.M), (
        "the target is not declared .PHONY"
    )


def test_it_refuses_an_env_file_with_an_unescaped_dollar(script: str) -> None:
    """The trap that cost an acceptance run, and would have cost the owner their panel.

    ``docker compose --env-file`` INTERPOLATES the values it reads. A scrypt password hash
    is ``scrypt$32768$8$1$<salt>$<digest>`` — four dollars — so ``$<salt>`` is read as a
    variable name and replaced with nothing. Whether that happens at all depends on the
    salt's first byte: a salt starting with a letter is destroyed, one starting with a
    digit survives. The same file therefore works on one host and silently locks the owner
    out on the next, with "Those credentials were not accepted" as the only symptom and a
    correct-looking hash sitting in the file.

    The script must refuse and explain. It must NOT fix the file: rewriting the file that
    holds the owner's secrets, to a value they did not choose, is worse than stopping.
    """
    # The mechanism: strip every doubled dollar from a VALUE, and anything left is
    # unescaped. Asserted as three properties rather than as one exact command line, so
    # the check can be reimplemented without this test having to be rewritten — but not
    # weakened without it noticing.
    assert re.search(r'gsub\(/\\\$\\\$/', script), (
        "the script does not strip doubled dollars before looking for a lone one"
    )
    assert "index($0" in script, (
        "the script scans whole lines rather than the value half of KEY=VALUE — it would "
        "then refuse an env file whose COMMENT mentions a dollar, which is a refusal the "
        "operator cannot act on and learns to work around"
    )
    assert re.search(r"\^\[\[:space:\]\]\*#", script), (
        "the script does not skip comment lines"
    )
    assert "unescaped" in script
    # It names the remedy, and does not write.
    assert "$$" in script
    assert not re.search(r"sed -i", script), "the script edits the env file in place"


def test_the_e2e_env_file_does_not_still_claim_env_files_are_not_interpolated() -> None:
    """A comment that is wrong about a hazard is worse than no comment.

    ``deploy/e2e.env`` used to say "an env file is not interpolated, so a `$` is a `$`".
    It is interpolated. The next person to regenerate that hash would have followed the
    comment and lost an afternoon.
    """
    text = (REPO / "deploy" / "e2e.env").read_text()
    assert "an env file is not interpolated" not in text, (
        "deploy/e2e.env still carries the comment that caused this"
    )
    assert "interpolates the values it reads" in text, (
        "deploy/e2e.env does not warn the next person who regenerates the hash"
    )
    # And the value is actually escaped, not merely commented about. A comment that
    # described the pre-fix state while the line below it was fixed is how the next
    # editor concludes that doubling is optional.
    hash_line = next(
        line for line in text.splitlines()
        if line.startswith("HASHI_OPERATOR_PASSWORD_HASH=")
    )
    value = hash_line.split("=", 1)[1]
    assert "$" in value, "the fixture hash has no $ at all, so this assertion is vacuous"
    assert value.replace("$$", "") .count("$") == 0, (
        "deploy/e2e.env's operator hash has an unescaped $ — compose will corrupt it and "
        "operator login will fail on a clean run"
    )


def test_it_does_not_print_an_address_it_has_not_proved_reachable(
    script: str, script_without_comments: str
) -> None:
    """M6.1, found on the live host: the success line named a URL nothing served.

    The script verified the stack from INSIDE the compose network and then printed
    ``The panel is at https://<host>/panel/`` while 80 and 443 were closed, because the
    base compose file publishes nothing and this script adds nothing. An address a script
    prints reads as an address a script checked — the same sin as ``echo ok``, which is
    the very thing property 3 exists to prevent.

    So either it publishes, or it says nothing about reachability. It says nothing, and
    says instead what it did prove and where the missing step is written down.
    """
    assert "The panel is at" not in script_without_comments, (
        "the closing line claims a panel address again, and nothing in this script makes "
        "one reachable"
    )
    assert not re.search(r"https?://\$\{", script_without_comments), (
        "the script builds a URL out of a configured host and prints it, which is a claim "
        "about the outside world that it has not checked"
    )
    assert "reachable from outside" in script, (
        "the run ends without telling the operator that nothing is reachable yet, so they "
        "go looking for a panel that is not there"
    )
    assert "port-publication gap" in script, (
        "the closing message does not point at the runbook section that says how to "
        "publish, which leaves the operator with a problem and no next step"
    )


def test_it_refuses_a_host_whose_firewall_is_recording_connections(
    script: str, script_commands: str
) -> None:
    """M6.2's second half. The record the charter forbids at any level.

    ``ufw enable`` turns logging on by default and writes a source address for every
    refused packet — 5840 bytes of it within minutes on the fleet's own leaf
    (docs/decisions.md, decision 5). This host is the one friends dial for a subscription,
    so its firewall log is a list of who asked for a config and when.

    Checked, never changed: turning it off belongs to ``scripts/node-bootstrap.sh``, which
    is the script that brings a firewall up. Anchored on command position rather than on
    the words, exactly as ``test_node_bootstrap_script.py`` does, because the refusal
    message legitimately contains the command it is telling the operator to run.
    """
    assert re.search(r"command -v ufw", script), (
        "the script never asks whether this host has a firewall that could be logging"
    )
    assert "LOGLEVEL" in script, (
        "the script does not read ufw's configured logging level, so it cannot tell an "
        "off host from a recording one"
    )
    assert re.search(r"sudo ufw logging off", script), (
        "the refusal does not name the command that fixes it"
    )
    # It must not run ufw itself. Command position only: `sudo ufw logging off` inside a
    # quoted message is the instruction, not the act.
    assert not re.search(r"^\s*(sudo\s+)?ufw\s", script_commands, re.M), (
        "the script runs ufw itself — it installs a control plane and must not rewrite "
        "the firewall of the host it is reached over"
    )
    # And there is no level of it that is allowed, not even while debugging.
    assert not re.search(r"ufw logging (?:on|low|medium|high|full)\b", script), (
        "the script names a ufw logging level other than off"
    )
    assert "not finish the job" in script, (
        "the script offers deleting /var/log/ufw.log as a cure — rsyslog, kern.log and "
        "the journal hold the same lines, and 22 of them survived that deletion on the "
        "live leaf. Logging being off beforehand is the only part that protects anyone."
    )


def test_a_second_run_does_not_rebuild_its_way_into_recreating_containers(script: str) -> None:
    """M6.5, and the reason property 1 was false for as long as this script has existed.

    BuildKit attaches a provenance attestation to every image it exports, and that
    attestation records when the build ran. So a FULLY CACHED rebuild still exports a
    manifest with a new digest — which is the image ID compose compares against the
    running container — and every service built from a Dockerfile was recreated on every
    run, with nothing in the output to say why.

    Asserted on the build command rather than on the whole file, because exporting the
    variable would also change how anything else in the run behaves.
    """
    build = re.search(r"^\s*if ! ([^\n]*up -d --build)", script, re.M)
    assert build, "the script no longer brings the stack up with a single converging build"
    assert "BUILDX_NO_DEFAULT_ATTESTATIONS=1" in build.group(1), (
        "the build does not disable BuildKit's default attestations, so every run exports "
        "a new image ID and compose recreates every built container — which makes the "
        "IDEMPOTENT property in this script's own header untrue"
    )


def test_it_generates_the_management_tunnel_rather_than_leaving_it_to_a_screen(
    script_commands: str,
) -> None:
    """M7's chicken-and-egg, and the reason it is solved in a bootstrap script.

    The panel cannot hand you the config you need to reach the panel, so the owner's
    management-tunnel config has to be produced by something that runs before there is
    a panel to log into. That is this script — the CONTROL PLANE's own bootstrap. It is
    deliberately not ``scripts/node-bootstrap.sh``: a node never joins this tunnel, and
    M11.1 fixed that script at docker, the key and the firewall.
    """
    assert "scripts/management-tunnel.sh" in script_commands, (
        "the panel bootstrap does not generate the management tunnel, so the owner's "
        "own way in is something they set up by hand"
    )
    assert "node-bootstrap" not in script_commands, (
        "the panel bootstrap reaches into the node bootstrap"
    )


def test_it_refuses_to_publish_the_console_on_loopback(script: str) -> None:
    """The mistake docker reports as "port is already allocated" and nothing explains.

    ``HASHI_PRIVATE_BIND_ADDR`` names the address the console is published on, and it
    is meant to be the management tunnel's. Loopback is already claimed for the same
    port by the fallback mapping beside it, so docker refuses the second bind with an
    error naming neither the cause nor the cure.
    """
    assert "HASHI_PRIVATE_BIND_ADDR" in script
    assert re.search(r"127\.\*\|localhost\|::1", script), (
        "the script does not check the private bind address for loopback"
    )
