#!/usr/bin/env python3
"""Send one already-encrypted backup artifact to an object store — M28.3.

WHAT: signs and makes exactly one request, ``PUT <bucket>/<prefix><name>``, against the
      S3-protocol endpoint named in the environment, and says what the store answered.
      The artifact arrives on stdin, already `age` ciphertext; nothing here encrypts,
      decrypts, reads an object back, lists a bucket or deletes anything, and there is no
      code path that could. Run by ``scripts/backup.sh`` inside a one-off control
      container, never by the application.

WHY:  four decisions are worth the reader's time.

      **The store is a field, not a provider.** Endpoint, region, bucket and prefix are
      configuration; there is no branch on who holds the bucket and no name of a company
      anywhere in this file, exactly as a node's country and address are node-record data
      (CLAUDE.md, hard rules). A provider you cannot rotate away from is one you are stuck
      with on the day you need to leave it — and that day is the day this project exists
      for. The only vendor-shaped strings here are ``AWS4-HMAC-SHA256``, ``aws4_request``
      and the ``x-amz-*`` header names: those are the wire format of the signature every
      S3-compatible store implements, in the same way ``age-encryption.org/v1`` is the
      first line of every artifact. They identify a protocol, not a supplier.

      **No SDK and no package on the host.** ``pyproject.toml`` is architect territory, so
      a step does not add a dependency; and a restore host is rented an hour before it is
      used, so it must need nothing installed. The signature is HMAC-SHA256 over a
      canonical string, which is ``hashlib`` and ``hmac``, and the request is one PUT,
      which is ``http.client`` — all of it already inside the control image, because that
      image is a Python image. What was rejected: an S3 client library (a dependency, and not a
      step's decision); a vendor CLI (a package to install, and a provider's name in a
      command); and the same thing in shell with ``curl`` and ``openssl`` (the image ships
      neither curl nor a signing helper, and a chain of hex HMACs in bash is the last
      place an authentication bug should live).

      **The credential can only write, so this cannot check its own work by reading.**
      ``HASHI_BACKUP_S3_ACCESS_KEY_ID`` is a PutObject-and-nothing-else key on purpose —
      an attacker who holds the control plane holds this key, and a key that can delete
      turns a seizure into the loss of every backup as well as the machine. So "it landed"
      is judged from the response and from nothing else: a 2xx to a request whose SHA-256
      of the body is inside the signature, which a conforming store recomputes before it
      accepts the object, plus the returned ETag compared against the same bytes whenever
      the store returns one that is comparable. That is a strong statement about the bytes
      the store received and accepted. It is NOT a statement that the object is still
      there a minute later, that retention or versioning is configured, or that a restore
      will find it — none of which this host can ever observe, by design. Whoever prints
      this output must not round it up.

      **Nothing printed here may become a liability.** The secret is used to derive a
      signing key and never appears in output, in an argument list or in an exception; a
      store's error is reduced to its code and message rather than echoed whole; and there
      is nothing about a user, a node or a connection to print in the first place — this
      program sees an opaque blob, its size and a file name.

HOW:  ``python3 upload.py preflight`` — decide whether an upload will be attempted at all
      and whether its configuration is complete, before ``scripts/backup.sh`` touches the
      database. ``python3 upload.py put <object-name>`` — send stdin under that name,
      below the configured prefix.

      Exit codes, which ``scripts/backup.sh`` turns into its own: 0 done (or, for
      preflight, "configuration resolves"), 10 the offsite upload is switched off, 1
      refused or failed with the reason on stderr. All output is on stderr; stdout stays
      empty, because every other stage of that script's pipeline is byte-clean and this
      one has no reason to be the exception.
"""

import hashlib
import hmac
import http.client
import ipaddress
import os
import socket
import sys
import tempfile
from datetime import UTC, datetime
from urllib.parse import quote, urlsplit

DONE = 0
REFUSED = 1
SWITCHED_OFF = 10

