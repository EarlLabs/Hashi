"""The reverse proxy's configuration, read as structure rather than as text — M7.

WHAT: parses ``deploy/caddy/Caddyfile`` into its top-level blocks and checks the
      properties that make the public/private split safe: what each site serves,
      and that every one of them throws its access log away.
WHY:  M7 turned one site block into three, and the log-discard rule is now a rule
      about a SET of blocks rather than about a file. "Remember to add the log
      block" is not a control: a new site added a year from now — a status page, a
      second delivery name, an ACME-only listener — inherits nothing, and Caddy's
      default is to write every request URI to stderr. A request URI here contains
      a subscription token, and a subscription token is a bearer credential, so the
      forgotten block writes a live key into the container log on disk.

      The companion check lives in tests/e2e/infra/test_caddy_discards_access_logs.py
      and drives real requests through a real Caddy. That one proves the file we
      ship behaves; this one proves the next edit cannot quietly stop behaving.
HOW:  a brace-depth walk over the file, not a regex over the whole text. The
      difference matters: a regex asking "does the word discard appear" is
      satisfied by one block having it, which is precisely the failure being
      guarded against.

Nothing here boots anything. What Caddy actually does with this file is the e2e
tier's question.
"""

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
CADDYFILE = REPO / "deploy" / "caddy" / "Caddyfile"

# The delivery endpoint, which is the only thing a user ever asks this proxy for.
PUBLIC_PATHS = {"/sub/*"}
# The console: the panel, the API it drives, and the panel's own assets.
PRIVATE_PATHS = {"/panel/*", "/api/*", "/static/*"}


def strip_comments(text: str) -> str:
    """Comment lines only.

    Not a general `#`-to-end-of-line strip: this file's comments explain at length
    what the directives beside them must never do, and a stripper that ate inline
    text would start matching prose. No directive here carries a trailing comment.
    """
    return "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("#")
    )


class Block:
    """One top-level block: its header line and the lines inside its braces."""

    def __init__(self, header: str, body: str) -> None:
        self.header = header.strip()
        self.body = body

    @property
    def is_global(self) -> bool:
        """Caddy's global options block is the one with no site address."""
        return self.header == ""

    def __repr__(self) -> str:  # pragma: no cover - test failure output only
        return f"<block {self.header or 'global options'!r}>"


def parse_blocks(text: str) -> list[Block]:
    """Split into top-level blocks by brace depth.

    Deliberately dumb. It is not a Caddyfile parser and must not become one — its
    whole job is to answer "which top-level blocks exist and what is in each",
    which is the shape of the rule being enforced.
    """
    blocks: list[Block] = []
    depth = 0
    header = ""
    body: list[str] = []
    for line in strip_comments(text).splitlines():
        opens = line.count("{") - line.count("}")
        if depth == 0:
            if not line.strip():
                continue
            assert line.rstrip().endswith("{"), (
                f"a top-level line is not a block header: {line!r}. This parser expects "
                "one block per `header {` line, which is how the rest of the file is "
                "written."
            )
            header = line.rsplit("{", 1)[0]
            body = []
            depth += opens
            continue
        depth += opens
        if depth == 0:
            blocks.append(Block(header, "\n".join(body)))
        else:
            body.append(line)
    assert depth == 0, "unbalanced braces in the Caddyfile"
    return blocks


@pytest.fixture(scope="module")
def blocks() -> list[Block]:
    return parse_blocks(CADDYFILE.read_text())


@pytest.fixture(scope="module")
def sites(blocks: list[Block]) -> list[Block]:
    found = [block for block in blocks if not block.is_global]
    assert found, "the Caddyfile defines no site at all"
    return found


@pytest.fixture(scope="module")
def site_by_paths(sites: list[Block]) -> dict[frozenset[str], Block]:
    """Sites keyed by the set of paths they proxy — never by their position.

    Keyed on behaviour so that reordering the file, or renaming a matcher, does not
    silently retarget an assertion at the wrong block.
    """
    return {frozenset(re.findall(r"/[\w/*.-]+", served(site))): site for site in sites}


