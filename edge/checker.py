"""Validate a rendered config with the upstream daemon's own checker.

WHAT: locates the pinned Xray binary and runs its config check over rendered text.
WHY:  the edge rulebook requires every rendered config to be validated by the
      upstream binary rather than by a regex of ours — "a config we believe is
      valid is not a config the daemon accepts". That check is needed in two
      places, which is why it lives here rather than in the test suite: the tests
      use it, and so does the apply path in `control`, which must refuse to push a
      config the daemon would reject rather than restart a node into a crash loop.
HOW:  ``validate(config)`` returns a ``CheckResult``. When the binary is absent it
      returns ``available=False`` rather than raising or pretending success —
      callers decide whether that is a loud skip (tests) or a refusal to push
      (apply). Nothing here renders, and nothing here reads node data.

This module does subprocess I/O and is therefore one of the few places in this
pure zone allowed to, alongside ``bootstrap/`` and ``health/``.
"""

import os
import pathlib
import shutil
import subprocess
from dataclasses import dataclass

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

# Where scripts/fetch-upstream-checkers.sh installs the pinned binary.
VENDORED = REPO_ROOT / ".tools" / "xray"


def xray_binary() -> str | None:
    """The Xray binary to validate with, or ``None`` if none is available.

    Resolution order is deliberate. ``HASHI_XRAY_BIN`` first, so a developer or
    the fleet can point at one specific pinned build. Then ``.tools/xray``, which
    is the version this repository pins. ``PATH`` last and reluctantly: a system
    Xray is of unknown version, and core invariants §5 pins the data plane because
    an upstream that changes its defaults changes how detectable every node is.
    """
    override = os.environ.get("HASHI_XRAY_BIN")
    if override:
        return override if pathlib.Path(override).is_file() else None
    if VENDORED.is_file():
        return str(VENDORED)
    return shutil.which("xray")


@dataclass(frozen=True)
class CheckResult:
    """The outcome of asking the daemon whether it would accept a config."""

    # False when no checker is installed. Distinguished from a failed check so a
    # caller can never mistake "we could not ask" for "the answer was yes".
    available: bool
    ok: bool
    output: str = ""

    def __bool__(self) -> bool:
        """Truthy only when the daemon was asked AND it said yes."""
        return self.available and self.ok


def validate(config: str, *, timeout: int = 60) -> CheckResult:
    """Ask Xray whether it would accept ``config``.

    Validates syntax and schema only. It will happily accept a decoy host that
    does not resolve, and it says nothing whatsoever about whether the transport
    survives inspection on a real network — that is a field observation, never a
    checker's exit code.

    **One limit worth knowing before relying on this as a pre-push gate,
    established by running it rather than by reading the docs:** ``-test`` does not
    merely parse — it builds the runtime objects, including the TLS context. So a
    config that names a certificate FILE fails here unless that file exists on the
    machine doing the checking. For such a transport (``vless-ws-tls`` today),
    validating locally in `control` before pushing proves strictly less than
    validating on the node after the certificate is in place, and the apply path
    treats a local failure of this kind as "not yet checkable here" rather than as
    a rejected config. See ``control/app/services/apply.py``.
    """
    binary = xray_binary()
    if binary is None:
        return CheckResult(available=False, ok=False, output="no xray binary available")

    # A real file because `xray run -test` takes a path, not stdin. Written to a
    # private temporary directory and removed with it: a rendered server config
    # contains a node's private key, so it must not linger in /tmp with default
    # permissions or survive the call.
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        path = pathlib.Path(directory) / "config.json"
        path.write_text(config)
        path.chmod(0o600)
        try:
            result = subprocess.run(
                [binary, "run", "-test", "-config", str(path)],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return CheckResult(available=True, ok=False, output="xray -test timed out")

    return CheckResult(
        available=True,
        ok=result.returncode == 0,
        # Both streams: Xray reports schema errors on stderr and some on stdout.
        output=(result.stderr + result.stdout).strip(),
    )
