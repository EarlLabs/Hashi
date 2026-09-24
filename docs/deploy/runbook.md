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
| **B — two boxes** | 1 in RU (entry + control plane), 1 abroad (leaf) | the charter's real topology: users dial the entry, traffic leaves from the leaf | your panel and your user-facing transport fight over 443, and `HASHI_SECRET_KEY` ends up on the host most likely to be seized |
| **C — three boxes** | control plane, entry in RU, leaf abroad | the same, with no compromise | one more rental |

**Shape A is the right first run.** It is the cheapest way to find out whether the images
start, the SSH push works and a client accepts the link. Shape C is the right shape to
actually live in.

**And a shape is not a choice you make once.** Going from the box you started with to the
charter's topology has a section of its own — *Growing out of Shape A*, below — because
the obvious way to read Shape B as a migration is the way that destroys every credential
your users are connecting on today.

None of the three proves the charter's first success criterion. "Survives a mobile
whitelist shutdown" is a field observation on a real Russian network, made with your own
phone. No test in this repository claims it and none ever will.

---

## Before any shape

### On your own machine

```bash
git clone <this repo> hashi && cd hashi
make setup                                        # needs Python 3.14
make verify                                       # the gate: static zones + tests/e2e

python -c "import secrets; print(secrets.token_urlsafe(48))"   # → HASHI_SECRET_KEY
.venv/bin/python -m control.cli hash-password                  # → HASHI_OPERATOR_PASSWORD_HASH

ssh-keygen -t ed25519 -f ~/.ssh/hashi-node -C hashi-control -N ''
```

`make verify` is the one command that answers "is this green": it runs the three static
zones, boots the disposable e2e stack, runs `tests/e2e/` against it and tears it down. It
needs a docker engine and **fails** without one rather than skipping — `make test` is the
static half, and a smaller claim. Neither says anything about whether a tunnel carries
traffic on a Russian network; nothing in this repository does.

Both secrets are generated here and nowhere else, and that is not a style preference:

- `hash-password` prompts instead of taking an argument, so the plaintext never enters
  your shell history or `/proc`. Minimum 12 characters, enforced — and there is **no
  lockout on failed logins** (a deliberate decision in `control/app/auth.py`: with one
  operator, a lockout is a denial-of-service against the one person who needs the panel
  during an emergency). Length is the whole defence. Use far more than twelve.
- `panel-bootstrap.sh` **refuses to generate `HASHI_SECRET_KEY` on the host it
  installs.** That key decrypts every user's credential and every node's private key.
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

**A node:** docker, and SSH. That is the entire list — **hashi does not install a
container runtime for you** when it drives a node; it runs `docker version`, and if that
fails it stops and says so (`edge/bootstrap/node_stack.py`). You do not need to collect
SSH host keys: the first successful connect learns the node's host key and pins it from
then on, so a later connection cannot be silently intercepted.

**The control-plane box needs three more things, and a genuinely bare one has none of
them:** a container runtime with the compose plugin, `git` — the stack is built from a
clone of this repository, not from a published image — and `make`, because every command
in the block below is a Make target. An acceptance walk on a bare host found all three
missing and the runbook listing none of them, which is two extra commands before the
first line of that block and an error message for each one you meet instead.

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
| `HASHI_OPERATOR_PASSWORD_HASH` | the hash, never the password. `make hash-password` produces it **on this host**, inside the control image, with nothing installed but the container runtime; `python -m control.cli hash-password` is the same command on a machine that already has the project set up |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `HASHI_DATABASE_URL` is composed from these, so the app and the database cannot drift apart |
| `CADDY_ACME_EMAIL` | not checked by the bootstrap script; compose fails without it |
| `HASHI_PRIVATE_HOST` | the name your own devices ask for over the management tunnel — usually this host's tunnel address |
| `HASHI_PRIVATE_PORT` | where Caddy serves the console; the same variable drives the listener and the published mapping, so they cannot drift |
| `HASHI_PRIVATE_BIND_ADDR` | which address on **this** host the console is published on. The tunnel's, never loopback — see *Reaching the panel*. Read only by `make up-panel`; a host with no tunnel yet leaves it unset and publishes with `make up-panel-over-ssh` |
| `HASHI_MGMT_*` | optional: the management tunnel's own address, port, endpoint, MTU and device list. Absent means no tunnel is generated |

**Paste the hash exactly as `hash-password` printed it, doubled `$$` and all.** The
command now prints `scrypt$$32768$$8$$1$$…` rather than `scrypt$32768$8$1$…`, and the
doubling belongs in the file: `docker compose --env-file` interpolates the values it
reads, turns each `$$` back into one `$`, and would read a single `$<salt>` as a variable
name and replace it with nothing. Whether that destroys the hash depends on the salt's
first byte — one starting with a letter is silently eaten, one starting with a digit
survives — so the same procedure worked on one host and locked the owner out of the next,
with "Those credentials were not accepted" beside a hash that looked perfectly correct.
**Do not double them a second time.** If you are working from a hash generated before this
changed, double it once by hand. Two things now catch the mistake either way: the
bootstrap script refuses an env file with a lone `$` (it will not rewrite a file full of
your secrets), and the control plane refuses to start on a hash that is not one, rather
than serving a login nobody can pass.

### The port-publication gap

`deploy/docker-compose.yml` publishes **no ports at all**, on purpose, and no overlay can
take a published port back — `ports:` is a sequence and the Compose spec merges sequences
by appending, so a `443:443` in the base file would follow every `make up-dev` and every
`make e2e-up` onto your laptop.

So `panel-bootstrap.sh` installs a stack that nothing outside the host can reach, and it
says so: it verifies the control plane from *inside* the compose network and ends by
naming what it proved and what it did not. It used to end with `The panel is at
https://…/panel/` — an address that answered nothing, because 80 and 443 were closed. It
prints no address now. Publishing is still a separate, deliberate step, and there are two
of them because a host either has a management tunnel or does not:

```bash
make up-panel            # the delivery endpoint, and the console on this host's
                         # management-tunnel address
make up-panel-over-ssh   # the same without that last mapping, for a host with no tunnel
                         # yet: the console answers on loopback only, reached with ssh -L
```

That is the base stack plus `deploy/docker-compose.public.yml` — and, for the first,
`deploy/docker-compose.tunnel.yml` on top. Both **ship with the repository**: they used to
be a heredoc you typed onto the box, and that stopped being survivable when the file grew
a mapping whose bind address is the difference between a private console and a public one.
Caddy only. Never the database.

**Why two files.** `HASHI_PRIVATE_BIND_ADDR` is the one value in the deployed shape that
names an address *this host must actually hold*, and a machine restored from a bucket
holds no tunnel address — the tunnel's keys were on the box that was lost. `make up-panel`
there fails on a bind docker cannot make, at the point where the operator cannot log in
yet; the bare-host walk of 2026-09-23 answered it with `ip addr add`, by hand. So the
mapping that needs a tunnel is a file of its own, and everything a deployed host publishes
regardless — including the loopback fallback the `ssh -L` route uses — is in the other.
Neither publishes the console on an address the internet can reach.

**And remember it after every `make panel-bootstrap`.** That script uses the base file
alone, on purpose — so a later run brings the stack back to the base file's shape and
takes the published ports away again. Run `make up-panel` afterwards, or run it instead
of the script once the box is installed. **The script says this itself now**, before it
converges and again when it has finished, and only on a host that was in fact publishing
something: it asks the running stack what it publishes rather than guessing. It is said
there because "a second run is safe" is printed by every refusal in the restore path, and
the one thing a second run is not safe for was written down only here — under a heading
an operator re-running a command has no reason to open.

---

## Reaching the panel

**The console is not on your public hostname.** As of M7 Caddy serves two sites out of
one container:

| site | serves | reachable from |
|---|---|---|
| public — `HASHI_PUBLIC_HOST` on 80/443 | `/sub/*`, and a redirect to https | anywhere, which is the point: a user refreshes their config from inside Russia at the moment a node was blocked |
| private — `HASHI_PRIVATE_HOST` on `HASHI_PRIVATE_PORT` | `/panel/*`, `/api/*`, `/static/*` | the management tunnel, and loopback |

Everything a site does not serve is `404`, with no body and nothing that says the other
site exists. The console holds every node key and every user credential, and there is
deliberately **no lockout on repeated failed logins** (`control/app/auth.py`, and it is a
recorded decision rather than an oversight) — so on a public address, password length was
the entire defence. This is what replaces it.

The console's certificate comes from Caddy's own CA, not from a public one: the private
site has no public name and no public address, so ACME could never validate it, and
nothing about the console's existence reaches a CA's logs. Your browser will ask about it
once.

**Set `HASHI_PRIVATE_HOST` to the tunnel address, not to a name**, unless you can resolve
that name on *every* device you would reach the console from — including your phone,
which cannot be given a hosts entry and is the device you reach for in an emergency. This
matters more than it looks: **a TLS client sends no SNI when the host is an IP literal**,
which is true of curl and of every browser, so a console dialled by address tells Caddy
nothing about which certificate it wants. `deploy/caddy/Caddyfile` answers that with
`default_sni`, set to this value — which is why it has to be the address you actually
type. Without it the handshake is aborted with `tlsv1 alert internal error` and the
console is unreachable by both of its routes; that is not hypothetical, it is how this
milestone failed on its first real host.

Two consequences worth knowing, neither of them a reason to change the value:

- `default_sni` is global — Caddy has no per-site form of it — so a client that connects
  to the **public** port without SNI is also answered with the console's certificate, and
  learns this address. It is private and unroutable, and the alternative was a
  certificate-name mismatch on every visit to your own console, which teaches you to
  click through TLS warnings on the one surface that must never be impersonated.
- **`HASHI_PUBLIC_HOST` must be a name with a real DNS record, never a bare address.** A
  public CA cannot issue for an IP, so Caddy falls back to its own CA and every stock
  client refuses the certificate — `/sub/{token}` then fails for every user while
  nothing on the host looks wrong. That is a fact about certificates rather than about
  SNI, and no setting here repairs it.

### The management tunnel

A dedicated **AmneziaWG** tunnel, not plain WireGuard and not a third-party mesh
(`docs/decisions.md`, 2026-09-09 — decision 2 was taken, reaffirmed on measurement, and
then reversed the same day; the sequence is the record). Two things it is not, both
deliberate: it is not a `node_transports` row, because that shape carries one peer
address and therefore serves one device, and you have a laptop and a phone; and it renders
no `PostUp`, no `PostDown` and no `Table`, because it carries traffic **to** this host
rather than **through** it, and forwarding rules would quietly turn your admin tunnel into
an exit.

Fill in the `HASHI_MGMT_*` keys **with this deployment's own values** and run the
bootstrap. It prints one config per device, **once**:

```bash
make panel-bootstrap
```

You will see `generating the management tunnel the panel is reached over`, then, for each
device, `Its configuration follows ONCE and is not stored anywhere` followed by the file
itself. **Copy each one to its device before you close that terminal.** Nothing stores it:
the private half of a device's key exists in that scrollback and on the device, and
nowhere else. A device whose config was lost gets a new entry in `HASHI_MGMT_PEERS` and a
new key — a re-run says `already a peer of this tunnel` and prints nothing, because there
is nothing left to print.

**Left as `.env.example` ships them, those keys generate nothing**, and that is deliberate:
the template's block is a complete one, so a machine rebuilt by copying that file used to
get a tunnel and two printed private keys for devices nobody owns, aimed at the template's
example endpoint. The bootstrap compares the block against `.env.example`'s own line, skips
the generation and says which mode it left the host in — which for a freshly restored host
is the SSH fallback below.

The run ends with `NOT done, and not yet true: the tunnel is not up and this host is not
listening.` That is accurate: it wrote a file and printed text. Bringing the tunnel up is
yours, as root, and needs `amneziawg-tools` on the host:

```bash
ufw allow <the management tunnel's UDP port>/udp   # HASHI_MGMT_PORT in your env file
awg-quick up ~/.hashi/management/awg-mgmt.conf
```

Set `HASHI_PRIVATE_BIND_ADDR` to the tunnel address the interface now holds — that
publication is the whole of "the console is off the public internet", because Caddy inside
the container listens on every interface it has and the host decides which one the port
appears on. Then `make up-panel`, and open the console from a device on the tunnel.

**Never `HASHI_PRIVATE_BIND_ADDR=127.0.0.1`.** Loopback is already claimed for that port
by the fallback below, and docker refuses the second bind with "port is already
allocated"; `panel-bootstrap.sh` checks for it and says so, because that error names
neither the cause nor the cure. **And never an address this host does not hold** — that
is the same mistake wearing different clothes, and it is what a freshly restored machine
has: no tunnel, therefore no address, therefore `make up-panel` fails on the bind. Leave
the variable unset and publish with `make up-panel-over-ssh` until the tunnel is up.

### The way back in when the tunnel is unavailable

**This route is tested, not merely described**, and the difference matters: the day you
need it is the day of an emergency rotation, and a fallback nobody has run is a paragraph.
It is also the route this project's own field run used all night.

`make up-panel` publishes the console's port a second time, on this host's loopback only
— and `make up-panel-over-ssh` publishes *only* that one, which is the whole of its
difference. Nothing off the host can reach it; anything that can already open an SSH
session can forward it:

