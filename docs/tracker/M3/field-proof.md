# M3 — the two-hop, proven on two real hosts, 2026-09-09

The same fleet, the same client, the same measurement as
`field-observations.md`. Only the code changed between them.

## The measurement

| | before M3 | after M3 |
|---|---|---|
| what the internet sees when a friend dials the Russian entry node | **the entry's own address** | **the leaf's address, in Amsterdam** |

A real client, built from the friend's own subscription document, in a throwaway
container on neither host, removed afterwards. `www.wikipedia.org` returned
`HTTP 200`, **119 573 bytes**, through friend → entry (Russia) → AmneziaWG hop →
leaf (Amsterdam) → internet.

## The kernel path, visible on the entry node itself

Both directions, same host, same moment — this is the mechanism, without a client
in the picture at all:

```
curl --interface <the hop's near address>   ->  the leaf's address    (Amsterdam)
curl                                        ->  the entry's address   (Russia)
```

## The control plane's own session survived, which was the risk

The entry's `AllowedIPs` had to widen to `0.0.0.0/0` — WireGuard only encrypts to
a peer whose `AllowedIPs` covers the destination, so a `/32` entry can send
nothing but pings. The protection is a **different switch**: `Table = off`, plus
source-based policy routing. Measured on the host afterwards:

```
ip rule    32765:  from <hop near address> lookup 51821
table 51821        default dev <hop interface>
main table         default via <the host's own gateway> dev eth0    ← UNCHANGED
```

Only traffic already sourced from the tunnel's own address goes into the hop. The
node's own outbound traffic — the SSH session the control plane manages it over —
is untouched, and SSH stayed up across the apply.

## Fail closed — decision 3, holding

The leaf's data plane was stopped, so the hop went dead beneath a friend who was
mid-session:

| | |
|---|---|
| attempt 1 | connection timed out |
| attempt 2 | connection timed out |
| a Russian exit address | **never, at any point** |

Then the leaf's data plane was started again:

| | |
|---|---|
| exit address | back to the leaf's, in Amsterdam |

The friend loses their exit and gets nothing, which is exactly what decision 3
chose and exactly what the alternative would have hidden.

## One correction this milestone made to the plan

The plan said to target `exit_address(leaf)` — the leaf's in-tunnel address — as
the entry's outbound destination. **Nothing listens there.** A leaf runs one hop
end and no proxy, so its in-tunnel address is not dialable; what a leaf offers is
a *route*, not a service. The entry instead opens ordinary connections **bound to
its own end of the tunnel** (`sendThrough`), and the kernel carries them. The
function survives with the same shape and the other argument: `exit_via(entry)`.

Worth stating because the plan's version would have rendered a config that looked
correct, passed review, and connected to nothing — the same failure mode as the
milestone it was written to fix.

## Why nothing but this could have settled it

Before M3 the fleet reported two `active` nodes, both `healthy: true`, `drifted:
[]`, `stale: []`, and a hop with both ends and a nine-second-old handshake —
while every friend exited in Russia. Every signal the product has was green and
the one number that mattered was not among them. Reading the rendered config
would have shown one `freedom` outbound and no routing section, which is the
cause but not the proof; the proof is the address, and only the internet can say
it.
