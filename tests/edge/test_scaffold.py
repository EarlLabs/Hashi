"""Data-plane scaffold tests.

WHAT: pins the two structural rules of the `edge` zone before any transport
      exists — discovery is dynamic, and the zone never depends on `control`.
WHY:  both are cheap to hold now and expensive to restore later. A single
      ``from control...`` import inside edge makes config rendering
      untestable in isolation and inverts the dependency the charter relies on.
HOW:  no I/O beyond reading this repository's own source.
"""

import pathlib

from edge.registry import discover

EDGE = pathlib.Path(__file__).resolve().parents[2] / "edge"


def test_discovery_returns_a_mapping_with_no_transports_yet() -> None:
    """No transports are implemented yet — an empty registry is correct, not broken."""
    found = discover()
    assert isinstance(found, dict)
    assert found == {}


def test_edge_never_imports_control() -> None:
    """`control` imports `edge`, never the reverse — core invariants §1."""
    offenders = [
        str(path.relative_to(EDGE))
        for path in EDGE.rglob("*.py")
        for line in path.read_text().splitlines()
        if line.startswith(("import control", "from control"))
    ]
    assert offenders == [], f"edge must not import control: {offenders}"
