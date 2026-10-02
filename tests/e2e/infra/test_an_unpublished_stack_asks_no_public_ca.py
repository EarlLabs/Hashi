"""An unpublished stack asks no public CA for anything — M31.1.

WHAT: asks the REAL Caddy in the e2e stack which certificate issuer the shipped
      Caddyfile configures for the delivery name, in the two shapes a host runs it in:
      the base stack (nothing published — what `make panel-bootstrap` and
      `make restore-from-bucket` bring up) and the publishing overlay's environment.
WHY:  the restore walk of 2026-10-02 found `/data/caddy/acme` on a freshly restored host
      already holding Let's Encrypt and ZeroSSL accounts, an issuance lock and a
      challenge token: the base stack's Caddy began public issuance at boot, for a name
      that did not resolve there, on ports nothing had published. Every validation that
      cannot succeed counts against the live domain's rate limit. The static half of
      this rule is tests/infra/test_caddyfile.py; this half is what Caddy itself makes of
      the file, because "`tls {$VAR:internal}` means internal when VAR is unset" is a
      claim about Caddy's parser, not about our text.
HOW:  `caddy adapt` inside the running caddy container — it parses and prints the JSON
      config and starts nothing, so no CA is asked anything by this test either. The
      delivery name is overridden to a public-looking one, because the e2e stack serves
      `localhost`, which Caddy would hand its own CA whatever the file said: a test on
      `localhost` could not fail. Then the running container's own live config, read
      off its loopback admin endpoint.

Boundary: real caddy. Nothing is published and nothing leaves the container.
"""

import json

# A name Caddy would ask a public CA for if nothing told it otherwise. `.test` is
# reserved (RFC 2606) and never resolves, so even a regression asks nobody real.
PUBLIC_LOOKING = "delivery.example.test"
ACME_EMAIL = "ops@example.test"


def adapted(exec_in, **env: str) -> dict:
    """The JSON Caddy builds from the shipped Caddyfile, with ``env`` in its environment."""
    assignments = [f"{key}={value}" for key, value in env.items()]
    result = exec_in(
        "caddy", "env", *assignments,
        "caddy", "adapt", "--config", "/etc/caddy/Caddyfile",
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout)


def issuers_for(config: dict, name: str) -> list[str]:
    """The issuer modules that cover ``name`` — empty when no policy names it, which is
    Caddy's automatic HTTPS deciding, and for a public name that means a public CA."""
    policies = config.get("apps", {}).get("tls", {}).get("automation", {}).get("policies", [])
    for policy in policies:
        if name in policy.get("subjects", []):
            return [issuer["module"] for issuer in policy.get("issuers", [])]
    return []


def test_the_base_stack_serves_the_delivery_name_from_its_own_ca(exec_in) -> None:
    """The shape a restore and a bootstrap run in. Red before M31.1: no policy covered
    the name, so Caddy's automatic HTTPS chose Let's Encrypt and ZeroSSL."""
    config = adapted(exec_in, HASHI_PUBLIC_HOST=PUBLIC_LOOKING)
    assert issuers_for(config, PUBLIC_LOOKING) == ["internal"], (
        "the unpublished stack would ask a public CA for the delivery name at boot: "
        f"{json.dumps(config.get('apps', {}).get('tls'))}"
    )


def test_the_publishing_shape_asks_a_public_ca(exec_in) -> None:
    """The accept twin: with the overlay's switch set, the same file asks a public CA as
    the operator's ACME account — or a deployed host would serve every user a
    certificate no stock client accepts."""
    config = adapted(exec_in, HASHI_PUBLIC_HOST=PUBLIC_LOOKING, HASHI_PUBLIC_TLS=ACME_EMAIL)
    assert issuers_for(config, PUBLIC_LOOKING) == ["acme", "acme"], (
        f"{json.dumps(config.get('apps', {}).get('tls'))}"
    )


def test_the_running_proxy_holds_no_public_issuer(exec_in) -> None:
    """What the container that is actually running loaded — its own admin endpoint,
    which listens on the container's loopback only (the Caddyfile's global block)."""
    result = exec_in(
        "caddy", "wget", "-q", "-O", "-", "http://127.0.0.1:2019/config/apps/tls",
    )
    assert result.returncode == 0, result.stderr
    assert '"acme"' not in result.stdout, (
        f"the running base-shape proxy has a public issuer configured: {result.stdout}"
    )
