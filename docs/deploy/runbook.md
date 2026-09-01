# Deploying hashi

**WHAT:** the commands to bring hashi up on real hosts, in the three topologies that
make sense, and the traps that are known, named and not yet fixed.

**WHY:** the repository proves that the code holds together. It does not tell you which
machines to rent, which port each thing wants, or which two of those wants collide. This
file is that, and it is written to be followed at 3am from a phone tether.

**HOW:** pick a shape, run the shared preparation once, then the section for your shape.
Every command below is idempotent — re-running is always safe.

---

## Pick a shape

| | Boxes | What it proves | What it costs you |
|---|---|---|---|
| **A — one box** | 1 abroad | the whole pipeline: panel → SSH push → subscription link → a stock client connects | nothing about the Russian topology, and Reality cannot have port 443 |
| **B — two boxes** | 1 in RU (entry + control plane), 1 abroad (leaf) | the charter's real topology: friends dial the entry, traffic leaves from the leaf | your panel and your friend-facing transport fight over 443, and `HASHI_SECRET_KEY` ends up on the host most likely to be seized |
| **C — three boxes** | control plane, entry in RU, leaf abroad | the same, with no compromise | one more rental |

**Shape A is the right first run.** It is the cheapest way to find out whether the images
start, the SSH push works and a client accepts the link. Shape C is the right shape to
actually live in.

None of the three proves the charter's first success criterion. "Survives a mobile
whitelist shutdown" is a field observation on a real Russian network, made with your own
phone. No test in this repository claims it and none ever will.

---

## Before any shape

### On your own machine

```bash
git clone <this repo> hashi && cd hashi
make setup                                        # needs Python 3.14

python -c "import secrets; print(secrets.token_urlsafe(48))"   # → HASHI_SECRET_KEY
.venv/bin/python -m control.cli hash-password                  # → HASHI_OPERATOR_PASSWORD_HASH

ssh-keygen -t ed25519 -f ~/.ssh/hashi-node -C hashi-control -N ''
```

Both secrets are generated here and nowhere else, and that is not a style preference:

- `hash-password` prompts instead of taking an argument, so the plaintext never enters
  your shell history or `/proc`. Minimum 12 characters, enforced — and there is **no
  lockout on failed logins** (a deliberate decision in `control/app/auth.py`: with one
  operator, a lockout is a denial-of-service against the one person who needs the panel
  during an emergency). Length is the whole defence. Use far more than twelve.
- `panel-bootstrap.sh` **refuses to generate `HASHI_SECRET_KEY` on the host it
  installs.** That key decrypts every friend's credential and every node's private key.
  If the panel sits on the Russian entry node, a key generated there would live on the
  machine most likely to be seized, beside the data it opens.

Keep a copy of `HASHI_SECRET_KEY` somewhere that is not the control host and not the
backup directory. **A dump without the key restores nothing**, and both in one place
defeats the encryption.

### DNS

Point an **A record** for your panel hostname at the control-plane box *before* you
bootstrap. Caddy asks a public CA for a certificate the moment it starts, and a name
that does not resolve to that box means it retries forever while serving nothing.

### What every box must already have

Docker, and SSH. That is the entire list for a node — **hashi does not install a
container runtime for you**; it runs `docker version`, and if that fails it stops and
says so (`edge/bootstrap/node_stack.py`). You do not need to collect SSH host keys: the
first successful connect learns the node's host key and pins it from then on, so a later
connection cannot be silently intercepted.

```bash
curl -fsSL https://get.docker.com | sh && docker version
cat >> ~/.ssh/authorized_keys      # paste ~/.ssh/hashi-node.pub, then Ctrl-D
```

### The env file

On the control-plane box, `cp .env.example .env` and fill in:

| Key | Note |
|---|---|
| `HASHI_SECRET_KEY` | from your machine; never generated on the host |
| `HASHI_PUBLIC_HOST` | the panel/delivery hostname, already pointing here |
| `HASHI_OPERATOR_USERNAME` | `owner` is the default and is guessable — that is fine, the password is the defence |
| `HASHI_OPERATOR_PASSWORD_HASH` | the hash, never the password |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `HASHI_DATABASE_URL` is composed from these, so the app and the database cannot drift apart |
| `CADDY_ACME_EMAIL` | not checked by the bootstrap script; compose fails without it |

