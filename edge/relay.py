"""One entry→leaf hop, rendered for both of its ends — backlog item 16.

WHAT: ``render_hop`` — given the two ends of a node-to-node tunnel, the configuration
      each end must run so that traffic arriving at the entry node leaves through the
      leaf node.
WHY:  this is the topology the charter is built on: a Russian ENTRY node fronts foreign
      LEAF nodes, and friends only ever dial the entry. Everything the fleet promises
      about survivability rests on that hop existing — a blocked leaf is replaced by
      re-pointing one hop, with no friend touching their device, and the entry is the
      only address a Russian network ever sees.
HOW:  a hop is symmetric data, not a special protocol. Each end is an ordinary
      transport configuration in which the OTHER end is the single authorised peer, so
      this module renders through the registry like everything else — it names no
      protocol, imports no transport package, and a hop over some future obfuscated
      transport works here unchanged.

      The asymmetry that does exist is one field: the entry dials the leaf, so the
      entry's peer block carries an endpoint and the leaf's does not. That direction is
      forced, not chosen — a node behind a Russian carrier NAT cannot be dialled, and a
      leaf that tried would simply never establish the tunnel.

Purity, as everywhere in ``edge``: no database, no network, no clock, no randomness.
Key material arrives already minted and already decrypted.
"""

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass

from edge.egress import Egress
from edge.node import Credential, NodeView
from edge.registry import profile


class HopNotRenderable(Exception):
    """The two ends do not describe a working tunnel, and rendering them would hide it.

    Raised rather than rendered because every failure this catches produces a config
    that is syntactically valid and silently dead: a tunnel whose ends disagree comes
    up as far as the daemon is concerned and carries nothing. The operator would see a
    healthy node and an unreachable exit.
    """


@dataclass(frozen=True)
class HopEnd:
    """One side of a hop: the node, and the parameters it runs the hop transport with.

    ``params`` is the full merged mapping the transport's own model validated —
    secrets included, exactly as ``render_server`` takes everywhere else.
    """

    node: NodeView
    params: Mapping[str, object]

    @property
    def public_key(self) -> str:
        """This end's public material, under the name the transport declared for it."""
        return str(self.params["public_key"])

    @property
    def tunnel_address(self) -> str:
        return str(self.params["tunnel_address"])


def endpoint_of(end: HopEnd) -> str:
    """The address the far end dials this one at.

    Built from the node's routable address and the hop's own port. Note it is the
    NODE's address rather than anything derived: no geo lookup, no "is this an IP"
    branch — core invariants forbid a renderer inspecting an address.
    """
    address = end.node.address
    # A bare IPv6 address has to be bracketed before a port can be appended, or the
    # daemon reads the last group as the port. The check is about the text's shape,
    # not about where the address is.
    try:
        if ipaddress.ip_address(address).version == 6:
            address = f"[{address}]"
    except ValueError:
        pass  # a hostname, which needs no bracketing
    return f"{address}:{end.params['port']}"


def _check(transport_name: str, entry: HopEnd, leaf: HopEnd) -> None:
    """Refuse the hops that would render cleanly and carry nothing."""
    # The charter's constraint, checked before anything else and before either end of the
    # hop is written. A transport declares this about itself (``hop_capable``); nothing
    # here recognises a protocol.
    #
    # It is first because it is categorical rather than a property of these two ends: the
    # entry-to-leaf hop crosses the Russian border by definition, so a protocol that is
    # blocked there produces two nodes each holding a valid configuration file and no
    # tunnel between them — with nothing in any log to say why, because there is nothing
    # wrong with either file. Backlog item 28.
    meta = profile(transport_name).meta
    if not meta.hop_capable:
        raise HopNotRenderable(
            f"transport {transport_name!r} declares that it cannot carry an "
            "entry-to-leaf hop. That hop crosses a border where this protocol is "
            "identified and blocked, so both ends would be configured correctly and no "
            "tunnel would ever come up. Use an obfuscated transport for the hop."
        )

    # The other half of ``hop_expressible``, and the half nothing used to ask — so a
    # transport that is merely PERMITTED on a hop reached the address reads below and
    # left the operator a ``KeyError`` on a parameter it had never declared. A hop is two
    # ends of one tunnel network, each with an address of its own; ``peer_address`` is
    # where a transport says it hands its consumers one, and a transport that says
    # nothing there has nothing to put at either end of this tunnel. Refused by the
    # declaration, like everything else here — no protocol is recognised.
    if meta.peer_address is None:
        raise HopNotRenderable(
            f"transport {transport_name!r} declares no address of its own for each "
            "consumer, and a hop is two ends of one tunnel network that each need one: "
            "each end authorises the other by its address, and the entry's way out is a "
            "route from its own. There is nothing to put in any of those places here. "
            "Use a transport that gives each consumer an address."
        )

    if entry.node.id == leaf.node.id:
        raise HopNotRenderable(
            "a node cannot be its own exit — this hop would send the node's traffic "
            "back to itself"
        )

    near = ipaddress.ip_interface(entry.tunnel_address)
    far = ipaddress.ip_interface(leaf.tunnel_address)
    if near.ip == far.ip:
        raise HopNotRenderable(
            f"both ends of this hop claim the tunnel address {near.ip} — each end "
            "needs its own"
        )
    if near.network != far.network:
        raise HopNotRenderable(
            f"the two ends are on different tunnel networks ({near.network} and "
            f"{far.network}), so neither would route to the other"
        )

    # A pre-shared key is symmetric: two different values mean the handshake never
    # completes, and the daemon reports nothing more useful than silence.
    if entry.params.get("preshared_key") != leaf.params.get("preshared_key"):
        raise HopNotRenderable(
            "the two ends carry different pre-shared keys, so the handshake would "
            "never complete"
        )

    if not profile(transport_name).meta.family:
        raise HopNotRenderable(f"transport {transport_name!r} declares no family")

    if near.version != 4:
        # Checked here, before either end is rendered, because since M3 a hop is not two
        # tunnels but a relay: the leaf forwards and masquerades what arrives over it and
        # the entry routes its friends into it, and both of those are IPv4 rules (see
        # ``edge/egress.py``). Rendering would raise from inside a transport instead —
        # which reaches the operator as "this node could not be rendered" rather than as
        # "this hop cannot carry traffic", and only after the pair was accepted.
        raise HopNotRenderable(
            f"this hop's tunnel network is {near.network}, and the forwarding a relay "
            "needs is rendered as IPv4 rules only. Give both ends IPv4 tunnel addresses."
        )


