# M11 — carry-over

Non-blocking findings left open, with the reason each was left. Read them as
BACKGROUND: they tell you what is known-wrong so you do not mistake it for the
intended design. Do not fix them as part of another step.

## From review

- **Medium — angle-bracket placeholders elsewhere in `docs/deploy/runbook.md`**
  (`:38`, `git clone <this repo>`, `<your panel host>`). Inside a runnable fence
  these are shell redirections, so the line dies on an error naming neither the
  command nor the unfilled field. **Fixed for the leaf section only**; the
  pre-existing instances were left because they are a separate class from the
  two defects M11.3 was asked to fix, and widening the diff would have put an
  unreviewed change into an otherwise clean step. The reviewer agreed with that
  scoping. De-literalising the rest of the runbook is a candidate follow-up.

## From the field, not from review

- **`AuthorizedKeysCommand`-only hosts would defeat the script's key check.**
  See the M11.4 notes for the mechanism. The script writes
  `~/.ssh/authorized_keys` and then verifies by reading back the file it just
  wrote, which is true regardless of whether sshd consults that file at all. On
  the two hosts this run touched, sshd sets `AuthorizedKeysFile` as well, so the
  key genuinely works — verified by authenticating with it, not by reading the
  file. Left open because no host in the fleet currently has that configuration
  and inventing the check without one to test it against would be guessing.

- **Pre-existing IP and port literals elsewhere in the runbook** — `172.17.0.1`,
  and the port numbers in the Shape A/B/C prose and the Shape C table. Not
  inside a `ufw allow`/`ufw enable` line, so outside the two named defects. The
  docker bridge address in particular is arguably not fleet topology. Flagged
  because `CLAUDE.md`'s rule is written without that exception.

- **The two dead volumes on the entry host** — `zhurabli_backend_app_logs` and
  `zhurabli_backend_postgres_data`. Deliberately kept when their compose project
  was removed: "nothing else" was satisfied without them, and a volume is the
  one thing there that could not be recreated. One line to remove when the owner
  says so.

- **22 residual `UFW …` records on the leaf**, in `/var/log/syslog`,
  `/var/log/kern.log` and the kernel journal. They predate this run; `ufw.log`
  itself is gone and logging is off on both hosts, so nothing new is written.
  Removing them was attempted and refused by the sandbox, correctly — selective
  editing of system logs is indistinguishable from anti-forensics. Needs the
  owner's hand or their explicit say-so.
