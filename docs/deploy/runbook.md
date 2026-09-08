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

**On a node, do neither of those by hand.** `scripts/node-bootstrap.sh` installs the
runtime, authorises the key and brings the firewall up in one run that asks no questions,
and running it again changes nothing — see *Preparing a leaf* below. The block it replaces
is here because a control-plane box that is not also a node still does it this way:

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

## Preparing a leaf

A rented host, an SSH session, and ten minutes. This section is every node — the leaf
abroad, the entry in Russia, and the box in shape A that is also its own node — because
they are prepared the same way: **one script, `scripts/node-bootstrap.sh`, and nothing by
hand.** A hand-prepared host is a host you cannot rebuild at three in the morning, which
is precisely when you rebuild one.

It gives the host three things and stops: a container runtime, the one **public** key the
control plane authenticates with, and the host firewall — with logging off before the
firewall ever comes up. It installs **no hashi code and no hashi state**; `/opt/hashi` is
created by the control plane on your first apply.

### Run it

From the machine that holds this repository and the key pair, so that nothing of the
repository lands on the node:

```bash
make node-bootstrap NODE=<user>@<the new host> \
  ARGS="--authorized-key '$(cat ~/.ssh/hashi-node.pub)' --port <transport port>/udp"
```

That is `ssh <host> 'bash -s -- <args>' < scripts/node-bootstrap.sh`: the script is piped
in and never copied, which is what keeps repository code off a node. Add `SSH_PORT=<port>`
if the host does not answer on the default one. If you are already sitting on the host,
run `./scripts/node-bootstrap.sh` with the same arguments.

| Argument | |
|---|---|
| `--authorized-key TEXT` | the **public** half of the pair you generated on your own machine. `--authorized-key-file <path>` reads it from a file already on the host. |
| `--port PORT[/PROTO]` | repeatable, one per transport this node will run — the same number you will enter in the node record. |
| `--user NAME` | the account the control plane logs in as; defaults to the invoking account (or `SUDO_USER` under sudo). |
| `--ssh-port N` | only when the script cannot work the management port out for itself. |

Progress lines start `==> `. A refusal exits **1** and starts `node-bootstrap: `; an
argument it does not recognise exits **2** and prints the usage. It refuses rather than
guessing in three places, and each one is a mistake you want stopped here:

- **No key, or a key that is not a public key.** The private half belongs in the node
  record, encrypted, and never on a node — a key generated or pasted on the host would sit
  in clear on the machine most likely to be seized. Generate the pair where the control
  plane lives (*Before any shape*, above) and pass the `.pub` half.
- **It cannot tell which port sshd listens on.** It reads the port this session arrived on
  and the ports `sshd -T` reports, and if neither answers it stops rather than enabling a
  firewall it cannot prove leaves you a way back in. Pass `--ssh-port`.
- **The account is not root and sudo wants a password.** The run is piped over SSH and must
  never prompt, so give the account passwordless sudo or run as root.

### What a finished run says

```
==> ready: docker <version>, key authorised, firewall up, logging off
==> register it in the panel with ssh_user <user> and ssh_port <port>
==> nothing of hashi's was installed here — the control plane creates /opt/hashi itself when you apply
```

Take the `ssh_user` and `ssh_port` from that second line — it names the port this session
actually arrived on, which is the one port known to work from outside. Then, in the panel:
**Add node** with those values and the contents of `~/.ssh/hashi-node` as the private key,
enable the transport on the port you opened, and **Apply**. Nothing before the apply has
told the fleet this host exists: the script writes nothing to the control database, and a
node never dials the control plane.

### Running it on a host somebody already prepared

The normal case, not the exception — both hosts of this project's own field run already
had docker, and one already had an active firewall carrying its own rules. A second run,
or a first run on a host with a past, reports rather than changes:

```
==> docker is already installed — left exactly as it is
==> the control plane's key is already authorised for <user>
==> ufw logging was already off
==> <port>/<proto> was already open
==> incoming was already denied by default
==> the firewall was already up — its existing rules were kept
==> an earlier apply already left /opt/hashi here — this run neither changed nor removed it
```

Nothing there is a warning. What the script never does is **close** anything: the rule set
is the union of every run, because a script that withdrew a rule could withdraw the one
carrying the session running it. Narrowing a rule set is an operator's job, done knowingly.

### The layer the script cannot see, and the evening it costs

Every run ends on this line, and it is the last one for a reason:

