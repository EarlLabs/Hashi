"""The listener a delivery host runs, and everything it is not allowed to write down.

WHAT: the pinned image, the rendered site configuration and the compose service that
      serve a node's placed delivery directory — plus the SSH step that puts that
      configuration on the host.
WHY:  M27.3. ``delivery.place_delivery`` leaves a node holding pre-rendered artifacts
      and nothing reading them. This is what reads them, and the whole of what makes
      it safe to run is negative: a request carries the name of one person's artifact,
      so every logger in the process is discarded, the container runtime is told to
      retain nothing the process prints, and there is no application behind the file
      server that could learn anything else.
HOW:  Caddy, at the pin below, running the rendered ``delivery-site.Caddyfile.j2``
      over the placed directory. Rendering is pure like everything else in this zone:
      the site ADDRESS and the response headers are passed in, because which hosts
      serve delivery under which name is not this zone's to know and the headers are
      the control plane's own route's.

WHAT A REQUEST CARRIES HERE, because it is the reason this file exists. An artifact's
name is a digest derived from a subscription token per host
(``control/app/services/delivery.artifact_name``), so nothing on a delivery host is a
token and nothing here could record one. The name is still a per-subscription
identifier and, since the path IS how an artifact is fetched, a record of one is a
record of a credential for this host — which is why "no access log" here is the same
absolute rule it is on the control plane and not a tidier default.

NOT DECIDED HERE and deliberately absent: which hosts serve delivery (M27.4), the name
and certificate the site is reached under (M27.6), and where a certificate persists —
no volume is declared for Caddy's own storage, so a host that obtains one today loses
it when the container is recreated.

A NODE RUNS THIS ONLY WHEN SOMETHING ASKS FOR IT. Two calls, neither of which this
package makes: ``compose_service`` has to reach ``node_stack.render_compose``, and
``place_delivery_site`` has to be called on the connection. A host nobody makes them for
keeps the state ``delivery.place_delivery`` leaves it in — holding material, serving
none of it.
"""

import re
from collections.abc import Mapping

from edge.bootstrap.delivery import ARTIFACT_EXTENSION, ARTIFACT_NAME, DELIVERY_DIR
from edge.bootstrap.node_stack import NODE_ROOT, digest_of
from edge.bootstrap.ssh import NodeConnection
from edge.registry import SubscriptionFormat
from edge.templating import environment_for

_TEMPLATES = environment_for(__file__)

# The daemon a delivery host runs, pinned to an exact patch version like every other
# image this zone names (core invariants §5).
#
# IT IS NOT IN ``node_stack.DATA_PLANES`` and cannot be: that table is keyed by
# ``ConfigFormat`` and answers "which daemon runs a transport's config", and a file
# server is neither. It is checked all the same —
# ``tests/e2e/edge/test_every_image_pin_resolves.py`` reads this name beside that
# table, which is the cost the 2026-09-26 rows named for the step that declares the
# service, paid here.
#
# The same Caddy the control plane's own proxy is built from
# (``deploy/docker/caddy.Dockerfile``), at the same tag, and fully qualified because a
# node's engine resolves a bare name against whatever registries it was configured
# with. Not that image: it carries the control plane's Caddyfile, which serves the
# panel and dials the control plane by service name.
DELIVERY_IMAGE = "docker.io/library/caddy:2.8.4-alpine"

# The compose service the listener runs as, and therefore a name no transport on a
# delivery host may take — ``render_compose`` refuses the collision rather than
# rendering two services with one name.
DELIVERY_SERVICE = "delivery"

# Where the rendered site configuration is placed. Beside the delivery directory
# rather than inside it: ``place_delivery`` REPLACES that directory wholesale on every
# apply, so a configuration file in there would be deleted by the next push. The name
# does not begin ``delivery.`` either — ``delivery.incoming`` and ``delivery.replaced``
# are that push's own staging paths.
DELIVERY_SITE_PATH = f"{NODE_ROOT}/delivery-site.Caddyfile"

# What the container runs. The image's own entrypoint would read ``/etc/caddy/Caddyfile``,
# which is the one baked into it; ``--adapter caddyfile`` is required because Caddy only
# infers the adapter for a file literally called ``Caddyfile``.
DELIVERY_COMMAND = (
    "caddy",
    "run",
    "--config",
    DELIVERY_SITE_PATH,
    "--adapter",
    "caddyfile",
)

