"""Would the command we give a container actually exec? — M2.2, asked of every entry.

WHAT: holds every ``DataPlane`` in ``edge/bootstrap/node_stack.py`` against what its
      image really is: the argv the container would be started with must begin with a
      binary that image can exec, and every binary the command line invokes from inside
      a shell must be there too.
WHY:  M2. Two of the three data planes declared ``command=("up", "{config}")`` against
      images that declare NO entrypoint, so that tuple was the entire argv and docker
      tried to exec a binary called ``up``:

          exec: "up": executable file not found in $PATH   → exit 127, stuck "Created"

      Every test in this suite passed. Rendering was pure, deterministic and golden;
      the compose file was valid; the pinned tags resolved. Nothing anywhere compared a
      declared command against the image that would run it, so the fleet's obfuscated
      transport — the one the runbook MANDATES for the entry-to-leaf hop — had never
      been able to start.

      This is the check that would have caught it, and the reason it is written against
      the TABLE rather than against today's three answers is the second half of M2.2: a
      transport added later brings a new format, a new image and a new command, and
      whoever adds it will not remember to come here. They do not have to. An image
      with no recorded facts fails, loudly, naming the way to record them.

HOW:  the facts come from ``golden/image-facts.json``, recorded from the real images by
      ``tests/e2e/edge/test_recorded_image_facts_match_the_real_images.py`` and kept
      honest by it. This file therefore runs offline, in ``make test-edge``, in a second
      — deliberately, because the alternative is a check that needs the internet, and a
      check that needs the internet is a check that gets skipped on the day it matters.

WHAT THIS DOES NOT PROVE, and it is worth being blunt about it because a green run here
is easy to over-read:

  * that the ARGUMENTS are right. ``awg-quick up <config>`` exec-ing is not
    ``awg-quick`` accepting that config.
  * that the daemon starts, that an interface is created, that a handshake completes or
    that one byte of traffic moves. A container can reach ``Up`` and carry nothing.
  * that the recorded facts are current. That is the e2e scenario's job, and it needs a
    docker engine and a network; if it has not been run since a pin changed, this file
    is asserting against history.

Those are field observations on a real node, and no assertion here stands in for them.
"""

import json
import pathlib

import pytest

from edge.bootstrap.node_stack import DATA_PLANES, services_for
from edge.registry import discover

FACTS = json.loads((pathlib.Path(__file__).parent / "golden" / "image-facts.json").read_text())

# Parametrised by the config FORMAT, which is how the table is keyed — so the ids in a
# failure name the format whose data plane is wrong, not an index.
FORMATS = sorted(DATA_PLANES)

# The flag that turns an argv into "run this script text": ``sh -c '…'``, ``python -c``.
# Everything after it is a program the reader of ``command`` cannot see.
INTERPRETED = "-c"


def facts_for(image: str) -> dict:
    """The recorded facts for one image, or a failure that says how to record them."""
    recorded = FACTS["images"].get(image)
    assert recorded is not None, (
        f"nothing is recorded about {image!r}, so its data plane's command has never "
        "been held against the image that would run it. Record it:\n"
        "    HASHI_RECORD_IMAGE_FACTS=1 pytest "
        "tests/e2e/edge/test_recorded_image_facts_match_the_real_images.py"
    )
    return recorded


def argv_head(image_facts: dict, command: tuple[str, ...]) -> str:
    """The binary docker would exec, given an image and a declared command.

    The rule M2 was broken by, written down once: compose's ``command:`` replaces the
    image's ``Cmd`` and NOT its ``Entrypoint``. So an image with an entrypoint prepends
    it and our command is only arguments; an image without one is handed our command as
    the whole argv, and its first word had better be a program.
    """
    entrypoint = image_facts["entrypoint"]
    if entrypoint:
        return entrypoint[0]
    if command:
        return command[0]
    return image_facts["cmd"][0]


def resolves(image_facts: dict, image: str, name: str) -> bool:
    """Whether the recorded facts say this image can exec ``name``."""
    recorded = image_facts["resolves"]
    assert name in recorded, (
        f"{name!r} has never been looked for in {image!r}. Record it:\n"
        "    HASHI_RECORD_IMAGE_FACTS=1 pytest "
        "tests/e2e/edge/test_recorded_image_facts_match_the_real_images.py"
    )
    return recorded[name]


@pytest.mark.parametrize("config_format", FORMATS)
def test_the_container_would_exec_something_that_exists(config_format) -> None:
    """argv[0] is a binary the image ships. The bug, stated as an assertion."""
    data_plane = DATA_PLANES[config_format]
    image_facts = facts_for(data_plane.image)
    head = argv_head(image_facts, data_plane.command)

    assert resolves(image_facts, data_plane.image, head), (
        f"the data plane for {config_format} would start with {head!r}, which "
        f"{data_plane.image!r} cannot exec. The container reaches `Created` and dies "
        "with exit 127 — it never runs, and every other test still passes."
    )


@pytest.mark.parametrize("config_format", FORMATS)
def test_everything_the_command_line_invokes_exists_too(config_format) -> None:
    """A shell command line's argv[0] is the shell, and proves nothing about its script.

    ``/bin/sh -c '… awg-quick up …'`` execs on any image with a shell, including one
    that ships no WireGuard tools at all — and then dies a second later inside the
    script, where the failure reads as a config problem rather than a packaging one.
    """
    data_plane = DATA_PLANES[config_format]
    image_facts = facts_for(data_plane.image)

    for name in data_plane.executables:
        assert resolves(image_facts, data_plane.image, name), (
            f"the data plane for {config_format} runs {name!r}, which "
            f"{data_plane.image!r} does not have"
        )


