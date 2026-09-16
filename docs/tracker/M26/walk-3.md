# M26 — acceptance walk 3: **findings**, gate BLOCKED (2026-09-16)

A third independent walker took bare hosts (privileged containers with volume-backed
`/var/lib/docker`), ran both bootstrap scripts, drove the real panel in a real browser —
and this time **reached the hop and carried a friend across it**. Its evidence is in
`.acceptance/M26/` under the `r3-` prefix — gitignored, so what it measured is written
down here instead.

**BLOCKER 1 WAS LEFT OPEN BY ROUND 2'S OWN RECORDED DECISION.** That is the most useful
line in this file and it is written first on purpose. Round 2 decided, deliberately, and
wrote it into `docs/decisions.md`: *"Apply does not re-ask the socket question… it widens
apply's failure surface with a reading that has its own 'nobody could ask' third state."*
The residual was recorded as acceptable — *"a port fault found before an apply is cleared
by a check that did not re-ask it"* — and this walk falsified it in one press. **A
residual that is written down is still a residual**; what made this one worse than a
silence is that the panel's own copy then offered the unasked check as the REASON the
finding could go.

Round 1's three blockers and round 2's blocker, high and three lows all came back
**verified closed** and are listed at the end. This walk found **two blockers, one high,
one medium and one low**, in 202 actions.

---

## The counts it measured — and the charter's third row, walked at last

| From | Commands | Panel actions |
|---|---|---|
| bare host → node **serving** | 1 | 3 — add node, enable transport, apply |
| bare host → **a friend's packets moving** | 1 | 5 — the 3 above + add user + **apply again** |
| two bare hosts → established **entry→leaf hop** | **2** | **6** — register ×2, friend-facing transport on the entry, establish hop, apply ×2 |
| bare host → **control plane** | 13 from the runbook's block | 0 |

**The third row is exactly what `docs/product/charter.md` claims for it**, walked rather
than read, and it is the first time in three walks that it has been reached. Values typed
by hand to get there: **13** node-record fields, **5** for `vless-reality`, **14** in the
hop form's advanced tuning (7 per end) — with 4 per end arriving already drawn by round
2's fix.

## THE HOP WAS REACHED, AND A FRIEND WAS CARRIED ACROSS IT

The milestone's fourth "done when" — unreached by both earlier walks — was reached here.
Evidence, all of it read off the hosts and the panel rather than inferred
(`.acceptance/M26/r3-hop-and-friend-traffic.log`):

- **The panel**: Hops → `r3entry | r3leaf | amneziawg | established | 16 Sep 2026`.
- **Both ends handshaking**, read on each host with `awg show`: `latest handshake: 36
  seconds ago` at both, entry `10.77.0.1/24` ↔ leaf `10.77.0.2/24`, and the four magic
  headers identical at the two ends — the property round 2's draw exists to produce.
- **Traffic across the tunnel itself**: `ping -c 4 10.77.0.2` → 4/4, 0% loss, and the
  entry's counters moved +512 B each way.
- **A friend carried through it end to end.** Their subscription decoded to exactly one
  node — the entry, `vless-reality` — and the leaf never appeared in it, as the runbook
  says it must not. A stock `xray-core:1.8.24` client configured from that URL alone, on a
  container on neither host, was offered a SOCKS port: `curl --socks5-hostname … http://example.com/`
  → **`http=200`, 559 bytes**. The leaf's hop counters moved +1012 / +1564, and the leaf's
  **`MASQUERADE 10.77.0.0/24 ! -o amneziawg` rule went from 0 packets to 2 packets, 117
  bytes** — so the page came back friend → entry → hop → leaf → internet, with the leaf
  doing the NAT.
- **And a friend still cannot reach the nodes' own network**: the same client aimed at a
  plain HTTP server on the hosts' private network got an empty reply, nothing crossed the
  hop, and the entry's rendered routing rule is why.

Neither this nor anything else here says anything about a real Russian network. The
charter's first success criterion is a field observation with a phone.

---

## B1 — the apply's check measures the wrong thing, and it deleted a true finding twice

**Done.** With the leaf serving and its hop established, the walker replaced the node's
image with one identical except that `awg-quick` exits 0 having done nothing. Nothing else
on the host was touched. Then: probe, apply, probe, apply
(`.acceptance/M26/r3-signature-defect.log`).

**Seen.** The node's own generated compose command is

```
sh -c 'set -e; … "$0" up "$1"; while :; do sleep 86400 & wait $!; done'
```

so a data plane whose `up` returns 0 without establishing anything **leaves the container
up for ever**. The apply reported **success**: row `active / in sync`, probe sub-line
gone, Overview silent, `nodes active 2`. On the host at that moment: `ip addr` →
*"Device "amneziawg" does not exist"*; the only process besides the shell was `sleep
86400`; across the hop, **100% packet loss** with a six-minute-old handshake. In the
database: `r3leaf | active | (null) | (null)`. A probe sixty seconds later caught it in
under ten — *"nothing listening on the port for: amneziawg. Its container is up and
nothing holds the port"* — **and the next apply deleted that finding too.** Not a race:
deterministic, reproduced twice. Unlike round 2's version, here the **second** press is
the dishonest one.