def served(site: Block) -> str:
    """The named-matcher line that says which paths this site proxies, if any."""
    match = re.search(r"^\s*@\w+\s+path\s+(.*)$", site.body, re.M)
    return match.group(1) if match else ""


def test_the_global_block_discards_the_default_logger(blocks: list[Block]) -> None:
    """The logger that catches everything no site block matched.

    A scan by IP, another name pointing at this host, and every ``http.log.error`` —
    including the 502s a user sees while the control plane restarts, which is
    exactly when a user is refreshing a subscription. All of it lands on stderr
    with the full URI unless this is here.
    """
    globals_ = [block for block in blocks if block.is_global]
    assert len(globals_) == 1, f"expected one global options block, found {len(globals_)}"
    assert re.search(r"log\s*\{\s*output discard\s*\}", globals_[0].body, re.S), (
        "the global options block does not discard the default logger"
    )


def test_every_site_block_discards_its_own_log(sites: list[Block]) -> None:
    """THE rule this file exists for, applied per block rather than per file.

    The per-site logger is separate from the default one and neither covers the
    other. A site added without this writes every request URI it serves — and a
    request URI here carries a live subscription token.
    """
    without = [
        site.header for site in sites
        if not re.search(r"log\s*\{\s*output discard\s*\}", site.body, re.S)
    ]
    assert without == [], (
        f"these site blocks do not discard their access log: {without}. Caddy's "
        "default is to write every request URI, and a request URI here contains a "
        "subscription token, which is a bearer credential."
    )


def test_no_site_block_sends_a_log_anywhere_that_persists(sites: list[Block]) -> None:
    """`discard` is the only acceptable output, and this catches the near-misses.

    ``output file`` and ``output stderr`` both look like careful configuration and
    both write the token down. Checked separately from the rule above because a
    block could satisfy both a discard directive and a second logger beside it.
    """
    for site in sites:
        offenders = [
            output for output in re.findall(r"^\s*output\s+(\w+)", site.body, re.M)
            if output != "discard"
        ]
        assert offenders == [], (
            f"site {site.header!r} sends a log to {offenders} — request paths here "
            "carry bearer tokens and must not be written anywhere"
        )


def test_the_public_site_serves_the_delivery_endpoint_and_nothing_else(
    site_by_paths: dict[frozenset[str], Block],
) -> None:
    """`/sub/{token}` stays public; the panel does not.

    The first half of M7's "done when". A user refreshes their config from inside
    Russia at the exact moment a node was blocked, so this route cannot move — and
    everything else on that name has to stop answering, because the console holds
    every node key and every user credential.
    """
    public = site_by_paths.get(frozenset(PUBLIC_PATHS))
    assert public is not None, (
        f"no site proxies exactly {sorted(PUBLIC_PATHS)} — found "
        f"{[sorted(paths) for paths in site_by_paths]}"
    )
    assert "reverse_proxy" in public.body, "the public site proxies nothing"
    assert re.search(r"respond\s+404", public.body), (
        "the public site has no catch-all 404, so what it does with an unmatched path "
        "is Caddy's default rather than a decision"
    )


def test_the_console_is_on_a_separate_site_from_the_delivery_endpoint(
    site_by_paths: dict[frozenset[str], Block],
) -> None:
    """The panel, the API and the panel's assets, all on the private site.

    One site block, so a path cannot be added to the console on the public name by
    accident: the two sets are disjoint and each site 404s everything outside its
    own.
    """
    private = site_by_paths.get(frozenset(PRIVATE_PATHS))
    assert private is not None, (
        f"no site proxies exactly {sorted(PRIVATE_PATHS)} — found "
        f"{[sorted(paths) for paths in site_by_paths]}"
    )
    assert re.search(r"respond\s+404", private.body), (
        "the private site has no catch-all 404"
    )
    assert not PRIVATE_PATHS & PUBLIC_PATHS, (
        "a path is served by both sites, so the split protects nothing"
    )