```bash
ssh -L PRIVATE_PORT:127.0.0.1:PRIVATE_PORT USER@THE_PANEL_HOST
```

Then, on your own machine, open `https://127.0.0.1:PRIVATE_PORT/panel/` — the same
console, the same certificate, the same login. The site block answers to the loopback name
as well as to the tunnel name precisely so that this arrives somewhere rather than at a
`404`.

Check it now, while nothing is on fire, and check it again after any change to the panel
host. One command, from your own machine, with the forward open:

```bash
curl -k -o /dev/null -w "%{http_code}\n" https://127.0.0.1:PRIVATE_PORT/panel/login
```

`200` means the way back in works. Anything else means it does not, and you have found
that out on a quiet afternoon instead of during a rotation.

**What this cannot tell you.** Your machine and the panel host may share a cloud region,
in which case traffic between them never traverses ТСПУ and an uninterrupted SSH session
says nothing about your home or mobile network. Only you can test that, from the network
you would actually be on.

---

## Preparing a leaf

A rented host, an SSH session, and ten minutes. This section is every node — the leaf
abroad, the entry in Russia, and the box in shape A that is also its own node — because
they are prepared the same way: **one script, `scripts/node-bootstrap.sh`, and nothing by
hand.** A hand-prepared host is a host you cannot rebuild at three in the morning, which
is precisely when you rebuild one.

It gives the host four things and stops: a container runtime, the one **public** key the
control plane authenticates with, the host firewall — with logging off before the firewall
ever comes up — and one **empty** directory, `/opt/hashi`, owned by the account you will
register. It installs **no hashi code and no hashi state**: everything that ever lands in
that directory is rendered by the control plane and pushed over SSH on your first apply. An
empty directory is not state — nothing in it needs regenerating, because nothing is in it —
and why it is created here rather than by the control plane is *Which accounts work*, below.

### Run it

From the machine that holds this repository and the key pair, so that nothing of the
repository lands on the node:

```bash
make node-bootstrap NODE=USER@THE_NEW_HOST \
  ARGS="--authorized-key '$(cat ~/.ssh/hashi-node.pub)' --port TRANSPORT_PORT/udp"
```

**The words in capitals are the placeholders**, and they are capitals rather than
`<angle brackets>` for one reason: a shell reads an angle bracket as a redirection, so a
line pasted with the brackets still in it dies on a message that names neither this script
nor the thing you forgot to fill in. Substitute all of them — none has a default.

That is `ssh THE_NEW_HOST 'bash -s -- ARGS' < scripts/node-bootstrap.sh`: the script is
piped in and never copied, which is what keeps repository code off a node. Add
`SSH_PORT=THE_PORT` if the host does not answer on the default one. If you are already
sitting on the host, run `./scripts/node-bootstrap.sh` with the same arguments.

| Argument | |
|---|---|
| `--authorized-key TEXT` | the **public** half of the pair you generated on your own machine. `--authorized-key-file <path>` reads it from a file already on the host. |
| `--port PORT[/PROTO]` | repeatable, one per transport this node will run — the same number you will enter in the node record. |
| `--user NAME` | the account the control plane logs in as; defaults to the invoking account (or `SUDO_USER` under sudo). |
| `--ssh-port N` | only when the script cannot work the management port out for itself. |

Progress lines start `==> `. A refusal exits **1** and starts `node-bootstrap: `; an
argument it does not recognise exits **2** and prints the usage. **Both of those are the
script's own codes, and `make` does not pass them on**: GNU make exits **2** whenever a
recipe fails, whatever the recipe returned, so through `make node-bootstrap` a refusal and
a typo are the same number. Read the sentence rather than the code — that is what the
sentence is for — or run the `ssh … < scripts/node-bootstrap.sh` line above directly, where
the codes are the script's. It refuses rather than
guessing, and these are the refusals worth knowing about before you start — each one is a
mistake you want stopped here rather than found on a node that says it is ready:

- **No key, or a key that is not a public key.** The private half belongs in the node
  record, encrypted, and never on a node — a key generated or pasted on the host would sit
  in clear on the machine most likely to be seized. Generate the pair where the control
  plane lives (*Before any shape*, above) and pass the `.pub` half.
- **More than one key.** `authorized_keys` holds one key per line, so a value with a
  newline in it authorises *every* line in it for that account — including one you did not
  read. `--authorized-key-file` reads the whole file for the same reason: it used to take
  the first line and say nothing about the rest. Pass the one key the control plane
  authenticates with; if the file you are copying from holds several, choose there. This
  one is refused **before anything is installed**, so the host is untouched and the run is
  safe to repeat.
- **An argument that is not a port.** `--port` and `--ssh-port` are both checked on the
  command line, before the host is touched at all — a typo costs you a re-run and not a
  half-prepared node.
- **It cannot tell which port sshd listens on.** It reads the port this session arrived on
  and the ports `sshd -T` reports, and if neither answers it stops rather than enabling a
  firewall it cannot prove leaves you a way back in. Pass `--ssh-port`.
- **The account is not root and sudo wants a password.** The run is piped over SSH and must
  never prompt, so give the account passwordless sudo or run as root.
- **The account does not exist yet.** It authorises a key *for* an account and puts that
  account in the `docker` group; it does not create one. Make it first, name another with
  `--user`, or leave the flag off.
- **sshd on this host will not read the file the key was installed in.** The run asks
  `sshd -T -C user=THE_ACCOUNT` which files the daemon really consults *for that account*,
  because a key in a file sshd never opens is not an authorisation. The shape that does
  this is a host taking its keys from an `AuthorizedKeysCommand` — instance metadata, on
  most cloud providers — with no `AuthorizedKeysFile` beside it. Add the key to whatever feeds that command, or set
  `AuthorizedKeysFile` in `/etc/ssh/sshd_config`, reload sshd, and run this again.
- **sshd reads that file and still will not let this account in with a key.** A different
  sentence from the one above, and the run asks both: `PubkeyAuthentication no` accepts no
  key from that account; an `AuthenticationMethods` list with no alternative that is a key *on
  its own* — `publickey,password`, where the comma means both are required — leaves the
  control plane, which has only a key, half way in; and with the default `ssh_user`,
  `PermitRootLogin no` or `forced-commands-only` keeps that key out of root. Fix the
  directive it names and reload sshd, or prepare another account with `--user` and
  register **that** name. `prohibit-password` is not one of these: it permits a key and
  refuses only a password, which is what a hardened host should have.

  **Both questions are asked about the account you are preparing**, not about the top of
  `sshd_config`: the run hands sshd `-C user=THE_ACCOUNT`, so a `Match User` or `Match
  Group` block that moves this account's keys or switches them back on for it is part of
  the answer. It hands sshd **no address**, which is deliberate and is the limit — a
  `Match Address`, `Match Host`, `Match LocalAddress` or `Match LocalPort` block is not
  seen, because an address in that script would be a piece of node topology the fleet
  could not rotate away from.
- **`net.ipv4.ip_forward` is not 1.** Then the kernel moves no packet from a tunnel out to
  the internet, and every other signal stays green while nothing arrives anywhere. It is 1
  on most hosts only because the docker daemon sets it at every start. Set it, put it in a
  file under `/etc/sysctl.d/` so it survives a reboot, and run this again — the script
  reads that setting and never writes one.

**One thing it names and does not refuse:** strict reverse-path filtering
(`net.ipv4.conf.all.rp_filter` and `net.ipv4.conf.default.rp_filter`, where `1` is strict
and `2` is loose). It is correct on a leaf and it breaks an **entry** node — the replies
coming back over the hop arrive on the hop's interface, the kernel decides they should not
have, and drops them before anything on the host sees them, so the hop handshakes and
carries nothing. The script is not told which role you will register the host in, so it
prints what it found and leaves the decision with you. If this box is going to be the
entry, set both to loose, or off, before you register it.

### Which accounts work

**Root works, and so does any account with passwordless `sudo`.** That is the whole list,
and both halves of the product agree on it — a test fails if they stop.

The control plane logs into a node as exactly the account in the node record and **never
escalates**: no `sudo`, no `su`, nothing per-node to switch on. It is a library that
configures upstream daemons, and giving it a privilege model would give every node one.
That is affordable only because the account already has everything it needs by the time
the control plane first connects, and arranging that is this script's job:

- **it owns `/opt/hashi`**, created here empty and `0700`, because `/opt` is root-owned and
  the account could not create it itself;
- **it is in the `docker` group**, so it can reach the socket the data plane runs on;
- **its `authorized_keys` holds the control plane's public key**, and nothing else
  authenticates.

Pass `--user THE_SSH_USER` when that is not the account you are running the script as, and
register **that** account in the panel — the run's `register it in the panel with ssh_user`
line names the one it prepared. An account the script never saw has none of the three.

**A host prepared before this script existed, or by hand as root, and now driven as a
non-root account** is missing the first of the three. The apply fails with a sentence
naming the directory rather than a `Permission denied` from inside a `mkdir`, and there are
two ways out: run this script against the host, or create the directory once, as root:

```bash
install -d -m 700 -o THE_SSH_USER /opt/hashi
```

**Changing the account of a node that has already been applied to** has its own section
below — *Changing the account a node is driven as*. Re-running this script with the new
`--user` is now enough for the **host** half, and no recursive chown typed by hand is
needed or wanted. The half it cannot do is change which account the control plane dials,
and that is where the cost is — read that section before you change the account of a node
that is serving.

### What a finished run says

```
==> created /opt/hashi, empty and owned by <user>
==> sshd reads <the account's ~/.ssh/authorized_keys>, so a key installed there is one it will consult
==> the running firewall was asked and it is not logging
==> ready: docker <version>, key authorised, firewall up, logging off
==> register it in the panel with ssh_user <user> and ssh_port <port>
==> no hashi code and no hashi state was installed here — /opt/hashi is an empty directory owned by <user>, and the control plane fills it on your first apply
```

**Two of those lines are about the same thing said twice, deliberately.** Earlier in the
run the script reports what `/etc/ufw/ufw.conf` says, because while ufw is inactive that
file is the only thing there is to read. It claims the firewall is not logging only after
asking the running firewall, and it refuses if the answer is anything else — the two can
disagree, and a ufw that silently ignores `ufw logging off` is exactly that host. This is
the one record the charter forbids at any level, so the run says what it read rather than
what it assumes.

Take the `ssh_user` and `ssh_port` from the `register it in the panel` line — it names the
port this session actually arrived on, which is the one port known to work from outside. Then, in the panel:
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
==> /etc/ufw/ufw.conf already reads LOGLEVEL=off
==> <port>/<proto> was already open
==> incoming was already denied by default
==> the firewall was already up — its existing rules were kept
==> /opt/hashi was already here — <user> now owns it and everything an earlier apply left inside it; nothing in it was read, changed or removed
==> no hashi code and no hashi state was installed here — /opt/hashi was already here, and the control plane replaces what is in it on your next apply
==> /opt/hashi was already here before this run — whatever an earlier apply left in it, this run neither read, changed nor removed it; it now belongs to <user> along with the directory, so an apply as that account can replace it
```

The closing line is the one from the first-run block above, in the form this run can
honestly make: a host that already has the directory is not told it is empty. Both forms
say the same thing about what the script installed, which is nothing.

Nothing there is a warning. What the script never does is **close** anything: the rule set
is the union of every run, because a script that withdrew a rule could withdraw the one
carrying the session running it. Narrowing a rule set is an operator's job, done knowingly.

### Changing the account a node is driven as

The last two lines above are the whole of it, and they are there because the obvious
reading of this section used to be wrong. A node applied as one account and then handed
to another kept the **files** of the first: `/opt/hashi` belonged to the new account, and
everything an apply had written inside it still belonged to the old one. The next apply
failed on a permission error naming a path — three layers away from the account that
caused it, on a host whose bootstrap had just said `ready`.

So re-running the script with `--user <new account>` now **is** sufficient — **for the
host**. It takes ownership of the directory's contents along with the directory, reading
none of them and removing none of them; the account it prepares can then replace every
file an earlier apply left.

**The control plane's half cannot be changed today, and it is the expensive half.** A
node's `ssh_user` is written once, at registration: nothing in the panel or the API
updates it, no screen displays it, and there is no way to delete a node record either. So
a host handed to a new account and a record still naming the old one disagree for ever —
the record is what decides which account is dialled, and every apply fails on an account
that no longer owns `/opt/hashi`. There are two repairs and neither is the one the last
paragraph of this section used to promise:

- **Prepare the host for the account the record already names.** Run this script again
  with that `--user`. Cheapest by far, and the right answer whenever the new account was
  a convenience rather than the point.
- **Or register the host a second time**, as a new node with the new `ssh_user`, enable
  the same transports on it, apply *it*, and then set the old record to `retired`. Two
  records may point at one host — the node table allows a repeated address precisely for
  a migration like this — but only one of them may ever be applied, because both push
  into the same `/opt/hashi` and the later apply overwrites the earlier one. The cost is
  that this is a **new node in every user's subscription**: everyone picks it up at their
  next refresh, and loses the retired one at the same refresh.

If you no longer know which account a record names, nothing in the product will tell you —
take the second repair.

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
  send a packet anywhere. Whether a user inside Russia can reach this node is a field
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

**This is 13 commands on 11 lines, and `panel-bootstrap.sh` is one of them.** It is the
honest one — it refuses to invent your secret key, it verifies the control plane answers
before it claims success, and a second run changes nothing — but it is a step inside this
block and not the whole of it, and the charter's *one script per host* is about nodes
before it is about this box. On a host that is genuinely bare, two more come first: the
docker install line above, and your package manager's `git` and `make`.

```bash
git clone <this repo> /opt/hashi-control && cd /opt/hashi-control
cp .env.example .env && "${EDITOR:-vi}" .env        # see the table above

