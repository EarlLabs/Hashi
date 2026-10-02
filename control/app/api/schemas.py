"""Request and response models for the operator API.

WHAT: the shapes the API accepts and returns.
WHY:  explicit response models rather than returning ORM objects, because a
      SQLAlchemy model serialised directly would include whatever columns exist —
      and this schema has columns holding decrypted private keys and subscription
      tokens. An explicit model makes leaking one an act of writing a field name.
HOW:  Pydantic v2. Node and user responses carry no secret at all; the one place a
      token is returned is ``SubscriptionIssued``, and only at the moment of issue.
"""

import datetime

from pydantic import BaseModel, ConfigDict, Field


class NodeCreate(BaseModel):
    """What the operator supplies to register a node."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    address: str = Field(min_length=1, max_length=255)
    location_label: str = Field(min_length=1, max_length=64)

    # Where this node's users' destination names are looked up once it dials a hop — M16.
    # Optional because a node with no hop never uses it. WHETHER IT CAN CARRY A LOOKUP is
    # checked in services/nodes.py, by the rule ``edge`` renders with, rather than here:
    # that is what lets the panel place the sentence under its own box, as it does for the
    # key below, instead of a type error's generic "not a value this field can take".
    resolver: str | None = Field(default=None, max_length=255)

    ssh_host: str | None = Field(default=None, max_length=255)
    ssh_port: int = Field(default=22, ge=1, le=65535)
    ssh_user: str = Field(default="root", max_length=32)

    # Supplied once, encrypted immediately, and never returned by any endpoint.
    #
    # WHETHER IT IS A KEY AT ALL IS CHECKED IN services/nodes.py, NOT HERE, and that is
    # not an oversight to tidy up. FastAPI answers a model validator's refusal with
    # ``input`` in the body — the value it rejected — so a ``field_validator`` on this
    # field would make ``POST /api/nodes`` echo the pasted private key back in a 422.
    # That is the one thing docs/decisions.md (2026-09-10) says a refusal may never
    # carry. ``nodes.create_node`` refuses it instead, with a sentence and no value.
    ssh_private_key: str | None = Field(default=None, repr=False)


class NodeResponse(BaseModel):
    """A node as the API describes it. Carries no credential of any kind."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    address: str
    location_label: str
    resolver: str | None
    state: str
    state_detail: str | None
    created_at: datetime.datetime


class TransportEnable(BaseModel):
    """Enabling one transport on one node.

    ``params`` is an open mapping because its shape belongs to the transport, which
    validates it with its own model. Accepting a typed model here would mean this
    file knowing every protocol's knobs — the surgery criterion 4 forbids.
    """

    model_config = ConfigDict(extra="forbid")

    transport_name: str = Field(min_length=1, max_length=64)
    params: dict = Field(default_factory=dict)

    # How many people this transport may hand an address of their own to — M17.
    # A FIELD OF ITS OWN AND NOT A MEMBER OF ``params``, because it is not a parameter of
    # the transport: it is a column on the node-transport record, and a transport's model
    # forbids what it does not declare, so it could not travel inside ``params`` at all.
    #
    # Optional here and required by the SERVICE for exactly the transports that declare
    # each consumer needs an address (``TransportMeta.peer_address``) — refused for the
    # rest. Optional rather than required because this schema must not learn which
    # transports those are: the answer is the transport's own declaration, and a required
    # field here would make every VLESS enable send a number that means nothing.
    #
    # A BREAKING CHANGE for one caller only: a script enabling a WireGuard-family
    # transport on a node now gets a 400 naming the box until it sends this. That is the
    # intended answer — before it, the same call produced a transport that served exactly
    # one person and refused to render for the second.
    pool_size: int | None = None


class TransportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    node_id: str
    transport_name: str
    # The name this row is placed under on the node: its config file's stem and, for the
    # wg-quick family, its network interface. Equal to ``transport_name`` for a node
    # running one of this transport, and the only thing telling two instances apart on a
    # node running two — which M15 permits. Not secret and not inventable: it is already
    # the filename on the host.
    config_name: str
    enabled: bool
    applied_at: datetime.datetime | None

    # Non-secret parameters only. The ``secrets`` column is deliberately not a field
    # here, and adding one would be how a node's private key reaches an API response.
    params: dict

    # How many addresses this row may hand out, or null on a transport that hands out
    # none — and on a row enabled before M17, whose pool is the single address already in
    # ``params``. A count, never a list: no address a person holds is in any response.
    pool_size: int | None


