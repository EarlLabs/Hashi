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

import pathlib
import re
import time

FAKE_TOKEN = "e2e-caddy-token-7b48fa02"
PATH = f"/sub/{FAKE_TOKEN}"
SITE = "localhost"  # what deploy/docker-compose.e2e.yml configures the stack with

REPO = pathlib.Path(__file__).resolve().parents[3]


def e2e_env(key: str) -> str:
    """One value out of the stack's own env file, rather than repeated here.

    M7 gave Caddy a second site block with its own name and its own port. Writing
    either of them here as well would be two places to change, and the failure of
    getting it wrong is a request that matches no site — which reads as "the log is
    clean" and proves nothing about the block it was meant to exercise.
    """
    text = (REPO / "deploy" / "e2e.env").read_text()
    match = re.search(rf"^{key}=(\S+)$", text, re.M)
    assert match, f"deploy/e2e.env does not set {key}"
    return match.group(1)


def private_port() -> str:
    return e2e_env("HASHI_PRIVATE_PORT")


PRIVATE_NAME = e2e_env("HASHI_PRIVATE_HOST")


# Reached by the loopback address the console's site block also answers to. The
# console is addressed by IP rather than by name throughout the e2e stack (see
# deploy/e2e.env), and the site block lists both that address and loopback.
PRIVATE = f"127.0.0.1:{private_port()}"


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
    log proves only that nothing happened.

    Asked of a token too short to be one. M7 left the public site serving ``/sub/*``
    and 404ing everything else, so ``/healthz`` — which this guard used to ask for —
    is now Caddy's own empty 404 and is indistinguishable from the control plane's
    404 for a token that does not exist. A token under the route's minimum length is
    refused on FORMAT, before any lookup, and the body that comes back could only
    have been written by the application behind the proxy.
    """
    result = exec_in("caddy", "wget", "-q", "-O-", "--no-check-certificate",
                     "--tries=1", "--timeout=5", "--server-response",
                     f"https://{SITE}/sub/short")
    combined = result.stdout + result.stderr
    assert "422" in combined, (
        f"Caddy did not proxy the delivery endpoint to the control plane:\n{combined}"
    )


def test_the_proxy_actually_serves_the_console_on_the_private_site(exec_in) -> None:
    """The same guard for the site block M7 added.

    A private site that served nothing would keep a perfectly clean log, and the
    scenario below would pass while the console's own logger was never once
    exercised. The login page is the one console page an unauthenticated request
    reaches, so a 200 here is the control plane answering.
    """
    result = exec_in("caddy", "wget", "-q", "-O-", "--no-check-certificate",
                     "--tries=1", "--timeout=5", f"https://{PRIVATE}/panel/login")
    assert result.returncode == 0, (
        f"Caddy is not serving the console on the private site:\n{result.stderr}"
    )
    assert "<form" in result.stdout.lower(), (
        f"the private site answered, but not with the login page: {result.stdout[:400]!r}"
    )


def test_caddy_writes_no_request_uri_to_its_log(exec_in, logs_of) -> None:
    """Both loggers: the site block, and the default one that catches the rest."""
    before = len(logs_of("caddy"))

    request_inside_caddy(exec_in, f"https://{SITE}{PATH}")       # proxied — site logger
    # The second delivery shape (item 27), through the proxy. A query string is a
    # separate field in Caddy's log format from the path, so a rule that strips one can
    # leave the other — and the token is still in the path either way.
    request_inside_caddy(exec_in, f"https://{SITE}{PATH}?format=client-config-file")
    request_inside_caddy(exec_in, f"http://{SITE}{PATH}")        # 308 to https
    request_inside_caddy(exec_in, f"http://127.0.0.1{PATH}")     # no site matches
    request_inside_caddy(exec_in, f"https://127.0.0.1{PATH}",
                         host_header="scanner.example")          # default logger
    # M7's third block. A token-shaped path on the CONSOLE's site is 404 there, but it
    # still passes through that block's own logger — and a site added without a `log`
    # directive of its own is exactly how this rule stops holding.
    request_inside_caddy(exec_in, f"https://{PRIVATE}{PATH}")
    request_inside_caddy(exec_in, f"https://{PRIVATE}{PATH}",
                         host_header=PRIVATE_NAME)

    time.sleep(1.0)  # Caddy's logger is asynchronous; do not read it too early

    written = logs_of("caddy")[before:]
    assert FAKE_TOKEN not in written, (
        "Caddy logged a request URI containing a bearer token:\n" + written[:2000]
    )
    assert "/sub/" not in written, f"Caddy is logging request paths:\n{written[:2000]}"
