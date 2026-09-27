"""What a delivery host serves, and what is left behind afterwards — M27.3.

WHAT: runs the listener a delivery host runs — the pinned image, the rendered site
      configuration, the rendered compose service — over a directory holding two
      artifacts, drives every request a user's client and a scanner would make, and then
      reads everything the container runtime kept.
WHY:  "the access log is off" is a claim about a configuration file until something
      makes the requests and reads the log. It is the claim this step exists to make,
      on the host whose logs nobody reads daily: an artifact's name is how that artifact
      is fetched (``control/app/services/delivery.artifact_name`` is per host since
      M27.3), so a request line written down anywhere is a credential written down.
      The 404 paths are here for the same reason as the 200s — an unknown name is still
      a request line, and it is the one a scanner produces by the thousand.
HOW:  the real compose service ``edge.bootstrap.delivery_site`` renders, with ONE
      deliberate deviation and a second that is the point of the exercise:

      * the container is put on a bridge network with the port published to loopback
        instead of ``network_mode: host``, because a scenario may not bind a port on
        whatever machine is running the suite;
      * the log driver is put BACK to the engine's ``json-file``, which a node's own
        rendering sets to ``none``. With ``none`` there is nothing to read, and a
        scenario that proved the log was empty by making it unreadable would prove
        nothing about Caddy at all. So the belt is removed to test the braces, and that
        a node wears both is asserted in ``tests/edge/``.

Boundary: a real engine, the real pinned image, the real rendered files. It says
nothing about TLS, about a certificate, or about whether any host is reachable from
anywhere — no name is served here, and nothing in this repository makes a node run this
listener yet.
"""

import datetime
import pathlib
import socket
import subprocess
import time
import uuid

import pytest
import yaml

from edge.bootstrap import delivery_site, node_stack
from edge.bootstrap.delivery import DELIVERY_DIR
from edge.registry import SubscriptionFormat

# The two artifacts on the host: one subscription, both shapes, under a name of the
# shape ``control`` derives — 64 hex characters. Written here rather than derived,
# because what a listener does with a name must not depend on how one was arrived at.
NAME = "3f" + "c" * 62
DOCUMENT = b"dGhlLXYxLWRvY3VtZW50\n"
ARCHIVE = b"PK\x03\x04-not-a-real-archive"

# A name nothing on this host is stored under — the scanner's request, and the one a
# user whose subscription was revoked makes.
UNKNOWN = "9d" + "e" * 62

# The response headers a caller passes, which on a node are the control plane's own.
# Two of them, not the whole set: this scenario asks whether Caddy applies what it is
# given, and which headers a delivery response must carry is held against
# ``control/app/api/delivery.py`` in ``tests/control/``.
HEADERS = {"Cache-Control": "no-store, max-age=0", "X-Frame-Options": "DENY"}
ARCHIVE_FILENAME = "hashi-configs.zip"


def run(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=300, **kwargs)


def a_free_port() -> int:
    """A port nothing on this machine is using, asked of the kernel rather than picked.

    A literal would collide with whatever else the machine runs, and this project's own
    published block belongs to its stacks.
    """
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class DeliveryHost:
    """One node's delivery listener, run by a real engine out of a temporary directory."""

    def __init__(self, directory: pathlib.Path, port: int) -> None:
        self.directory = directory
        self.port = port
        self.project = f"hashi-m27-{uuid.uuid4().hex[:12]}"
        self.compose = ["docker", "compose", "-p", self.project]
        self.served = directory / "delivery"
        self.served.mkdir(parents=True, exist_ok=True)
        self.site_path = directory / "delivery-site.Caddyfile"

    def place(self) -> None:
        """Everything an apply would put on the host, at the paths it would use."""
        (self.served / f"{NAME}.txt").write_bytes(DOCUMENT)
        (self.served / f"{NAME}.zip").write_bytes(ARCHIVE)
        site = delivery_site.render_delivery_site(
            # No name and no TLS: a delivery host's name and certificate are M27.6's,
            # and a scenario cannot be given either.
            site_address=f"http://:{self.port}",
            headers=HEADERS,
            shape_headers={
                SubscriptionFormat.CLIENT_CONFIG_FILE: {
                    "Content-Disposition": f'attachment; filename="{ARCHIVE_FILENAME}"'
                }
            },
        )
        self.site_path.write_text(site)
        (self.directory / "docker-compose.yml").write_text(
            node_stack.render_compose(
                transports=[], delivery=delivery_site.compose_service(site=site)
            )
        )
        (self.directory / "docker-compose.override.yml").write_text(self._override())

    def _override(self) -> str:
        """The two deviations, as YAML through the parser rather than as text."""
        return yaml.safe_dump(
            {
                "services": {
                    delivery_site.DELIVERY_SERVICE: {
                        "network_mode": "bridge",
                        "ports": [f"127.0.0.1:{self.port}:{self.port}"],
                        "logging": {"driver": "json-file"},
                        "volumes": [
                            f"{self.site_path}:{delivery_site.DELIVERY_SITE_PATH}:ro",
                            f"{self.served}:{DELIVERY_DIR}:ro",
                        ],
                    }
                }
            },
            sort_keys=True,
        )

    def up(self) -> None:
        result = run(
            [*self.compose, "up", "-d", "--remove-orphans"], cwd=self.directory
        )
        assert result.returncode == 0, (
            "a real engine refused the compose file this project renders for a delivery "
            f"host:\n{(result.stderr or result.stdout).strip()[:2000]}"
        )

    def logs(self) -> str:
        result = run(
            [*self.compose, "logs", "--no-color", delivery_site.DELIVERY_SERVICE],
            cwd=self.directory,
        )
        return result.stdout + result.stderr

    def down(self) -> None:
        run([*self.compose, "down", "--remove-orphans", "-t", "5"], cwd=self.directory)