class TransportMetaResponse(BaseModel):
    """A transport the image ships, as the panel lists it."""

    name: str
    family: str
    needs_tls: bool
    port_range: tuple[int, int]

    # Whether it rides in the v1 base64 URI list. Kept as its own field because that is
    # the question the existing panel column and every existing client of this endpoint
    # were written against.
    subscription_expressible: bool

    # Every shape a user can receive this transport in — the transport's own
    # declaration, sorted. Since item 27 "not a URI" no longer means "not deliverable",
    # so a yes/no here would hide the thing an operator needs: whether this transport
    # arrives inside the subscription link they already sent, or as a file to import.
    subscription_formats: list[str]

    # Whether a filtering network identifies this protocol on the wire. The transport's
    # own declaration; `control` passes it through and never decides it. Surfaced so the
    # panel can refuse to present such a transport to a user as a working exit —
    # backlog item 28's constraint, whose declaration half lives in `edge`.
    blocked_by_inspection: bool

    # Whether an entry-to-leaf hop can actually be BUILT out of it. Listed for the same
    # reason as the field above: the hop form should not offer an option the renderer
    # will refuse.
    #
    # IT CARRIES ``hop_expressible``, NOT THE RAW ``hop_capable`` DECLARATION — M20's
    # acceptance, and the distinction is what that walk fell into. The raw one is a
    # charter constraint that defaults to True ("this protocol is not identified at the
    # border the hop crosses"), so a transport that was never shaped like a hop end says
    # nothing and reads as able: both VLESS transports were advertised here as capable
    # and answered ``POST /api/hops`` with a 500. The name stays because it is the
    # question a caller asks — may I build a hop out of this — and the value is now the
    # answer to it. The border half of the story is already a field of its own,
    # ``blocked_by_inspection``, so nothing is hidden by not surfacing the permission.
    hop_capable: bool

    # Whether the registry has withdrawn this transport from every list a chooser is
    # built from — M20. Surfaced here because this endpoint is what a script or a second
    # front end builds an "enable a transport" form out of, and a declaration the HTML
    # honours while the JSON does not is a retirement that only holds where somebody
    # remembered it.
    #
    # It says nothing about whether the transport can be enabled: a retired one still
    # renders, still mints material, and is still accepted by
    # ``POST /api/nodes/{id}/transports`` for an operator who names it outright. What
    # stopped is being proposed.
    retired: bool

    # Why, in the transport's own words, and ``None`` when it is not retired. Carried
    # rather than composed here for the reason every other sentence in this response is
    # the transport's: `control` cannot know what is wrong with a protocol it is built
    # not to recognise.
    retired_because: str | None

    # The parameters an operator must supply, i.e. everything the transport's model
    # requires that is not generated for them. Lets the panel build a form without
    # knowing any protocol.
    operator_params: list[str]


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nickname: str = Field(min_length=1, max_length=64)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    nickname: str
    revoked_at: datetime.datetime | None
    created_at: datetime.datetime


class SubscriptionIssued(BaseModel):
    """The one response that contains a bearer credential.

    Returned when a subscription is created or re-displayed to the operator, because
    the operator has to be able to send it to their user. It is never logged and
    never included in any list endpoint.
    """

    url: str


