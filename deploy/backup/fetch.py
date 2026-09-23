#!/usr/bin/env python3
"""Read backup artifacts back out of an object store — M28.8, the restore side.

WHAT: lists what is in the bucket and fetches one object out of it, with a credential
      supplied at the moment a restore runs. Two verbs and no third: ``list`` names what
      is there, ``get`` writes one object's bytes to stdout. Nothing here writes to the
      store, deletes from it, decrypts anything or touches a database — the artifact
      arrives as `age` ciphertext and leaves this program exactly as it came.

WHY:  this is the half of the backup that the control-plane host is deliberately unable
      to do, and keeping the two halves apart is the whole design.

      **It is a separate program from ``upload.py`` because the credentials are separate,
      and they must stay that way.** The key in ``.env`` on a live control plane may
      ``PutObject`` and nothing else: whoever seizes that box holds it, and a key that
      could read would hand them every backup the fleet ever wrote as well as the machine.
      So the read credential lives on the operator, is handed to one command on the day it
      is needed, and is named ``HASHI_RESTORE_S3_*`` rather than ``HASHI_BACKUP_S3_*``
      precisely so that no env file on a control-plane host ever has a reason to contain
      it. ``scripts/backup.sh`` refuses an env file that does.

      **The signature maths is written out again here rather than imported**, and that is
      a decision rather than an oversight. Both programs are handed to a one-off container
      as a ``-c`` ARGUMENT read from the checkout (see ``upload.py``'s header for why they
      are not baked into the image), and a ``-c`` argument is one file. Importing would
      mean a mount, a package or a rebuild, all three of which are things a restore must
      not wait on. The cost is that a change to the signature has to be made twice, and
      ``tests/infra/test_the_restore_comes_from_the_bucket.py`` pins the two against each
      other: they must produce the same signature for the same request, or the suite goes
      red.

      **The store is a field, not a provider** — same rule and same reason as the
      uploader: endpoint, region, bucket and prefix are configuration, there is no branch
      on who holds the bucket, and the only vendor-shaped strings in here are the wire
      constants of the signature (``AWS4-HMAC-SHA256``, ``aws4_request``, ``x-amz-*``).
      The listing is parsed by the LOCAL name of each XML element, with the namespace
      dropped, so a store that answers under its own namespace is read the same way.

      **Nothing printed here may become a liability.** The credential derives a signing
      key and appears in no output, no argument list and no exception; a store's error is
      reduced to its code and message; and what this program sees is an opaque blob, its
      size and a name. There is nothing about a user, a node or a connection to print.

HOW:  ``python3 fetch.py preflight`` — does the configuration resolve at all, before
      anything slow happens. ``python3 fetch.py list`` — one line per object on stdout,
      ``<last-modified>TAB<bytes>TAB<name>``, NEWEST FIRST, names relative to the prefix.
      ``python3 fetch.py get <name>`` — that object's bytes on stdout and nothing else.

      Exit codes, which ``scripts/backup.sh`` turns into its own: 0 done, 1 refused or
      failed with the reason on stderr. Every message is on stderr; stdout carries the
      listing or the artifact and nothing else, because one stray byte on stdout is a
      corrupted artifact.
"""

import hashlib
import hmac
import http.client
import ipaddress
import os
import socket
import sys
import xml.etree.ElementTree as ElementTree
from datetime import UTC, datetime
from urllib.parse import quote, urlsplit

DONE = 0
REFUSED = 1

ALGORITHM = "AWS4-HMAC-SHA256"
SERVICE = "s3"
EMPTY_BODY = hashlib.sha256(b"").hexdigest()
# Same reasoning as the uploader's: long enough for a slow link out of a country that
# throttles them, short enough that a restore cannot hang until the operator gives up.
TIMEOUT = 300
# A bucket holding a daily artifact passes a thousand objects in under three years, and a
# listing answers a thousand keys at a time in LEXICOGRAPHIC order — so a program that
# reads one page of a long history reads the OLDEST names and calls the result "newest".
# Paging is therefore correctness, not completeness. The ceiling is here so a store that
# keeps handing back a continuation token cannot spin forever.
MAX_PAGES = 50
PAGE_SIZE = "1000"

