# The bot's egress config lives here — M40

The Telegram bot (the `telegram-bot` compose profile) has no network of its own: it shares
the `telegram-bot-egress` sidecar's namespace, and that sidecar runs an **AmneziaWG client to
a leaf abroad**. Everything the bot sends — Telegram, and the SSH it opens to nodes on
`/adduser` and `/apply` — leaves through that leaf. Only the compose subnet (the shared
database) stays direct.

Put the sidecar's client config in this directory as **`awg0.conf`** (the filename is the
interface name, so it must be `awg0.conf`). The container mounts this directory read-only at
`/etc/amneziawg` and runs `awg-quick up /etc/amneziawg/awg0.conf`. The file is **gitignored**
(`deploy/egress/*.conf`) because it holds a WireGuard private key — it belongs here and
nowhere else, never in git, a chat or a ticket.

## The shape it must have

A container cannot use `awg-quick`'s own `AllowedIPs = 0.0.0.0/0` auto-routing: `/proc/sys` is
read-only there, so the route install fails. Instead the config installs the default route
itself — but it must **pin the leaf's endpoint to the original gateway first**, or the tunnel's
own transport packets (the UDP to the leaf) would match the new default and be routed back into
the tunnel, so no handshake ever completes:

```ini
[Interface]
PrivateKey = <this sidecar's private key>
Address    = 10.x.y.2/24          # the bot's address on the hop, a private range
MTU        = 1280                  # a tunnel inside a tunnel; the default fragments
Table      = off                  # we install the route, awg-quick does not
# Pin the endpoint to the ORIGINAL gateway, THEN swap the default to the tunnel. `awg show %i
# endpoints` is the resolved endpoint ip:port; the gateway is the default route's current next
# hop. `ip route replace` keeps a down-before-up idempotent. IPv4 only.
PostUp = GW=$(ip route show default | awk 'NR==1{print $3}'); EP=$(awg show %i endpoints | awk 'NR==1{print $2}' | sed -E 's/:[0-9]+$//'); [ -n "$GW" ] && [ -n "$EP" ] && ip route replace "$EP/32" via "$GW"; ip route replace default dev %i
PostDown = ip route del default dev %i 2>/dev/null || true
Jc = ...                          # this host's OWN obfuscation values — never fleet-shared,
Jmin = ...  Jmax = ...            # a shared set is itself the fingerprint
H1 = ...  H2 = ...  H3 = ...  H4 = ...

[Peer]
PublicKey    = <the leaf's public key>
PresharedKey = <the pair's pre-shared key>
Endpoint     = <the leaf's address>:<port>   # a PUBLIC leaf; the PostUp pins it off the tunnel
AllowedIPs   = 0.0.0.0/0
PersistentKeepalive = 25
```

The `Endpoint` is a real leaf abroad, reached over the internet — **not** a connected route.
The PostUp above is what keeps the WireGuard packets to it off the tunnel: it adds a `/32` for
the endpoint via the original default gateway before it points the default at the tunnel. That is
the whole carve-out — the default route goes to the tunnel, while the endpoint `/32` and the
connected compose subnet (the shared DB) stay on the host's own route.

## DNS must leave through the tunnel too

Name resolution is the easy leak: Docker's embedded resolver (`127.0.0.11`) forwards external
lookups to the host's resolver, so `api.telegram.org` would be looked up in the clear from the
Russian host. The sidecar's compose service sets `dns:` to a public resolver so that, with the
default route through the tunnel, the forwarded query leaves through the leaf; the bot inherits
the sidecar's `/etc/resolv.conf`, and internal names (`db`) still resolve on `127.0.0.11`
directly. **Confirm this on the real host** (e.g. `tcpdump` that DNS egresses via the tunnel) —
whether an engine forwards external DNS from the container or the host namespace varies, and if
it forwards from the host, run a resolver reachable only past the leaf and point the sidecar's
`dns:` there instead.

## If the sidecar restarts

The bot shares the sidecar's network namespace, and compose's `depends_on` does not re-trigger
the bot when the sidecar restarts — so after a sidecar restart the bot has no network until it
too is restarted (fail-closed: it reaches nothing in the clear, it just reaches nothing).
Restart the bot after the sidecar: `make restart-control` restarts control only, so use
`docker compose ... restart telegram-bot` (or bring the profile down and up).

## Where this config comes from

For now it is **operator-supplied** (or, on the e2e stand, generated per run by
`.e2e/gen_egress_configs.py`). Minting it through the control plane's own credential machinery
— the same way a node's keys are minted — is the next step (M40.2); until then, generate the
keypair and pre-shared key with `awg genkey` / `awg genpsk` on the leaf and write them here by
hand.
