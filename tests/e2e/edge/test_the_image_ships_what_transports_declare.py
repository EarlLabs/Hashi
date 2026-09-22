"""A serialisation a transport declares but the image cannot perform.

WHAT: proves the built image agrees with this checkout about what each transport
      serialises into, and that everything needed to perform those serialisations —
      the render functions AND their templates — is actually inside the artefact.
WHY:  backlog item 26 turned "expressible in the v1 subscription, yes or no" into a
      declared SET of subscription formats, with one required render function per
      format. That makes a new failure possible in the artefact rather than in the
      code: a transport whose declaration ships and whose serialiser or template does
      not. The symptom is the worst shape available — the panel offers the transport,
      and one user's refresh raises at delivery time, days later.

      `tests/edge/` cannot see it: it runs against the source tree, where every file
      is present by definition. This is the same argument as its neighbour scenario
      about discovery, one level down.
HOW:  loads every transport through ``profile()`` INSIDE the running control
      container — which is where item 26's load-time contract check lives — and
      compares the declarations and the shipped template files with this checkout's.

Boundary: real control image. No node, no user, no rendering of real material: the
bytes a user receives are pinned by golden files in tests/edge/, and the upstream
tool's verdict on them is tests/edge/test_upstream_validation.py.
"""

import json
import pathlib

EDGE_TRANSPORTS = pathlib.Path(__file__).resolve().parents[3] / "edge" / "transports"

# Runs inside the image. Loads each transport the way `control` does — ``profile()``,
# not ``discover()`` — because that is the call that imports render.py and enforces
# "every declared format has the function that produces it". A ContractViolation here
# is the finding, not an error in the test.
INSPECT = (
    "import json, pathlib;"
    "from edge.registry import discover, profile;"
    "out = {};"
    "\nfor name in sorted(discover()):"
    "\n    transport = profile(name);"
    "\n    directory = pathlib.Path(transport.profile.__file__).parent;"
    "\n    out[name] = {"
    "'formats': sorted(str(f) for f in transport.meta.subscription_formats),"
    "'templates': sorted(p.name for p in directory.glob('*.j2')),"
    "}"
    "\nprint(json.dumps(out))"
)


def declarations_in_the_tree() -> dict[str, dict[str, list[str]]]:
    """The same facts, read from this checkout, by the same code path."""
    from edge.registry import discover, profile

    found = {}
    for name in sorted(discover()):
        transport = profile(name)
        directory = pathlib.Path(transport.profile.__file__).parent
        found[name] = {
            "formats": sorted(str(f) for f in transport.meta.subscription_formats),
            "templates": sorted(path.name for path in directory.glob("*.j2")),
        }
    return found


def inspected(compose) -> dict[str, dict[str, list[str]]]:
    """Run the inspection in the image, or fail with what went wrong there.

    The returncode is checked before the output is parsed, and that is not a nicety:
    the failure this scenario exists to catch — a declared format with no serialiser —
    makes ``profile()`` raise, which produces no JSON at all. Parsing first would
    report the real finding as an ``IndexError`` in the test.
    """
    result = compose("exec", "-T", "control", "python", "-c", INSPECT)
    assert result.returncode == 0, (
        "loading a transport raised inside the shipped image — a declared subscription "
        f"format has no serialiser there:\n{result.stdout}\n{result.stderr}"
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_the_image_agrees_with_the_tree_about_every_serialisation(compose) -> None:
    """Declarations and templates, both sides, one comparison."""
    shipped = inspected(compose)
    expected = declarations_in_the_tree()

    assert shipped == expected, (
        f"the image and the tree disagree.\nimage: {json.dumps(shipped, indent=2)}\n"
        f"tree:  {json.dumps(expected, indent=2)}\n"
        "A missing template is a packaging gap (pyproject.toml "
        "[tool.setuptools.package-data]); a missing format is a stale image."
    )

    # And neither side is vacuously empty. A transport package that failed to import
    # would shrink both sides equally and pass the comparison above.
    assert shipped, "no transports in the image at all"
    for name, facts in shipped.items():
        assert facts["formats"] or facts["templates"], (
            f"{name}: declares no user-facing format and ships no template — "
            "nothing about this transport is verifiable here"
        )


def test_every_transport_directory_reached_the_image(compose) -> None:
    """No transport was lost between "a directory exists" and "it loads in the image"."""
    packages = sorted(
        path.name
        for path in EDGE_TRANSPORTS.iterdir()
        if path.is_dir() and (path / "__init__.py").exists()
    )
    shipped = inspected(compose)
    assert len(shipped) == len(packages), (
        f"the tree has {packages} but the image loads {sorted(shipped)} — a transport "
        "package is present here and not loadable there"
    )
