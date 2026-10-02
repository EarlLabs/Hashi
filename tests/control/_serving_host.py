"""A fake node at the SHELL, for the fix round 5 tests — M26, walk 4.

WHAT: one host double that answers the four things an apply and a probe ask a node —
      what its containers are doing, what holds its sockets, and (since walk 4) what its
      transport's own serving question returns — with each answer a knob a test turns.
WHY:  walk 4's findings are each a mismatch between two of those answers: a port held
      and no peers (an ordinary wrong key), a port held by a squatter and no interface at
      all, a reading that could not be taken at all, a host that comes up a moment after
      the wait ends. A double that answered "everything works" (``accepting_nodes``)
      cannot express any of them, and one per test file would be four copies of the
      parsers' expected formats.
HOW:  the real compose render, the real ``docker inspect`` parser, the real ``ss`` parser
      and the real serving-question runner all run; only what the host prints is
      invented. The serving answer is computed from the config this control plane
      actually placed on the host, so "holds the peers it was given" is compared against
      the real render rather than against a list the test wrote down.

      Nothing here is a connection record: the peers answer is the authorisation list,
      exactly what ``wg show <if> peers`` prints, and no endpoint or handshake appears.
"""

import yaml

from edge.bootstrap import node_stack
from edge.bootstrap.ssh import CommandResult, NodeUnreachable
from edge.health import listening
from edge.transports.amneziawg.serving import authorised_peers

# What the host's socket table holds besides the transport — we arrived over sshd, so an
# empty table is a reading the parser refuses (``listening.bound_ports``).
SSH_ONLY = """Netid State  Recv-Q Send-Q    Local Address:Port  Peer Address:PortProcess
tcp   LISTEN 0      4096            0.0.0.0:22         0.0.0.0:*
tcp   LISTEN 0      4096               [::]:22            [::]:*
"""

# How a peers answer can come back. ``held`` is a node serving what it was given;
# ``empty`` is walk 4's real daemon with its peer removed (device up, port held,
# ``peers=[]``); ``no-interface`` is the walk's squatter, where nothing configured the
# interface so the tool exits non-zero; ``no-tool`` is an image without the binary
# (exit 127, the "nobody could ask" status ``edge.health.serving`` decides).
PEERS_HELD = "held"
PEERS_EMPTY = "empty"
NO_INTERFACE = "no-interface"
NO_TOOL = "no-tool"


class ServingHost:
    """A node whose every answer is a knob.

    ``port`` / ``protocol`` are where the transport should be listening, and
    ``port_held`` whether something holds it. ``no_ss`` is a host whose socket table
    cannot be read. ``peers`` is one of the four modes above. All of them can be changed
    between presses, which is how a test models a host that recovers.
    """

    learned_host_key = None

    def __init__(
        self,
        *,
        port: int,
        protocol: str,
        port_held: bool = True,
        no_ss: bool = False,
        peers: str = PEERS_HELD,
    ) -> None:
        self.files: dict[str, str] = {}
        self.services: list[str] = []
        self.port = port
        self.protocol = protocol
        self.port_held = port_held
        self.no_ss = no_ss
        self.peers = peers
        # Every serving question this host was asked, by service name — so a test can
        # prove the question was put at all rather than inferring it from a verdict.
        self.asked: list[str] = []
        self.dialled = 0
        # ``unreachable``: no session at all, the way a connect timeout looks.
        # ``drops_at_restart``: a session that opens, takes the files, and dies at the
        # restart — a half-written host.
        self.unreachable = False
        self.drops_at_restart = False
        # M31.3: which LIFE of each container is running, and the digest it was CREATED
        # with — the two things ``docker compose up -d`` decides by. A service whose
        # definition did not change keeps its life across an ``up -d``, exactly as the
        # engine leaves an unchanged container alone; ``docker compose restart`` starts
        # a new one. ``peers_return_on_restart`` is the field walk's leaf: a peer removed
        # live, which only the daemon re-reading its own file puts back.
        self.lives: dict[str, int] = {}
        self.created_with: dict[str, str] = {}
        self.peers_return_on_restart = False
        self.restarted: list[str] = []

    async def __aenter__(self):
        self.dialled += 1
        if self.unreachable:
            raise NodeUnreachable("could not connect to the node: connection timed out")
        return self

    async def __aexit__(self, *_exc_info) -> bool:
        return False

    def sockets(self) -> str:
        if not self.port_held:
            return SSH_ONLY
        state = "LISTEN" if self.protocol == "tcp" else "UNCONN"
        queue = "4096" if self.protocol == "tcp" else "0"
        return (
            SSH_ONLY
            + f"{self.protocol}   {state} 0      {queue}            0.0.0.0:{self.port}"
            f"      0.0.0.0:*\n"
        )

    def peers_answer(self, service: str) -> CommandResult:
        self.asked.append(service)
        if self.peers == NO_TOOL:
            return CommandResult(exit_status=127, stdout="", stderr="not found")
        if self.peers == NO_INTERFACE:
            return CommandResult(exit_status=1, stdout="", stderr="no such device")
        if self.peers == PEERS_EMPTY:
            return CommandResult(exit_status=0, stdout="", stderr="")
        placed = "".join(
            content for path, content in self.files.items() if path.startswith(
                f"{node_stack.NODE_ROOT}/conf/{service}."
            )
        )
        keys = "\n".join(sorted(authorised_peers(placed)))
        return CommandResult(exit_status=0, stdout=keys + ("\n" if keys else ""), stderr="")

    async def run(self, command: str, *, check: bool = True) -> CommandResult:
        if "docker compose exec -T" in command:
            service = command.split("docker compose exec -T ", 1)[1].split()[0]
            return self.peers_answer(service.strip("'"))

        if "docker compose up -d" in command and self.drops_at_restart:
            raise NodeUnreachable("command timed out or failed to start")

        if "docker compose up -d" in command:
            definitions = yaml.safe_load(self.files[node_stack.COMPOSE_PATH])["services"]
            self.services = list(definitions)
            for service, definition in definitions.items():
                digest = definition["labels"][node_stack.CONFIG_DIGEST_LABEL]
                # Recreated only when the definition changed — the engine's rule, and the
                # reason a peer removed live survived every apply on the field walk.
                if self.created_with.get(service) != digest:
                    self.created_with[service] = digest
                    self.lives[service] = self.lives.get(service, 0) + 1
            return CommandResult(exit_status=0, stdout="", stderr="")

        if "docker compose restart " in command:
            named = command.split("docker compose restart ", 1)[1].split()
            for service in named:
                service = service.strip("'")
                self.restarted.append(service)
                self.lives[service] = self.lives.get(service, 0) + 1
            if self.peers_return_on_restart:
                self.peers = PEERS_HELD
            return CommandResult(exit_status=0, stdout="", stderr="")

        if "docker inspect" in command:
            lines = [
                f"{service}|{self.created_with[service]}|true|false|life-{self.lives[service]}"
                for service in self.services
            ]
            return CommandResult(exit_status=0, stdout="\n".join(lines) + "\n", stderr="")

        if command == listening.LISTENING_SOCKETS:
            if self.no_ss:
                return CommandResult(exit_status=127, stdout="", stderr="ss: not found")
            return CommandResult(exit_status=0, stdout=self.sockets(), stderr="")

        if "docker version" in command:
            return CommandResult(exit_status=0, stdout="27.1.1\n", stderr="")

        return CommandResult(exit_status=0, stdout="", stderr="")

    async def write_file(self, path: str, content: str, *, mode: int = 0o600) -> None:
        self.files[path] = content

    async def read_file(self, path: str) -> str | None:
        return self.files.get(path)
