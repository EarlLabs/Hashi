"""Fail loudly, never start degraded.

WHAT: the shipped control image must refuse to start when HASHI_SECRET_KEY is
      absent, rather than boot and generate one.
WHY:  that key encrypts node credentials at rest. A generated-on-boot fallback
      does not fail — it starts a healthy-looking service that cannot read
      yesterday's backup, and nobody finds out until a restore. tests/control/
      pins this at the Settings level; this pins it for the artefact that
      actually gets deployed, where an entrypoint, a default in the compose file
      or a base-image env var could each put the value back.
HOW:  runs the already-built control image directly, with no HASHI_SECRET_KEY in
      its environment, and requires a non-zero exit.

Boundary: real control image; no database, no network. Nothing stubbed.
"""

import json
import subprocess


def _image_of(compose, service: str) -> str:
    """The image the e2e stack is actually running for a service."""
    cid = compose("ps", "-q", service).stdout.split()
    assert cid, f"no running container for {service!r} — is the e2e stack up?"
    inspected = subprocess.run(
        ["docker", "inspect", cid[0]], capture_output=True, text=True, timeout=60
    )
    return json.loads(inspected.stdout)[0]["Config"]["Image"]


def test_control_image_refuses_to_start_without_a_secret_key(compose) -> None:
    """No key, no boot — and the failure must name what is missing."""
    image = _image_of(compose, "control")

    result = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "python", image,
         "-c", "from control.app.settings import Settings; Settings()"],
        capture_output=True, text=True, timeout=120,
    )

    assert result.returncode != 0, (
        "the control image constructed Settings with no HASHI_SECRET_KEY set — "
        "a generated-on-boot key makes yesterday's backup undecryptable"
    )
    assert "secret_key" in (result.stdout + result.stderr).lower(), (
        "it failed, but the error does not say which value is missing:\n"
        f"{result.stdout}\n{result.stderr}"
    )
