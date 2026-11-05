#!/usr/bin/env python3
"""Mint the stand's leaf + bot AmneziaWG configs, per run, into a throwaway dir — M40.

WHAT: two config files written to ``.e2e/artifacts/egress/`` — ``leaf.conf`` (the
      forwarding leaf the bot's egress sidecar dials) and ``awg0.conf`` (the sidecar's
      own client end). A fresh keypair pair + pre-shared key every run, plus a fresh set
      of AmneziaWG obfuscation values, so the e2e proof is reproducible and nothing with
      a private key in it is ever committed.
WHY:  M40 makes the bot's internet-bound traffic leave through a leaf over AmneziaWG. The
      stand needs BOTH ends of that hop to exist before the stack boots, and generating
      them here — rather than committing them — is the same rule the rest of this project
      lives by: no key material in git, ever (CLAUDE.md). The leaf end is rendered by the
      REAL edge renderer (``render_server`` + ``server.j2`` + ``egress.py`` hooks), so the
      stand exercises the forwarding/NAT rules a real leaf would carry rather than a
      hand-written stand-in — see ``LEAF_EGRESS`` for why that policy is RELAY here and not
      LOCAL. The sidecar end is the container-client shape the PoC proved (``Table = off`` +
      ``ip route replace default``), which has no control-plane renderer yet — minting it
      through the control plane's credential machinery is M40.2.
HOW:  run from the repo root by ``make e2e-up`` before it brings the stack up. Keys are
      X25519, derived with ``cryptography`` (asyncssh already depends on it) — verified
      byte-for-byte against ``awg pubkey``, so no container is needed to make them. The
      output dir is under ``.e2e/artifacts/``, which is gitignored.

NOT a node's config. The leaf here forwards to the stand's fake Telegram on an isolated
private network, never to a real exit. A real leaf's config is operator-supplied on the host
(``deploy/egress/``) until M40.2 mints it.
"""

import base64
import secrets
import uuid
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from edge.egress import Egress
from edge.node import Credential, NodeView
from edge.transports.amneziawg.render import render_server

# The leaf's egress policy — M40. Egress.RELAY, not Egress.LOCAL, and the choice is forced by
# a docker fact rather than preference. LOCAL (a user-facing leaf) DROPS every private
# destination, so the fake would have to sit at a globally-routable address to be forwarded —
# and the only such address safe to use is 192.88.99.0/24, which the hop scenario
# (tests/e2e/edge/test_a_user_exits_at_the_leaf_and_not_at_the_entry.py) already creates as a
# docker network for its whole run. Two networks with the same subnet is "Pool overlaps", so a
# LOCAL stand leaf would break that scenario — and other e2e scenarios must stay green. RELAY
# (the far-end-of-a-hop policy: forward + masquerade, no private drops) forwards a private fake,
# so the egress network can be an ordinary private /24 that collides with nothing. It is also
# exactly the shape the PoC leaf.conf proved. The production config M40.2 mints should still be
# LOCAL — that is a real leaf, reaching the real internet, where the drops belong.
LEAF_EGRESS = Egress.RELAY

# Where the two configs land. Under .e2e/artifacts/, which .gitignore already excludes, so
# a file with a private key in it cannot reach history even by accident.
OUT_DIR = Path(__file__).resolve().parent / "artifacts" / "egress"

# The hop's own tunnel range — a private /24, the leaf first and the sidecar second. Not a
# node's range and never routed: it only exists inside this stand. 1280, the MTU M40
# mandates (a tunnel inside a tunnel fragments at the default — edge rulebook's trap).
LEAF_TUNNEL = "10.90.0.1/24"
BOT_TUNNEL = "10.90.0.2/24"
MTU = 1280
# Where the sidecar dials the leaf. The service name resolves on the compose default
# network both share, and the port is the leaf's ListenPort below — a name here, not an
# address, because the stand's leaf has no fixed IP worth pinning.
LEAF_ENDPOINT = "leaf:51820"
LEAF_PORT = 51820


def _keypair() -> tuple[str, str]:
    """A WireGuard keypair as (private, public), standard base64.

    X25519 clamps on scalar-mult exactly as wg does on load, so the public half derived
    here is the one ``awg`` derives from the same private key — checked against ``awg
    pubkey`` when this was written, which is why no container is needed to mint keys.
    """
    private = X25519PrivateKey.generate()
    raw_private = private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    raw_public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(raw_private).decode(), base64.b64encode(raw_public).decode()


def _obfuscation() -> dict[str, int]:
    """One fresh set of AmneziaWG obfuscation values, valid and per-run.

    Shared by both ends of this one hop — the four magic headers MUST match for the
    handshake to complete, and are generated once here for that reason. Fresh each run
    rather than fixed, because a value shared across runs (or across the fleet) is itself
    the fingerprint the obfuscation exists to remove (params.py says the same).
    """
    headers: list[int] = []
    while len(set(headers)) < 4:
        headers = [secrets.randbelow(2**32 - 1) + 1 for _ in range(4)]
    minimum = secrets.randbelow(100) + 1
    return {
        "junk_packet_count": secrets.randbelow(10) + 1,
        "junk_packet_min_size": minimum,
        "junk_packet_max_size": minimum + secrets.randbelow(900) + 100,
        "init_packet_magic_header": headers[0],
        "response_packet_magic_header": headers[1],
        "underload_packet_magic_header": headers[2],
        "transport_packet_magic_header": headers[3],
    }