@pytest.mark.parametrize("config_format", FORMATS)
def test_a_command_that_runs_a_script_declares_what_the_script_runs(config_format) -> None:
    """Hiding a binary inside ``sh -c`` must not hide it from the check above.

    A heuristic, and named as one: it recognises the ``-c`` convention, which every
    interpreter this project would plausibly use shares. It cannot recognise a wrapper
    script invoked by path. What it does buy is that the obvious way to evade the
    check — move the real program into a quoted string — is the way that fails here.
    """
    data_plane = DATA_PLANES[config_format]
    if INTERPRETED not in data_plane.command:
        return

    assert data_plane.executables, (
        f"the data plane for {config_format} runs an interpreter, so its real program "
        "is inside a string nothing can check. List what it invokes in "
        "``DataPlane.executables``."
    )


def test_the_pre_m2_command_would_be_caught() -> None:
    """The red half: the command that shipped broken must fail this file's check.

    Without this, the three assertions above could be passing because they ask nothing.
    ``("up", "{config}")`` is what was in the tree until M2 — on an image with no
    entrypoint it is the whole argv, and ``up`` is not a program.
    """
    image = "docker.io/amneziavpn/amneziawg-go:3.0.3"
    image_facts = facts_for(image)

    head = argv_head(image_facts, ("up", "{config}"))

    assert head == "up"
    assert image_facts["resolves"].get(head) is not True, (
        "the image is recorded as able to exec `up`, which would mean the recorded "
        "facts are wrong: this is the exact argv that died with exit 127 on a node"
    )


def test_an_image_with_an_entrypoint_prepends_it() -> None:
    """The other half of the same rule, which is why two of three data planes were fine.

    The Xray family's command was correct by luck, not by design: its image declares an
    entrypoint, so ``("run", "-config", …)`` was only ever arguments. Asserted so that a
    later reader does not conclude the difference was in the command.
    """
    facts = {"entrypoint": ["/usr/bin/xray"], "cmd": ["-config", "/etc/xray/config.json"]}

    assert argv_head(facts, ("run", "-config", "{config}")) == "/usr/bin/xray"
    # And with no override at all, the image's own command runs.
    assert argv_head({"entrypoint": [], "cmd": ["/entrypoint.sh"]}, ()) == "/entrypoint.sh"


@pytest.mark.parametrize("transport_name", sorted(discover()))
def test_a_declared_serving_question_runs_a_binary_its_image_ships(transport_name: str) -> None:
    """M26's fourth walk: the question a transport declares is run INSIDE its container.

    So it is the same class of assumption ``DataPlane.command`` was, and the same one M2
    was broken by — with a quieter failure. A binary that is not in the image answers 127,
    which ``edge.health.serving`` correctly reads as "nobody could ask": no error, no red
    row, and a check that silently establishes nothing about every node in the fleet.

    Asked of the transport's declaration and answered from the recorded image facts, so a
    package added later is held to it without anyone remembering this file exists.
    """
    meta = discover()[transport_name]
    if meta.serving_question is None:
        return

    image = DATA_PLANES[meta.config_format].image
    binary = meta.serving_question.command[0]

    assert resolves(facts_for(image), image, binary), (
        f"transport {transport_name!r} asks its node a question that starts with "
        f"{binary!r}, which {image!r} does not ship. The node would answer 127 and the "
        "panel would report that nobody could ask — for ever, and quietly."
    )


@pytest.mark.parametrize("transport_name", sorted(discover()))
def test_every_transport_can_be_placed_on_a_node(transport_name: str) -> None:
    """No transport in the registry has a name its own data plane would refuse.

    The WireGuard family takes its interface name from the config's filename, which is
    the transport's name — so a transport name is not a free-text label for that family,
    it is a kernel interface name with a 15-character limit. Parametrised over
    ``discover()`` rather than over a list, so a transport added later is asked too.
    """
    services_for({transport_name: "a rendered config"})


def test_a_transport_whose_name_is_not_a_legal_interface_is_refused(monkeypatch) -> None:
    """The red half of the rule above, and the reason it is checked at render time.

    Left to the node, this arrives as ``awg-quick: `…' is not a valid interface name``
    in a container's logs at three in the morning. Here it arrives while rendering, with
    the transport named, in front of whoever added the package.
    """
    from edge.bootstrap import node_stack

    # A real transport of the family that has the rule, so the refusal comes from the
    # real data plane and the real profile — only the path is forced.
    victim = next(
        name
        for name in sorted(discover())
        if DATA_PLANES[discover()[name].config_format].interface_from_config_filename
    )
    too_long = "a-transport-with-a-very-long-name"
    # ``config_path_of`` since M15: ``services_for`` asks where a config PLACED under a
    # given name goes, because a node may run two instances of one transport and the
    # file's name is then not the transport's. The rule being forced is unchanged — what
    # is measured is still the path's stem.
    monkeypatch.setattr(
        node_stack,
        "config_path_of",
        lambda config_name, transport_name: f"{node_stack.CONFIG_DIR}/{too_long}.conf",
    )

    with pytest.raises(node_stack.UnrunnableTransport) as raised:
        node_stack.services_for({victim: "a rendered config"})

    assert victim in str(raised.value)
    assert too_long in str(raised.value)