**Expected.** The walker's own sentence is the diagnosis and was taken as the brief: *the
apply discards a measurement of **serving** on the strength of a measurement of
**liveness**, and the port check that would have refused already exists, in the probe.*
Given that supervisor shape, container liveness is not a weak signal for whether a node is
serving — it is an **unrelated** one. A container holding a port and a container running
`sleep 86400` are indistinguishable to it, permanently.

**Fixed, on one principle, written at the clearing itself:** *an apply may only clear a
finding it has actually contradicted, with a measurement of the same kind.* Step 5 of an
apply now takes the probe's own reading — `edge.health.listening`, the port off the
operator's row and the protocols off the transport's declaration — **inside** the settle
loop (`control/app/services/serving.py`), so:

- a placed config that stayed up and holds **nothing** refuses the apply and marks the
  node degraded, in the probe's own words (*"nothing listening on the port for: …"*), so
  one fault about one host does not acquire two vocabularies;
- a config whose port **could not be asked about** — no port on the row, no protocols
  declared, or a host that would not give up its socket table — **does not fail the
  apply** and **does not clear anything**. Round 2's "nobody could ask" third state is the
  reason to handle the state, not to skip the reading; a reading that could not be taken
  is not a confirmation. The finding stands and the row goes on saying so;
- the port question is asked inside the settle loop rather than after it, because a daemon
  binds some time after its container starts and a check that could not wait for that
  would be round 2's false red rebuilt one layer down.

**Round 2's life-token settle loop is untouched and still necessary** — a container that
dies and restarts between two glances reads `Running: true` at both. It is necessary and
not sufficient, and both halves are now under test, in two files that keep to their own
subject: `tests/control/test_an_applys_own_check_waits_for_the_daemon.py` (the container)
and `tests/control/test_an_apply_measures_serving_and_not_liveness.py` (the socket). Every
host in the first now holds its port, because a fake that held nothing could be refused
for its socket while the file believed it was proving something about its container —
with that left unfixed, reverting the life-token comparison left the whole file green.

**And round 2's row in `docs/decisions.md` is corrected rather than left standing beside
its reversal**, the way round 2 was asked to correct round 1's.

## B2 — the Overview said nothing was applied when something was

**Done.** Read the Overview after an apply that failed on the crash-looping leaf.

**Seen.** *"The last probe of r3leaf found it not serving … and **nothing has been applied
to it since**."* Something was: `/opt/hashi/conf/amneziawg.conf` on the host has mtime
`15:01:17` and the apply was at `15:01:16`. The sentence is false, and it is false in the
direction that reassures — it tells the operator the host is untouched since the reading,
when in fact its files were replaced and the replacement did not come up.

**Expected.** A screen may claim only what it knows. What this panel knows is what has
been MEASURED, and an apply that pushed files and failed to confirm them is not a
measurement of what the node is serving.

**Fixed.** `console.FLEET_NOT_SERVING` now reads *"…and nothing has contradicted that
since — files may well have been pushed to it in the meantime, and pushing is not
measuring."* It is true by construction rather than by inspection: the finding survives
exactly when nothing has cleared it, and what clears it is a contradicting measurement.
`console.COUNTERS_COUNT_CONFIGURATION` says the same thing where it explains the counters,
including the case an apply cannot ask about.

## H1 — the "Add a node" form cannot be submitted in a 1440×900 window

**Done.** Opened Nodes → add node in a 1440×900 browser and tried to submit it
(`.acceptance/M26/r3-005-add-node-form-007.png`, `r3-008-leaf-submit-016-failed.png`).

**Seen.** The form is taller than the viewport, its submit button is below the fold, **and
that button shared its label with the header button that opened the form** — so pressing
"add node" re-opened the form. Actions were spent on it. This is the second walk a form
has cost: walk 2 ran out of budget inside the hop dialog and never reached the hop.

**Expected.** The button that submits a form must be addressable and visible. A press
aimed at a dialog's own action must not land on the screen behind it.

**Fixed, in both halves.** The three creation dialogs now carry a submit whose name is not
any other button's on the page — **"register node"** (the verb `node-bootstrap.sh` itself
uses when it tells the operator what to do next), **"issue subscription"** and **"write
both ends"**, which is also the more honest sentence: that press writes two rows and
establishes nothing until both nodes are applied. The two confirmations opened from a row
whose table stays on screen behind them had the same collision and are renamed with it —
**"delete their key material"** and **"dissolve both ends"**. And the actions of the two
tall dialogs are pinned to the bottom of the scrolling box, so the submit is on screen
whatever the form's height.

`tests/control/test_a_dialog_can_be_pressed.py` holds it, comparing names the way the
thing that presses them matches: case-insensitively and by containment, which is what
`page.get_by_role(name=…)` does without `exact` — so renaming a button by appending to it
would fix nothing and is refused.

## M1 — an internal symbol in an operator-facing hint

**Done.** Read the enable dialog's port box.

**Seen.** *"the port Xray listens on, inside `META.port_range`"* — an internal name the
operator cannot open, with the range it stands for shown nowhere on the form.