@pytest.fixture(scope="module")
def engine() -> str:
    """A real docker engine, or a failure that says the scenario needs one.

    Not a skip, for the reason the edge scenarios give: the offline suite cannot answer
    this question, so an engine that is absent means the answer was not obtained.
    """
    result = run(["docker", "version", "--format", "{{.Server.Version}}"])
    assert result.returncode == 0, (
        "this scenario runs a real delivery listener and there is no docker engine "
        f"here:\n{result.stderr.strip()[:500]}"
    )
    return result.stdout.strip()


@pytest.fixture(scope="module")
def host(engine: str, tmp_path_factory) -> DeliveryHost:
    running = DeliveryHost(tmp_path_factory.mktemp("delivery-host"), a_free_port())
    running.place()
    running.up()
    # Caddy binds its listener in well under this; the loop is what keeps a slow engine
    # from being reported as a listener that never came up.
    deadline = time.time() + 30
    while time.time() < deadline:
        if fetch(running, f"/sub/{NAME}").returncode == 0:
            break
        time.sleep(0.5)
    yield running
    running.down()


def fetch(running: DeliveryHost, path: str, *extra: str) -> subprocess.CompletedProcess:
    """One request, with the response headers on stdout.

    ``curl`` from this machine rather than from inside the container: a delivery host is
    reached from outside by definition, and this is the only request in this suite that
    is not made through a proxy of ours.
    """
    return run(
        [
            "curl", "--silent", "--show-error", "--include", "--max-time", "10",
            *extra, f"http://127.0.0.1:{running.port}{path}",
        ]
    )


def answered(running: DeliveryHost, path: str, *extra: str) -> str:
    result = fetch(running, path, *extra)
    assert result.returncode == 0, f"no answer for {path!r}: {result.stderr[:500]}"
    return result.stdout


def header_names(answer: str) -> tuple[str, ...]:
    """The header names of one response, lowercased and sorted, minus the ones every
    answer from any server carries — ``Date`` differs by the second and
    ``Content-Length`` by the body, and neither says anything about this host."""
    names = sorted(
        line.split(":", 1)[0].strip().lower()
        for line in answer.splitlines()
        if ":" in line and not line.startswith("HTTP/")
    )
    return tuple(one for one in names if one not in ("date", "content-length"))


# --- what it serves -------------------------------------------------------------------


def test_a_held_link_is_answered_with_that_users_document(host: DeliveryHost) -> None:
    """The request a client makes on its own, with no query at all."""
    answer = answered(host, f"/sub/{NAME}")
    assert "200" in answer.splitlines()[0], answer[:400]
    assert DOCUMENT.decode() in answer, answer[:400]


def test_the_archive_shape_is_answered_under_a_name_that_identifies_nobody(
    host: DeliveryHost,
) -> None:
    """The second shape, asked for the way the control plane's route asks for it."""
    answer = answered(host, f"/sub/{NAME}?format=client-config-file")
    assert "200" in answer.splitlines()[0], answer[:400]
    assert f'filename="{ARCHIVE_FILENAME}"' in answer, answer[:400]


