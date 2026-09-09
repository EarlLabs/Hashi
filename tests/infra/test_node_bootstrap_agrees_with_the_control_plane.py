"""The two halves of the product, checked against each other — M13.2.

WHAT: that ``scripts/node-bootstrap.sh`` and ``edge/bootstrap/node_stack.py`` agree about
      which accounts can drive a node: the same directory, owned by the same account, with
      neither side assuming a privilege the other did not grant.
WHY:  M13 is the failure this file exists to make impossible. The script deliberately
      supports a non-root account, puts it in the ``docker`` group and ends by telling the
      operator to register it as ``ssh_user``; the library then created ``/opt/hashi``
      inside root-owned ``/opt`` as that very account, and every apply died on
      ``Permission denied``. Both halves were individually correct and individually
      tested. Nothing read them together, and the disagreement is invisible from either
      side alone — which is why the fix without this file would be worth less than this
      file without the fix.
HOW:  the script is READ, never run (the convention of ``test_node_bootstrap_script.py``);
      the library is IMPORTED, so the values compared are the ones a node really gets
      rather than a second copy of them in a regex. Assertions anchor on command position,
      not on prose: both files talk about ``sudo`` and about ``/opt/hashi`` in comments,
      and a rule that cannot tell an explanation from a command cannot be written honestly.

      This suite lives in the infra zone because that is where the script and its tests
      live, and because a cross-check has to sit on one side or the other. The cost is
      that ``make test-edge`` alone will not catch a change made to ``NODE_ROOT`` from the
      edge side — ``make test`` and CI will. The constant carries a comment saying so.
"""

import pathlib
import re

import pytest

from edge.bootstrap import node_stack

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "node-bootstrap.sh"
LIBRARY = REPO / "edge" / "bootstrap" / "node_stack.py"
RUNBOOK = REPO / "docs" / "deploy" / "runbook.md"

# What escalation looks like, in a command rather than in a sentence about one.
ESCALATIONS = ("sudo", "su -", "doas", "pkexec", "runuser")


@pytest.fixture(scope="module")
def script() -> str:
    return SCRIPT.read_text()


@pytest.fixture(scope="module")
def creation(script: str) -> str:
    """The one line that creates the node's directory on the host."""
    line = re.search(r"^as_root install -d[^\n]*NODE_ROOT[^\n]*$", script, re.M)
    assert line, (
        "the script no longer creates the node's directory — an apply as a non-root "
        "ssh_user then dies on `mkdir: cannot create directory '/opt/hashi': Permission "
        "denied`, which is M13 exactly"
    )
    return line.group(0)


@pytest.fixture(scope="module")
def commands() -> list[str]:
    """Every command the library runs on a node, taken from its call sites.

    Read from the source rather than by driving a fake connection, because what matters
    here is that no command exists in the file at all — a branch this suite forgot to
    reach would otherwise pass by not running.
    """
    found = re.findall(r'connection\.run\(\s*f?"([^"]*)"', LIBRARY.read_text())
    assert found, "no commands were found — this fixture's regex has stopped matching"
    return found


def test_the_script_creates_exactly_the_directory_the_library_writes_into(
    script: str,
) -> None:
    """One value, two files, and no mechanism until now that noticed they had parted.

    The script cannot import the constant — it is piped to a host that has none of this
    repository on it — so the value is duplicated by necessity. What is not necessary is
    for the duplication to be silent.
    """
    declared = re.search(r'^NODE_ROOT="([^"]+)"$', script, re.M)
    assert declared, "the script no longer names the node root, so nothing pins it"
    assert declared.group(1) == node_stack.NODE_ROOT, (
        f"the script prepares {declared.group(1)} and the control plane writes into "
        f"{node_stack.NODE_ROOT} — a node prepared by one is unusable by the other"
    )