ENDPOINT = "HASHI_RESTORE_S3_ENDPOINT"
REGION = "HASHI_RESTORE_S3_REGION"
BUCKET = "HASHI_RESTORE_S3_BUCKET"
PREFIX = "HASHI_RESTORE_S3_PREFIX"
ACCESS_KEY = "HASHI_RESTORE_S3_ACCESS_KEY_ID"
SECRET_KEY = "HASHI_RESTORE_S3_SECRET_ACCESS_KEY"

# Where an address may come from when the restore-side one is not set. Only the four that
# are NOT secrets: which store, which region, which bucket, which prefix are the same
# whether you are writing or reading, they are already in the env file of a host that
# takes backups, and making an operator retype them at 3am is the step that gets typed
# wrong. The two credentials fall back to NOTHING, ever — the whole point is that the key
# on the host cannot read, so silently reaching for it would turn a clear refusal into a
# confusing one.
FALLBACK = {
    ENDPOINT: "HASHI_BACKUP_S3_ENDPOINT",
    REGION: "HASHI_BACKUP_S3_REGION",
    BUCKET: "HASHI_BACKUP_S3_BUCKET",
    PREFIX: "HASHI_BACKUP_S3_PREFIX",
}
REQUIRED = (ENDPOINT, REGION, BUCKET, ACCESS_KEY, SECRET_KEY)


class Refusal(Exception):
    """Something the operator can fix, said in one paragraph and without the credential."""


def say(message: str) -> None:
    print(message, file=sys.stderr)


def field(name: str) -> str:
    """One configuration value, from its own name or from the one it may fall back to."""
    value = os.environ.get(name, "").strip()
    if value:
        return value
    return os.environ.get(FALLBACK[name], "").strip() if name in FALLBACK else ""