def _peer(end: HopEnd, *, endpoint: str | None) -> Credential:
    """Describe one end as the other end's single authorised peer.

    A ``Credential`` because that is the contract's word for "one consumer of this
    transport", and on this hop the consumer is a node rather than a friend. The
    contract does not need to know the difference — which is the debt from M1 being
    paid: the transport contract survived a family that has no URI form.

    ``subject`` is the node id, never its name: this becomes a comment in a file on a
    remote host, and an operator-facing name there would say more about the fleet's
    shape than that file needs to.
    """
    secrets = {
        "peer_public_key": end.public_key,
        "peer_tunnel_address": end.tunnel_address,
    }
    if endpoint is not None:
        secrets["peer_endpoint"] = endpoint
    return Credential(subject=end.node.id, secrets=secrets)


def render_hop(
    transport_name: str, *, entry: HopEnd, leaf: HopEnd
) -> tuple[str, str]:
    """The (entry, leaf) configurations for one hop.

    Rendered through the transport's own ``render_server`` at both ends, so a hop is
    not a second rendering path that could drift from the one under test elsewhere.

    **Each end's egress policy is fixed here rather than asked of the caller** — M14.3,
    and now M3. The two ends are not symmetric and neither answer is the safe default:

    * the LEAF forwards what arrives over the hop and masquerades it out of its own
      route. That is the exit — the foreign address a friend's traffic is supposed to
      appear from, and the whole point of the topology;
    * the ENTRY does the opposite. It masquerades nothing: a packet arriving over this
      hop is a reply for a connection the entry's own proxy opened, and nothing of a
      friend's may leave the entry by the entry's own route. What it renders instead is
      the way OUT — a source-routed path through this tunnel, taken only by traffic
      already sourced from the tunnel's own address (``edge/egress.py``).

    Making either the caller's decision would mean one wrong argument, anywhere,
    reproduces the failure this project is most afraid of: a friend in Russia exiting in
    Russia while the panel shows two active nodes and a live hop.
    """
    _check(transport_name, entry, leaf)
    render = profile(transport_name).profile.render_server

    return (
        # The entry dials, so its peer block carries the leaf's endpoint.
        render(
            entry.node,
            entry.params,
            [_peer(leaf, endpoint=endpoint_of(leaf))],
            egress=Egress.HOP,
            exit_via=exit_via(entry),
        ),
        # The leaf waits. Giving it an endpoint would have it dial a Russian address
        # that is behind carrier NAT, and the tunnel would come up only by luck.
        render(leaf.node, leaf.params, [_peer(entry, endpoint=None)], egress=Egress.LOCAL),
    )


def exit_via(entry: HopEnd) -> str:
    """The address on the ENTRY node that friend traffic leaves through.

    The entry's own tunnel address without its prefix. A connection opened from it can
    only reach the internet through the hop, and while the hop is down it cannot be
    opened at all — which is decision 3, fail-closed, expressed as an address rather
    than as a rule somebody has to remember to write.

    **This replaces M3's own sketch, and the reason is worth having here rather than in a
    commit message.** The plan called for the entry to target the LEAF's in-tunnel
    address as an outbound destination. Nothing listens there: a leaf runs one hop end
    and no proxy (see the runbook's shapes B and C), so there is no address on the leaf to
    dial. What the leaf offers is a route — it forwards and masquerades whatever arrives
    over the hop — and the only way to hand a packet to that route is to send it THROUGH
    the tunnel rather than TO the far end of it. Which is what an address to send from
    buys: the kernel does the rest, and no config anywhere learns what the hop is made of.
    """
    return str(ipaddress.ip_interface(entry.tunnel_address).ip)


__all__ = ["HopEnd", "HopNotRenderable", "endpoint_of", "exit_via", "render_hop"]
