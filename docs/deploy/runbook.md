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
| `HASHI_PRIVATE_HOST` | the name your own devices ask for over the management tunnel — usually this host's tunnel address |
| `HASHI_PRIVATE_PORT` | where Caddy serves the console; the same variable drives the listener and the published mapping, so they cannot drift |
| `HASHI_PRIVATE_BIND_ADDR` | which address on **this** host the console is published on. The tunnel's, never loopback — see *Reaching the panel* |
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
prints no address now. Publishing is still a separate, deliberate step:

```bash
make up-panel
```

That is the base stack plus `deploy/docker-compose.public.yml`, which **ships with the
repository** — it used to be a heredoc you typed onto the box, and that stopped being
survivable when the file grew a mapping whose bind address is the difference between a
private console and a public one. Caddy only. Never the database.

**And remember it after every `make panel-bootstrap`.** That script uses the base file
alone, on purpose — so a later run brings the stack back to the base file's shape and
takes the published ports away again. Run `make up-panel` afterwards, or run it instead
of the script once the box is installed.

---

## Reaching the panel

**The console is not on your public hostname.** As of M7 Caddy serves two sites out of
one container:

| site | serves | reachable from |
|---|---|---|
| public — `HASHI_PUBLIC_HOST` on 80/443 | `/sub/*`, and a redirect to https | anywhere, which is the point: a friend refreshes their config from inside Russia at the moment a node was blocked |
| private — `HASHI_PRIVATE_HOST` on `HASHI_PRIVATE_PORT` | `/panel/*`, `/api/*`, `/static/*` | the management tunnel, and loopback |

Everything a site does not serve is `404`, with no body and nothing that says the other
site exists. The console holds every node key and every friend credential, and there is
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
  client refuses the certificate — `/sub/{token}` then fails for every friend while
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

Fill in the `HASHI_MGMT_*` keys and run the bootstrap. It prints one config per device,
**once**:

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
neither the cause nor the cure.

### The way back in when the tunnel is unavailable

**This route is tested, not merely described**, and the difference matters: the day you
need it is the day of an emergency rotation, and a fallback nobody has run is a paragraph.
It is also the route this project's own field run used all night.

`make up-panel` publishes the console's port a second time, on this host's loopback only.
Nothing off the host can reach it; anything that can already open an SSH session can
forward it:

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
argument it does not recognise exits **2** and prints the usage. It refuses rather than
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
==> ready: docker <version>, key authorised, firewall up, logging off
==> register it in the panel with ssh_user <user> and ssh_port <port>
==> no hashi code and no hashi state was installed here — /opt/hashi is an empty directory owned by <user>, and the control plane fills it on your first apply
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
   entry node's friends instead* for what was measured. Read *The one combination that
   will not render* before you make it the entry end of one. The form asks one more
   thing for this family — **how many users this row may hand an address to**, counted
   up from `peer_tunnel_address`. Size it for the fleet you expect rather than for
   today's: the number is a ceiling, raising it later is a resize, and the box says how
   many people it is being measured against.
3. **Apply.**
4. **Add a friend**, open their subscription link, load it into a stock client. The
   WireGuard family is a config *file* rather than a URI, so it is the
   `?format=client-config-file` form of that link that carries it — the plain link is
   empty on a box that offers only `amneziawg`, and empty is not an error.

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
   from E). Give **E** a `resolver` as you register it: E dials a hop, and such a node does
   not render without one (*A node that dials a hop needs a resolver*, below).
3. Enable a **friend-facing** transport on E — `vless-reality` unless you have a reason
   for the other one. E dials a hop, so it must be a transport the table in *The one
   combination that will not render* (below) marks yes for a node with a hop; a kernel
   tunnel here is accepted by the panel and refused at apply.
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
   control container needs outbound SSH to each. Give **E** a `resolver` as you register
   it (*A node that dials a hop needs a resolver*).
3. Enable **`vless-reality` on E, port 443** — free here, because the panel is on another
   box. Give it a `decoy_host` of your own choosing. A VLESS transport is not merely
   convenient here: E dials a hop, and that is the only kind of friend-facing transport
   such a node can render at all (*The one combination that will not render*).
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

