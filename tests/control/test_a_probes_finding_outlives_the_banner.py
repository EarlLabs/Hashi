"""A probe's finding survives the next click — M26, the first acceptance walk.

WHAT: that what a probe found is kept on the node's row, is still there after a plain
      reload of the Nodes screen, is said on the Overview beside the counters it
      contradicts, and is cleared by the two things that genuinely unsay it — a later
      probe that finds nothing, and a successful apply.
WHY:  the walk stopped ``hashi-node-amneziawg-1`` on its leaf and pressed probe. The
      probe was RIGHT — *"failed  leaf-acc answered but is not serving — not running:
      amneziawg."* — and one reload later the row read ``active`` beside ``in sync``,
      ``state_detail`` was empty, and the Overview read *"nodes active 2 … transports
      serving 2"* while that friend's ``ping 1.1.1.1`` was 100% loss. The node stayed in
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
def host(monkeypatch: pytest.MonkeyPatch):
    """One fake host, reached by both the apply that places configs and the probe.

    Returned so a test can change what it answers mid-run, which is the whole scenario:
    the same host serving, then not.
    """
    fake = _FakeHost()
    for module in (apply, health):
        monkeypatch.setattr(module, "NodeConnection", lambda target: fake)
    return fake


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
    client, session, reality_params, host
) -> None:
    """The accept direction, and the reason it is first.

    Without it every assertion below could pass on a panel that warns about every node
    it has, which is the same uselessness as warning about none.
    """
    await an_applied_node(client, reality_params)

    rows = await console.node_rows(session)

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


async def test_a_successful_apply_clears_it(
    client, session, reality_params, host
) -> None:
    """The second thing that genuinely unsays a finding, and the stronger of the two.

    An apply verifies the daemon came back on the configuration it just pushed, which is
    more than the probe establishes — so keeping a finding about the configuration before
    it would leave a stale fault on the row of a node that has just been proven.
    """
    node_id = await an_applied_node(client, reality_params)
    await client.get(f"/api/nodes/{node_id}/health")

    applied = await client.post(f"/api/nodes/{node_id}/apply")
    assert applied.status_code == 200, applied.text

    node = await nodes.get_node(session, node_id)
    await session.refresh(node)

    assert node.last_probe_finding is None
    assert node.last_probe_at is None, (
        "a freshly applied node reads as probed, over an answer that was thrown away"
    )


async def test_no_finding_records_anything_about_a_person(
    client, session, reality_params, host
) -> None:
    """The charter's one forbidden record, asserted on the column that now outlives a
    click — the probe's own answers are already held to this, and this is the first of
    them that is written down."""
    node_id = await an_applied_node(client, reality_params)
    await client.get(f"/api/nodes/{node_id}/health")

    node = await nodes.get_node(session, node_id)
    await session.refresh(node)
    finding = node.last_probe_finding or ""

    assert NODE_ADDRESS not in finding, "a stored finding names an address"
    for word in ("user", "friend", "peer", "handshake", "bytes", "connected"):
        assert word not in finding.lower(), f"a stored finding says {word!r}"
