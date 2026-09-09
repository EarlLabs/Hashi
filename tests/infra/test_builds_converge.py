"""A build must not recreate a stack that has not changed — M6.5's other half.

WHAT: that every `up -d --build` in this repository disables BuildKit's default
      attestations.
WHY:  BuildKit attaches a provenance attestation to every image it exports, and that
      attestation records when the build ran. A FULLY CACHED rebuild therefore exports a
      manifest with a new digest — which is the image ID compose compares against the
      running container — so compose recreated every Dockerfile-built service on every
      invocation. Measured, not inferred: two consecutive cached builds of
      ``caddy.Dockerfile`` gave ``9383dcef…`` then ``bd9181d7…``; with the variable set,
      both gave ``aec06078…``.

      What that cost is worth stating accurately. The database is PULLED by tag rather
      than built, so it was never recreated and no data was ever at risk. The churn was
      ``control`` and ``caddy`` — a control-plane and TLS restart on every routine
      deploy, and a ``make up`` that could not be used to ask whether a stack was already
      converged. It also made ``panel-bootstrap.sh``'s own IDEMPOTENT header untrue,
      which is where it was found.
HOW:  reads the Makefile. Running it would mean building two images inside
      ``make test-infra``, which is the static tier.

      ``deploy/`` is deliberately not the place for this: ``build.provenance: false`` in
      a compose file parses and is then IGNORED under compose's bake path — verified, and
      the reason this is an environment variable on the command instead.
"""

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
MAKEFILE = REPO / "Makefile"
BOOTSTRAP = REPO / "scripts" / "panel-bootstrap.sh"


@pytest.fixture(scope="module")
def build_commands() -> list[str]:
    """Every line in the Makefile that builds and starts a stack."""
    lines = [
        line for line in MAKEFILE.read_text().splitlines()
        if "up -d --build" in line and not line.lstrip().startswith("#")
    ]
    assert lines, "no Make target builds and starts a stack any more"
    return lines


def test_every_make_target_that_builds_leaves_a_converged_stack_alone(
    build_commands: list[str],
) -> None:
    """`make up`, `make up-dev`, `make e2e-up` — all three, or the odd one churns.

    Asserted over every matching line rather than over three named targets, so a fourth
    stack-starting target added later inherits the rule instead of quietly missing it.
    """
    for command in build_commands:
        assert "BUILDX_NO_DEFAULT_ATTESTATIONS" in command or "NO_ATTESTATIONS" in command, (
            f"this build exports a new image ID on every run, so compose recreates every "
            f"built container even when nothing changed: {command.strip()!r}"
        )


def test_the_variable_is_scoped_to_the_build_and_not_exported() -> None:
    """Set on the command, never `export`ed at the top of the file.

    An export would also change how every other docker invocation in a run behaves —
    including the ones in the e2e helpers — which is a much larger claim than the one
    being made here.
    """
    makefile = MAKEFILE.read_text()
    assert not re.search(r"^\s*export\s+BUILDX_NO_DEFAULT_ATTESTATIONS", makefile, re.M), (
        "the Makefile exports the variable, so it applies to commands that never asked"
    )
    assert re.search(r"^NO_ATTESTATIONS\s*:?=", makefile, re.M), (
        "the variable is spelled out at each call site rather than named once, which is "
        "how the fourth one gets forgotten"
    )


def test_the_bootstrap_script_and_the_makefile_agree() -> None:
    """Both install the same stack; one converging and the other not is a trap.

    ``scripts/panel-bootstrap.sh`` is what an operator runs on a host and ``make up`` is
    what they run afterwards. If only one of them converged, re-running the other would
    look like the fix for a problem it had just caused.
    """
    assert "BUILDX_NO_DEFAULT_ATTESTATIONS=1" in BOOTSTRAP.read_text(), (
        "the panel bootstrap no longer disables default attestations, so its own "
        "IDEMPOTENT property is untrue again"
    )
