"""The serving check, against the real daemon — M26's fourth acceptance walk.

WHAT: brings a wg-family data plane up from its real rendered config on a real engine,
      puts the transport's OWN serving question to it through the product's own code,
      and then rebuilds — on that same running container — the two hosts the walk used
      to defeat every earlier check this project had:

      * **a foreign process on the port.** The interface is taken down and ``nc -u -l``
        holds the number instead. ``ss`` inside the container still shows the port bound,
        so the reading M22 built still answers YES — and the transport's own question
        answers NO.
      * **the right daemon with no peers.** The interface is up, the daemon holds the
        port, and its peers are removed — which is what a wrong peer key or a wrong
        endpoint leaves behind, and is an ordinary operator typo rather than an attack.
        Port still bound, and the transport's own question answers NO.
WHY:  because the offline file beside this one (``tests/edge/test_a_transport_says_what_
      serving_means_for_it.py``) asserts against text this repository wrote down. Walk 4
      is the third walk in a row to find that the thing this project believed about a
      node was not what the node was doing, so the belief is worth checking against the
      node: that ``awg show <if> peers`` prints one key per line, that it exits non-zero
      for an interface that is not there, that it exits ZERO and prints NOTHING for a
      daemon with no peers — the case the walk found by removing one — and that our own
      command reaches a container at all.
HOW:  ``edge.health.serving.ask``, unmodified, over ``LocalNode``: the shell line the
      product would run on a node, against a real compose project. The config is the
      golden file, which is the real renderer's real output.

Boundary — what this cannot prove, and it is the same boundary every scenario in this
directory has. The containers get their own network namespace rather than the node's, so
nothing here says the port is free on a real host or that anything reaches it from
outside. Nothing here says a handshake completed or that one byte moved: the check under
test deliberately refuses to ask that (``edge.health.listening`` has the charter argument
in full). What it establishes is that the daemon holds the authorisation list this
control plane gave it — which is strictly more than "something holds the port", and is
exactly what both of the walk's hosts could not fake.
"""

import time

import pytest

from edge.bootstrap import node_stack
from edge.health import serving
from edge.registry import discover

# Every installed transport that declares a serving question — which is the WireGuard
# family today and is not written down as such: a package added later is asked by
# arriving, and one that declares nothing is not asked at all.
ASKABLE = sorted(
    name for name, meta in discover().items() if meta.serving_question is not None
)

# How long the daemon is given to configure its interface. ``awg-quick up`` is
# synchronous and finishes in well under a second; this is the ceiling, not the
# expectation.
UP_WITHIN = 15


def interface_of(transport_name: str) -> str:
    """The interface this transport's config produces on the node.

    The config's own stem, which for this family is the name the config is placed
    under — the same fact ``DataPlane.interface_from_config_filename`` declares and the
    same substitution the serving question uses.
    """
    return transport_name


def exec_in(stack, transport_name: str, argv: list[str]):
    """Run something in the container by hand, to BREAK it in the ways the walk did.

    Deliberately not the product's own path: what is under test is the question, and a
    test that sabotaged a node through the code it is asking would be asking itself.
    """
    from .conftest import run

    return run(["docker", "exec", stack.container_id(transport_name), *argv], timeout=120)


@pytest.fixture(params=ASKABLE, scope="module")
def daemon(request, data_plane_stack, golden_server_config):
    """One wg-family data plane, up on its real config, one per family member."""
    transport_name = request.param
    config = golden_server_config(transport_name)
    stack = data_plane_stack()
    stack.place({transport_name: config})
    stack.up()

    deadline = time.monotonic() + UP_WITHIN
    while time.monotonic() < deadline:
        if exec_in(stack, transport_name, ["ip", "link", "show", interface_of(transport_name)]).returncode == 0:
            break
        time.sleep(0.5)
    else:  # pragma: no cover - a data plane that never came up fails the first test
        pytest.fail(
            f"{transport_name} never created its interface, so nothing here is about "
            f"the serving check:\n{stack.logs(transport_name)[-2000:]}"
        )
    return stack, transport_name, config


def checks_for(transport_name: str, config: str) -> dict[str, serving.ServingCheck]:
    """What `control` builds and hands to the health code, built the same way here."""
    return {
        transport_name: serving.ServingCheck(
            question=discover()[transport_name].serving_question,
            config=config,
            path=node_stack.config_path_of(transport_name, transport_name),
        )
    }


async def ask(stack, transport_name: str, config: str) -> bool | None:
    """The product's own command, run on a real compose project."""
    answered = await serving.ask(
        stack.node(),
        checks=checks_for(transport_name, config),
        about=[transport_name],
    )
    return answered[transport_name]


