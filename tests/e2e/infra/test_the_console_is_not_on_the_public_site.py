"""The panel is off the public name, and the delivery endpoint is still on it — M7.

WHAT: drives the real Caddy that the real Caddyfile is baked into, and asks the
      public listener for the console and the console's listener for a subscription.
WHY:  M7's first two "done when" bullets are field observations the owner makes
      from two different networks, and no suite running on one machine can stage
      that. What a suite CAN settle is the half that is about configuration rather
      than about routing: whether the site block serving the public name will hand
      out the panel at all. If it will not, the remaining question is only whether
      the port is reachable — and if it will, no firewall anywhere makes the panel
      private.

      The second scenario is the one that would be forgotten. Splitting a site is a
      cheap way to break ``/sub/{token}``, and breaking it strands every friend at
      the exact moment a node was blocked and they are refreshing their config.
HOW:  requests are made from INSIDE the caddy container, because Caddy is
      deliberately unpublished — the base stack exposes it to a real deployment,
      never to a laptop. The e2e overlay names the public site `localhost` and the
      console `console.localhost` on its own port, so both are served by Caddy's
      internal CA and neither reaches a CA on the internet.

Boundary: real caddy + control + postgres. Nothing stubbed, nothing external.
          NOT covered: reachability from a second network. Whether the console's
          port is refused from Amsterdam is the owner's observation on the two live
          hosts and must never be reported as covered here.
"""

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[3]

PUBLIC = "localhost"


def e2e_env(key: str) -> str:
    """One value out of the stack's own env file — never a second copy of it here."""
    match = re.search(rf"^{key}=(\S+)$", (REPO / "deploy" / "e2e.env").read_text(), re.M)
    assert match, f"deploy/e2e.env does not set {key}"
    return match.group(1)


PRIVATE_NAME = e2e_env("HASHI_PRIVATE_HOST")
PRIVATE_PORT = e2e_env("HASHI_PRIVATE_PORT")
# The console's site block answers to its name and to loopback; the name does not
# resolve inside the container, and the loopback address is the same block.
PRIVATE = f"127.0.0.1:{PRIVATE_PORT}"

# Every path the console is made of. `/static` is on the list because the panel
# without its stylesheet is still the panel: the pages, the forms and the node names
# are all in the HTML.
CONSOLE_PATHS = ("/panel/", "/panel/login", "/api/nodes", "/static/app.css")


def ask(exec_in, url: str, host_header: str | None = None) -> str:
    """Request a URL from inside the proxy and return the status line plus body.

    ``--server-response`` rather than an exit code, because most of what is under
    test here is a refusal: wget exits non-zero on a 404 and identically on a
    connection failure, and those two answers mean opposite things.
    """
    argv = ["wget", "-O-", "--no-check-certificate", "--tries=1", "--timeout=5",
            "--server-response"]
    if host_header:
        argv += ["--header", f"Host: {host_header}"]
    result = exec_in("caddy", *argv, url)
    return result.stdout + result.stderr


def test_the_public_name_does_not_serve_the_console(exec_in) -> None:
    """The first "done when", to the extent a single machine can settle it.

    Every console path, asked of the site block that answers the name a friend uses.
    A 404 is the right answer and it is the same answer a mistyped URL gets: nothing
    in it says the console exists somewhere else.
    """
    for path in CONSOLE_PATHS:
        answer = ask(exec_in, f"https://{PUBLIC}{path}")
        assert " 404 " in answer, (
            f"the public site answered {path} with something other than 404:\n{answer}"
        )
        assert "<html" not in answer.lower(), (
            f"the public site returned a page for {path} rather than a bare refusal:"
            f"\n{answer}"
        )


async def test_the_public_name_still_serves_a_subscription(exec_in, client) -> None:
    """The second "done when", and the one the split is most likely to have broken.

    Compared against the control plane's own answer on the published port rather
    than asserted as a bare status: what matters is that the proxy passes the route
    through unchanged, and "both say 422" is a statement about the pair. A token
    shorter than the route's minimum is refused on FORMAT, before any lookup, so
    this asks nothing about whether a token exists and carries no credential.
    """
    through_the_proxy = ask(exec_in, f"https://{PUBLIC}/sub/short")
    assert " 422 " in through_the_proxy, (
        "the public site did not pass /sub/ through to the control plane:\n"
        + through_the_proxy
    )
    direct = (await client.get("/sub/short")).status_code
    assert direct == 422, (
        f"the control plane itself answers /sub/short with {direct}, so the comparison "
        "above proves nothing about the proxy"
    )


def test_the_console_is_served_on_its_own_site(exec_in) -> None:
    """And it really is served — a private site that served nothing would pass
    every refusal above for the wrong reason."""
    answer = ask(exec_in, f"https://{PRIVATE}/panel/login")
    assert " 200 " in answer, f"the console's own site does not serve the panel:\n{answer}"
    assert "<form" in answer.lower(), (
        f"the console's site answered, but not with the login page:\n{answer[:600]}"
    )


def test_the_console_site_does_not_also_serve_subscriptions(exec_in) -> None:
    """The split cuts both ways.

    The delivery endpoint on the console's port would be a subscription URL that
    only works from inside the management tunnel — which is the one place a friend
    can never be. Refused here so it cannot be handed out by accident.
    """
    answer = ask(exec_in, f"https://{PRIVATE}/sub/short")
    assert " 404 " in answer, (
        f"the console's site serves the delivery endpoint too:\n{answer}"
    )


def test_the_public_listener_does_not_hand_out_the_console_s_address(exec_in) -> None:
    """The leak that automatic HTTP→HTTPS redirects create, measured rather than assumed.

    With them on, Caddy derives a redirect for EVERY name it serves — so port 80,
    which faces the whole internet, answers a request carrying the console's host
    header with ``Location: https://<private host>:<private port>/…``. That is the
    address of the console this milestone just made private, handed to anyone who
    asks. ``auto_https disable_redirects`` in the Caddyfile's global block is what
    closes it, and this is the scenario that would go red if it were removed.
    """
    answer = ask(exec_in, "http://127.0.0.1/panel/", host_header=PRIVATE_NAME)
    assert PRIVATE_PORT not in answer, (
        "port 80 answered the console's name with the console's port — the public "
        f"listener is advertising the private one:\n{answer}"
    )
    assert PRIVATE_NAME not in answer.replace(f"Host: {PRIVATE_NAME}", ""), (
        f"port 80 echoed the console's hostname back:\n{answer}"
    )


def test_the_public_name_still_redirects_plain_http_to_https(exec_in) -> None:
    """Disabling the automatic redirects must not have taken the public one with it.

    A friend who types the delivery hostname without a scheme, or a client that
    follows an old http link, has to arrive somewhere. This is the redirect the
    Caddyfile writes out by hand precisely because the global switch is off.
    """
    answer = ask(exec_in, f"http://{PUBLIC}/sub/short")
    assert " 308 " in answer, f"plain http on the public name does not redirect:\n{answer}"
    assert f"https://{PUBLIC}/sub/short" in answer, (
        f"the redirect does not preserve the path:\n{answer}"
    )
