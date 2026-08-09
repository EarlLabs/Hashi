"""The rules that make `control` protocol-blind, checked against its source.

WHAT: that nothing in ``control/`` branches on a specific transport, country,
      provider, address or port, and that no module reads the environment directly.
WHY:  core invariants §1 and §6, and charter criterion 4. These are the rules that
      decay silently: one ``if transport_name == "vless-reality"`` added under time
      pressure still passes every functional test, and the cost only appears when the
      next protocol is added and nothing works. A test is the only thing that holds
      them.
HOW:  AST and text analysis over this repository's own source. No database, no app.

The subscription renderer gets its own, sharper assertion: the contract's stated proof
is arithmetic — adding a transport adds ZERO lines there — so that file must not
contain a transport name at all.
"""

import ast
import pathlib
import re

import pytest

CONTROL = pathlib.Path(__file__).resolve().parents[2] / "control"
SUBSCRIPTIONS = CONTROL / "app" / "services" / "subscriptions.py"

SOURCE_FILES = sorted(CONTROL.rglob("*.py"))

# The transports that exist today. Their names must not appear as literals in
# `control` — discovered from the registry rather than hardcoded here, so this test
# keeps working as transports come and go.
from edge.registry import discover  # noqa: E402

TRANSPORT_NAMES = sorted(discover())


def code_without_comments_or_docstrings(path: pathlib.Path) -> str:
    """The file's executable text, with comments and docstrings removed.

    Necessary because this codebase explains its decisions in prose, and that prose
    legitimately names transports, countries and ports. A grep over raw source would
    flag every explanatory comment — and a test that cries wolf gets deleted, taking
    the real check with it.
    """
    source = path.read_text()
    tree = ast.parse(source)

    docstring_spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            docstring_spans.append((node.lineno, node.end_lineno or node.lineno))

    kept = []
    for number, line in enumerate(source.splitlines(), start=1):
        if any(start <= number <= end for start, end in docstring_spans):
            continue
        kept.append(line.split("#", 1)[0])
    return "\n".join(kept)


def test_control_never_names_a_transport_in_code() -> None:
    """No ``if transport == "..."``, anywhere. Criterion 4 in one assertion.

    Note the test is over CODE, not comments: the modules here explain at length why
    they avoid protocol names, and those explanations name protocols.
    """
    offenders = []
    for path in SOURCE_FILES:
        code = code_without_comments_or_docstrings(path)
        for name in TRANSPORT_NAMES:
            if name in code:
                offenders.append(f"{path.relative_to(CONTROL)}: names {name!r}")
    assert offenders == [], (
        "control must not know any transport by name — a new protocol is one package "
        f"under edge/transports/, not an edit here: {offenders}"
    )


def test_the_subscription_renderer_names_no_transport_at_all() -> None:
    """The contract's proof is arithmetic: a new transport adds zero lines here."""
    code = code_without_comments_or_docstrings(SUBSCRIPTIONS)
    for name in TRANSPORT_NAMES:
        assert name not in code, f"the subscription renderer branches on {name!r}"
    # It must also not be parsing the serialised entry, which is the other way this
    # contract gets broken: reading `entry` to decide anything makes the format the
    # renderer's business again.
    assert ".entry.split" not in code
    assert "urlparse" not in code


def test_control_hardcodes_no_country_provider_or_address() -> None:
    """Core invariants §6: a hardcoded value is a node you cannot rotate away from."""
    # Reserved documentation ranges are fine — they only ever appear in fixtures — but
    # a real-looking public address in control's code is not.
    forbidden = re.compile(
        r"\b(?:"
        r"digitalocean|hetzner|vultr|linode|aws|amazonaws|cloudflare"
        r"|Netherlands|Germany|Iceland|Finland|Russia"
        r")\b",
        re.IGNORECASE,
    )
    offenders = []
    for path in SOURCE_FILES:
        code = code_without_comments_or_docstrings(path)
        for match in forbidden.finditer(code):
            offenders.append(f"{path.relative_to(CONTROL)}: {match.group(0)!r}")
    assert offenders == [], f"hardcoded provider or country: {offenders}"


