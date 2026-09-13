# M18 — acceptance: **partial**, with one blocking-class finding referred to the owner

Two rounds, walked by an independent agent on a disposable stand with **no sight
of the diff or any account of how it was built**. Round 1: 154 actions, ~35 min.
Round 2: 158 actions, ~33 min.

**Both rounds built a real node** — a privileged container with its own dockerd
and sshd on the stand's network, `node-bootstrap.sh` run on it for real, a node
registered against it with a real SSH key, and a real apply that pushed files
over SSH and ran `docker compose up -d`. That is what separates a true sentence
from a plausible one here, and it is why both verdicts are worth their weight.

## Verdict

**Round 1 — blocked.** One `lies`-class finding.
**Round 2 — round 1's blocker closed; blocked again on two findings, one of them
new and outside M18's scope.**

**Recorded as partial.** Both of M18's own "done when" lines pass. What remains
is one defect the run declines to fix inside this milestone, referred to the
owner rather than downgraded — see *The disagreement* below.

| "done when" | verdict |
|---|---|
| Applying a node with no transports gives an answer an operator can act on, and does not degrade the node | **good** |
| The panel's node form does not silently point at an account the bootstrap script did not prepare | **good** |

## Round 1's blocker, and how it was closed

Removing a node's **last** transport promised an apply that would never come:

> "The node keeps serving it until you apply the node: this changes what this
> panel holds and hands out, not what the host is running…"

When it is the last transport that is **false** — the apply is then refused, so
no apply ever stops the host. Proven on a real applied host: after remove +
apply, `hashi-node-wireguard-1` was still **Up**, `wireguard.conf` still present,
and the panel's own probe still said the node was serving it — while the Nodes
row read `active` / `nothing enabled` / `none`.

**An operator who removes the last transport specifically to cut everyone off,
presses apply, and reads "nothing on the node was changed" has every reason to
believe access is gone. It was not.**

Closed, and re-verified on a rebuilt real host. The confirmation now reads:

> "This is the last transport enabled on realhost, so the apply that would stop
> the host serving it is refused: with nothing left to push, an apply changes
> nothing on the node. … the way out is to enable a transport on realhost and
> apply that."

and the refusal:

> "…if a transport was removed here to cut people off, removing it did not stop
> the host serving it."

Both true at the moment they were shown. **The named way out was then followed
and works** — enabling a different transport and applying removed the wireguard
container from the host. With two transports the original sentence is retained
and is also true.

## Round 1's other three, all fixed and re-verified

- **Overview's "nodes online"** counted `active` state, not anything serving.
  Now labelled **"nodes active"**; acceptance flipped an untouched node's state
  and watched the count move — label and count agree.
- **`gaierror` and a wall of docker-pull layer ids** reaching the operator: gone.
  Now *"this node's address could not be resolved"*, *"docker is not available on
  this node…"*, with the cause still recoverable from the server log.
- **The bootstrap script's contradictory closing summary**: first run and re-run
  are each coherent, and M18.3's file-handover claim was verified end to end —
  `/opt/hashi` chowned to root, script re-run, contents really came over.

## The charter's hard rules — checked on a real fetch, not assumed

After a real subscription fetch: **no token, no `/sub/` path, no nickname, no
node address and no client IP** in the control or Caddy logs. No IP-shaped string
on any panel page. A bad-key refusal echoed **zero characters** of the value.

## The disagreement — one blocking-class finding, referred rather than resolved

**The panel's probe reports a crash-looping transport as serving.**
`vless-ws-tls` exited 23 every second (a missing certificate file), nothing was
listening on its port, and the panel answered *"realhost is serving amneziawg,
vless-ws-tls"* on **six consecutive probes**. With the container **fully
stopped** the probe is correct — so `Restarting` counts as serving. The probe is
the operator's **only oracle** for *is this node working*, and a certificate path
that is not there yet is an ordinary first-run mistake.

**Acceptance blocks M18 on it. The run declines to fix it inside M18, and says so
rather than downgrading it.** The reasons, for the owner to accept or overrule:

1. It **predates M18 and M18 does not touch it**. Acceptance itself records it as
   *"New this round, not one of round 1's four."*
2. **Both of M18's own done-when lines pass.**
3. Fixing it properly is a **product decision, not a patch**: what does "serving"
   mean — the container exists, is running, is listening, or a peer has
   handshaked? Each answer has a different cost and a different failure mode.
   That is a milestone.
4. The owner's own standing rule: *"A milestone that turns out to need work the
   plan does not mention is a new milestone for the owner to approve, not a
   bigger one for you to finish."*

**It is recorded in `docs/decisions.md` as measured-and-not-closed**, with the
evidence and what the decision would have to settle. **M18 is not marked good.**

It is the same failure shape as M14's *"handshake completes, nothing moves"* —
every signal green, nothing carried — which the charter treats as the shape that
hurts most, because the operator stops looking.

## Works, but awkward — dispositioned in carry-over.md

Fixed in the round-2 tightening, all four with mutation proof:

**The script's silent exit 2** on `--user <account that does not exist>` — zero
bytes on stdout *and* stderr. M18's own theme in its purest form. **The cause was
not where it looked:** `TARGET_HOME="$(getent passwd … | cut -d: -f6)"` — when
the account does not exist `getent` exits 2 and prints nothing, so under
`set -euo pipefail` the **assignment** ended the run before the refusal on the
next line could fire. `getent` is the only command in that file that can end the
run without printing; a test now holds every one of them to being guarded.

**The never-applied node** described as though something had been pushed to it.
On the dialogs, whose row survives, this is now known from `applied_at`. On the
remove path's refusal it **cannot** be known — and rather than guess, the
sentence states the uncertainty and names the missing record. Three ways of
knowing were considered and rejected: the audit trail keys on the node's *name*
and is deleted by the retention sweep, so its absence is not evidence;
`ssh_host_key` is written *before* `place_config`, so a value proves a session
and not a push; and a new column cannot be backfilled for the one case it would
exist for. **A false "nothing was ever pushed" is exactly the lie this milestone
exists to remove.**

**An unrecognised docker error** dumped raw and cut mid-word: the truncation
budget is now spent from the **end** — the last line first, which is where the
daemon's actual error is — and every cut is marked.

**The API handed panel directions** in a JSON error body. Split at the existing
`wording.for_the_page` seam, with a test that every clause written for a screen
has a console version.

Left open with reasons: the removed transport's **config file, `PrivateKey` and
all, stays on the host** after apply — same family as the recorded *"nothing
stops a node serving its last config"* gap; and a **successful** probe answer
never became visible on screen in four attempts, while every failing probe's
banner did.

## Could not — needs the field

- **Whether any tunnel carries traffic**, and the charter's first success
  criterion. *Observation required:* from a mobile connection inside Russia
  during a whitelist shutdown, import the subscription and confirm the node
  answers. Nothing in this run or any test covers it.
- **Whether the apply refusal is visible without scrolling** from the bottom of a
  long node table. The driver writes full-page captures. *Observation required:*
  a person at the screen, scrolled to the bottom of a 43-row table, presses apply
  on the last row and says whether the answer appears without touching the
  scrollbar. **No scaffolding was built to fake it.**
- Whether the probe's success banner flashes briefly or never renders at all.
