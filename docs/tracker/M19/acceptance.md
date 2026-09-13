# M19 — acceptance: **good**

One round. Walked by an independent agent with **no sight of the diff**, 46
actions, ~30 minutes. **Both "done when" lines passed. Nothing blocked.**

## How the verdict was reached — this is the part worth keeping

The owner's acceptance line said: *"On a host whose sshd takes keys only from a
command, run the script. It must not say `ready`. **If no such host is available,
say so rather than passing it.**"*

**The walker built the host rather than reasoning about it.** Sixteen shapes, each
a `debian:13-slim` container running a **real `openssh-server`** with its own host
key from `ssh-keygen -A`, a real docker daemon, real `ufw`, and the real
`scripts/node-bootstrap.sh` bind-mounted read-only.

**And then it did the thing that makes this acceptance trustworthy:** after every
run it **attempted a real `ssh` login with the same key.** So every `ready` and
every refusal is corroborated against reality rather than taken on the script's
word.

That is this run's own signature lesson — *a verification that cannot fail is not
a verification* — applied by the acceptance agent **to itself**. It is the right
standard for a milestone whose entire subject is a check that could not fail.

| shapes | outcome |
|---|---|
| **6 broken** — `AuthorizedKeysFile /etc/ssh/authorized_keys/%u`, `AuthorizedKeysFile none` alone, `AuthorizedKeysFile none` + `AuthorizedKeysCommand`, `PubkeyAuthentication no`, `PermitRootLogin no`, `AuthenticationMethods password`, `sshd -T` unavailable | **refused**, each with a **denied real login** |
| **4 working** — stock config as root, `PermitRootLogin prohibit-password`, a non-root account under sudo, **`AuthorizedKeysCommand` *alongside* `AuthorizedKeysFile`** | **accepted**, each with a real **`LOGIN-OK`** |

**That last accept-case is the one that matters most:** it is the real entry
host's shape. Distinguishing it from a metadata-*only* host is the whole point of
M19.2, and the check does.

## Done when

**1 — a host missing a kernel precondition is told so by name, before it is
registered as a working node: passed.**

- `ip_forward=0` → exit 1: *"net.ipv4.ip_forward is '0' on this host and it has
  to be 1, or the kernel will not move one packet from a tunnel out to the
  internet."*
- `ip_forward` unreadable → exit 1: *"…could not be read on this host, so this run
  cannot tell you whether a tunnel here would carry anything off the node."*
  **"Could not check" does not read as "checked."**
- `rp_filter=1` → **named with its consequence, not refused**: *"That is fine for
  a LEAF and it breaks an ENTRY node… This run does not refuse it, because nothing
  tells this script which role you will register this host in."*

**The split is right:** `ip_forward` breaks every role, so it refuses;
`rp_filter` breaks only an entry, whose role the script cannot know, so it speaks.

Every refusal lands **before** `==> register it in the panel with ssh_user root
and ssh_port 22` — the only line that tells the operator to register. The panel
closes the loop: its ssh-user help reads *"The account scripts/node-bootstrap.sh
told you to register — it prints that line when it finishes preparing the host."*

`ip` is declared: `WG_QUICK → ['awg-quick', 'ip', 'iptables']`,
`WG_QUICK_PLAIN → ['ip', 'iptables', 'wg-quick']`.

**2 — cannot report `ready` for a key that will not authenticate: passed.**

On the metadata-shaped host, exit 1:

> node-bootstrap: sshd on this host takes its keys from a command —
> '/usr/local/sbin/fetch-metadata-keys' — and not from
> /root/.ssh/authorized_keys, so the key this run installed would never be
> offered to it and the control plane could not log in.

Real `ssh` on that same host: `Permission denied (publickey,password)`, exit 255.
**The sentence is true.**

## Charter

The key is **never echoed** — a private key handed in by mistake is refused
without printing it. **No IP, domain, country or port** appears in any `==>` or
`node-bootstrap:` line; the ssh port is detected and the script **refuses rather
than assuming 22** when it cannot be. Nothing resembling a connection log.

## Probes

Two concurrent runs → both exit 0, **one** line in `authorized_keys`. Rerun →
`already` everywhere, exit 0, nothing changed. **Nothing exited silently** — the
worst was 54 bytes of bash error, and the unknown-flag case exits 2 with the full
usage. *(M18's acceptance found this same script exiting with zero bytes on both
streams; that shape is gone.)*

## Works, but awkward — two were promoted and fixed, five recorded

**Promoted to must-fix, because one is a security defect:**

1. **A two-line `--authorized-key` installs the extra key and leaves it there.**
   The script printed *"authorised the control plane's key for root"*, wrote
   `ssh-ed25519 AAAAsmuggled intruder@elsewhere` into `/root/.ssh/authorized_keys`,
   and **then** refused correctly. The operator is stopped — but is **never told a
   foreign key is now authorised for root**, and nothing removes it. **Reachable
   by accident**, not only by malice: pasting a file with two keys, or a key with
   a trailing line.
2. **A working host is turned away with no way through.** `sshd -T` is asked
   without `-C`, so it reports the pre-`Match` configuration. With
   `PubkeyAuthentication no` plus `Match User root / PubkeyAuthentication yes`,
   **the real login succeeds** but the script refuses — and there is no override,
   so the host can never produce the line the panel tells the operator to register
   from. **The convention this milestone established is that a check turning away
   a working host is the same defect as one passing a broken host.**

**Recorded in carry-over.md:** `--authorized-key` as the last token dies with
`$2: unbound variable`; `--ssh-port 0` leaks ufw's bare `ERROR: Bad port` while
`--port 0/udp` is caught properly; argument and kernel checks run **after** the
key is installed and the firewall configured; raw `ufw` output leaks and run 2
repeats itself; a 1000-character `--user` is echoed twice.

## Could not — needs the field

**The field observations behind both kernel rules.** That a tunnel actually goes
dark at `ip_forward=0`, and that a two-hop starts carrying when `rp_filter` is
loosened, need the real Russian entry host. **Not covered, and not written as
"good."** Neither live host was touched.

The metadata fetcher behind `AuthorizedKeysCommand` was a stub returning no keys,
so a real cloud sshd may differ. The interruption probe is inconclusive: on a
prepared host the script finishes in under 0.25 s, and the only slow phase — the
container-runtime install — was unreachable from the stand.

## One hygiene note, recorded against the orchestrator

The walker observed *"the repo moved under me at 18:11 and 18:12 — two commits
from another session, touching `docs/PLAN.md` only."* **That was the
orchestrator**, committing the M20 and M23 plan changes after saying it would
wait for this walk to finish. The walker checked and confirmed
`scripts/node-bootstrap.sh` and `edge/` did not move between its first and last
run, so the verdict is unaffected — but the rule was broken, and it is the same
rule whose breach cost this run two recoveries earlier.
