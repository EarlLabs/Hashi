"""The panel loads from this host alone, proven against the booted stack.

WHAT: every page AND every fragment of the console is fetched, every asset it
      references is followed, and every reference found on the way — in HTML and
      inside the stylesheets — is required to be same-origin.
WHY:  ``docs/decisions.md`` decision 7, and it is the only part of M8 a test can hold.
      Three separate reasons, each sufficient on its own: ``base.html`` already refused
      a CDN for HTMX because *"the panel must work on a network where the CDN is
      blocked, which is the same network the operator uses to fix a blocked node"*; M7
      put the console behind a management tunnel where a request to the open internet
      may have no route at all; and a font fetched from a US company announces every
      time the owner opens their VPN console.
HOW:  follow what the panel actually serves, rather than reading the templates —
      ``tests/control/test_the_panel_is_self_contained.py`` is the source-level half
      and this is the runtime one. They fail differently: a template that stops being
      rendered still passes the source check and would drop out of this one, and a
      stylesheet vendored into the image but not into the repository would pass the
      source check and fail here.

      THE LIST IS THE TEST. A surface that is not fetched is not checked, and this
      scenario shipped once with only its four navigable pages on it — so a reference
      planted in the subscription-link dialog, the single most sensitive fragment in
      the panel, was caught by the source scan and invisible here. Every new screen,
      dialog or self-refreshing table goes into ``PANEL_PAGES``, ``PANEL_FRAGMENTS``
      or the ``surfaces`` fixture in the same change that adds it.

Boundary: real control + postgres + caddy. It proves the DOCUMENTS reference nothing
external. It does not prove a browser made no request — no browser runs here — which
is why the same claim is also walked with the machine's outbound network cut during
acceptance.
"""

import re
import uuid

import pytest

OPERATOR = {"username": "owner", "password": "e2e-operator-password"}

# Whole documents the browser navigates to.
PANEL_PAGES = (
    "/panel/login",
    "/panel/",
    "/panel/friends",
    "/panel/nodes",
    "/panel/hops",
    # M9.3's, added in the change that added the screen. It has no fragment of its own:
    # nothing this panel can do changes which protocols the image ships, so the whole
    # screen is one document and there is no refresh URL to list.
    "/panel/transports",
    "/panel/fleet",
)

# The FRAGMENTS the console swaps in — dialogs and self-refreshing tables. They are
# on this list for the reason the whole scenario exists: a fragment is rendered from
# its own template, is never navigated to, and is therefore where a third-party
# reference survives longest before anyone looks at it. Leaving them off is exactly
# how this scenario would have passed while the panel's most sensitive dialog fetched
# a font from a stranger.
#
# The two that need a friend are parameterised and built by ``surfaces`` below. The
# POST routes are deliberately absent: they render these same templates through
# panel/mutation_result.html, and a scenario that mutated the stand to re-read a
# template it has already read would buy nothing and cost determinism.
PANEL_FRAGMENTS = (
    "/panel/friends/new",
    "/panel/friends/table",
    "/panel/overview/body",
    # M9.1's two, added in the change that added the screen — which is the rule this
    # list exists to enforce.
    "/panel/nodes/new",
    "/panel/nodes/table",
    # M9.2's, same rule. The establish-hop dialog is the largest fragment in the
    # console — three questions and twenty-two tuning boxes — and every one of those
    # boxes carries text this panel did not write, which is exactly the kind of
    # surface a third-party reference survives longest in.
    "/panel/hops/new",
    "/panel/hops/table",
)

# Anything that is not a path on this host. A scheme-relative URL is included on
# purpose: `//fonts.example/x` reads like a path and is fetched from another host,
# which makes it the form this rule dies of.
EXTERNAL = re.compile(r"^\s*(?:[a-z][a-z0-9+.-]*:)?//", re.I)

# Schemes that fetch nothing over the network and are therefore not a third party.
INERT_SCHEMES = ("data:", "mailto:", "#", "javascript:void")


@pytest.fixture
def unique() -> str:
    """A per-run suffix, so a re-run against a warm stack does not collide."""
    return uuid.uuid4().hex[:8]


@pytest.fixture
async def operator(client):
    response = await client.post("/panel/login", data=OPERATOR)
    assert response.status_code == 303, (
        f"the operator could not log in ({response.status_code}) — check "
        "deploy/e2e.env against deploy/docker-compose.e2e.yml"
    )
    return client


