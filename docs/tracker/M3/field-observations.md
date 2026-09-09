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
