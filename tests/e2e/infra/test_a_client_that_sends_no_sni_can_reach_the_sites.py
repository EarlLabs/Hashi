"""A TLS client that sends no SNI still completes a handshake — M7, round 1.

WHAT: opens a real TLS connection to each of Caddy's two listeners with the SNI
      extension deliberately absent, and then speaks HTTP over it.
WHY:  M7 shipped, passed review, and the console could not be reached on the first
      real host — not over the tunnel and not over the SSH forward. The cause is one
      sentence: **a TLS client sends no SNI when the host is an IP literal**, that is
      true of curl and of every browser, and a management tunnel hands the owner an
      IP. With two certificates on the listener and no name to choose between them,
      Caddy aborts the handshake with an internal-error alert.

      Nothing in the suite could see it, and the reason is the lesson. The e2e stack
      gave the console a NAME (`console.localhost`), a name sends SNI, and every
      assertion passed against a question the field never asks. The stack now uses an
      IP for the same reason the field does, and these two scenarios ask the question
      directly rather than relying on whatever the test client happens to do — busybox
      wget, which every other scenario here uses, sends SNI even for an address.
HOW:  from inside the CONTROL container, because it is the only container in the stack
      with a TLS client we can aim: `ssl.SSLContext.wrap_socket(server_hostname=None)`
      omits the extension, and nothing else in the stack can be made to. Caddy's own
      image carries busybox and nothing else. The connection is made to `caddy` over
      the compose network and the Host header is set by hand, which is exactly the
      shape of an `ssh -L` forward: the TLS layer knows an address, the HTTP layer
      names one.

Boundary: real caddy + control + postgres. Nothing stubbed, nothing external.
          NOT covered: whether a user's stock client TRUSTS what it is served. An
          internal-CA certificate is refused by every stock client, which is a fact
          about certificates rather than about SNI — see the runbook, "Reaching the
          panel", on why HASHI_PUBLIC_HOST must be a name with a real record.
"""

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[3]

PUBLIC = "localhost"


def e2e_env(key: str) -> str:
    match = re.search(rf"^{key}=(\S+)$", (REPO / "deploy" / "e2e.env").read_text(), re.M)
    assert match, f"deploy/e2e.env does not set {key}"
    return match.group(1)


PRIVATE_HOST = e2e_env("HASHI_PRIVATE_HOST")
PRIVATE_PORT = e2e_env("HASHI_PRIVATE_PORT")

# The one-liner the control container runs. Written as a program rather than as a
# `curl` because the whole point is control over ONE extension: `server_hostname=None`
# is the SNI-less case, and there is no flag on any client in this stack that says so.
PROBE = """
import socket, ssl, sys

port = int(sys.argv[1])
http_host = sys.argv[2]
path = sys.argv[3]

context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
# Neither is laxness: this stack's certificates come from Caddy's own CA, which nothing
# in the control container trusts, and what is under test is whether a handshake can
# happen at all — not whom it was with.
context.check_hostname = False
context.verify_mode = ssl.CERT_NONE

raw = socket.create_connection(("caddy", port), timeout=10)
try:
    # server_hostname=None is the entire scenario. With a value, python sends SNI and
    # the question being asked disappears.
    sock = context.wrap_socket(raw, server_hostname=None)
except Exception as error:
    print("HANDSHAKE-FAILED", type(error).__name__, error)
    raise SystemExit(1)

request = f"GET {path} HTTP/1.1\\r\\nHost: {http_host}\\r\\nConnection: close\\r\\n\\r\\n"
sock.sendall(request.encode())
answer = b""
while True:
    chunk = sock.recv(4096)
    if not chunk:
        break
    answer += chunk
print(answer.decode("utf-8", "replace"))
"""


def without_sni(exec_in, port: str, http_host: str, path: str) -> str:
    """One HTTP exchange over a TLS connection that carried no SNI."""
    result = exec_in("control", "python", "-c", PROBE, port, http_host, path)
    return result.stdout + result.stderr


def test_the_console_answers_a_client_that_sent_no_sni(exec_in) -> None:
    """The field failure, reproduced as a scenario.

    Both cases that matter arrive here: a browser opening the console at the tunnel
    address, and `curl -k https://127.0.0.1:PORT/panel/login` over the SSH forward.
    Neither sends SNI, because both name an IP. Before `default_sni`, this handshake
    ended in ``tlsv1 alert internal error`` and the console was unreachable by any
    route the owner actually has.
    """
    for http_host in (f"{PRIVATE_HOST}:{PRIVATE_PORT}", f"127.0.0.1:{PRIVATE_PORT}"):
        answer = without_sni(exec_in, PRIVATE_PORT, http_host, "/panel/login")
        assert "HANDSHAKE-FAILED" not in answer, (
            f"the console refused a client that sent no SNI, addressed as {http_host} — "
            "which is every browser and every curl aimed at an IP:\n" + answer
        )
        assert " 200 " in answer.splitlines()[0], (
            f"the console handshook but did not serve the panel for {http_host}:\n{answer}"
        )
        assert "<form" in answer.lower(), (
            f"the console answered {http_host} with something other than the login page"
        )


def test_the_delivery_endpoint_answers_a_client_that_sent_no_sni(exec_in) -> None:
    """The same question of the public listener, and it had the same answer.

    A user's client dials the delivery hostname and sends SNI, so this is not the
    normal path — but a client that dials an address does not, and the owner's own
    first host had no DNS record at all. The handshake must not be the thing that
    fails: a certificate a client declines to TRUST is a different, visible problem
    with a known fix, while an aborted handshake looks like the host being down.
    """
    answer = without_sni(exec_in, "443", PUBLIC, "/sub/short")
    assert "HANDSHAKE-FAILED" not in answer, (
        "the delivery endpoint refused a client that sent no SNI — a user whose "
        "client dials an address gets no subscription at all:\n" + answer
    )
    assert " 422 " in answer.splitlines()[0], (
        "the handshake succeeded but /sub/ was not proxied to the control plane:\n"
        + answer
    )


def test_sending_sni_is_still_the_ordinary_path(exec_in) -> None:
    """Guard: the two scenarios above must be about SNI and not about the stack.

    If the console were unreachable for some other reason, both would fail and would
    be read as "SNI is still broken". This one uses the stack's ordinary client, which
    does send SNI, so a failure here says the problem is somewhere else entirely.
    """
    result = exec_in(
        "caddy", "wget", "-q", "-O-", "--no-check-certificate", "--tries=1",
        "--timeout=5", f"https://127.0.0.1:{PRIVATE_PORT}/panel/login",
    )
    assert result.returncode == 0, (
        f"the console is unreachable even WITH SNI, so the scenarios above are not "
        f"measuring SNI:\n{result.stderr}"
    )
