"""One link, two hosts, one answer — M27.3.

WHAT: holds the site configuration a delivery host serves
      (``edge.bootstrap.delivery_site``) against the route the control plane serves the
      same document from (``control.app.api.delivery``).
WHY:  a subscription URL is the only artefact a user holds, and from M27 there is more
      than one host that can answer one. The two answers are written in two zones that
      cannot import each other — `edge` may not import `control`, and nothing in `edge`
      may learn what a subscription contains — so what keeps them from drifting is a
      test that imports both, and this is it. The header set is the sharpest half:
      ``no-store`` is what keeps a bearer-credential body out of somebody else's cache,
      and a delivery host that lost it would be a leak nothing else would report.
HOW:  the control plane's own constants are passed to the renderer, which is how the
      caller M27.4 writes will pass them — the renderer holds no copy of them and
      invents nothing, so the only thing that can drift is a caller that stops passing
      them.

Boundary: text only. That Caddy applies these headers, and that the control plane does,
is asked of running processes in ``tests/e2e/infra/`` and ``tests/e2e/control/``.
"""

import inspect

from control.app.api.delivery import (
    ARCHIVE_FILENAME,
    DELIVERY_HEADERS,
    deliver_subscription,
)
from control.app.api.delivery import router as delivery_router
from edge.bootstrap import delivery_site
from edge.registry import SubscriptionFormat

# What a caller hands the renderer, in one place so every assertion below is about the
# same rendering the control plane would ask for.
SITE = delivery_site.render_delivery_site(
    site_address="sub.example.test",
    headers=DELIVERY_HEADERS,
    shape_headers={
        SubscriptionFormat.CLIENT_CONFIG_FILE: {
            "Content-Disposition": f'attachment; filename="{ARCHIVE_FILENAME}"'
        }
    },
)


def test_a_delivery_host_sets_every_header_the_control_plane_sets() -> None:
    """All of them, by name and by value.

    The same document served from two hosts under two cache policies is two different
    answers to one link, and the one that is wrong is the one nobody tested.
    """
    for name, value in DELIVERY_HEADERS.items():
        assert f"{name} `{value}`" in SITE, (
            f"a delivery host does not set {name!r} the way the control plane's own "
            f"route does:\n{SITE}"
        )


def test_the_archive_is_saved_under_the_name_that_identifies_nobody() -> None:
    """The control plane's fixed filename, on the host where it matters more.

    Without it a browser saves the file under the request's own last path segment —
    which on a delivery host is the artifact's name, and the artifact's name is how that
    artifact is fetched. That would put a credential in a downloads folder.
    """
    assert f'filename="{ARCHIVE_FILENAME}"' in SITE


def test_both_hosts_answer_the_same_route() -> None:
    """A subscription URL differs between hosts in its NAME and in its host, never in
    its route: a client that has to be told which of the two it is talking to is a
    client this product cannot update.

    Read off the registered route rather than written down twice, which is the whole
    point of this file.
    """
    routes = [one.path for one in delivery_router.routes]
    assert routes == [f"{delivery_site.SUBSCRIPTION_PATH}{{token}}"], routes


def test_both_hosts_answer_a_query_less_request_with_the_same_shape() -> None:
    """The link a user already holds carries no ``format``, and the two hosts must not
    disagree about what that means."""
    declared = inspect.signature(deliver_subscription).parameters["subscription_format"]
    assert declared.default.default is delivery_site.DEFAULT_SHAPE, (
        "the shape a delivery host answers a request with no format with is not the one "
        "the control plane's own route defaults to"
    )
