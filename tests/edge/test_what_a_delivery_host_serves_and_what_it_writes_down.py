"""The listener a delivery host runs — M27.3.

WHAT: what ``edge.bootstrap.delivery_site`` renders: the site configuration that serves
      a node's placed delivery directory, and the compose service that runs it.
WHY:  a request to that listener carries the NAME of one person's artifact, and under
      the route M27.3 took the name is how the artifact is fetched — so a record of one
      is a record of a credential, on the host in the fleet whose logs nobody reads.
      Every logger the rendered file can reach is discarded, the container runtime is
      told to retain nothing, and those are the properties asserted here rather than
      described in a comment.
HOW:  rendering is pure, so this is all offline. That the file is VALID, that Caddy
      serves what it says and that nothing lands in the container log is a real engine's
      answer and is asked in ``tests/e2e/infra/``; what is asked here is that the text
      says what it must and refuses what it must.

Boundary: nothing here starts a container, opens a socket or reaches a node. A green
run says the configuration is right, never that a delivery host is reachable: no name
is rendered here, and a node runs this only once something passes the compose service
to ``render_compose`` and places the file.
"""

import pytest

from edge.bootstrap import delivery_site, node_stack
from edge.bootstrap.delivery import ARTIFACT_EXTENSION, ARTIFACT_NAME, DELIVERY_DIR
from edge.bootstrap.node_stack import CONFIG_DIR
from edge.registry import Layer4, SubscriptionFormat

# A site address of the shape a delivery host is given. A name, because that is what a
# public CA can issue for and what M27.6 settled a delivery host is reached under;
# nothing in this zone chooses it.
ADDRESS = "sub.example.test"

# Stands in for the certificate the control plane pushes. It is never parsed here — the
# renderer writes its digest into the site and the daemon reads the FILE, not this text
# — so a fake is the honest fixture, and a real certificate in a repository is a habit
# this zone does not have.
CERTIFICATE = "-----BEGIN CERTIFICATE-----\nnot-a-certificate\n-----END CERTIFICATE-----\n"

# The response headers the control plane's own route sets. Passed in rather than
# imported: `edge` may not import `control`, and the two are held together by
# ``tests/control/test_a_delivery_host_answers_like_the_control_plane.py``.
HEADERS = {"Cache-Control": "no-store, max-age=0", "X-Frame-Options": "DENY"}
ARCHIVE_HEADERS = {"Content-Disposition": 'attachment; filename="hashi-configs.zip"'}


def a_site(**overrides) -> str:
    settings: dict = {
        "site_address": ADDRESS,
        "headers": HEADERS,
        "shape_headers": {SubscriptionFormat.CLIENT_CONFIG_FILE: ARCHIVE_HEADERS},
        "certificate": CERTIFICATE,
    }
    settings.update(overrides)
    return delivery_site.render_delivery_site(**settings)


# --- what it records, which is the step ---------------------------------------------


def test_every_logger_in_the_rendered_site_is_discarded() -> None:
    """Both of them, and the count is the assertion.

    Caddy has two that can write a request URI: the site's own, and the DEFAULT one,
    which catches everything matching no site block plus every log.error. The same pair
    the control plane's own Caddyfile silences, on a host that is further away.
    """
    site = a_site()
    assert site.count("log {") == 2, site
    assert site.count("output discard") == 2, (
        "a logger in the rendered delivery site is not discarded, so a request path can "
        f"be written down on a delivery host:\n{site}"
    )


def test_the_rendered_site_opens_no_admin_socket() -> None:
    """Caddy binds an admin API unless told not to, and a node has no use for one."""
    assert "admin off" in a_site()


def test_the_delivery_container_keeps_no_log_at_all() -> None:
    """The half the site configuration cannot cover: what the ENGINE retains.

    A process that prints anything — a panic, a configuration it will not load — is
    captured by the container runtime and kept for that container whatever the
    application believes about its own logging. ``driver: none`` is the only setting
    under which there is nothing to keep.
    """
    compose = node_stack.render_compose(
        transports=[], delivery=delivery_site.compose_service(site=a_site())
    )
    assert "driver: none" in compose, compose
    # Rendered with no transports, so the only logging directive in the file is the
    # listener's — the data planes above it keep their own bounded json-file.
    assert "driver: json-file" not in compose, (
        "the delivery container is on a log driver that retains what it prints:\n"
        f"{compose}"
    )


