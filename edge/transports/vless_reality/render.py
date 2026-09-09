"""Pure rendering for VLESS + Reality.

WHAT: ``render_server`` (the node's Xray config) and ``render_client`` (one
      friend's subscription entry).
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

from edge.egress import Egress, exit_origin
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
) -> str:
    """The node's complete Xray config, with one inbound client per credential.

    ``clients`` is a sequence rather than a single credential because a VLESS
    inbound carries every authorised client in one list: that is precisely why
    revocation has to re-render and re-push the node rather than only delete a
    database row. An empty sequence renders a valid config that authorises
    nobody — the correct state for a node with no friends assigned yet, and not
    an error.

    ``egress`` and ``exit_via`` together say which way out a friend's traffic takes. This
    transport renders no forwarding or NAT rule for either, and that is a statement about
    the protocol rather than an omission: Xray is a userspace proxy — it terminates a
    connection and ORIGINATES a new one from the node itself, so no packet of a friend's
    is ever forwarded by the kernel and there is nothing for a FORWARD or NAT rule to act
    on. What decides where that new connection goes is the address it is opened FROM, and
    that is the outbound's business — M3.

    So on an entry node with a hop (``Egress.HOP`` plus the hop's near address) the config
    carries exactly ONE outbound, bound to that address. There is no second outbound to
    fall back to, which is decision 3 expressed structurally: when the hop is down the
    connection cannot be opened, and a friend gets no exit rather than a Russian one.
    With no hop, nothing changes — the same direct outbound as before, byte for byte.
    """
    return _TEMPLATES.get_template("server.j2").render(
        node=node,
        params=params,
        # The address every outgoing connection is opened from, or ``None`` for this
        # node's own route. Checked by ``edge/egress.py`` rather than here: that a policy
        # and an address agree is a question about the policy, not about this protocol.
        exit_origin=exit_origin(egress, exit_via),
        clients=[
            # `email` in an Xray client entry is a label, and Xray uses it in
            # statistics and log lines. It gets the friend's OPAQUE subject, never
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
    """One friend's client entry for this node, as a finished VLESS URI.

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
        # The node's operator-chosen name, not the protocol's. A friend picking an
        # exit in their client should read "leaf-ams-1", not "vless-reality".
        display_label=node.display_name,
        country_label=node.location_label,
        node_id=node.id,
    )


# Re-exported so a reader of this module can see which transport it belongs to
# without opening meta.py. Not used by the registry, which imports meta directly.
__all__ = ["META", "render_client", "render_server"]
