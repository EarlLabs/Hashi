# M23 — acceptance: **good** (9 walks, 14 fix rounds)

**The loop the owner asked for, run to completion:** walk the real hosts, write
every finding down, fix them all, walk again — and repeat while any BLOCKING or
HIGH finding is open. **Round 9 came back clean.**

## Why this milestone existed

Six milestones in this plan closed **partial**, every one for the same reason:
*the stand has no data plane, no tunnel and no second host.* `make verify` cannot
prove a tunnel carries a packet, and this project's most expensive defects have
all been one shape — **every signal green, nothing carried**.

## The arc

| walk | found | severity |
|---|---|---|
| 1 | 6 | HIGH |
| 2 | 4 | blocking |
| 3 | 2 + 1 half | blocking |
| 4 | 1 + 1 + 2 | blocking / HIGH / clumsy |
| 5 | **1** | **blocking — the worst finding of the run** |
| 6 | 1 | blocking (the IPv4-only sibling) |
| 7 | 2 | blocking / HIGH |
| 8 | 2 | blocking |
| **9** | **0** | **clean** |

**Tests across the milestone: control 729 → 842, edge 376 → 843.**

## What only a real host could show

**Round 5 — a friend's tunnel reached the private hop network.** An ordinary
friend served by the leaf opened TCP to the **Russian entry at `10.90.0.1`** and
was answered by its sshd: `SSH-2.0-OpenSSH_9.6p1`. Ports 80 and 443 accepted;
4444 did not, so it was not a probe artefact. **RTT identified the host — 104 ms
to the entry against 52 ms to the leaf.** That address is RFC1918 and unreachable
from the open internet, so **the tunnel granted reach a friend could not otherwise
have** — and their packets were masqueraded on the way in, so **the entry saw them
from its own trusted peer address.**

Nothing was individually broken. `PostUp` rendered exactly what M14 designed,
the rule did what it said, and the friend↔friend isolation added in round 1 worked
perfectly. **The hole was in what the rule did not say**, and it only becomes
visible when a second interface exists on the same host with something listening
at the other end.

It took **four layered rounds** to close, each finding the previous one's blind
spot: the kernel tunnels by destination; the entry's proxy by inbound tag; the
leaf's proxy (same hole, wider — the leaf's **cloud metadata service** was
reachable); and then names, because `127.0.0.1` was refused while `localhost` and
`10.90.0.2.nip.io` walked past.

**Closed and proven with the product's own rule counters** —
`-d 10.0.0.0/8 -i awgt0 -j DROP` caught **47 packets**, `-d 169.254.0.0/16`
caught **10** — and re-verified on every subsequent walk.

## Six more that no stand could reach

- **A friend's config gave them no DNS at all**, while the config's own comment
  reassured them otherwise. Handshake green, 5 MB flowing, **not one name
  resolving.**
- **Every friend on a node shared one PresharedKey** — two lines, one unique
  value, in the product's own rendered config. One leaked config exposed the key
  protecting everyone else's handshake, and revoking that friend did not rotate it.
- **Friends could reach each other's devices** — and, found while fixing it,
  **across two different transports of one node**, which `-i %i -o %i` never
  matched.
- **A revocation silently put a parked node back into service**, pushed to its
  host, and granted key material to a user who had never been on it. The whole
  visible response was *"olga revoked — link is dead"*.
- **Apply resurrected a retired node and granted every user on it** — and
  **revoking a friend reached the same door**, so revoking one person would have
  put the fleet back onto a node recorded as gone.
- **A push that landed and then failed** left the host authorising peers the
  database no longer held, silently.

## What was re-established on the wire, repeatedly

Real handshakes over the real internet; **25 MB each way for two friends
concurrently** (round 9), **10 MB each in ~3 s** (round 8); exit at
`45.151.69.107` while this machine is `178.208.65.94`; two friends at two `/32`s
with independent counters; **source-spoofing refused**; per-friend PSKs distinct
on both sides; DNS resolving end to end including with a **private** node
resolver, address- and port-scoped on the real kernel; the probe's cases honest;
a retired node refused by apply, probe and every fan-out.

**Throughput is not the tunnel's problem:** 13.73 s through it against 13.13 s
with no tunnel at all, from the same machine (round 7).

**And M15's uniqueness decision, proven at last:** two AmneziaWG instances on one
node binding two ports side by side — field-checklist item 3, which no stand can
show.

## The charter's one hard record

Verified on every walk: **zero `-j LOG` rules in either netfilter backend**,
`LOGLEVEL=off`, `nf_conntrack_acct=0`, Xray `access: none` and `sniffing: false`,
`dnsLog: false` on every rendered config, no uvicorn access line, no `/sub/` path
and no token or nickname anywhere in the control plane's or Caddy's logs. The
leaf's node container log stayed at **36 lines, written six days earlier**, while
a friend carried traffic.

**One residual, recorded rather than hidden:** a friend can reach the node's own
sshd through the tunnel (INPUT, not FORWARD), and **the host's** sshd then writes
their tunnel address into `auth.log`. hashi records nothing; OpenSSH does. It is
closable at apply time and is written up as needing its own milestone.

## The owner's hop was never at risk

**Nine walks, nine baselines, nine confirmations.** Its handshake and byte
counters were read immediately before and after every single walk and **moved
every time** — round 9: **+5,472 received, +3,872 sent**. No file in
`/opt/hashi/conf` was ever opened for writing; all three kept their original
sha256 and their `2026-09-09 08:41` timestamps throughout. **No container was
restarted** — all three were `Up 6 days` at the end.

Every walk brought up a throwaway interface on a free port with its own network,
created inside the existing container from `/dev/shm`, with exact inverse firewall
rules torn down in a `finally` written before the setup. **Every walk left the
leaf spotless.**

## Could not — needs the field

- **The Russian entry**, at all. It refuses this machine's key and takes keys from
  cloud metadata. **M16's own question is unobserved:** whether a friend's DNS
  lookup leaves the entry's own interface. *A person must run
  `ip route get <resolver>` and `awg show` on the entry while a friend resolves.*
- **The charter's first success criterion** — *surviving a mobile whitelist
  shutdown* — is a field observation on a real Russian mobile network **during a
  real shutdown**. Nothing in fourteen rounds touches it, and nothing should be
  read as covering it.
- **Apply was never run against the real leaf**, by design: the safety rule
  forbade it. Control-plane paths ran against disposable hosts with real sshd,
  real pushes and real digest comparison; the data plane was driven from the
  product's own rendered output.
- **No global IPv6 exists on either host**, so *"a friend still reaches the IPv6
  internet at speed"* is untested on hardware. Field-checklist item 22 has the
  observation.

## Still open, none blocking — see carry-over.md

Four clumsy findings from round 9, and the `auth.log` residual.
