"""A transport declares what serving means for it, and judges the answer — M26, walk 4.

WHAT: that the wg-family packages read a node's own answer the way the walk needed them
      to — an interface that is not there is not serving, an interface that is there and
      holds none of the peers we authorised is not serving, and an interface holding them
      all is — and that the code which RUNS the question keeps its third answer for the
      cases where nothing could be asked.
WHY:  walk 4 defeated the port check twice in eight minutes.

      * ``awg-quick`` replaced by ``nc -u -l -p 51833``. Apply: SUCCESS, row ``active /
        in sync``. On the host: no amneziawg device, ``ss`` showing ``nc`` on the port,
        the hop at 100% packet loss. Probe: *"checked — its container is up and something
        holds its port."*
      * **And then without contriving anything at all.** The real ``awg-quick up``, and
        then the peer removed — which is exactly what a wrong peer key or a wrong
        endpoint leaves behind. Device present, ``amneziawg-go`` holding 51833,
        ``peers=[]``, 62 KiB out and 728 B back, 100% loss. Apply: SUCCESS. Probe: the
        same green sentence. An ordinary typo produces that node.

      Three rounds had each replaced one proxy with a better proxy, and every one of them
      asked a GENERIC question about a SPECIFIC daemon. This is the question that is not
      generic: only the transport knows that a wg-family interface is serving when it
      exists and holds the peers that were rendered into its config.
HOW:  against the REAL rendered configs — the golden files, which are what this project
      actually pushes to a node — and against the output the real tool actually prints,
      which is one peer public key per line and nothing else (``awg show <if> peers``).
      The e2e scenario beside this one runs the real binary in the real image and feeds
      it the real thing; this file is the same judgement offline, in a second.

      BOTH FAMILIES, parametrised over the packages rather than written twice. They are
      deliberately separate modules — the same rule ``render.py`` keeps — and a test that
      only knew about one of them would let the other rot.

      Boundary: nothing here says a user's packets move. What this establishes is that
      the daemon holds the authorisation list we gave it, which is strictly more than
      "something holds the port" and strictly less than a handshake — and a handshake is
      refused on the charter's own grounds (``edge.health.listening``).
"""

import pathlib

import pytest

from edge.bootstrap.ssh import CommandResult
from edge.health import serving as health_serving
from edge.registry import ContractViolation, ServingAnswer, ServingQuestion, discover
from edge.transports.amneziawg import serving as amneziawg_serving
from edge.transports.wireguard import serving as wireguard_serving

GOLDEN = pathlib.Path(__file__).parent / "golden"

# The two packages under test, each with the config this project really renders for it.
# A tuple of (module, golden file), because the judge is only meaningful against a
# config it could actually be handed.
FAMILY = [
    pytest.param(amneziawg_serving, "amneziawg-server.conf", id="amneziawg"),
    pytest.param(wireguard_serving, "wireguard-server.conf", id="wireguard"),
]


def config_of(golden: str) -> str:
    return (GOLDEN / golden).read_text()


def what_the_tool_prints(keys: list[str]) -> str:
    """``wg show <interface> peers`` — one public key per line, and nothing else.

    Written as a function rather than inline so that what this file believes the tool
    prints is stated once and is the thing the e2e scenario beside it checks against the
    real binary.
    """
    return "".join(f"{key}\n" for key in keys)


# --- what one rendered config authorises ---------------------------------------------


@pytest.mark.parametrize(("package", "golden"), FAMILY)
def test_a_rendered_config_declares_exactly_the_peers_it_authorises(package, golden) -> None:
    """The half of the comparison that comes from our side.

    Read off the file this project pushes, so a template that changed how it writes a
    peer would fail here rather than silently confirm every node in the fleet.
    """
    peers = package.authorised_peers(config_of(golden))

    assert len(peers) == 2, peers
    # The PEER's public key, never the interface's private one and never a pre-shared
    # key — all three are base64 on a line of their own in the same file.
    assert all(f"PublicKey = {key}" in config_of(golden) for key in peers)
    for wrong in ("PrivateKey", "PresharedKey"):
        line = next(
            row for row in config_of(golden).splitlines() if row.startswith(wrong)
        )
        assert line.split("=", 1)[1].strip() not in peers, (
            f"{wrong} was read as a peer, so the comparison would pass on a node "
            "holding nothing"
        )


# --- the two hosts the walk built ----------------------------------------------------


