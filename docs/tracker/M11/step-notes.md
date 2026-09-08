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

## From M11.2 — idempotency, and the boundaries section

**New operator-facing strings.** M11.3's runbook must match these, not invent
its own wording:

- `incoming was already denied by default`
- `outgoing was already allowed by default`
- `ufw logging was already off`
- `<spec> was already open`
- `an earlier apply already left /opt/hashi here — this run neither changed nor
  removed it`
- the closing line beginning `the provider's own firewall sits in front of this
  host and outside this script's reach`

All M11.1 strings above are unchanged.

**Two named shell helpers** now exist and are the way to ask these questions:
`key_is_authorised` and `ufw_default INPUT|OUTPUT`.

**The regex anchor moved.** `as_root ufw logging off` is now *indented* inside
its guard, so the ordering test anchors on `^\s*as_root ufw logging off$`. A
later step copying M11.1's exact `^…$` regex will fail. Command-position
anchoring still holds — that rule is intact, only the whitespace changed.

**Guardedness is checked as indentation.**
`test_no_ufw_command_that_rewrites_its_config_runs_unconditionally` reads a line
at column zero as a line that runs every time. That is the pattern to reuse for
any new "must not run unconditionally" rule.

**One guard's failure direction is load-bearing.** The `ufw logging off` guard
reads `LOGLEVEL` from `/etc/ufw/ufw.conf`, and on a missing or unreadable config
it falls through to **running the command**. It must keep failing in that
direction: a guard that failed the other way would leave logging on, which is
the charter violation this milestone exists to prevent. Verified by review, not
assumed.

**`LC_ALL=C` is forced on exactly one command** (`ufw allow`), not exported. An
`export LC_ALL=C` at the top would also change how docker's output parses. If a
translated ufw ever defeats the match the cost is one wrong word, never a wrong
rule set.

**The SSH-port `ufw allow` loop is deliberately unguarded**, unlike the
data-plane loop. Its line states the resulting *state*, not an action, so it is
true on run one and run ten. There is a comment saying so; do not "fix" it.

**Red-first was proved, not claimed.** All ten new tests were run against
`git show ce44a7c:scripts/node-bootstrap.sh` and all ten went red — by the
implementer and again, independently, by the reviewer.

## From M11.3 — the runbook's leaf section

**Two placeholder conventions, on purpose.** CAPITALS inside runnable fences
(`NODE=USER@THE_NEW_HOST`); angle brackets in prose and in sample *output*,
which are transcripts of what the script prints rather than commands. A test
enforces the first —
`test_every_command_in_the_leaf_section_survives_being_pasted`. Anything added
to that section as a pasteable command uses capitals.

**Anti-drift is now mechanical.**
`test_the_leaf_section_quotes_the_script_rather_than_paraphrasing_it` asserts a
list of strings appears **verbatim in both** `scripts/node-bootstrap.sh` and the
runbook. Changing a `say` line or a flag in one now requires the same edit in
the other. Verified load-bearing: the reviewer changed one string in the script
alone and watched it go red.

**The section fixture anchors on `^## Preparing a leaf\n`** up to the next
`^## `. Renaming that heading breaks four tests, and Shape B/C and "What every
box must already have" cross-reference it by name.

**Port literals are checked against an explicit `KNOWN_PORTS` tuple**, not a
bare `\d` regex — the runbook legitimately contains the number 5840, a byte
count.

## From M11.4 — what the real hosts said

Run on two hosts of deliberately different shape. Both were already prepared by
somebody else, which is the normal case and not the exceptional one.

**Entry host** — non-root with passwordless sudo, docker present, `ufw`
inactive. First run authorised the key, opened the requested ports, brought the
firewall up with logging already off. Second run, same arguments: **every
observed byte identical** — `authorized_keys`, `/etc/ufw/ufw.conf`,
`/etc/default/ufw`, `/etc/ufw/user.rules` and the rule set, *mtimes included*.
Not "no visible change": no write at all. That is the M11.2 work paying off.

**Leaf host** — root, `ufw` already active carrying its own rules, and hashi
already applied to it. Its pre-existing `80/tcp` and `443/tcp` rules survived,
all four running containers survived, and the honesty line M11.2 added fired
exactly where it was designed to: `an earlier apply already left /opt/hashi here
— this run neither changed nor removed it`.

**A field condition worth knowing about, and it nearly bit.** The entry host had
**no `~/.ssh/authorized_keys` at all** and was still reachable, because its sshd
uses an `AuthorizedKeysCommand` fed from cloud metadata. The script's key
install works there only because that sshd *also* sets `AuthorizedKeysFile`, so
both sources are consulted. On a host configured with `AuthorizedKeysCommand`
**alone**, writing `authorized_keys` would succeed and the key still would not
authenticate — and the script's own verification, which greps the file it just
wrote, would report `ready`. Worth a check against `sshd -T` if this is ever
seen in the wild. Recorded in `carry-over.md`.
