"""Request and response models for the operator API.

WHAT: the shapes the API accepts and returns.
WHY:  explicit response models rather than returning ORM objects, because a
      SQLAlchemy model serialised directly would include whatever columns exist —
      and this schema has columns holding decrypted private keys and subscription
      tokens. An explicit model makes leaking one an act of writing a field name.
HOW:  Pydantic v2. Node and friend responses carry no secret at all; the one place a
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

    # Every shape a friend can receive this transport in — the transport's own
    # declaration, sorted. Since item 27 "not a URI" no longer means "not deliverable",
    # so a yes/no here would hide the thing an operator needs: whether this transport
    # arrives inside the subscription link they already sent, or as a file to import.
    subscription_formats: list[str]

    # Whether a filtering network identifies this protocol on the wire. The transport's
    # own declaration; `control` passes it through and never decides it. Surfaced so the
    # panel can refuse to present such a transport to a friend as a working exit —
    # backlog item 28's constraint, whose declaration half lives in `edge`.
    blocked_by_inspection: bool

    # Whether it may carry an entry-to-leaf hop. Listed for the same reason: the hop form
    # should not offer an option the renderer will refuse.
    hop_capable: bool

    # The parameters an operator must supply, i.e. everything the transport's model
    # requires that is not generated for them. Lets the panel build a form without
    # knowing any protocol.
    operator_params: list[str]


class FriendCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nickname: str = Field(min_length=1, max_length=64)


class FriendResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    nickname: str
    revoked_at: datetime.datetime | None
    created_at: datetime.datetime


class SubscriptionIssued(BaseModel):
    """The one response that contains a bearer credential.

    Returned when a subscription is created or re-displayed to the operator, because
    the operator has to be able to send it to their friend. It is never logged and
    never included in any list endpoint.
    """

    url: str


class RevocationResponse(BaseModel):
    """The outcome of a revocation, including the uncomfortable case."""

    friend_id: str
    complete: bool
    nodes_updated: list[str]
    nodes_failed: dict[str, str]
    summary: str


class ApplyResponse(BaseModel):
    node_id: str
    transports_applied: list[str]


class HealthResponse(BaseModel):
    """A node's health. Says nothing about who connected to it, by construction."""

    node_id: str
    reachable: bool
    healthy: bool
    running: list[str]
    missing: list[str]
    drifted: list[str]
    # Transports whose container is up on a configuration we did not just push —
    # separate from ``drifted`` because they are different faults with different
    # repairs. See ``edge.health.probe.NodeHealth.stale``: a node measured in the field
    # reported ``drifted: []`` while its daemon had never read the file it was reporting
    # about.
    stale: list[str]
    detail: str | None


class ParamsReplace(BaseModel):
    """New values for operator-supplied parameters on one node-transport."""

    model_config = ConfigDict(extra="forbid")

    # Open mapping for the same reason as TransportEnable.params: the shape belongs to
    # the transport, which validates it with its own model.
    params: dict = Field(min_length=1)


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

    # The node friends dial. It DIALS the leaf — the direction is forced, since an
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
    # transport to friends AND carries a hop over it, this is what says which file on
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
    # Only meaningful when moving to `degraded`; the service clears it otherwise, so a
    # node cannot sit in `active` carrying a stale complaint.
    detail: str | None = Field(default=None, max_length=500)


class TransportEnabledChange(BaseModel):
    """Switching one node-transport in or out of what friends are offered.

    A required boolean rather than a toggle verb: two operators looking at the same
    stale page must not be able to flip a transport back and forth by both clicking
    "toggle". Stating the wanted value makes the second request a no-op.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool
