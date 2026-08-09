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
    # The mechanism: strip every doubled dollar, then anything left is unescaped.
    assert re.search(r"sed 's/\\\$\\\$//g'", script), (
        "the script does not look for an unescaped $ in the env file"
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
    assert "DOES interpolate" in text, (
        "deploy/e2e.env does not warn the next person who regenerates the hash"
    )