@pytest.mark.parametrize(("package", "golden"), FAMILY)
def test_a_process_that_merely_holds_the_port_is_not_serving(package, golden) -> None:
    """Walk 4's first host: ``nc -u -l`` on the port, and no interface at all.

    The tool runs, finds no such device and exits non-zero. Every earlier check this
    project had said this node was serving.
    """
    answer = ServingAnswer(
        exit_status=1, output=""
    )  # "Unable to access interface: No such device" goes to stderr, which is not read

    assert package.reads(answer, config_of(golden)) is False


@pytest.mark.parametrize(("package", "golden"), FAMILY)
def test_the_real_daemon_with_its_peer_removed_is_not_serving(package, golden) -> None:
    """Walk 4's second host, and the one that matters: an ordinary wrong peer key.

    The interface is up, the daemon holds the port, and it authorises nobody. The tool
    exits 0 and prints nothing, because there is nothing to print.
    """
    answer = ServingAnswer(exit_status=0, output=what_the_tool_prints([]))

    assert package.reads(answer, config_of(golden)) is False


@pytest.mark.parametrize(("package", "golden"), FAMILY)
def test_an_interface_holding_somebody_elses_peer_is_not_serving(package, golden) -> None:
    """The same fault one step along: a peer, and not the one we pushed.

    This is what a config applied to the wrong node, or a daemon left on a previous
    file, leaves behind — and it is indistinguishable from a healthy node to every
    reading of a container or a socket.
    """
    answer = ServingAnswer(
        exit_status=0,
        output=what_the_tool_prints(["c29tZWJvZHkgZWxzZXMga2V5IGJhc2U2NCBwYWRkZWQ9"]),
    )

    assert package.reads(answer, config_of(golden)) is False


@pytest.mark.parametrize(("package", "golden"), FAMILY)
def test_one_missing_peer_out_of_two_is_not_serving(package, golden) -> None:
    """Half an authorisation list is not an authorisation list.

    A node holding one of two users is a node where one person's client handshakes
    into nothing while every screen is green — which is the same fault as the walk's,
    scaled down to the size nobody notices.
    """
    peers = sorted(package.authorised_peers(config_of(golden)))
    answer = ServingAnswer(exit_status=0, output=what_the_tool_prints(peers[:1]))

    assert package.reads(answer, config_of(golden)) is False


# --- and the direction without which every refusal above refuses every node ----------


@pytest.mark.parametrize(("package", "golden"), FAMILY)
def test_an_interface_holding_every_authorised_peer_is_serving(package, golden) -> None:
    """The accept direction. Without it this file would pass on a check that says no to
    the whole fleet, which is the same uselessness as one that says yes to it."""
    peers = sorted(package.authorised_peers(config_of(golden)))
    answer = ServingAnswer(exit_status=0, output=what_the_tool_prints(peers))

    assert package.reads(answer, config_of(golden)) is True


@pytest.mark.parametrize(("package", "golden"), FAMILY)
def test_a_peer_we_did_not_render_is_not_this_questions_business(package, golden) -> None:
    """A node holding MORE than we gave it is drift, which the probe already reads from
    the file itself and reports with its own repair. Reporting it here too would name one
    fault twice, in two vocabularies, and send the operator to the wrong one."""
    peers = sorted(package.authorised_peers(config_of(golden)))
    answer = ServingAnswer(
        exit_status=0,
        output=what_the_tool_prints([*peers, "YW5vdGhlciBrZXkgbm9ib2R5IHJlbmRlcmVkPT0="]),
    )

    assert package.reads(answer, config_of(golden)) is True


@pytest.mark.parametrize(("package", "golden"), FAMILY)
def test_a_config_that_authorises_nobody_is_serving_once_its_interface_is_up(
    package, golden
) -> None:
    """A transport enabled on a node with no users on it yet is not broken.

    The interface existing is all there is to check, and this is the one case where this
    answer is no stronger than that. Refusing it would make an empty pool read as an
    outage on the day a node is first applied.
    """
    config = config_of(golden).split("[Peer]")[0]
    assert package.authorised_peers(config) == frozenset()

    assert package.reads(ServingAnswer(exit_status=0, output=""), config) is True


# --- the code that runs the question, which recognises no protocol -------------------


class _Host:
    """A node that answers one command with one scripted result, and records the line."""

    def __init__(self, result: CommandResult) -> None:
        self.result = result
        self.commands: list[str] = []

    async def run(self, command: str, *, check: bool = True) -> CommandResult:
        self.commands.append(command)
        return self.result


def a_check(config: str = "") -> health_serving.ServingCheck:
    return health_serving.ServingCheck(
        question=discover()["amneziawg"].serving_question, config=config, path="/opt/x.conf"
    )


