"""The panel loads from this host alone, proven against the booted stack.

WHAT: every page of the console is fetched, every asset it references is followed,
      and every reference found on the way — in HTML and inside the stylesheets — is
      required to be same-origin.
WHY:  ``docs/decisions.md`` decision 7, and it is the only part of M8 a test can hold.
      Three separate reasons, each sufficient on its own: ``base.html`` already refused
      a CDN for HTMX because *"the panel must work on a network where the CDN is
      blocked, which is the same network the operator uses to fix a blocked node"*; M7
      put the console behind a management tunnel where a request to the open internet
      may have no route at all; and a font fetched from a US company announces every
      time the owner opens their VPN console.
HOW:  follow what the page actually links, rather than reading the templates —
      ``tests/control/test_the_panel_is_self_contained.py`` is the source-level half
      and this is the runtime one. They fail differently: a template that stops being
      rendered still passes the source check and would drop out of this one, and a
      stylesheet vendored into the image but not into the repository would pass the
      source check and fail here.

Boundary: real control + postgres + caddy. It proves the DOCUMENTS reference nothing
external. It does not prove a browser made no request — no browser runs here — which
is why the same claim is also walked with the machine's outbound network cut during
acceptance.
"""

import re

import pytest

OPERATOR = {"username": "owner", "password": "e2e-operator-password"}

# Every screen the console can put on a display, including the fragments a dialog is
# made of — a third-party reference hidden in a modal is still a third-party
# reference, and it is the one nobody looks at.
PANEL_PAGES = (
    "/panel/login",
    "/panel/",
    "/panel/friends",
    "/panel/friends/new",
    "/panel/fleet",
)

# Anything that is not a path on this host. A scheme-relative URL is included on
# purpose: `//fonts.example/x` reads like a path and is fetched from another host,
# which makes it the form this rule dies of.
EXTERNAL = re.compile(r"^\s*(?:[a-z][a-z0-9+.-]*:)?//", re.I)

# Schemes that fetch nothing over the network and are therefore not a third party.
INERT_SCHEMES = ("data:", "mailto:", "#", "javascript:void")


@pytest.fixture
async def operator(client):
    response = await client.post("/panel/login", data=OPERATOR)
    assert response.status_code == 303, (
        f"the operator could not log in ({response.status_code}) — check "
        "deploy/e2e.env against deploy/docker-compose.e2e.yml"
    )
    return client


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
    """The ones that leave this host."""
    return [
        reference
        for reference in references
        if EXTERNAL.match(reference)
        and not reference.lower().startswith(INERT_SCHEMES)
    ]


async def test_no_panel_page_references_another_origin(operator) -> None:
    """The whole console, page by page, with the dialogs it opens."""
    for page in PANEL_PAGES:
        response = await operator.get(page)
        assert response.status_code == 200, f"{page} answered {response.status_code}"

        leaking = offenders(references_in_html(response.text))
        assert leaking == [], (
            f"{page} points the browser at another host: {leaking}. The panel must "
            "load from this host alone — docs/decisions.md, decision 7."
        )


async def test_every_stylesheet_the_panel_links_is_served_here_and_stays_here(
    operator,
) -> None:
    """Follow the links, not the templates.

    A stylesheet is where this rule actually died in the design handoff — the
    ``@import`` on line 2 of the design system, which no reading of the HTML would
    ever have found.
    """
    sheets = set()
    for page in PANEL_PAGES:
        document = (await operator.get(page)).text
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
