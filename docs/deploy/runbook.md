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
```

Restore is destructive and never picks "the latest one" for you — that is not a decision a
Makefile gets to make.

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

### Where the artifact goes, and the credential that sends it

With `HASHI_BACKUP_ENABLED=1`, `make backup` sends the artifact it has just written to the
object store configured in the `HASHI_BACKUP_S3_*` block of `.env`: one `PutObject` to
`<endpoint>/<bucket>/<prefix><file>`, and nothing else. The store is addressed by the **S3
protocol, never by a provider's name** — the same rule as a node's country and address
living in a node record rather than in code, and for the same reason: a provider you cannot
rotate away from is one you are stuck with on the day you need to leave it. Moving to
another store is four lines of `.env` and no code.

**The credential kept on this host may only write.** `PutObject` and nothing else: no
`GetObject`, no `ListBucket`, no `DeleteObject`. Whoever holds this box holds that key, and
a key that can delete turns a seizure into the loss of the entire backup history as well as
the machine. Retention is therefore enforced on the **bucket** side — versioning, object
lock, or a lifecycle rule — where this key cannot reach it. Set that up when you create the
bucket: nothing on this host can do it for you, and nothing on this host can undo it.

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

`HASHI_BACKUP_ENABLED=0`, or unset, is a supported mode rather than an oversight — the
artifact is written and stays on this host, and every run says so in as many words. What
still does not exist is the **schedule**: nothing runs `make backup` for you yet. Nor does
the management directory have a place inside the artifact (see the table below — the
artifact is the database and nothing else so far).

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
  database.
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
second. The third becomes needed the day the offsite upload exists.

1. `HASHI_SECRET_KEY` — without it the dump is unreadable data.
2. The **private half** of the age keypair whose public half is `HASHI_BACKUP_AGE_RECIPIENT`.
   Without it the artifact does not open at all, on any machine, including this one.
3. A **read** credential for the backup bucket. The key in `.env` is write-only on
   purpose, so the box that is seized cannot delete its own history.

Plus the values needed to rewrite `.env` itself — hosts, ports, the operator password
hash, the Postgres password. Everything else in that file comes from `.env.example`.