**Fixed.** The hint says the numbers, interpolated from the same declaration the validator
enforces (`edge/transports/vless_reality/params.py`), so no port is written into code by
hand — which is the rule that put a symbol there in the first place.
`tests/edge/test_a_field_hint_is_written_for_a_person.py` holds every installed
transport's every hint to naming no identifier out of this codebase, and holds a port hint
to stating its transport's own range.

## L1 — 14 values still hand-typed for a hop, 5 for a transport, 13 for a node

**Done.** Counted what the walk typed, and judged each remaining box on its merits, as the
finding asks.

**Kept from round 2, unchanged and verified by this walk**: the four matched parameters
per end arrive already drawn — three renders gave three different sets, identical within
each end-pair, and both stored rows carried the same values
(`.acceptance/M26/r3-hop-magic-headers-three-renders.log`). That property is not to be
disturbed.

**Judged, and no new value is drawn this round.** Field by field, and the reason differs:

- **`port`** — the hop's UDP port must be chosen BEFORE the leaf's bootstrap runs, because
  that run is what opens it in the firewall (Shape C step 2, walk 1's L3). A number drawn
  by the panel afterwards is a number no host is listening for.
- **the two tunnel addresses** — a drawn range would have to avoid not only every other
  hop this panel knows about but everything already on those two hosts: the provider's own
  networking, the docker bridges, whatever else the operator runs. The control plane
  cannot see any of it, and the params model says what a wrong answer costs — a public or
  colliding range takes the host off the network, "only fixable with console access".
- **`mtu`** — a property of the path, which nothing here measures; the transport refuses a
  default in as many words, and a value chosen in `control` would be `control` overruling
  `edge` about a protocol.
- **the three junk-packet knobs** — and **round 2's stated reason for these was wrong**,
  which is worth correcting: it said a cross-field rule (`max` not below `min`) is one no
  generic draw can honour, and an ordered draw honours it trivially. The real reason is
  that their declared bounds are **validation** bounds, not draw bounds: every value in a
  magic header's 32-bit field is equally good, which is why drawing one is safe, while
  `junk_packet_count: 0–128` and sizes up to 1280 differ enormously in what they cost the
  tunnel. Drawing from those bounds would hand the operator a working hop that is slow for
  a reason they did not choose and cannot see. **What would close it is an `edge`-side
  declaration of a recommended draw range per field** — a protocol judgement belonging to
  the transport's own package, and a milestone rather than a fix round.
- **key material and the Reality decoy destination stay empty**, and that is not a
  judgement call: `CLAUDE.md` forbids a shared decoy outright, and a fleet that borrows one
  handshake becomes enumerable.

One candidate is recorded rather than built, because it is a derivation rather than a
default and has a machine-readable declaration behind it (`TransportMeta.peer_address`):
**each end's `peer_tunnel_address` is the other end's `tunnel_address`**, which is what
`edge/relay.py` already writes into the rendered peer block. Filling it from the other
column would remove two of the fourteen boxes and a class of typo. It is left for a
milestone because it changes what the hop form submits, and this round is a fix round.

---

## What the walk found closed, and what must not regress

- **The charter's `serving traffic` and `answers a health probe` are gone**, and success
  criterion 2 names the script.
- **The four-surface drift announcement is true, and all four go silent after the apply** —
  Users screen, link dialog, Nodes row, Overview.
- **A probe finding survives a reload**, does **not** clear on unaided recovery, and
  **does** clear on a fresh probe.
- **`node-bootstrap.sh`'s ufw-logging lines are scoped to `/etc/ufw/ufw.conf`** and true
  when printed, with the refusal still firing against a lying ufw.
- **A failed `ufw --force enable` exits 1 naming the exposure.**
- **Both scripts are idempotent and non-interactive** (host-state fingerprints identical
  across runs; stdin on `/dev/null`).
- **The false-red direction is fixed**: a leaf whose container failed once and settled
  (`RestartCount = 1`) applied to `active / in sync` and was genuinely carrying traffic.

## The edge nobody has measured, and what was done about it

The walk **could not starve the new watcher** — a container down longer than the settle
window, then recovering — and filed that nobody knows what the window does at its edge.
`tests/control/test_an_applys_own_check_waits_for_the_daemon.py` now builds exactly that
host: the apply **refuses**, because the ceiling running out is not evidence of anything;
the wait is bounded by the ceiling rather than by the container; and the same host, pressed
again once its data plane is up, applies and goes active — so a node that is slow for a
reason outliving one press is not locked out of its own panel. That is a test, not a walk:
what it holds is the arithmetic of the window, not how long a real daemon takes.

## What this walk could not check

No live host was touched (`45.151.69.107`, `158.160.67.252` carry the owner's real
traffic), so there are no byte counters from the field. The bare hosts were privileged
containers, so a real VPS differs in its kernel, its provider firewall and its `rp_filter`
default. The panel walk ran on a host whose DNS name does not resolve, so Caddy obtained no
certificate and the public delivery endpoint was exercised only over the private site. And
nothing here says anything about a real Russian network — the charter's first success
criterion is a field observation with a phone, and no test run and no stand is evidence
for it.
