"""A probe's finding survives the next click — M26, the first acceptance walk.

WHAT: that what a probe found is kept on the node's row, is still there after a plain
      reload of the Nodes screen, is said on the Overview beside the counters it
      contradicts, and is cleared by the two things that genuinely unsay it — a later
      probe that finds nothing, and a successful apply.
WHY:  the walk stopped ``hashi-node-amneziawg-1`` on its leaf and pressed probe. The
      probe was RIGHT — *"failed  leaf-acc answered but is not serving — not running:
      amneziawg."* — and one reload later the row read ``active`` beside ``in sync``,
      ``state_detail`` was empty, and the Overview read *"nodes active 2 … transports
      serving 2"* while that user's ``ping 1.1.1.1`` was 100% loss. The node stayed in
      every user's link. A measurement that is taken, is correct and is then discarded is
      worse than one never taken: the operator saw the truth once and the product
      overwrote it with a reassurance.
HOW:  against a fake host at the SHELL, like ``test_a_probe_says_what_it_checked.py`` —
      the real render, the real socket parser and the real summary all run, and the only
      invented thing is what the host answers. Both directions every time: a node whose
      probe found nothing must carry no note at all, or this file would pass on a product
      that warns about every host in the fleet.
"""

import pytest
import yaml

from control.app.services import apply, console, health, nodes
from edge.health import listening

from .conftest import GENERATED_SSH_KEY

# RFC 5737 documentation address, as everywhere in this zone. Never dialled: the
# connection is replaced.
NODE_ADDRESS = "192.0.2.40"

TRANSPORT = "vless-reality"

# A node's listening table as ``ss -l -n -t -u`` prints it, with nothing on the port the
# transport was given — which is the state the walk's leaf was in once its container was
# stopped, and the state this whole file is about.
SSH_ONLY = """Netid State  Recv-Q Send-Q    Local Address:Port  Peer Address:PortProcess
tcp   LISTEN 0      4096            0.0.0.0:22         0.0.0.0:*
tcp   LISTEN 0      4096               [::]:22            [::]:*
"""


def bound(port: int) -> str:
    """The same table with the transport's own socket on it."""
    return SSH_ONLY + f"tcp   LISTEN 0      4096            0.0.0.0:{port}      0.0.0.0:*\n"


class _FakeHost:
    """A node that answers the two questions a probe asks and holds what it was sent."""

    learned_host_key = None

    def __init__(self, *, sockets: str = SSH_ONLY) -> None:
        self.files: dict[str, str] = {}
        self.services: list[str] = []
        self.sockets = sockets

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info) -> bool:
        return False

    async def run(self, command: str, *, check: bool = True):
        from edge.bootstrap import node_stack
        from edge.bootstrap.ssh import CommandResult

        if "docker compose up -d" in command:
            self.services = list(
                yaml.safe_load(self.files[node_stack.COMPOSE_PATH])["services"]
            )
            return CommandResult(exit_status=0, stdout="", stderr="")

        if "docker inspect" in command:
            definitions = yaml.safe_load(self.files[node_stack.COMPOSE_PATH])["services"]
            lines = [
                f"{service}"
                f"|{definitions[service]['labels'][node_stack.CONFIG_DIGEST_LABEL]}"
                f"|true|false"
                # Which LIFE of the container this reading looked at — M26's second walk.
                # Constant per service here: this fake's containers do not crash-loop,
                # and an apply's settle check confirms only a container it saw staying up
                # across two readings.
                f"|one-life"
                for service in self.services
            ]
            return CommandResult(exit_status=0, stdout="\n".join(lines) + "\n", stderr="")

        if command == listening.LISTENING_SOCKETS:
            return CommandResult(exit_status=0, stdout=self.sockets, stderr="")

        if "docker version" in command:
            return CommandResult(exit_status=0, stdout="27.1.1\n", stderr="")

        return CommandResult(exit_status=0, stdout="", stderr="")

    async def write_file(self, path: str, content: str, *, mode: int = 0o600) -> None:
        self.files[path] = content

    async def read_file(self, path: str) -> str | None:
        return self.files.get(path)


@pytest.fixture
def host(monkeypatch: pytest.MonkeyPatch, reality_params):
    """One fake host, reached by both the apply that places configs and the probe.

    Returned so a test can change what it answers mid-run, which is the whole scenario:
    the same host serving, then not.

    IT STARTS OUT SERVING — its container is up and its port is held — and that is a
    correction from M26's THIRD walk rather than set dressing. This file used to apply
    its node to a host holding nothing, because an apply asked no port question; the walk
    found that an apply which does not ask cannot tell a daemon from a ``sleep``, so one
    now refuses such a host. A test whose ``given`` is a host in the state the product
    refuses would be proving nothing about the state it is written for.
    """
    fake = _FakeHost(sockets=bound(reality_params["port"]))
    for module in (apply, health):
        monkeypatch.setattr(module, "NodeConnection", lambda target: fake)
    return fake