# The route a user's client asks for, which is the control plane's own
# (``control/app/api/delivery.py``) because a subscription URL must mean the same thing
# whichever host answers it. ``tests/control`` holds the two together.
SUBSCRIPTION_PATH = "/sub/"

# Which shape a request with no ``format`` query asks for — again the control plane's
# answer, for the same reason: a link a user already holds carries no query.
DEFAULT_SHAPE = SubscriptionFormat.V1_URI_LIST

# What the path may carry, derived from the rule this zone already applies to a name
# it is asked to PLACE rather than copied out of it. The two cannot drift, which
# matters in one direction in particular: a listener that accepted less than
# ``place_delivery`` writes would 404 artifacts that are sitting on the disk.
_NAME = ARTIFACT_NAME.pattern.removeprefix("^").removesuffix("$")
_PATH_PATTERN = f"^{SUBSCRIPTION_PATH}({_NAME})$"

# What may be written into the rendered configuration. Everything below goes into a
# Caddyfile as a bare or quoted token, so a value carrying a line break or the quote
# character it is wrapped in could close the block it sits in and open another — the
# whole file is a structure, and these are the parts of it a caller chooses.
#
# A header value is wrapped in BACKTICKS rather than double quotes, which is why a
# double quote is allowed in one: the one value this is written for is a
# ``Content-Disposition`` carrying a quoted filename, and Caddy's backtick-quoted token
# takes it without an escape. Checked against caddy 2.8.4, not assumed.
_SITE_ADDRESS = re.compile(r"^[A-Za-z0-9:/._*\[\]-]{1,255}$")
_HEADER_NAME = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_HEADER_VALUE = re.compile(r"^[\x20-\x7e]{1,256}$")
_UNWRITABLE_IN_A_VALUE = "`\\"


class UnservableSite(Exception):
    """This site cannot be rendered as asked, and no retry will help.

    Raised while rendering rather than on the node, for the reason
    ``node_stack.UnrunnableTransport`` is: it is a property of what the caller passed
    and is the same on every host.
    """


# The matcher name the block for a request naming NO shape is written under. A name of
# its own, because it is a second block for the same format as one of the shapes below
# and two Caddy matchers may not share a name — the first version of this file rendered
# ``@shape_v1_uri_list`` twice.
_NO_SHAPE_NAMED = "no_shape_named"


def _matcher_for(shape: SubscriptionFormat) -> str:
    """A Caddy matcher name for one shape, and the name of its path capture with it.

    Derived from the format's own value so the file reads as the vocabulary it
    dispatches on, with the characters a matcher name and a regexp capture group both
    have to be spelled in.
    """
    return "shape_" + re.sub(r"[^A-Za-z0-9]", "_", str(shape.value))


def _shape(
    shape: SubscriptionFormat, headers: Mapping[str, str], *, matcher: str | None = None
) -> dict:
    return {
        "format": shape.value,
        "matcher": matcher or _matcher_for(shape),
        "pattern": _PATH_PATTERN,
        "extension": ARTIFACT_EXTENSION[shape],
        "headers": sorted(_checked_headers(headers).items()),
    }


def _checked_headers(headers: Mapping[str, str]) -> Mapping[str, str]:
    for name, value in headers.items():
        if not _HEADER_NAME.match(name):
            raise UnservableSite(
                f"{name!r} is not a response header name this site can carry — a name "
                "is 1 to 64 characters from A-Z a-z 0-9 and -, so that it is one token "
                "in the rendered configuration"
            )
        if not _HEADER_VALUE.match(value) or any(
            character in value for character in _UNWRITABLE_IN_A_VALUE
        ):
            raise UnservableSite(
                f"the value given for {name!r} is not one this site can carry — a value "
                "is 1 to 256 printable ASCII characters with no backtick, no backslash "
                "and no line break, so that it cannot end the token it is written into"
            )
    return headers


