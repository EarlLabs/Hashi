"""The other half of "never log who connected to what".

WHAT: proves the reverse proxy writes no request URI to its container log.
WHY:  Caddy sees every subscription request before the control plane does, and
      a subscription token is a bearer credential carried in the URL path. Two
      loggers can leak it and BOTH are silenced in the Caddyfile: the per-site
      one, and the DEFAULT one — which handles every request that matches no
      site block (a scan by IP, another name pointing here) plus every
      http.log.error, including the 502s a friend sees while the control plane
      restarts. The control-plane half of this rule is pinned separately in
      tests/e2e/control/; either log alone is enough to burn someone.
HOW:  drives requests from INSIDE the caddy container, because Caddy is
      deliberately unpublished — the base stack exposes it to a real deployment,
      never to a laptop. The request that matters is the one that is genuinely
      PROXIED (https, matching site name), because a request Caddy turns away at
      the door never reaches the site's logger and so proves nothing about it;
      the e2e overlay names the site `localhost` precisely so Caddy can serve it
      with its internal CA. Then greps the container log for the token.

Boundary: real caddy + control + postgres. Nothing stubbed, nothing external.
          The certificate is Caddy's own internal CA, not a public one — this
          says nothing about ACME or about a real deployment's TLS.
"""

import time

FAKE_TOKEN = "e2e-caddy-token-7b48fa02"
PATH = f"/sub/{FAKE_TOKEN}"
SITE = "localhost"  # what deploy/docker-compose.e2e.yml configures the stack with


def request_inside_caddy(exec_in, url: str, host_header: str | None = None):
    """Ask Caddy for a token-shaped path. The response does not matter; what
    Caddy writes down does."""
    argv = ["wget", "-q", "-O", "/dev/null", "--no-check-certificate",
            "--tries=1", "--timeout=5"]
    if host_header:
        argv += ["--header", f"Host: {host_header}"]
    return exec_in("caddy", *argv, url)


def test_the_proxy_actually_serves_the_control_plane(exec_in) -> None:
    """Guard for the scenario below: if Caddy is not really proxying, a clean
    log proves only that nothing happened."""
    result = exec_in("caddy", "wget", "-q", "-O-", "--no-check-certificate",
                     "--tries=1", "--timeout=5", f"https://{SITE}/healthz")
    assert result.returncode == 0, f"Caddy is not serving the site:\n{result.stderr}"
    assert '"status":"ok"' in result.stdout.replace(" ", ""), (
        f"Caddy answered, but not from the control plane: {result.stdout!r}"
    )


def test_caddy_writes_no_request_uri_to_its_log(exec_in, logs_of) -> None:
    """Both loggers: the site block, and the default one that catches the rest."""
    before = len(logs_of("caddy"))

    request_inside_caddy(exec_in, f"https://{SITE}{PATH}")       # proxied — site logger
    request_inside_caddy(exec_in, f"http://{SITE}{PATH}")        # 308 to https
    request_inside_caddy(exec_in, f"http://127.0.0.1{PATH}")     # no site matches
    request_inside_caddy(exec_in, f"https://127.0.0.1{PATH}",
                         host_header="scanner.example")          # default logger

    time.sleep(1.0)  # Caddy's logger is asynchronous; do not read it too early

    written = logs_of("caddy")[before:]
    assert FAKE_TOKEN not in written, (
        "Caddy logged a request URI containing a bearer token:\n" + written[:2000]
    )
    assert "/sub/" not in written, f"Caddy is logging request paths:\n{written[:2000]}"