def test_a_response_that_carries_a_document_carries_the_headers_it_was_given(
    host: DeliveryHost,
) -> None:
    """Both shapes: the body is a bearer credential and must not be cacheable."""
    for path in (f"/sub/{NAME}", f"/sub/{NAME}?format=client-config-file"):
        answer = answered(host, path)
        for name, value in HEADERS.items():
            assert f"{name}: {value}" in answer, f"{path}:\n{answer[:400]}"


def test_every_refusal_is_the_same_bare_answer(host: DeliveryHost) -> None:
    """Measured header for header, because this is a fingerprint question.

    A fixed set of headers on an empty 404 is a signature every delivery host would
    answer with, on the most scannable machine in the fleet. It also has to be true that
    a name nothing is stored under is answered EXACTLY as a path that was never a
    subscription — otherwise a scanner learns which names exist, which is the one thing
    the control plane's own 404 is written to hide.

    What a refusal here matches is a stock Caddy's, which is what the control plane's
    PUBLIC site answers anything that is not a subscription with. It deliberately does
    not match the control plane's own ``/sub/`` refusal: measured on 2026-09-26, that one
    carries ``cache-control``, a CSP, ``referrer-policy``, ``x-content-type-options`` and
    ``x-frame-options`` from the application's middleware, and answering like it would
    put the header set that identifies a hashi control plane on every delivery host.
    """
    refusals = {
        path: header_names(answered(host, path))
        for path in (
            f"/sub/{UNKNOWN}",
            f"/sub/{NAME}?format=there-is-no-such-shape",
            "/",
            "/panel/login",
        )
    }
    assert len(set(refusals.values())) == 1, (
        f"a delivery host answers its refusals differently from each other: {refusals}"
    )
    for path, names in refusals.items():
        for header in HEADERS:
            assert header.lower() not in names, (
                f"{path} is refused with {header!r} on it — a header this host puts on a "
                "DOCUMENT, so a refusal carrying it tells a scanner what kind of machine "
                f"refused and, between two refusals, which names exist: {names}"
            )


@pytest.mark.parametrize(
    "path",
    [
        "/sub/{unknown}",
        "/sub/{name}.txt",
        "/sub/{name}?format=there-is-no-such-shape",
        "/",
        "/panel/login",
        "/delivery/{name}.txt",
        "/../delivery/{name}.txt",
    ],
)
def test_everything_that_is_not_a_subscription_is_404(
    host: DeliveryHost, path: str
) -> None:
    """One answer for all of them, including the two that would be a disclosure.

    A 404 for an unknown name says the same thing to a scanner as it does to a revoked
    user, and the file's real path on disk is not a second way in.
    """
    answer = answered(host, path.format(name=NAME, unknown=UNKNOWN))
    assert "404" in answer.splitlines()[0], answer[:400]


# --- and what it wrote down, which is the step ------------------------------------------


def test_the_delivery_host_records_nothing_about_any_of_it(host: DeliveryHost) -> None:
    """Every request above, and then the whole of what the engine kept.

    The requests are made again here rather than relied on from the scenarios above, so
    that this one fails for its own reason when it is run alone.
    """
    for path in (
        f"/sub/{NAME}",
        f"/sub/{NAME}?format=client-config-file",
        f"/sub/{NAME}?format=v1-uri-list",
        f"/sub/{UNKNOWN}",
        "/",
        "/panel/login",
    ):
        fetch(host, path)
    # Caddy's logger is asynchronous; do not read it too early.
    time.sleep(1.0)

    written = host.logs()
    # The red half, and this scenario is worthless without it: with the node's own
    # ``driver: none`` — or a compose project this reader is not addressing — the log
    # comes back empty whatever Caddy did, and every assertion below would pass. What is
    # in it is the handful of lines Caddy writes before it applies the logging
    # configuration in the rendered site, which is also why a node's rendering does not
    # leave the engine capturing at all.
    assert written.strip(), (
        "nothing at all came back from the container log, so this scenario is not "
        "reading what the engine kept and the assertions below prove nothing"
    )
    assert NAME not in written, (
        "a delivery host wrote down the name of an artifact, which is how that artifact "
        f"is fetched:\n{written[:2000]}"
    )
    assert UNKNOWN not in written, (
        f"a delivery host wrote down the path of a request it refused:\n{written[:2000]}"
    )
    assert "/sub/" not in written, (
        f"a delivery host is logging request paths:\n{written[:2000]}"
    )


def test_the_listener_writes_nothing_into_what_it_serves(host: DeliveryHost) -> None:
    """The directory is mounted read-only and is replaced by the next apply.

    A file appearing in it would be one the control plane did not put there and would
    survive until the next push — and if it were a log, it would survive a seizure.
    """
    assert sorted(one.name for one in host.served.iterdir()) == [
        f"{NAME}.txt",
        f"{NAME}.zip",
    ]