def stops_serving(host) -> None:
    """The walk's own break: the daemon goes and nothing holds the port any more.

    Named rather than assigned in place at six call sites, because what it models is the
    premise of every finding in this file — the host was serving when it was applied and
    is not serving when it is probed.
    """
    host.sockets = SSH_ONLY


async def an_applied_node(client, reality_params, *, name: str = "leaf-acc") -> str:
    """One node with one transport, applied — so there is something to probe."""
    created = await client.post(
        "/api/nodes",
        json={
            "name": name,
            "address": NODE_ADDRESS,
            "location_label": "Testland",
            "ssh_host": NODE_ADDRESS,
            "ssh_private_key": GENERATED_SSH_KEY,
        },
    )
    assert created.status_code == 201, created.text
    node_id = created.json()["id"]
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": TRANSPORT, "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text
    applied = await client.post(f"/api/nodes/{node_id}/apply")
    assert applied.status_code == 200, applied.text
    return node_id


async def test_a_node_nobody_probed_carries_no_finding(
    client, session, reality_params, host, settings
) -> None:
    """The accept direction, and the reason it is first.

    Without it every assertion below could pass on a panel that warns about every node
    it has, which is the same uselessness as warning about none.
    """
    await an_applied_node(client, reality_params)

    rows = await console.node_rows(session, settings)

    assert [row.probe for row in rows] == [None]
    assert console.fleet_doubt(rows) == []


async def test_what_the_probe_found_is_still_there_after_a_reload(
    client, session, reality_params, host
) -> None:
    """The finding, on the screen the operator comes back to.

    Red against the previous commit: the finding existed only in the response to the
    press, so a plain re-fetch of the table said nothing at all about the node — which is
    exactly what the walk read one reload after a correct answer.
    """
    node_id = await an_applied_node(client, reality_params)
    stops_serving(host)

    probed = await client.post(f"/panel/nodes/{node_id}/probe")
    assert probed.status_code == 200, probed.text
    assert "is not serving" in probed.text, probed.text

    table = await client.get("/panel/nodes/table")

    assert table.status_code == 200, table.text
    said = " ".join(table.text.split())
    assert "is not serving" in said, (
        "the Nodes screen has forgotten a finding the operator was shown one click ago"
    )
    assert "probe," in said, "the kept finding does not say when it was found"


async def test_the_overview_says_what_its_counters_do_not_know(
    client, session, reality_params, host
) -> None:
    """The screen whose subtitle promises to say whether the nodes are running it.

    The counters stay what they are — they count configuration, and that node IS in
    service and IS in every user's link, which is the fact the operator has to act on.
    What changes is that the screen no longer says only that.
    """
    node_id = await an_applied_node(client, reality_params)
    stops_serving(host)
    await client.get(f"/api/nodes/{node_id}/health")

    body = await client.get("/panel/overview/body")

    assert body.status_code == 200, body.text
    said = " ".join(body.text.split())
    assert "The last probe of leaf-acc found it not serving" in said, said
    assert " ".join(console.COUNTERS_COUNT_CONFIGURATION.split()) in said, (
        "the Overview claims nothing about the limit of what it counted"
    )


