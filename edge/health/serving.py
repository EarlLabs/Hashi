"""Putting a transport's OWN serving question to a node — M26's fourth walk.

WHAT: runs the command one transport declared for one placed config, inside that
      config's own container, and hands the answer back to the transport to judge.
      Answers ``True`` / ``False`` / ``None`` per config — serving, not serving, and
      nobody could ask.
WHY:  three rounds of this milestone each asked a GENERIC question about a SPECIFIC
      daemon and each was satisfied by the wrong answer. The strongest of them —
      ``edge.health.listening``, is the port held — was defeated twice in one walk: once
      by ``nc -u -l`` on the port, and once, without contriving anything, by the real
      data plane with its peer removed, which is what a wrong peer key looks like. Both
      hosts were reported as serving while a hop sat at 100% packet loss.

      A question that shared code can ask cannot tell our data plane from anything else
      holding a number, and the question that can is a different one per protocol. That
      is exactly the shape ``CLAUDE.md`` forbids in shared code — so the protocol-shaped
      half lives in the transport's own package (``TransportMeta.serving_question``) and
      this module is the part that recognises nothing: it substitutes two values it
      knows about any config whatever, runs an argv it never reads, and asks the
      declaration what the answer meant. Nothing here compares a transport's name to
      anything, and adding a protocol adds no line to this file.
HOW:  ``docker compose exec`` into the container the config already runs in, because that
      is where the tool that knows the answer is. The host itself is not asked: a node
      prepared by ``scripts/node-bootstrap.sh`` has docker and nothing else on it, and a
      check that needed a protocol's CLI installed on every host would be a check that
      answers "could not ask" on every host in the fleet.

      THREE ANSWERS, and the third is load-bearing — the same three ``bound_ports``
      keeps one file over, for the same reason it keeps them. A tool missing from an
      image and an engine that would not exec it are facts about the MACHINERY, and
      reporting either as "this node is not serving" would mark a whole fleet broken on
      the day a pin changes. They are decided here, by exit status, and never reach the
      transport: what reaches the transport is a tool that ran.

      NOTHING IS LOGGED AND NOTHING IS STORED. There is no module logger here, exactly as
      in ``edge.health.listening`` and for the same reason: what these commands return is
      a daemon's own reading of its configuration, the transports that ship declare
      questions whose answers are authorisation lists rather than connection records, and
      a logger sitting ready beside that is an invitation. Only the verdict leaves this
      module — never the output, never the command's error text.

      THE TIMING IS THE CALLER'S. This module runs one command and returns; how long to
      wait for a daemon before believing it is a decision about the control plane's own
      patience and lives in ``control/app/services/serving.py``, which is where every
      other clock in this path already is.
"""

import shlex
from collections.abc import Collection, Mapping
from dataclasses import dataclass

from edge.bootstrap.node_stack import NODE_ROOT
from edge.bootstrap.ssh import NodeConnection
from edge.registry import ServingAnswer, ServingQuestion

# NO MODULE LOGGER. See this module's header — the absence is deliberate, as it is in
# ``edge.health.listening``.

# What the engine reports when it could not run the command at all: 125 is docker itself
# failing, 126 is a file that is there and cannot be executed, 127 is one that is not
# there. Docker's own documented convention, and the same pair of codes M2's bug produced
# and ``tests/e2e/edge/test_recorded_image_facts_match_the_real_images.py`` reads.
#
# These are the "nobody could ask" statuses and they are decided HERE rather than by the
# transport: an image that ships no such tool is a fact about our packaging, not about
# whether a protocol is serving, and a transport asked to judge it would have to invent
# an answer. Everything else — including a non-zero status from a tool that ran and
# refused — is the transport's to read.
COULD_NOT_ASK = frozenset({125, 126, 127})


@dataclass(frozen=True)
class ServingCheck:
    """One placed config's own serving question, with everything its command needs.

    Built by `control`, which is the only place that knows which transport a placed
    config came from and what was rendered for it — the same division of labour
    ``Listener`` keeps one file over, and for the same reason: this zone resolves no row
    and looks nothing up.
    """

    # The transport's own declaration: the argv, and the pure function that reads what
    # comes back.
    question: ServingQuestion

    # The configuration this control plane rendered for that placed config. Handed to
    # the transport's own reader, which is what lets it compare what the node is doing
    # against what the node was given — the comparison that makes this check impossible
    # to satisfy with a process that merely holds a port.
    config: str

    # Where that config was placed on the node, for a question whose command needs the
    # path rather than the name.
    path: str


def command_for(name: str, check: ServingCheck) -> str:
    """The shell line that puts one transport's question to one container.

    ``docker compose exec -T`` and not ``docker exec``: the service name is the name the
    config is placed under, which this project already uses as the compose service
    everywhere else (``node_stack.services_for``), so nothing here has to map a container
    name back to a transport. ``-T`` because there is no terminal on an SSH command
    channel and compose would otherwise refuse.

    Every part of the argv is quoted, including the two substitutions. Both values are
    ours — a config name is constrained to an interface-safe alphabet and a path is
    composed by this codebase — so this is the second line of defence rather than the
    first, which is the only kind worth having on a command line built for a remote root
    shell.
    """
    argv = " ".join(
        shlex.quote(part.format(name=name, config=check.path))
        for part in check.question.command
    )
    return f"cd {NODE_ROOT} && docker compose exec -T {shlex.quote(name)} {argv}"


async def ask(
    connection: NodeConnection,
    *,
    checks: Mapping[str, ServingCheck],
    about: Collection[str],
) -> dict[str, bool | None]:
    """Ask each named config's transport whether it is serving, on this node.

    ``about`` is which placed configs to ask about, and the caller is expected to pass
    only those whose container it has just observed running: a container that is not up
    has already been reported by a reading that says so, and exec-ing into it would turn
    one fault into two sentences. A config in ``about`` with no check declared for it is
    absent from the answer entirely rather than present as ``None`` — "this transport
    declares no such question" and "the question could not be asked" are different facts,
    and only the second is a gap.

    One command per config rather than one for the node, because the argv is the
    transport's and two transports on one node do not share it. The fleets this product
    is built for are a handful of hosts running one or two configs each.
    """
    answers: dict[str, bool | None] = {}
    for name in sorted(set(about)):
        check = checks.get(name)
        if check is None:
            continue
        result = await connection.run(command_for(name, check), check=False)
        if result.exit_status in COULD_NOT_ASK:
            answers[name] = None
            continue
        # Standard output only — see this module's header. ``stderr`` is where a daemon
        # writes the text that can name a host, and it is not collected rather than
        # collected and discarded.
        answers[name] = check.question.reads(
            ServingAnswer(exit_status=result.exit_status, output=result.stdout),
            check.config,
        )
    return answers


__all__ = ["COULD_NOT_ASK", "ServingCheck", "ask", "command_for"]
