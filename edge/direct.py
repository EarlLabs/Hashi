"""Which destinations an entry node opens by its OWN route instead of through its hop — M34.

WHAT: ``Destinations`` (a set of names, name suffixes and networks, held in one canonical
      form), ``DirectRoutes`` (what an entry sends direct, what it never does, and the
      resolver the direct names are looked up at), the normalisers that turn an
      operator's or a list's text into that canonical form, ``direct_resolver_problem``
      and ``match`` — the one statement of what "this destination is on that list" means.
WHY:  some destinations refuse every address that is not Russian — state services, banks,
      a few shops — and an entry node is the one machine in the fleet that has a Russian
      address. Sending those out by the entry's own route, and everything else through the
      hop as before, is a decision about DESTINATIONS, and the lists that name them are
      fetched, versioned and held by `control`. What reaches this zone is their content as
      plain values: no URL, no source, no date. Rendering stays pure — nothing here
      fetches, reads a clock or asks a resolver — and two renders of one ``DirectRoutes``
      are the same bytes.
HOW:  ``control`` builds a ``DirectRoutes`` and passes it to a transport that declares
      ``TransportMeta.splits_by_destination``; how a destination is written in a daemon's
      own grammar is that transport's business, never this module's. The canonical form
      (lower case, IDNA-encoded, de-duplicated, sorted) is enforced by the types
      themselves, so a renderer may trust what it is handed and two orderings of one list
      can never be two different configs.

**Rejected: shipping the lists to the node as geo files** (``geosite.dat``) and naming a
category in the rule. A node would then hold data the control database does not — the
version actually in force on a host could not be compared with the one approved — and a
node would have to be handed a second file per list, or fetch it itself, which the
topology forbids (control → node, always). Inline values are bounded instead, and the
bound is `control`'s configuration.
"""

import ipaddress
from collections.abc import Iterable
from dataclasses import dataclass, field

# The longest name DNS can carry, and the longest label inside one (RFC 1035 §2.3.4).
# Protocol limits rather than policy, which is why they may be constants here.
_NAME_MAX = 253
_LABEL_MAX = 63

# What a label may hold once IDNA-encoded. The underscore is allowed because real lists
# carry service names (``_dmarc``-style labels) and a daemon matches them as text; a
# character outside this set is a line that is not a name at all.
_LABEL_CHARACTERS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-_")


class NotADestination(ValueError):
    """A piece of text that is not a name, a name suffix or a network.

    A ``ValueError`` so a caller parsing a list line by line can count it and go on; the
    message is a sentence an operator reads under the box they typed it into.
    """


def normalise_name(text: str) -> str:
    """``text`` as one DNS name in canonical form, or ``NotADestination``.

    Lower case, no trailing dot, no leading ``*.`` (a wildcard is what a suffix already
    means), and IDNA-encoded so that ``госуслуги.рф`` and ``xn--c1aapkosapc.xn--p1ai``
    are one entry: a daemon matches the encoded form, which is what a client sends.
    An address is refused here — it belongs in a network, and accepting it as a name
    would be a rule that matches a hostname nobody has.
    """
    name = text.strip().lower().rstrip(".")
    if name.startswith("*."):
        name = name[2:]
    if not name:
        raise NotADestination("an empty name")
    try:
        ipaddress.ip_address(name)
    except ValueError:
        pass
    else:
        raise NotADestination(
            f"{text.strip()!r} is an address, not a name — give it as a network "
            "(for example with /32 after it)"
        )
    try:
        name = name.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise NotADestination(f"{text.strip()!r} is not a name that DNS can carry") from exc
    if len(name) > _NAME_MAX:
        raise NotADestination(f"{text.strip()!r} is longer than a DNS name can be")
    for label in name.split("."):
        if (
            not label
            or len(label) > _LABEL_MAX
            or not set(label) <= _LABEL_CHARACTERS
            or label.startswith("-")
            or label.endswith("-")
        ):
            raise NotADestination(f"{text.strip()!r} is not a name")
    return name


def normalise_network(text: str) -> str:
    """``text`` as one network in canonical form (``ip_network``'s), or ``NotADestination``.

    A bare address becomes a host network. Host bits are cleared rather than refused:
    lists published by others write ``5.8.43.1/24`` as often as ``5.8.43.0/24``, and
    the two mean the same network to a router.

    A zero-length prefix is refused, in both families. "Every address" is not a list of
    destinations, and in the direct list it would quietly send every user's traffic out
    of the entry's own address — the failure the hop exists to prevent.
    """
    try:
        network = ipaddress.ip_network(text.strip(), strict=False)
    except ValueError as exc:
        raise NotADestination(f"{text.strip()!r} is not an address or a network") from exc
    if network.prefixlen == 0:
        raise NotADestination(
            f"{text.strip()!r} is every address there is, not a list of destinations"
        )
    return str(network)


def _canonical(values: Iterable[str], normalise) -> tuple[str, ...]:
    return tuple(sorted({normalise(value) for value in values}))