# --- the site as a real host is given it: a name, and a certificate — M27.6 -----------
#
# Everything above runs the site on `http://:<port>`, which is what a scenario could ask
# for before this step: it has no name a public authority would issue for. What it could
# not answer is the question M27.6 is about — that a listener handed a CERTIFICATE by the
# control plane serves the same documents over TLS, takes ONE socket while doing it, and
# still writes nothing down. This runs the shape a node is actually given.


TLS_NAME = "sub.example.test"


class ServedUnderAName(DeliveryHost):
    """The same host, rendered the way an apply renders it: a bare name and a certificate.

    A self-signed certificate, and curl is pointed at it as its own authority. Nothing in
    this product validates a chain — the control plane reads the expiry and pushes the
    bytes, the daemon serves them — so a scenario that went to a real authority would be
    testing the internet.
    """

    def __init__(self, directory: pathlib.Path, port: int) -> None:
        super().__init__(directory, port)
        self.certificate_path = directory / "delivery-cert.pem"
        self.key_path = directory / "delivery-key.pem"

    def place(self) -> None:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID

        (self.served / f"{NAME}.txt").write_bytes(DOCUMENT)
        (self.served / f"{NAME}.zip").write_bytes(ARCHIVE)

        key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, TLS_NAME)])
        now = datetime.datetime.now(datetime.UTC)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=30))
            .add_extension(
                x509.SubjectAlternativeName([x509.DNSName(TLS_NAME)]), critical=False
            )
            .sign(key, hashes.SHA256())
        )
        pem = certificate.public_bytes(serialization.Encoding.PEM).decode()
        self.certificate_path.write_text(pem)
        self.key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )

        site = delivery_site.render_delivery_site(
            # A BARE NAME, which is the whole of the port answer: no port is written and
            # the daemon's own defaults decide the socket.
            site_address=TLS_NAME,
            certificate=pem,
            headers=HEADERS,
            shape_headers={
                SubscriptionFormat.CLIENT_CONFIG_FILE: {
                    "Content-Disposition": f'attachment; filename="{ARCHIVE_FILENAME}"'
                }
            },
        )
        self.site_path.write_text(site)
        (self.directory / "docker-compose.yml").write_text(
            node_stack.render_compose(
                transports=[], delivery=delivery_site.compose_service(site=site)
            )
        )
        (self.directory / "docker-compose.override.yml").write_text(self._override())

    def _override(self) -> str:
        """The deviations, and the mounts are NOT among them.

        The certificate and its key are mounted by the compose file this product renders
        — that is the thing under test — so the override names only what a scenario
        cannot have: a bridge network, a published port, and a log the engine keeps.
        """
        return yaml.safe_dump(
            {
                "services": {
                    delivery_site.DELIVERY_SERVICE: {
                        "network_mode": "bridge",
                        "ports": [f"127.0.0.1:{self.port}:{delivery_site.DELIVERY_PORT}"],
                        "logging": {"driver": "json-file"},
                        "volumes": [
                            f"{self.site_path}:{delivery_site.DELIVERY_SITE_PATH}:ro",
                            f"{self.certificate_path}:"
                            f"{delivery_site.DELIVERY_CERTIFICATE_PATH}:ro",
                            f"{self.key_path}:{delivery_site.DELIVERY_CERTIFICATE_KEY_PATH}:ro",
                            f"{self.served}:{DELIVERY_DIR}:ro",
                        ],
                    }
                }
            },
            sort_keys=True,
        )

    def listening(self) -> tuple[set[int], set[int]]:
        """Every TCP and UDP port this container holds, read from its own /proc/net.

        Asked of the kernel rather than of the configuration, because the claim is about
        what the daemon BINDS and the rendered file deliberately names no port at all.
        """
        held: list[set[int]] = []
        for family in (("tcp", "tcp6"), ("udp", "udp6")):
            ports: set[int] = set()
            for table in family:
                result = run(
                    [
                        *self.compose, "exec", "-T", delivery_site.DELIVERY_SERVICE,
                        "cat", f"/proc/net/{table}",
                    ],
                    cwd=self.directory,
                )
                for line in result.stdout.splitlines()[1:]:
                    columns = line.split()
                    if len(columns) < 4 or ":" not in columns[1]:
                        continue
                    if table.startswith("tcp") and columns[3] != "0A":
                        continue
                    ports.add(int(columns[1].split(":")[1], 16))
            held.append(ports)
        return held[0], held[1]


