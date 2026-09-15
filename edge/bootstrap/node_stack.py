"""What a node runs, and how it gets there — backlog items 11 and 12.

WHAT: the paths on a node, the compose file that runs its data plane, and the
      bootstrap and apply sequences.
WHY:  a node holds nothing that cannot be regenerated from the control database
      (core invariants §3) — that is what makes "destroy and replace in ten
      minutes" safe. So the node stack is deliberately minimal: one directory, one
      compose file, one config file per transport, and no state worth backing up.
HOW:  rendering the compose file is pure and lives here; the SSH sequences take a
      ``NodeConnection``. The upstream image pins live here too, keyed by config
      FORMAT rather than by transport — see ``DATA_PLANES``. They are in this zone and
      not in `control` because naming a daemon is naming a protocol, and the control
      plane is not allowed to do either.
"""

import hashlib
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath

from edge.bootstrap.ssh import NodeConnection
from edge.registry import ConfigFormat, profile
from edge.templating import environment_for

logger = logging.getLogger(__name__)

_TEMPLATES = environment_for(__file__)

# Everything hashi puts on a node lives under here. One directory, so removing a
# node's configuration is one `rm -rf` and there is nothing to hunt for.
#
# WHO CREATES IT is a contract with `scripts/node-bootstrap.sh` and not a detail —
# `/opt` is root-owned on every distro, and this library never escalates (see
# ``prepare``). The script creates this directory, owned by the account it tells the
# operator to register as ``ssh_user``; the two halves are pinned together by
# ``tests/infra/test_node_bootstrap_agrees_with_the_control_plane.py``, so changing
# this value here without changing the script turns that suite red. Do not change one
# side alone — a disagreement between them is invisible from either side, which is
# exactly how M13 reached a real host.
NODE_ROOT = "/opt/hashi"
COMPOSE_PATH = f"{NODE_ROOT}/docker-compose.yml"
CONFIG_DIR = f"{NODE_ROOT}/conf"


# The file extension each config format is written with. Not cosmetic: wg-quick
# derives the INTERFACE NAME from the file name and refuses anything but ``.conf``,
# so a config written as ``.json`` would be a valid file the daemon will not load.
EXTENSION = {
    ConfigFormat.XRAY_JSON: "json",
    ConfigFormat.WG_QUICK: "conf",
    ConfigFormat.WG_QUICK_PLAIN: "conf",
}


def config_path(
    config_name: str, config_format: ConfigFormat = ConfigFormat.XRAY_JSON
) -> str:
    """Where one rendered config lives on the node, by the name it is placed under.

    The name is the file's STEM, so two configs on one node cannot overwrite each
    other, and so the file on disk is identifiable by an operator reading it. The
    extension follows the transport's DECLARED format — see ``EXTENSION``.

    Usually the transport's own name, which is what ``config_path_for`` passes and
    what every node in the field already has on disk. It is a name in its own right
    because M15 lets one node run two instances of one transport — a friend-facing
    AmneziaWG and the entry end of a hop — and those are two files, two compose
    services and, for this family, two network interfaces.
    """
    return f"{CONFIG_DIR}/{config_name}.{EXTENSION[config_format]}"


# The pinned upstream data plane for each config FORMAT. Exact patch versions, never
# `latest` and never a bare major — core invariants §5: an upstream that changes its
# default TLS parameters silently changes how detectable every node is.
#
# Keyed by format rather than by transport name, which is what keeps this from being
# the ``if transport ==`` the invariants forbid: a new transport rendering Xray JSON
# needs no entry at all, and one rendering something genuinely new needs one line.
#
# It lives in `edge` rather than in `control` for the same reason everything else about
# a protocol does — the control plane must not be able to name a transport or the
# daemon that runs it.
XRAY_IMAGE = "ghcr.io/xtls/xray-core:1.8.24"

# CORRECTED in backlog item 28, and the correction is worth reading rather than
# glossing. This line used to say ``ghcr.io/amnezia-vpn/amneziawg-go:v0.2.12`` with an
# honest note that the tag had never been pulled. Item 28 resolved every pin in this
# module against a real registry, and that one does not exist — not the tag, not the
# repository, not on that registry at all. So the note was right to be there and the
# value was wrong: no node could ever have started on it.
#
# The replacement is a tag that resolves, on the registry that actually publishes this
# project's images. Note it is a MAJOR version away from what was written (0.2.x → 3.x);
# that is not a migration, because nothing was ever running.
#
# ``tests/e2e/edge/test_every_image_pin_resolves.py`` now checks every entry here, so a
# pin that does not exist cannot sit in the tree unnoticed again.
AMNEZIAWG_IMAGE = "docker.io/amneziavpn/amneziawg-go:3.0.3"

