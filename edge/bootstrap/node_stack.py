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
from collections.abc import Iterable
from dataclasses import dataclass

from edge.bootstrap.ssh import NodeConnection
from edge.registry import ConfigFormat, profile
from edge.templating import environment_for

logger = logging.getLogger(__name__)

_TEMPLATES = environment_for(__file__)

# Everything hashi puts on a node lives under here. One directory, so removing a
# node's configuration is one `rm -rf` and there is nothing to hunt for.
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


def services_for(transport_names: Iterable[str]) -> list[dict]:
    """One compose service per transport, each with the daemon its format needs.

    The one place a rendered config's PATH and the command that loads it are decided
    together — split across two callers, they drift, and the symptom is a daemon
    running happily against a file nobody writes.
    """
    services = []
    for name in transport_names:
        data_plane = DATA_PLANES[profile(name).meta.config_format]
        path = config_path_for(name)
        services.append(
            {
                "name": name,
                "config_path": path,
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
    ``image``, ``command`` and optionally ``capabilities`` / ``devices`` — built by
    the caller from node records and from the pinned data-plane table. This function
    never looks up a transport or branches on its name, and it holds no image tag: a
    literal here would be the version pin living in code instead of in configuration
    (core invariants §5).
    """
    return _TEMPLATES.get_template("node-compose.yml.j2").render(
        transports=transports, config_dir=CONFIG_DIR
    )


async def prepare(connection: NodeConnection) -> None:
    """Make a bare host ready to run a data plane.

    Idempotent on purpose — bootstrap gets re-run after a partial failure, and a
    step that fails the second time turns a recoverable node into a rebuild.

    Time sync is here for a reason the edge rulebook names as a trap: skew breaks
    every TLS-based transport, and Reality handshakes then fail with errors that
    look exactly like blocking. Getting it wrong costs a day of debugging the wrong
    layer.
    """
    await connection.run(f"mkdir -p {CONFIG_DIR} && chmod 700 {NODE_ROOT} {CONFIG_DIR}")

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
    never started, is partly running, or needs a changed config picked up. One verb
    for every case means bootstrap and apply follow the same path, so the
    well-tested path is the one that runs during an emergency rotation.
    """
    await connection.run(f"cd {NODE_ROOT} && docker compose up -d --remove-orphans")


async def running_services(connection: NodeConnection) -> list[str]:
    """Which data-plane services the node reports as running.

    Reads container state only. It says nothing about who is connected, and there is
    deliberately no code path here that could — the charter's no-logging rule covers
    health too: health means "is this node serving", never "who used it".
    """
    result = await connection.run(
        f"cd {NODE_ROOT} && docker compose ps --services --filter status=running", check=False
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]
