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
itself:

```ini
[Interface]
PrivateKey = <this sidecar's private key>
Address    = 10.x.y.2/24          # the bot's address on the hop, a private range
MTU        = 1280                  # a tunnel inside a tunnel; the default fragments
Table      = off                  # we install the route, awg-quick does not
PostUp     = ip route replace default dev %i
PostDown   = ip route del default dev %i || true
Jc = ...                          # this host's OWN obfuscation values — never fleet-shared,
Jmin = ...  Jmax = ...            # a shared set is itself the fingerprint
H1 = ...  H2 = ...  H3 = ...  H4 = ...

[Peer]
PublicKey    = <the leaf's public key>
PresharedKey = <the pair's pre-shared key>
Endpoint     = <the leaf's address>:<port>   # reachable from this host; the LAN carve-out
AllowedIPs   = 0.0.0.0/0
PersistentKeepalive = 25
```

The `Endpoint` address must be one this host can reach **directly** (a connected route), so the
WireGuard packets to the leaf do not themselves try to go through the tunnel. That is the whole
carve-out: the default route points at the tunnel, but the route to the leaf (and to the
compose subnet) is more specific and stays off it.

## Where this config comes from

For now it is **operator-supplied** (or, on the e2e stand, generated per run by
`.e2e/gen_egress_configs.py`). Minting it through the control plane's own credential machinery
— the same way a node's keys are minted — is the next step (M40.2); until then, generate the
keypair and pre-shared key with `awg genkey` / `awg genpsk` on the leaf and write them here by
hand.