# --- what it serves ------------------------------------------------------------------


@pytest.mark.parametrize("shape", sorted(ARTIFACT_EXTENSION, key=lambda one: one.value))
def test_every_subscription_shape_is_served_under_its_own_query(
    shape: SubscriptionFormat,
) -> None:
    """One block per FORMAT, off the same table the push writes the files with.

    A format added later is served by arriving, and a transport added later adds
    nothing here at all — which is the property that keeps a protocol's name out of
    this file.
    """
    site = a_site()
    assert f"query format={shape.value}" in site, site
    assert ARTIFACT_EXTENSION[shape] in site, (
        f"the {shape.value} shape is matched but no block rewrites to its suffix, so "
        f"the file the push wrote is not the file a request would ask for:\n{site}"
    )


def test_a_request_naming_no_shape_is_served_the_one_a_held_link_asks_for() -> None:
    """A link a user already holds carries no query, and must still be answered."""
    site = a_site()
    assert "not query format=*" in site, site
    assert ARTIFACT_EXTENSION[delivery_site.DEFAULT_SHAPE] in site


def test_the_path_it_accepts_is_the_rule_this_zone_places_a_name_under() -> None:
    """Derived from ``ARTIFACT_NAME`` rather than copied beside it.

    The drift that matters runs one way: a listener accepting less than
    ``place_delivery`` writes would 404 artifacts that are sitting on the node's disk,
    and nothing anywhere would say so.
    """
    inner = ARTIFACT_NAME.pattern.removeprefix("^").removesuffix("$")
    assert f"^/sub/({inner})$" in a_site()


def test_it_serves_the_placed_directory_and_not_the_config_directory() -> None:
    """Two properties in one line, and the second is the one with teeth.

    ``conf`` holds every transport's server configuration — node keys included — and is
    bind-mounted into every data-plane container. A file server rooted there would
    publish it.
    """
    site = a_site()
    assert f"root * {DELIVERY_DIR}" in site
    assert CONFIG_DIR not in site, (
        f"the delivery site names the node's config directory:\n{site}"
    )


def test_the_site_holds_no_address_but_the_one_it_was_given() -> None:
    """No hostname, no port and no country in this zone's own text (CLAUDE.md).

    Asked of the DIRECTIVES and not of the whole file: a colon in a comment is prose and
    a colon in a directive is a port or a scheme. The earlier form read the text up to
    ``root *``, which put every explanatory line above it inside the assertion and made
    the rule impossible to state in a sentence.
    """
    site = a_site()
    assert ADDRESS in site
    assert site.count(ADDRESS) == 1, site
    directives = [
        line
        for line in site.replace(ADDRESS, "").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert not [line for line in directives if ":" in line], (
        f"something in the rendered site names a port or a scheme of its own:\n{site}"
    )


# --- what it refuses -----------------------------------------------------------------


@pytest.mark.parametrize(
    "address",
    [
        "sub.example.test {\n\trespond 200\n}",
        "sub.example.test\n\nother.example.test",
        "sub.example.test`",
        "",
    ],
)
def test_an_address_that_could_be_read_as_more_than_one_directive_is_refused(
    address: str,
) -> None:
    """The whole file is a structure, and this is the part a caller chooses."""
    with pytest.raises(delivery_site.UnservableSite):
        a_site(site_address=address)


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Thing\n\tlog": "value"},
        {"X-Thing": "value`\n}\n"},
        {"X-Thing": "value`"},
        {"X-Thing": ""},
    ],
)
def test_a_header_that_could_end_the_block_it_sits_in_is_refused(headers: dict) -> None:
    with pytest.raises(delivery_site.UnservableSite):
        a_site(headers=headers)


def test_no_header_of_ours_is_set_on_a_refusal() -> None:
    """A fixed header set on an empty 404 is a signature every delivery host answers
    with, on the most scannable host in the fleet — the argument CLAUDE.md makes about a
    shared decoy destination, one layer up.

    Each shape's headers are guarded by a ``file`` matcher, so they reach a response that
    carries a document and nothing else; the catch-all answers a bare ``respond 404``.
    What that matches is the control plane's PUBLIC site, which answers everything that
    is not a subscription with a bare 404 — and not the control plane's own ``/sub/``
    route, whose refusal was measured on 2026-09-26 carrying five headers its middleware
    adds. Matching that one would mean every delivery host answered a scan with the
    header set that identifies a hashi control plane.
    """
    site = a_site()
    refusal = site.rsplit("handle {", 1)[1]
    assert "header" not in refusal, (
        f"the catch-all refusal sets a header of ours:\n{refusal}"
    )
    for name in HEADERS:
        # Once per shape block and never outside one. Three blocks: the two formats and
        # the request that names no format.
        assert site.count(f"{name} `") == 3, site


