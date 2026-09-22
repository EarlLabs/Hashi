"""An apply that returns 200 must mean the daemon is serving what we pushed — M1.

WHAT: ``POST /api/nodes/{id}/apply`` against a node whose containers behave the way
      Compose really behaves, and ``GET /api/nodes/{id}/health`` against the state the
      field measurement found.
WHY:  docs/tracker/M1/field-measurement.md. On a real node, a config was written 8m25s
      AFTER the container meant to serve it started; the apply returned 200, the node
      was ``active``, and the health probe said ``reachable: true, healthy: true,
      drifted: []``. Every one of those was a true answer to a question that does not
      establish what an operator reads it as establishing. The consequence is charter
      criterion 6 failing silently: a revoked user keeps connecting, because the file
      lost their credential and the running daemon never re-read the file.
HOW:  the node is faked at the SHELL, not at ``node_stack``. ``_FakeHost`` answers
      commands and holds files, so the real ``node_stack`` builds the real compose
      file, the real verification command runs, and the real parsing reads the answer
      — the only thing invented here is Docker, and only the one rule of it that
      matters: **Compose compares the desired service definition against the running
      container and leaves the container alone when they match.** That rule is the
      bug's whole mechanism, so a fake that did not obey it would prove nothing.

      Stated plainly: this does not prove that real Docker recreates a container when a
      label changes. That is documented Compose behaviour and a field observation, and
      M1's step notes say what to look at on the node. What it proves is that we now
      ASK, and that a node which did not come back on this config cannot be reported as
      applied.

      Every test here is red against baseline 2413883 — see the module note in
      ``_FakeHost.run`` for the one accommodation that makes them red by assertion
      rather than by AttributeError.
"""

import itertools

import yaml

from control.app.models import NodeState
from edge.bootstrap import node_stack
from edge.health import listening

from .conftest import GENERATED_SSH_KEY

# RFC 5737 documentation address, as everywhere in this zone. Never dialled: the
# connection is replaced.
NODE_ADDRESS = "192.0.2.10"

# A real key, from the conftest — see the constant there for why a placeholder string no
# longer reaches the apply path. It authenticates nothing: the connection is replaced.
FAKE_PRIVATE_KEY = GENERATED_SSH_KEY

TRANSPORT = "vless-reality"

# The label the compose file carries a service's config digest in. Spelled out here
# rather than imported, deliberately: ``_FakeHost`` stands in for a NODE, and a node
# reads what is written in the file rather than agreeing with our library by
# construction. That the two spellings agree is its own assertion below.
DIGEST_LABEL = "io.hashi.config-digest"


