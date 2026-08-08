"""A transport that is not in the image does not exist.

WHAT: proves the built control image can import `edge` and run discovery, and
      that what it discovers matches the transport packages in this checkout.
WHY:  the charter's fourth criterion is that a new protocol is one new package
      under edge/transports/ and not surgery. Discovery makes that true at
      runtime; PACKAGING makes it true in the artefact, and the two fail
      independently. A package list in pyproject.toml that does not cover a new
      subpackage produces exactly this bug: green tests on the developer's
      machine, and a deployed image whose registry is silently one transport
      short. tests/edge/ cannot see it — it runs against the source tree.
HOW:  runs discovery inside the running control container and compares the names
      with the directories on disk here.

Boundary: real control image. No node, no tunnel, no rendering of a real config.
"""

import json
import pathlib

EDGE_TRANSPORTS = pathlib.Path(__file__).resolve().parents[3] / "edge" / "transports"

DISCOVER = (
    "import json;"
    "from edge.registry import discover;"
    "print(json.dumps(sorted(discover())))"
)


def transport_packages_in_the_tree() -> list[str]:
    """Every transport package a developer would expect to be shipped."""
    return sorted(
        path.name
        for path in EDGE_TRANSPORTS.iterdir()
        if path.is_dir() and (path / "__init__.py").exists()
    )


def test_the_image_ships_every_transport_in_the_tree(compose) -> None:
    """No transports yet is a real answer: then both sides must be empty."""
    result = compose("exec", "-T", "control", "python", "-c", DISCOVER)
    assert result.returncode == 0, (
        f"discovery raised inside the shipped image:\n{result.stdout}\n{result.stderr}"
    )
    shipped = json.loads(result.stdout.strip().splitlines()[-1])

    assert shipped == transport_packages_in_the_tree(), (
        f"the image discovers {shipped}, the tree has "
        f"{transport_packages_in_the_tree()} — a transport is missing from the "
        "image's package list (pyproject.toml [tool.setuptools])"
    )