# Plain WireGuard's data plane — its own image, because it is its own format. See
# ``ConfigFormat.WG_QUICK_PLAIN``: running a plain config on the AmneziaWG daemon would
# work, which is precisely the problem.
#
# The assumption that used to be recorded here — "whether this image accepts
# ``up <config>`` as its command is the owner's field check" — has been answered, and the
# answer was no. M2: this image, like the AmneziaWG one, declares an EMPTY entrypoint, so
# the compose ``command`` became the whole argv and Docker tried to exec a binary called
# ``up``. Both containers died at ``Created`` with exit 127 and
# ``exec: "up": executable file not found in $PATH``. See ``_WG_QUICK_SUPERVISOR`` for
# what replaced it, and ``tests/edge/test_every_data_plane_command_is_executable.py`` for
# the check that stops the same assumption being made again by a transport added later.
WIREGUARD_IMAGE = "docker.io/masipcat/wireguard-go:0.0.20230223"


@dataclass(frozen=True)
class DataPlane:
    """How a config in one format is actually run on a node."""

    image: str

    # The argv that REPLACES the image's own ``Cmd``. ``{config}`` is substituted with
    # the path the config was placed at.
    #
    # Read the word "replaces" as the warning it is — it is the whole of M2. Compose's
    # ``command:`` overrides ``Cmd`` and NOT ``Entrypoint``, so for an image that
    # declares no entrypoint this list is the entire argv and its first element must be
    # a binary that image ships. Two of the three images here declare none. An empty
    # tuple is legal and means "the image's own ``Cmd`` is already right"; the compose
    # template then emits no ``command:`` at all.
    command: tuple[str, ...]

    # Every executable this data plane invokes inside the image BEYOND the first element
    # of its argv — the binaries a shell command line runs, which no reader of ``command``
    # can see and no check of argv[0] would catch. It covers what the tool runs out of the
    # CONFIG too (M14 put ``iptables`` in a wg-quick ``PostUp``): the failure is identical
    # either way — a binary the image does not have, discovered on a node.
    #
    # Declared rather than parsed out of the command, because parsing a shell string is
    # guesswork and a wrong guess here reads as "checked". It exists so that
    # ``tests/edge/test_every_data_plane_command_is_executable.py`` can hold every entry
    # in this table against the image's real metadata — including one added later by
    # someone who never read this comment.
    executables: tuple[str, ...] = ()

    # Whether the tool this data plane runs takes the network INTERFACE NAME from the
    # config file's name — which ``wg-quick`` and ``awg-quick`` both do, and which makes
    # the config's path part of the transport's behaviour rather than a storage detail.
    #
    # Declared here rather than checked centrally by format, because it is a property of
    # the TOOL and the rule it enforces is the tool's own. ``services_for`` refuses a
    # transport whose name would not survive it, at render time, rather than letting the
    # node discover it — see ``INTERFACE_NAME``.
    interface_from_config_filename: bool = False

    capabilities: tuple[str, ...] = ()
    devices: tuple[str, ...] = ()


# ``wg-quick``'s own rule for an interface name, copied from its source
# (``[[ $INTERFACE =~ ^[a-zA-Z0-9_=+.-]{1,15}$ ]]``) rather than approximated: 15 is the
# kernel's IFNAMSIZ limit less its terminator, and the character set is what the tool
# will accept before it looks at the file at all.
INTERFACE_NAME = re.compile(r"^[a-zA-Z0-9_=+.-]{1,15}$")


