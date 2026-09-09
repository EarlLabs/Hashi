# M3 — field observations

Things the two real hosts said while M3 was being built. Kept separate from the
milestone's own proof.

## Applying a node with no enabled transports renders an invalid compose file

Registering the leaf and pressing apply before enabling anything on it gives:

```
502  the node could not be configured and has been marked degraded:
     command failed (1): 'cd /opt/hashi && docker compose up -d --remove-orphans':
     services must be a mapping
```

and leaves the node `degraded`.

**M4 is working exactly as intended here** — that is the *real* error, surfaced
verbatim, where before tonight it would have been `409: a node cannot go from
draft to degraded`. The remaining problem is a different one: the situation is
not really a failure at all. A node with nothing enabled has nothing to serve,
and the honest answer is either "this node has no transports enabled — enable one
before applying" or a no-op, not a Docker parser error and a degraded node.

**Why it is worth writing down rather than fixing here.** It is a first-run
experience: register a node, press the obvious next button, get a message about
YAML mappings. It costs an operator confidence at exactly the moment they have
least of it. It belongs with the console work (M8/M9, where "apply" gets a
button) or with a small guard in the apply service — but it is neither M3's nor
worth widening M3 to carry.

Nothing about it blocks the hop: the leaf's end of a hop is created by the hop
itself, not by enabling a friend-facing transport.

---

# M3 — the invisible failure, measured on two real hosts before the fix

Taken 2026-09-09 on the live fleet: a Russian entry node and an Amsterdam leaf,
joined by a working AmneziaWG hop, with a real client connected as a friend.

## The hop is genuinely up

Handshake on both ends, seconds old, bytes moving both ways, `AllowedIPs` correct
and narrow:

```
ENTRY  interface: amneziawg  listening port: 51830
       peer …  allowed ips: 10.90.0.2/32   latest handshake: 9 seconds ago
LEAF   interface: amneziawg  listening port: 51830
       peer …  allowed ips: 10.90.0.1/32   latest handshake: 11 seconds ago
```

This is the first time in the project's history the hop has carried a handshake
between two real hosts. Everything the plan credits it with — keys minted, both
ends rendered, the entry-dials-leaf asymmetry, the deliberately narrow
`AllowedIPs` — is true.

## What the operator sees

```
nodes    entry-ru  state=active  detail=None
         leaf-nl   state=active  detail=None
health   entry  reachable=True healthy=True running=[amneziawg, vless-reality]
                drifted=[] stale=[]
         leaf   reachable=True healthy=True running=[amneziawg]
                drifted=[] stale=[]
hops     entry end: amneziawg purpose=relay-entry
         leaf  end: amneziawg purpose=relay-leaf
```

Two active nodes. Both healthy. No drift. No staleness — M1's new check is
satisfied, correctly, because the node **is** running exactly the config that was
pushed. A live hop with both ends present. There is no signal anywhere that
anything is wrong.

## Where the friend actually exits

```
158.160.67.252
```

**The entry node's own address. Russia.** The leaf in Amsterdam —
`45.151.69.107` — carries the friend's traffic nowhere at all.

## Why, in one line of rendered config

```
outbounds : [{"tag": "direct", "protocol": "freedom"}]
routing   : ABSENT
```

The entry's data plane has one outbound, straight out of its own interface, and
no routing section at all. `exit_address(leaf)` — the function that computes
precisely the address this config should be sending to — exists in `edge/relay.py`
and is called from nowhere but its own unit test.

## Why this is the worst failure in the plan

Every other defect found tonight announced itself: a container stuck `Created`, a
`409`, a `Permission denied`, a request that timed out. **This one produces a
working VPN.** The friend connects. Pages load. Throughput is fine. Every panel
field is green, and the one number that matters — the address the internet sees —
is the one number nothing in the product displays.

A friend in Russia using this to reach a blocked site would succeed, and would be
exiting from a Russian address the whole time. The topology that exists to prevent
exactly that is fully built, fully healthy, and not connected to anything.

**Nothing short of asking the internet what address it sees could have found
this**, which is why M3's acceptance cannot be discharged by reading a config,
and why decision 3's fail-closed rule matters: if the alternative to no exit is a
quiet Russian one, the quiet Russian one is worse.