def test_the_private_site_issues_its_own_certificate(
    site_by_paths: dict[frozenset[str], Block],
) -> None:
    """`tls internal`, never a public CA.

    This site has no public name and no public address, so a public issuer cannot
    validate it: Caddy would retry ACME forever and the console would never be
    served — the same failure the e2e stack hit for its own reason
    (docs/decisions.md, 2026-08-08). It also keeps the console's existence out of a
    CA's public logs.
    """
    private = site_by_paths[frozenset(PRIVATE_PATHS)]
    assert re.search(r"^\s*tls internal\s*$", private.body, re.M), (
        "the private site does not pin Caddy's internal CA"
    )


def test_automatic_redirects_are_off_so_port_80_cannot_leak_the_console(
    blocks: list[Block],
) -> None:
    """Measured against caddy:2.8.4-alpine, not assumed.

    With automatic redirects on, Caddy derives one for EVERY site name it serves —
    so port 80, which faces the whole internet, answers a request carrying the
    private host header with ``Location: https://<private host>:<private port>/…``
    and hands out the address of the console this milestone just made private.
    Turning them off costs the public site its own redirect, which is why one is
    written out by hand.
    """
    options = next(block for block in blocks if block.is_global)
    assert re.search(r"^\s*auto_https disable_redirects\s*$", options.body, re.M), (
        "automatic HTTP->HTTPS redirects are on, so port 80 answers the private "
        "site's name with its address"
    )
    assert any("redir" in site.body for site in blocks if not site.is_global), (
        "redirects are disabled globally and nothing redirects the public name to "
        "https, so a user typing http:// reaches nothing"
    )


def test_a_client_that_sends_no_sni_is_given_something_to_be_served(
    blocks: list[Block],
) -> None:
    """`default_sni`, which M7 shipped without and the first real host found missing.

    **A TLS client omits SNI whenever the host is an IP literal** — curl does, every
    browser does. The management tunnel hands the owner an address rather than a name,
    and the SSH fallback is dialled at loopback, so the console is reached without SNI
    by both of its routes. With more than one certificate on a listener and no name to
    choose between them, Caddy aborts the handshake and the console is unreachable.

    The scenario that proves the behaviour is
    tests/e2e/infra/test_a_client_that_sends_no_sni_can_reach_the_sites.py, which
    opens a real SNI-less handshake. This is the cheap half: it runs in `make test`
    with no engine, and it fails the moment the line is deleted.
    """
    options = next(block for block in blocks if block.is_global)
    match = re.search(r"^\s*default_sni\s+(\S+)\s*$", options.body, re.M)
    assert match, (
        "no default_sni: a client that sends no SNI — which is every client aimed at "
        "an IP, and the management tunnel hands out an IP — gets its handshake aborted"
    )
    assert match.group(1) == "{$HASHI_PRIVATE_HOST}", (
        f"default_sni is {match.group(1)!r}. It has to be the console's own name, or "
        "the owner meets a certificate-name mismatch on every visit to their own "
        "panel — and a literal here would be a name this deployment cannot change."
    )


def test_no_site_names_a_host_or_a_port_this_deployment_cannot_change(
    sites: list[Block],
) -> None:
    """Every address is an interpolation, with loopback the one deliberate literal.

    The rule that keeps a country, a provider or a port out of the code applies
    hardest here: a hostname or a port written into this file is a hostname or a
    port the fleet cannot rotate away from, and this file is baked into an image.

    ``127.0.0.1`` is exempt and is the only exemption. It appears twice, for two
    reasons that are both about NOT reaching a network: Caddy's admin endpoint stays
    off every interface, and the private site answers to the loopback name so that
    an `ssh -L` forward — the documented way back in when the management tunnel is
    down — arrives at a site block rather than at nothing.
    """
    for site in sites:
        address = site.header.replace("127.0.0.1", "")
        assert not re.search(r"\d", address), (
            f"the site address {site.header!r} carries a literal port or address — "
            "it belongs in the environment, like every other one"
        )
        assert "{$" in site.header, (
            f"the site address {site.header!r} names no environment variable, so this "
            "deployment's hostname is baked into the image"
        )
