# M19 — carry-over

## Counts

| source | Blocking | Medium | Low |
|---|---|---|---|
| M19 review (1 strict reviewer, ran the gate itself) | 0 | 1 | 4 |
| acceptance (1 round, verdict **good**) | 0 | — | 7 awkward |

**Nothing blocking was ever open in this milestone.** The review's single Medium
was M19's own second done-when and was fixed; two of acceptance's seven were
promoted to must-fix and fixed; five are recorded below.

## What the review caught that 26 mutations did not

The implementer built the check, proved it against a real OpenSSH 9.6p1, and ran
**26 mutations** — and still shipped a path where the script printed **`ready`**
for a key that cannot log in. **Reproduced by the reviewer:** a config of just
`PubkeyAuthentication no` gave *"sshd reads /root/.ssh/authorized_keys, so a key
installed there is one it will consult"* → `ready`, exit 0.

**The check was not wrong; it answered a slightly different question than the
done-when asked** — *which file* sshd reads, rather than whether a key
authenticates at all. That is the fourth time in this run a step passed its own
gate, its own mutations and its own author's judgement, and was caught by someone
reading it fresh.

## The convention this milestone established — keep it

**Accept-cases are mandatory beside every refusal.** A check that turns away a
working host is treated as the same defect as one that passes a broken one.

It earned itself immediately: `PermitRootLogin prohibit-password` **permits** key
auth, and real `sshd -T` prints it as **`without-password`**, which is OpenSSH's
compiled default — so a check refusing on the string it actually sees would have
turned away a stock Debian host.

## Still open, recorded rather than fixed

1. **`--authorized-key` as the last token** dies with `line 181: $2: unbound
   variable` instead of a refusal.
2. **`--ssh-port 0`** leaks ufw's bare `ERROR: Bad port`, while `--port 0/udp` is
   caught properly. Inconsistent.
3. **Argument and kernel checks run after the key is installed**, `/opt/hashi` is
   created and the firewall configured. An invalid argument should be caught
   before the script touches the host at all. *(Attempted in the tightening
   round — see that round's report for whether it landed.)*
4. **Raw `ufw` output leaks** to the operator, and run 2 repeats itself.
5. **A 1000-character `--user`** is echoed twice in the refusal.

## Needs the field — the two observations no stand can make

Both kernel rules are asserted from documented kernel semantics and from what the
two field hosts happen to ship. **Neither consequence has been observed:**

- that a tunnel actually **goes dark** at `ip_forward=0`;
- that a two-hop **starts carrying** when `rp_filter` is loosened from strict.

Both need the real Russian entry host, which refuses this machine's key. **M23
covers what it can from the leaf side; the entry half stays open.**

## A note on `sshd -T` that a later change will need

`sshd -T` is asked **once**, at section 5, and read twice. A host that reloads
sshd mid-run would be described by the stale answer. Not a defect today — nothing
in the script reloads sshd — but any future step that does must re-ask.

The `Match` limitation is named in header item G rather than closed, because
closing it needs `sshd -T -C addr=…` and **an address in this file would be a
hard-rule violation.**