class RevocationResponse(BaseModel):
    """The outcome of a revocation, including the uncomfortable case."""

    user_id: str

    # ``RevocationOutcome.confirmed``, NOT ``RevocationOutcome.complete`` — M23, round 8,
    # and it is the same finding as the panel's one surface over. This field is what an
    # integration polls, and retrying after a partial failure is exactly what an
    # integration does: the second call reported ``complete: true`` with the fleet
    # unchanged between the two, because the service's ``complete`` answers "did every
    # AFFECTED node accept" and a revocation deletes the credential rows that say which
    # nodes were affected. With none left, nothing can fail and the answer is vacuously
    # true. The panel already refused to reassure on it (``panel/routes.py``); this field
    # went on saying it.
    #
    # So what is serialised is the pair a caller may act on: this call withdrew access AND
    # every node it affected accepted the new configuration. FALSE ON A SECOND CALL, and
    # that is the honest direction rather than an inconvenience — once the rows are gone
    # this control plane cannot tell a revocation that was pushed everywhere from one
    # whose push failed, so "the credential is gone from every node" is not a claim it is
    # in a position to make twice. ``withdrew``, ``nodes_failed`` and ``summary`` are what
    # separate "nothing to do" from "a node kept it": a caller that retried and got
    # ``complete: false`` with ``withdrew: false`` has not found a new failure, it has
    # reached the end of what this endpoint can settle, and the rest is a probe and an
    # apply of the node.
    #
    # The NAME is kept deliberately, exactly as ``HealthResponse.running`` kept its name
    # when M22 took crash-looping containers out of it: a field that has been lying is
    # corrected where a caller already reads it, rather than renamed into one they would
    # not notice had gone.
    complete: bool

    # Whether THIS call withdrew anything — M23. The half of the pair above that says
    # which kind of "not complete" this is: false here means the access was already
    # withdrawn before the call, so nothing was pushed and nothing about this call can
    # confirm that any node stopped serving it. ``summary`` says the same in words.
    withdrew: bool
    nodes_updated: list[str]
    nodes_failed: dict[str, str]
    summary: str


class ApplyResponse(BaseModel):
    node_id: str
    transports_applied: list[str]
    # What this apply pushed and could NOT measure serving — fix round 5. Empty is the
    # only answer under which a 200 means "pushed and measured"; a name here is a config
    # that stayed up, was refused by nothing and was confirmed by nothing either (an image
    # without its transport's own check, a host without ``ss``). Its own field because the
    # walk read a success that could not take the reading byte-identical to one that did.
    serving_unmeasured: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """A node's health. Says nothing about who connected to it, by construction."""

    node_id: str
    reachable: bool
    healthy: bool
    running: list[str]
    # Transports whose container the engine is restarting after it died — M22. Its own
    # field rather than an absence from ``running``, because the repairs differ: nothing
    # running is a transport never pushed, a crash loop is a configuration the daemon
    # will not accept and applying the same one again changes nothing.
    #
    # ``running`` used to include these. Docker reports ``Running: true`` throughout a
    # restart backoff, so a daemon that had never once started was listed as running and
    # the panel said the node was serving it.
    restarting: list[str]
    missing: list[str]
    drifted: list[str]
    # Transports whose container is up on a configuration we did not just push —
    # separate from ``drifted`` because they are different faults with different
    # repairs. See ``edge.health.probe.NodeHealth.stale``: a node measured in the field
    # reported ``drifted: []`` while its daemon had never read the file it was reporting
    # about.
    stale: list[str]
    # Transports whose container is running and something holds the port it was given —
    # and, beside it, those whose port nothing holds. M22, and the strongest thing this
    # probe can say: what it establishes is that the port is bound on the node, never
    # that our container bound it and never that anything reached it from outside.
    #
    # A running transport in NEITHER list is one whose port could not be asked about —
    # no port on the row, or a node whose socket table could not be read. That is a third
    # answer on purpose: reporting it as "nothing is listening" would be a confident
    # statement about something nobody measured.
    listening: list[str]
    not_listening: list[str]
    # Transports whose OWN serving question was put to the node and answered yes / no —
    # M26's fourth walk. A different question from the two above, asked of the transport
    # rather than of the socket: a wg-family node answers it by holding the peers it was
    # given, which ``nc`` on its port cannot fake. A running transport in neither list
    # declares no such question, or could not be asked it.
    serving: list[str] = Field(default_factory=list)
    not_serving: list[str] = Field(default_factory=list)
    # Transport name → what its yes (or its no) means, in the transport's own words, for
    # every name in the two lists above. The console composes it into the sentence and
    # must not invent it.
    serving_means: dict[str, str] = Field(default_factory=dict)
    detail: str | None

    @property
    def unchecked_ports(self) -> list[str]:
        """Running transports whose port this probe could not ask about.

        Derived rather than a fourth list, and derived the same way
        ``edge.health.probe.NodeHealth.unchecked_ports`` derives it — a stored copy would
        be a fourth place for the three to disagree. Not a serialised field: an API
        consumer holds the same three lists and can take the same difference.
        """
        return sorted(set(self.running) - set(self.listening) - set(self.not_listening))


