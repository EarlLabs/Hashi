# M11 — step notes

Conventions established here. They bind later steps, and later milestones in
this codebase, until something supersedes them. Follow them; do not relitigate.

## From M11.1 — `scripts/node-bootstrap.sh`

**The script's contract.** M11.2 and M11.3 match this; they do not change it.

- Flags: `--authorized-key`, `--authorized-key-file`, `--user`,
  `--port PORT[/PROTO]` (repeatable), `--ssh-port`, `-h`/`--help`.
- An unknown argument exits **2** with usage on stderr.
- A refusal exits **1**, prefixed `node-bootstrap: `.
- Progress lines are `==> …`.
- The header enumerates **five** properties the script holds itself to:
  idempotent; not one interactive question; verifies before reporting success;
  no hashi code, state or private key; never starts recording connections.
  M11.2's "what it does not do" — the provider security group — is deliberately
  *absent* from that list. Adding it is M11.2's job.

**Wording a person will see, and acceptance judges these strings:**

- `ready: docker <ver>, key authorised, firewall up, logging off`
- `register it in the panel with ssh_user <user> and ssh_port <port>`
- `nothing of hashi's was installed here — the control plane creates /opt/hashi
  itself when you apply`
- on a re-run: `the firewall was already up — its existing rules were kept` and
  `the control plane's key is already authorised for <user>`

**No port literal, anywhere.** Data-plane ports arrive as repeatable `--port`.
The management port is detected from `$SSH_CONNECTION` unioned with `sshd -T`,
with `--ssh-port` as an override; if neither source answers, the script
**refuses** rather than enabling a firewall it cannot prove leaves a way back in.
Keep that refusal — it is the difference between a locked host and a locked-out
one.

**It is self-contained on purpose** so it can be piped (`ssh host 'bash -s -- …'
< script`) instead of copied. That is what keeps repository code off a node.

## Test conventions — `tests/infra/test_node_bootstrap_script.py`

- **The test reads the script; it never runs it.** Module-scoped `script`
  fixture over `SCRIPT.read_text()`, exactly like
  `test_panel_bootstrap_script.py`. No host, no chdir, instant.
- **Anchor regexes on command position, not prose.** The script's own comments
  and refusal messages contain the words `sudo`, `ufw enable`, `ufw logging`,
  `/var/log/…` and `ssh-keygen`. Every assertion anchors on `as_root …` or `^…`
  for that reason. Reuse that; do not weaken it.
- The `ufw logging off` assertion is a **position** check
  (`logging_off.start() < enable.start()`), not a presence check. Reversing the
  two lines in the script turns it red. Any later ordering rule gets the same
  treatment.

## Shell traps hit here, so the next step does not hit them again

- **Never put a backtick in a double-quoted message** — it is command
  substitution. Use `sudo(1)` phrasing instead.
- **Never `| head -1 |` inside a `set -o pipefail` check.** The SIGPIPE reads as
  failure and the firewall then silently never comes up. Use
  `grep '^Status: inactive'` or `awk 'NR==1'`.
- Array expansions use the empty-safe `${arr[@]+"${arr[@]}"}` idiom under
  `set -u`.

## Two decisions taken here that a later step should know were deliberate

- **The script deletes `/var/log/ufw.log*`** — the only destructive act in it,
  and it implements decision 5. The comment beside it says, and the run output
  repeats, that this sweep is **not sufficient** on a host that has already
  logged: rsyslog, `kern.log` and the journal hold copies. Nobody may read that
  line as "the host is now clean". The real protection is that logging is turned
  off *before* the firewall ever comes up, so a host prepared by this script
  never writes the record at all.
- **`make node-bootstrap` runs `ssh`, which no other Make target does.** The
  infra rulebook's "an operation without a Make target is a bug in this zone"
  outweighed the local idiom. It requires `NODE=user@host` on the command line
  and defaults nothing, so no address enters the repository. No agent should run
  it.

## Known-stale, and not this step's to fix

`docs/deploy/runbook.md:141` still hardcodes `ufw allow 22/80/443/51820` and
`ufw enable` **without** `ufw logging off`. That is M11.3 / M6.2 territory.
