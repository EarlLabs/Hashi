"""What a push of delivery material does to a host's directory — M27.2.

WHAT: the path one artifact is written under, the names this package refuses, and the
      order of the commands ``edge.bootstrap.delivery.place_delivery`` runs — which is
      what makes a push a REPLACEMENT of the host's delivery material rather than an
      addition to it.
WHY:  an artifact is somebody's rendered subscription. Merging would mean a host goes
      on holding — and, once something serves the directory, on handing out — a
      document for a person who no longer holds a credential on it, with no path in
      this product that ever takes it away. ``docs/decisions.md`` (2026-09-13) records
      that an apply never removes what an earlier one wrote; this directory is the one
      place that is not true, and these tests are what holds it.
HOW:  two halves. The ORDER is proven against a stub connection, exactly as
      ``test_node_preparation`` does — ``place_delivery`` touches a node only through
      ``run`` and ``write_file``, so a recorder that answers both proves the sequence in
      microseconds. What those two commands DO is proven by running the exact strings
      under this host's own ``/bin/sh`` against a temporary directory, the way
      ``test_the_wireguard_family_can_start`` runs the supervisor: they contain
      ``rm -rf`` and they run on a node, and a shell construct busybox accepts and this
      host does not — or the reverse — is a push that fails on the host.

      Stated plainly: nothing here reaches a node over SSH. What it proves is that this
      package cannot write an artifact outside its own directory, and cannot leave one
      behind that the control plane stopped rendering.
"""

import pathlib
import subprocess

import pytest

from edge.bootstrap.delivery import (
    _STAGE,
    _SWAP,
    ARTIFACT_EXTENSION,
    DELIVERY_DIR,
    INCOMING_DIR,
    Artifact,
    UndeliverableArtifact,
    artifact_path,
    place_delivery,
)
from edge.bootstrap.node_stack import CONFIG_DIR, NODE_ROOT
from edge.bootstrap.ssh import CommandResult
from edge.registry import SubscriptionFormat

OK = CommandResult(exit_status=0, stdout="", stderr="")

# A name of the shape the control plane derives — 64 hex characters. Fixed here rather
# than computed, because what this zone does with a name must not depend on how one was
# arrived at.
NAME = "f" * 64
OTHER_NAME = "a" * 64


class _Recorder:
    """A node that accepts everything, and remembers what it was asked to do.

    One list for both kinds of step, in the order they happened, because the ORDER is
    the property under test: a write that lands after the swap is a write into a
    directory nothing will replace.
    """

    def __init__(self) -> None:
        self.commands: list[str] = []
        self.written: list[tuple[str, bytes | str, int]] = []
        self.steps: list[str] = []

    async def run(self, command: str, *, check: bool = True) -> CommandResult:
        self.commands.append(command)
        self.steps.append(command)
        return OK

    async def write_file(self, path: str, content, *, mode: int = 0o600) -> None:
        self.written.append((path, content, mode))
        self.steps.append(f"write {path}")


def an_artifact(name: str = NAME, *, shape=SubscriptionFormat.V1_URI_LIST) -> Artifact:
    return Artifact(name=name, shape=shape, content=b"opaque to this zone")


async def test_an_artifact_is_written_under_the_staging_directory_and_not_the_live_one() -> None:
    """The write goes to ``.incoming``; the live path only ever appears in the swap.

    The whole replacement rests on this: a write that targets the live directory is a
    merge whatever the last command says.
    """
    node = _Recorder()

    await place_delivery(node, artifacts=[an_artifact()])

    written_paths = [path for path, _, _ in node.written]
    assert written_paths == [f"{INCOMING_DIR}/{NAME}.txt"], written_paths
    assert not any(path.startswith(f"{DELIVERY_DIR}/") for path in written_paths), (
        "an artifact was written straight into the live directory, so this push adds to "
        "what the host holds instead of replacing it"
    )


async def test_the_swap_is_the_last_thing_that_happens() -> None:
    """Stage, write, swap — and a test that reads the order rather than assuming it."""
    node = _Recorder()

    await place_delivery(
        node, artifacts=[an_artifact(), an_artifact(OTHER_NAME)]
    )

    assert len(node.commands) == 2, node.commands
    staging, swap = node.commands
    assert node.steps[0] == staging, "something was written before the staging directory existed"
    assert node.steps[-1] == swap, "the live directory was replaced before every write had landed"
    assert f"mv {INCOMING_DIR} {DELIVERY_DIR}" in swap, swap


async def test_an_empty_push_is_how_a_host_stops_holding_delivery_material() -> None:
    """Nothing to place still replaces the directory — the one removal path there is.

    A host that stops carrying anyone's material gets an empty directory, not its last
    one. Without this, "this node no longer serves anybody" would leave every artifact
    it was last given on disk for as long as the host exists.
    """
    node = _Recorder()

    await place_delivery(node, artifacts=[])

    assert node.written == [], node.written
    assert len(node.commands) == 2, (
        "an empty push skipped the replacement, so a host that stopped carrying users "
        f"keeps the artifacts it was last given: {node.commands}"
    )
    assert f"mv {INCOMING_DIR} {DELIVERY_DIR}" in node.commands[-1]