def port_is_held(stack, transport_name: str, config: str) -> bool:
    """Whether M22's reading — is the number bound — would answer yes right now.

    Read with ``ss`` inside the container because that is where the namespace is here;
    on a node the same table is the host's. It is the WEAKER check, and every assertion
    below pairs it with the stronger one so that the difference between them is what
    this file measures rather than something a reader has to take on trust.
    """
    port = next(
        line.split("=", 1)[1].strip()
        for line in config.splitlines()
        if line.startswith("ListenPort")
    )
    listing = exec_in(stack, transport_name, ["ss", "-l", "-n", "-t", "-u"])
    return any(f":{port} " in line or line.rstrip().endswith(f":{port}") for line in listing.stdout.splitlines())


async def test_the_real_daemon_answers_its_own_question(daemon) -> None:
    """The accept direction, and it runs first: everything below is a change from here.

    Without it every refusal in this file could be a command that never reaches a
    container — which is the failure mode a check like this dies of, silently, because
    "could not ask" is not a red row anywhere.
    """
    stack, transport_name, config = daemon

    assert await ask(stack, transport_name, config) is True, (
        f"the real {transport_name} daemon, up on the config this project renders, does "
        f"not answer its own serving question:\n{stack.logs(transport_name)[-2000:]}"
    )
    assert port_is_held(stack, transport_name, config)


async def test_a_foreign_process_on_the_port_is_not_serving(daemon) -> None:
    """Walk 4's contrived binder, rebuilt on a real container.

    The walk replaced ``awg-quick`` with ``nc -u -l -p 51833`` and the panel reported a
    node serving. Here the interface is taken down and the same netcat holds the same
    number: the port reading still says yes, and the transport's own question says no.
    """
    stack, transport_name, config = daemon
    port = next(
        line.split("=", 1)[1].strip()
        for line in config.splitlines()
        if line.startswith("ListenPort")
    )
    tool = "awg-quick" if transport_name == "amneziawg" else "wg-quick"
    exec_in(stack, transport_name, [tool, "down", node_stack.config_path_of(transport_name, transport_name)])
    exec_in(
        stack,
        transport_name,
        ["sh", "-c", f"setsid nc -u -l -p {port} >/dev/null 2>&1 < /dev/null &"],
    )
    time.sleep(1)

    assert port_is_held(stack, transport_name, config), (
        "nothing holds the port, so this scenario is not the one the walk built and "
        "proves nothing about telling a binder from a daemon"
    )
    assert await ask(stack, transport_name, config) is False


async def test_the_daemon_with_its_peers_removed_is_not_serving(daemon) -> None:
    """The walk's second host, and the one that matters: an ordinary wrong peer key.

    Nothing is contrived here — the real tool brought the interface up and the peers are
    gone, which is what the panel would be looking at if the operator had mistyped a key
    or an endpoint. The port is held throughout. On the walk this node read ``active / in
    sync`` and probed green over a hop at 100% packet loss.
    """
    stack, transport_name, config = daemon
    tool = "awg" if transport_name == "amneziawg" else "wg"
    interface = interface_of(transport_name)
    # Back up, whatever the scenario above left behind: these share a module-scoped
    # container on purpose, because bringing one up is the expensive part.
    exec_in(stack, transport_name, ["sh", "-c", f"pkill nc || true"])
    exec_in(
        stack,
        transport_name,
        [f"{tool}-quick", "up", node_stack.config_path_of(transport_name, transport_name)],
    )
    listed = exec_in(stack, transport_name, [tool, "show", interface, "peers"])
    assert listed.returncode == 0 and listed.stdout.split(), (
        "the daemon came back with no peers before this test removed any, so its "
        "refusal below would prove nothing"
    )

    for peer in listed.stdout.split():
        exec_in(stack, transport_name, [tool, "set", interface, "peer", peer, "remove"])

    assert port_is_held(stack, transport_name, config), (
        "the daemon stopped holding its port when its peers were removed, so the walk's "
        "host is not what this is measuring"
    )
    assert await ask(stack, transport_name, config) is False


async def test_an_interface_that_is_not_there_answers_and_does_not_hang(daemon) -> None:
    """And the shape of the answer itself, which the offline file takes on trust.

    ``wg show <if> peers`` for an interface that does not exist must exit non-zero rather
    than exiting 0 with nothing — those two are opposite answers to this check, and the
    offline judge is written against the first.
    """
    stack, transport_name, _config = daemon
    tool = "awg" if transport_name == "amneziawg" else "wg"

    missing = exec_in(stack, transport_name, [tool, "show", "nosuchiface", "peers"])

    assert missing.returncode != 0, (
        "the tool reports a missing interface as success, so an interface that was never "
        "created would read exactly like one with no peers"
    )
    assert missing.stdout.strip() == ""