class _FakeHost:
    """One node: a shell, a filesystem, and a container per compose service.

    ``recreates`` is the knob the milestone turns. With it on, the host obeys Compose:
    a service whose definition changed gets a new container, and one whose definition
    is unchanged is left running whatever it started with. With it off, the host never
    recreates anything — which is the state every hashi node was in before M1, and the
    state ``apply`` must refuse to call success. It is deliberately not "the node is
    broken": a container can also fail to come back on the new config because Compose
    is old, because the daemon crashed and was restarted from its old definition, or
    because somebody ran `docker start` by hand. The verification has to catch the
    outcome, not the cause.
    """

    learned_host_key = None

    def __init__(self, *, recreates: bool = True, sockets: str | None = None) -> None:
        # The node's listening table, as ``ss`` prints it, or ``None`` for a host that
        # does not have the tool. ``None`` is the DEFAULT on purpose: this file is M1's
        # and its subject is what the daemon loaded, not what it bound. A host that
        # cannot be asked reports its ports as unchecked, which is the honest answer and
        # leaves every assertion here about the question it was written for. M22's own
        # control-level scenarios are in
        # ``tests/control/test_a_probe_says_what_it_checked.py``.
        self.sockets = sockets
        self.files: dict[str, str] = {}
        # service name -> the definition it was created from, and the digest label on it
        self.containers: dict[str, dict] = {}
        # How many times each service's container has been created. The evidence for
        # "the daemon restarted onto the new config" — a start timestamp, without a
        # clock.
        self.creations: dict[str, int] = {}
        self.recreates = recreates
        self._generation = itertools.count(1)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info) -> bool:
        return False

    async def run(self, command: str, *, check: bool = True):
        from edge.bootstrap.ssh import CommandResult

        if "docker compose up -d" in command:
            self._compose_up()
            return CommandResult(exit_status=0, stdout="", stderr="")

        if "docker inspect" in command:
            # Five fields since M26's second acceptance walk — service, digest, running,
            # RESTARTING, and a token for which LIFE of the container this reading looked
            # at. Nothing this fake runs crash-loops: a container it created either
            # exists, is up and stays up, or was never created, which is the only rule of
            # Docker this file models. The token is therefore constant per service — a
            # fake that invented a new one on every read would model a permanent crash
            # loop, and the apply's settle check would refuse every node here.
            lines = [
                f"{service}|{container['digest']}|true|false|one-life"
                for service, container in self.containers.items()
            ]
            return CommandResult(exit_status=0, stdout="\n".join(lines) + "\n", stderr="")

        if command == listening.LISTENING_SOCKETS:
            if self.sockets is None:
                # What a shell answers for a command that is not on the host.
                return CommandResult(exit_status=127, stdout="", stderr="ss: not found")
            return CommandResult(exit_status=0, stdout=self.sockets, stderr="")

        if "docker compose ps --services" in command:
            # The PRE-M1 question — "which services are up" — still answerable, and
            # this is the only reason it is here. It is what makes every assertion in
            # this file fail on the BASELINE commit for the reason it is written about,
            # instead of erroring on a function that does not exist yet. A fake that
            # went silent on the old question would have made a stale node look absent,
            # which is a red for the wrong reason and would not have proven the bug.
            return CommandResult(
                exit_status=0, stdout="\n".join(self.containers), stderr=""
            )

        if "docker version" in command:
            return CommandResult(exit_status=0, stdout="27.1.1\n", stderr="")

        return CommandResult(exit_status=0, stdout="", stderr="")

    def _compose_up(self) -> None:
        """`docker compose up -d`, with the one rule that matters modelled honestly."""
        services = yaml.safe_load(self.files[node_stack.COMPOSE_PATH])["services"]
        for service, definition in services.items():
            running = self.containers.get(service)
            if running is not None and (running["definition"] == definition or not self.recreates):
                # Unchanged definition: Compose does nothing, and the process keeps
                # whatever config it parsed at start. This line is the bug.
                continue
            self.containers[service] = {
                "definition": definition,
                "digest": definition.get("labels", {}).get(DIGEST_LABEL, ""),
                "generation": next(self._generation),
            }
            self.creations[service] = self.creations.get(service, 0) + 1

    async def write_file(self, path: str, content: str, *, mode: int = 0o600) -> None:
        self.files[path] = content

    async def read_file(self, path: str) -> str | None:
        return self.files.get(path)


def host_for(monkeypatch, host: _FakeHost) -> _FakeHost:
    """Point every node connection this control plane opens at one fake host.

    Both modules, because they import the class rather than the package: an apply and a
    probe have to reach the SAME host here, or the probe would be answering about a
    node the apply never touched — which is the one thing this file is about.
    """
    from control.app.services import apply, health

    for module in (apply, health):
        monkeypatch.setattr(module, "NodeConnection", lambda target: host)
    return host


async def a_node_with_a_transport(client, session, reality_params) -> str:
    """One reachable node with one transport enabled, active and ready to be applied."""
    from control.app.services import nodes

    response = await client.post(
        "/api/nodes",
        json={
            "name": "leaf-nl",
            "address": NODE_ADDRESS,
            "location_label": "Netherlands",
            "ssh_host": NODE_ADDRESS,
            "ssh_port": 22,
            "ssh_private_key": FAKE_PRIVATE_KEY,
        },
    )
    node_id = response.json()["id"]
    await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": TRANSPORT, "params": reality_params},
    )
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    return node_id


def test_the_label_the_node_carries_is_the_one_the_library_reads() -> None:
    """The fake above spells the label out; the library must agree with it.

    Both halves of M1 are this one string — Compose recreates on it, and
    ``docker inspect`` reads it back — so a rename that reached only one side would
    leave apply silently unable to verify anything, with every test still green.
    """
    assert node_stack.CONFIG_DIGEST_LABEL == DIGEST_LABEL


async def test_adding_a_user_and_applying_recreates_the_container(
    client, session, reality_params, monkeypatch
) -> None:
    """M1's first "done when", as far as a test can carry it.

    The node is applied, then a user is added — which changes the rendered config and
    nothing else — and the node is applied again. The container must be a NEW one: on a
    real host that is a start timestamp later than the config's mtime, and the field
    measurement is the same two numbers 8m25s apart in the wrong order.

    Before M1 the second apply rendered a byte-identical compose file, Compose saw an
    unchanged definition, and the user could not connect.
    """
    host = host_for(monkeypatch, _FakeHost())
    node_id = await a_node_with_a_transport(client, session, reality_params)

    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 200
    assert host.creations[TRANSPORT] == 1

    await client.post("/api/users", json={"nickname": "kolya"})

    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 200
    assert host.creations[TRANSPORT] == 2, (
        "the second apply left the original container running, so the user who was "
        "just added is in the file on the node and not in the daemon serving it"
    )


async def test_the_running_container_carries_the_digest_that_was_applied(
    client, session, reality_params, monkeypatch
) -> None:
    """The label and the recorded ``applied_digest`` are the same value.

    If they could differ, the read-back would certify something that was never pushed
    and drift detection would compare two unrelated numbers.
    """
    from sqlalchemy import select

    from control.app.models import NodeTransport
    from control.app.services import apply

    host = host_for(monkeypatch, _FakeHost())
    node_id = await a_node_with_a_transport(client, session, reality_params)

    configs = await apply.apply_node(session, node_id=node_id)

    row = (
        await session.execute(
            select(NodeTransport).where(NodeTransport.node_id == node_id)
        )
    ).scalars().unique().one()

    assert host.containers[TRANSPORT]["digest"] == node_stack.digest_of(configs[TRANSPORT])
    assert row.applied_digest == host.containers[TRANSPORT]["digest"]


async def test_a_daemon_that_did_not_come_back_on_this_config_fails_loudly(
    client, session, reality_params, monkeypatch
) -> None:
    """M1's second "done when": apply must not report success over a stale daemon.

    The host here never recreates a container. The config reaches its disk and the
    process goes on serving the previous one — the exact state measured in the field,
    where the API answered 200 and the node was left ``active``.
    """
    from control.app.services import nodes

    host_for(monkeypatch, _FakeHost(recreates=False))
    node_id = await a_node_with_a_transport(client, session, reality_params)

    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 200

    await client.post("/api/users", json={"nickname": "kolya"})
    response = await client.post(f"/api/nodes/{node_id}/apply")

    assert response.status_code == 502, (
        f"a node still running the previous configuration was reported as applied: "
        f"{response.text}"
    )
    message = response.json()["error"]["message"]
    assert "still running an older configuration" in message
    assert TRANSPORT in message

    node = await nodes.get_node(session, node_id)
    assert node.state == NodeState.DEGRADED
    assert "still running an older configuration" in node.state_detail
    # Core invariants §4 and §3 together: no address, and nothing that names a person.
    assert NODE_ADDRESS not in message


async def test_a_stale_apply_records_no_applied_digest(
    client, session, reality_params, monkeypatch
) -> None:
    """The database must not record a state the node is not in.

    ``applied_digest`` is what drift is measured against. Writing it for a config the
    daemon never loaded is how the control plane came to answer ``drifted: []`` about a
    node serving something else — the lie compounding itself.
    """
    from sqlalchemy import select

    from control.app.models import NodeTransport

    host_for(monkeypatch, _FakeHost(recreates=False))
    node_id = await a_node_with_a_transport(client, session, reality_params)

    await client.post(f"/api/nodes/{node_id}/apply")
    first = (
        await session.execute(
            select(NodeTransport).where(NodeTransport.node_id == node_id)
        )
    ).scalars().unique().one().applied_digest

    await client.post("/api/users", json={"nickname": "kolya"})
    await client.post(f"/api/nodes/{node_id}/apply")

    session.expire_all()
    after = (
        await session.execute(
            select(NodeTransport).where(NodeTransport.node_id == node_id)
        )
    ).scalars().unique().one().applied_digest

    assert after == first, (
        "the failed apply recorded a digest the running daemon never loaded"
    )


