"""Does the tag we pinned actually exist?

WHAT: resolves every upstream image a node is told to run — the data planes pinned in
      ``edge/bootstrap/node_stack.py`` and the delivery listener pinned in
      ``edge/bootstrap/delivery_site.py`` — against a real container registry.
WHY:  it is the one class of value in this repository that no unit test can check. A
      pinned tag is a string; a string that resolves and a string that does not are
      indistinguishable until something asks a registry. And the consequence is not
      subtle: the compose file we push to a node names these images, so a tag that does
      not exist is a node that will never start a data plane at all — discovered on the
      first real host, by the owner, with nothing in the tree having complained.

      This scenario was written because that had already happened. Backlog item 16
      pinned ``ghcr.io/amnezia-vpn/amneziawg-go:v0.2.12`` with an honest note that the
      tag had never been pulled, and the report for `e2-117` carried that note to the
      owner as the single unverified value in the code. It does not exist — not the tag,
      not the repository, not on that registry. The note was right and the value was
      wrong for months.
HOW:  ``docker manifest inspect``, which asks the registry for a tag's manifest and
      downloads no layers. The docker CLI is used rather than a hand-rolled registry
      client because it already knows every registry's authentication dance, and a
      client of ours that got that wrong would report a real tag as missing.

Boundary: this is the ONE scenario in this suite that reaches the public internet, and
that is inherent to the question — "does this tag exist" has no local answer. It says
nothing about whether the image WORKS: that it starts, accepts our command line, and
carries traffic is the owner's field check on the first real node. A registry can
confirm a name and nothing more.
"""

import subprocess

import pytest

from edge.bootstrap.delivery_site import DELIVERY_IMAGE
from edge.bootstrap.node_stack import DATA_PLANES

# One entry per config format, plus the delivery listener — which is NOT in that table
# and cannot be, because the table answers "which daemon runs a transport's config" and
# a file server runs none. It is named here explicitly for the reason this whole file
# exists: a pin nothing resolves is a container that never starts, discovered on a real
# host, and the 2026-09-26 rows named that as the cost of declaring the service.
#
# Sorted so a failure names the same pin on every run.
PINS = sorted({data_plane.image for data_plane in DATA_PLANES.values()} | {DELIVERY_IMAGE})

# A tag that cannot exist, on a repository that does. The red half of this file: without
# it, a `docker manifest inspect` that succeeded on everything — a wrapper that swallowed
# its own error, a registry mirror answering 200 to anything — would make every
# assertion above pass and mean nothing.
KNOWN_MISSING = "docker.io/library/alpine:this-tag-does-not-exist-hashi-e2e"


def resolves(reference: str) -> subprocess.CompletedProcess:
    """Ask a registry for this tag's manifest. Downloads no layers."""
    return subprocess.run(
        ["docker", "manifest", "inspect", reference],
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_there_are_pins_to_check() -> None:
    """An empty pin list would make the scenario below vacuous."""
    assert PINS, "no data-plane images are pinned, so nothing here is verified"


@pytest.mark.parametrize("reference", PINS)
def test_the_pinned_data_plane_image_exists(reference: str) -> None:
    """Every pin resolves.

    Failure here is not "flaky network": it is a tag that will not pull on a node. If the
    registry is genuinely unreachable, the message below says so and the run should be
    repeated rather than the pin changed.
    """
    result = resolves(reference)
    assert result.returncode == 0, (
        f"the pinned image {reference!r} does not resolve. A node's compose file names "
        "it, so no data plane would ever start:\n"
        f"{(result.stderr or result.stdout).strip()[:1000]}"
    )


@pytest.mark.parametrize("reference", PINS)
def test_every_pin_names_an_exact_version(reference: str) -> None:
    """No ``latest``, no bare major — core invariants §5.

    Sharper here than "reproducible builds": an upstream that changes its default TLS
    parameters silently changes how detectable every node in the fleet is, and a floating
    tag means that happens without a commit.
    """
    assert ":" in reference, f"{reference!r} has no tag at all, so it means `latest`"
    tag = reference.rsplit(":", 1)[1]
    assert tag != "latest", f"{reference!r} is pinned to `latest`"
    # A digest is even better than a tag and is allowed; otherwise require something
    # more specific than a single number, which is what a bare major looks like.
    if not reference.count("@"):
        assert not tag.isdigit(), (
            f"{reference!r} is pinned to the bare major {tag!r}, which moves"
        )


def test_a_tag_that_does_not_exist_is_reported_as_missing() -> None:
    """Proof that the check above can fail. The red half, applied to the tool."""
    result = resolves(KNOWN_MISSING)
    assert result.returncode != 0, (
        "a knowingly nonexistent tag resolved, so `docker manifest inspect` is not "
        "answering the question this scenario asks and every result above is meaningless"
    )
