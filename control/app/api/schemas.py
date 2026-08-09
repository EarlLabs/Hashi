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

    ssh_host: str | None = Field(default=None, max_length=255)
    ssh_port: int = Field(default=22, ge=1, le=65535)
    ssh_user: str = Field(default="root", max_length=32)

    # Supplied once, encrypted immediately, and never returned by any endpoint.
    ssh_private_key: str | None = Field(default=None, repr=False)


class NodeResponse(BaseModel):
    """A node as the API describes it. Carries no credential of any kind."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    address: str
    location_label: str
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
    subscription_expressible: bool

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
    detail: str | None
