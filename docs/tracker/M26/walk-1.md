# M26 — acceptance walk 1: **findings**, gate BLOCKED (2026-09-16)

An independent walker took bare hosts (privileged containers with volume-backed
`/var/lib/docker`), ran both bootstrap scripts, drove the real panel in a real browser
and carried a friend's real traffic. Its evidence is in `.acceptance/M26/` — gitignored,
so what it measured is written down here instead.

This is the record the owner asked for: *"text it into a separate block on the
milestone"*. Each finding says what was done, what was seen, what was expected, and what
was done about it. **Nothing here was marked fixed by the walker** — the second walk
decides that.

---

## The counts it measured

These are the measurement the charter was narrowed to (`docs/product/charter.md`, *What
the scripts actually deliver*). Every row was walked, not estimated.

| From | Commands | Panel actions |
|---|---|---|
| bare host → node **serving** | 1 (48 s) | 3 — add node, enable transport, apply |
| bare host → **a friend's packets moving** | 1 | 5 — the 3 above + add user + **apply again** |
| two bare hosts → established **entry→leaf hop** | 2 (3 in the run, see L3) | 6 — register ×2, friend-facing transport on the entry, establish hop, apply ×2 |
| bare host → **control plane** | 13 from the runbook's block (15 on a truly bare host) | 0 |
| Shape C, three bare hosts → one friend carried | ~17 | ~8 |

---

## B1 — the charter overstated both scripts

**Done.** Read `docs/product/charter.md` against the two scripts' actual output.

**Seen.** Line ~151: node bootstrap delivers *"from a bare host to serving traffic"*.
Line ~162: *"It ends by checking the daemon accepts its own config and the node answers a
health probe."* The node script's last lines are `==> ready: docker 29.8.1, key
authorised, firewall up, logging off` and `==> register it in the panel with ssh_user
root and ssh_port 22`. At that moment `/opt/hashi` is empty — no daemon, no config,
nothing to probe, and the script says so.

**Expected.** A page that says what ships. Serving traffic is three panel actions past
the end of that run; a friend's traffic is five.

**Fixed.** The charter's script table now says the node script delivers *a host the
control plane can drive* and quotes the line it ends on. The verification bullet is
narrowed rather than deleted: the health-probe promise is **true of
`scripts/panel-bootstrap.sh`**, which waits for `/healthz` and a `/sub/{token}` route
from inside the compose network and refuses if neither comes — the walker proved that by
breaking the stack with a wrong `POSTGRES_PASSWORD` (exit 1, `panel-bootstrap: the
control plane did not answer within 180s.`). A new section, *What the scripts actually
deliver*, carries the counts above. `tests/infra/test_the_charter_states_what_the_scripts
_deliver.py` holds the page to both scripts, including the closing seam the runbook
already pins.

## B2 — adding a user did not reach the nodes, and nothing said so

**Done.** Added friend `acc-friend`, fetched `…/sub/<token>?format=client-config-file`.

**Seen.** A complete, correct, importable configuration — `Address = 10.77.13.2/24`, the
node's real public key — while on the host `grep -c "\[Peer\]"
/opt/hashi/conf/amneziawg.conf` was **0** and `awg show` listed no peers. The friend's
client would have handshaked into nothing. Only after a second apply (audit:
`friend-added 10:31:46` → `node-applied 10:34:39`) did the peer appear (`allowed ips:
10.77.13.2/32`) and traffic flow. The runbook's Shape A step 4 and Shape C step 5 both
read *"Apply … Add friends"*; the Users screen's one standing note is about **withdrawn**
access.

**Expected.** The panel must not present a link as working for a node that has not been
told the user exists.

**Fixed.** Two surfaces, one sentence, composed once in `services/console.py`: the Users
screen and the dialog that hands the link over both say *"A user added here is not on
`<nodes>` yet: … Apply it on the Nodes screen."*, naming every serving node whose host is
not holding what this panel would push. The Nodes screen's `config` cell was already
right (a granted credential changes the render, so the node reads `1 / 1 drifted`) — it
is now pinned by a test, because nothing carried that reading to the person who had just
pressed the button. The runbook's Shape A and Shape C apply **after** adding users, and a
test holds every shape to that order.

## B3 — a dead node read `active / in sync` and was counted as serving

**Done.** Stopped `hashi-node-amneziawg-1` on the leaf, pressed **probe**.

**Seen.** The probe was right: *"failed  leaf-acc answered but is not serving — not
running: amneziawg."* One reload later the row read `active / in sync`, `nodes
.state_detail` was empty, and the Overview — subtitle *"what is serving … and whether the
nodes are running what you told them to"* — read **"nodes active 2 … transports serving
2"** while the friend's `ping 1.1.1.1` was 100% loss. The node stayed in every user's
link.

**Expected.** A measurement that is taken and is correct must not be discarded. M22
already made the probe trustworthy; what was broken was what the product did with what it
found.

**Fixed.** The finding is now a column on the node (`last_probe_at`,
`last_probe_finding`; migration 0007), written by `services/health.check_node` in the
words the operator read, so both the panel button and `GET /api/nodes/{id}/health` record
it. It is shown under that node's row for as long as it stands, and named on the Overview
beside the counters it contradicts. A later probe that finds nothing clears it; so does a
successful apply, which verifies the daemon came back on the configuration it just pushed
— strictly more than a probe establishes. The Overview additionally prints the standing
limit of all four counters: they count configuration, nothing on that screen dials a
host, and probe is what measures one.

**Deliberately NOT done: the probe does not mark the node degraded.** That would take it
out of every user's link on the strength of one reading, including a reading that only
means this control plane could not open an SSH session — which is not the same as "not
serving". The three options the brief allowed were persisting the finding, dropping the
node from the serving set, and narrowing the Overview; this took the first and the third.

## M1 — the control plane is not one script

**Done.** Followed the runbook's Shape A control-plane block on a bare host.

**Seen.** 13 commands (clone, `cp .env.example .env`, edit, `ufw logging off`, four `ufw
allow`, `ufw enable`, `make panel-bootstrap`, `make up-panel`, a curl check), plus a
docker install line, `make` and `git` that *"What every box must already have"* did not
list.

**Fixed.** The runbook says *"This is 13 commands on 11 lines, and `panel-bootstrap.sh`
is one of them"* — and a test counts the block and refuses a number that disagrees with
it. The prerequisites section now answers separately for a node and for the control-plane
box, naming `git` and `make`. The charter's own row says the control plane is not brought
up by one script.

## M2 — a refusal in the firewall step printed no `node-bootstrap:` sentence

**Done.** Sabotaged `iptables-restore` so `ufw --force enable` fails.

**Seen.** The run ended on ufw's raw `ERROR: problem running ufw-init`, exit 1, with no
hashi sentence at all (`.acceptance/M26/node-bootstrap-ufw-enable-fails-no-sentence.log`).
Nothing false was claimed; the operator was left with no statement of what state the host
was in, against a page promising every refusal starts `node-bootstrap: `.

**Fixed.** The enable call is captured, and its failure raises the script's own refusal
with ufw's words inside it and the state of the host named — *the host is otherwise
prepared and it is EXPOSED*. Run for real in `tests/infra` against a stubbed ufw, both
directions.

## L1 — the logging line was printed before anything read it back

**Fixed.** `==> ufw logging is off …` is printed only after the level is read back, and a
host whose ufw ignored `logging off` is refused **before** the firewall comes up rather
than after — so on that host nothing has begun writing a connection log at all. This is
the one line in the run about the record the charter forbids at any level.

## L2 — exit codes do not survive the documented invocation

**Fixed in the page, not in the Makefile.** Direct, a refusal exits 1 and a bad argument
exits 2. GNU make exits **2** whenever a recipe fails, whatever the recipe returned, so
`make node-bootstrap` cannot pass either through — that is make's behaviour and not
something a target can change. The runbook now says so and points at the `ssh …` line for
anyone who needs the codes.

## L3 — the hop's UDP port must be known before the leaf is prepared

**Fixed in the page.** Shape C step 2 now says to choose the hop's port before running
either script and to pass it as `--port` on the leaf, and names what the walker hit: the
form asks for that number at step 4, by which time the firewall is already set, and the
repair is a second run of the script.

## L4 — no defaults in the parameter forms

**Judged, and no defaults were added.** 13 empty boxes for one amneziawg row, 22 for a
hop. A default is refused for everything these forms ask for, and the reason is one rule
in `CLAUDE.md` applied consistently: a value every node borrows is a value the fleet can
be enumerated by. That covers key material (minted per node, never typed), decoy hosts
(the charter names the shared-decoy hazard outright), addresses and ports (a default is a
value nobody can rotate away from), and the AmneziaWG magic headers — which ARE this
fleet's fingerprint, which is why the boxes carry a warning against copying the protocol's
published examples.

**What was fixed instead is the hazard the walker actually named**: four numbers per end
that must match exactly at both ends or the tunnel comes up and carries nothing. A
transport now declares which of its parameters both ends of a hop must share
(`TransportMeta.hop_matched_params`), and `edge.relay` refuses a mismatched pair before
either end is written, naming every box that differs. The junk-packet knobs are
deliberately not in that list: junk is prepended by the sender and skipped by the
receiver, so two ends may legitimately differ, and refusing that would refuse a working
hop.

## L5 — the generated client config needs `resolvconf`

**Fixed in the page.** `awg-quick` implements the `DNS =` line by shelling out to
`resolvconf`, so a plain Linux client without it fails to bring the tunnel up at all, on
an error about a missing command. Stock GUI clients are unaffected; the operator testing
from a shell is exactly who is told to *"load it into a stock client"*.

## The suspicion — one apply that never reached the server

**Not reproduced, and recorded as unreproduced.** One `apply` click was accepted by the
browser with no `node-applied` audit row and no movement in the config file's mtime; it
worked from a freshly loaded page. The console's mutation buttons are plain `hx-post`s on
a table that re-fetches itself, and nothing in this round changed that path. It could
equally be the driver racing htmx after a navigation. **No fix was made and none is
claimed** — if it recurs, the thing to capture is the browser's network log for the click
that vanished, because from the server side there is nothing to find.

---

## What held up under attack — do not regress any of it

- **Both scripts are genuinely idempotent**, proved by host-state fingerprint diff: docker
  version, `authorized_keys` sha + mode, `/opt/hashi` mode/owner/contents, ufw rules-file
  shas, package set, sysctls and running units identical across runs; for the panel script
  compose ps, images, volumes, `.env` sha and alembic version identical, run 2 took 3 s, no
  keys re-minted, `awg-mgmt.conf` sha256 unchanged.
- **Both ran to completion with `< /dev/null`** — no interactive question anywhere.
- **Every verification the walker attacked failed correctly**: docker daemon down;
  `AuthorizedKeysFile` pointing elsewhere; a key appended to a `/dev/null` symlink;
  `ip_forward=0`; ufw logging on; strict `rp_filter` (warns and names the entry-node
  consequence); a broken stack; a lone `$` in the env file (refused, naming line 92).
- **The probe itself is trustworthy** (M22's precedent): it correctly called a stopped
  container not serving. This milestone changed what the product does with that, not the
  measurement.
- **The panel's refusals under stress**: an empty form stopped by the browser; a
  1000-character node name refused field-level with the dialog intact; a double apply
  producing two audit rows, no restart and no dropped packet; an abandoned dialog saving
  nothing; browser-back re-rendering live data with no ghost dialog.

## What the walk could not check

No live host was touched (`45.151.69.107`, `158.160.67.252` carry the owner's real
traffic), so there are no byte counters from the field. A friend's packets were proved end
to end only on the leaf's amneziawg — no Xray client was available, so the entry's
`vless-reality` was proved only as far as "the container is up and holding its port", and
**a friend's traffic was never carried ACROSS the hop**. The bare hosts were privileged
containers: a real VPS differs in its kernel, its provider firewall and its `rp_filter`
default. The panel walk ran on a host whose DNS name does not resolve, so Caddy obtained
no certificate and the public delivery endpoint was never exercised. And nothing here says
anything about a real Russian network — the charter's first success criterion is a field
observation with a phone, and no test run is evidence for it.
