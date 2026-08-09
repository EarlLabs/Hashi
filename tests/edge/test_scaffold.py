"""Structural rules of the `edge` zone — the ones that must hold for all time.

WHAT: the zone's two architectural invariants, checked against the source tree:
      `edge` never imports `control`, and rendering is pure.
WHY:  both are cheap to hold now and expensive to restore later. A single
      ``from control...`` import inside edge makes config rendering untestable in
      isolation and inverts the dependency the charter relies on. An ``import
      requests`` or a ``datetime.now()`` inside a renderer is worse: it does not
      fail, it just makes every render slightly different, and then drift
      detection on a node stops meaning anything.
HOW:  no I/O beyond reading this repository's own source. This file replaced an
      earlier assertion that the registry was EMPTY — true of the scaffold, and a
      false premise the moment the first transport landed.
"""

import ast
import pathlib

from edge.registry import discover

EDGE = pathlib.Path(__file__).resolve().parents[2] / "edge"

# Modules whose mere presence in this zone means rendering is no longer pure. The
# renderers must be a function of their arguments: given the same node record and
# parameters, the same bytes. `os`/`pathlib` are deliberately absent from this
# list — `templating.py` legitimately locates a template file shipped in the image.
IMPURE = {
    "socket", "http", "urllib.request", "requests", "httpx",
    "random", "secrets", "time", "datetime", "uuid",
    "sqlalchemy", "asyncpg", "psycopg",
}

# Where I/O is allowed, and the rulebook says only here: SSH to a node and health
# probing, both initiated by the control plane. `templating.py` reads a template
# shipped in the image; `checker.py` shells out to the upstream config checker.
IO_ALLOWED = {"bootstrap", "health", "templating.py", "checker.py"}


def source_files() -> list[pathlib.Path]:
    return sorted(EDGE.rglob("*.py"))


def test_registry_discovers_the_shipped_transports() -> None:
    """Discovery is dynamic and finds what is on disk, whatever that is."""
    found = discover()
    assert isinstance(found, dict)
    assert found, "no transport packages discovered under edge/transports/"
    # The registry keys itself on the name the transport DECLARES, not its
    # directory — so this holds even after a package is renamed.
    for name, meta in found.items():
        assert name == meta.name


def test_edge_never_imports_control() -> None:
    """`control` imports `edge`, never the reverse — core invariants §1."""
    offenders = [
        str(path.relative_to(EDGE))
        for path in source_files()
        for line in path.read_text().splitlines()
        if line.startswith(("import control", "from control"))
    ]
    assert offenders == [], f"edge must not import control: {offenders}"


def imported_modules(path: pathlib.Path) -> set[str]:
    """Top-level module names imported by a file, via AST rather than by regex.

    AST because a regex over source counts the word `random` in a comment or a
    docstring, and a purity test that cries wolf is a purity test people delete.
    """
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_renderers_import_nothing_that_could_make_them_impure() -> None:
    """No clock, no randomness, no network, no database anywhere but bootstrap/health.

    Key material is *passed into* a renderer, never generated inside one — which is
    why `secrets` and `uuid` are on the forbidden list even though generating a key
    is a perfectly good thing to do somewhere else (it happens in `control`).
    """
    offenders = []
    for path in source_files():
        relative = path.relative_to(EDGE)
        if any(part in IO_ALLOWED for part in relative.parts):
            continue
        for module in imported_modules(path):
            root = module.split(".")[0]
            if module in IMPURE or root in IMPURE:
                offenders.append(f"{relative}: imports {module}")
    assert offenders == [], (
        "rendering must be a pure function of its arguments, but: " + "; ".join(offenders)
    )