# What a WireGuard-family container actually runs, and the second half of M2.
#
# ``wg-quick up`` CONFIGURES and returns — it is not a daemon. Run as a container's whole
# command it would exit 0 immediately, and ``restart: unless-stopped`` would then restart
# it forever, so "the command exists" is not enough: something has to hold the container
# open for as long as the tunnel should live, and take the tunnel down when it is stopped.
#
# That is what this shell does, and it is the same shape the plain-WireGuard image's own
# entrypoint uses — deliberately, because that script is the upstream author's answer to
# this exact problem and it has been right for years. We do not use the script itself:
# it hardcodes one interface (``wg0``) and one path (``/etc/wireguard/wg0.conf``), and a
# node here runs one container per transport out of one shared directory, so two
# WireGuard-family transports on one node would both claim ``wg0`` in the host's network
# namespace and the second would fail. Ours takes the tool as ``$0`` and the config as
# ``$1``, so ONE line of shell serves the whole family and neither image is named in it.
#
# Line by line, because every clause is load-bearing:
#
# * ``set -e`` — if the ``up`` fails, the container must DIE. Without it the shell would
#   go on to sleep and the node would report a container that is ``Up`` and carrying
#   nothing, which is M2's own failure one level in.
# * ``trap ... INT TERM`` — the interface lives in the HOST's network namespace
#   (``network_mode: host``), so it outlives the container unless it is taken down. Without
#   this, ``docker stop`` leaves a configured tunnel behind on a node that is no longer
#   serving it. Its ``|| true`` is not decoration: ``set -e`` would otherwise abandon the
#   trap at a failing ``down`` and exit 1, reporting a normal stop as a crash.
# * the ``down`` before the ``up`` — recovery, and it is M1 that makes it necessary. A
#   changed config now recreates the container (``CONFIG_DIGEST_LABEL``), and any stop
#   that skipped the trap (SIGKILL, an OOM kill) leaves the old interface in place; the
#   replacement then fails with ``wg-quick: `<name>' already exists`` and crash-loops.
#   Measured, not imagined. Its output is discarded because on the normal path there is
#   nothing to take down and the tool says so on stderr.
# * ``sleep ... & wait $!`` rather than a bare ``sleep`` — a shell blocked in ``sleep``
#   does not run traps until it returns. Backgrounding it and waiting is what makes the
#   trap fire at once, and it is why an unexpected death of the idle child still ends
#   the container: ``wait`` returns non-zero and ``set -e`` takes it from there.
# * the LOOP, and the integer operand, are M21.3. This line used to read ``sleep
#   infinity``, which busybox and GNU coreutils both accept and POSIX does not: the
#   operand is specified as one non-negative decimal integer, so ``infinity`` is an
#   extension. No node ever cared — both images ship busybox — but the test beside this
#   file runs this exact string under the TEST HOST's ``/bin/sh``, and a BSD ``sleep``
#   refuses the operand, so ``make verify`` was red on the owner's own laptop for a
#   reason that had nothing to do with the change under test. Re-sleeping in a loop
#   rather than naming one enormous number keeps any implementation's upper bound on the
#   operand out of it as well; the number only decides how often the shell wakes, and a
#   ``fork`` a day inside a container that lives for months is nothing. Behaviour on a
#   node is unchanged in every respect: it still idles forever, still tears the tunnel
#   down the instant a signal arrives, still dies if the idle dies.
_WG_QUICK_SUPERVISOR = (
    """set -e; trap '"$0" down "$1" || true; exit 0' INT TERM; """
    '"$0" down "$1" >/dev/null 2>&1 || true; '
    '"$0" up "$1"; '
    "while :; do sleep 86400 & wait $!; done"
)


def _wg_quick_command(tool: str) -> tuple[str, ...]:
    """The argv for a data plane whose config is brought up by a wg-quick-style tool.

    ``tool`` arrives as ``$0`` and the config path as ``$1``, so the script text is
    identical for every member of the family and the only difference between two data
    planes is the name of the binary their image ships.
    """
    return ("/bin/sh", "-c", _WG_QUICK_SUPERVISOR, tool, "{config}")