## The one combination that will not render

**On a node that dials a hop, friends may not be on a kernel tunnel.** Following this
runbook used to produce exactly that: `amneziawg` for box E's friends, because Shape A
names it, and `amneziawg` for the hop E dials, because the hop requires it.

The panel now takes both rows. Two instances of one transport on one node are ordinary —
they collide on a **listening port**, on a **config name** and, for the WireGuard family,
on their **tunnel ranges**, which may not overlap (*Rules that are not optional*, below).
Give the hop a range of its own and two `amneziawg` rows on two ports share none of the
three. What refuses is the **apply**, on the entry, with this in a banner on the Nodes
screen:

> `amneziawg could not be rendered for this node — EgressNotRenderable:` … *A tunnel whose
> packets this node's kernel routes cannot send them out through a different interface, so
> they would leave by the node's own route instead — which is the silent failure the hop
> exists to prevent. Give this node's friends a transport that terminates their connection
> and re-originates it, or take the hop away.*

**That banner is the only signal you get, and the node does not go `degraded`.** The
refusal happens while the configuration is being rendered, before anything is written to
the host, so there is no half-configured node to mark and the node's state is left exactly
as it was. An entry that was already `active` therefore **stays active and stays in every
user's link**, serving whatever its last successful apply left on the host — an operator
scanning the Nodes screen for something red finds nothing. Read the banner, and treat a
node whose apply you cannot complete as one that is serving a configuration you did not
choose.

**That is a refusal, not a defect.** A wg-quick-family tunnel hands a friend's decrypted
packets to the entry's own routing table, and the only route this project renders for a
hop is source-based, from the hop interface's own address. A friend's packets never match
it, so they would leave by the entry's own route — an exit in the country the hop exists
to leave, with every screen green. Refusing beats that (`docs/decisions.md`, decision 3).
The **leaf** end of the same hop renders fine; it is the friend-facing side on the entry
that cannot.

**What to give an entry node's friends instead.** A transport whose data plane
*terminates* the connection and originates a new one, which is what the refusal asks for.
In this image that is the VLESS pair, `vless-reality` and `vless-ws-tls`. Both are Xray,
which forwards no packet in the kernel: it accepts the friend's connection and opens its
own, and on a node with a hop that new connection is bound to the hop's near address. So
it can only reach the internet through the hop, and while the hop is down it cannot be
opened at all — fail closed, as a property of the rendered file rather than a rule someone
has to remember.

Between the two, `vless-reality` needs nothing placed on the host: it borrows a decoy's
handshake, so give it a `decoy_host` of your own choosing and never a shared one.
`vless-ws-tls` needs a real certificate and key **already on the node**, named by path —
nothing in this project puts them there — so it is the right answer only on a host where
you already terminate TLS for a name you own.

`amneziawg` stays exactly right for friends on a node with **no** hop: Shape A's single
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

| transport | friends on a node with a hop | friends on a node with no hop | the entry→leaf hop |
|---|---|---|---|
| `vless-reality` | yes — Xray terminates the connection and originates its own | yes | no — a hop is two ends of one tunnel network that each need an address of their own, and this transport hands its consumers none: it identifies them by their material |
| `vless-ws-tls` | yes, once a certificate and key are on the node | yes, on the same condition | no, for the same reason |
| `amneziawg` | no — the panel accepts the row and the apply refuses it | yes | yes, and today it is the only one |
| `wireguard` | no — the same refusal, for the same reason | no — retired: the panel does not offer it, and a row enabled before that carries no traffic on a host this runbook prepared | no — it is protocol-blocked where this matters, and the form will not offer it |

Every cell in it is checked against the code by `tests/infra/test_deploy_runbook.py` —
against the renderers for the first column, the panel's own enable dialog for the second,
and its hop form for the third. A fifth transport, a retirement, or a change to what one
of these can do turns that suite red rather than leaving this table quietly wrong.

