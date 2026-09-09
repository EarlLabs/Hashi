"""What a node does with the packets it decrypts — M14.3.

WHAT: ``Egress``, the closed vocabulary that says whether traffic arriving over one
      tunnel may leave this node for the internet, and ``wg_quick_hooks``, the wg-quick
      expression of it.
WHY:  M14, measured on a real entry node with a real client. The handshake completed in
      both directions, the interface was up, the container was up — and nothing moved,
      because a decrypted packet was dropped by the host's FORWARD chain having never
      been NATed. The rendered config had no ``PostUp``/``PostDown``, so nothing added
      either rule when the interface came up and nothing removed them when it went down.

      The policy is a value rather than a branch because the two answers are not
      interchangeable and the wrong one is silent. A friend-facing tunnel on a leaf must
      exit here. A node-to-node hop must NOT: masquerading it out of the entry is a
      friend in Russia exiting in Russia while every screen shows green, which is the
      failure this project is most afraid of. So the default is ``NONE`` — decision 3's
      fail-closed rule, expressed as the value a caller gets when it says nothing.
HOW:  pure, like everything in this zone: text in, text out, no clock, no I/O, and
      nothing here reads a node, an interface or an address off this machine.

      **It names no interface.** The egress interface is not ``eth0`` everywhere, and a
      rendered name is a node the fleet could not rotate onto (``CLAUDE.md``). The rule
      is written so it never needs one: masquerade what came FROM the tunnel subnet and
      is leaving by anything that is not the tunnel itself. ``%i`` is wg-quick's own
      substitution for the interface it is bringing up, so even the tunnel's name is the
      tool's answer rather than ours.

      **It never logs.** netfilter has a ``LOG`` target and it would break the charter's
      one absolute rule in a single word. There is none here, not even commented out.

One copy, shared by every transport whose config a wg-quick-style tool reads, and
deliberately so. The two WireGuard-family packages duplicate everything else about their
rendering on purpose — one has obfuscation, the other has none, and a shared renderer
would be one ``if`` away from emitting the wrong one. This is the exception, argued
rather than assumed: these lines contain nothing protocol-specific at all, and two
copies of a firewall rule that must be its own exact inverse is precisely how residue
ends up on a node.
"""

import enum
import ipaddress
from dataclasses import dataclass


class Egress(enum.StrEnum):
    """Whether packets decrypted from one tunnel may leave this node for the internet.

    A property of the RELATIONSHIP rather than of the transport or of the node: the same
    protocol on the same host exits locally when friends dial it and must not when it is
    one end of a hop. ``control`` derives it from the ``purpose`` its ``node_transports``
    row already carries, and passes it in.
    """

    # Nothing is forwarded off this node. The fail-closed answer, and the default
    # everywhere: no exit at all beats a quiet local one.
    NONE = "none"

    # Forwarded, and masqueraded out of whatever route this node has to the internet.
    # What a friend-facing transport on a leaf needs, and the whole of M14.1.
    LOCAL = "local"


class EgressNotRenderable(Exception):
    """The policy cannot be expressed for this tunnel, and pretending would be silent.

    Raised rather than rendered as a partial rule set, for the same reason
    ``relay.HopNotRenderable`` exists: the failure it would otherwise hide is a config
    the daemon accepts, an interface that comes up, a handshake that completes and a
    friend who carries nothing.
    """


@dataclass(frozen=True)
class WgQuickHooks:
    """The two hook lines a wg-quick config carries for one egress policy.

    Two fields rather than a rendered fragment because the template places them, and
    because ``up`` and ``down`` have to be checkable against each other — that they
    describe the same rules is M14.2, and a test asserts it.
    """

    up: str
    down: str


# The rules, as (table, chain, rule) — one place, so ``PostUp`` and ``PostDown`` cannot
# drift into describing different rule sets.
#
# Both FORWARD rules are needed and neither is enough. The measured host had ufw's
# ``deny (routed)`` default, so the return direction is dropped just as readily as the
# outbound one.
#
# ``! -o %i`` on the MASQUERADE is what removes the need for an egress interface name AND
# keeps tunnel-internal traffic alone: a packet from one peer to another never leaves the
# interface, so it must not be rewritten to look like the node.
def _rules(network: str) -> tuple[tuple[str, str, str], ...]:
    return (
        ("filter", "FORWARD", "-i %i -j ACCEPT"),
        ("filter", "FORWARD", "-o %i -j ACCEPT"),
        ("nat", "POSTROUTING", f"-s {network} ! -o %i -j MASQUERADE"),
    )


def wg_quick_hooks(egress: Egress, tunnel_address: str) -> WgQuickHooks | None:
    """The ``PostUp``/``PostDown`` pair for one interface under one policy.

    ``None`` when the policy asks for no exit — there is nothing to add, and an empty
    hook line in the file would read as a decision that had been made and lost.

    ``tunnel_address`` is the interface's own address WITH its prefix, exactly as the
    transport's ``Params`` validated it. The masqueraded source is that address's
    network, so the range comes from the node's own record and never from a constant
    here.
    """
    if egress is not Egress.LOCAL:
        return None

    interface = ipaddress.ip_interface(tunnel_address)
    if interface.version != 4:
        # An IPv6 tunnel needs ``ip6tables``, which is a different binary — and one of
        # the pinned data-plane images does not ship it, so a rendered v6 rule would
        # fail inside the container and take the interface down with it. Refused where
        # an operator can still read why, rather than rendered as an IPv4 rule that
        # matches nothing.
        raise EgressNotRenderable(
            f"a local exit was asked for on the IPv6 tunnel {tunnel_address!r}. The "
            "forwarding rules this project renders are IPv4 only; a v6 exit needs a "
            "tool the data-plane images have not been shown to carry. Give this "
            "transport an IPv4 tunnel address, or leave it with no local exit."
        )

    rules = _rules(str(interface.network))

    # Inserted at the head of the chain rather than appended: the measured host runs ufw,
    # whose own rules sit in the same chain, and a rule appended behind them is a rule
    # that may never be reached. Scoped to this interface, so nothing else the operator
    # firewalls is affected.
    up = "; ".join(f"iptables -t {table} -I {chain} 1 {rule}" for table, chain, rule in rules)

    # ``|| true`` on every delete, and it is not decoration. wg-quick runs a hook under
    # ``set -e``, so the first delete that fails abandons every delete after it — and a
    # rule an earlier teardown already removed fails. Without this, the residue M14.2
    # exists to prevent would be created by the teardown itself.
    down = "; ".join(
        f"iptables -t {table} -D {chain} {rule} || true" for table, chain, rule in rules
    )

    return WgQuickHooks(up=up, down=down)


__all__ = ["Egress", "EgressNotRenderable", "WgQuickHooks", "wg_quick_hooks"]