DATA_PLANES = {
    ConfigFormat.XRAY_JSON: DataPlane(
        image=XRAY_IMAGE, command=("run", "-config", "{config}")
    ),
    ConfigFormat.WG_QUICK_PLAIN: DataPlane(
        image=WIREGUARD_IMAGE,
        # ``wg-quick``, this image's own copy — see ``_WG_QUICK_SUPERVISOR``. Not the
        # bare ``up <config>`` that was here before M2: this image declares no
        # entrypoint, so that was an argv beginning with a binary called ``up``.
        command=_wg_quick_command("wg-quick"),
        # ``iptables`` and ``ip`` are not in the command line — they are in the config's
        # ``PostUp``, which this tool runs (M14 and M3, ``edge/egress.py``). Declared
        # here because the consequence of the image not having one of them is the M2
        # failure exactly: the hook fails, wg-quick removes the interface it just made,
        # and the container dies.
        #
        # ``ip`` was left undeclared from M3 until M19 — ``ip rule`` and ``ip route``
        # have been in the hop's hooks since M3, and the check that reads this tuple
        # would not have caught a future pin without ``iproute2``. It was left because
        # the failure is LOUD rather than silent, and it is declared now because
        # "loud" is a property of the day it happens, not a reason not to say so.
        executables=("wg-quick", "iptables", "ip"),
        # ``wg-quick up /opt/hashi/conf/wireguard.conf`` brings up an interface named
        # ``wireguard`` — the config's own stem. So the transport's name reaches the
        # node's network namespace and has to be legal there.
        interface_from_config_filename=True,
        # A tunnel device cannot be created without these two, and nothing else is
        # granted: the proxy containers beside it stay unprivileged, so a compromised
        # data plane cannot reconfigure the node's network.
        capabilities=("NET_ADMIN",),
        devices=("/dev/net/tun:/dev/net/tun",),
    ),
    ConfigFormat.WG_QUICK: DataPlane(
        image=AMNEZIAWG_IMAGE,
        # AmneziaWG's own fork of the tool, under its own name. The image ships no
        # entrypoint script at all, so unlike its plain cousin it has never had anything
        # that could have worked.
        command=_wg_quick_command("awg-quick"),
        # Same reason as its plain cousin above: the egress hooks M14 and M3 render into
        # the config are run by this tool, out of the file, and nothing about ``command``
        # would ever reveal them. ``ip`` is the one the hop needs — ``ip rule`` and
        # ``ip route`` under ``Egress.HOP`` — and this is the family that carries a hop.
        executables=("awg-quick", "iptables", "ip"),
        # Same rule, same tool lineage — see the note on the format above.
        interface_from_config_filename=True,
        # A tunnel device cannot be created without these two, and nothing else is
        # granted: the proxy containers beside it stay unprivileged, so a compromised
        # data plane cannot reconfigure the node's network.
        #
        # Enough on their own: neither image needs the AmneziaWG or WireGuard kernel
        # module, because ``awg-quick``/``wg-quick`` fall back to the userspace
        # implementation each image ships when ``ip link add`` finds no module — which is
        # the normal case on a rented VPS, and the reason ``/dev/net/tun`` is here.
        capabilities=("NET_ADMIN",),
        devices=("/dev/net/tun:/dev/net/tun",),
    ),
}


def config_path_for(transport_name: str) -> str:
    """Where this transport's config goes, per the format the transport declared.

    The single-instance answer: a node running one of a transport places it under the
    transport's own name. ``config_path_of`` is the same question for a node running
    two of one transport, which M15 permits.
    """
    return config_path_of(transport_name, transport_name)


def config_path_of(config_name: str, transport_name: str) -> str:
    """Where the config placed under ``config_name`` goes, for the transport it renders.

    Two arguments because the two answers come from different places: the FILE's name is
    the control plane's — it is what has to be unique on a node, and for the wg-quick
    family it is also the interface name — while the EXTENSION is the transport's, and
    getting that wrong is a valid file the daemon will not load (see ``EXTENSION``).
    """
    return config_path(config_name, profile(transport_name).meta.config_format)


def config_name_is_usable(transport_name: str, config_name: str) -> bool:
    """Whether this transport could be placed on a node under this name.

    Asked by `control` BEFORE it writes a second instance of one transport onto a node.
    The wg-quick family takes its network interface name from the config file's stem
    (``interface_from_config_filename``), so the name is part of what the node can
    actually run rather than a label we are free to choose — and a name the kernel
    refuses is a container that dies at ``up``.

    ``True`` for a transport whose tool does not care, which is most of them: this
    answers for every transport so that `control` never has to ask which family it is
    looking at. ``_check_interface_name`` remains the render-time backstop for the name
    a transport arrives with; this is the question about a name we are about to choose.
    """
    data_plane = DATA_PLANES[profile(transport_name).meta.config_format]
    if not data_plane.interface_from_config_filename:
        return True
    # The stem of ``config_path(config_name, …)`` IS ``config_name``, so the rule is
    # applied to exactly the string the tool would see.
    return bool(INTERFACE_NAME.match(config_name))