@pytest.fixture
async def surfaces(operator, unique: str) -> list[str]:
    """Every panel URL that renders markup, including the two that need a friend.

    A real friend and a real node are created because the two most interesting
    fragments do not exist without them: the subscription-link dialog and the node
    page. The stand is disposable and this run's rows are suffixed, so they cannot
    collide with another scenario's.

    NOTE what this fixture does NOT do: it never reads the friend's subscription URL.
    The id is enough to address the dialog, and the token stays where it belongs.
    """
    friend = await operator.post("/api/friends", json={"nickname": f"styles-{unique}"})
    assert friend.status_code == 201, friend.text
    friend_id = friend.json()["id"]

    node = await operator.post(
        "/api/nodes",
        json={
            "name": f"styles-{unique}",
            "address": "192.0.2.60",
            "location_label": f"Testland-{unique}",
        },
    )
    assert node.status_code == 201, node.text

    return [
        *PANEL_PAGES,
        *PANEL_FRAGMENTS,
        # The link dialog — the one fragment in the console that displays a live
        # bearer credential, and therefore the one whose markup matters most.
        f"/panel/friends/{friend_id}/subscription",
        f"/panel/friends/{friend_id}/revoke",
        # The pre-redesign node page. Still part of the panel until M9.6 retires it,
        # and it carries an inline script of its own.
        f"/panel/nodes/{node.json()['id']}",
        # The tear-down confirmation, which needs a whole hop behind it.
        *await _with_a_hop(operator, unique),
    ]


async def _with_a_hop(operator, unique: str) -> list[str]:
    """The tear-down dialog, and the two nodes and the hop it does not exist without.

    Its own helper because a hop is the most expensive surface on this list to reach —
    two nodes and a validated parameter block for each end — and the alternative was to
    leave it off, which is the omission this whole scenario was written about.
    """
    transports = (await operator.get("/api/transports")).json()
    carrier = sorted(
        transport["name"]
        for transport in transports
        if transport["hop_capable"] and not transport["subscription_expressible"]
    )
    if not carrier:  # pragma: no cover - an image with no hop-capable transport
        return []

    ends = []
    for role, address in (("hop-entry", "192.0.2.61"), ("hop-exit", "192.0.2.62")):
        created = await operator.post(
            "/api/nodes",
            json={
                "name": f"{role}-{unique}",
                "address": address,
                "location_label": f"Testland-{unique}-{role}",
            },
        )
        assert created.status_code == 201, created.text
        ends.append(created.json()["id"])

    def side(address: str, peer: str) -> dict:
        return {
            "port": 51820,
            "tunnel_address": address,
            "peer_tunnel_address": peer,
            "mtu": 1280,
            "junk_packet_count": 4,
            "junk_packet_min_size": 40,
            "junk_packet_max_size": 80,
            "init_packet_magic_header": 1020327352,
            "response_packet_magic_header": 2060487442,
            "underload_packet_magic_header": 3679305607,
            "transport_packet_magic_header": 1436947798,
        }

    hop = await operator.post(
        "/api/hops",
        json={
            "entry_node_id": ends[0],
            "leaf_node_id": ends[1],
            "transport_name": carrier[0],
            "entry_params": side("10.77.0.1/24", "10.77.0.2/24"),
            "leaf_params": side("10.77.0.2/24", "10.77.0.1/24"),
        },
    )
    assert hop.status_code == 201, hop.text
    return [f"/panel/hops/{hop.json()['entry']['id']}/tear-down"]


def without_comments(text: str, *, css: bool = False) -> str:
    """The document as a BROWSER reads it, with comments removed.

    Not a loophole: a browser fetches nothing out of a comment. It is necessary
    because this repository explains its decisions where they are made, and the
    vendored stylesheet's header quotes the very ``@import`` decision 7 deleted — so
    a scanner that read comments would report the removal itself as the violation,
    and a test that cries wolf gets deleted.
    """
    if css:
        return re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def references_in_html(document: str) -> list[str]:
    """Every URL an HTML document would make the browser fetch or follow.

    Hand-parsed rather than with a DOM library: adding a dependency to `control`'s
    test path is an architect decision, and what is needed here is a list of
    attribute values, not a tree.
    """
    document = without_comments(document)
    found = re.findall(
        r'\b(?:src|href|action|poster|srcset|data-src)\s*=\s*"([^"]*)"', document
    )
    # Inline <style> blocks are documents of their own and get the same treatment.
    for block in re.findall(r"<style[^>]*>(.*?)</style>", document, re.S):
        found.extend(references_in_css(block))
    return found