async def test_an_unreachable_node_is_recorded_as_one_that_could_not_be_reached(
    client, session, reality_params, host, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other finding a probe can come back with, and it must not read like a fault
    on the host's containers — nobody looked at those."""
    node_id = await an_applied_node(client, reality_params)

    class _Unreachable:
        learned_host_key = None

        async def __aenter__(self):
            from edge.bootstrap import NodeUnreachable

            raise NodeUnreachable("this node's address could not be resolved")

        async def __aexit__(self, *_exc_info) -> bool:
            return False

    monkeypatch.setattr(health, "NodeConnection", lambda target: _Unreachable())
    await client.get(f"/api/nodes/{node_id}/health")

    node = await nodes.get_node(session, node_id)
    await session.refresh(node)

    assert node.last_probe_finding is not None
    assert "could not be reached" in node.last_probe_finding


async def test_a_later_probe_that_finds_nothing_clears_it(
    client, session, reality_params, host
) -> None:
    """A finding is a reading and not a stain.

    The operator fixes the host and presses the same button; the note goes. Without this
    the product would trade one permanent wrong answer for another.
    """
    node_id = await an_applied_node(client, reality_params)
    stops_serving(host)
    await client.get(f"/api/nodes/{node_id}/health")

    host.sockets = bound(reality_params["port"])
    healthy = (await client.get(f"/api/nodes/{node_id}/health")).json()
    assert healthy["healthy"] is True, healthy

    node = await nodes.get_node(session, node_id)
    await session.refresh(node)

    assert node.last_probe_finding is None
    assert node.last_probe_at is not None, (
        "a probe that found nothing wrong left no record of having been taken, so "
        "'never probed' and 'asked and it was fine' are the same reading"
    )
    assert console.probe_note(node) is None


async def test_an_apply_that_re_measured_and_found_otherwise_clears_it(
    client, session, reality_params, host
) -> None:
    """The second thing that unsays a finding, and it took three walks to state.

    WALK 1 SAID an apply clears the finding because it verifies more than a probe does.
    WALK 2 PROVED that false — an apply asks no host what is holding a port, and until
    that walk it concluded from one sample of a container in its first second — and
    settled on "an apply replaces the processes the finding was about, so the finding is
    obsolete". WALK 3 PROVED THAT FALSE TOO: replacing a process that then serves nothing
    does not unsay a finding about serving nothing, and the walk watched exactly that
    apply report success.

    So the rule this asserts is the third one: an apply clears a finding only when it
    took the SAME READING and got a different answer. Here the operator fixed the host —
    its port is held again — and the apply that follows watches the containers stay up
    AND finds the port held, which is a contradiction of the finding rather than a
    replacement of its subject.

    The timestamp still goes with it, because an apply is still not a probe: the row
    reads "never probed", which is what it is.
    """
    node_id = await an_applied_node(client, reality_params)
    stops_serving(host)
    await client.get(f"/api/nodes/{node_id}/health")

    node = await nodes.get_node(session, node_id)
    await session.refresh(node)
    assert node.last_probe_finding, "the probe recorded nothing, so this proves nothing"

    # The operator repairs the host: the daemon comes back and holds its port again.
    host.sockets = bound(reality_params["port"])
    applied = await client.post(f"/api/nodes/{node_id}/apply")
    assert applied.status_code == 200, applied.text

    session.expire_all()
    node = await nodes.get_node(session, node_id)

    assert node.last_probe_finding is None
    assert node.last_probe_at is None, (
        "a freshly applied node reads as probed, over an answer that was thrown away"
    )


async def test_an_apply_that_could_not_confirm_the_daemon_clears_nothing(
    client, session, reality_params, host, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The half of the rule above that walk 2 had to be run twice to find.

    A finding may be replaced by a measurement and by nothing else. An apply that pushed
    and could NOT then watch the daemon stay up has measured a failure, not a success —
    so it leaves what the probe found exactly where it was, and puts its own reason on
    the row beside it. Without this, "an apply clears the finding" is a licence for any
    apply at all to erase a true reading, which is the defect the walk filed.
    """
    node_id = await an_applied_node(client, reality_params)
    stops_serving(host)
    await client.get(f"/api/nodes/{node_id}/health")

    node = await nodes.get_node(session, node_id)
    await session.refresh(node)
    found = node.last_probe_finding
    assert found, "the probe recorded nothing, so this test proves nothing"

    # The host stops answering with any container at all: the push lands and the daemon
    # does not come back on it, which is the failure the settle check reports.
    host.services = []
    monkeypatch.setattr(host, "run", _pushes_but_never_comes_up(host))

    applied = await client.post(f"/api/nodes/{node_id}/apply")
    assert applied.status_code != 200, applied.text

    session.expire_all()
    node = await nodes.get_node(session, node_id)

    assert node.last_probe_finding == found, (
        "an apply that could not confirm the daemon deleted a true probe finding"
    )
    assert node.state_detail, "the failed apply left no reason of its own on the row"


def _pushes_but_never_comes_up(host):
    """The fake's own shell, with ``docker inspect`` answering for no container."""
    real = host.run

    async def run(command: str, *, check: bool = True):
        from edge.bootstrap.ssh import CommandResult

        if "docker inspect" in command:
            return CommandResult(exit_status=0, stdout="", stderr="")
        return await real(command, check=check)

    return run


async def test_no_finding_records_anything_about_a_person(
    client, session, reality_params, host
) -> None:
    """The charter's one forbidden record, asserted on the column that now outlives a
    click — the probe's own answers are already held to this, and this is the first of
    them that is written down."""
    node_id = await an_applied_node(client, reality_params)
    stops_serving(host)
    await client.get(f"/api/nodes/{node_id}/health")

    node = await nodes.get_node(session, node_id)
    await session.refresh(node)
    finding = node.last_probe_finding or ""

    assert NODE_ADDRESS not in finding, "a stored finding names an address"
    for word in ("user", "peer", "handshake", "bytes", "connected"):
        assert word not in finding.lower(), f"a stored finding says {word!r}"
