"""What a node runs, and how it gets there — backlog items 11 and 12.

WHAT: the paths on a node, the compose file that runs its data plane, and the
      bootstrap and apply sequences.
WHY:  a node holds nothing that cannot be regenerated from the control database
      (core invariants §3) — that is what makes "destroy and replace in ten
      minutes" safe. So the node stack is deliberately minimal: one directory, one
      compose file, one config file per transport, and no state worth backing up.
HOW:  rendering the compose file is pure and lives here; the SSH sequences take a
      ``NodeConnection``. The image tag is a PARAMETER, not a constant, because
      core invariants §5 pins the data plane to an exact patch version and that
      pin belongs in configuration the operator can change without a code edit.
"""

import hashlib
import logging

from edge.bootstrap.ssh import NodeConnection
from edge.templating import environment_for

logger = logging.getLogger(__name__)

_TEMPLATES = environment_for(__file__)

# Everything hashi puts on a node lives under here. One directory, so removing a
# node's configuration is one `rm -rf` and there is nothing to hunt for.
NODE_ROOT = "/opt/hashi"
COMPOSE_PATH = f"{NODE_ROOT}/docker-compose.yml"
CONFIG_DIR = f"{NODE_ROOT}/conf"


def config_path(transport_name: str) -> str:
    """Where one transport's rendered config lives on the node.

    Named by the transport, so two transports on one node cannot overwrite each
    other, and so the file on disk is identifiable by an operator reading it.
    """
    return f"{CONFIG_DIR}/{transport_name}.json"


def digest_of(config: str) -> str:
    """A stable digest of a rendered config, for drift detection.

    Meaningful only because rendering is pure and deterministic: the same node
    record renders the same bytes, so a differing digest means the NODE changed,
    not that we re-rendered.
    """
    return hashlib.sha256(config.encode()).hexdigest()


def render_compose(*, transports: list[dict], xray_image: str) -> str:
    """The node's docker-compose.yml.

    Pure. ``transports`` is a list of ``{"name", "config_path", "ports"}`` dicts
    built by the caller from node records — this function never looks up a transport
    or branches on its name.
    """
    return _TEMPLATES.get_template("node-compose.yml.j2").render(
        transports=transports, xray_image=xray_image, config_dir=CONFIG_DIR
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
    connection: NodeConnection, *, transport_name: str, config: str
) -> None:
    """Write one transport's config to the node, 0600.

    Restrictive permissions because a rendered server config contains the node's
    private key — see ``NodeConnection.write_file`` for why the mode is set before
    the bytes land.
    """
    await connection.write_file(config_path(transport_name), config, mode=0o600)


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
