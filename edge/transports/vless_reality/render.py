"""Pure rendering for VLESS + Reality.

WHAT: ``render_server`` (the node's Xray config) and ``render_client`` (one
      user's subscription entry).
WHY:  both are pure functions of their arguments — no clock, no randomness, no
      network, no database. That is what makes the golden-file tests meaningful
      and configuration drift on a node detectable by plain comparison.
HOW:  the server config comes from ``server.j2``; the client entry is a URI this
      module builds itself. It builds it here, and not in `control`, because every
      part of it is protocol-specific — the scheme *is* the protocol name, and
      `security`/`pbk`/`sid`/`fp`/`flow` mean nothing to any other transport. See
      the edge rulebook, *What ``render_client`` returns*.
"""

from collections.abc import Mapping, Sequence
from urllib.parse import quote, urlencode

from edge.direct import DirectRoutes, direct_resolver_problem
from edge.egress import (
    NOT_THE_INTERNET,
    Egress,
    EgressNotRenderable,
    exit_origin,
    lookup_resolver,
)
from edge.node import Credential, NodeView
from edge.registry import ClientEntry
from edge.templating import environment_for
from edge.transports.vless_reality.meta import META

_TEMPLATES = environment_for(__file__)


def render_server(
    node: NodeView,
    params: Mapping[str, object],
    clients: Sequence[Credential] = (),
    *,
    egress: Egress = Egress.NONE,
    exit_via: str | None = None,
    direct: DirectRoutes | None = None,
) -> str:
    """The node's complete Xray config, with one inbound client per credential.

    ``clients`` is a sequence rather than a single credential because a VLESS
    inbound carries every authorised client in one list: that is precisely why
    revocation has to re-render and re-push the node rather than only delete a
    database row. An empty sequence renders a valid config that authorises
    nobody — the correct state for a node with no users assigned yet, and not
    an error.

    ``egress`` and ``exit_via`` together say which way out a user's traffic takes. This
    transport renders no forwarding or NAT rule for either, and that is a statement about
    the protocol rather than an omission: Xray is a userspace proxy — it terminates a
    connection and ORIGINATES a new one from the node itself, so no packet of a user's
    is ever forwarded by the kernel and there is nothing for a FORWARD or NAT rule to act
    on. What decides where that new connection goes is the address it is opened FROM, and
    that is the outbound's business — M3.

    So on an entry node with a hop (``Egress.HOP`` plus the hop's near address) the config
    carries exactly ONE outbound, bound to that address. There is no second outbound to
    fall back to, which is decision 3 expressed structurally: when the hop is down the
    connection cannot be opened, and a user gets no exit rather than a Russian one.
    With no hop the way out is unchanged — this node's own route, bound to nothing — and
    only what a user may ASK for is narrower since M23's tenth round.

    M16 is the part of that ``sendThrough`` cannot reach. A user's client sends a NAME,
    and the outbound resolves it before it dials — left alone, through the host's own
    resolver, which on an entry node is on the near side of the hop. So under a hop the
    config also carries the resolver on the node's record (``node.resolver``) and routes
    the lookup out through the same outbound as the traffic; a node with a hop and no
    resolver is refused rather than rendered with the host's (``edge/egress.py``).

    And M23's ninth round is the part NEITHER of them reaches: where a user's traffic may
    GO. Both of those settings are about this node's own side of a connection, and a proxy
    dials whatever it is asked for — so a user on an entry node could name the leaf's
    address on the hop and be answered by its SSH daemon, having reached it from the one
    address that leaf's peer entry trusts. Nothing this node forwards is on that path, so
    the refusal is a routing rule here and not a firewall rule anywhere: the config refuses
    every destination off the public internet (``NOT_THE_INTERNET``) for the user-facing
    inbound alone, which is what leaves M16's own lookups untouched.

    M23's tenth round is that refusal made true rather than nearly true, and it is why this
    function passes ``refused`` on EVERY render rather than only under a hop. A leaf's own
    proxy renders no ``sendThrough`` and no resolver, and used to render no refusal either —
    while sitting beside the far end of the hop, its provider's LAN and its metadata
    service. And the rule matched an ADDRESS, so a name resolving into one of those ranges
    was dialled anyway; the template closes that with ``routing.domainStrategy``, which is
    its business and not this module's. See its header for both, measured.

    ``direct`` is M34: the destinations this node opens by its OWN route while everything
    else leaves through the hop, with the resolver their names are looked up at. ``None``
    (and an empty direct list) renders exactly the file this function rendered before the
    feature existed — asserted byte for byte, because "off" must mean off. See
    ``_direct_for_xray`` for the refusals and the template's header for the rule order.
    """
    origin = exit_origin(egress, exit_via)
    resolver = lookup_resolver(egress, node.resolver)
    return _TEMPLATES.get_template("server.j2").render(
        node=node,
        params=params,
        # The address every outgoing connection is opened from, or ``None`` for this
        # node's own route. Checked by ``edge/egress.py`` rather than here: that a policy
        # and an address agree is a question about the policy, not about this protocol.
        exit_origin=origin,
        # Where the names in those connections are looked up — M16, and the half
        # ``sendThrough`` cannot reach: it binds the connection, not the lookup before it.
        # ``None`` with no hop; refused, never defaulted, on a node with one.
        resolver=resolver,
        # What leaves by this node's own route instead of the hop — M34. ``None`` renders
        # the file byte for byte as it was before the feature existed, and so does a
        # ``DirectRoutes`` with nothing in its direct list: see ``_direct_for_xray``.
        direct=_direct_for_xray(direct, origin, resolver),
        # What a user may NOT ask this node to dial — M23's ninth round, and the mirror
        # of the finding a kernel tunnel closed in its own firewall rules. ``edge.egress``
        # owns the list and both kinds of data plane read that one copy; what differs is
        # only how each expresses it, which is why the rule itself is in this package's
        # template and the list is not. See the template's header for why the node's own
        # lookups are not refused with it.
        refused=NOT_THE_INTERNET,
        clients=[
            # `email` in an Xray client entry is a label, and Xray uses it in
            # statistics and log lines. It gets the user's OPAQUE subject, never
            # a nickname or an address — the label must not become a record of who
            # connected. It is derived, not passed in, so no caller can smuggle
            # identifying text into it.
            {"subject": credential.subject, "label": f"c-{credential.subject[:8]}"}
            for credential in clients
        ],
    )