def test_the_question_is_put_to_the_containers_own_service() -> None:
    """The command runs INSIDE the container the config already runs in.

    A node prepared by ``scripts/node-bootstrap.sh`` has docker and nothing else, so a
    question asked of the HOST would answer "could not ask" on every node in the fleet —
    which is the answer that clears nothing and tells nobody anything.
    """
    line = health_serving.command_for("amneziawg", a_check())

    assert "docker compose exec -T amneziawg" in line
    assert line.endswith("awg show amneziawg peers")


async def test_a_host_that_cannot_run_the_question_is_not_reported_as_broken() -> None:
    """The third answer, which is the whole reason this is not a two-state reading.

    An image that ships no such tool answers 127. Reporting that as "not serving" would
    mark the fleet broken on the day a pin changes — this milestone's own defect pointed
    the other way — so it is ``None``, and every surface above says nobody asked.
    """
    for status in sorted(health_serving.COULD_NOT_ASK):
        host = _Host(CommandResult(exit_status=status, stdout="", stderr="not found"))

        answered = await health_serving.ask(
            host, checks={"amneziawg": a_check()}, about=["amneziawg"]
        )

        assert answered == {"amneziawg": None}, status


async def test_a_tool_that_ran_and_refused_is_a_no_and_not_a_shrug() -> None:
    """The distinction the line above must not swallow.

    ``awg show`` exits 1 when the interface is not there, and that is the walk's first
    host — the one every other check in this product called healthy.
    """
    host = _Host(CommandResult(exit_status=1, stdout="", stderr=""))

    answered = await health_serving.ask(
        host,
        checks={"amneziawg": a_check(config_of("amneziawg-server.conf"))},
        about=["amneziawg"],
    )

    assert answered == {"amneziawg": False}


async def test_a_transport_that_declares_no_question_is_not_asked_one() -> None:
    """A config with no check is absent from the answer rather than ``None`` in it.

    "This transport declares no such question" and "the question could not be asked" are
    different facts about a node, and only the second is a gap in a reading.
    """
    host = _Host(CommandResult(exit_status=0, stdout="", stderr=""))

    answered = await health_serving.ask(host, checks={}, about=["vless-reality"])

    assert answered == {}
    assert host.commands == [], "a node was asked a question nothing declared"


# --- the declaration itself ----------------------------------------------------------


def test_the_shipped_questions_ask_for_an_authorisation_list_and_not_a_handshake() -> None:
    """The charter's no-logging rule, held against every question this image ships.

    ``wg show <if>`` and ``wg show <if> dump`` print each peer's ENDPOINT and its latest
    handshake time, which is who connected and when — a connection record the moment it
    crosses the wire, whatever the code then does with the bytes. The ``peers``
    subcommand prints the authorisation list this control plane pushed and nothing else.

    A heuristic, and named as one: it cannot read a future package's intent. What it
    does buy is that the obvious sharper command — the one an operator would type — is
    the one that fails here.
    """
    forbidden = {"dump", "endpoints", "latest-handshakes", "transfer"}
    for name, meta in sorted(discover().items()):
        if meta.serving_question is None:
            continue
        asked = set(meta.serving_question.command)
        assert not asked & forbidden, (
            f"transport {name!r} asks its node for {sorted(asked & forbidden)}, which is "
            "a record of who connected and when"
        )


@pytest.mark.parametrize(
    ("broken", "why"),
    [
        (
            {"command": ()},
            "a question with no command is never asked, and both surfaces quietly fall "
            "back to the port reading it was written to replace",
        ),
        ({"reads": None}, "a node asked a question whose answer nothing reads"),
        ({"confirms": "  "}, "a check whose result is a bare word"),
        ({"refutes": ""}, "a check whose result is a bare word"),
    ],
)
def test_a_half_declared_question_is_refused_at_discovery(broken, why, monkeypatch) -> None:
    """A declaration that obliges nothing is a comment — the registry's own rule.

    Refused where every other malformed declaration is refused: at discovery, so the
    failure is one message on the fleet page rather than an exception inside one apply.
    """
    import dataclasses

    from edge import registry

    whole = ServingQuestion(
        command=("awg", "show", "{name}", "peers"),
        reads=lambda answer, config: True,
        confirms="it is up",
        refutes="it is not",
    )
    meta = dataclasses.replace(
        discover()["amneziawg"],
        serving_question=dataclasses.replace(whole, **broken),
    )

    with pytest.raises(ContractViolation):
        registry._check_declaration("amneziawg", meta)
