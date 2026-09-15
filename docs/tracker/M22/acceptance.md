# M22 — acceptance: **folded into M23's real-host walk**

**No separate stand walk was run, deliberately.** M22's acceptance line is:

> Break a transport's config so its container crash-loops, then press probe. The
> answer must not say the node is serving it.

That is a question about **a real container engine on a real host**, and M23 —
approved by the owner, walking the whole platform on the Amsterdam leaf — is
where it can be answered properly. A probe judged against fabricated containers
on a stand is a weaker answer than the same probe judged against a daemon that
really crash-loops.

**The premise is already proven against a real engine inside the gate**:
`tests/e2e/edge/test_a_crash_looping_container_is_not_reported_as_running.py`
reproduces the field state on engine 29.4.0 rather than modelling it — which is
the right place for a fact about somebody else's software.

**M23's walk must confirm, on the leaf:** a transport whose container is
crash-looping is not reported as serving; one listening on nothing is not
reported as serving; a genuinely working transport **is** reported as serving
(the accept-case — M19's convention: a probe that calls a working node broken is
the same defect as one that calls a broken node working); and the success answer
is as visible as a failing one.

## What was established without a walk

**Review: 0 critical, 0 high.** The reviewer re-ran the gate itself and matched
every count exactly, noting the deltas reconciled so **nothing was removed to
make room**. It ran **27 mutations of its own**, 24 caught.

**The decision M22 actually turned on.** "Serving" now means: the container is up
**and not restarting**, **and** something holds the port it was given over every
protocol the transport declared it binds. Both, per placed config.

**A handshake check was refused, and the reason is the charter's.**
`wg show latest-handshakes` returns peer public keys with timestamps — **a record
of who connected and when.** A probe reading it would *be* a connection log
whatever it then did with the bytes. The reviewer sharpened this: the *layering*
reason is the one that settles it, because an Xray transport keeps **no handshake
table at all**, so the charter reason bites only on the WireGuard family while
"it cannot be asked without naming a protocol" covers every transport. The header
was reordered to put the reason with no exceptions last.

**So the probe's ceiling is a choice, not a shortfall** — and the wording says so:

> Read on the node itself, not dialled from outside — so this is not proof that
> anyone can connect.

**The root cause was subtler than reported.** The old probe did not measure that a
container *exists*; it read `.State.Running`, which is **`true` during restart
backoff**. That rules out the cheap fix (`.State.Status` is also `running` in the
alive instant) and is why the socket check is load-bearing rather than
belt-and-braces. `Restarting` alone is a **sample** — a probe landing in the
~100 ms alive window would answer "running" truthfully.

**A third answer exists on purpose.** A host without `ss`, or a socket table with
no listening socket at all, reports the port as **unchecked** rather than silent.
Collapsing "nothing is listening" into "nobody could ask" would be this
milestone's own defect pointed the other way.

**No transport declares anything new.** `TransportMeta.listens_on` already existed
from M15's port-collision rule. A fifth transport is probed by arriving.

**The charter's record holds.** Nothing on the probe path — `bound_ports` →
`NodeConnection.run` → `parse_sockets` → `probe` → `check_node` → `node_health` →
`probe_node` — makes a logging call at **any** level; no audit entry is written
for a probe; `parse_sockets` reads fields 0 and 4 only and **never indexes the
peer column**; `ss -l` makes a peer address structurally impossible, and mutating
it to `-a` is caught. `edge/health/listening.py` carries **no module logger**,
unlike every other module in its zone — *"a logger sitting beside a socket-table
reader is an invitation, and the no-logging rule has no debugging clause."*

## The two findings the review caught, both fixed

**Instance seventeen of a verification that cannot fail.** Replacing
`placement.binds_of(transport_name)` with a literal `frozenset({Layer4.TCP})`
left the **entire suite green** — 65 tests across every file reaching
`check_node`. The one test asserting protocols checked `vless-reality`, **whose
declaration IS that literal.** So the milestone's central claim was asserted only
where the declaration and the constant coincide.

**Its failure scenario is why this mattered:** every `amneziawg` row in the fleet
checked for a **TCP** socket on its **UDP** port, finding none, and every working
node reporting *"nothing holds the port"* — M19's forbidden direction, fleet-wide,
on the one transport proven end to end on real hardware.

Now parametrised over `discover()`, asserting the property rather than a value.
Mutation proof: `2 failed, 2 passed` — amneziawg and wireguard fail, the two vless
transports still pass, *which is exactly the coincidence the old test lived
inside*.

**A shipped bug waiting on port 443.** The command guard pinned `-l`, `-p` and
`-a` but **not `-n`**. Without it `ss` resolves through `/etc/services`, so the
address reads `0.0.0.0:https`, `port.isdigit()` is false, and the line is
**skipped silently**. 443 is the most operationally likely port in this product.
The real-tool test could not catch it because it binds **ephemeral** ports, which
have no service name.

## M22.3 was a different defect from M18's

M18's was **place** — a banner rendering above the fold, fixed by
`watch("banner-slot", … scrollIntoView)`. This was **time**: the success answer
was a toast cleared after **2200 ms**, and acceptance's shortest wait was 2 s plus
snapshot latency. `scrollIntoView` could never have helped.

A healthy probe now answers into the banner slot as a **notice** — same slot, same
lifetime, picked up by M18's existing observer for free. A deliberate exception to
`UI-PATTERNS §8`, argued on the grounds that **a probe is not a mutation**:
nothing changed, and its answer is the reason the button was pressed. Recorded in
`docs/decisions.md` as reversing one clause of the 2026-09-13 row.
