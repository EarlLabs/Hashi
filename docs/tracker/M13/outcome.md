# M13 — outcome

**Steps:** M13.1, M13.2, M13.3 — built together, one commit per zone, reviewed
in **one round, clean, no findings at any severity**.

**Shape chosen: one.** `scripts/node-bootstrap.sh` creates `/opt/hashi` — empty,
`0700`, owned by the account it puts in the `docker` group and tells the operator
to register. `edge` acquires no notion of privilege.

**Acceptance: discharged by field observation.** M13's scenario needs a real
non-root host, which the disposable stand cannot provide — the same rule the plan
already applies to M1, M2, M3 and M7. It was walked on the entry host and the
evidence is in `field-proof.md`: apply returns 200, the node is `active` and
`healthy`, the data-plane container is `Up`, and the config file is on disk owned
by the non-root account. **Stated plainly: this was verified by the run's
orchestrator, not by an independent acceptance agent.** That is weaker than the
stand-walked milestones — the orchestrator is not the author, since implementer
agents wrote every line, but it is not a fresh pair of eyes either.

**Gate at close:** `make test` green — 169 control, 139 edge (3 skipped), 96
infra.

## The result worth remembering

The apply succeeded on that host while its control plane was **still running the
pre-M13 library**. The script alone made a non-root node work. That is shape one's
central claim demonstrated rather than argued: the privilege boundary belongs to
host preparation, and `edge` never has to learn about `sudo`. The library change
that shipped alongside is not what fixed it — it is what turns a *missing*
directory into a sentence naming the repair instead of a `Permission denied` from
`mkdir`.

## What M13.2 actually pins

Not a shared string. `tests/infra/test_node_bootstrap_agrees_with_the_control_plane.py`
reads the shell script as text and *imports* `node_stack`, then asserts they agree
about: the directory created, its owner, its mode, that the library never
escalates privilege, and that it writes nowhere else. Six mutations were proven
red **one side changed at a time**, including the M13 bug itself — the script
creating the directory as root while still advertising a non-root `ssh_user`.
Three were reproduced independently by the reviewer.