ufw logging off                                # FIRST, always — see below
ufw allow <the port sshd listens on>/tcp       # sshd -T | awk '/^port /{print $2}'
ufw allow <Caddy's plain-HTTP port>/tcp        # the ACME challenge and the redirect
ufw allow <Caddy's HTTPS port>/tcp             # the DELIVERY endpoint, not the console
ufw allow <this node's transport port>/udp     # the number you enter in the node record
ufw enable

make panel-bootstrap
make up-panel

curl -o /dev/null -w "%{http_code}\n" https://<your panel host>/panel/    # expect 404
```

**That `404` is the milestone working.** The console is not on the public hostname — it is
on the private site, reached over the management tunnel or over the SSH forward. See
*Reaching the panel* above, which is also where the console's own port is opened.

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

In the panel — reached over the management tunnel or the SSH forward, never over the
public hostname (*Reaching the panel*):

1. **Add node.** `address` and `ssh_host` are both this box's public IP — the control
   container dials out and back, which works; `172.17.0.1` is the fallback if the public
   address is awkward. `ssh_user root`, port 22, private key = the contents of
   `~/.ssh/hashi-node`.
2. **Enable a transport: `amneziawg` on UDP 51820.** Right here it is the right choice,
   because this box dials no hop. Its plain cousin is not offered — see *What to give an
   entry node's users instead* for what was measured. Read *The one combination that
   will not render* before you make it the entry end of one: once this box dials a hop,
   this row is what the hop form refuses. The form asks one more
   thing for this family — **how many users this row may hand an address to**, counted
   up from `peer_tunnel_address`. Size it for the fleet you expect rather than for
   today's: the number is a ceiling, raising it later is a resize, and the box says how
   many people it is being measured against.
3. **Apply.** The node is serving at this point and nobody is on it yet.
4. **Add a user**, open their subscription link, load it into a stock client. The
   WireGuard family is a config *file* rather than a URI, so it is the
   `?format=client-config-file` form of that link that carries it — the plain link is
   empty on a box that offers only `amneziawg`, and empty is not an error.
5. **Apply again.** This is the step an acceptance walk had to work out for itself, and
   the one that costs a user an evening: adding a user changes what the panel *would*
   push and touches no host. Their configuration file is complete and correct the moment
   it is issued — their own address, the node's real public key — while the node holds no
   peer for them and their client handshakes into nothing. The panel says so now: the
   Users screen and the dialog that hands the link over both name the nodes that are not
   running what this panel would give them. **Any change to who may use a node — a user
   added, a user revoked, a pool resized — is an apply, on every node that serves them.**

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
Users only ever hold E's address; a blocked leaf is replaced by re-pointing one hop,
with nobody touching their device.

Everything from Shape A applies to box E, plus:

1. Bootstrap the control plane on **E** exactly as in Shape A.
2. Prepare **L** with *Preparing a leaf* above, then register **E** as a node
   (`ssh_host` = its own IP) and **L** as a node (`ssh_host` = L's IP, reachable over SSH
   from E). Give **E** a `resolver` as you register it: E dials a hop, and such a node does
   not render without one (*A node that dials a hop needs a resolver*, below).
3. Enable a **user-facing** transport on E — `vless-reality` unless you have a reason
   for the other one. E dials a hop, so it must be a transport the table in *The one
   combination that will not render* (below) marks yes for a node with a hop; the panel
   refuses a kernel tunnel here, in whichever order you build the two.
4. Build the hop from the panel's hop form: entry = E, leaf = L, transport =
   `amneziawg`. The entry dials the leaf, always — E sits behind a Russian carrier NAT
   and cannot be dialled — so L listens and E reaches out.
5. **Apply both nodes.** Until you do, the hop exists only in the database.

### The two things shape B costs you

**Port 443 is contested.** Caddy owns 443/TCP on box E for the panel, so the
user-facing transport on E cannot be Reality on 443. Either put Reality on another
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
| **E** entry (RU) | one user-facing transport, one hop end (dials) | 22/tcp from C, the user port | the hop's UDP port to L |
| **L** leaf (abroad) | one hop end (listens) | 22/tcp from C, the hop's UDP port from E | — |

1. Bootstrap the control plane on **C** (the Shape A control-plane block, unchanged).
2. Prepare **E** and **L** with *Preparing a leaf* above — one script run each — and
   register both as nodes. **Choose the hop's UDP port before you run either script**, and
   pass it as a `--port` on **L**: the leaf is the end that listens, `node-bootstrap.sh`
   is what opens the port in its firewall, and step 4 is where the form asks you for that
   number. An acceptance walk did it in the printed order, reached the hop form with a
   port nothing had opened, and had to run the script on the leaf a second time — safe,
   purely additive, and a third command in a two-command procedure. Nothing in the product
   warns you, because the script is not told which role the host will be registered in. Both `ssh_host` values are real remote addresses this time; the
   control container needs outbound SSH to each. Give **E** a `resolver` as you register
   it (*A node that dials a hop needs a resolver*).
3. Enable **`vless-reality` on E, port 443** — free here, because the panel is on another
   box. Give it a `decoy_host` of your own choosing. A VLESS transport is not merely
   convenient here: E dials a hop, and that is the only kind of user-facing transport
   such a node can render at all (*The one combination that will not render*).
4. Build the hop: entry = E, leaf = L, transport = `amneziawg`.
5. Apply both nodes. Until you do, the hop exists only in the database.
6. Add users. Their subscription contains E and never L: a hop is never granted to a
   user and never appears in a subscription, because a user holding the entry↔leaf
   tunnel would route straight past the entry the topology exists to hide behind.
7. **Apply E again**, for the reason Shape A's step 5 gives: a user added since the last
   apply is a change no host has been told about, and their link is complete and correct
   before any node has heard of them.

Where to put box C is a real decision, not a formality. Outside Russia, it is out of
seizure range but the delivery endpoint may be unreachable from a Russian network under
whitelist mode — exactly when a user needs to refresh a config. Inside Russia, it is
reachable but carries the problem described under shape B. The repository serves the
panel and the delivery endpoint from one Caddy site, so today you choose one location for
both.

---

## Growing out of Shape A — the box you have becomes the leaf

**This is the move most operators actually make, and Shape B read literally is not it.**
You ran Shape A because this page calls it the right first run: one box abroad, carrying
the control plane and a node, with `amneziawg` for your users. Months later you rent a
Russian box, and the charter's topology becomes buildable for the first time. The shapes
above are a choice between three fresh builds; this is the one migration between them,
and it is written down because the obvious reading of it is expensive.

**Do not make the box you already have the entry.** Giving a hop to a node that already
offers its users a kernel tunnel is refused at the hop form — *no hop was established —
`E` already offers `amneziawg` to its users …* — and correctly, because that node could
never render again (*The one combination that will not render*, below). The refusal names
two ways out, and **the one you will reach for is the one that costs you every user on
that box.** Removal is what destroys material, and the panel says so before you confirm:

> `amneziawg` removed from `E` — *out of every user's link at their next refresh, and the
> material minted for it is gone with it.*

Every user on that box then loses the credential their device is connecting on, and the
repair is to reach all of them with a new configuration — over whatever channel you have,
on the day you have just taken their working one away.

**So point the move the other way.** The box you already have becomes the **leaf**. The
box you just rented becomes the **entry**. The tunnel your users are connecting on is on
the box that does not move, so nothing they hold has to change and nobody is cut off at
any point of this.

| | before | after |
|---|---|---|
| the box you have, abroad | control plane, and `amneziawg` for your users | both of those, unchanged, **plus the leaf end of the hop** |
| the box you rent, in Russia | — | the entry: a user-facing VLESS transport, and it dials the hop |

**A leaf carrying both is supported, not a workaround.** A leaf's users exit by the
leaf's own route — that is route B, and a hop landing on the same box does not touch it —
so one node holds `amneziawg` for its users and `amneziawg` for the leaf end of the hop,
both enabled, and every user on the first row goes on connecting. Two rows on one node
need two ports and two ranges of their own (*Rules that are not optional*, below); nothing
else about them collides, and neither has to be taken away for the other to exist.

1. **Prepare the new box** with *Preparing a leaf* above — the script is the same
   whichever end a node turns out to be — and register it. Give it a `resolver` as you
   register it: it is about to dial a hop, and such a node does not render without one
   (*A node that dials a hop needs a resolver*, below).
2. **Enable a user-facing transport on it** — `vless-reality` unless you have a reason
   for the other one, with a `decoy_host` of your own choosing and never a shared one.
   This box dials a hop, so it is the one node in your fleet whose users may not be on
   a kernel tunnel. Reality has the HTTPS port to itself here, unlike Shape A's box: the
   panel is not on this machine.
3. **Build the hop** from the panel's hop form: entry = the box you rented, leaf = the
   box you already have, transport = `amneziawg`. The entry dials and the leaf listens,
   so the hop's UDP port is opened on the firewall of the box you have been running for
   months, not on the new one.
4. **Apply both nodes.** Until you do, the hop exists only in the database.
5. **Nothing your users already hold stops working.** Enabling that transport granted
   every active user material on it, so the new entry is in every subscription at the
   next refresh — on the *plain* link, since the VLESS pair is a URI list while the
   `amneziawg` they are connecting on is a config file (*The one combination that will
   not render*, below). The tunnel on their device is untouched. Taking the new way up
   is them loading that link into a client that speaks VLESS, once, at their own pace.

**When you want everybody behind the entry, withdraw the leaf's user-facing row —
do not remove it.** Withdrawing takes it out of every user's link at their next refresh,
leaves every credential minted, and is one press to undo if the new path disappoints you;
apply the leaf afterwards, or the host goes on serving what it was last given. Two things
to have done first: watched a user's traffic actually come out of the entry, and given
everyone still on the old tunnel time to load the new link, because this is the press that
takes their working route away. Removal is the irreversible one and there is no reason at
all to reach for it on this path.

**What this costs, and it is not what Shape B costs.** Your control plane stays on the box
abroad, so `HASHI_SECRET_KEY` never travels to Russia and Shape B's charter problem never
arises. What you take on instead is the other half of that same decision: your delivery
endpoint is now outside Russia, and a user inside it may be unable to refresh their
subscription at exactly the moment a whitelist shutdown makes them need to — the choice
set out at the end of *Shape C*, above. The third box buys you out of both, and this path
leaves you one rental from it: move the control plane and neither node moves.

---

## The one combination that will not render

**On a node that dials a hop, users may not be on a kernel tunnel.** Following this
runbook used to produce exactly that: `amneziawg` for box E's users, because Shape A
names it, and `amneziawg` for the hop E dials, because the hop requires it.

**The panel refuses it at both doors, before anything is written.** Enable such a
transport for the users of a node that already dials a hop and the dialog answers *nothing
was enabled — this node's traffic leaves through a hop, and `amneziawg` cannot carry a
user's out through one …*; build a hop from a node that already offers one to its users and
the hop form answers *no hop was established — `<node>` already offers `amneziawg` to its
users …*. Both name the two ways out: give that node's users a transport that terminates
their connection and re-originates it, or take the other row away. Nothing is enabled,
nobody is granted anything, and no user is handed a file.

That refusal is M25's, and it is worth knowing what it replaced. Until then the panel took
both rows without a word, granted every user a credential on the new one, and handed one of
them a complete, importable configuration file over their own subscription link — for a
node whose apply then refused to render it. Three yeses and a no, in that order, with the
no arriving last.

Two instances of one transport on one node are otherwise ordinary — they collide on a
**listening port**, on a **config name** and, for the WireGuard family, on their **tunnel
ranges**, which may not overlap (*Rules that are not optional*, below). On a **leaf** they
are exactly right: give the hop a range of its own and two `amneziawg` rows on two ports
share none of the three. It is the node that DIALS the hop that may not also hand one to
its users.

**If a node is already in that state, the apply is still what refuses it** — a fleet built
before this refusal existed, or a database edited by hand. It arrives as a banner on the
Nodes screen:

> `amneziawg could not be rendered for this node — EgressNotRenderable:` … *A tunnel whose
> packets this node's kernel routes cannot send them out through a different interface, so
> they would leave by the node's own route instead — which is the silent failure the hop
> exists to prevent. Give this node's users a transport that terminates their connection
> and re-originates it, or take the hop away.*

**That banner is the only signal you get, and the node does not go `degraded`.** The
refusal happens while the configuration is being rendered, before anything is written to
the host, so there is no half-configured node to mark and the node's state is left exactly
as it was. An entry that was already `active` therefore **stays active and stays in every
user's link**, serving whatever its last successful apply left on the host — an operator
scanning the Nodes screen for something red finds nothing. Read the banner, and treat a
node whose apply you cannot complete as one that is serving a configuration you did not
choose. The way out is the one the doors name: take one of the two rows away.

**That is a refusal, not a defect.** A wg-quick-family tunnel hands a user's decrypted
packets to the entry's own routing table, and the only route this project renders for a
hop is source-based, from the hop interface's own address. A user's packets never match
it, so they would leave by the entry's own route — an exit in the country the hop exists
to leave, with every screen green. Refusing beats that (`docs/decisions.md`, decision 3).
The **leaf** end of the same hop renders fine; it is the user-facing side on the entry
that cannot.

**What to give an entry node's users instead.** A transport whose data plane
*terminates* the connection and originates a new one, which is what the refusal asks for.
In this image that is the VLESS pair, `vless-reality` and `vless-ws-tls`. Both are Xray,
which forwards no packet in the kernel: it accepts the user's connection and opens its
own, and on a node with a hop that new connection is bound to the hop's near address. So
it can only reach the internet through the hop, and while the hop is down it cannot be
opened at all — fail closed, as a property of the rendered file rather than a rule someone
has to remember.

Between the two, `vless-reality` needs nothing placed on the host: it borrows a decoy's
handshake, so give it a `decoy_host` of your own choosing and never a shared one.
`vless-ws-tls` needs a real certificate and key **already on the node**, named by path —
nothing in this project puts them there — so it is the right answer only on a host where
you already terminate TLS for a name you own.

`amneziawg` stays exactly right for users on a node with **no** hop: Shape A's single
box, and a leaf. There the same row renders a local exit, which is the shape a real client
was measured carrying traffic on.

**Its plain cousin does not, and is retired: the panel no longer offers it.** `wireguard`
is still in the image and a node already running it still serves it — but the pinned data
plane writes its forwarding rules on one netfilter backend while the firewall this runbook
has you enable writes its default-deny policy on the other. Both are traversed, so the
accept never front-runs the drop: a user's handshake completes, nothing is carried, and
neither end says anything. Measured twice on a live node. The Transports screen states it
on the row, with the reason; the enable dialog simply does not list it.

Every transport this image ships, and what each one may be asked to do:

| transport | users on a node with a hop | users on a node with no hop | the entry→leaf hop |
|---|---|---|---|
| `vless-reality` | yes — Xray terminates the connection and originates its own | yes | no — a hop is two ends of one tunnel network that each need an address of their own, and this transport hands its consumers none: it identifies them by their material |
| `vless-ws-tls` | yes, once a certificate and key are on the node | yes, on the same condition | no, for the same reason |
| `amneziawg` | no — the panel refuses it at both doors, and an apply refuses a node already in that state | yes | yes, and today it is the only one |
| `wireguard` | no — the same refusal, for the same reason | no — retired: the panel does not offer it, and a row enabled before that carries no traffic on a host this runbook prepared | no — it is protocol-blocked where this matters, and the form will not offer it |

Every cell in it is checked against the code by `tests/infra/test_deploy_runbook.py` —
against the renderers for the first column, the panel's own enable dialog for the second,
and its hop form for the third. A fifth transport, a retirement, or a change to what one
of these can do turns that suite red rather than leaving this table quietly wrong.

**A wg-quick-family config needs a resolver tool on a plain Linux client, and what it does
without one looks like the node's fault.** The file this project generates carries a
`DNS =` line, and `awg-quick`/`wg-quick` implement that line by shelling out to
`resolvconf`. On a Linux box without it the run **brings the interface up and then deletes
it again**, which is `awg-quick`'s own error path and not a failure on the node:

```
[#] ip link add awg0 type amneziawg
[#] ...
[#] resolvconf -a awg0 -m 0 -x
/usr/bin/awg-quick: line NNN: resolvconf: command not found
[#] ip link del awg0
```

The last line an operator reads is about a program they have never heard of, after a
tunnel that appeared to work for a second. **Install `resolvconf` or `openresolv` on that
machine and run it again** — on Debian and Ubuntu that is `apt install openresolv`. Two
things it is not: nothing on the node changes and nothing on the node is wrong, and the
node's own `resolver` field is a different thing entirely — that one is for a node that
dials a hop, below. Stock GUI clients on phones and desktops resolve names themselves and
never touch `resolvconf`; it is the operator testing from a shell who meets this, which is
exactly who this page tells to *"load it into a stock client"*.

**Do not answer it by deleting the `DNS =` line.** That line is what sends a user's
lookups through the tunnel; without it their device keeps asking a resolver it can no
longer reach, and the tunnel that looked fixed resolves no names at all.

**The two families are delivered differently, and you find that out before your users
do.** A VLESS transport rides the subscription link the panel shows. The WireGuard family
is a config file: the same token, `?format=client-config-file`, an archive. A user whose
node offers only AmneziaWG and whose client opens the plain link gets an empty document
rather than an error — so hand them the `?format=` URL, and expect the plain link to carry
entries again once that node's users are on a VLESS transport.

### If you already built it the other way

The way out is in the panel, and it is **removal** rather than withdrawal. Withdrawing the
user-facing `amneziawg` does stop the apply failing — a withdrawn row is not rendered at
all — but it leaves the row on the node still holding its listening port, its config name
and its tunnel range, its users' material still minted for a transport that node can no
longer render, and a trap for whoever offers it again: the same apply fails the same way.
Removing it takes the row, the material, the port, the name and the range.

1. **Nodes → transports** on the entry box. Both `amneziawg` rows are listed, and the
   second one created carries a config name of its own — it reads `amneziawg
   (amneziawg-2)` — so the two cannot be confused. The hop end is the row whose standing
   begins *one end of a hop*, and it is drawn with no buttons at all.
2. **remove** the user-facing one, and read the dialog before you confirm: removal
   destroys the material every user holds on that row and frees its port, its config name
   and its tunnel range, and it is the only action that does any of the three. `withdraw`
   beside it is the reversible one, and it is not what gets you out of this.
3. **Enable a VLESS transport** for users on that node, on a port nothing else there
   listens on.
4. **Apply the node.** Removal does not push: until you apply, the host is still running
   the container the panel has stopped showing.

Two things removal deliberately does not do. It does not revoke anybody — those users lose
that one entry at their next refresh and keep everything else. And it does not unlink the
config the last apply wrote under `/opt/hashi/conf/`: that file still holds the node's
private key and every credential that transport carried, and nothing in this project ever
unlinks a rendered config — the same is true after a withdrawal and after a dissolved hop.
Once you have applied, nothing on the node serves that file and no copy of what is in it
remains in this panel; what is left is key material at rest on a host that can be seized.

**So delete it, and it is the one exception to *never edit anything under `/opt/hashi`*.**
After the apply that removed the service:

```bash
ls /opt/hashi/conf/                              # every rendered config on this node
rm /opt/hashi/conf/THE_CONFIG_NAME.THE_EXTENSION # the name the panel showed on that row
```

**The extension is the transport's, not a fixed one** — the WireGuard family is written
`.conf`, because wg-quick takes the interface name from the file name and loads nothing
else; the VLESS pair is written `.json`, because Xray reads JSON. So the file this
section's own advice leaves behind — the `amneziawg` you removed — is a `.conf`, and the
next one you orphan, once that node's users are on a VLESS transport, is a `.json`
holding that transport's node key, its secret path and every user's id. Both are the same
kind of residue and both are covered by this exception. `ls` first, and go by the config
name the row carried.

**Only for a transport that is no longer enabled on that node.** The standing rule holds
for every other file there, and for the reason it gives — the control plane generates them
and overwrites them on every apply. An orphan is the exception precisely because nothing
regenerates it, which is what puts it outside that reason. `docs/tracker/field-checklist.md`
carries the same carve-out; if the two ever disagree, they are describing the same file and
one of them is stale.

To take the hop away instead, use the **Hops** screen. Removing or withdrawing one end of
a hop is refused wherever you ask for it, because it would leave the other end holding a
tunnel to an exit that is no longer configured.

## A node that dials a hop needs a resolver

**On a node that dials a hop, a user's destination names are looked up through the hop,
at a resolver named on the node's record — never by the host's own.** Before this, the exit
had moved abroad and the lookups had not: the proxy asked the entry host's resolver, inside
the network the hop exists to leave, one query per site a user visited
(`docs/decisions.md`, 2026-09-09). Whichever resolver you name still sees the names — from
the far end of the hop rather than from the entry's network, which is the exposure that
decision accepts knowingly.

A node that dials a hop and has no resolver is refused at **apply**, on the entry, with this
in a banner on the Nodes screen:

> `vless-reality could not be rendered for this node — ResolverMissing:` *this node's
> traffic leaves through a hop, and its record names no resolver for the destinations its
> users ask for. Without one they would be looked up by this host's own resolver — on
> the near side of the hop, inside the network the hop exists to leave — while the traffic
> itself exits at the far end. Nothing is rendered until the node has one: an IPv4 address
> the far end of the hop can reach.*

Like the refusal above, it happens while the configuration is being rendered, so the node
does not go `degraded`: an entry that was already `active` **stays active on whatever its
last successful apply left** — its users' lookups still going to the host's resolver — and
a user you revoke **keeps working there**, because a revocation's re-push is a render too.
The revocation's banner says so, naming the node.

**Do it right after the upgrade that brings this refusal — before the next apply, and before
you revoke anybody: give every node that dials a hop its resolver.** The upgrade adds the
field empty on every existing node, because any value it wrote would be a resolver this
project chose for you; from that moment each existing entry is in the state described above.

1. **Nodes → resolver** on each node that is the entry end of a hop — the Hops screen lists
   them. Give an IPv4 address the far end of the hop can reach: a public resolver of your
   choosing, or one inside the leaf's own network. A name is refused, and so is a loopback
   address — a stub resolver on the entry would answer from the entry. **An address the
   entry itself holds on one of its own interfaces is the case nothing here can catch:**
   the host answers it locally, on the near side of the hop, and neither the panel nor
   `edge` can see which addresses a host holds. Avoiding that one is yours. The same call
   without the panel is `POST /api/nodes/<id>/resolver` with `{"resolver": "<address>"}`.
2. **Apply the node.** Setting the resolver changes the record, not the host.

A new node takes its resolver in **Add a node**, in the box of the same name. A node that
never dials a hop leaves it empty: its lookups and its exit already leave from the same
place, and its configuration does not change.

---

## Upgrading an install that predates the rename

**The person who uses hashi is a `user`. They used to be a `friend`** — in the API, in
the panel's routes and in the database — **and this release moves all three at once.**
**Nobody has to be sent a new link and nobody has to touch their device.** A
subscription URL issued before this is byte-identical after it, so is the token inside
it, `/sub/{token}` is untouched, no token is reissued, and a VLESS document comes back
byte for byte as it went out. A WireGuard-family config comes back with **every
functional line identical** — private key, address, MTU, the AmneziaWG obfuscation
values (`Jc`, `Jmin`, `Jmax`, `H1`–`H4`), peer key, preshared key, `AllowedIPs`,
endpoint, keepalive — and one `#` comment reworded, which `wg-quick` and `awg-quick`
ignore. The device connects on that file exactly as it did. It is not the same file,
though, and the panel counts the difference: read *Every WireGuard-family node reads as
drifted*, below, before you read the Overview.

What does change is what you can call from a script. **Anything scripted against the old
paths stops working** the day this lands. There is no alias, no redirect and no
deprecation window — the old paths answer `404`.

| was | is |
|---|---|
| `GET` / `POST /api/friends` | `GET` / `POST /api/users` |
| `GET /api/friends/{friend_id}/subscription` | `GET /api/users/{user_id}/subscription` |
| `POST /api/friends/{friend_id}/revoke` | `POST /api/users/{user_id}/revoke` |
| `/panel/friends`, `/panel/friends/table`, `/panel/friends/new` | `/panel/users`, `/panel/users/table`, `/panel/users/new` |
| `/panel/friends/{friend_id}/subscription` | `/panel/users/{user_id}/subscription` |
| `/panel/friends/{friend_id}/revoke` | `/panel/users/{user_id}/revoke` |

**And one field moved inside a body that still parses.** A revocation now answers
`user_id` where it answered `friend_id`. A consumer reading the old key gets `None`
rather than an error — nothing raises, nothing is logged, and whatever it was going to do
with that id it now does to nobody. That is worse than a `404`, because a `404` is
visible. Grep your own tooling for `friend_id` before you deploy rather than after.

### Every WireGuard-family node reads as drifted, and none of them has changed

Drift is a byte comparison: the panel renders what it would push now and compares that
against the digest of what it last pushed. A comment is bytes, so the one reworded
comment above is a difference. **The moment the new image is up, every node carrying a
WireGuard-family transport reads as out of sync, before anybody has touched anything.**
The Overview says *"Not yet pushed to `<node>`: that node is not running the
configuration this panel would give it"*, and the Nodes screen counts that row among the
drifted ones. A node whose transports are all VLESS is unaffected — its rendered document
did not move at all.

**On screen that is indistinguishable from a real configuration change**, and it arrives
at the one moment you are watching for trouble. It is not one, and no user is affected
while it stands: the config already on the device keeps working, because the line that
moved is one `wg-quick` never reads. Apply each of those nodes on the Nodes screen — an
ordinary apply, nothing special about it — and the count goes back to nothing.

**Expect it again, in the same shape, if you roll back.** Going back to the old image
re-renders the old comment, so every one of those nodes drifts a second time and needs
the same pass of applies.

### The two migrations, and how to go back

The container applies them itself: `deploy/docker/entrypoint.sh` runs `alembic upgrade
head` on every start, so bringing the new image up **is** the upgrade. Two revisions land.

- **`0008` renames, and only renames.** The table `friends` becomes `users`, both
  `friend_id` columns become `user_id`, and the indexes and constraints that carried the
  old name follow. No row is read or written and no encrypted column is opened, so it
  cannot fail on data and it cannot touch a token.
- **`0009` rewrites two stored words an operator reads back.** A transport's `purpose`
  goes `friends` → `users`, and two audit actions go `friend-added` / `friend-revoked` →
  `user-added` / `user-revoked`. Any other value in either column is left exactly as
  found. **`purpose` is handed back verbatim by the API**, so a consumer matching on the
  literal `friends` silently matches nothing from here on.

Both reverse exactly, and the round trip has been run against a copy of real data — and
so has the rollback below, on real hosts. **The order is the whole of it: downgrade under
the NEW image, stop the container, and only then put the old tree back.** The other order
does not work, cannot be recovered in place, and takes the delivery endpoint down while
it fails — *Do not roll the image back first*, below.

On the control-plane box:

```bash
# 1. Downgrade under the image that is still running. It is the only image that has
#    0008 and 0009 in it, and therefore the only one that can undo them.
docker compose --env-file .env -f deploy/docker-compose.yml exec control sh
# --env-file is not optional: without it every ${VAR} becomes an empty string and
# nothing says so.

# inside the container. alembic.ini ships inside the installed package, which is how
# the entrypoint finds it too — there is no checkout in that image to point at.
INI=$(python -c 'import control, pathlib; print(pathlib.Path(control.__file__).parent / "alembic.ini")')
alembic -c "$INI" downgrade 0007    # Running downgrade 0009 -> 0008, then 0008 -> 0007
alembic -c "$INI" current           # 0007
exit

# 2. Stop it, before anything can carry the schema forward again. `stop`, not `restart`
#    and not `down` followed by an `up`.
docker compose --env-file .env -f deploy/docker-compose.yml stop control

# 3. Put the old tree back in the checkout, then bring the stack up on it. That image's
#    entrypoint runs `alembic upgrade head` as always, but ITS head is 0007, so the
#    upgrade is a no-op and the panel comes up on the schema you just rolled back to.
git checkout <the commit or tag that predates this release>
make up-panel
```

**A schema rollback does not survive a restart, and that is why step 2 is a step.** That
`alembic upgrade head` in the entrypoint is unconditional and runs on *every* boot, so a
database left at `0007` under the new image is carried forward again by the next
`compose up`, the next `restart` and the next reboot of the host — with nothing to read
but two lines in the container log. Check `select version_num from alembic_version` when
you are done rather than assuming.

**Do not roll the image back first.** The old image ships `0001`–`0007` and nothing else,
so it holds no downgrade path from `0009` and cannot take the schema back for you. Its
entrypoint dies on `Can't locate revision identified by '0009'`, and `restart:
unless-stopped` makes it do that for as long as you leave it. Measured, in that state:

- the control container crash-loops, logging `applying migrations…` then
  `FAILED: Can't locate revision identified by '0009'`, over and over;
- `make up-panel` exits non-zero with `dependency failed to start: container
  hashi-control-1 is unhealthy`, and **Caddy never starts at all** — it sits in
  `Created`;
- so `/sub/{token}` refuses the connection for **every** user, from the first second of
  that state until you are out of it. That is the one route the whole design says stays
  up;
- and you cannot `exec` in to fix it, because `docker compose exec` on a restarting
  container answers `Container … is restarting, wait until the container is running`.
  The commands above are not available to you there.

Getting out of it is putting the new image back, doing step 1 under it, and continuing
from step 2 — the order above, arrived at the expensive way.

**Ask `alembic_version` that same question *before* you upgrade.** Because the upgrade is
unconditional and silent, a control plane sits at whatever revision its image last
carried — this project's own was **seven revisions behind** its repository when it was
measured, having been up since long before these two existed. The jump one container
start makes is from what `alembic_version` actually says to head, which may be a good
deal more than the two migrations above.

**Take a backup first** (*Backups*, below), and keep `HASHI_SECRET_KEY` where the dump is
not. A restore under the wrong key is not a broken migration and must not be read as one:
every screen that loads a user or a node answers *"The data is intact; the key is wrong.
Nothing has been changed."*, while a migration fault fails at the driver first, on an
undefined table or column.

---

## Rules that are not optional

- **Never plain WireGuard on the entry→leaf hop.** That hop crosses the border by
  definition, and a protocol-blocked transport there defeats the topology even in phase
  1. Use AmneziaWG or another obfuscated transport. This one is enforced rather than
  advised: the hop form offers only the transports that can carry a hop at all, which
  in this image is `amneziawg` and nothing else.
- **Never present plain WireGuard to a user as something that works from a Russian
  mobile network.** TSPU protocol-blocks it. It works everywhere else.
- **A decoy host is chosen per node and never shared.** There is no project default and
  there must never be one — if every node borrows the same handshake, the fleet becomes
  enumerable by that fact alone.
- **A node may run one transport twice. What it may not do is run it twice on one
  port, under one config name, or over one tunnel range.** Two rows on one node collide
  on three things. The **listening port** — with its protocol, so a TCP transport and a
  UDP one on the same number are two sockets and no conflict. The **config name**, which
  for the wg-quick family is also the interface name. And, for the WireGuard family, the
  **tunnel range**: two such rows on one node may not have overlapping tunnel networks,
  hop ends and disabled rows included. That third one is refused in the panel, under the
  box you typed it in, before anything is saved:

  > node `E` already carries `amneziawg` on a tunnel at … and … *is in the same range.
  > Two tunnels on one node cannot share one: their data planes write into that host's
  > single routing table, so a reply meant for one person's device would be sent to
  > whoever holds the same address on the other — and neither config file shows it,
  > because each is correct on its own. Give this tunnel a range of its own.*

  Overlapping is not only the same range typed twice: a range you widen on one row
  swallows the narrower one beside it, and that is the pair written by accident. This
  is the rule that meets you when you follow Shape A and then the hop it mandates on
  the same box — users and hop are two `amneziawg` rows on that node, and they need
  two ranges as much as they need two ports. Nothing else collides. A **disabled** row
  still holds all three, because freeing them would move the collision to the moment
  somebody switches it back on; removing the row is the only thing that gives them
  back.
- **A user-facing kernel tunnel and the hop a node DIALS still cannot share that
  node**, which is a different rule and the one that bites — *The one combination that
  will not render*, above. **Which end of the hop it is decides the answer**, so this
  rule is never absolute: on the **leaf** end the same two rows are ordinary and
  supported. A leaf's users exit by the leaf's own route, a hop landing there does not
  change that, and one box carries `amneziawg` for its users and `amneziawg` for the
  leaf end of the hop with both enabled — two ports and two ranges apart, exactly as the
  rule above requires. It is the node that dials the hop that may not also hand one to
  its users. That asymmetry is what makes *Growing out of Shape A*, above, possible at
  all.
- **A WireGuard-family row is told how many users it may serve, and the number is a
  ceiling.** AmneziaWG and plain WireGuard give every user their own address inside the
  tunnel, drawn from a pool that starts at the row's `peer_tunnel_address` and is as long
  as the `pool_size` you set when you enable it. One address is one user. A pool smaller
  than the people you already have is **refused before anything is saved** — at enable,
  when you add a user, when you offer the transport again, when you put the node into
  service and when you resize it — and the panel says so on the screen rather than after
  the press: Keys & configs shows `<users> of <pool>` per row, the add-user dialog names
  a pool that is full and offers no button, and a node whose pool is short is not offered
  the serving state. Resize on **Keys & configs → replace params**; there is no other
  action for it. VLESS transports identify each user by their own material and have no
  pool at all.
  *Until M17 these rows minted one shared address, so the second user on a node
  collided on `AllowedIPs` and the render refused, loudly — backlog item 33. A row
  enabled before that upgrade has no size, hands out exactly the one address it renders
  today, and is repaired by replacing its parameters with a size: the address the working
  device already holds is written down first and is never moved.*
- **Never edit anything under `/opt/hashi` on a node — with one exception.** It is
  generated by the control plane and overwritten on every apply. The control database is
  the source of truth, and that is what makes replacing a node safe. The exception is a
  **rendered config whose transport is no longer enabled** on that node — `.conf` for the
  WireGuard family, `.json` for the VLESS pair, since the extension is the transport's:
  nothing regenerates it, so the reason above does not reach it, and what it holds is the
  node's private key and every user's credential for that transport. Delete those, after
  the apply that removed the service — see *If you already built it the other way*, above.

## Known-unproven

`docker.io/masipcat/wireguard-go:0.0.20230223` has a tag that resolves but has **never
been started by this project**. Whether it accepts `up <config>` as its command is
discovered on your first real node. If it does not, that is a finding, not a mistake on
your side.

Every other data-plane image pin is checked against a real registry by
`tests/e2e/edge/test_every_image_pin_resolves.py` — a check that exists because one pin
in the tree turned out never to have existed at all.

**This project has never re-issued a certificate on a replacement host.** The reasoning
in *Backups* for not keeping `caddy_data` rests on issuance being automatic and on the
CA's published rate limits, both read rather than observed. The first real rebuild is
what turns that into a fact; if it does not go that way, that is a finding.

## Backups

```bash
make backup                                       # → backups/hashi-<timestamp>.sql.gz.age, mode 0600
make backup-upload FROM=backups/hashi-<...>.sql.gz.age  # send one that is already written
HASHI_RESTORE_AGE_IDENTITY=/path/to/identity \
  make restore FROM=backups/hashi-<...>.sql.gz.age  # destructive, so the path is required
make restore-from-bucket                          # the whole rebuild, on a machine that
                                                  # has never run this — see below
```

`make restore` is destructive and never picks "the latest one" for you: it is given a file
you are already holding, and choosing between files you can see is not a decision a
Makefile gets to make. `make restore-from-bucket` is the other case and does choose,
because there the artifacts are in a bucket you cannot see into at all and the alternative
is a restore that cannot be started — see *Coming back from the bucket, on a machine that
has never run this*, below, for how it chooses and what it prints.

**The file `make backup` writes is encrypted, whole, before it reaches the disk.** It is
`age` ciphertext, addressed to the public key in `HASHI_BACKUP_AGE_RECIPIENT`, and this
host holds only that public half: it can write a backup and **cannot read one back**. The
plaintext exists nowhere but in memory, in flight, while the dump runs — it is never a
file on this machine, not even briefly, so there is no moment at which a seizure catches a
plain copy on the disk.

Under the `age` layer it is plain SQL, gzipped, in which a *subset of columns* is
encrypted again — every node's `ssh_private_key`, every node_transport's `secrets`, every
user's `token`, `subject`, `secrets` and `tunnel_address`. **Opening the artifact and
reading it are two different secrets:**

1. the **age identity**, the private half of the keypair, which opens the file;
2. **`HASHI_SECRET_KEY`**, without which those columns cannot be restored.

Neither is on the control host, and that is the whole point: a seizure of this machine
hands over every backup it ever wrote and opens none of them. Keep the two apart from each
other as well — a copy of both in one place means one theft takes everything.

What a reader of the bucket learns, and the jurisdiction that bucket sits in, is written
down in `docs/decisions.md`. In one line: that a backup exists, how big it is and when it
was written — not a node address, not a leaf address, not how many users there are.

**Generating the keypair**, once, on a machine that is not the control plane:

```bash
age-keygen -o hashi-backup-identity.txt   # prints the public key; keep the FILE with you
```

The public key it prints goes in `HASHI_BACKUP_AGE_RECIPIENT` in `.env`. Until it does,
`make backup` refuses and says so. It will not write a plain artifact as a fallback,
because a fallback is how the plain shape survives.

**Restoring.** The identity is handed over at the moment of the restore, from whatever you
are carrying, and never written into `.env` on this host:

```bash
HASHI_RESTORE_AGE_IDENTITY=/path/to/hashi-backup-identity.txt \
  make restore FROM=backups/hashi-<...>.sql.gz.age
```

**What it asks before it replaces anything**: it names the env file, the compose project
and the database it resolved, counts what is in that database, and asks you to type the
database name — *unless there is nothing there*, in which case it says so and asks
nothing. A database with rows in it and no terminal to answer on is a refusal with a
sentence, not a silent exit; `FORCE=1` is the deliberate way past. Afterwards it prints
`make restart-control`, which restarts the control plane without changing what this host
publishes — **not** `make down && make up`, which would take every published port away.

`age` runs inside the control container, so nothing extra is installed on the box and any
host that can run the stack can restore. If the control plane itself will not start, open
the artifact by hand on any machine that has `age` and restore what comes out — the script
still accepts that shape:

```bash
age --decrypt --identity /path/to/hashi-backup-identity.txt <file> > hashi.sql.gz
make restore FROM=hashi.sql.gz
```

**A backup taken before 2026-09-23 still restores.** Plain SQL, gzipped, is what
`make backup` wrote until then; `make restore` takes it as-is and needs no identity. It
tells the two shapes apart by reading the file rather than trusting its name, and says
which one it found before it touches anything. Those older files are **not** safe offsite:
they are a map of the fleet to anyone who opens them, with every node's real address,
including the leaf addresses no user is ever shown. Keep them on media you control, and
replace them with a fresh backup at the first opportunity.

### Coming back from the bucket, on a machine that has never run this

The day this is used is the day the box is gone. What you have is a bare machine, this
repository, and three things you are carrying. One command does the rest:

```bash
# the runtime first — a genuinely bare host has none of docker, git or make; see
# "What every box must already have" above. This command does not install one for you.
git clone <this repo> hashi && cd hashi
cp .env.example .env

make hash-password      # prints the whole HASHI_OPERATOR_PASSWORD_HASH line to paste in.
                        # It runs inside this project's control image, so this host needs
                        # nothing but the runtime it already has.

# then fill in .env: HASHI_SECRET_KEY, the hostnames, that hash and the database
# password. That is what the control plane needs in order to START; where the BUCKET is
# is the next four lines, and it is not in .env on a machine that has never run this.

HASHI_RESTORE_AGE_IDENTITY=/path/to/hashi-backup-identity.txt \
HASHI_RESTORE_S3_ENDPOINT=<your store's own endpoint, with a scheme> \
HASHI_RESTORE_S3_REGION=<its region> \
HASHI_RESTORE_S3_BUCKET=<the bucket these backups are in> \
HASHI_RESTORE_S3_PREFIX=<the key prefix, if you set one> \
HASHI_RESTORE_S3_ACCESS_KEY_ID=<a key that may list and get> \
HASHI_RESTORE_S3_SECRET_ACCESS_KEY=<its secret> \
  make restore-from-bucket
```

That installs the control plane on this machine, reads the bucket, takes the newest
artifact that actually opens, and restores it. It is safe to run again after any failure —
with one exception on a host that is already serving, three paragraphs down.

**Why the four `HASHI_RESTORE_S3_` lines that are not credentials are there.** Endpoint,
region, bucket and prefix fall back to the `HASHI_BACKUP_S3_` block of `.env` — the right
default on a host that was taking backups, because that is where they already are. On a
machine rebuilt from `.env.example` that block is **the template's example store**, which
belongs to nobody: the walk of 2026-09-23 followed this section exactly, installed the
whole control plane, and died at a hostname out of the template with `Name or service not
known`. So either fill those four into `.env` beside the rest, or hand them to the command
as above. Either way the command **prints which of the two each value came from** before
it asks the store anything, so a value that came out of the template is visible before the
failure rather than after it. The two credentials never fall back to anything: the key in
`.env` may only write, and reaching for it silently would turn the clearest refusal there
is into a 403 that reads as your own key being wrong.

**`make hash-password` is here because the value could not be made on the machine that
needs it.** The hash is a scrypt digest produced by this project's own code, so the
documented route — `python -m control.cli hash-password` — needs the project installed and
Python 3.14. A host rented an hour ago has the system's Python (3.10 on Ubuntu 22.04) and
`make setup` cannot make a venv it does not have an interpreter for. Until this target
existed, one of the four values above required a **second working computer**, in the
middle of a rebuild: the walk of 2026-09-23 met it as a traceback, then a
`command not found`. The image the target builds is the same image the restore builds
seconds later, so it costs nothing the rebuild was not already spending.

**A terminal, or `FORCE=1`.** The restore replaces live data and confirms before it does,
and a confirmation needs somewhere to be answered. On a machine this command has just
installed from nothing there is nothing to confirm — the database holds no rows and it
says so instead of asking — so the ordinary bare-host run needs no terminal at all. If the
database does hold something and there is no tty (`ssh host 'make …'`, a wrapper, a cron
entry), it stops **before the bucket is read** and says so, rather than printing a question
into a session that cannot answer it. `FORCE=1` skips the question and nothing else.

**Then publish the ports, and mind which command.** The command ends by naming them; the
one to use on a freshly restored host is `make up-panel-over-ssh`, because `make up-panel`
wants `HASHI_PRIVATE_BIND_ADDR` to be a management-tunnel address this machine does not
have yet. See *The port-publication gap*. The closing screen prints the `ssh -L` line with
this deployment's own console port in it, read out of the running stack rather than left
for you to find in `.env`.

**"Safe to run again" is true of the data and false of the publication, on a host that is
already serving.** The install step converges the stack to the base compose file, which
publishes nothing — so re-running this (or `make panel-bootstrap`) on a host where
`make up-panel` had published 80, 443 and the console takes all three away until you
publish them again. Nothing is lost but reachability, and the database is untouched. The
bootstrap now **says so before it does it and again when it has finished**, having asked
the running stack what it publishes, so this paragraph is a second place rather than the
only one.

**No management tunnel is generated from the template's own values.** `.env.example` ships
a complete `HASHI_MGMT_*` block, and a machine rebuilt by copying that file arrives with
one. Generating a tunnel from it wrote a config here and printed a **full device config,
private key included**, for each of the template's example devices, pointing at the
template's example endpoint — credentials nobody asked for, for a host that is not this
one. The bootstrap compares the block against `.env.example`'s own line and skips the
generation, saying which mode it left the host in; fill the block in with this
deployment's values and run it again to get a real one. See *The management tunnel*.

**And the restored host is not backing anything up.** `HASHI_BACKUP_AGE_RECIPIENT` and the
write-only `HASHI_BACKUP_S3_*` credential lived only in the `.env` that was lost — that
file is deliberately in no backup — so `make backup` here refuses outright with
`required variable HASHI_BACKUP_AGE_RECIPIENT is missing a value`, and the crontab that ran
the schedule was on the old machine too. Put the **public** half of the age keypair you are
carrying back into `.env`, refill the S3 block, and run `make backup-schedule`. The command
says this on its last screen as well, and says which of the two cases it measured. Until
you do it, the fleet has exactly one copy of itself and it is the machine you just built.

**It does not move DNS, it does not re-issue the delivery endpoint's certificate, and it
tells no user anything** — the three that decide whether a restored control plane serves
anybody. They are the section immediately below, and the command says them again on its
last screen.

**`HASHI_SECRET_KEY` goes in `.env` here; the other two never do.** That is not the design
leaking — it is where the design puts it. The control plane cannot start without that key
and cannot read one node or user credential without the *right* one, so it belongs in this
machine's own env file exactly as it belonged in the lost machine's. What must never be
written onto a control-plane host is the **age identity** and the **read credential for the
bucket**: those are `HASHI_RESTORE_*`, they are handed to the command in its environment at
the moment it runs, and the command reads them from there and nowhere else. Putting them in
`.env` is not a working shortcut — it refuses, and says where they belong.

**Which object it takes.** It lists everything under the prefix, prints the newest ten with
the store's own timestamps, and takes the newest. The order is the **store's**
`LastModified`, not the object's name: the name is chosen by whichever key wrote the
object, and on a live control plane that is a key an attacker would hold. If the newest
does not open, it says so and walks back — up to five — and each attempt names what was
wrong with the one before it. `make restore-from-bucket OBJECT=<name>` takes exactly the
one you name and does not walk.

Unlike `make restore`, this one *does* choose for you, and the difference is the point:
`restore` is given a file you are holding, and here you cannot see into the bucket at all.
What it chose is printed beside everything it did not choose.

**The artifact opens before anything is asked of you.** It is decrypted and checked to be a
whole gzip stream *before* the destructive confirmation, so nobody types a database name to
authorise a restore that was always going to fail. Every object it fetched is left in
`backups/`, mode 0600, still encrypted.

**What each failure says, because at 3am "it did not work" is the difference between five
minutes and an hour.** Every one of them names which of the three inputs is wrong:

| What is wrong | What you get |
|---|---|
| No container runtime, no compose plugin, or a daemon that is not answering | Three different sentences, each naming which one, and *"Nothing has been fetched and nothing has been changed"*. `git` and `make` cannot be the problem here — they are what put this checkout on the machine and what ran the command |
| No `.env` | The copy-and-fill line, `make hash-password` for the value that cannot be typed, and why that file is deliberately in no backup |
| The env file is one compose cannot parse | The file and the line number, never the line — see *When the backup runs* |
| `HASHI_SECRET_KEY` missing from `.env` | The bootstrap refuses before anything is built, and never generates one |
| `HASHI_OPERATOR_PASSWORD_HASH` missing, or still `.env.example`'s placeholder | The bootstrap refuses at once and names `make hash-password`, rather than letting the control plane refuse the unfilled value three minutes later as a health-check timeout |
| No terminal to confirm on, and a database with something in it | Said **before the bucket is read**, with what it counted and with `FORCE=1`. A database this command just installed holds nothing and is never asked about |
| `HASHI_RESTORE_AGE_IDENTITY` unset or not a file | Named as the private half you carry, with the form to supply it in |
| The read credential is not in the command's environment | Named, with the reminder that the key in `.env` may only write and is not the one to reach for |
| Endpoint, region or bucket unresolvable | Every missing name at once, and that three of them may come from the `HASHI_BACKUP_S3_` block instead |
| The endpoint is set, and it is the template's | Before anything is asked of the store, the command prints the endpoint, the bucket and the prefix it is about to use **and which name each came from** — its own, or the `HASHI_BACKUP_S3_` fallback in `.env`. If the store then cannot be reached, the refusal names that same value rather than leaving a DNS error to be read as a network fault |
| The store refuses the credential | *"A restore needs a credential that may LIST and GET this bucket"* — the write-only key produces exactly this, and it is the most likely mistake on the list |
| No such bucket | Named as the bucket and not the key, because the credential answered |
| Nothing under the prefix | *"The credential works — this is the bucket or the prefix"* |
| The identity is not the one these artifacts were written to | *"The artifact is intact; the identity is wrong."* It stops rather than walking the history: every object was written to the same public half |
| The newest artifact is damaged | Says what did not open, and tries the one before it. Five, then it stops and tells you to name one |
| The restore itself fails part-way | The database is left exactly as it was — one transaction, `ON_ERROR_STOP` — and the artifact is still in `backups/` |
| `HASHI_SECRET_KEY` is the wrong one | **Nothing.** The restore succeeds: the rows arrive whatever the key is, and the columns holding node and user secrets stay shut. This is the one failure the command cannot see, so it ends by naming it — open the panel, and if the screens that touch a node or a user say *"The data is intact; the key is wrong."*, it is that one line and not another artifact |

### What `make restore-from-bucket` does not do

Everything on this list is an operator step. None of it is something a script may do on
your behalf, and all of it is the difference between a control plane that is *back* and one
that *serves somebody*.

1. **It does not move DNS.** Nothing in this repository touches a record. Your delivery
   name still points at the machine you lost, and until it points at this one, every user's
   link resolves to a box that is gone — the tokens are alive and the address is not. This
   is the one that leaves a perfectly restored control plane serving nobody.
2. **It does not re-issue the delivery endpoint's certificate.** `caddy_data` is
   deliberately not in the backup (see *What belongs in a backup, and what does not*): the
   old host's private keys are to be presumed compromised. Caddy asks a public CA for a new
   one the first time the name resolves *here* and inbound `:80`/`:443` reach this machine
   — which cannot happen before 1, and cannot happen at all until `make up-panel` (or
   `make up-panel-over-ssh`, on a host with no tunnel yet) publishes those ports, because
   the base stack publishes none. Until then `/sub/*` serves nothing.
   The panel itself is unaffected: it is served by Caddy's own CA, which is new, so each of
   your own devices is asked to trust the console once more. The costs and the issuance
   limits are in *The `caddy_data` cost, stated rather than waved at*.
3. **It tells no user anything.** No message goes to any user from this command or from the
   control plane — there is no channel, and that is a charter decision rather than an
   omission. If the delivery *name* is gone rather than merely pointing elsewhere, the
   tokens survived and the URL they live in did not, and every user has to be handed a new
   link by you.

It also does not tell you whether `HASHI_SECRET_KEY` is the right one, and cannot: see the
last row of the table above.

### Where the artifact goes, and the credential that sends it

With `HASHI_BACKUP_ENABLED=1` **in `.env`**, `make backup` sends the artifact it has just
written to the object store configured in the `HASHI_BACKUP_S3_*` block of the same file:
one `PutObject` to
`<endpoint>/<bucket>/<prefix><file>`, and nothing else. The store is addressed by the **S3
protocol, never by a provider's name** — the same rule as a node's country and address
living in a node record rather than in code, and for the same reason: a provider you cannot
rotate away from is one you are stuck with on the day you need to leave it. Moving to
another store is four lines of `.env` and no code.

**The credential kept on this host may only write.** `PutObject` and nothing else: no
`GetObject`, no `ListBucket`, no `DeleteObject`. Whoever holds this box holds that key, and
a key that can delete turns a seizure into the loss of the entire backup history as well as
the machine. That is half of the protection; the other half is enforced on the **bucket**,
where this key has no authority, and it is set up by hand when you create the bucket — see
*The retention this host's own key cannot reach*, below.

**What "uploaded" proves, exactly.** The SHA-256 of the artifact is inside the request's
signature, so a store that accepts the request has recomputed that hash over the bytes it
received; where the store returns a comparable `ETag`, it is compared against the same
bytes as well. That is a real statement about what arrived. It is *not* a statement that
the object is still there, that retention is keeping it, or that it can be read back — this
host holds a write-only credential and cannot look, which is the whole point. The only way
to verify a backup is to restore it, from a machine that holds the identity, which is the
part of this section above.

**When the upload fails, the dump does not fail with it.** The artifact is here, intact and
encrypted, and `make backup` exits **3** rather than 0 — a code of its own, because "there
is no backup" and "there is a backup and it never left the machine" call for different
actions. Send the same file once the store answers again:

```bash
make backup-upload FROM=backups/hashi-<...>.sql.gz.age
```

Nothing is dumped a second time, and the database is not touched. Use `https`: over plain
`http` the key id and the name of your bucket travel in the clear, and the upload refuses
unless the endpoint resolves to a private address.

**In the env file, and nowhere else.** `HASHI_BACKUP_ENABLED=1 make backup` on the command
line does not switch the upload on: two things read this value — the uploader, and the
thing that writes the backup record — and until M28.15 an exported one reached only the
first, so a run uploaded the artifact and `make backup-status` then said the upload was
switched off, about that same run. One file both of them can see is what stops that.

`HASHI_BACKUP_ENABLED=0`, or unset, is a supported mode rather than an oversight — the
artifact is written and stays on this host, and every run says so in as many words. It does
not switch the **schedule** off: a daily backup that never leaves the machine is still a
backup, and the section below keeps taking it. What still does not exist is a place for the
management directory inside the artifact (see *What belongs in a backup, and what does
not* — the artifact is the database and nothing else so far).

### When the backup runs, and how you know it did

```bash
make backup-schedule      # install it: one cron entry, no root, nothing new on the host
make backup-status        # when did one last succeed, and has one failed since
make backup-unschedule    # stop it
```

**Set the hour first**, in `.env`:

```ini
HASHI_BACKUP_AT=04:00
HASHI_BACKUP_TZ=Etc/UTC     # an IANA zone NAME — `Europe/Paris`, `Asia/Tokyo` — never an offset
```

`HASHI_BACKUP_AT` is a wall-clock time **in that zone**, and the zone is spelled out
because this host's clock is UTC and you are not. A name rather than `+02:00`: an offset is
a decision taken once about a rule that changes — by season, and by decree — and on the day
it changes, nothing anywhere tells you. Get it wrong in any of the three ways and the
backup still happens: an unset zone falls back to this host's own clock and is recorded as
`unset` (there is no correct country to guess at), a zone this host has never heard of is
recorded as `unknown`, and a time that is not `HH:MM` falls back to `04:00` and is recorded
as `malformed`. A typo must not cost you a day of backups; it costs you a line in
`make backup-status` until you fix it.

> The zone is **checked against this host's zone database, not trusted**, because
> `TZ=Nowhere/Useful date` does not fail — it answers in UTC and exits 0. A misspelled zone
> would otherwise be indistinguishable from a working one, which is the silent skew the
> variable exists to prevent.

**The cron entry carries no hour.** It runs every fifteen minutes and asks
`scripts/backup-run.sh` whether the day's backup is owed. That is the whole design, and the
reason is the failure this section exists to prevent:

> `0 4 * * *` is a promise cron cannot keep. If the box is off, asleep, or being rebuilt at
> 04:00, the minute passes and **nothing anywhere records that it did**. You find out
> during a restore.

So "today's backup has not been taken" stays true until one is taken. A box that was down
at 04:00 and came back at 10:00 takes the day's backup at 10:00 — late, and a late backup
is a backup. **The days that had none are written down by date**, and stay written down
after the next successful run; `make backup-status` and the panel both report them.
Deliberately **one** run, not one per missed day: a dump is a copy of the database as it is
now, so five runs today would be five copies of today wearing five different dates.

The first tick after `make backup-schedule` takes a backup immediately, because this host
has no record of one. That is on purpose — you learn within a quarter of an hour whether
the schedule works, instead of the morning after.

**What is recorded, and where.** `backups/state/last-run.json` on this host. It holds the
schedule's settings, the last attempt, the last success, the last failure, and the dates
with no backup — dates, exit codes and settings, **and nothing about any person**, now or
ever. The control container reads it through a read-only mount, which is how the panel can
answer *when did a backup last succeed, and has one failed since* without a credential that
could look in the bucket. Nothing on this host has one: see the section above.

**Where the panel says it.** At the top of the **Overview** — the screen `/panel/` opens on
— above the four counts, because a run that did not land has to be read without anybody
going to look for it. It says one of six things: *no backup has ever been recorded on this
host* (which is also what an empty mount says, and it means nothing recorded rather than
something broken); *there is a record and this panel could not read it*, assuming nothing
either way; *no backup has ever succeeded*; *nothing has been trying* — one succeeded, it is
days old, and nothing has failed since, which is what a schedule that was uninstalled looks
like; *backups are failing*; and a quiet muted line for a recent one. There is no colour
change between a blip and a disaster and there is not going to be one: what separates them
is the sentence — *"the last one that succeeded was 19 hours ago"* against *"43 days ago"* —
because a banner that shouts on the first failure is a banner that is ignored by the
fortieth. Every one of the six, the quiet one included, closes with a caveat saying what
it is not telling you.

**Which caveat depends on where that host sends, and this is the one thing on the screen
that is not about a run.** The record carries whether the upload is switched on, and the
panel reads it. With the upload **on**, the screen closes with *whether any of those
artifacts is still in the bucket* — the same caveat `make backup-status` closes with,
because the credential here may only write and cannot look. With the upload **off**, it
closes with *that this host is sending its backups anywhere*: nothing left the machine,
and a copy on the same disk as the thing it copies does not survive losing that disk. And
where there is no record at all, or a word the panel has no meaning for, it closes with
*whether anything was sent anywhere* — claiming neither, because it could not read which.

The middle one is the shipped default (`HASHI_BACKUP_ENABLED=0`) and it is not an alarm:
the artifact is still taken, the schedule still runs, and this is a supported mode. It is
said out loud because a caveat about a bucket, on a host that has no bucket, invites
exactly the belief that there is one.

**Two smaller things the screen now gets right, and both are about trusting the file less.**
The missed days are printed newest first — the panel sorts them itself rather than taking
the writer's order, so *"most recent"* points at now even during a gap that started weeks
ago; the writer stores them newest first as well, so the two agree without either taking
the other on trust. And a **run** in the record dated ahead of the clock the panel reads it
against is said so instead of being reported as a backup taken minutes ago: the age is still
clamped for the arithmetic, so a disagreeing clock cannot turn a stale backup into a fresh
one, but the screen goes loud with `clock ahead` and says no age on it can be believed until
the two machines agree about the time. A *run* and not the record's `due_date`, which this
screen does not read at all — that half is said on the command line only, and the Backups
section below says which is which.

**`make backup-status` says the same three things on the command line, out of the same
field, and refuses the same file.** It closes with whichever of the three caveats the
record's own `offsite` chooses, prints the missed days newest first, and — where the panel
says *"there is a record and this panel could not read it"* — it now says that too,
instead of printing a damaged record as fact. That was the other half of the same
finding: a record with a `schema` this script has never seen, or a `last_success` that is
not a run, was read out as *"last success: never, last attempt: never"* and exited **0**,
which is byte-for-byte what a machine that has never taken a backup prints. It exits **1**
for both of the two bad answers now, assumes nothing from the file, and names which field
it could not read — never what was in it. The line about the appointed time says that it
came from `.env` as it is **now** rather than from the record, because it does.

**Its first line is asked of the crontab, not assumed.** `scheduled:` has three answers —
*yes*, *NO — nothing on this host takes a backup*, and *NOT KNOWN* on a host with no
`crontab` for it to ask, which is the systemd-timer host above. It used to print
*"scheduled: 04:00 Etc/UTC (configured), checked every 15 minutes"* whether or not anything
was installed, including in the minute after `make backup-unschedule` answered *"removed.
Nothing runs a backup on this host now."* **When** a run would be owed is a separate line,
`appointed:`, because it has a separate source: the env file. The panel cannot make this
distinction and says so instead — it reads one record and may not go looking — which is why
the two channels word this differently and do not contradict each other.

**A record dated ahead of this host's clock is said out loud on both channels**, because
every age in it is then worthless: a backup taken weeks ago reads as one taken this morning.
`scripts/backup-run.sh due` reports `clock=ahead` and exits **1** rather than 0, whatever
the action on the same line turns out to be; `make backup-status` prints the same paragraph
beside the ages it makes worthless and exits 0, because it is a screen rather than a
verdict. Fix the clock; `make backup` takes one whatever the record says.

**`scripts/backup-run.sh due` refuses a damaged record too**, exit **1**, naming the key —
it used to answer `offsite=no missed=none` and *"no backup has ever been recorded on this
host"* out of a file it could not parse, which is what a genuinely fresh host prints. A
record that has merely been **re-indented** — opened in `jq`, or saved by something that
pretty-prints — is not damaged and is read normally; the layout is the only thing tolerated,
and a changed value, a truncated file or a schema from the future are refused as before. A
file **larger than 64 KiB** is refused whole, for its size, without any of it being read —
the same ceiling and the same answer as the panel, because the record is under a kilobyte
and a file that big is a wrong path rather than a long history. (The two channels are held
to that one number by `tests/infra/test_the_command_line_says_what_the_panel_says.py`,
which reads it out of both sources — and out of the sentence above — rather than keeping a
copy of it.) **Move the file aside before you go and look at it**: refusing to read it does
not protect it, and the next scheduled run writes a new record at that path over whatever
is there.

**And the schedule does not stop for a record it cannot read — it takes a backup.** All
four verbs read that file through one reader (`scripts/lib/backup-record.sh`), so `tick`
and `now` get the same refusal `due` and the panel get, and a record this host cannot parse
is treated as no record at all: a dump is taken and a new record written in its place. That
is the fail-safe direction and it is deliberate — the alternative stops the backups on the
strength of a file nothing here can understand — and `due` says which it will be, on an
`action=` line under the refusal. What it costs, stated: a host with a damaged record takes
at most one extra backup per due period until the same run rewrites the file, and a backup
taken by hand over an unreadable record does not carry the old `last_success` or the
missed-day count forward, because those are values nothing was able to check. Only a path
that is **not a file** ends in no backup, and it is refused before anything is dumped — see
below.

**And a record dated ahead of this host's clock does not stop the backups either — the
tick takes one.** That file is not damaged: every reader parses it and they all agree about
it, so it is a different state from the paragraph above and it arrives by a different road.
A host whose clock jumped forward wrote a record for a day that has not come; or
`HASHI_BACKUP_TZ` was moved west far enough to put this host back on the previous day, which
does the same thing to the due date and touches nothing else — a record due `2026-09-24`,
read on `Pacific/Midway` before 04:00 there, answers `clock=ahead due=2026-09-23`. Until
this was decided the tick waited — **exit 0, no output, no backup, at every tick, until the
calendar reached the date in the file** — and it now takes a backup instead, because the
backup is what repairs the state: the run writes a record dated by this host's own clock, so
the date that stopped the schedule is gone by the end of that run. One extra dump, once, and
it happens whether the dump succeeds or fails. Fix the clock all the same, and `make backup`
takes one now whatever the record says.

**What the panel says about it, exactly, because the two halves differ.** The panel goes
loud — a *clock ahead* banner — when a RUN in the record is dated ahead, which is what a
clock that jumped forward leaves behind. It does **not** read the record's `due_date` at
all, so the zone-moved-west shape gives it a quiet, healthy-looking screen — *last backup
less than an hour ago*, no banner — about a record this host cannot reconcile with its own
clock: `make backup-status` and `scripts/backup-run.sh due` are the only two channels that
say anything about that half. The command line's warning says which half is which, so an
operator reading one screen and then the other is not told two different things about one
host.

The decision, and the direction it can be reversed in, is in `docs/decisions.md` under
2026-09-24: this is the owner's rule for a record the tick cannot READ carried to one it
cannot TRUST, and it was taken by the orchestrator rather than by the owner.

**A directory at the record's path is refused by name**, on both channels and on the
writing side too. It is what a `mkdir` of the file's own name leaves, and what the docker
daemon creates if a bind mount ever points at the record instead of the directory holding
it. `make backup-status` and `due` call it a record that is there and is not legible —
which is what the panel calls it — rather than a host that has never run one, and a `tick`
refuses before it dumps anything: moving the new record onto a directory does not fail, it
drops `last-run.json.partial` *inside* it, so the schedule used to report success and leave
no record at all, every fifteen minutes. Move the directory aside; nothing here deletes it.

A run that fails is reported by its exit code, unchanged from `make backup`: **1** nothing
was written, **3** the artifact exists and did not leave this machine. Only **1** is retried
automatically, hourly, up to six times a day — a stack that had not finished booting is the
usual cause and a retry costs nothing. **3 is not retried**, because the artifact is already
on the disk and re-dumping would fill it with copies of the same database; the remedy is
the `make backup-upload FROM=…` above, which the failing run prints — and which
`make backup-status` prints too, beside the number, because a bare **3** on a screen says
nothing about the artifact still being on the machine.

A tick with nothing to do prints nothing, so a working schedule is silent and cron sends no
mail. A tick that fails prints everything, and cron delivers that wherever it delivers mail
— which on most hosts is nowhere anybody looks. **The record is the channel that does not
depend on mail existing.**

**On a host with no `crontab`**, the same script under a systemd timer, as root:

```ini
# /etc/systemd/system/hashi-backup.service
[Service]
Type=oneshot
User=<the account that runs `make up`>
ExecStart=<the checkout>/scripts/backup-run.sh tick

# /etc/systemd/system/hashi-backup.timer
[Timer]
OnCalendar=*:0/15
Persistent=true
[Install]
WantedBy=timers.target
```

```bash
systemctl enable --now hashi-backup.timer
systemctl list-timers hashi-backup.timer
```

`OnCalendar=*:0/15` and not `04:00`, for the reason above — the timer carries no hour
either, and `Persistent=true` is then only a belt on top of a schedule that already cannot
skip a day. Everything else is identical: the same script, the same record, the same
`.env`.

**What none of this proves.** That the artifact of any of those runs is still in the
bucket. This host cannot look — see *The retention this host's own key cannot reach*, below
— and a green `make backup-status` is a statement about what happened here, not about what
is kept there. **The panel's line is the same statement in a second place, and no stronger
for being on a screen**: it is read from this host's own record, and nothing in the control
plane has ever read that bucket. The only check is a restore.

### The retention this host's own key cannot reach

The write-only key is the half of the protection that can be taken from you. Whoever holds
this box holds a credential that may `PutObject` **to any name in the bucket, including a
name that is already there** — so "it cannot delete" is not the same as "it cannot
destroy". The rest is enforced by the account that owns the bucket, with a credential that
never comes near this machine.

**The requirement, before any mechanism:** an artifact that was in the bucket yesterday must
still be retrievable tomorrow, by somebody holding a *different* credential, after anything
the key on this host is able to do to that bucket today. Three things get offered as the way
to get there and they are not interchangeable — one is the defence, one is an upgrade to it,
and the third is the thing you are defending against.

| Mechanism | In force? | What it actually defends against |
|---|---|---|
| **Bucket versioning** | **Required. This is the mechanism.** | The overwrite. A `PutObject` to a key that already exists adds a version instead of replacing one, so the one destructive act this host's credential can perform destroys nothing: the earlier bytes stay and are addressable by their version id. It covers the second case too — should the key turn out to have more authority than was intended, a `DeleteObject` under versioning writes a delete marker over versions that are still there. Without it, a single authenticated `PutObject` is a permanent loss and nothing else on this page helps. |
| **Object lock (WORM retention)** | **On top of versioning where the store offers it. Optional, because many S3-compatible stores do not implement it.** | The deletion that versioning does not stop. Versions survive `DeleteObject`; they do not survive `DeleteObjectVersion`, which removes history one version at a time. A locked version cannot be removed until its retention expires — in governance mode, not by anyone without the privilege to bypass it; in compliance mode, not by anyone at all, including the account owner. That second property is also its cost: a period you set too long is paid for in storage until it runs out, and compliance mode cannot be talked out of it. It is defined on versions, so it needs the row above; it is never a substitute for it. |
| **A lifecycle rule** | **Not a retention mechanism. Set one anyway, with a floor you chose on purpose.** | Nothing. It deletes on a schedule — that is its entire function, and under versioning it is the necessary counterweight that stops every version of every daily artifact accumulating for ever. It is therefore also the only thing here that can quietly undo the two rows above. Give noncurrent versions an expiry longer than the longest stretch in which you would not notice that the recent artifacts are garbage, remembering that noticing means *restoring one*, because this host cannot read back what it wrote. A rule that expires noncurrent versions after a few days turns versioning into a few days of protection. |

**So, in one line:** versioning on, object lock on top of it where the store has it, and one
lifecycle rule whose noncurrent expiry you picked deliberately and wrote down.

**The object's name does a different job, and it is not this one.** `make backup` writes
`hashi-<timestamp>.sql.gz.age` and sends it under that name below
`HASHI_BACKUP_S3_PREFIX`, so two runs never collide and a scheduled run cannot clobber the
one before it. That is protection against *accident* and it is worth having. It is not
protection against anybody: the uploading key chooses the name, so it can name an object
yesterday's name, and a bucket without versioning will accept that `PutObject` and keep the
last one written. **The naming means nobody loses a backup by mistake; versioning is what
means nobody loses one on purpose.**

**If the store offers none of it.** First, ask properly rather than concluding it from a
console page that had no checkbox on it — the three calls below answer it definitively, and
versioning is the one of the three a store is likeliest to have. If the answer is genuinely no, the
protection moves off the bucket and onto **a copy you pull down**: a machine that is not the
control plane, holding the read credential from *What you carry*, fetches new objects out of
the bucket on whatever cadence you can actually keep, onto media you hold. The artifact is
already `age` ciphertext, so a copy on your own disk is no more exposed than the copy in the
bucket; what it buys is that it is out of reach of this host's key entirely, which is the
property versioning would have given you. **The cadence of the pull is the size of the
window you can lose.**

What is *not* a fallback: a second destination configured in `.env` here. Two buckets
written by two keys on the same box are two things one seizure takes. Nor is giving this
host a key that can delete so it can tidy up after itself — tidying is the lifecycle rule's
job, and it is row three above. Moving the whole thing to a store that does offer versioning
costs four lines of `.env` and no code, which is what keeping the store a *field* bought;
whether to move is the owner's call and the constraints on it are recorded in
`docs/decisions.md`, not re-argued here.

**Checking it is really in force — from anywhere that is not this host.** You cannot check
with the credential in `.env`, by construction: it can write and it can do nothing else.
With an administrative credential for the bucket, on your own machine, ask the store
directly:

- `GetBucketVersioning` — the answer must be `Enabled`. `Suspended`, and an empty answer,
  both mean new writes are unversioned; the difference between the two is only whether
  versions were ever kept at all.
- `GetObjectLockConfiguration` — the mode and the period, or an error saying the store does
  not implement it. An error is not a failed check here; it is the answer to whether row two
  is available to you.
- `GetBucketLifecycleConfiguration` — read the noncurrent-version expiry and compare it to
  the number you chose. This is the one that drifts, because it is the one somebody edits
  later to save money.

Those are the protocol's own names for the three settings, not one store's menu: what a
console calls them differs from store to store, and a store that does not implement one
answers the call with an error rather than under a different name. That is why they are
written here as calls and not as a path through somebody's console.

A setting can read `Enabled` and still not be doing what you assume, so confirm it
empirically as well: with that same administrative credential, `PutObject` a throwaway
object twice under one key, then `ListObjectVersions` under its prefix. **Two versions is
versioning working. One is the state this entire section exists to prevent.** Objects that
were already in the bucket are protected from the moment versioning is switched on, but
nothing brings back a write that happened while it was off — so the check belongs at bucket
creation, after any credential rotation, after a move to another store, and after anybody
touches a lifecycle rule. Not once a year.

**What this repository cannot tell you, and never will.** No test in this tree asserts any
of the above. It cannot: the only credential this project holds is write-only by design,
there is no read, list or delete path anywhere in the product, and the bucket lives in an
account this code has no standing in. `make verify` proves the artifact is written, that it
is encrypted before it reaches the disk, and that a store accepted exactly those bytes — it
says nothing whatever about what that store does with them a minute later. The calls above
are the only proof there is, you are the only one who can run them, and the day you will
wish they had been true is a day you can no longer run them.

### What belongs in a backup, and what does not

Decided 2026-09-23, item by item, because "everything the control plane generates" is not
self-evident at 3am and half of it is key material.

| Item | Backed up? | Why |
|---|---|---|
| **The control database** (the `hashi-db` volume, via `make backup`) | **Yes** — it *is* the backup | The single source of truth. Every node, every transport row, every user and every credential. Nothing else in this table can be reconstructed *from* the others; this can reconstruct a whole fleet. |
| **`caddy_data`** (Caddy's ACME account key, its issued certificates, and the internal CA root the panel is served with) | **No** | Every byte of it regenerates on first boot with no operator action, and after a seizure the old host's private keys are to be presumed compromised — restoring them carries the seized machine's identity onto the new one. The cost of regenerating is real but bounded, and it is spelled out below rather than assumed. |
| **`~/.hashi/management/`** (this host's management-tunnel private key, its per-host obfuscation values, and every enrolled device's public key and pre-shared key) | **Yes** — but only inside the age-encrypted artifact, never in the plain dump above | It is regenerable but **not reproducibly**: `scripts/management-tunnel.sh` prints each device's config exactly once and keeps no copy, so a fresh run invalidates every device already enrolled. Losing it means re-enrolling your laptop *and* your phone by copying a freshly printed private key out of an SSH session, at the moment the panel is unreachable and you are rebuilding under pressure — which is the one moment the tunnel exists for. It is 32 bytes and it is the difference between typing one new `Endpoint` line per device and re-doing the whole enrolment. |
| **`.env`** | **NO. Not in the artifact, not in the bucket, not even encrypted.** | It holds `HASHI_SECRET_KEY`, which is the *only* thing standing between a reader of the bucket and every node credential and user token in the dump. Putting it beside the data defeats the encryption entirely: one stolen age identity would then yield both halves. Excluding it is what makes a restore cost **two** secrets that never meet on this host — the age identity and `HASHI_SECRET_KEY`, both carried by you. It also holds `HASHI_OPERATOR_PASSWORD_HASH`, so it is what lets you log in at all; see *What you carry*, below. Rebuild it on the new machine from `.env.example` plus what you carry. |
| **`/opt/hashi` on a node** | **No**, explicitly | A node holds nothing that cannot be regenerated from the database — that is the invariant that makes replacing a node safe. Its rendered configs come back from an apply. Backing a node up would be backing up a derived artifact and calling it a source. |

### What a restore of the database actually gives you back

Every node record, every transport row, every user and every subscription token — so
**every user's existing subscription URL keeps working**, with no message to anyone,
*provided the delivery name still resolves to the new host*. If the domain itself is
gone, that is the one thing no backup returns: the tokens survive and the URL they live
in does not, and every user has to be handed a new link.

It does not give you back:

- **Anything readable without `HASHI_SECRET_KEY`.** Under the wrong key the panel loads
  and every screen that touches a node or a user answers *"The data is intact; the key is
  wrong. Nothing has been changed."*
- **A way to log in.** `HASHI_OPERATOR_PASSWORD_HASH` lives in `.env`, not in the
  database. `make hash-password` makes a new one on the host itself.
- **A backup.** `HASHI_BACKUP_AGE_RECIPIENT` and the write-only S3 credential were in
  `.env` too, and the schedule was a crontab on the machine that is gone — so the host
  that came out of the backup history cannot add to it until you put both back and run
  `make backup-schedule`. Nothing fails loudly on its own: `make backup` refuses, and the
  panel truthfully reports that nothing has been recorded here.
- **A working fleet.** Restoring records does not touch a node. The new control plane
  believes in nodes that may be seized, blocked or gone; you re-apply to the ones you
  still hold and delete the ones you do not.
- **The management tunnel**, unless you carried `~/.hashi/management/` (above).

### The `caddy_data` cost, stated rather than waved at

On a new host Caddy registers a fresh ACME account and requests a fresh certificate for
`HASHI_PUBLIC_HOST` the first time it boots. That needs the name to already resolve to
the new machine and inbound `:80`/`:443` to reach it; until both are true, `/sub/*`
serves nothing. Users with a working config are unaffected — a user who needs to
*refresh* one is not.

Issuance is rate-limited at the CA, and the binding limit for a rebuild is the
**duplicate-certificate** one: for an identical set of names it is five per week, on top
of a per-registered-domain limit an order of magnitude higher. One rebuild spends one.
You would have to rebuild the same name six times in seven days to be refused, and the
refusal degrades the delivery endpoint only.

The panel is not affected either way: it is served with `tls internal`, Caddy's own CA,
created at first boot and never published to a CA's logs. What you do lose is that the
root is **new**, so each device is asked to trust the console once more. On a deliberate
rebuild that prompt is expected. A prompt you did *not* expect is the one to refuse.

Both paragraphs above are read from the issuer's published limits and from this
repository's own Caddyfile. Neither is measured — see *Known-unproven*.

### What you carry

Three things live on you and never on the control host. The first two are needed by every
restore of an artifact written since 2026-09-23 — the file does not even open without the
second. The third is needed from the moment anything is in the bucket, which since
2026-09-23 it is.

1. `HASHI_SECRET_KEY` — without it the dump is unreadable data.
2. The **private half** of the age keypair whose public half is `HASHI_BACKUP_AGE_RECIPIENT`.
   Without it the artifact does not open at all, on any machine, including this one.
3. A **read** credential for the backup bucket — `ListBucket` and `GetObject` — and, to
   check the retention above, an administrative one. The key in `.env` can only write, on
   purpose, so the box that is seized cannot delete its own history; the direct consequence
   is that fetching an artifact back out of the bucket, and asking that bucket whether
   versioning is on, are both things only you can do. `make restore-from-bucket` does the
   fetching *with the credential you hand it*, in its own environment, for the length of
   one command — neither it nor the age identity is ever written into `.env` on this host,
   and the command refuses rather than reading them from there.

Plus the values needed to rewrite `.env` itself — hosts, ports, the Postgres password,
and a password for the panel. The operator password **hash** is not on that list any more:
`make hash-password` makes it on the host, so what you carry is the password itself, in
your head. Everything else in that file comes from `.env.example`.