**Double every `$` in the password hash.** `scrypt$32768$8$1$…` becomes
`scrypt$$32768$$8$$1$$…`. `docker compose --env-file` interpolates the values it reads,
so `$<salt>` is expanded as a variable name and replaced with nothing. Whether that
destroys the hash depends on the salt's first byte — a salt starting with a letter is
silently eaten, one starting with a digit survives — and the only symptom is "Those
credentials were not accepted" beside a hash that looks perfectly correct. The bootstrap
script refuses to run rather than fixing the file for you: it must not rewrite a file
full of your secrets.

### The port-publication gap

`deploy/docker-compose.yml` publishes **no ports at all**, on purpose, and no overlay can
take a published port back — `ports:` is a sequence and the Compose spec merges sequences
by appending, so a `443:443` in the base file would follow every `make up-dev` and every
`make e2e-up` onto your laptop.

The consequence today is a real defect, and you should know it before it confuses you:
`panel-bootstrap.sh` verifies the stack from *inside* the compose network and then prints
`The panel is at https://…/panel/` — a URL nothing in the repo makes reachable. Until
that is fixed, write the overlay by hand on the control-plane box:

```bash
cat > deploy/docker-compose.public.yml <<'YAML'
services:
  caddy:
    ports:
      - "80:80"
      - "443:443"
YAML
```

Caddy only. Never the database.

---

## Shape A — one box

One VPS abroad, carrying the control plane and one node at the same time.

### Bring up the control plane

```bash
git clone <this repo> /opt/hashi-control && cd /opt/hashi-control
cp .env.example .env && "${EDITOR:-vi}" .env        # see the table above
# write deploy/docker-compose.public.yml as shown above

ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp \
  && ufw allow 51820/udp && ufw enable

make panel-bootstrap
docker compose --env-file .env \
  -f deploy/docker-compose.yml -f deploy/docker-compose.public.yml up -d

curl -fsS https://<your panel host>/healthz
```

Clone to `/opt/hashi-control`, **not** `/opt/hashi` — that path is the node stack's own
root, and on this box both live on the same disk.

### Register the box as its own node

In the panel at `https://<your panel host>/panel/`:

1. **Add node.** `address` and `ssh_host` are both this box's public IP — the control
   container dials out and back, which works; `172.17.0.1` is the fallback if the public
   address is awkward. `ssh_user root`, port 22, private key = the contents of
   `~/.ssh/hashi-node`.
2. **Enable a transport: `amneziawg` (or `wireguard`) on UDP 51820.**
3. **Apply.**
4. **Add a friend**, open their subscription link, load it into a stock client.

**Not Reality on this box.** Caddy holds 443/TCP for the panel, and Reality's whole
camouflage is *being* on 443. Its declared range is `(443, 65535)`, so 8443 validates —
but a TLS "website" answering on an odd port is a signal in itself. Save Reality for a
shape where the node is not sharing a host with the panel.

### Verify on the box

```bash
cd /opt/hashi && docker compose ps      # the node stack, project: hashi-node
```

Two data-plane containers on one host, in two compose projects (`hashi` and
`hashi-node`), is the expected picture.

---

## Shape B — two boxes

Box **E** in Russia: control plane **and** entry node. Box **L** abroad: leaf node.
Friends only ever hold E's address; a blocked leaf is replaced by re-pointing one hop,
with nobody touching their device.

Everything from Shape A applies to box E, plus:

