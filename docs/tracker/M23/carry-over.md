# M23 — carry-over

## Counts

| | Blocking / HIGH | clumsy |
|---|---|---|
| 9 real-host walks | **13, all closed** | 14 |
| 14 fix rounds | — | — |

**Nothing blocking or HIGH is open.** Round 9 came back clean, which is what ended
the loop.

## Open, none blocking

**1 · An integration cannot tell "already revoked, fine" from "still served
somewhere".** The retry body is byte-identical (bar `friend_id`) either way,
`complete` never returns to `true` — **not even after the operator repairs and
re-applies the node** — and no endpoint answers *"is this person still served
anywhere?"*. The **panel** answers it in a banner; an integration has nothing.

*This is the honest end of round 6's constraint*: `friends.revoke` deletes the
credential rows, which is what makes revocation total, so after the first call
nothing records which nodes that person was on. Closing it properly means keeping
a record of where a withdrawal still needs to land — **which is a schema decision,
and arguably one that conflicts with "records must be absent".**

**2 · Users says `3 / 3 transports served` while Nodes says that node is
`1 / 3 drifted`** — and the friend's link is built from the optimistic reading.
Two screens, two truths about the same fleet.

**3 · The *rotate keys* confirm dialog offers "apply the node once it can be
reached" on a retired node**, where apply is refused permanently. Round 14's fix
reached the config cell and three other doors; this dialog was the fifth.
`apply.cannot_serve_again(state)` is the predicate it should ask.

**4 · From inside a friend's tunnel the leaf's own addresses answer**
(`10.90.0.2`, `10.66.0.1`), while the entry's `10.90.0.1` is correctly
unreachable. The rendered policy is **FORWARD-only**, so INPUT is outside its
scope — the recorded boundary, not a new class.

*The walker deliberately did not dial the leaf's sshd to confirm it: **that would
create the one record this project forbids.***

## The `auth.log` residual — closable, and it needs its own milestone

A friend reaching the node's own sshd through the tunnel puts **their tunnel
address into the host's `auth.log`**. hashi records nothing — zero `-j LOG` rules,
`LOGLEVEL=off`, `nf_conntrack_acct=0`, Xray `access: none`. **OpenSSH does.**

**Round 13 judged it out of scope for `scripts/node-bootstrap.sh` on three
grounds; round 8 overturned one of them and round 14 recorded the correction.**
What stands: that script never closes anything (runs are additive, and a rule
withdrawing access could withdraw the session running it), and it is not host
hardening. **What does not stand:** *"it cannot tell a leaf from an entry"* — the
control plane knows the role at **apply** time, and already renders per-interface
rules that live and die with the interface.

**So the residual is real and closable, just not where it was first looked for.**
A milestone must decide: the chain (INPUT, against the FORWARD rules that function
writes, and what `PostDown` removes); the value (the SSH port travels into the
render as data, or the rule names no port at all); and what a node may legitimately
serve on its own tunnel address — **M16's resolver exception would have to be
mirrored into INPUT.**

## Two deliberate gaps, argued and recorded in the code

**`::/96` (IPv4-compatible) is not refused.** Round 13 measured it, round 8
confirmed and sharpened the argument, and it now lives in `edge/egress.py`'s
header: *the decisive test is not whether a responder bound to `::7f00:1` answers,
but whether `::7f00:1` reaches what `127.0.0.1` is serving. It does not. A node
the product sets up carries only `::1` on `lo`. **It is a separate address, not a
spelling.***

**`192.88.99.0/24` is not refused**, and round 13 showed why there is no asymmetry
to explain: `2002::/16` is refused because the registry says a 6to4 address is
**not globally reachable**; `192.88.99.0/24` is not refused because the registry
says it **is**. The list has never tracked the registry — it tracks *not globally
reachable, or a spelling of something that is not* — and round 9's own test had
always asserted exactly that.

## The lesson worth keeping

The last four walks stopped finding **new classes** of defect and started finding
**the same defect surviving in a surface the fix did not reach**: revoke-twice
fixed in the panel, missed in the API; the retired-node remedy fixed in the revoke
dialog, missed in the Users banner, then the config cell, then the rotate dialog;
the hop refusal fixed for kernel tunnels, then the entry's proxy, then the leaf's,
then IPv6, then NAT64.

**The countermeasure that worked was a shared predicate, not a shared sentence.**
`apply.cannot_serve_again(state)` now has four doors asking it, and a fifth cannot
answer differently without being told to. **A new refusal should extend the
predicate, never compare a state.**
