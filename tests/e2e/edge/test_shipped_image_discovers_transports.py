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


def packages_in_the_tree() -> list[str]:
    """Every transport DIRECTORY in this checkout.

    Directory names, not transport names: a package declares its own name in ``META``
    and the two differ on purpose (``vless_reality`` declares ``vless-reality``), which
    is why this count is cross-checked against discovery rather than compared to it.
    """
    return sorted(
        path.name
        for path in EDGE_TRANSPORTS.iterdir()
        if path.is_dir() and (path / "__init__.py").exists()
    )


def transports_in_the_tree() -> list[str]:
    """What discovery finds in the SOURCE tree, by the names transports declare.

    Run in this process against the checkout, so the comparison below is exactly
    "source tree vs shipped artefact" — the two things that fail independently.
    """
    from edge.registry import discover

    return sorted(discover())


def test_the_image_ships_every_transport_in_the_tree(compose) -> None:
    """No transports yet is a real answer: then both sides must be empty."""
    result = compose("exec", "-T", "control", "python", "-c", DISCOVER)
    assert result.returncode == 0, (
        f"discovery raised inside the shipped image:\n{result.stdout}\n{result.stderr}"
    )
    shipped = json.loads(result.stdout.strip().splitlines()[-1])

    assert shipped == transports_in_the_tree(), (
        f"the image discovers {shipped}, the tree has {transports_in_the_tree()} — a "
        "transport is missing from the image's package list (pyproject.toml "
        "[tool.setuptools])"
    )
    # And nothing was lost between "a directory exists" and "discovery found it": a
    # package that fails to import in this process would otherwise shrink both sides
    # of the comparison above equally and pass.
    assert len(shipped) == len(packages_in_the_tree()), (
        f"the tree has {packages_in_the_tree()} but only {shipped} are discoverable — "
        "a transport package is present and not importable"
    )
