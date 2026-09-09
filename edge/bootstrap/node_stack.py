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
from collections.abc import Mapping
from dataclasses import dataclass

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
    transport_name: str, config_format: ConfigFormat = ConfigFormat.XRAY_JSON
) -> str:
    """Where one transport's rendered config lives on the node.

    Named by the transport, so two transports on one node cannot overwrite each
    other, and so the file on disk is identifiable by an operator reading it. The
    extension follows the transport's DECLARED format — see ``EXTENSION``.
    """
    return f"{CONFIG_DIR}/{transport_name}.{EXTENSION[config_format]}"


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
# ASSUMPTION, recorded rather than hidden: the tag resolves (checked against the
# registry, and re-checked by the scenario named above), but this project has never
# STARTED it — no node has been deployed. Whether this image accepts ``up <config>`` as
# its command is the owner's field check on the first real node; a registry can confirm a
# tag exists and nothing more.
WIREGUARD_IMAGE = "docker.io/masipcat/wireguard-go:0.0.20230223"


@dataclass(frozen=True)
class DataPlane:
    """How a config in one format is actually run on a node."""

    image: str
    # ``{config}`` is replaced with the path the config was placed at.
    command: tuple[str, ...]
    capabilities: tuple[str, ...] = ()
    devices: tuple[str, ...] = ()


DATA_PLANES = {
    ConfigFormat.XRAY_JSON: DataPlane(
        image=XRAY_IMAGE, command=("run", "-config", "{config}")
    ),
    ConfigFormat.WG_QUICK_PLAIN: DataPlane(
        image=WIREGUARD_IMAGE,
        # wg-quick takes the config PATH and derives the interface name from it.
        command=("up", "{config}"),
        # A tunnel device cannot be created without these two, and nothing else is
        # granted: the proxy containers beside it stay unprivileged, so a compromised
        # data plane cannot reconfigure the node's network.
        capabilities=("NET_ADMIN",),
        devices=("/dev/net/tun:/dev/net/tun",),
    ),
    ConfigFormat.WG_QUICK: DataPlane(
        image=AMNEZIAWG_IMAGE,
        # wg-quick takes the config PATH and derives the interface name from it.
        command=("up", "{config}"),
        # A tunnel device cannot be created without these two, and nothing else is
        # granted: the proxy containers beside it stay unprivileged, so a compromised
        # data plane cannot reconfigure the node's network.
        capabilities=("NET_ADMIN",),
        devices=("/dev/net/tun:/dev/net/tun",),
    ),
}


def config_path_for(transport_name: str) -> str:
    """Where this transport's config goes, per the format the transport declared."""
    return config_path(transport_name, profile(transport_name).meta.config_format)


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

# One line per container: service, digest it was created with, whether it is running.
#
# ``|`` rather than whitespace because both middle fields can be empty (a container
# from before this label existed) or contain a space (Go templates print a missing map
# key as ``<no value>``), and either would silently shift the columns.
_INSPECT_FORMAT = (
    f'{{{{index .Config.Labels "{COMPOSE_SERVICE_LABEL}"}}}}'
    f'|{{{{index .Config.Labels "{CONFIG_DIGEST_LABEL}"}}}}'
    f"|{{{{.State.Running}}}}"
)

# What a Go template prints for a label a container does not carry.
_NO_LABEL = "<no value>"


def services_for(configs: Mapping[str, str]) -> list[dict]:
    """One compose service per transport, each with the daemon its format needs.

    The one place a rendered config's PATH and the command that loads it are decided
    together — split across two callers, they drift, and the symptom is a daemon
    running happily against a file nobody writes. The config's DIGEST is decided here
    for the same reason: the file, the command that loads it and the label that proves
    it was loaded all describe one config, and they have to come from the same bytes or
    the label certifies something that was never pushed.

    Takes the rendered configs rather than the transport names because of that — a name
    alone cannot produce a digest. Still pure: ``digest_of`` is a hash, and nothing here
    touches a node.
    """
    services = []
    for name, config in configs.items():
        data_plane = DATA_PLANES[profile(name).meta.config_format]
        path = config_path_for(name)
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
    for line in result.stdout.splitlines():
        fields = line.strip().split("|")
        if len(fields) != 3:
            continue
        service, digest, running = fields
        # Not everything under this compose project has to be one of ours, and a
        # container that is present but not running is reported by its absence here —
        # the caller's "did it come up" answer, unchanged from before M1.
        if service in ("", _NO_LABEL) or running != "true":
            continue
        loaded[service] = "" if digest == _NO_LABEL else digest
    return loaded