# The label each transport's container carries the digest of its own config in.
#
# THIS LABEL IS THE WHOLE OF M1, in both directions, and it is worth reading why one
# value does two jobs.
#
# Outbound: `docker compose up -d` is declarative. It compares the desired SERVICE
# DEFINITION against the running container and does nothing when they match — and the
# CONTENTS of a bind-mounted config file are not part of that definition. So a node
# could be handed a new config, report every container up, and go on serving the old
# one from a process that reads its config only at start. Putting the digest in a label
# makes a changed config *be* a changed definition, and Compose recreates the container
# by itself. `up -d` stays the single verb.
#
# Inbound: a container's labels are fixed when it is CREATED, so `docker inspect` on a
# running container reports the digest that container was started from — not what is on
# disk now. That is the only protocol-agnostic answer to "what did this process
# actually load" available without asking the daemon, and asking the daemon would mean
# a protocol's name in shared code (core invariants §1). See ``loaded_digests``.
#
# The name is ours (reverse-DNS, as Docker's own convention asks) rather than one of
# Compose's `com.docker.compose.*`, which belong to Compose and could be reused by it.
CONFIG_DIGEST_LABEL = "io.hashi.config-digest"

# Compose's own label naming the service a container was created for. Not ours to
# choose, but ours to read: it is how a container is mapped back to the transport whose
# config it runs, without parsing container names.
COMPOSE_SERVICE_LABEL = "com.docker.compose.service"

# One line per container: service, digest it was created with, whether it is running,
# and whether it is RESTARTING.
#
# ``|`` rather than whitespace because both middle fields can be empty (a container
# from before this label existed) or contain a space (Go templates print a missing map
# key as ``<no value>``), and either would silently shift the columns.
#
# THE FOURTH FIELD IS M22, and the reason it has to be there is measured rather than
# reasoned: Docker reports ``Running: true`` for the whole of a restart backoff. A
# container that exits the instant it starts and is restarted for ever therefore answers
# this format ``<service>|<digest>|true`` — up, on the digest we pushed, and serving
# nothing. Measured on engine 29.4.0 on 2026-09-14: a container exiting 23 immediately
# reads ``Status=restarting Running=true Restarting=true`` between every attempt, which
# is exactly the state a real node was in when the panel said it was serving.
#
# ``.State.Restarting`` rather than ``.State.Status`` — the same fact, and a boolean this
# code already knows how to read, where ``Status`` is a vocabulary of seven words whose
# membership is the engine's to change.
_INSPECT_FORMAT = (
    f'{{{{index .Config.Labels "{COMPOSE_SERVICE_LABEL}"}}}}'
    f'|{{{{index .Config.Labels "{CONFIG_DIGEST_LABEL}"}}}}'
    f"|{{{{.State.Running}}}}"
    f"|{{{{.State.Restarting}}}}"
)

# What a Go template prints for a label a container does not carry.
_NO_LABEL = "<no value>"


class UnrunnableTransport(Exception):
    """This transport cannot be run on a node as declared, and no retry will help.

    Raised while RENDERING rather than on the node, because it is a property of the
    transport package and the same on every host — so the first person to see it should
    be whoever added the package, not an operator reading `docker ps` at three in the
    morning.
    """


def _check_interface_name(transport_name: str, path: str, data_plane: DataPlane) -> None:
    """Refuse a transport whose config filename would not be a legal interface name.

    Only for a data plane that declared it derives one from the other. The check is here,
    in the one place the path and the command are decided together, and it asks about the
    PATH the config will be written to rather than about the transport's name — because
    the name the tool sees is the file's stem, and that is what has to be legal.

    A transport name is otherwise unconstrained, so this is a real limit and the message
    says so: 15 characters is IFNAMSIZ, and it is not ours to widen.
    """
    if not data_plane.interface_from_config_filename:
        return
    interface = PurePosixPath(path).stem
    if not INTERFACE_NAME.match(interface):
        raise UnrunnableTransport(
            f"transport {transport_name!r} runs a tool that takes the network interface "
            f"name from its config file, so it would ask for an interface called "
            f"{interface!r} — which is not one this kernel accepts (at most 15 characters "
            f"from a-z A-Z 0-9 _ = + . -). Rename the transport."
        )


def services_for(
    configs: Mapping[str, str], *, transports: Mapping[str, str] | None = None
) -> list[dict]:
    """One compose service per placed config, each with the daemon its format needs.

    The one place a rendered config's PATH and the command that loads it are decided
    together — split across two callers, they drift, and the symptom is a daemon
    running happily against a file nobody writes. The config's DIGEST is decided here
    for the same reason: the file, the command that loads it and the label that proves
    it was loaded all describe one config, and they have to come from the same bytes or
    the label certifies something that was never pushed.

    Takes the rendered configs rather than the transport names because of that — a name
    alone cannot produce a digest. Still pure: ``digest_of`` is a hash, and nothing here
    touches a node.

    ``configs`` is keyed by the name each config is PLACED under, which is also the
    compose service's name and, for the wg-quick family, the node's interface name.
    ``transports`` says which transport each of those came from, and defaults to the
    name itself — the single-instance case, which is every node in the field and every
    caller that existed before M15. A node running two instances of one transport
    (a friend-facing AmneziaWG and a hop end) passes the mapping, because the name on
    the file and the transport that rendered it are then two different strings.
    """
    services = []
    for name, config in configs.items():
        transport_name = (transports or {}).get(name, name)
        data_plane = DATA_PLANES[profile(transport_name).meta.config_format]
        path = config_path_of(name, transport_name)
        _check_interface_name(transport_name, path, data_plane)
        services.append(
            {
                "name": name,
                "config_path": path,
                "config_digest": digest_of(config),
                "image": data_plane.image,
                "command": [part.format(config=path) for part in data_plane.command],
                "capabilities": list(data_plane.capabilities),
                "devices": list(data_plane.devices),
            }
        )
    return services


def digest_of(config: str) -> str:
    """A stable digest of a rendered config, for drift detection.

    Meaningful only because rendering is pure and deterministic: the same node
    record renders the same bytes, so a differing digest means the NODE changed,
    not that we re-rendered.
    """
    return hashlib.sha256(config.encode()).hexdigest()


def render_compose(*, transports: list[dict]) -> str:
    """The node's docker-compose.yml.

    Pure. ``transports`` is a list of dicts carrying ``name``, ``config_path``,
    ``config_digest``, ``image``, ``command`` and optionally ``capabilities`` /
    ``devices`` — built by ``services_for`` from node records and from the pinned
    data-plane table. This function never looks up a transport or branches on its name,
    and it holds no image tag: a literal here would be the version pin living in code
    instead of in configuration (core invariants §5).

    Deterministic in the strong sense M1 needs: the same configs render the same
    compose file, and DIFFERENT configs render a different one. The second half is not
    a nicety — it is what makes `docker compose up -d` recreate a container whose
    config changed. See ``CONFIG_DIGEST_LABEL``.
    """
    return _TEMPLATES.get_template("node-compose.yml.j2").render(
        transports=transports, config_dir=CONFIG_DIR, digest_label=CONFIG_DIGEST_LABEL
    )


# What the operator is told when the node's directory is not there, or is there and
# belongs to somebody else. It names the real problem, which is host preparation, and
# the exact repair — M13, where the same fault arrived as
# ``mkdir: cannot create directory '/opt/hashi': Permission denied`` and cost an
# evening of debugging SSH, keys and docker, none of which were wrong.
#
# It names a node-side path, which operator-facing text in ``ssh.py`` deliberately does
# not. The rule there is about a path that identifies a node or one file on it; this one
# is a constant of the product, identical on every node and written down in this
# repository, and without it the sentence cannot be acted on.
HOST_NOT_PREPARED = (
    f"{NODE_ROOT} is not there, or the account this node is driven as cannot write into "
    "it. The control plane never escalates privilege on a node, so it cannot create that "
    "directory itself: prepare the host with scripts/node-bootstrap.sh, which creates it "
    "owned by the account it tells you to register — or, on a host prepared before that "
    f"script existed, create it once as root: install -d -m 700 -o THE_SSH_USER {NODE_ROOT}"
)


