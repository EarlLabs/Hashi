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
run says the configuration is right, never that a delivery host is reachable — nothing
in this repository wires this listener onto one yet.
"""

import pytest

from edge.bootstrap import delivery_site, node_stack
from edge.bootstrap.delivery import ARTIFACT_EXTENSION, ARTIFACT_NAME, DELIVERY_DIR
from edge.bootstrap.node_stack import CONFIG_DIR
from edge.registry import SubscriptionFormat

# A site address of the shape a caller will pass once something decides one. A name,
# because that is what M27.6 says a delivery host needs and what a public CA can issue
# for; nothing in this zone chooses it.
ADDRESS = "sub.example.test"

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
    captured by the container runtime and kept in the node's journal whatever the
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
    """No hostname, no port and no country in this zone's own text (CLAUDE.md)."""
    site = a_site()
    assert ADDRESS in site
    assert site.count(ADDRESS) == 1, site
    without = site.replace(ADDRESS, "")
    assert ":" not in without.split("root *")[0].replace("http", ""), (
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