def render_delivery_site(
    *,
    site_address: str,
    headers: Mapping[str, str],
    shape_headers: Mapping[SubscriptionFormat, Mapping[str, str]] | None = None,
) -> str:
    """The site configuration a delivery host serves its placed directory through.

    Pure, and deterministic in the strong sense the compose file is: the same arguments
    render the same bytes, so a host is only ever handed a changed configuration when
    something actually changed.

    ``site_address`` is a Caddy site address — a name, optionally a scheme and a port —
    and this function neither invents one nor defaults one. Whether a delivery host has
    a name at all is M27.6's question and which hosts are delivery hosts is M27.4's; a
    literal here would be an address the fleet could not rotate away from.

    ``headers`` go on every response, 404s included, and ``shape_headers`` adds to them
    for one shape — the archive's ``Content-Disposition``, in the one caller this is
    written for. Both are the CONTROL PLANE's: its route decides what a subscription
    response carries (``control/app/api/delivery.py``), and a document served from two
    hosts under two policies is two different answers to one link.

    ONE BLOCK PER SUBSCRIPTION FORMAT, off ``ARTIFACT_EXTENSION`` — the same table the
    push writes the files with, so the request that arrives and the file that is on
    disk cannot come to different conclusions about the suffix. A format added later
    adds a block by existing; a transport added later adds nothing at all.

    The directory it serves is ``delivery.DELIVERY_DIR`` and is not a parameter: it is
    the one the push writes into, and a listener pointed anywhere else would be serving
    something nothing puts there.
    """
    if not _SITE_ADDRESS.match(site_address):
        raise UnservableSite(
            f"{site_address!r} is not an address this site can be served on — an "
            "address is 1 to 255 characters of a host, scheme and port and nothing "
            "else, so that it cannot be read as more than one directive"
        )
    per_shape = shape_headers or {}
    return _TEMPLATES.get_template("delivery-site.Caddyfile.j2").render(
        site_address=site_address,
        directory=DELIVERY_DIR,
        headers=sorted(_checked_headers(headers).items()),
        # Sorted by the format's own value, so two fleets rendering the same shapes
        # render the same file. The default shape is passed separately because it gets
        # a SECOND block for a format that already has one above — a different matcher
        # name (two Caddy matchers may not share one) and a different condition: that
        # block answers a request carrying no ``format`` at all, and only that.
        shapes=[
            _shape(shape, per_shape.get(shape, {}))
            for shape in sorted(ARTIFACT_EXTENSION, key=lambda one: one.value)
        ],
        default_shape=_shape(
            DEFAULT_SHAPE, per_shape.get(DEFAULT_SHAPE, {}), matcher=_NO_SHAPE_NAMED
        ),
    )


def compose_service(*, site: str) -> dict:
    """The delivery listener as one entry for ``node_stack.render_compose``.

    A dict of the same shape ``node_stack.services_for`` produces, for the same reason:
    the compose template holds no image tag and no path, so nothing about what runs on
    a node is decided in a template.

    IT CARRIES THE DIGEST OF THE SITE CONFIGURATION, and that is why this takes the
    rendered text rather than nothing at all. It is the whole of M1 applied to a second
    container: ``docker compose up -d`` compares the service DEFINITION, and the
    contents of a bind-mounted file are not part of one — so a host handed a changed
    site would go on serving the previous one from a process that reads its
    configuration only at start, and the apply would report success. See
    ``node_stack.CONFIG_DIGEST_LABEL``, whose label this reuses: it says "the
    configuration this container was created with", which is the same question here.

    ``network_mode: host`` like every other container on a node — the listener has to
    answer on the node's real interface, on whatever port its site address names, and a
    bridge would mean naming that port a second time in a published mapping.

    THE CONTAINER RUNTIME KEEPS NOTHING, and that is the half the site configuration
    cannot cover. Caddy discards its own loggers, but a process that prints anything at
    all — a panic, a configuration it will not load, a future directive that logs by
    default — is captured by the engine and kept in the node's journal, where nobody is
    watching for a subscription identifier to appear. ``driver: none`` is the only
    setting under which there is nothing to retain. It costs the operator this
    container's startup diagnostics, which is a real cost and the smaller one: those
    are recoverable by running the image by hand on the node, and a request line in a
    journal is not recoverable at all.
    """
    return {
        "name": DELIVERY_SERVICE,
        "image": DELIVERY_IMAGE,
        "command": list(DELIVERY_COMMAND),
        "config_digest": digest_of(site),
        "site_path": DELIVERY_SITE_PATH,
        "directory": DELIVERY_DIR,
    }


async def place_delivery_site(connection: NodeConnection, *, site: str) -> None:
    """Put the rendered site configuration on the node.

    0600 and outside the delivery directory, for the two reasons the constants above
    give. It holds no secret — an address and a set of response headers — and the mode
    is the one every file this package places carries, rather than an exception someone
    would have to justify.
    """
    await connection.write_file(DELIVERY_SITE_PATH, site, mode=0o600)