ALGORITHM = "AWS4-HMAC-SHA256"
SERVICE = "s3"
EMPTY_BODY = hashlib.sha256(b"").hexdigest()
# Long enough for a slow link out of a country that throttles them, short enough that a
# backup job cannot hang until the next one starts.
TIMEOUT = 300

ENDPOINT = "HASHI_BACKUP_S3_ENDPOINT"
REGION = "HASHI_BACKUP_S3_REGION"
BUCKET = "HASHI_BACKUP_S3_BUCKET"
PREFIX = "HASHI_BACKUP_S3_PREFIX"
ACCESS_KEY = "HASHI_BACKUP_S3_ACCESS_KEY_ID"
SECRET_KEY = "HASHI_BACKUP_S3_SECRET_ACCESS_KEY"
REQUIRED = (ENDPOINT, REGION, BUCKET, ACCESS_KEY, SECRET_KEY)

TRUTHY = {"1", "true", "yes", "on"}


class Refusal(Exception):
    """Something the operator can fix, said in one paragraph and without the secret."""


def say(message: str) -> None:
    print(message, file=sys.stderr)


def switched_on() -> bool:
    return os.environ.get("HASHI_BACKUP_ENABLED", "").strip().lower() in TRUTHY


def addresses_of(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Where a name points from in here, or nothing at all if it does not resolve.

    Asked for one thing: deciding whether a plain-``http`` endpoint is acceptable. Over
    http the signature and the key id travel in the clear — the secret never does, and the
    body is already `age` ciphertext, so this is not a catastrophe, but it hands anybody on
    the path the bucket a control plane backs up to. On a private network there is nobody
    on the path, and that is exactly where a disposable test endpoint lives.
    """
    try:
        return [ipaddress.ip_address(info[4][0]) for info in socket.getaddrinfo(host, None)]
    except (OSError, ValueError):
        return []


def configuration() -> dict[str, str]:
    """Everything the upload needs, or a refusal naming every missing piece at once.

    All of them at once deliberately: a host being set up offsite for the first time is
    usually missing three of these, and being told about them one run at a time is three
    dumps and three trips to the env file.
    """
    missing = [name for name in REQUIRED if not os.environ.get(name, "").strip()]
    if missing:
        raise Refusal(
            "the offsite upload is switched on and its configuration is incomplete.\n"
            "Not set in the env file: " + ", ".join(missing) + ".\n"
            "See the backup block in .env.example — the credential there must be "
            "write-only (PutObject and nothing else)."
        )

    endpoint = os.environ[ENDPOINT].strip().rstrip("/")
    parts = urlsplit(endpoint)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise Refusal(
            f"{ENDPOINT} is not a URL this can send to: {endpoint!r}.\n"
            "It is the object store's own endpoint, with a scheme — for example "
            "https://<the endpoint your store documents>."
        )
    if parts.scheme == "http":
        # Two different problems, said apart: a name that does not resolve is a typo or a
        # stack with no route out, and an operator sent to look at TLS for it loses an hour.
        addresses = addresses_of(parts.hostname)
        if not addresses:
            raise Refusal(
                f"{ENDPOINT} names a host that does not resolve from inside this stack: "
                f"{parts.hostname}."
            )
        if not all(address.is_private or address.is_loopback for address in addresses):
            raise Refusal(
                f"{ENDPOINT} is plain http to an address outside a private network.\n"
                "The artifact itself is encrypted, but the request would hand anybody on "
                "the path the key id and the name of the bucket this control plane backs "
                "up to. Use https."
            )

    prefix = os.environ.get(PREFIX, "").strip().lstrip("/")
    if prefix and not prefix.endswith("/"):
        # A prefix that does not end in a separator silently glues itself to the file
        # name, and the objects land beside the folder the operator believes they are in.
        prefix += "/"

    return {
        "endpoint": endpoint,
        "scheme": parts.scheme,
        "netloc": parts.netloc,
        "region": os.environ[REGION].strip(),
        "bucket": os.environ[BUCKET].strip(),
        "prefix": prefix,
        "access_key": os.environ[ACCESS_KEY].strip(),
        "secret_key": os.environ[SECRET_KEY].strip(),
    }


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode(), hashlib.sha256).digest()


def signed(
    config: dict[str, str],
    method: str,
    object_key: str,
    payload_hash: str,
    *,
    now: datetime | None = None,
) -> tuple[str, dict[str, str]]:
    """The request path and headers for one signed request — signature version 4, path style.

    Path style (``<endpoint>/<bucket>/<key>``) rather than putting the bucket in the
    hostname: the virtual-hosted form needs the store to answer for every bucket name as a
    subdomain, which is a property of one provider's DNS rather than of the protocol, and
    the whole point here is that the store is replaceable.

    The payload hash is signed, so a store that recomputes it — which a conforming one
    does — is checking the bytes it received against the bytes we meant to send, without
    this host ever being able to read the object back.
    """
    now = now or datetime.now(UTC)
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    day = now.strftime("%Y%m%d")

    canonical_uri = "/" + quote(f"{config['bucket']}/{object_key}", safe="/~")
    headers = {
        "host": config["netloc"],
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": timestamp,
    }
    signed_headers = ";".join(sorted(headers))
    canonical_headers = "".join(f"{name}:{headers[name].strip()}\n" for name in sorted(headers))
    canonical_request = "\n".join(
        [method, canonical_uri, "", canonical_headers, signed_headers, payload_hash]
    )

    scope = f"{day}/{config['region']}/{SERVICE}/aws4_request"
    to_sign = "\n".join(
        [ALGORITHM, timestamp, scope, hashlib.sha256(canonical_request.encode()).hexdigest()]
    )
    key = _hmac(("AWS4" + config["secret_key"]).encode(), day)
    for piece in (config["region"], SERVICE, "aws4_request"):
        key = _hmac(key, piece)
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()

    headers["authorization"] = (
        f"{ALGORITHM} Credential={config['access_key']}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return canonical_uri, headers


def refusal_from(status: int, body: str) -> str:
    """What the store said, reduced to the two fields that help and nothing else.

    An S3 error body is XML carrying a code, a message and a pile of identifiers for the
    request and the host that served it. The code is what tells an operator whether they
    have the wrong key, the wrong bucket or a key that was never allowed to write; the
    identifiers are noise here and would put the store's own naming into whatever reads
    this output later.
    """
    fields = []
    for tag in ("Code", "Message"):
        opening, closing = f"<{tag}>", f"</{tag}>"
        if opening in body and closing in body:
            fields.append(body.split(opening, 1)[1].split(closing, 1)[0][:200])
    said = ": " + " — ".join(fields) if fields else ""
    return f"HTTP {status}{said}"


def send(config: dict[str, str], path: str, headers: dict[str, str], body, size: int):
    """One PUT over a connection this code owns, so a refusal mid-body is still readable.

    Written against ``http.client`` rather than ``urllib.request`` for one reason, found by
    running it: a store that rejects the request — the wrong key, a key not allowed to
    write — answers as soon as it has the headers and closes the connection, while this
    side is still sending megabytes. urllib turns that into "connection broken" and hides
    the 403 that is already sitting in the socket. Here the write failure is caught and
    the response read anyway, so the operator is told which of their two credentials is
    wrong instead of being sent to look at the network.
    """
    connect = (
        http.client.HTTPSConnection
        if config["scheme"] == "https"
        else http.client.HTTPConnection
    )
    connection = connect(config["netloc"], timeout=TIMEOUT)
    try:
        # skip_host, because the Host header is one of the SIGNED headers and must reach
        # the store exactly as it was signed.
        connection.putrequest("PUT", path, skip_host=True, skip_accept_encoding=True)
        for name, value in headers.items():
            connection.putheader(name, value)
        connection.putheader("Content-Length", str(size))
        connection.endheaders()
        try:
            connection.send(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the answer, whatever it is, is below.
        answer = connection.getresponse()
        return answer.status, answer.headers, answer.read(4096).decode("utf-8", "replace")
    finally:
        connection.close()


def put(config: dict[str, str], name: str) -> None:
    """Read the artifact from stdin and send it, once."""
    object_key = config["prefix"] + name
    payload = hashlib.sha256()
    # Not a security claim: md5 is what the S3 protocol makes an object's ETag for a
    # single-part upload, and comparing it is a second confirmation that the bytes the
    # store kept are the bytes this host sent.
    fingerprint = hashlib.md5(usedforsecurity=False)
    size = 0

    with tempfile.TemporaryFile() as body:
        # Staged rather than streamed, because the signature covers the payload hash and
        # the request needs a content length: both are known only once the last byte has
        # been seen. It is ciphertext, it is unlinked the moment it is created, and the
        # container it lives in is deleted when this exits.
        while chunk := sys.stdin.buffer.read(1024 * 1024):
            payload.update(chunk)
            fingerprint.update(chunk)
            size += len(chunk)
            body.write(chunk)
        if size == 0:
            raise Refusal("nothing arrived on stdin, so there is no artifact to send.")
        body.seek(0)

        path, headers = signed(config, "PUT", object_key, payload.hexdigest())
        say(f"sending {size} bytes to {config['netloc']}/{config['bucket']}/{object_key}…")
        try:
            status, answered, said = send(config, path, headers, body, size)
        except (OSError, http.client.HTTPException) as unreachable:
            raise Refusal(f"the object store could not be reached: {unreachable}") from None

    if status not in (200, 201):
        raise Refusal(
            "the object store did not take it: " + refusal_from(status, said) + ".\n"
            "A refusal naming access usually means the credential is not allowed to write "
            "this key — which is the one permission it needs and the only one it should "
            "have."
        )
    etag = (answered.get("ETag") or "").strip('"')
    version = answered.get("x-amz-version-id") or ""

    if len(etag) == 32 and all(character in "0123456789abcdef" for character in etag.lower()):
        if etag.lower() != fingerprint.hexdigest():
            raise Refusal(
                "the object store kept something other than what was sent: its ETag does "
                "not match these bytes. Treat the object as not written."
            )
        confirmed = "its ETag matches the bytes sent"
    else:
        # Multipart, or server-side encryption, or a store that simply forms it another
        # way. The signed payload hash is still what was accepted, so this is a weaker
        # confirmation rather than no confirmation — and saying which one it was is the
        # difference between a fact and a habit.
        confirmed = "it returned no comparable ETag, so only the signed payload hash was checked"

    say(f"the object store accepted it ({confirmed}).")
    if version:
        say(f"object version: {version}")
    say(
        "What that proves: the store received exactly these bytes and accepted them. What "
        "it does not prove: that the object is still there, that retention keeps it, or "
        "that it can be read back — this host holds a write-only credential and cannot "
        "look."
    )


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else ""
    if mode not in ("preflight", "put"):
        say("usage: upload.py preflight | upload.py put <object-name>  (artifact on stdin)")
        return REFUSED

    if not switched_on():
        say(
            "offsite upload: OFF. HASHI_BACKUP_ENABLED is not 1, so the artifact stays on "
            "this host and nowhere else."
        )
        return SWITCHED_OFF

    try:
        config = configuration()
        if mode == "preflight":
            say(
                f"offsite upload: on, to {config['netloc']}/{config['bucket']}/"
                f"{config['prefix']} — the configuration resolves. Whether the credential "
                "is accepted is only known when the object is sent."
            )
            return DONE
        if len(argv) < 2 or not argv[1]:
            raise Refusal("no object name was given, so there is nothing to name the object.")
        put(config, argv[1])
    except Refusal as refusal:
        say(str(refusal))
        return REFUSED
    return DONE


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