def test_the_headers_are_set_only_where_the_artifact_is_really_there() -> None:
    """The ``file`` matcher is what makes the assertion above true of an unknown NAME.

    Without it the headers would land on `file_server`'s own 404 — so a name that exists
    and a name that does not would be answered differently, which is the one thing a
    delivery host must not disclose.

    EVERY BLOCK, including the one for a request that names no shape at all. That is the
    block a URL a user already holds actually reaches, and it is a second block for a
    format the loop below has already covered under another matcher name — so a version
    of this test built from ``ARTIFACT_EXTENSION`` alone stayed green with the guard
    deleted from exactly the block that answers real traffic.
    """
    site = a_site()
    guarded = {
        delivery_site._matcher_for(shape): extension
        for shape, extension in ARTIFACT_EXTENSION.items()
    }
    guarded[delivery_site._NO_SHAPE_NAMED] = ARTIFACT_EXTENSION[
        delivery_site.DEFAULT_SHAPE
    ]
    for matcher, extension in guarded.items():
        assert f"@present_{matcher} file /{{re.{matcher}.1}}{extension}" in site, site
        assert f"header @present_{matcher} {{" in site, site


def test_a_header_that_would_answer_with_the_request_itself_is_refused() -> None:
    """Braces, and this one is not about quoting at all.

    Caddy resolves a placeholder inside a quoted token too, so a value naming one would
    put whatever it names into a header of every response — and the request URI is the
    artifact's name.
    """
    with pytest.raises(delivery_site.UnservableSite):
        a_site(headers={"X-Thing": "{http.request.uri}"})


def test_a_header_carrying_a_quoted_filename_is_accepted() -> None:
    """The red half of the rule above: the one value this is written for has quotes in
    it, and refusing it would make the archive save under a per-subscription name."""
    assert 'filename="hashi-configs.zip"' in a_site()


# --- the service that runs it ---------------------------------------------------------


def test_a_node_without_a_delivery_listener_renders_what_it_always_did() -> None:
    """The listener is an addition, and a node that is not a delivery host gets none.

    Byte for byte, because a compose file that differed would recreate every container
    on the next apply on a node this step was not supposed to touch.
    """
    transports = node_stack.services_for({"vless-reality": "{}"})
    assert node_stack.render_compose(transports=transports) == node_stack.render_compose(
        transports=transports, delivery=None
    )


def test_a_changed_site_is_a_changed_service_definition() -> None:
    """M1, in a second container.

    ``up -d`` compares the service definition and a bind-mounted file's contents are not
    part of one, so without the digest label a host handed a changed site would go on
    serving the previous one from a process that reads its configuration at start.
    """
    first = delivery_site.compose_service(site=a_site())
    second = delivery_site.compose_service(site=a_site(site_address="other.example.test"))
    assert first["config_digest"] != second["config_digest"]
    assert first["config_digest"] in node_stack.render_compose(
        transports=[], delivery=first
    )


def test_a_transport_cannot_take_the_listeners_own_service_name() -> None:
    """Two services of one name in a compose file are one service, silently.

    Which of the two survives is a YAML detail; either answer is a node missing
    something an apply reported it had placed.
    """
    transports = [{"name": delivery_site.DELIVERY_SERVICE, "config_path": "", "image": ""}]
    with pytest.raises(node_stack.UnrunnableTransport):
        node_stack.render_compose(
            transports=transports, delivery=delivery_site.compose_service(site=a_site())
        )


def test_the_listener_mounts_what_it_serves_read_only() -> None:
    """It has no reason to write, and the directory it reads is replaced by the next
    apply — a listener that could write into it would be writing into something with an
    owner."""
    compose = node_stack.render_compose(
        transports=[], delivery=delivery_site.compose_service(site=a_site())
    )
    assert f"- {DELIVERY_DIR}:{DELIVERY_DIR}:ro" in compose, compose
    assert f"- {CONFIG_DIR}" not in compose, (
        f"the delivery listener is given the node's config directory:\n{compose}"
    )