def fetch_over_tls(
    running: ServedUnderAName, path: str, *extra: str
) -> subprocess.CompletedProcess:
    """One HTTPS request at the name the certificate is for, resolved to the published port.

    ``--cacert`` and never ``--insecure``: half of what is under test is that the daemon
    serves the certificate it was handed, and a client that accepted any certificate
    would pass against a listener serving its own.
    """
    return run(
        [
            "curl", "--silent", "--show-error", "--include", "--max-time", "10",
            "--cacert", str(running.certificate_path),
            "--resolve", f"{TLS_NAME}:{running.port}:127.0.0.1",
            *extra, f"https://{TLS_NAME}:{running.port}{path}",
        ]
    )


@pytest.fixture(scope="module")
def named_host(engine: str, tmp_path_factory) -> ServedUnderAName:
    running = ServedUnderAName(tmp_path_factory.mktemp("named-delivery-host"), a_free_port())
    running.place()
    running.up()
    deadline = time.time() + 30
    while time.time() < deadline:
        if fetch_over_tls(running, f"/sub/{NAME}").returncode == 0:
            break
        time.sleep(0.5)
    yield running
    running.down()


def test_a_host_serves_its_users_documents_under_the_certificate_it_was_pushed(
    named_host: ServedUnderAName,
) -> None:
    """The shape a node is actually given, answered by a real daemon.

    ``--cacert`` is the assertion as much as the 200 is: the client verified against the
    certificate this scenario placed, so the daemon is serving what it was handed rather
    than one of its own.
    """
    answer = fetch_over_tls(named_host, f"/sub/{NAME}")
    assert answer.returncode == 0, (
        f"the TLS handshake or the fetch failed: {answer.stderr.strip()[:800]}"
    )
    assert "200" in answer.stdout.splitlines()[0], answer.stdout[:400]
    assert DOCUMENT.decode() in answer.stdout, answer.stdout[:400]


def test_the_listener_holds_one_socket_and_no_more(
    named_host: ServedUnderAName,
) -> None:
    """The measured answer to the port, and the reason this scenario exists.

    A delivery host always carries a user-facing transport, so every socket this holds is
    one that transport cannot have. Rendered without ``auto_https disable_redirects`` and
    ``protocols h1 h2`` the same file binds TCP 80, TCP 443 and UDP 443; the UDP one is
    the half nothing in the product could have caught, because a port number is not a
    port and the rule that keeps two transports apart treats TCP and UDP as two sockets.
    """
    tcp, udp = named_host.listening()
    assert tcp == {delivery_site.DELIVERY_PORT}, (
        f"the delivery listener holds TCP {sorted(tcp)} and the product tells the "
        f"operator it holds {delivery_site.DELIVERY_PORT} alone"
    )
    assert udp == set(), (
        f"the delivery listener holds UDP {sorted(udp)}, which nothing in this product "
        "keeps a transport off — a port number is not a port"
    )


def test_the_named_host_records_no_path_either(named_host: ServedUnderAName) -> None:
    """The step's own rule, asked again on the surface M27.6 added.

    TLS is a new layer in front of the same file server and the engine keeps this
    container's output in this scenario, so this is where a handshake or a certificate
    error that named a request would show up.
    """
    fetch_over_tls(named_host, f"/sub/{NAME}")
    fetch_over_tls(named_host, f"/sub/{UNKNOWN}")
    time.sleep(1.0)

    written = named_host.logs()
    assert written.strip(), (
        "nothing came back from the container log, so this scenario is not reading what "
        "the engine kept and the assertions below prove nothing"
    )
    assert NAME not in written, written[:2000]
    assert UNKNOWN not in written, written[:2000]
    assert "/sub/" not in written, written[:2000]


def test_a_refusal_over_tls_is_the_same_empty_404(named_host: ServedUnderAName) -> None:
    """A name that is not there and a path that was never a subscription are one answer,
    so a scanner learns neither what else runs here nor whether a name it guessed
    exists. The headers are the assertion: a fixed set on an empty body would be a
    signature every delivery host in the fleet answers with."""
    for path in (f"/sub/{UNKNOWN}", "/", "/panel/login"):
        answer = fetch_over_tls(named_host, path)
        assert answer.returncode == 0, answer.stderr[:400]
        assert "404" in answer.stdout.splitlines()[0], answer.stdout[:400]
        assert header_names(answer.stdout) == ("server",), answer.stdout[:400]
