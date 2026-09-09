"""Nothing the panel serves may reference an origin that is not this host.

WHAT: a source-level check over every template and every static file, plus a drift
      check on the vendored design system.
WHY:  ``docs/decisions.md`` decision 7. ``base.html`` already refused a CDN for HTMX
      because *"the panel must work on a network where the CDN is blocked, which is
      the same network the operator uses to fix a blocked node"*; M7 has now put the
      console behind a management tunnel where such a request may have no route at
      all; and an ``@import`` from a font service tells a US company every time the
      owner opens their VPN console.
HOW:  text analysis over ``control/app/templates`` and ``control/app/static``.
      Comments are stripped first — this repository explains its decisions in prose,
      and that prose legitimately quotes the very URL that was removed. A test that
      cries wolf gets deleted, taking the real check with it.

The RUNTIME proof is a separate scenario:
``tests/e2e/control/test_the_panel_fetches_nothing_from_a_third_party.py`` walks the
booted panel and follows what it actually links. This file is the fast half — it runs
in ``make test-control`` and fails the moment a URL is typed, without a stack.
"""

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
TEMPLATES = REPO / "control" / "app" / "templates"
STATIC = REPO / "control" / "app" / "static"
DESIGN_SYSTEM = REPO / "design" / "design-system" / "styles.css"

TEXT_SUFFIXES = {".html", ".css", ".js"}
SERVED_FILES = sorted(
    path
    for path in [*TEMPLATES.rglob("*"), *STATIC.rglob("*")]
    if path.is_file() and path.suffix in TEXT_SUFFIXES
)

# A scheme-relative URL (`//example.com/x`) is the one that hides: it looks like a
# path and is fetched from another host. `url(//` and `src="//` are both real.
EXTERNAL = re.compile(r"""(?:https?:)?//(?!/)[a-z0-9]""", re.I)


def without_comments(path: pathlib.Path) -> str:
    """The file's effective text, with every comment syntax it can carry removed."""
    text = path.read_text()
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.S)      # Jinja
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)     # HTML
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)      # CSS and JS block
    text = re.sub(r"^\s*//.*$", "", text, flags=re.M)      # JS line
    return text


@pytest.mark.parametrize("path", SERVED_FILES, ids=lambda p: p.name)
def test_no_served_file_references_another_origin(path: pathlib.Path) -> None:
    """One failing file names itself, rather than one failure naming a list."""
    offenders = [
        line.strip()
        for line in without_comments(path).splitlines()
        if EXTERNAL.search(line)
    ]
    assert offenders == [], (
        f"{path.relative_to(REPO)} points the panel at another host: {offenders[:3]}. "
        "The console must load from this host alone — decision 7."
    )


def test_the_vendored_design_system_differs_from_the_original_only_by_the_font_import()  -> None:
    """The one edit decision 7 authorised, and nothing else.

    The handoff's fidelity note is about the NUMBERS in this file — "recreate them
    exactly" — so a colour or a spacing step quietly changed here would be a silent
    divergence from the design nobody could see in a screenshot. Re-vendoring means
    repeating exactly this one edit.
    """
    original = _body(DESIGN_SYSTEM.read_text())
    vendored = _body((STATIC / "styles.css").read_text())

    expected = "\n".join(
        line for line in original.splitlines() if not line.startswith("@import")
    )
    assert vendored.strip() == expected.strip()
    assert "@import" in DESIGN_SYSTEM.read_text(), (
        "the original no longer has the @import this test exists to prove was removed "
        "— re-read decision 7 before changing this"
    )


def test_every_vendored_font_file_is_actually_there() -> None:
    """A self-hosted @font-face pointing at nothing fails silently.

    The browser falls back and the panel merely looks slightly wrong, which is the
    kind of fault nobody reports and nobody notices. Cheaper to assert.
    """
    fonts_css = (STATIC / "fonts.css").read_text()
    referenced = re.findall(r"url\('([^']+)'\)", fonts_css)

    assert len(referenced) >= 10, referenced
    for reference in referenced:
        assert reference.startswith("/static/"), reference
        target = STATIC / reference.removeprefix("/static/")
        assert target.is_file(), f"{reference} is declared but not vendored"
        # woff2's magic number. A truncated or HTML-error-page download would
        # otherwise sit in the repository looking like a font.
        assert target.read_bytes()[:4] == b"wOF2", f"{reference} is not a woff2 file"


def test_every_face_the_removed_import_asked_for_is_declared() -> None:
    """Barlow 400/500/700 and Barlow Condensed 400/600 — the exact weights."""
    fonts_css = (STATIC / "fonts.css").read_text()
    declared = set(
        re.findall(r"font-family: '([^']+)';\s+font-style: normal;\s+font-weight: (\d+)",
                   fonts_css)
    )

    for weight in ("400", "500", "700"):
        assert ("Barlow", weight) in declared
    for weight in ("400", "600"):
        assert ("Barlow Condensed", weight) in declared


def _body(css: str) -> str:
    """The stylesheet with its leading block comment removed."""
    return re.sub(r"^/\*.*?\*/\s*", "", css, count=1, flags=re.S)