def addresses_of(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Where a name points from in here, or nothing at all if it does not resolve."""
    try:
        return [ipaddress.ip_address(info[4][0]) for info in socket.getaddrinfo(host, None)]
    except (OSError, ValueError):
        return []


def configuration() -> dict[str, str]:
    """Everything the fetch needs, or a refusal naming every missing piece at once.

    All of them at once, for the same reason the uploader does it: an operator rebuilding
    under pressure is usually missing more than one, and finding out one run at a time is
    three round trips they do not have.
    """
    missing = [name for name in REQUIRED if not field(name)]
    if missing:
        credentials = [name for name in missing if name in (ACCESS_KEY, SECRET_KEY)]
        message = (
            "the restore cannot read the object store: its configuration is incomplete.\n"
            "Not set: " + ", ".join(missing) + "."
        )
        if credentials:
            message += (
                "\nThe credential a restore reads with is carried by you and handed to "
                "this command in its environment — it is never written into the env file "
                "on a control-plane host, and this command refuses one that contains it. "
                "The key in that file can only write, by design, so it is not the one to "
                "reach for here."
            )
        if [name for name in missing if name in FALLBACK]:
            message += (
                "\nThe endpoint, region and bucket may also come from the "
                "HASHI_BACKUP_S3_ block of the env file, which is where they already are "
                "on a host that was taking backups."
            )
        raise Refusal(message)

    endpoint = field(ENDPOINT).rstrip("/")
    parts = urlsplit(endpoint)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise Refusal(
            f"{ENDPOINT} is not a URL this can read from: {endpoint!r}.\n"
            "It is the object store's own endpoint, with a scheme — for example "
            "https://<the endpoint your store documents>."
        )
    if parts.scheme == "http":
        # Same rule as the upload, and the same two problems said apart: over plain http
        # the key id and the bucket's name travel in the clear even though the artifact
        # does not, and a name that does not resolve is a typo rather than a TLS question.
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
                "the path the key id and the name of the bucket these backups are in. "
                "Use https."
            )

    prefix = field(PREFIX).lstrip("/")
    if prefix and not prefix.endswith("/"):
        prefix += "/"

    return {
        "endpoint": endpoint,
        "scheme": parts.scheme,
        "netloc": parts.netloc,
        "region": field(REGION),
        "bucket": field(BUCKET),
        "prefix": prefix,
        "access_key": field(ACCESS_KEY),
        "secret_key": field(SECRET_KEY),
    }


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode(), hashlib.sha256).digest()


def canonical_query(parameters: dict[str, str]) -> str:
    """The query string as the signature sees it: sorted, and every character encoded.

    ``/`` included — a prefix like ``control/`` is ``control%2F`` here, and a store that
    recomputes the signature over the unencoded form is not the one at fault when it
    disagrees.
    """
    return "&".join(
        f"{quote(name, safe='-_.~')}={quote(value, safe='-_.~')}"
        for name, value in sorted(parameters.items())
    )


def signed(
    config: dict[str, str],
    method: str,
    object_key: str,
    payload_hash: str,
    *,
    query: str = "",
    now: datetime | None = None,
) -> tuple[str, dict[str, str]]:
    """The request path and headers for one signed request — signature version 4, path style.

    The same maths as ``upload.py``'s function of the same name, plus a canonical query
    string, which a listing needs and a single-object PUT does not. With ``query=""`` the
    two must agree byte for byte; a test asserts it, because the alternative is one of
    them being quietly fixed and the other not.

    Path style (``<endpoint>/<bucket>/<key>``) rather than the bucket in the hostname: the
    virtual-hosted form is a property of one provider's DNS rather than of the protocol,
    and the point of this whole block is that the store is replaceable.
    """
    now = now or datetime.now(UTC)
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    day = now.strftime("%Y%m%d")

    path = f"{config['bucket']}/{object_key}" if object_key else config["bucket"]
    canonical_uri = "/" + quote(path, safe="/~")
    headers = {
        "host": config["netloc"],
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": timestamp,
    }
    signed_headers = ";".join(sorted(headers))
    canonical_headers = "".join(f"{name}:{headers[name].strip()}\n" for name in sorted(headers))
    canonical_request = "\n".join(
        [method, canonical_uri, query, canonical_headers, signed_headers, payload_hash]
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

    Identical in intent to the uploader's: the code is what tells an operator whether they
    have the wrong bucket, the wrong credential or one that was never allowed to read; the
    request and host identifiers are the store's own naming and are dropped.
    """
    fields = []
    for tag in ("Code", "Message"):
        opening, closing = f"<{tag}>", f"</{tag}>"
        if opening in body and closing in body:
            fields.append(body.split(opening, 1)[1].split(closing, 1)[0][:200])
    said = ": " + " — ".join(fields) if fields else ""
    return f"HTTP {status}{said}"


def opened(config: dict[str, str], method: str, object_key: str, parameters: dict[str, str]):
    """One signed request, with the response still open so a body can be streamed.

    The caller closes the connection. ``http.client`` rather than ``urllib`` for the same
    reason the uploader gives — this code needs the response the store actually sent, not
    a reconstruction of it — and because a multi-megabyte artifact is read in chunks
    rather than into memory.
    """
    query = canonical_query(parameters)
    path, headers = signed(config, method, object_key, EMPTY_BODY, query=query)
    connect = (
        http.client.HTTPSConnection
        if config["scheme"] == "https"
        else http.client.HTTPConnection
    )
    connection = connect(config["netloc"], timeout=TIMEOUT)
    try:
        # skip_host, because the Host header is one of the SIGNED headers and must reach
        # the store exactly as it was signed.
        connection.putrequest(
            method, path + (f"?{query}" if query else ""), skip_host=True,
            skip_accept_encoding=True,
        )
        for name, value in headers.items():
            connection.putheader(name, value)
        connection.putheader("Content-Length", "0")
        connection.endheaders()
        return connection, connection.getresponse()
    except (OSError, http.client.HTTPException) as unreachable:
        connection.close()
        raise Refusal(f"the object store could not be reached: {unreachable}") from None


def refused(status: int, answer) -> Refusal:
    """A store's rejection, turned into the sentence that names which input is wrong."""
    said = refusal_from(status, answer.read(4096).decode("utf-8", "replace"))
    if status in (401, 403):
        return Refusal(
            "the object store refused the credential: " + said + ".\n"
            "A restore needs a credential that may LIST and GET this bucket. The one a "
            "control plane keeps in its env file may only write, on purpose — if that is "
            "the key you supplied, it is the wrong one and no key on the lost host was "
            "ever the right one."
        )
    if status == 404:
        return Refusal(
            "the object store has no such bucket or object: " + said + ".\n"
            f"The bucket is named by {BUCKET} (or by HASHI_BACKUP_S3_BUCKET in the env "
            "file), and the credential answered, so this is the name and not the key."
        )
    return Refusal("the object store did not answer with what was asked for: " + said + ".")


def _local(tag: str) -> str:
    """An XML element's name without its namespace.

    Stores answer a listing under their own document namespace, and matching on the
    namespaced name would be this code being right about one store's choice of URL.
    """
    return tag.rsplit("}", 1)[-1]


def listing(config: dict[str, str]) -> list[tuple[str, int, str]]:
    """Everything under the prefix, as ``(last-modified, bytes, name)``, newest first.

    The store's own ``LastModified`` decides the order, not the name. The name is chosen
    by whatever key wrote the object — which on a live control plane is a key an attacker
    would hold — so ordering by it would let a name decide which artifact a restore
    reaches for. The store's clock is the one thing in this exchange the host that was
    lost had no say in. Both are printed, so an operator can see when they disagree.
    """
    objects: list[tuple[str, int, str]] = []
    token = ""
    for _ in range(MAX_PAGES):
        parameters = {"list-type": "2", "max-keys": PAGE_SIZE}
        if config["prefix"]:
            parameters["prefix"] = config["prefix"]
        if token:
            parameters["continuation-token"] = token
        connection, answer = opened(config, "GET", "", parameters)
        try:
            if answer.status != 200:
                raise refused(answer.status, answer)
            document = ElementTree.fromstring(answer.read())
        except ElementTree.ParseError:
            raise Refusal(
                "the store answered the listing with something that is not a listing. "
                f"Is {config['endpoint']} really an object-store endpoint?"
            ) from None
        finally:
            connection.close()

        truncated, token = False, ""
        for element in document:
            name = _local(element.tag)
            if name == "IsTruncated":
                truncated = (element.text or "").strip().lower() == "true"
            elif name == "NextContinuationToken":
                token = (element.text or "").strip()
            elif name == "Contents":
                entry = {_local(child.tag): (child.text or "").strip() for child in element}
                key, size = entry.get("Key", ""), entry.get("Size", "0")
                # A key that is a folder marker, or an object with no bytes in it, is not
                # an artifact. Both exist in real buckets and neither would ever open.
                if not key or key.endswith("/") or not size.isdigit() or int(size) == 0:
                    continue
                objects.append(
                    (entry.get("LastModified", ""), int(size), key[len(config["prefix"]):])
                )
        if not truncated or not token:
            break

    objects.sort(reverse=True)
    return objects


def get(config: dict[str, str], name: str) -> None:
    """One object's bytes onto stdout, in chunks, and nothing else onto stdout ever."""
    object_key = config["prefix"] + name
    say(f"fetching {config['netloc']}/{config['bucket']}/{object_key}…")
    connection, answer = opened(config, "GET", object_key, {})
    try:
        if answer.status != 200:
            raise refused(answer.status, answer)
        written = 0
        while chunk := answer.read(1024 * 1024):
            sys.stdout.buffer.write(chunk)
            written += len(chunk)
        sys.stdout.buffer.flush()
    finally:
        connection.close()
    if written == 0:
        raise Refusal(f"{name} is in the bucket and is empty. There is nothing to restore.")
    say(f"{written} bytes read back.")


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else ""
    if mode not in ("preflight", "list", "get"):
        say("usage: fetch.py preflight | fetch.py list | fetch.py get <object-name>")
        return REFUSED

    try:
        config = configuration()
        if mode == "preflight":
            say(
                f"reading from {config['netloc']}/{config['bucket']}/{config['prefix']} — "
                "the configuration resolves. Whether the credential is allowed to read it "
                "is only known when the store is asked."
            )
            return DONE
        if mode == "list":
            found = listing(config)
            if not found:
                raise Refusal(
                    "the store answered, and there is nothing under "
                    f"{config['bucket']}/{config['prefix']}.\n"
                    "The credential works — this is the bucket or the prefix. A backup "
                    "written with a different HASHI_BACKUP_S3_PREFIX is under that "
                    "prefix and not this one."
                )
            for modified, size, name in found:
                print(f"{modified}\t{size}\t{name}")
            return DONE
        if len(argv) < 2 or not argv[1]:
            raise Refusal("no object name was given, so there is nothing to fetch.")
        get(config, argv[1])
    except Refusal as refusal:
        say(str(refusal))
        return REFUSED
    return DONE


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