async def test_the_previous_material_is_moved_aside_and_then_removed() -> None:
    """The live directory is never merged into, and never left beside the new one."""
    node = _Recorder()

    await place_delivery(node, artifacts=[an_artifact()])

    swap = node.commands[-1]
    assert swap.startswith(f"rm -rf {DELIVERY_DIR}.replaced"), swap
    assert swap.endswith(f"rm -rf {DELIVERY_DIR}.replaced"), (
        "what the host held before this push is still on disk when the push ends: "
        f"{swap}"
    )


async def test_every_artifact_is_written_0600() -> None:
    """Somebody's own configuration, on a host with other accounts on it."""
    node = _Recorder()

    await place_delivery(node, artifacts=[an_artifact(), an_artifact(OTHER_NAME)])

    assert {mode for _, _, mode in node.written} == {0o600}, node.written


async def test_two_shapes_of_one_subscription_do_not_overwrite_each_other() -> None:
    """One name, two shapes, two files — the extension is what tells them apart."""
    node = _Recorder()

    await place_delivery(
        node,
        artifacts=[
            an_artifact(shape=SubscriptionFormat.V1_URI_LIST),
            an_artifact(shape=SubscriptionFormat.CLIENT_CONFIG_FILE),
        ],
    )

    written_paths = [path for path, _, _ in node.written]
    assert len(set(written_paths)) == 2, written_paths
    assert set(written_paths) == {
        f"{INCOMING_DIR}/{NAME}{ARTIFACT_EXTENSION[shape]}"
        for shape in (SubscriptionFormat.V1_URI_LIST, SubscriptionFormat.CLIENT_CONFIG_FILE)
    }


@pytest.mark.parametrize(
    "name",
    [
        "../../etc/passwd",
        "..",
        "",
        "short",
        f"{'a' * 60}/{'b' * 60}",
        f"{NAME}.txt",
        "f" * 129,
    ],
)
def test_a_name_that_is_not_one_path_segment_is_refused(name: str) -> None:
    """Refused while building the path, before anything is opened on a node."""
    with pytest.raises(UndeliverableArtifact):
        artifact_path(name, SubscriptionFormat.V1_URI_LIST)


def test_delivery_material_is_not_written_where_every_daemon_can_read_it() -> None:
    """Not under the config directory, which the rendered compose file mounts into
    every data-plane container.

    These artifacts are other people's client configurations; a transport's daemon has
    no reason to be able to read one, and the mount that would let it is read-only and
    directory-wide.
    """
    assert not DELIVERY_DIR.startswith(f"{CONFIG_DIR}/"), (
        f"{DELIVERY_DIR} is inside {CONFIG_DIR}, which node-compose.yml.j2 bind-mounts "
        "into every data-plane container"
    )


# --- and the same two commands, run by a real shell ----------------------------------
#
# The stub above proves the ORDER; it cannot prove that a shell accepts these strings or
# that they do what they say. They contain `rm -rf` and they run on a node, so they are
# exercised here the way ``_WG_QUICK_SUPERVISOR`` is — the exact strings, under this
# host's own /bin/sh, with the node root rebased into a temporary directory so nothing
# outside it can be reached.


def _run(command: str, root: pathlib.Path) -> subprocess.CompletedProcess:
    rebased = command.replace(NODE_ROOT, str(root))
    assert NODE_ROOT not in rebased, "the rebase missed a path and this would touch a real one"
    return subprocess.run(["/bin/sh", "-c", rebased], capture_output=True, text=True, check=True)


@pytest.mark.parametrize("command", [_STAGE, _SWAP], ids=["stage", "swap"])
def test_both_commands_are_posix_shell(command: str) -> None:
    """``sh -n`` on this host, for the reason M21.3 gives: a node's shell is busybox and
    this one is not, and a construct only one of them accepts is a push that fails on
    the host rather than here."""
    checked = subprocess.run(
        ["/bin/sh", "-n", "-c", command], capture_output=True, text=True
    )
    assert checked.returncode == 0, checked.stderr


def test_the_sequence_replaces_the_directory_on_a_real_shell(tmp_path) -> None:
    """Stage, write, swap — three times over, on a filesystem.

    First push onto a host that has nothing, second push replacing it, third push with
    nothing to place. The third is the one the stop case rests on.
    """
    live = tmp_path / "delivery"

    _run(_STAGE, tmp_path)
    (tmp_path / "delivery.incoming" / "first").write_text("x")
    _run(_SWAP, tmp_path)
    assert sorted(path.name for path in live.iterdir()) == ["first"]
    assert sorted(path.name for path in tmp_path.iterdir()) == ["delivery"], (
        "the staging or the previous directory is still beside the live one"
    )

    _run(_STAGE, tmp_path)
    (tmp_path / "delivery.incoming" / "second").write_text("x")
    _run(_SWAP, tmp_path)
    assert sorted(path.name for path in live.iterdir()) == ["second"], (
        "the previous push's material survived a push that does not render it"
    )

    _run(_STAGE, tmp_path)
    _run(_SWAP, tmp_path)
    assert list(live.iterdir()) == [], (
        "a host that stopped carrying anybody still holds the material it was last given"
    )


def test_the_staging_directory_is_private(tmp_path) -> None:
    """0700 on the directory, as ``prepare`` sets on the config one: the files in it are
    0600, and a directory anyone can list is a directory anyone can count users in."""
    _run(_STAGE, tmp_path)

    assert (tmp_path / "delivery.incoming").stat().st_mode & 0o777 == 0o700