def test_the_site_configuration_is_placed_outside_the_directory_that_is_replaced() -> None:
    """``place_delivery`` replaces the whole delivery directory on every apply, so a
    configuration file inside it would be deleted by the next push."""
    assert not delivery_site.DELIVERY_SITE_PATH.startswith(f"{DELIVERY_DIR}/")


async def test_placing_the_site_writes_one_file_where_the_container_reads_it() -> None:
    """The only thing this module does to a node, against a connection that records.

    The path and the mode are the assertion: a site written anywhere else is a listener
    that starts on the configuration baked into its image, and one written world-readable
    is a habit this package does not have.
    """
    written: list[tuple[str, object, int]] = []

    class _Recorder:
        async def write_file(self, path, content, *, mode):
            written.append((path, content, mode))

    site = a_site()
    await delivery_site.place_delivery_site(_Recorder(), site=site)
    assert written == [(delivery_site.DELIVERY_SITE_PATH, site, 0o600)]


# --- one socket, and the certificate that fills it — M27.6 ---------------------------


def test_the_site_takes_one_socket_and_writes_no_port_to_take_it() -> None:
    """The measured answer to the port, pinned as text so it cannot be tidied away.

    A delivery host always carries a user-facing transport, so every socket this
    listener holds is one that transport cannot have. Measured on caddy 2.8.4 by reading
    the container's own /proc/net: without these two directives the same file binds TCP
    80, TCP 443 and UDP 443; with them, TCP 443 alone. The UDP one is the half no rule in
    this product could have caught — a port number is not a port, so an obfuscated tunnel
    on UDP 443 and this listener's HTTP/3 are two sockets to every check that exists.

    AND NO PORT IS WRITTEN. The site address is a bare name and the daemon's own defaults
    decide the socket, which is how the control plane's own `/sub/*` is already served.
    """
    site = a_site()
    assert "auto_https disable_redirects" in site
    assert "protocols h1 h2" in site
    assert ":443" not in site, site
    assert ":80" not in site, site


def test_a_named_site_is_served_under_the_certificate_the_control_plane_placed() -> None:
    """``tls`` names the two files the push writes, and nothing asks a CA for anything.

    The paths are constants rather than parameters for the reason the served directory
    is one: they are where ``place_delivery_certificate`` writes, and a site pointed
    anywhere else is a listener reading a file nothing puts there.
    """
    site = a_site()
    assert (
        f"tls {delivery_site.DELIVERY_CERTIFICATE_PATH} "
        f"{delivery_site.DELIVERY_CERTIFICATE_KEY_PATH}" in site
    ), site


def test_a_site_with_a_name_and_no_certificate_is_refused() -> None:
    """A name is answered on the HTTPS port, and a listener with nothing to answer a
    handshake with is one every client refuses — which reads to a user exactly like the
    block the endpoint exists to survive."""
    with pytest.raises(delivery_site.UnservableSite):
        a_site(certificate=None)


def test_a_certificate_on_a_site_asked_for_without_tls_is_refused() -> None:
    """The two would be saying different things about one file, and the daemon refuses a
    certificate on a site it is told to serve without TLS."""
    with pytest.raises(delivery_site.UnservableSite):
        a_site(site_address="http://:8080")


def test_a_site_asked_for_without_tls_renders_none() -> None:
    """The one caller that does this is a scenario, which cannot be given a name a public
    CA would issue for. Whether there is TLS is read off the address rather than asked
    for, so there is no second argument to disagree with it."""
    site = a_site(site_address="http://:8080", certificate=None)
    assert "tls " not in site, site
    assert delivery_site.DELIVERY_CERTIFICATE_PATH not in site


def test_a_renewed_certificate_is_a_changed_service_definition() -> None:
    """The fault this pins is the one the config digest exists for, one file over.

    Caddy reads a ``tls`` file once, at start. ``up -d`` compares the service definition
    and a bind-mounted file's contents are not part of one — so a host pushed a renewed
    certificate under an unchanged site would go on serving the expired one, from a
    container nothing recreated, with the apply reporting success.
    """
    renewed = CERTIFICATE.replace("not-a-certificate", "a-different-certificate")
    assert (
        delivery_site.compose_service(site=a_site())["config_digest"]
        != delivery_site.compose_service(site=a_site(certificate=renewed))["config_digest"]
    )