async def prepare(connection: NodeConnection) -> None:
    """Make a prepared host ready to run a data plane.

    Idempotent on purpose — bootstrap gets re-run after a partial failure, and a
    step that fails the second time turns a recoverable node into a rebuild.

    THE PRIVILEGE BOUNDARY IS HERE, and it is the whole of M13. This function runs as
    the account in the node record and never as anything else: no `sudo`, no `su`, no
    per-node "escalate" flag. That keeps every notion of privilege out of `edge`, whose
    value is that it is a library with no policy in it — and it is affordable only
    because ``NODE_ROOT`` arrives already owned by that account, created by
    ``scripts/node-bootstrap.sh`` when the host was prepared.

    So the first thing done here is to check that assumption instead of discovering it
    through a failing `mkdir`. The two are not the same failure: `mkdir -p` on a
    root-owned `/opt` reports `Permission denied`, which reads as a broken SSH account
    and sends the operator to fix the key, the user or docker. What is actually wrong is
    that the host was never prepared, and that is what ``HOST_NOT_PREPARED`` says.

    Time sync is here for a reason the edge rulebook names as a trap: skew breaks
    every TLS-based transport, and Reality handshakes then fail with errors that
    look exactly like blocking. Getting it wrong costs a day of debugging the wrong
    layer.
    """
    prepared = await connection.run(f"test -d {NODE_ROOT} && test -w {NODE_ROOT}", check=False)
    if not prepared.ok:
        raise NodeStackUnsupported(HOST_NOT_PREPARED)

    # ``NODE_ROOT`` itself is deliberately NOT chmod'ed here: its mode belongs to
    # whoever created it (the script uses 700), and an account that legitimately writes
    # into a directory it does not own cannot chmod it — that would turn a working host
    # into a failing apply for no gain. What must be private is what we create, and that
    # is this one.
    await connection.run(f"mkdir -p {CONFIG_DIR} && chmod 700 {CONFIG_DIR}")

    # `|| true`: a host may run systemd-timesyncd, chrony or ntpd, and we do not
    # care which — only that time is being synchronised. Failing the whole bootstrap
    # because a specific daemon is absent would be a policy about the host's distro,
    # which the charter's bring-your-own-SSH model refuses to have.
    await connection.run(
        "timedatectl set-ntp true 2>/dev/null || systemctl start chronyd 2>/dev/null || true",
        check=False,
    )

    result = await connection.run("docker version --format '{{.Server.Version}}'", check=False)
    if not result.ok:
        raise NodeStackUnsupported(
            "docker is not available on this node. hashi configures upstream data-plane "
            "containers and does not install a container runtime for you — see "
            "docs/product/charter.md, bring-your-own-SSH."
        )
    logger.info("node prepared, docker %s", result.stdout.strip())


class NodeStackUnsupported(Exception):
    """The host cannot run the node stack, and no retry will change that."""


async def place_config(
    connection: NodeConnection, *, transport_name: str, config: str, path: str | None = None
) -> None:
    """Write one transport's config to the node, 0600.

    Restrictive permissions because a rendered server config contains the node's
    private key — see ``NodeConnection.write_file`` for why the mode is set before
    the bytes land.

    ``path`` lets the caller pass the path it already computed from the transport's
    declared format, so the config cannot be written somewhere other than where the
    compose file tells the daemon to look for it.
    """
    await connection.write_file(path or config_path(transport_name), config, mode=0o600)


async def place_compose(connection: NodeConnection, *, compose: str) -> None:
    await connection.write_file(COMPOSE_PATH, compose, mode=0o600)


async def restart(connection: NodeConnection) -> None:
    """Bring the node's data plane up on the current configuration.

    ``up -d`` rather than ``restart``: it is the same command whether the stack was
    never started, is partly running, or has a genuinely changed definition. One verb
    for every case means bootstrap and apply follow the same path, so the well-tested
    path is the one that runs during an emergency rotation.

    CORRECTED IN M1, and the correction is the milestone. This comment used to end
    that list with "or needs a changed config picked up", which was false and was the
    defect stated as the design: `up -d` is DECLARATIVE, and the contents of a
    bind-mounted config file are not part of the definition it compares. A node
    measured on 2026-09-09 had a config written 8m25s after the container meant to
    serve it started, through an apply that returned 200. What makes the clause true
    now is not this command — it is ``CONFIG_DIGEST_LABEL``, which puts the config's
    digest into the definition so that a changed config is a changed definition. `up
    -d` on its own still picks up nothing.

    Rejected alternative: swapping this for `restart`. It would break the cases this
    verb exists for — a container that was never created, a definition that genuinely
    changed, a stack that is only partly up — and it would still say nothing about
    whether the daemon came back on the config we pushed, which is ``loaded_digests``'
    job either way.
    """
    await connection.run(f"cd {NODE_ROOT} && docker compose up -d --remove-orphans")


@dataclass(frozen=True)
class RunningContainers:
    """One reading of what a node's compose project has up, in two halves.

    Two halves because ``up`` has two meanings on a node and only one of them serves
    anybody. ``loaded`` is a container that is running and staying running; ``restarting``
    is one the engine is bringing back after it died, which Docker also calls running and
    which carries nothing — M22, and the state a real node was in while the panel reported
    it was serving.

    They are kept apart rather than folded into "not up" for the reason ``drifted`` and
    ``stale`` are kept apart: the faults have different repairs. Nothing there is a
    transport that was never pushed or a container somebody stopped; a crash loop is a
    config the daemon will not accept, and the container's own output on the node says
    which.
    """

    # Service name → the config digest that container was CREATED with. Running, and
    # not in a restart loop.
    loaded: dict[str, str]

    # Service names whose container is being restarted after dying. Sorted.
    restarting: tuple[str, ...]