def test_the_directory_is_owned_by_the_account_the_operator_is_told_to_register(
    script: str, creation: str
) -> None:
    """THE assertion of this milestone, and the one that would have caught it.

    The bug was not a wrong path — it was a directory the registered account could not
    write into. So the account named in the ``-o`` of the creation, the account added to
    the ``docker`` group, and the account the closing line tells the operator to enter as
    ``ssh_user`` must be one and the same. Creating it owned by root while still
    advertising a non-root ``ssh_user`` is M13, and turns this red.
    """
    owner = re.search(r'-o "\$\{(\w+)\}"', creation)
    assert owner, f"the directory is created without an owner: {creation!r}"

    advertised = re.search(r'say "register it in the panel with ssh_user \$\{(\w+)\}', script)
    assert advertised, "the run no longer tells the operator which account to register"

    grouped = re.search(r'usermod -aG docker "\$\{(\w+)\}"', script)
    assert grouped, "the account is no longer given access to the docker socket"

    assert owner.group(1) == advertised.group(1) == grouped.group(1), (
        f"the host is prepared for one account and the operator is told to register "
        f"another: the directory belongs to ${{{owner.group(1)}}}, the docker group to "
        f"${{{grouped.group(1)}}}, and the panel is told ${{{advertised.group(1)}}}"
    )


def test_the_library_never_escalates_privilege_on_a_node(commands: list[str]) -> None:
    """The other side of the same contract: the account gets a directory, not a `sudo`.

    This is the shape M13 chose over teaching the library to escalate, and it is only
    safe while both halves hold. A `sudo` appearing here without the script being changed
    would be one half of the second shape — which works on hosts with passwordless sudo
    and fails silently on the ones the first shape supports.
    """
    for command in commands:
        for escalation in ESCALATIONS:
            assert escalation not in command, (
                f"the control plane escalates privilege on a node: {command!r}. If that is "
                "now the intended shape, the bootstrap script must stop creating the "
                "directory and the runbook must stop promising it."
            )


def test_the_library_writes_nowhere_but_the_directory_it_was_given(
    commands: list[str],
) -> None:
    """"Which accounts work" is decided by what the account is asked to touch.

    An unprivileged account can be relied on for exactly two things: what it owns under
    the node root, and the docker socket its group membership grants. So every command
    whose failure stops an apply may name absolute paths only under ``NODE_ROOT``. The
    best-effort ones — time sync, the docker version probe — are exempt because they run
    with ``check=False`` and a host that refuses them is not failed for it.
    """
    best_effort = ("timedatectl", "systemctl", "docker version", "test -")
    for command in commands:
        if any(command.startswith(prefix) or prefix in command for prefix in best_effort):
            continue
        for path in re.findall(r"(?<![\w{])/[\w./{}-]+", command):
            assert path.startswith("{NODE_ROOT}") or path.startswith("{CONFIG_DIR}"), (
                f"an apply fails unless the account can write {path} — which is a demand "
                f"for root that the bootstrap script does not grant: {command!r}"
            )
    # And the two paths every file lands at are inside it, so the same guarantee covers
    # the SFTP transfers, which issue no command at all.
    assert node_stack.CONFIG_DIR.startswith(f"{node_stack.NODE_ROOT}/")
    assert node_stack.COMPOSE_PATH.startswith(f"{node_stack.NODE_ROOT}/")


def test_the_repair_the_library_suggests_is_the_one_the_script_performs(
    creation: str,
) -> None:
    """A host prepared before this script existed still has to be told what to do.

    ``HOST_NOT_PREPARED`` is what an operator reads when the directory is missing, and it
    hands them two ways out: run the script, or create the directory by hand. The second
    is a copy of what the script does — so it is pinned to the script, or it drifts into
    advice that produces a directory the control plane still cannot use.
    """
    reason = node_stack.HOST_NOT_PREPARED
    assert "scripts/node-bootstrap.sh" in reason, "the reason does not name the script"
    assert SCRIPT.is_file(), "the reason names a script this repository does not have"

    mode = re.search(r"-m (\d+)", creation)
    assert mode, f"the script creates the directory without a mode: {creation!r}"
    assert f"install -d -m {mode.group(1)} -o " in reason, (
        f"the by-hand repair does not match what the script does (-m {mode.group(1)}), so "
        "a host repaired by following it differs from one the script prepared"
    )
    assert node_stack.NODE_ROOT in reason, "the reason does not say which directory"

    # Three files, one repair. The operator meets it in the panel when the apply fails and
    # in the runbook when they go looking for why, and a repair that differs between the
    # two is one they cannot trust either version of.
    repair = re.search(rf"install -d -m \d+ -o \S+ {re.escape(node_stack.NODE_ROOT)}", reason)
    assert repair, f"the reason gives no runnable repair: {reason!r}"
    assert repair.group(0) in RUNBOOK.read_text(), (
        f"the runbook does not carry the repair the control plane prints "
        f"({repair.group(0)!r}), so an operator who reads the page gets a different "
        "instruction from the one the panel gave them"
    )