async def test_health_calls_a_stale_node_stale_rather_than_healthy(
    client, session, reality_params, monkeypatch
) -> None:
    """The field measurement's second half, through the endpoint that produced it.

    ``reachable: true, healthy: true, drifted: []`` about a node whose daemon had never
    read its config. Drift detection compares the file on disk with the digest we
    pushed and those genuinely matched; nothing compared either against what the
    PROCESS loaded. ``drifted`` must stay empty here — nobody edited that file — and
    the answer has to arrive in a field of its own.
    """
    host_for(monkeypatch, _FakeHost(recreates=False))
    node_id = await a_node_with_a_transport(client, session, reality_params)

    await client.post(f"/api/nodes/{node_id}/apply")
    await client.post("/api/users", json={"nickname": "kolya"})
    await client.post(f"/api/nodes/{node_id}/apply")

    health = (await client.get(f"/api/nodes/{node_id}/health")).json()

    assert health["reachable"] is True
    assert health["healthy"] is False, (
        "a node whose daemon is serving a configuration we did not push reported "
        "healthy — this is the answer the operator reads before believing a "
        "revocation took effect"
    )
    assert health["drifted"] == [], (
        "staleness was reported as drift, which sends the operator looking for "
        "somebody who edited the node"
    )
    assert health["stale"] == [TRANSPORT]
    assert health["running"] == [TRANSPORT]


async def test_a_node_serving_what_we_pushed_is_healthy(
    client, session, reality_params, monkeypatch
) -> None:
    """The green case, so the check above cannot pass by calling every node stale."""
    host_for(monkeypatch, _FakeHost())
    node_id = await a_node_with_a_transport(client, session, reality_params)

    await client.post(f"/api/nodes/{node_id}/apply")
    await client.post("/api/users", json={"nickname": "kolya"})
    await client.post(f"/api/nodes/{node_id}/apply")

    health = (await client.get(f"/api/nodes/{node_id}/health")).json()

    assert health["healthy"] is True, health
    assert health["stale"] == []
    assert health["drifted"] == []


async def test_a_revoked_user_leaves_the_running_daemon_too(
    client, session, reality_params, monkeypatch
) -> None:
    """Criterion 6, at the node rather than in the file — M1's third "done when".

    The code half of it: revoking must recreate the container, so the process
    authorising connections is one that never saw the withdrawn credential. Whether
    that user's client actually stops connecting is a field observation on real
    hardware, and this asserts only what makes it possible.
    """
    host = host_for(monkeypatch, _FakeHost())
    node_id = await a_node_with_a_transport(client, session, reality_params)

    user_id = (await client.post("/api/users", json={"nickname": "kolya"})).json()["id"]
    await client.post(f"/api/nodes/{node_id}/apply")
    with_user = host.containers[TRANSPORT]["generation"]

    response = await client.post(f"/api/users/{user_id}/revoke")

    assert response.status_code == 200, response.text
    assert response.json()["complete"] is True
    assert host.containers[TRANSPORT]["generation"] != with_user, (
        "the revocation rewrote the file and left the same process running, so the "
        "revoked user is still being authorised by the daemon"
    )


async def test_a_revocation_over_a_stale_daemon_says_the_push_landed(
    client, session, reality_params, monkeypatch
) -> None:
    """M23, measured on the owner's leaf: the node WAS reached, and was told it was not.

    The host here takes the file and never recreates the container — the same state the
    test above asserts an apply refuses to call success. On the walk that state arrived
    through a revocation instead, and the banner said *"could not be reached — apply it
    again once it can be"* about a node whose peer count had just gone 2 → 1 on disk.
    Every word of that is wrong in the direction that matters: the operator is sent to
    wait for a host that is answering, while the process on it goes on authorising the
    person they just withdrew.

    So the kind is asserted as well as the sentence. The kind is what the banner is
    composed from — a node's own message may quote its private key and can never be
    printed — so a right sentence over a wrong kind would be a coincidence of this
    fleet rather than a property.

    Red against the previous commit: ``why_not_updated`` had no arm for this, so the
    failure fell through to ``UNREACHED`` and both assertions below fail.
    """
    from control.app.services import revocation
    from control.app.services.apply import NotUpdated

    host_for(monkeypatch, _FakeHost(recreates=False))
    node_id = await a_node_with_a_transport(client, session, reality_params)

    # The user first, so the container the host starts is one that authorises them —
    # from that point the host is frozen on it and the withdrawal cannot reach the
    # process, which is the state this test is about.
    user_id = (await client.post("/api/users", json={"nickname": "kolya"})).json()["id"]
    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 200

    outcome = await revocation.revoke_user(session, user_id=user_id)

    assert outcome.why_failed == {node_id: NotUpdated.NOT_SERVING}, outcome.why_failed
    summary = outcome.summary()
    assert "was reached and its configuration WAS replaced on it" in summary, summary
    assert "could not be reached" not in summary, summary