class ParamsReplace(BaseModel):
    """New values for operator-supplied parameters on one node-transport."""

    model_config = ConfigDict(extra="forbid")

    # Open mapping for the same reason as TransportEnable.params: the shape belongs to
    # the transport, which validates it with its own model.
    #
    # NO LONGER ``min_length=1`` — M17.1c. Since the pool size travels beside this mapping,
    # a request carrying only a new size is a real request, and refusing it here would
    # refuse the one operation migration 0006 promises: sizing a row that has served since
    # before M17. A request that changes nothing at all is still refused, by the service,
    # which is the only place that can tell — it compares what arrived against what the
    # row already holds, and "these values are already in place" is a better answer than
    # "params is too short".
    params: dict = Field(default_factory=dict)

    # How many people this transport may hand an address to, from here on. Not a member of
    # ``params`` for ``TransportEnable``'s reason: it is a column on the node-transport
    # record rather than a parameter of the transport, whose model forbids what it did not
    # declare. ``None`` leaves the size exactly as it is, which is what a request replacing
    # a blocked decoy sends.
    pool_size: int | None = None


class RotationResponse(BaseModel):
    """The outcome of a rotation, including the case where the push did not land."""

    node_transport_id: str
    rotated: list[str]
    complete: bool
    summary: str


class HopCreate(BaseModel):
    """One entry→leaf hop, both ends at once — backlog item 16.

    Both ends in one request because a hop is only meaningful as a pair: half a hop is
    a node holding a tunnel interface that leads nowhere, and an API that could produce
    one would make that the operator's problem to notice.
    """

    model_config = ConfigDict(extra="forbid")

    # The node users dial. It DIALS the leaf — the direction is forced, since an
    # entry node behind a Russian carrier NAT cannot be dialled.
    entry_node_id: str
    leaf_node_id: str
    transport_name: str

    # Open mappings, validated by the transport's own model, like everywhere else.
    entry_params: dict
    leaf_params: dict


class HopEndResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    node_id: str
    transport_name: str
    # Same field, same reason as ``TransportResponse``: on a node that offers this
    # transport to users AND carries a hop over it, this is what says which file on
    # the host is this end.
    config_name: str
    purpose: str
    # Never ``secrets``: this end's private key lives in the same row.
    params: dict


class HopResponse(BaseModel):
    """A hop, as the pair it is. ``leaf`` is null when one end has been deleted."""

    entry: HopEndResponse
    leaf: HopEndResponse | None


class NodeStateChange(BaseModel):
    """An operator moving a node between states.

    ``state`` is a plain string validated against the enum in the service rather than
    typed as the enum here, so an unknown value produces the service's 409 with its list
    of legal transitions rather than a bare 422 that says only "not a valid enumeration
    member".
    """

    model_config = ConfigDict(extra="forbid")

    state: str
    # Kept on every state but `active`, which the service clears it on — M23, round 4.
    # A node cannot sit in `active` carrying a stale complaint, and a retired one no
    # longer loses the note the operator wrote about the host that is gone.
    detail: str | None = Field(default=None, max_length=500)


class ResolverChange(BaseModel):
    """Setting a node's resolver after it was registered — M16's one edit on a node record.

    Required and non-empty: this is the path that gives a node the resolver it needs, not
    one that takes it away. Whether the value can carry a lookup is the service's check,
    for the reason ``NodeCreate.resolver`` gives.
    """

    model_config = ConfigDict(extra="forbid")

    resolver: str = Field(min_length=1, max_length=255)


class TransportEnabledChange(BaseModel):
    """Switching one node-transport in or out of what users are offered.

    A required boolean rather than a toggle verb: two operators looking at the same
    stale page must not be able to flip a transport back and forth by both clicking
    "toggle". Stating the wanted value makes the second request a no-op.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool
