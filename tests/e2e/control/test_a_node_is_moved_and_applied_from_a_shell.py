"""The node commands a rebuild runs, inside the real control image — M36.

WHAT: ``python -m control.cli node-plan``, ``relocate-node`` and ``apply-node`` executed in
      the booted e2e stack's control container — the exact place ``make node-plan`` and
      its neighbours run them — against a node registered through the real API.
WHY:  ``scripts/restore-node.sh`` drives a rebuilt node entirely through these three
      commands, over SSH, with no operator session. The unit suite proves the service;
      only the image proves the commands boot there: that ``Settings`` reads the
      container's environment, that the secret box opens the stored key, and that a
      refusal comes out as a sentence and an exit code rather than a traceback a script
      cannot read.
HOW:  ``docker exec`` into the e2e project's control container (``exec_in``), never the
      dev stack's. The node's address is a documentation address nothing answers on, so
      the apply is refused — which is the half of ``apply-node`` that must be readable by
      a script.

Boundary: real control + postgres. No node host exists here, so a successful apply is
not claimed; the walk in docs/tracker/M36 is where one was observed.
"""

import uuid

import asyncssh
import pytest

KEY = asyncssh.generate_private_key("ssh-ed25519")
PRIVATE_KEY = KEY.export_private_key("openssh").decode()
PUBLIC_KEY = " ".join(KEY.export_public_key().decode().split()[:2])
HOST_KEY = " ".join(
    asyncssh.generate_private_key("ssh-ed25519").export_public_key().decode().split()[:2]
)


@pytest.fixture
async def operator(client):
    response = await client.post(
        "/panel/login", data={"username": "owner", "password": "e2e-operator-password"}
    )
    assert response.status_code == 303, response.text
    return client


def plan_of(exec_in, name: str) -> dict[str, str]:
    ran = exec_in("control", "python", "-m", "control.cli", "node-plan", name)
    assert ran.returncode == 0, ran.stderr
    return dict(line.split("=", 1) for line in ran.stdout.splitlines() if "=" in line)


async def test_a_node_is_described_moved_and_refused_by_the_commands_a_rebuild_runs(
    operator, exec_in
) -> None:
    name = f"moved-{uuid.uuid4().hex[:8]}"
    created = await operator.post(
        "/api/nodes",
        json={
            "name": name,
            "address": "192.0.2.41",
            "location_label": "Testland",
            "ssh_user": "old-box-account",
            "ssh_private_key": PRIVATE_KEY,
        },
    )
    assert created.status_code == 201, created.text

    before = plan_of(exec_in, name)
    assert before["public_key"] == PUBLIC_KEY, "the plan does not carry the record's public key"
    assert (before["ssh_user"], before["host_key_pinned"]) == ("old-box-account", "no")
    assert "PRIVATE" not in "\n".join(before.values())

    moved = exec_in(
        "control", "python", "-m", "control.cli", "relocate-node", name,
        "--ssh-host", "192.0.2.42", "--ssh-user", "hashi", "--ssh-port", "2222",
        "--host-key", HOST_KEY,
    )
    assert moved.returncode == 0, moved.stderr
    assert "changed=yes" in moved.stdout
    assert f"needs_apply={name}" in moved.stdout

    after = plan_of(exec_in, name)
    assert (after["ssh_host"], after["ssh_user"], after["ssh_port"]) == (
        "192.0.2.42", "hashi", "2222"
    )
    assert after["host_key_pinned"] == "yes"

    trail = await operator.get("/panel/audit")
    assert f"{name} moved to a new host" in trail.text

    # Nothing is enabled on the node, so the apply is refused before anything is dialled —
    # and it is refused the way a script can read: exit 1, one sentence, no traceback.
    applied = exec_in("control", "python", "-m", "control.cli", "apply-node", name)
    assert applied.returncode == 1, (applied.stdout, applied.stderr)
    assert applied.stderr.strip(), "the refusal said nothing"
    assert "Traceback" not in applied.stderr, applied.stderr


async def test_an_unknown_node_is_a_sentence_and_exit_1(exec_in) -> None:
    ran = exec_in("control", "python", "-m", "control.cli", "node-plan", "no-such-node-m36")
    assert ran.returncode == 1
    assert "no node named 'no-such-node-m36'" in ran.stderr
    assert "Traceback" not in ran.stderr
