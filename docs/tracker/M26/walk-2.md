# M26 — acceptance walk 2: **findings**, gate BLOCKED (2026-09-16)

A second independent walker took bare hosts (privileged containers with volume-backed
`/var/lib/docker`), ran both bootstrap scripts, drove the real panel in a real browser and
carried a friend's real traffic. Its evidence is in `.acceptance/M26/` — gitignored, so
what it measured is written down here instead. 200 actions, 75 minutes.

Round 1's three blockers came back **verified two-sided** and are not re-opened below;
what they hold is listed at the end. This walk found **one blocker, one high and three
lows**, and left the fourth "done when" unreached.

**The blocker was created by round 1's own fix.** That is the most useful line in this
file, and it is written first on purpose. Round 1 decided, on its own initiative, that *"a
successful apply clears the finding, because step 5 of an apply verifies the daemon came
back on the config it just pushed — strictly more than a probe establishes."* **That
premise was false twice over**, and this walk broke it twice in the same session. Every
fix below is downstream of it.

---

## The counts it measured

| From | Commands | Panel actions |
|---|---|---|
| bare host → node **serving** | 1 | 3 — add node, enable transport, apply |
| bare host → **a friend's packets moving** | 1 | 5 — the 3 above + add user + **apply again** |
| two bare hosts → established **entry→leaf hop** | 2 | **not reached** — 4 of the 6 walked, the budget ran out in the hop form |
| bare host → **control plane** | 13 from the runbook's block | 0 |

The first two rows match what the charter's own table claims, walked rather than read. The
third is unconfirmed by this walk beyond its first four actions — see the high below.

---

## B1 (walk 2) — an apply DELETES a true probe finding and then reports nothing

**Done.** With the leaf's data plane unable to start (an interface named `amneziawg`
already existed on the host, so `awg-quick` failed and the container crash-looped), pressed
**probe**, then pressed **apply**.