async def test_a_push_that_landed_says_what_is_still_on_the_host(
    client, session, reality_params, monkeypatch
) -> None:
    """The banner names the key material the failure left behind — M23, round 4.

    Round 6 made ``_record_failure`` delete what the apply minted on its way into
    service, because an apply that fails must grant nobody, and it named the cost out
    loud: on the one failure where the bytes actually landed, the host is left
    authorising peers this database no longer holds. The walk measured exactly that —
    two ``[Peer]`` blocks on the node against zero credential rows here — and checked
    the bounds, which hold: a successful retry overwrites the file, each further failure
    replaces one orphan generation with the next, and an apply that mints nothing leaves
    nothing.

    What was missing is not a mechanism, it is a sentence. The operator was told the
    daemon did not come up and nothing at all about what is on that host meanwhile — and
    the exposure is the window in which the daemon later starts on its own and serves
    peers the panel can neither list nor withdraw.

    The node is parked and the user added while it is parked, because that is the only
    way an apply has anybody left to grant: a user added to a serving node already holds
    their credential, and the fan-out into service skips them.
    """
    from sqlalchemy import func, select

    from control.app.models import Credential
    from control.app.services import apply, nodes

    host_for(monkeypatch, _FakeHost(recreates=False))
    node_id = await a_node_with_a_transport(client, session, reality_params)
    # One successful apply first, so the container exists and is frozen on that
    # definition. Everything after this reaches the host's disk and not its process.
    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 200
    parked = await client.post(
        f"/api/nodes/{node_id}/state",
        json={"state": "draft", "detail": "parked, rebuilding the host"},
    )
    assert parked.status_code == 200, parked.text
    await client.post("/api/users", json={"nickname": "kolya"})

    response = await client.post(f"/api/nodes/{node_id}/apply")

    assert response.status_code == 502, response.text
    message = response.json()["error"]["message"]
    assert "still running an older configuration" in message, message
    assert apply.ORPHANED_ON_THE_HOST in message, message
    # The premise of that sentence, in the database: the grant is gone, and the file the
    # host took carries it.
    session.expire_all()
    held = await session.execute(select(func.count()).select_from(Credential))
    assert held.scalar_one() == 0, "the failed apply left the grant it minted behind"
    # And it is on the BANNER and not on the row. ``state_detail`` is 500 characters that
    # already carry however many transports did not come up, and a warning cut off
    # mid-clause by that ceiling is worse than one read once where the operator is
    # looking.
    node = await nodes.get_node(session, node_id)
    assert apply.ORPHANED_ON_THE_HOST not in node.state_detail, node.state_detail


async def test_a_re_apply_that_minted_nothing_says_nothing_about_orphans(
    client, session, reality_params, monkeypatch
) -> None:
    """The half that keeps the sentence above worth reading.

    A node that was already serving grants nobody on a re-apply, so a failure deletes
    nothing and leaves no orphan. Saying it anyway would be a warning about a state that
    is not there, which is how a real warning stops being read.
    """
    from control.app.services import apply

    host_for(monkeypatch, _FakeHost(recreates=False))
    node_id = await a_node_with_a_transport(client, session, reality_params)
    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 200
    # Added while the node is serving, so they already hold their credential and the
    # apply below has nobody to grant.
    await client.post("/api/users", json={"nickname": "kolya"})

    response = await client.post(f"/api/nodes/{node_id}/apply")

    assert response.status_code == 502, response.text
    message = response.json()["error"]["message"]
    assert "still running an older configuration" in message, message
    assert apply.ORPHANED_ON_THE_HOST not in message, message
