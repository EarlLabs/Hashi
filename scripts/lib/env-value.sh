# hashi — one value out of an env file, by name. Sourced, never executed.
#
# WHAT: one function, `env_value_of FILE KEY`, which prints the value `KEY` has in `FILE`
#       the way the readers of that file mean it, and prints nothing when it has none.
# WHY:  every script here is forbidden to `source` the env file — sourcing it RUNS it, so a
#       backtick in a password becomes a command on the host — and each one therefore grew
#       its own `sed` to lift a named value out. THREE OF THEM EXISTED AND THEY DID NOT
#       AGREE, which is the defect this file closes rather than a tidiness argument.
#
#       M28.12 round 1 found two of them in `scripts/panel-bootstrap.sh`: the weaker one
#       took the FIRST assignment instead of the last and left `\r` on the value, and it
#       gave the right answer on every file anybody had ever tested with. That is the whole
#       shape of the bug — a second parser is not wrong on the author's file, it is wrong on
#       an operator's, and nothing says so out loud. M28.13 found the third, in
#       `scripts/management-tunnel.sh`, where an env file saved by a Windows editor produced
#       `Endpoint = <host>^M:<port>^M`, `Address`, `ListenPort` and `MTU` with a carriage
#       return inside them — in this host's own `awg-mgmt.conf` AND in every device config
#       an operator pastes onto a phone. Every value was genuinely configured; the tunnel
#       simply never came up, from a file that looks correct in an editor that hides the
#       byte.
#
#       So: one implementation, and the same reason `scripts/lib/env-file-gate.sh` is a
#       library rather than a copy (M28.8). Two parsers are two things that drift, and they
#       drift silently.
#
#       WHAT IT IS NOT is the fence on WHICH names a script may read. `backup-run.sh` runs
#       unattended every fifteen minutes with its output going wherever cron sends it, and
#       enforces a three-name whitelist before it reads anything (M28.5); that whitelist
#       stays in `backup-run.sh`, in front of this call, because a fence belongs in the
#       script it constrains and a shared reader that knew about it would be one place for
#       every caller's fence to be got wrong at once.
# HOW:  `. "${REPO_ROOT}/scripts/lib/env-value.sh"`, then `env_value_of "${ENV_FILE}" KEY`.
#       The file is an argument rather than the caller's `ENV_FILE`, unlike the gate's
#       contract, because `panel-bootstrap.sh` compares the operator's file against
#       `.env.example` and needs both sides read by the same parser — reading one side with
#       a different one is exactly how the comparison was defeated before.
#
#       What it does to the value, and every part of it is a file somebody really saves:
#         - LAST assignment wins — an env file means the last, and so does compose reading
#           the same file, and correcting a value by adding a line under it is ordinary;
#         - `\r` goes, for a file edited on Windows;
#         - a trailing ` # comment` goes, because `.env.example` annotates keys that way;
#         - surrounding quotes come off, single or double;
#         - trailing whitespace goes.
#       It reads a named value and never prints one — the rule every caller is already held
#       to. A caller that needs to know only whether a key has ANY value asks a different
#       question and should keep asking it its own way: a stray `\r` reads as empty there,
#       which is the answer that question should give.

env_value_of() {
  sed -n "s/^[[:space:]]*$2[[:space:]]*=[[:space:]]*//p" "$1" \
    | tail -n 1 \
    | tr -d '\r' \
    | sed -e 's/[[:space:]]\{1,\}#.*$//' -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/" \
          -e 's/[[:space:]]*$//'
}