@dataclass(frozen=True)
class Destinations:
    """A set of destinations in canonical form.

    ``suffixes`` match a name and every name under it — what every published list this
    feature reads means by a bare line. ``names`` match one name exactly. ``networks``
    match an address inside them, which a NAME reaches only once it has been resolved.

    Built with ``of``; constructing one directly with anything but canonical tuples is
    refused, because a renderer trusts this order and a second order of the same set
    would be a second config for one state.
    """

    suffixes: tuple[str, ...] = ()
    names: tuple[str, ...] = ()
    networks: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for values, normalise in (
            (self.suffixes, normalise_name),
            (self.names, normalise_name),
            (self.networks, normalise_network),
        ):
            if tuple(values) != _canonical(values, normalise):
                raise NotADestination(
                    "destinations must be normalised, de-duplicated and sorted — build "
                    "them with Destinations.of"
                )

    @classmethod
    def of(
        cls,
        *,
        suffixes: Iterable[str] = (),
        names: Iterable[str] = (),
        networks: Iterable[str] = (),
    ) -> Destinations:
        return cls(
            suffixes=_canonical(suffixes, normalise_name),
            names=_canonical(names, normalise_name),
            networks=_canonical(networks, normalise_network),
        )

    @property
    def empty(self) -> bool:
        return not (self.suffixes or self.names or self.networks)

    def __len__(self) -> int:
        return len(self.suffixes) + len(self.names) + len(self.networks)


@dataclass(frozen=True)
class DirectRoutes:
    """What one entry node sends out by its own route, and how it looks those names up.

    ``direct`` is every destination that leaves directly. ``never`` is every destination
    that goes through the hop even when ``direct`` names it — the owner's override, and
    it wins over everything, a source's name or network included. ``resolver`` is where
    a DIRECT name is looked up: a resolver on the entry's side of the border, so the
    answer is the one a Russian client gets. Every other name stays where M16 put it.

    ``resolver`` has no default, for ``NodeView.resolver``'s reason: a default would be a
    resolver this project chose for every node.
    """

    resolver: str
    direct: Destinations
    never: Destinations = field(default_factory=Destinations)


def direct_resolver_problem(resolver: str, hop_resolver: str | None) -> str | None:
    """Why ``resolver`` cannot look up an entry's direct names, or ``None``.

    A sentence rather than an exception, like ``egress.resolver_problem``, so a form can
    refuse the value while the operator is still looking at it and the renderer can
    refuse the same value at the same rule.

    * **a name** would itself have to be looked up first, by the host's own resolver;
    * **IPv6** — the lookups and the direct connections ask for IPv4 answers only,
      matching the hop, so one rule holds for both ways out;
    * **loopback or unspecified** — inside the data plane's container that is not the
      host, and the answer would come from nowhere this panel can name;
    * **the hop's own resolver** — the two are told apart by ADDRESS (the rule that sends
      a lookup out by the entry's own route matches the resolver's address), so one
      address for both would send every lookup, listed or not, out of the entry: the
      M16 leak, switched on by this feature.
    """
    try:
        address = ipaddress.ip_address(resolver.strip())
    except ValueError:
        return (
            f"{resolver!r} is not an IPv4 address. A name would itself have to be looked "
            "up first. Give the resolver's address."
        )
    if address.version != 4:
        return f"{resolver!r} is an IPv6 address; give an IPv4 one."
    if address.is_loopback or address.is_unspecified:
        return (
            f"{resolver!r} would be answered inside the data plane's own container, not "
            "by a resolver on the entry's network. Give a resolver's real address."
        )
    if hop_resolver is not None and address == _address_or_none(hop_resolver):
        return (
            f"{resolver!r} is also this node's resolver for everything else. The two are "
            "told apart by address, so one address for both would send every lookup out "
            "of this node directly. Give a different resolver."
        )
    return None


def _address_or_none(text: str):
    try:
        return ipaddress.ip_address(text.strip())
    except ValueError:
        return None


def match(destination: str, destinations: Destinations) -> str | None:
    """The entry in ``destinations`` that ``destination`` falls under, or ``None``.

    ``destination`` is a name or an address, as an operator would type it into a lookup.
    A name is matched against names and suffixes only: whether it would also fall into a
    NETWORK depends on what it resolves to, and resolving is I/O this zone does not do.
    The caller says that in its own words.

    The entry returned is written the way a person reads it: a suffix as ``*.name``'s
    parent (``name``), an exact name as itself, a network as itself.
    """
    text = destination.strip()
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        address = None
    if address is not None:
        for network in destinations.networks:
            if address in ipaddress.ip_network(network):
                return network
        return None

    name = normalise_name(text)
    if name in destinations.names:
        return name
    labels = name.split(".")
    for start in range(len(labels)):
        candidate = ".".join(labels[start:])
        if candidate in destinations.suffixes:
            return candidate
    return None


__all__ = [
    "Destinations",
    "DirectRoutes",
    "NotADestination",
    "direct_resolver_problem",
    "match",
    "normalise_name",
    "normalise_network",
]