def _bot_config(private_key: str, leaf_public_key: str, preshared_key: str,
                obfuscation: dict[str, int]) -> str:
    """The egress sidecar's own client config — the PoC's proven container-client shape.

    NOT rendered by edge: ``Table = off`` plus ``ip route replace default dev %i`` is the
    answer to a container's read-only ``/proc/sys``, where awg-quick's own
    ``AllowedIPs = 0.0.0.0/0`` auto-routing fails. This is the hand-made/scripted end M40.2
    will replace with one the control plane mints. The junk/header values match the leaf's
    because the handshake needs the four headers to.
    """
    lines = [
        "# Generated per run by .e2e/gen_egress_configs.py — throwaway, never committed.",
        "[Interface]",
        f"PrivateKey = {private_key}",
        f"Address = {BOT_TUNNEL}",
        f"MTU = {MTU}",
        # The sidecar's routes are its own to install: Table = off stops awg-quick touching
        # the main table (which it cannot, read-only /proc/sys in a container), and the hook
        # points the default route at the tunnel so everything but the connected compose
        # subnet — the shared DB — leaves through the leaf.
        "Table = off",
        "PostUp = ip route replace default dev %i",
        "PostDown = ip route del default dev %i || true",
        f"Jc = {obfuscation['junk_packet_count']}",
        f"Jmin = {obfuscation['junk_packet_min_size']}",
        f"Jmax = {obfuscation['junk_packet_max_size']}",
        f"H1 = {obfuscation['init_packet_magic_header']}",
        f"H2 = {obfuscation['response_packet_magic_header']}",
        f"H3 = {obfuscation['underload_packet_magic_header']}",
        f"H4 = {obfuscation['transport_packet_magic_header']}",
        "",
        "[Peer]",
        f"PublicKey = {leaf_public_key}",
        f"PresharedKey = {preshared_key}",
        f"Endpoint = {LEAF_ENDPOINT}",
        # Everything is routed to the leaf; it decides where it goes next. Safe here because
        # Table = off means no route is installed from this line — only the PostUp hook adds
        # one — so the sidecar's own compose-subnet traffic (the DB) stays on eth0.
        "AllowedIPs = 0.0.0.0/0",
        "PersistentKeepalive = 25",
        "",
    ]
    return "\n".join(lines)


def _leaf_config(leaf_private: str, leaf_public: str, preshared_key: str,
                 bot_public: str, obfuscation: dict[str, int]) -> str:
    """The forwarding leaf, through the real edge renderer — server.j2 + egress.py hooks.

    ``LEAF_EGRESS`` (RELAY) decides the rules; see its definition for why RELAY and not LOCAL.
    Still the real rendering path — the stand proves server.j2 + egress.py produce a leaf that
    forwards and masquerades the bot's traffic on to the fake.
    """
    node = NodeView(
        id="stand-leaf",
        address="leaf",
        location_label="Stand",
        display_name="leaf",
        resolver=None,
    )
    params = {
        "private_key": leaf_private,
        "public_key": leaf_public,
        "preshared_key": preshared_key,
        "tunnel_address": LEAF_TUNNEL,
        "peer_tunnel_address": BOT_TUNNEL,
        "port": LEAF_PORT,
        "mtu": MTU,
        "client_dns": (),
        **obfuscation,
    }
    bot = Credential(
        subject=str(uuid.uuid4()),
        secrets={
            "peer_public_key": bot_public,
            "peer_preshared_key": preshared_key,
            "peer_tunnel_address": BOT_TUNNEL,
        },
    )
    return render_server(node, params, [bot], egress=LEAF_EGRESS)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    leaf_private, leaf_public = _keypair()
    bot_private, bot_public = _keypair()
    preshared_key = base64.b64encode(secrets.token_bytes(32)).decode()
    obfuscation = _obfuscation()

    leaf = _leaf_config(leaf_private, leaf_public, preshared_key, bot_public, obfuscation)
    awg0 = _bot_config(bot_private, leaf_public, preshared_key, obfuscation)

    # 0600: these hold private keys. The dir is throwaway, but the files are still secrets
    # while the stand is up, so they are written the way every other key file in this
    # project is (edge/bootstrap/node_stack.place_config uses the same mode on a node).
    leaf_path = OUT_DIR / "leaf.conf"
    bot_path = OUT_DIR / "awg0.conf"
    leaf_path.write_text(leaf, encoding="utf-8")
    leaf_path.chmod(0o600)
    bot_path.write_text(awg0, encoding="utf-8")
    bot_path.chmod(0o600)
    print(f"wrote {leaf_path} and {bot_path}")


if __name__ == "__main__":
    main()