async def running_containers(connection: NodeConnection) -> RunningContainers:
    """What this node's compose project is running, and what it is merely retrying.

    The single reading both questions come from: one ``docker inspect`` over the whole
    project, split by what it says about each container. Asking twice would be two
    commands and two moments, and a container crossing between them would be reported in
    both halves or in neither.

    See ``loaded_digests`` for why the digest is read from the container's own label, and
    ``_INSPECT_FORMAT`` for why a restart loop cannot be told from a healthy container by
    ``.State.Running`` alone.
    """
    # ``ps -q | xargs docker inspect`` rather than ``compose ps --format json``: the
    # JSON that Compose emits has changed shape between versions (an array, then one
    # object per line) and its ``Labels`` field is a flattened string. ``docker
    # inspect --format`` is a stable interface, and ``-r`` keeps a node with no
    # containers from running ``docker inspect`` with no arguments, which is an error
    # rather than an empty answer.
    result = await connection.run(
        f"cd {NODE_ROOT} && docker compose ps -q | "
        f"xargs -r docker inspect --format '{_INSPECT_FORMAT}'",
        check=False,
    )

    loaded: dict[str, str] = {}
    restarting: set[str] = set()
    for line in result.stdout.splitlines():
        fields = line.strip().split("|")
        if len(fields) != 4:
            continue
        service, digest, running, is_restarting = fields
        # Not everything under this compose project has to be one of ours, and a
        # container that is present but not running is reported by its absence here —
        # the caller's "did it come up" answer, unchanged from before M1.
        if service in ("", _NO_LABEL):
            continue
        # Restarting FIRST, because the engine says both at once. A container in a
        # restart backoff is ``Running: true`` as well, so testing ``running`` first
        # would put every crash loop straight back into ``loaded`` and change nothing.
        if is_restarting == "true":
            restarting.add(service)
        elif running == "true":
            loaded[service] = "" if digest == _NO_LABEL else digest
    return RunningContainers(loaded=loaded, restarting=tuple(sorted(restarting)))


async def loaded_digests(connection: NodeConnection) -> dict[str, str]:
    """Which config each RUNNING container was started from: service name → digest.

    This is M1.2, and it replaces a check that asked whether a process exists. That
    question is the one the bug hid behind: a stale container genuinely IS up, so
    "running" was true and meaningless, and `apply` wrote an ``applied_digest``
    recording a state the node was not in.

    THE SHAPE, and why this one of the three that were considered:

    * A container's labels are part of its definition and are fixed when it is created,
      so ``docker inspect`` on the running container reports the digest THAT CONTAINER
      WAS CREATED WITH — not what is on disk now, which is the thing every other check
      here already reads. It needs no cooperation from the daemon inside, works for
      every transport family alike, and is the same value that made Compose recreate
      the container in the first place, so the two halves of M1 cannot disagree.
    * Container start time versus the config's mtime is what the bug was first measured
      with by hand. Rejected as a product check: it is a clock comparison across two
      machines, and a node that restarts for an unrelated reason reports fresh while
      serving whatever was on disk at that moment.
    * Asking the daemon what it loaded is protocol-specific — a different command and a
      different answer per transport — so it would put a transport's name into shared
      code. Core invariants §1 forbids that, and it is the rule that keeps "a new
      protocol is one new package" true.

    Reads container state only. It says nothing about who is connected, and there is
    deliberately no code path here that could — the charter's no-logging rule covers
    health too: health means "is this node serving", never "who used it".

    A running container with no digest label — one created before M1 — comes back with
    an empty digest rather than being omitted. It is up, and it is provably not on the
    config we would push, which is exactly what a caller comparing digests concludes.

    A CRASH-LOOPING CONTAINER IS NOT IN HERE — M22, and it used to be. See
    ``RunningContainers``: the engine calls a container in a restart backoff running, so
    a daemon that has never once started successfully answered this function with the
    digest we pushed. ``apply`` reads that answer as "it came up" and the probe reads it
    as "it is serving"; both were wrong about the same node. What such a container is now
    is ``RunningContainers.restarting``, which a caller wanting the distinction asks for
    by calling ``running_containers`` instead of this.
    """
    return (await running_containers(connection)).loaded