```
==> the provider's own firewall sits in front of this host and outside this script's reach
```

The provider's security group is a **separate layer, in their console, invisible from
inside the host**. `ufw status` on the node tells you nothing about whether a packet ever
reaches the box. And a closed security group looks *exactly* like a broken transport: the
host firewall allows the port, the container is up, every check the script makes is green,
the panel says the node is fine, and the client still times out. An operator who does not
know this layer exists debugs the transport, where there is nothing to find.

**Confirm it from a machine on a different network.** Not from the host itself, and not
from another box on the same private network — both answer a question you did not ask. In this project's field
run the check was made from a second host in another country: bind a listener on the new
node one port at a time, probe it from that other machine, remove the listener.

**And distrust the probe before you distrust the firewall.** In that same run one
privileged port appeared shut and was not: the probing process was running as an
unprivileged account and could not bind that port at all. A privileged port needs a
privileged probe on both ends. That is what a false negative looks like here, and it is
exactly the trap that ends with someone filing a support ticket about a firewall that was
open the whole time.

### What it deliberately does not do

- **It does not register the node.** When it finishes the host is drivable and the fleet
  still does not know it exists. The node record is created by you, in the panel.
- **It does not harden the host.** Password authentication, unattended upgrades, a ban
  daemon, the clock and the kernel are all still yours. "Ready" here means ready to be
  driven by the control plane, and nothing wider.
- **It proves nothing about reachability.** Its checks ask *this host* questions and never
  send a packet anywhere. Whether a friend inside Russia can reach this node is a field
  observation on a real network, and no run of this script is evidence for it.
- **Its ufw log sweep is not a cleanup.** On a host that had already logged, rsyslog,
  `kern.log` and the kernel journal hold the same lines, and nothing done on the host
  reaches all four. The real protection is the ordering — logging off *before* the
  firewall comes up — which is why a host prepared by this script never writes the record
  at all, and why a host that already did needs you rather than a script.

---

## Shape A — one box

One VPS abroad, carrying the control plane and one node at the same time.

### Bring up the control plane

```bash
git clone <this repo> /opt/hashi-control && cd /opt/hashi-control
cp .env.example .env && "${EDITOR:-vi}" .env        # see the table above
# write deploy/docker-compose.public.yml as shown above

ufw logging off                                # FIRST, always — see below
ufw allow <the port sshd listens on>/tcp       # sshd -T | awk '/^port /{print $2}'
ufw allow <Caddy's plain-HTTP port>/tcp        # the ACME challenge and the redirect
ufw allow <Caddy's HTTPS port>/tcp             # the panel and the delivery endpoint
ufw allow <this node's transport port>/udp     # the number you enter in the node record
ufw enable

make panel-bootstrap
docker compose --env-file .env \
  -f deploy/docker-compose.yml -f deploy/docker-compose.public.yml up -d

curl -fsS https://<your panel host>/healthz
```

Clone to `/opt/hashi-control`, **not** `/opt/hashi` — that path is the node stack's own
root, and on this box both live on the same disk.

**`ufw logging off` comes first and is not optional.** `ufw enable` turns connection
logging on by default and starts writing source addresses to `/var/log/ufw.log` from the
moment the firewall comes up. That is a connection log — the one record the charter
forbids at any level and the one that can hurt a real person (`docs/decisions.md`,
decision 5). On this project's own leaf host it had collected 5840 bytes. Doing it after
`enable` is too late, and deleting the file afterwards is not a repair: rsyslog,
`kern.log` and the journal hold the same lines, and nothing on the host reaches all four.
Off before up is the only version of this that works.

**None of those ports is a number to copy from here.** They are the ports your own
configuration uses: read them from `sshd -T`, from your Caddyfile's site addresses, and
from the transport in the node record. A port written into a runbook becomes a port the
fleet cannot move away from — the same rule that keeps one out of the code. On a box that
is only a node, `scripts/node-bootstrap.sh` does this whole block for you, in the right
order, from arguments.

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
2. Prepare **L** with *Preparing a leaf* above, then register **E** as a node
   (`ssh_host` = its own IP) and **L** as a node (`ssh_host` = L's IP, reachable over SSH
   from E).
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
2. Prepare **E** and **L** with *Preparing a leaf* above — one script run each — and
   register both as nodes. Both `ssh_host` values are real remote addresses this time; the
   control container needs outbound SSH to each.
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
