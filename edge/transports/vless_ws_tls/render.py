"""Pure rendering for VLESS over WebSocket behind TLS.

The shape is deliberately identical to the first transport's ``render.py``: same
two functions, same signatures, same purity. Nothing here imports the other
transport and nothing here was added to the registry to make it fit — that is the
result the second transport was built to demonstrate.
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
from edge.transports.vless_ws_tls.meta import META
from edge.transports.vless_ws_tls.params import ws_path

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
    """The node's complete Xray config, authorising exactly ``clients``.

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

    M16 is the part of that ``sendThrough`` cannot reach, and it is the first transport's
    reasoning unchanged: a user's client sends a NAME, the outbound resolves it before it
    dials, and under a hop that lookup goes through the hop to the resolver on the node's
    record (``node.resolver``) — or the node is refused, never given the host's resolver.

    M23's ninth and tenth rounds are the first transport's reasoning unchanged too: a proxy
    dials whatever it is asked for, so this config refuses every destination off the public
    internet (``NOT_THE_INTERNET``) for the user-facing inbound alone — on a leaf as much
    as on an entry, and by the destination's resolved ADDRESS rather than by the name a
    user happened to send. The list is ``edge.egress``'s one copy, shared with the kernel
    tunnels that drop the same ranges; the rule expressing it is this package's, in its own
    template.

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
        # Where the names in those connections are looked up — M16. ``None`` with no hop;
        # refused, never defaulted, on a node with one. See ``edge/egress.py``.
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
        ws_path=ws_path(str(params["ws_path_secret"])),
        clients=[
            # Opaque subject only — see the note in the first transport's renderer.
            {"subject": credential.subject, "label": f"c-{credential.subject[:8]}"}
            for credential in clients
        ],
    )


def render_client(
    node: NodeView,
    params: Mapping[str, object],
    credential: Credential,
) -> ClientEntry:
    """One user's client entry, as a finished VLESS-over-WebSocket URI."""
    query = urlencode(
        {
            "encryption": "none",
            "security": "tls",
            "type": "ws",
            "sni": params["server_name"],
            # Both the Host header and the path are part of how the endpoint is
            # addressed; a client that omits either reaches the camouflage site
            # instead of the tunnel, which is the intended behaviour for anyone
            # who does not hold this URI.
            "host": params["server_name"],
            "path": ws_path(str(params["ws_path_secret"])),
        },
        quote_via=quote,
    )
    entry = f"vless://{credential.subject}@{node.address}:{params['port']}?{query}"
    return ClientEntry(
        entry=entry,
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


__all__ = ["META", "render_client", "render_server"]