def test_the_certificate_is_mounted_exactly_where_the_site_names_one() -> None:
    """A bind mount of a path nothing placed does not fail — the engine creates a
    DIRECTORY there and mounts it over the file. So mounting unconditionally would turn
    a site that wants no certificate into two directories and a listener that will not
    start, and a site that wants one and does not get it is the same thing later."""
    served = node_stack.render_compose(
        transports=[], delivery=delivery_site.compose_service(site=a_site())
    )
    plain = node_stack.render_compose(
        transports=[],
        delivery=delivery_site.compose_service(
            site=a_site(site_address="http://:8080", certificate=None)
        ),
    )
    for path in (
        delivery_site.DELIVERY_CERTIFICATE_PATH,
        delivery_site.DELIVERY_CERTIFICATE_KEY_PATH,
    ):
        assert f"- {path}:{path}:ro" in served, served
        assert path not in plain, plain


def test_the_certificate_and_its_key_are_placed_outside_the_replaced_directory() -> None:
    """``place_delivery`` replaces the whole delivery directory on every apply, and its
    staging siblings are cleared by name. A key in either is a key the next push
    deletes, on a host whose listener then answers no handshake at all."""
    for path in (
        delivery_site.DELIVERY_CERTIFICATE_PATH,
        delivery_site.DELIVERY_CERTIFICATE_KEY_PATH,
    ):
        assert not path.startswith(f"{DELIVERY_DIR}/")
        assert not path.startswith(f"{DELIVERY_DIR}.")


async def test_placing_the_certificate_writes_both_files_unreadable_to_others() -> None:
    """Certificate first, so a listener recreated between the two writes never meets a
    key that belongs to a certificate it has not got."""
    written: list[tuple[str, object, int]] = []

    class _Recorder:
        async def write_file(self, path, content, *, mode):
            written.append((path, content, mode))

    await delivery_site.place_delivery_certificate(
        _Recorder(), certificate=CERTIFICATE, key="key"
    )
    assert written == [
        (delivery_site.DELIVERY_CERTIFICATE_PATH, CERTIFICATE, 0o600),
        (delivery_site.DELIVERY_CERTIFICATE_KEY_PATH, "key", 0o600),
    ]


async def test_the_removal_takes_the_private_key_off_the_host() -> None:
    """A host that stops being a delivery host and keeps its artifacts is holding
    documents its own users already had. One that keeps this key is holding the ability
    to answer for the delivery name, on a box nothing drives any more.

    And it creates nothing — like the material's own removal, it has to be legal on a
    host ``prepare`` has never touched.
    """
    ran: list[str] = []

    class _Recorder:
        async def run(self, command, check=True):
            ran.append(command)

    await delivery_site.remove_delivery_site(_Recorder())
    assert len(ran) == 1
    for path in (
        delivery_site.DELIVERY_SITE_PATH,
        delivery_site.DELIVERY_CERTIFICATE_PATH,
        delivery_site.DELIVERY_CERTIFICATE_KEY_PATH,
    ):
        assert path in ran[0]
    assert "mkdir" not in ran[0]


def test_the_declared_socket_is_the_one_a_rendered_site_actually_binds() -> None:
    """``DELIVERY_PORT`` exists so that something outside this zone can keep a transport
    off it, and a declaration nothing checks is a number that drifts from the daemon.

    It cannot be read out of the rendered file — the whole point is that no port is
    written there — so what is held here is the pair of directives that make the binding
    what the constant says, and the constant against the scheme it is the default for.
    A run of the real image behind the claim is in ``tests/e2e/infra/``.
    """
    assert delivery_site.DELIVERY_LAYER4 is Layer4.TCP
    assert delivery_site.DELIVERY_PORT == 443
    site = a_site()
    assert "auto_https disable_redirects" in site and "protocols h1 h2" in site
    directives = [
        line
        for line in site.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert not [
        line for line in directives if str(delivery_site.DELIVERY_PORT) in line
    ], site


def test_an_empty_certificate_is_refused_like_a_missing_one() -> None:
    """The guard is on TRUTH and not on ``None``, because the template is.

    An empty string would pass an ``is None`` guard and render a NAMED site with no
    ``tls`` directive — which Caddy answers by going to a certificate authority, the one
    thing this package's header says a node never does. Nothing in ``control`` produces
    one today; this is the contract this package offers any caller, and a contract that
    holds only for today's caller is not one.
    """
    with pytest.raises(delivery_site.UnservableSite):
        a_site(certificate="")