def test_only_settings_reads_the_environment() -> None:
    """Configuration comes from ``settings.py`` and nowhere else.

    A scattered ``os.environ`` lookup fails on the first request that needs it, in
    production, at night — which is the whole reason the rule exists.
    """
    allowed = {"settings.py"}
    offenders = []
    for path in SOURCE_FILES:
        if path.name in allowed:
            continue
        code = code_without_comments_or_docstrings(path)
        if "os.environ" in code or "os.getenv" in code:
            offenders.append(str(path.relative_to(CONTROL)))
    assert offenders == [], (
        f"these read the environment directly instead of via settings.py: {offenders}"
    )


def test_nothing_in_control_prints() -> None:
    """``print`` bypasses the logging configuration that keeps paths out of logs.

    ``control/cli.py`` is exempt: it is a terminal command whose entire output is for
    the person who typed it, and it never runs inside the server.
    """
    offenders = []
    for path in SOURCE_FILES:
        if path.name == "cli.py":
            continue
        code = code_without_comments_or_docstrings(path)
        if re.search(r"\bprint\s*\(", code):
            offenders.append(str(path.relative_to(CONTROL)))
    assert offenders == [], f"use the module logger, not print: {offenders}"


def test_no_logger_call_includes_a_request_path_or_token() -> None:
    """The subscription token lives in the URL path, so a logged path is a logged key.

    Catches the shapes that put one in a log record: ``request.url``,
    ``request.url.path``, and any logging call mentioning a token variable.
    """
    dangerous = re.compile(
        r"log(?:ger)?\.\w+\([^)]*(?:request\.url|\.url\.path|subscription\.token|\btoken\b)",
        re.DOTALL,
    )
    offenders = []
    for path in SOURCE_FILES:
        code = code_without_comments_or_docstrings(path)
        for match in dangerous.finditer(code):
            offenders.append(f"{path.relative_to(CONTROL)}: {match.group(0)[:80]!r}")
    assert offenders == [], f"a log call may record a live subscription token: {offenders}"


def test_no_model_records_anything_about_a_connection() -> None:
    """Core invariants §3, asserted on the schema rather than trusted.

    The one record that can hurt a real person is the one that must not exist. This
    checks column NAMES across the models, because the way this rule breaks is a
    well-meant ``last_seen_at`` added to help debugging.
    """
    models = sorted((CONTROL / "app" / "models").rglob("*.py"))
    forbidden = (
        "last_seen", "last_connected", "connection", "traffic", "bytes_",
        "ip_address", "client_ip", "dns", "usage", "session_count",
    )
    offenders = []
    for path in models:
        code = code_without_comments_or_docstrings(path)
        for term in forbidden:
            if term in code:
                offenders.append(f"{path.relative_to(CONTROL)}: {term!r}")
    assert offenders == [], (
        "a model records something about connections or traffic, which the charter "
        f"says must not exist anywhere: {offenders}"
    )


@pytest.mark.parametrize("path", SOURCE_FILES, ids=lambda p: p.name)
def test_every_module_has_a_what_why_how_header(path: pathlib.Path) -> None:
    """A project convention, and the owner is learning from this codebase.

    ``__init__.py`` files are exempt when they are short re-export shims — there is
    nothing to explain in one import line.
    """
    source = path.read_text()
    tree = ast.parse(source)
    docstring = ast.get_docstring(tree)

    assert docstring, f"{path.name} has no module docstring"

    if path.name == "__init__.py" and len(source.splitlines()) < 25:
        return
    if len(source.splitlines()) < 30:
        return
    # Migrations follow Alembic's own header convention (Revision ID / Revises), which
    # is what every Alembic reader and tool expects to find at the top of the file.
    # They still carry prose explaining the non-obvious choices — see 0001's note on
    # why it is hand-written — but not under these three markers.
    if "migrations" in path.parts:
        return

    for marker in ("WHAT:", "WHY:", "HOW:"):
        assert marker in docstring, f"{path.name}: module docstring has no {marker} section"