**The two families are delivered differently, and you find that out before your friends
do.** A VLESS transport rides the subscription link the panel shows. The WireGuard family
is a config file: the same token, `?format=client-config-file`, an archive. A friend whose
node offers only AmneziaWG and whose client opens the plain link gets an empty document
rather than an error — so hand them the `?format=` URL, and expect the plain link to carry
entries again once that node's friends are on a VLESS transport.

### If you already built it the other way

The way out is in the panel, and it is **removal** rather than withdrawal. Withdrawing the
friend-facing `amneziawg` does stop the apply failing — a withdrawn row is not rendered at
all — but it leaves the row on the node still holding its listening port, its config name
and its tunnel range, its users' material still minted for a transport that node can no
longer render, and a trap for whoever offers it again: the same apply fails the same way.
Removing it takes the row, the material, the port, the name and the range.

1. **Nodes → transports** on the entry box. Both `amneziawg` rows are listed, and the
   second one created carries a config name of its own — it reads `amneziawg
   (amneziawg-2)` — so the two cannot be confused. The hop end is the row whose standing
   begins *one end of a hop*, and it is drawn with no buttons at all.
2. **remove** the friend-facing one, and read the dialog before you confirm: removal
   destroys the material every user holds on that row and frees its port, its config name
   and its tunnel range, and it is the only action that does any of the three. `withdraw`
   beside it is the reversible one, and it is not what gets you out of this.
3. **Enable a VLESS transport** for friends on that node, on a port nothing else there
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
next one you orphan, once that node's friends are on a VLESS transport, is a `.json`
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

**On a node that dials a hop, a friend's destination names are looked up through the hop,
at a resolver named on the node's record — never by the host's own.** Before this, the exit
had moved abroad and the lookups had not: the proxy asked the entry host's resolver, inside
the network the hop exists to leave, one query per site a friend visited
(`docs/decisions.md`, 2026-09-09). Whichever resolver you name still sees the names — from
the far end of the hop rather than from the entry's network, which is the exposure that
decision accepts knowingly.

A node that dials a hop and has no resolver is refused at **apply**, on the entry, with this
in a banner on the Nodes screen:

> `vless-reality could not be rendered for this node — ResolverMissing:` *this node's
> traffic leaves through a hop, and its record names no resolver for the destinations its
> friends ask for. Without one they would be looked up by this host's own resolver — on
> the near side of the hop, inside the network the hop exists to leave — while the traffic
> itself exits at the far end. Nothing is rendered until the node has one: an IPv4 address
> the far end of the hop can reach.*

Like the refusal above, it happens while the configuration is being rendered, so the node
does not go `degraded`: an entry that was already `active` **stays active on whatever its
last successful apply left** — its friends' lookups still going to the host's resolver — and
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

## Rules that are not optional

- **Never plain WireGuard on the entry→leaf hop.** That hop crosses the border by
  definition, and a protocol-blocked transport there defeats the topology even in phase
  1. Use AmneziaWG or another obfuscated transport. This one is enforced rather than
  advised: the hop form offers only the transports that can carry a hop at all, which
  in this image is `amneziawg` and nothing else.
- **Never present plain WireGuard to a friend as something that works from a Russian
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
  the same box — friends and hop are two `amneziawg` rows on that node, and they need
  two ranges as much as they need two ports. Nothing else collides. A **disabled** row
  still holds all three, because freeing them would move the collision to the moment
  somebody switches it back on; removing the row is the only thing that gives them
  back.
- **A friend-facing kernel tunnel and a hop still cannot share a node**, which is a
  different rule and the one that bites — *The one combination that will not render*,
  above.
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
  *Until M17 these rows minted one shared address, so the second friend on a node
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

## Backups

```bash
make backup                                   # → backups/hashi-<timestamp>.sql.gz, mode 0600
make restore FROM=backups/hashi-<...>.sql.gz  # destructive, so the path is required
```

The dump is encrypted with `HASHI_SECRET_KEY` and cannot be restored without it. Keep the
key somewhere the dumps are not. Restore is destructive and never picks "the latest one"
for you — that is not a decision a Makefile gets to make.