**Seen.** The probe was right and the panel stored it: *"r2leaf answered but is not serving
— not running: amneziawg."* After the apply, at 20 seconds and still at 65: row `active /
in sync`, the probe sub-line **gone**, the Overview silent, `nodes active 1 / transports
serving 1`. `SELECT name,state,last_probe_at,last_probe_finding FROM nodes` →
`r2leaf | active | (null) | (null)`. On the host: `hashi-node-amneziawg-1 Restarting (1)`.
The friend: **100% packet loss**. Reproduced twice.

**And the apply's own check existed all along.** Pressing apply a *second* time on the same
host said *"configuration was applied but the node is not serving it — marked degraded:
pushed, but these did not come up: amneziawg"*. So it was sampling the container **inside
the first seconds of its first start** — which is precisely the apply an operator makes
after a change. **It fired the other way too:** one apply on a leaf whose container came up
a moment later left the row **`degraded`** while that friend's ping was **0% loss**.

**Expected.** Nothing may erase a measurement except a measurement that actually
contradicts it. An apply whose serving sample is taken too early to mean anything has not
contradicted the probe; it has merely run. And an operator told their node is broken while
it is carrying traffic is an operator who learns to ignore the warning — so both
directions are the bug.

**This is the project's signature defect class in its newest form.** "A verification that
cannot fail" has been found here about seventeen times. This one *can* fail — **at random,
in both directions, depending on how fast a container starts.**

**Fixed.** Step 5 of an apply is now a bounded **settle-and-resample**
(`control/app/services/serving.py`): two readings an interval apart, and a container is
confirmed only when both saw the **same life** of it. That last word is the whole fix — a
container that dies and is restarted between two readings is `Running: true` and
`Restarting: false` in both, so two readings alone would have changed nothing. Every
reading now carries `.State.StartedAt` per service as an opaque token
(`edge.bootstrap.node_stack.RunningContainers.started`), compared only with itself and
never with a clock. The window is `node_settle_interval` (2s) and `node_settle_timeout`
(20s) in settings; a healthy apply costs one interval, a host that never settles costs the
ceiling once, and **a ceiling with no time in it confirms nothing**.

**And the premise is corrected rather than left standing.** An apply's check is *not*
strictly more than a probe's: it asks no host what is holding a port. What is true is that
an apply **replaces every process the finding was about**, and now refuses unless it has
watched the replacements stay up — so the finding is obsolete rather than contradicted.
An apply that could not confirm **clears nothing**. `last_probe_at` stays NULL, because an
apply is not a probe and the row must not read as though one had been taken. The panel's
sentence, which promised the opposite (*"what that found is kept until the next apply"*),
now says which of the two clears it and what each establishes.

**Tested by exercising the timing, not a fixed answer**
(`tests/control/test_an_applys_own_check_waits_for_the_daemon.py`): a fake host whose
containers behave as a function of wall-clock time — one that always *looks* healthy and
never keeps a life, one that is being restarted when the apply first looks and settles a
moment later, one that comes straight up. Reverted to the single glance it was, five of its
six tests go red, in both directions.

## B2 (walk 2) — the hop "done when" was not reached, and the reason is the finding

**Done.** Prepared two bare hosts with one command each, registered both (the entry with a
resolver, as the runbook requires of a node that dials a hop), enabled `vless-reality` on
the entry — and opened the hop form.

**Seen.** The form's face has improved to three comboboxes, and behind *advanced tuning*
sits the same set as before: **eleven parameters per end with no defaults.** The walker's
action budget ran out there. No hop row was created.

**Expected.** Whatever the form asks for, it must not be the thing that stops a walk. And
four of those eleven are AmneziaWG magic headers that must be typed **identically at both
ends** — where round 1 had just taught `edge.relay` to refuse a pair that disagrees. The
product was inviting the typo and then refusing it.

**Fixed.** The dialog now opens with a value already in every box the transport declares
both ends must carry identically — **drawn per hop with `secrets`, inside the bounds the
transport's own field declares, distinct from each other, and written into both ends from
one draw.** A minted value is not a default: a default is one value every hop borrows,
which is the fingerprint `CLAUDE.md`'s shared-decoy rule is about; this is what key
material already does one field over. A refusal re-renders whatever the operator typed and
never redraws.

**Everything else stays empty, and the form now says why** — a port and the two tunnel
addresses belong to these hosts and to whatever is already on them, an MTU belongs to the
path, and the junk-packet sizes carry a rule between two of them (`max` not below `min`)
that no generic draw can honour, so a drawn value could arrive already refused. The
single-node transports dialog is deliberately untouched: there the same four numbers are
rendered into both ends of a friend's tunnel by us, so a hand-typo cannot produce a dead
tunnel, and what is left is the hazard the box's own warning is for.

`edge` gained the ceiling those four fields never declared (`MAGIC_HEADER_MAX`, the
protocol's 32-bit field width): a matched parameter with no upper bound is one nothing can
draw inside, and `tests/edge/test_relay.py` now holds every transport that declares a
parameter matched to declaring its bounds as well.

**Not claimed:** no hop was established by this walk, so the charter's third row stays
unconfirmed beyond its first four actions, and **nothing here says a friend's traffic has
crossed a hop.**

## L1 — two false statements about ufw logging, before the check that contradicts them

**Done.** Ran `node-bootstrap.sh` against a ufw whose `logging off` silently no-ops, whose
`/etc/ufw/ufw.conf` said `LOGLEVEL=off` and whose `status verbose` said `Logging: on
(low)`. Evidence: `.acceptance/M26/node-bootstrap-ufw-logging-claim.log`.

**Seen.** `==> ufw logging was already off` **and** `==> ufw logging is off; the log file
it may have had is gone` — and only then the correct refusal. Round 1 fixed one path and
added another. End state honest, scroll not, **on the one line in the run about the record
the charter forbids at any level.**

**Expected.** A line may claim only what the thing it read actually said.

**Fixed.** The two sources genuinely disagree on exactly that host, and ufw's config file
is the only one that answers while the firewall is inactive — which is the state that step
runs in. So each line names the source it read (`/etc/ufw/ufw.conf already reads
LOGLEVEL=off`), and the claim that the firewall is not logging is made once, in section 6,
of the **running** firewall, with its own line: `the running firewall was asked and it is
not logging`. Both are quoted in the runbook and held by `tests/infra`, which now checks
the ordering on the script's own text as well as by running the block — a fragment can
only prove the lines it runs.

## L2 — the charter still said a replacement is bootstrapped "from the panel"

**Done.** Read criterion 2 against the section written to remove exactly that
overstatement, one screen below it.

**Seen.** *"when I destroy it and bootstrap a replacement **from the panel**"*. The panel
bootstraps nothing. Round 1 narrowed the deployment section — which references this
criterion — and left its wording alone.

**Expected.** A page that corrects itself in one place and goes on overstating the product
two hundred lines higher is worse than one uniformly wrong: the correction reads as
complete.

**Fixed.** Criterion 2 names `scripts/node-bootstrap.sh`, says it is run over SSH from the
machine holding the fleet's key pair, keeps the ten minutes, and records in place what it
used to say. Every success criterion is now held to it by
`tests/infra/test_the_charter_states_what_the_scripts_deliver.py`.

## L3 — `awg-quick` deletes the interface it just raised when `resolvconf` is missing

**Done.** Loaded the subscription's `?format=client-config-file` on a plain Linux client.
Evidence: `.acceptance/M26/r2-friend-traffic.log`.

**Seen.** `awg-quick` runs `resolvconf -a awg0`, gets `command not found`, and **its own
error path deletes the interface it had just brought up**. The friend's device is up and
then is not, and the last line is about a program they have never heard of.

**Expected.** Client-environment rather than product — but it is what a Linux friend meets,
and round 1's note said the tunnel *"does not come up at all"*, which is not what happens
or what they see.

**Fixed in the page.** `docs/deploy/runbook.md` now carries the transcript, names the
package (`openresolv`), says twice that nothing on the node changes and nothing on the node
is wrong, and forbids the obvious wrong fix: deleting the `DNS =` line leaves the friend's
device asking a resolver it can no longer reach, so the tunnel looks fixed and resolves
nothing.

---

## Round 1's three blockers, re-checked and holding

- **B1 — the charter no longer overstates the scripts.** *"from a bare host to serving
  traffic"* and *"the node answers a health probe"* are both gone; the node-bootstrap row
  reads *"from a bare host to a host the control plane can drive"* and quotes the line the
  script printed on both bare hosts. The measured table's first two rows match what this
  walk counted.
- **B2 — adding a user reaches the operator on every surface, in the right order.** Before
  applying, all four said so — the Users screen, the link dialog, the Nodes row (`1 / 1
  drifted`), the Overview (*"Not yet pushed to r2leaf"*) — and the claim was TRUE at that
  moment (0 `[Peer]` blocks on the host, no peers in `awg show`). **All four went silent
  after the apply**, when the host held 1 `[Peer]` and the friend's traffic flowed.
- **B3 — a probe finding survives a reload.** Still there after a fresh page load,
  timestamped, with a matching Overview note and `last_probe_finding` set. It did **not**
  clear when the container came back by itself (correct — nothing had re-measured) and
  **did** clear on a fresh probe (correct — something had). *The walker noted this fix was
  undone by the apply defect above; that is what B1 of this walk fixes.*

## Also re-proved this round, and not to be regressed

- A failing `ufw enable` exits 1 with a `node-bootstrap:` sentence naming the state — *"it
  is EXPOSED — every port it has is open until this is fixed"* — with ufw's own words
  inside it.
- The make exit-code collapse is documented: direct, a refusal is 1 and a bad argument is
  2; through `make` both are 2, and the runbook says so.
- The hop's UDP port is chosen **before** the leaf is prepared (Shape C step 2). The walker
  followed it and opened both ports in one run.
- The control plane's 13 commands, and the missing `docker`/`git`/`make` prerequisites, are
  written down in both documents.
- **Both scripts idempotent** (host-state fingerprints byte-identical across runs; panel
  `.env` and `awg-mgmt.conf` shas unchanged, no keys re-minted) and **non-interactive**
  (stdin on `/dev/null`, exit 0).
- The panel under stress: an empty nickname stopped by the browser; 1000 characters refused
  field-level with the dialog intact and nothing written; a double apply producing two
  audit rows 1.55s apart with no dropped packet; an abandoned hop dialog saving nothing;
  browser-back re-rendering live data with no ghost dialog.

## What this walk could not check

No live host was touched (`45.151.69.107`, `158.160.67.252` carry the owner's real
traffic), so there are no byte counters from the field. **No hop was established and
nothing was carried across one**, and with no Xray client available the entry's
`vless-reality` was proved only as far as the panel accepting it. The runbook's final
control-plane check returned 000 because the stand's hostname does not resolve and Caddy
obtained no certificate — a limit of the stand, not an observation about the product; the
console was proved over the private site instead. The bare hosts were privileged
containers, so a real VPS differs in its kernel, its provider firewall and its `rp_filter`
default. `panel-bootstrap`'s broken-stack refusal and `node-bootstrap`'s `ip_forward=0`
refusal were not re-proved this round; round 1 proved both. And nothing here says anything
about a real Russian network — the charter's first success criterion is a field observation
with a phone, and no test run is evidence for it.
