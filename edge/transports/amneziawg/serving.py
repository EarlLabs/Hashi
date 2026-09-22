"""Is this AmneziaWG interface actually serving? — M26's fourth acceptance walk.

WHAT: the question this package tells the health code to put to a node, and the pure
      function that reads the answer: the interface named after this placed config must
      exist, and it must hold every peer the configuration we pushed authorises.
WHY:  three rounds of this milestone each replaced one proxy with a better proxy and the
      fourth walk defeated the best of them twice, one press each.

      * ``awg-quick`` replaced by ``nc -u -l -p <port>``: the port was held, the apply
        reported success, the probe said *"its container is up and something holds its
        port"* — over a host with no tunnel device and a hop at 100% packet loss.
      * **And then without contriving anything.** The REAL ``awg-quick up``, followed by
        the peer being removed — which is exactly what a wrong peer key or a wrong
        endpoint leaves behind. Device present, ``amneziawg-go`` holding the port,
        ``peers=[]``, 62 KiB sent and 728 B received, 100% loss. Every check the product
        had said the node was fine. An ordinary typo produces that node.

      What both have in common is that the question being asked — *is the number held* —
      is a question about a SOCKET, and any process can answer it. The question an
      operator is actually asking is about THIS protocol, and only this package can ask
      it: a wg-family interface is serving when it exists and holds the peers we gave it.
HOW:  ``awg show <interface> peers``, and nothing wider. That subcommand prints one peer
      PUBLIC KEY per line and nothing else.

      THAT NARROWNESS IS THE WHOLE OF THE PRIVACY ARGUMENT and it is why the obvious
      command is refused. ``awg show <interface>`` and ``awg show <interface> dump``
      print each peer's ENDPOINT and its latest handshake time — which is who connected
      and when, the one record the charter says must not exist, and it would be a
      connection log the moment it crossed the wire whatever this code then did with the
      bytes. ``peers`` prints the AUTHORISATION LIST: the same set of public keys this
      control plane rendered into the config a moment earlier and already holds in its
      database. It says nothing about who reached the node, and there is no code path
      here that could learn it.

      Nothing is logged, stored or returned but the verdict — the same rule
      ``edge.health.listening`` keeps, and for the same reason: a health surface is the
      one most likely to grow a log by accident.

      DELIBERATELY NOT SHARED with the plain-WireGuard package beside it, which asks its
      own daemon the same shape of question through a different binary. That is
      ``render.py``'s own rule one file over: the two protocols agree on a file format
      and disagree on everything that matters, and a shared reader would be one ``if``
      away from asking the wrong daemon.
"""

from edge.registry import ServingAnswer, ServingQuestion

# What a yes and a no mean, in this package's own voice — read by an operator on the
# probe's sentence and nowhere else. They are clauses rather than paragraphs: the
# console composes them into a sentence that already names the node and the transport.
CONFIRMS = (
    "its interface is up and holds every peer this control plane authorised for it"
)
REFUTES = (
    "either its interface is not there at all — which is what a data plane that started "
    "and configured nothing leaves behind — or it is there and does not hold the peers "
    "this control plane authorised, which is what a wrong peer key or a wrong endpoint "
    "leaves behind. Both come up, stay up and carry nothing"
)

# The section a peer's public key is read from, and the key it is written under. Taken
# from ``server.j2`` rather than assumed: every ``[Peer]`` block there carries exactly
# one ``PublicKey`` line, and the ``[Interface]`` block above them carries a PRIVATE key
# under a different name — so a reader that scanned for any key at all would still be
# right here and wrong the day the template gains one.
PEER_SECTION = "[peer]"
PEER_KEY = "publickey"


def authorised_peers(config: str) -> frozenset[str]:
    """Every peer public key one rendered config authorises.

    Reads the file this control plane just rendered, never the node — the whole point of
    the comparison below is that the two are separate readings of what should be one
    fact.

    Parsed rather than tracked alongside the render, because what has to be compared is
    what the NODE was given: a list built beside the renderer could go stale against the
    template and the comparison would then confirm itself. The format is wg-quick's INI
    and this package owns it.
    """
    peers = set()
    section = ""
    for line in config.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("["):
            section = stripped.lower()
            continue
        if section != PEER_SECTION:
            continue
        name, separator, value = stripped.partition("=")
        if not separator or name.strip().lower() != PEER_KEY:
            continue
        peers.add(value.strip())
    return frozenset(peers)


def reads(answer: ServingAnswer, config: str) -> bool | None:
    """Whether this interface is serving what we gave it. Pure.

    THREE ANSWERS, and the only one this function never gives is the third: every way
    the question can fail to be answered at all — the tool missing from the image, the
    engine refusing to exec it — is decided by the code that RUNS the command, because
    those are facts about the machinery and not about this protocol. What reaches here
    is a tool that ran.

    So a non-zero status is a NO rather than a shrug: ``awg show`` exits non-zero when it
    cannot read the interface, and an interface that is not there is the strongest form
    of not serving there is. It is the state the walk's contrived binder produced, and
    the state a data plane whose ``up`` did nothing successfully leaves behind for ever.

    A config that authorises NOBODY is serving as soon as its interface exists — a node
    whose transport has no users on it yet is not broken, and refusing it would make an
    empty pool read as an outage. That is the one case where this answer is no stronger
    than "the interface is there", and it is honest: there is nothing else to check.
    """
    if answer.exit_status != 0:
        return False

    wanted = authorised_peers(config)
    if not wanted:
        return True

    # Every line that is not blank, which is what this subcommand prints: one key per
    # line. Compared as opaque text — this function never decodes a key, and the only
    # thing it does with the set is ask whether ours is inside it.
    on_the_node = {line.strip() for line in answer.output.splitlines() if line.strip()}

    # SUBSET, not equality. A peer the node holds and we did not render is not this
    # question's business: it is drift, which the probe already reads from the file
    # itself and reports with its own repair. Demanding equality here would report one
    # fault twice, in two vocabularies, and the second one would be wrong about which
    # repair it needs.
    return wanted <= on_the_node


# The declaration ``meta.py`` carries. ``{name}`` is the name this config is placed
# under, which for this family is also the node's interface name — the tool takes it
# from the config's filename (``node_stack.DataPlane.interface_from_config_filename``),
# so the two cannot be different strings.
QUESTION = ServingQuestion(
    command=("awg", "show", "{name}", "peers"),
    reads=reads,
    confirms=CONFIRMS,
    refutes=REFUTES,
)

__all__ = ["CONFIRMS", "QUESTION", "REFUTES", "authorised_peers", "reads"]