1. Bootstrap the control plane on **E** exactly as in Shape A.
2. Register **E** as a node (`ssh_host` = its own IP) and **L** as a node (`ssh_host` =
   L's IP, reachable over SSH from E).
3. Enable a **friend-facing** transport on E.
4. Build the hop from the panel's hop form: entry = E, leaf = L, transport =
   `amneziawg`. The entry dials the leaf, always — E sits behind a Russian carrier NAT
   and cannot be dialled — so L listens and E reaches out.
5. **Apply both nodes.** Until you do, the hop exists only in the database.

### The two things shape B costs you

**Port 443 is contested.** Caddy owns 443/TCP on box E for the panel, so the
friend-facing transport on E cannot be Reality on 443. Either put Reality on another
port and accept the fingerprint cost, or move to shape C.

**Your secret key sits in Russia.** The charter's condition for putting the database and
panel inside Russia is that secrets are encrypted with a key that *does not live on that
host* — and today `panel-bootstrap.sh` requires `HASHI_SECRET_KEY` to be present in the
env file on the machine it installs. There is no supported way to keep it off that disk.
Shape B therefore violates the charter's own condition; run it knowingly or run shape C.

---

## Shape C — three boxes

Box **C**: control plane alone. Box **E** in Russia: entry node. Box **L** abroad: leaf
node. Nothing is contested and nothing is co-located.

| Box | Runs | Inbound | Outbound |
|---|---|---|---|
| **C** control plane | Postgres, control, Caddy | 22/tcp, 80/tcp, 443/tcp | 22/tcp to E and L |
| **E** entry (RU) | one friend-facing transport, one hop end (dials) | 22/tcp from C, the friend port | the hop's UDP port to L |
| **L** leaf (abroad) | one hop end (listens) | 22/tcp from C, the hop's UDP port from E | — |

1. Bootstrap the control plane on **C** (the Shape A control-plane block, unchanged).
2. Register **E** and **L** as nodes. Both `ssh_host` values are real remote addresses
   this time; the control container needs outbound 22 to each.
3. Enable **`vless_reality` on E, port 443** — free here, because the panel is on another
   box. Give it a `decoy_host` of your own choosing.
4. Build the hop: entry = E, leaf = L, transport = `amneziawg`.
5. Apply both nodes. Add friends. Their subscription contains E and never L: a hop is
   never granted to a friend and never appears in a subscription, because a friend
   holding the entry↔leaf tunnel would route straight past the entry the topology exists
   to hide behind.

Where to put box C is a real decision, not a formality. Outside Russia, it is out of
seizure range but the delivery endpoint may be unreachable from a Russian network under
whitelist mode — exactly when a friend needs to refresh a config. Inside Russia, it is
reachable but carries the problem described under shape B. The repository serves the
panel and the delivery endpoint from one Caddy site, so today you choose one location for
both.

---

## Rules that are not optional

- **Never plain WireGuard on the entry→leaf hop.** That hop crosses the border by
  definition, and a protocol-blocked transport there defeats the topology even in phase
  1. Use AmneziaWG or another obfuscated transport.
- **Never present plain WireGuard to a friend as something that works from a Russian
  mobile network.** TSPU protocol-blocks it. It works everywhere else.
- **A decoy host is chosen per node and never shared.** There is no project default and
  there must never be one — if every node borrows the same handshake, the fleet becomes
  enumerable by that fact alone.
- **One transport per node, once.** Enabling a transport that a node already has is
  refused, hop or not. So the hop transport and the friend-facing transport on the same
  node must be *different transports* (backlog item 34 is the fix; until then, plan
  around it).
- **One friend per node on the WireGuard family.** AmneziaWG and plain WireGuard mint a
  shared tunnel address today, so a second friend on the same node collides on
  `AllowedIPs` and the node refuses, loudly, and goes `degraded` (backlog item 33). VLESS
  transports have no such limit.
- **Never edit anything under `/opt/hashi` on a node.** It is generated by the control
  plane and overwritten on every apply. The control database is the source of truth, and
  that is what makes replacing a node safe.

## Known-unproven

`docker.io/masipcat/wireguard-go:0.0.20230223` has a tag that resolves but has **never
been started by this project**. Whether it accepts `up <config>` as its command is
discovered on your first real node. If it does not, that is a finding, not a mistake on
your side.

Every other data-plane image pin is checked against a real registry by
`tests/e2e/edge/test_every_image_pin_resolves.py` — a check that exists because one pin
in the tree turned out never to have existed at all.

## Backups

```bash
make backup                                   # → backups/hashi-<timestamp>.sql.gz, mode 0600
make restore FROM=backups/hashi-<...>.sql.gz  # destructive, so the path is required
```

The dump is encrypted with `HASHI_SECRET_KEY` and cannot be restored without it. Keep the
key somewhere the dumps are not. Restore is destructive and never picks "the latest one"
for you — that is not a decision a Makefile gets to make.
