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

THE CERTIFICATE IS HANDED TO THIS LISTENER, NOT OBTAINED BY IT. ``tls`` names two files
the control plane placed, so nothing here dials a certificate authority, answers a
challenge or keeps an account key — and therefore this container declares no volume and
loses nothing when it is recreated, which is the alternative design's first cost. What
this one costs instead is that the certificate is only as fresh as the last apply that
reached the host, and that a private key issued for a name now lives on a node. Both are
recorded in ``docs/decisions.md`` under 2026-09-27, where the decision is, rather than
argued here where this package could not see it change.

NOT DECIDED HERE and deliberately absent: which hosts serve delivery and what each one
is called — that is ``control/app/services/delivery``, a question about the fleet and
about the box, neither of which this zone can see.

A NODE RUNS THIS ONLY WHEN SOMETHING ASKS FOR IT. Three calls, none of which this
package makes: ``compose_service`` has to reach ``node_stack.render_compose``, and
``place_delivery_site`` and ``place_delivery_certificate`` have to be called on the
connection. A host nobody makes them for runs no listener, and what it holds is whatever
the last call to ``delivery`` left there — which is either material nothing serves or,
after ``remove_delivery``, nothing at all.
"""

import re
from collections.abc import Mapping

from edge.bootstrap.delivery import ARTIFACT_EXTENSION, ARTIFACT_NAME, DELIVERY_DIR
from edge.bootstrap.node_stack import NODE_ROOT, digest_of
from edge.bootstrap.ssh import NodeConnection
from edge.registry import Layer4, SubscriptionFormat
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

# THE SOCKET A RENDERED SITE BINDS. Declared because something outside this zone has to
# keep a transport off it, and read from here rather than written down twice: this is
# the daemon's behaviour, measured on the pin above by reading a running container's own
# /proc/net, and not a number anybody chose. Nothing renders it — the site address is a
# bare name and the daemon's defaults do the rest, which is why no port appears in the
# rendered file at all.
#
# It is a CONSEQUENCE and cannot be rotated away from, which is the one thing that makes
# it unlike the addresses and ports ``CLAUDE.md`` keeps out of code. A subscription URL
# is fetched by whatever ordinary HTTPS client a user's device has, at the moment a
# whitelist shutdown has taken everything else away; a delivery endpoint on another port
# is one that is not reachable then, which is the only moment it exists for.
DELIVERY_PORT = 443
DELIVERY_LAYER4 = Layer4.TCP

# Where the rendered site configuration is placed. Beside the delivery directory
# rather than inside it: ``place_delivery`` REPLACES that directory wholesale on every
# apply, so a configuration file in there would be deleted by the next push. The name
# does not begin ``delivery.`` either — ``delivery.incoming`` and ``delivery.replaced``
# are that push's own staging paths.
DELIVERY_SITE_PATH = f"{NODE_ROOT}/delivery-site.Caddyfile"

# The certificate this host serves the site under, and its private key — both placed
# by ``place_delivery_certificate`` below, both beside the site file for the reasons
# that constant gives.
#
# A NODE ASKS NO CERTIFICATE AUTHORITY FOR ANYTHING. These two arrive over the same
# channel every other file on a node arrives over, which keeps the one direction this
# product has: the control plane reaches the node and a node reaches nothing. What it
# costs is stated where it is paid — the material is only as fresh as the last apply
# that reached the host — and what it buys here is that this container needs no
# persistent storage: Caddy is handed a certificate rather than managing one, so there
# is no account key and no issued-certificate store to lose when it is recreated.
DELIVERY_CERTIFICATE_PATH = f"{NODE_ROOT}/delivery-cert.pem"
DELIVERY_CERTIFICATE_KEY_PATH = f"{NODE_ROOT}/delivery-key.pem"

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
#
# BRACES ARE REFUSED IN A VALUE for a reason that has nothing to do with quoting:
# Caddy resolves ``{...}`` as a placeholder inside quoted tokens too, so a value
# carrying one would be answered with whatever it names — ``{http.request.uri}`` would
# put the request path, and therefore the artifact's name, into a response header of
# every answer this host gives. Nothing needs a placeholder here.
_SITE_ADDRESS = re.compile(r"^[A-Za-z0-9:/._*\[\]-]{1,255}$")
_HEADER_NAME = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_HEADER_VALUE = re.compile(r"^[\x20-\x7e]{1,256}$")
_UNWRITABLE_IN_A_VALUE = "`\\{}"


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
    name = matcher or _matcher_for(shape)
    return {
        "format": shape.value,
        "matcher": name,
        # The matcher that asks whether the artifact this request names is actually
        # here. Its own name, because a Caddy matcher name is unique within a site and
        # this is a second one per block.
        "present": f"present_{name}",
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
                "is 1 to 256 printable ASCII characters with no backtick, no backslash, "
                "no brace and no line break, so that it can neither end the token it is "
                "written into nor name a placeholder to be resolved into it"
            )
    return headers


# The one site address shape that is served without TLS, and the whole of how this
# module decides whether to write a ``tls`` directive. Caddy's own vocabulary already
# answers the question — an ``http://`` site has no TLS and refuses a ``tls`` directive
# — so the answer is read off the address the caller passes rather than asked for as a
# second argument that could disagree with it.
_WITHOUT_TLS = "http://"

# The line the template writes when there is a certificate, spelled here so that
# ``compose_service`` can tell a site that needs the certificate mounted from one that
# does not. It is the template's line and not a paraphrase of it: a test renders both
# shapes and asserts this is in one and not the other, so the two cannot drift into a
# listener whose certificate is not mounted.
_TLS_DIRECTIVE = f"\ttls {DELIVERY_CERTIFICATE_PATH} {DELIVERY_CERTIFICATE_KEY_PATH}\n"


def render_delivery_site(
    *,
    site_address: str,
    headers: Mapping[str, str],
    shape_headers: Mapping[SubscriptionFormat, Mapping[str, str]] | None = None,
    certificate: str | None = None,
) -> str:
    """The site configuration a delivery host serves its placed directory through.

    Pure, and deterministic in the strong sense the compose file is: the same arguments
    render the same bytes, so a host is only ever handed a changed configuration when
    something actually changed.

    ``site_address`` is a Caddy site address — a name, optionally a scheme and a port —
    and this function neither invents one nor defaults one. Which hosts are delivery
    hosts and what each one is called are both questions about the fleet
    (``control/app/services/delivery``); a literal here would be an address the fleet
    could not rotate away from.

    NO PORT IS WRITTEN, ANYWHERE, and that is the answer rather than the absence of
    one. A bare name is a complete Caddy site address and the daemon's own defaults
    decide what it binds — which is how ``deploy/caddy/Caddyfile`` already serves the
    control plane's own ``/sub/*``. Measured against caddy 2.8.4 with the two global
    directives this file's template carries: TCP 443 and nothing else.

    ``certificate`` is the PEM the control plane pushed, and it is the text rather than
    the path so that the rendered site changes when the certificate does — see the
    template, where the digest of it is written as a comment and the reason is the same
    one every other config digest in this zone exists for. The PATHS are constants and
    not parameters, exactly as ``directory`` is: they are where
    ``place_delivery_certificate`` writes, and a site pointed anywhere else would be a
    site reading a file nothing puts there.

    WHETHER THERE IS TLS AT ALL IS READ OFF THE ADDRESS and is not a second argument.
    An ``http://`` address is Caddy's own way of saying "no TLS here" and it refuses a
    ``tls`` directive under one; anything else is served under the placed certificate.
    Two arguments could disagree, and the disagreement would be a listener that will
    not start or — worse — one that starts and serves a name it holds no certificate
    for. So a certificate with an ``http://`` address is refused here, and so is an
    address without one.

    ``headers`` go on every response that carries a document, and ``shape_headers`` adds
    to them for one shape — the archive's ``Content-Disposition``, in the one caller this
    is written for. Both are the CONTROL PLANE's: its route decides what a subscription
    response carries (``control/app/api/delivery.py``), and a document served from two
    hosts under two policies is two different answers to one link.

    THEY DO NOT GO ON A 404, and that is not a saving. A fixed set of headers on an empty
    body is a signature every delivery host would answer with, on the most scannable host
    in the fleet — the argument `CLAUDE.md` makes about a shared decoy destination, one
    layer up. What a refusal here matches is the bare 404 the control plane's PUBLIC SITE
    gives anything that is not a subscription (``deploy/caddy/Caddyfile``), and it
    deliberately does not match that host's own ``/sub/`` refusal: measured on 2026-09-26,
    an unknown token there comes back with five headers the application's middleware adds,
    so answering like it would mean answering with the header set that identifies a hashi
    control plane. Either way an unknown NAME and a path that is not a subscription are
    answered identically here, which is the property that keeps a scanner from learning
    which names exist.

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
    serves_tls = not site_address.startswith(_WITHOUT_TLS)
    if serves_tls and certificate is None:
        raise UnservableSite(
            f"{site_address!r} is served over TLS and no certificate was given for it "
            "— a site with a name is answered on the HTTPS port, and a listener with "
            "nothing to answer a handshake with is one every client refuses. Give the "
            f"certificate this host was pushed, or ask for {_WITHOUT_TLS}"
        )
    if not serves_tls and certificate is not None:
        raise UnservableSite(
            f"{site_address!r} is an {_WITHOUT_TLS} address and a certificate was "
            "given for it — the daemon refuses a certificate on a site it is told to "
            "serve without TLS, so one of the two is not what was meant"
        )
    per_shape = shape_headers or {}
    return _TEMPLATES.get_template("delivery-site.Caddyfile.j2").render(
        site_address=site_address,
        directory=DELIVERY_DIR,
        certificate_digest=digest_of(certificate) if certificate else "",
        certificate_path=DELIVERY_CERTIFICATE_PATH,
        certificate_key_path=DELIVERY_CERTIFICATE_KEY_PATH,
        # Sorted by the format's own value, so two fleets rendering the same shapes
        # render the same file. The default shape is passed separately because it gets
        # a SECOND block for a format that already has one above — a different matcher
        # name (two Caddy matchers may not share one) and a different condition: that
        # block answers a request carrying no ``format`` at all, and only that.
        shapes=[
            _shape(shape, {**headers, **per_shape.get(shape, {})})
            for shape in sorted(ARTIFACT_EXTENSION, key=lambda one: one.value)
        ],
        default_shape=_shape(
            DEFAULT_SHAPE,
            {**headers, **per_shape.get(DEFAULT_SHAPE, {})},
            matcher=_NO_SHAPE_NAMED,
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
    default — is captured by the engine and kept for that container, where nobody is
    watching for a subscription identifier to appear. ``driver: none`` is the only
    setting under which there is nothing to retain. It costs the operator this
    container's startup diagnostics, which is a real cost and the smaller one: those
    are recoverable by running the image by hand on the node, and a request line in a
    journal is not recoverable at all.

    WHETHER THE CERTIFICATE IS MOUNTED IS READ OUT OF THE SITE, not asked for. A bind
    mount of a path nothing placed does not fail — the engine creates a DIRECTORY there
    and mounts that over the file, which is the trap ``deploy/docker/caddy.Dockerfile``
    was written to escape — so mounting the certificate unconditionally would turn a
    site that wants no certificate into two directories on the node and a listener that
    will not start. The alternative, a second argument saying what the site was
    rendered with, is two values that can disagree about one file; reading the rendered
    text is the same text ``digest_of`` above already consumes, and it cannot.
    """
    mounted = [DELIVERY_SITE_PATH]
    if _TLS_DIRECTIVE in site:
        mounted += [DELIVERY_CERTIFICATE_PATH, DELIVERY_CERTIFICATE_KEY_PATH]
    return {
        "name": DELIVERY_SERVICE,
        "image": DELIVERY_IMAGE,
        "command": list(DELIVERY_COMMAND),
        "config_digest": digest_of(site),
        "directory": DELIVERY_DIR,
        "mounted": mounted,
    }


async def place_delivery_site(connection: NodeConnection, *, site: str) -> None:
    """Put the rendered site configuration on the node.

    0600 and outside the delivery directory, for the two reasons the constants above
    give. It holds no secret — an address and a set of response headers — and the mode
    is the one every file this package places carries, rather than an exception someone
    would have to justify.
    """
    await connection.write_file(DELIVERY_SITE_PATH, site, mode=0o600)


async def place_delivery_certificate(
    connection: NodeConnection, *, certificate: str, key: str
) -> None:
    """Put the certificate this host serves under, and its private key, on the node.

    The KEY IS THE ONE FILE THIS PACKAGE PLACES THAT IS NOT THIS HOST'S OWN SECRET, and
    that is worth saying here rather than only in the decision record. Every other
    private key a node holds belongs to that node: a seizure yields the transport
    material of the host that was seized and nothing about any other. This one is
    issued for a name, and whoever holds it can answer for that name from anywhere
    until it expires. What the fleet accepts by pushing it, and what bounds the damage,
    is ``docs/decisions.md`` under 2026-09-27 — named here and not paraphrased, because
    this package cannot see that decision change.

    Both files together and in this order, certificate first: a listener recreated
    between the two writes would find a certificate that does not match its key and
    refuse every handshake, which is the same outage either way, while the reverse
    order can leave a key on a host that never gets its certificate.

    0600 on both, which is the mode every file this package places carries. The
    container runs as root and reads them through a read-only bind mount; the account
    the control plane drives the node as is the only other reader.
    """
    await connection.write_file(DELIVERY_CERTIFICATE_PATH, certificate, mode=0o600)
    await connection.write_file(DELIVERY_CERTIFICATE_KEY_PATH, key, mode=0o600)


# Taking the listener's own files off a host, which is not ``delivery.remove_delivery``
# and is deliberately a second call rather than an extension of that one. That function
# answers about the pushed MATERIAL — the directory, and whether the host was holding
# one — and this is about the three files that make a host answer for a name at all.
# They are this module's paths, so they are removed by this module; the caller makes
# both calls, in the one place that knows a host has stopped serving delivery.
#
# THE PRIVATE KEY IS WHY THIS EXISTS. A host that stops being a delivery host and keeps
# its artifacts is holding documents its own users already had; one that keeps this key
# is holding the ability to answer for the delivery name, on a box the fleet has
# stopped driving and may have stopped watching.
#
# ``rm -f`` and never a ``mkdir``: like the removal beside it, this must be legal on a
# host ``node_stack.prepare`` has never touched, and a path that is not there is not a
# failure.
_REMOVE_SITE = (
    f"rm -f {DELIVERY_SITE_PATH} {DELIVERY_CERTIFICATE_PATH} "
    f"{DELIVERY_CERTIFICATE_KEY_PATH}"
)


async def remove_delivery_site(connection: NodeConnection) -> None:
    """Take the site configuration, the certificate and its key off the node.

    It does not stop a container, and does not need to: the listener is one service in
    the node's rendered compose file, so a host that is no longer a delivery host is
    handed a compose file without it and ``node_stack.restart`` — which runs with
    ``--remove-orphans`` — takes the container away. What is left after that is the
    files, and this is them.

    Says nothing about what it found, unlike ``delivery.remove_delivery``. That one's
    answer becomes a sentence an operator reads, because a directory of other people's
    rendered subscriptions disappearing is a change worth naming; these three are this
    product's own scaffolding and their removal is not news.
    """
    await connection.run(_REMOVE_SITE)