def references_in_css(sheet: str) -> list[str]:
    """Every URL a stylesheet would make the browser fetch — url() and @import."""
    sheet = without_comments(sheet, css=True)
    return [
        *re.findall(r"url\(\s*['\"]?([^'\")]+)", sheet),
        *re.findall(r"@import\s+url\(\s*['\"]?([^'\")]+)", sheet),
        *re.findall(r"@import\s+['\"]([^'\"]+)", sheet),
    ]


def offenders(references: list[str]) -> list[str]:
    """The ORIGINS that leave this host, with every path and query stripped.

    Origins and not whole URLs, deliberately, and this is a rule for anything added
    to this file. The surfaces below include the subscription-link dialog, which
    carries a live bearer credential — so a failure message that echoed a matched URL
    could put a friend's token into a CI log, which would be a worse defect than the
    one this scenario closes. An origin names the third party, which is the entire
    actionable content of the finding; the path adds nothing an operator needs.
    """
    leaking = {
        _origin_of(reference)
        for reference in references
        if EXTERNAL.match(reference)
        and not reference.lower().startswith(INERT_SCHEMES)
    }
    return sorted(leaking)


def _origin_of(url: str) -> str:
    """``https://fonts.example/css2?x=y`` -> ``https://fonts.example``."""
    stripped = url.strip()
    scheme, _, rest = stripped.partition("//")
    return f"{scheme}//{rest.split('/', 1)[0]}"


async def test_no_panel_surface_references_another_origin(operator, surfaces) -> None:
    """Every page AND every fragment — the dialogs and the self-refreshing tables.

    The fragments are the half this scenario was missing when it was written. A
    dialog is rendered from its own template and is never navigated to, so a
    third-party reference planted in one is invisible to any check that only walks
    pages — including, before this, the link dialog.

    Only the URL is named on failure, never the response body: one of these surfaces
    is a live subscription URL.
    """
    for surface in surfaces:
        response = await operator.get(surface)
        assert response.status_code == 200, f"{surface} answered {response.status_code}"

        leaking = offenders(references_in_html(response.text))
        assert leaking == [], (
            f"{surface} points the browser at another host: {leaking}. The panel must "
            "load from this host alone — docs/decisions.md, decision 7."
        )


async def test_every_stylesheet_the_panel_links_is_served_here_and_stays_here(
    operator, surfaces
) -> None:
    """Follow the links, not the templates.

    A stylesheet is where this rule actually died in the design handoff — the
    ``@import`` on line 2 of the design system, which no reading of the HTML would
    ever have found.
    """
    sheets = set()
    for surface in surfaces:
        document = (await operator.get(surface)).text
        sheets.update(
            re.findall(r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"', document)
        )

    assert sheets, "the console links no stylesheet at all, so this proves nothing"

    for sheet in sorted(sheets):
        assert not EXTERNAL.match(sheet), sheet
        response = await operator.get(sheet)
        assert response.status_code == 200, f"{sheet} is linked but answers {response.status_code}"

        leaking = offenders(references_in_css(response.text))
        assert leaking == [], (
            f"{sheet} fetches from another host: {leaking}. Decision 7 removed exactly "
            "one of these and authorised exactly one download to replace it."
        )


async def test_every_font_the_panel_declares_is_served_by_this_host(operator) -> None:
    """A self-hosted @font-face pointing at nothing falls back silently.

    Asserted on the bytes rather than on a status code: a stack that answers every
    unknown path with an HTML error page would give a cheerful 200 for a font that is
    not there, and the panel would merely look a little wrong.
    """
    faces = references_in_css((await operator.get("/static/fonts.css")).text)
    assert len(faces) >= 10, faces

    for face in faces:
        assert face.startswith("/static/"), face
        response = await operator.get(face)
        assert response.status_code == 200, f"{face} is declared but answers {response.status_code}"
        assert response.content[:4] == b"wOF2", f"{face} is not a woff2 file"


async def test_the_login_screen_is_clean_before_anyone_signs_in(client) -> None:
    """The first document the panel ever serves, fetched with no session at all.

    Its own test because it is the one page an operator reaches when everything else
    is broken, and because it is served by a different router — a page that skipped
    the session dependency could just as easily have skipped this rule.
    """
    response = await client.get("/panel/login")

    assert response.status_code == 200
    assert offenders(references_in_html(response.text)) == []