def render_client(
    node: NodeView,
    params: Mapping[str, object],
    credential: Credential,
) -> ClientEntry:
    """One user's client entry for this node, as a finished VLESS URI.

    Returned WITHOUT a display fragment: appending one is `control`'s half of the
    contract, because the fragment is a property of the subscription format that
    every scheme in it shares.
    """
    query = urlencode(
        {
            "encryption": "none",
            "flow": "xtls-rprx-vision",
            "security": "reality",
            "type": "tcp",
            "sni": params["server_names"][0],
            "fp": params["fingerprint"],
            "pbk": params["public_key"],
            "sid": params["short_id"],
        },
        # Ordered by construction (dicts keep insertion order) so the same inputs
        # always produce the same bytes — a URI whose query order drifts would
        # make every golden file and every drift comparison useless.
        quote_via=quote,
    )
    entry = f"vless://{credential.subject}@{node.address}:{params['port']}?{query}"
    return ClientEntry(
        entry=entry,
        # The node's operator-chosen name, not the protocol's. A user picking an
        # exit in their client should read "leaf-ams-1", not "vless-reality".
        display_label=node.display_name,
        country_label=node.location_label,
        node_id=node.id,
    )


def _direct_for_xray(
    direct: DirectRoutes | None, origin: str | None, resolver: str | None
) -> dict | None:
    """``direct`` in Xray's own grammar, or ``None`` when nothing leaves directly.

    The grammar is this package's business and nobody else's: ``domain:`` is Xray's word
    for "this name and every name under it" and ``full:`` for "exactly this name", which
    is what ``Destinations.suffixes`` and ``.names`` mean. Measured against the pinned
    Xray (``tests/edge/test_listed_sites_leave_from_the_entry.py``).

    An EMPTY direct list renders as no list at all, never as a rule with an empty
    condition: a routing rule whose only condition is its inbound matches everything, so
    an empty ``domain`` list here would have sent every user out of the entry.

    Refused rather than rendered when there is no hop to leave by instead — the whole
    feature is a choice between two ways out, and without the hop there is one — and when
    the direct resolver cannot be told apart from the hop's (``direct_resolver_problem``).
    """
    if direct is None or direct.direct.empty:
        return None
    if origin is None:
        raise EgressNotRenderable(
            "this transport was given destinations to send out directly, and its node has "
            "no hop: there is only one way out, so there is nothing to choose between."
        )
    problem = direct_resolver_problem(direct.resolver, resolver)
    if problem:
        raise EgressNotRenderable(problem)

    def names(destinations) -> list[str]:
        return [f"domain:{suffix}" for suffix in destinations.suffixes] + [
            f"full:{name}" for name in destinations.names
        ]

    return {
        "resolver": direct.resolver.strip(),
        "direct_names": names(direct.direct),
        "direct_networks": list(direct.direct.networks),
        "never_names": names(direct.never),
        "never_networks": list(direct.never.networks),
    }


# Re-exported so a reader of this module can see which transport it belongs to
# without opening meta.py. Not used by the registry, which imports meta directly.
__all__ = ["META", "render_client", "render_server"]
