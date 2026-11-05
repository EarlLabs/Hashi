# M40 — step notes
Conventions established here, binding later steps/milestones until superseded.
Everything in docs/tracker/M37–M39 step-notes binds too.

Scope (owner, 2026-11-04/05): the bot's traffic leaves through a leaf, MANDATORY in the
`telegram-bot` profile. Control-plane minting of the egress peer is DEFERRED to a future
milestone (owner wanted "just make it work"); for now the operator supplies the config by
hand (`deploy/egress/awg0.conf`), like the management tunnel.

## From the egress step (M40.1 + stand restructure) — commits 108c4d0 + 0d8ced4, review clean in round 2 (round 1: 1 High + 3 Medium, all fixed)

- **Mandatory egress sidecar.** `telegram-bot-egress` in `deploy/docker-compose.yml`, in the
  `telegram-bot` profile: fleet's `amneziawg-go:3.0.3`, `NET_ADMIN`+`/dev/net/tun`, runs an
  AmneziaWG client (`_WG_QUICK_SUPERVISOR`, `awg-quick up /etc/amneziawg/awg0.conf`). The bot
  gets `network_mode: "service:telegram-bot-egress"` and `depends_on` the sidecar
  `service_healthy` (healthcheck requires a nonzero `latest-handshakes` — a LIVE tunnel, not
  just a running process). Fail-closed: no config / no handshake → sidecar never healthy →
  bot never starts; the bot has no network of its own, so it can never poll Telegram in the
  clear. If the sidecar restarts, the bot keeps a dead netns until it too is restarted
  (fail-closed; `depends_on` doesn't re-trigger; operator restarts the bot).
- **Container-client config shape** (`deploy/egress/awg0.conf`, operator-supplied, gitignored,
  mounted `ro`, never baked, never in git): `Table = off`; **PostUp pins the leaf endpoint via
  the ORIGINAL default gateway BEFORE swapping the default** — `GW=$(ip route show default|awk
  'NR==1{print $3}'); EP=$(awg show %i endpoints|awk 'NR==1{print $2}'|sed 's/:port//');
  ip route replace "$EP/32" via "$GW"; ip route replace default dev %i` (IPv4 only); matching
  PostDown. Without the pin the tunnel's own UDP routes into the tunnel and no handshake
  completes on a real public leaf — the stand hides this (connected-route leaf). MTU **1280**.
  Jc/Jmin/Jmax/H1–H4 obfuscation, per-host, the four headers must match the leaf's.
- **LAN carve-out:** the sidecar is on the compose network, so the DB is a connected route the
  tunnel's default doesn't cover (DB stays direct); everything else goes through the tunnel.
- **DNS:** `dns: [1.1.1.1, 1.0.0.1]` on the SIDECAR (rejected on a `network_mode: service:`
  container), so lookups go through the tunnel; the bot inherits it; `db` still resolves on
  127.0.0.11. FIELD-ONLY: the stand dials by IP and can't prove the leak is closed; the owner
  confirms with tcpdump, and if an engine forwards DNS from the host namespace the operator
  runs a resolver past the leaf.
- **Stand:** `.e2e/gen_egress_configs.py` mints throwaway leaf+bot keypairs/PSK/obfuscation per
  `make e2e-up` (X25519 via `cryptography`, verified vs `awg pubkey`), renders the leaf through
  the real edge renderer. A `leaf` service forwards+masquerades; the fake Telegram sits on an
  `--internal` `egress` network (10.90.1.9) reachable ONLY past the leaf; the DB stays direct.
  `test_the_bots_telegram_traffic_leaves_through_the_leaf` proves the fake routes via `awg0`,
  the DB direct, and the leaf shows a handshake. `E2E_ALL_PROFILES` unchanged (leaf always on;
  sidecar in the `telegram-bot` profile). Service set now `{control, db, caddy, telegram,
  telegram-bot, telegram-bot-egress, leaf}`.
- **RELAY vs LOCAL:** the STAND leaf renders `Egress.RELAY` (LOCAL drops private destinations
  and its only usable public test block, 192.88.99.0/24, collides with the hop scenario's
  docker network). **The future control-minted PRODUCTION leaf must render `Egress.LOCAL`.**
- **Deferred to a future milestone:** minting the bot's egress peer through the control plane
  (so it rotates/revokes). It needs: a container-client render variant (Table=off + the
  endpoint-pin PostUp + the tunnel-DNS), and the production leaf rendered `Egress.LOCAL`.
