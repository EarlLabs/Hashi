# hashi — reaching a host over SSH from the operator's machine. Sourced, never executed.
#
# WHAT: `remote_open` (one multiplexed SSH connection to a host, named so a caller can
#       hold two), `on` / `on_as_root` (run a command line there), `remote_root_access`,
#       `remote_close_all`, `host_part_of`,
#       `resolve_ipv4` (the IPv4 addresses a name has, from this machine's resolver) and
#       `q` (shell-quote words for a remote command line).
# WHY:  scripts/restore-panel.sh and scripts/restore-node.sh both drive a fresh host from
#       the operator's laptop, dozens of commands each. One connection carries all of them
#       — a rebuild is often done over a phone tether, where every new handshake is
#       seconds — and the quoting rule lives in one place: every word that reaches a
#       remote shell goes through `q`, so a value with a space or a quote in it is a value
#       and never a second command.
# HOW:  `remote_open node root@203.0.113.7 22`, then `on node "$(q ls -l /opt)"`. A caller
#       that needs two hosts opens two names; `remote_close_all` belongs in its EXIT trap.

# The options every connection here uses. BatchMode: nothing in a rebuild may stop on a
# password prompt over a pipe. accept-new: a fresh host's key is unknown by definition and
# is recorded on first contact — but a CHANGED key for a known host is still refused, which
# is ssh's own protection and stays on.
REMOTE_SSH_OPTS=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new
                 -o ConnectTimeout=20 -o ServerAliveInterval=15 -o ServerAliveCountMax=8)

REMOTE_CONTROL_DIR=""

q() {
  local word out=""
  for word in "$@"; do
    out="${out}${out:+ }$(printf '%q' "${word}")"
  done
  printf '%s' "${out}"
}

host_part_of() {
  local target="${1#*@}"
  target="${target#[}"
  printf '%s' "${target%]}"
}

# IPv4 only, sorted and unique, one per line; empty — and exit 0 — when the name does not
# resolve. getent first (it asks the resolver every program on this machine uses), python3
# where there is no getent. getent's own "no such name" is exit 2, which under `pipefail`
# in a caller's `$(…)` would end that caller's run with no sentence; it is an answer here.
resolve_ipv4() {
  local name="$1"
  if command -v getent >/dev/null 2>&1; then
    { getent ahostsv4 "${name}" 2>/dev/null || true; } | awk '{print $1}' | sort -u
  elif command -v python3 >/dev/null 2>&1; then
    python3 -I -c 'import socket,sys
try:
    print("\n".join(sorted({a[4][0] for a in socket.getaddrinfo(sys.argv[1], None, socket.AF_INET)})))
except OSError:
    pass' "${name}"
  fi
}

# `ssh` to the named connection. The control socket lives in a private directory made
# for this run, so nothing else on this machine can ride the session.
_ssh_to() {
  local name="$1"; shift
  local target_var="REMOTE_TARGET_${name}" port_var="REMOTE_PORT_${name}"
  local port_opt=()
  [ -n "${!port_var:-}" ] && port_opt=(-p "${!port_var}")
  ssh "${REMOTE_SSH_OPTS[@]}" -o ControlMaster=auto \
      -o "ControlPath=${REMOTE_CONTROL_DIR}/${name}" -o ControlPersist=120 \
      "${port_opt[@]}" "${!target_var}" "$@"
}

remote_close_all() {
  local socket
  [ -n "${REMOTE_CONTROL_DIR}" ] && [ -d "${REMOTE_CONTROL_DIR}" ] || return 0
  for socket in "${REMOTE_CONTROL_DIR}"/*; do
    [ -S "${socket}" ] || continue
    ssh -o "ControlPath=${socket}" -O exit placeholder >/dev/null 2>&1 || true
  done
  rm -rf "${REMOTE_CONTROL_DIR}"
}

# remote_open NAME user@host [port] — and the first command over it, so an unreachable
# host is a sentence here rather than a failure three steps later.
remote_open() {
  local name="$1" target="$2" port="${3:-}"
  if [ -z "${REMOTE_CONTROL_DIR}" ]; then
    REMOTE_CONTROL_DIR="$(mktemp -d "${TMPDIR:-/tmp}/hashi-ssh.XXXXXX")"
    chmod 700 "${REMOTE_CONTROL_DIR}"
  fi
  printf -v "REMOTE_TARGET_${name}" '%s' "${target}"
  printf -v "REMOTE_PORT_${name}" '%s' "${port}"
  _ssh_to "${name}" true </dev/null
}

# on NAME 'command line' — the line is run by the remote login shell. Every value in it
# must already have gone through `q`.
on() {
  local name="$1"; shift
  _ssh_to "${name}" "$*"
}

# The same as root: directly when the account is root, through `sudo -n` otherwise —
# never a sudo that can prompt, because there is no terminal to answer it.
on_as_root() {
  local name="$1"; shift
  local root_var="REMOTE_IS_ROOT_${name}"
  if [ "${!root_var:-}" = "yes" ]; then
    _ssh_to "${name}" "$*"
  else
    _ssh_to "${name}" "sudo -n sh -c $(q "$*")"
  fi
}

# Whether the account is root, or has a sudo that will not prompt. Sets REMOTE_IS_ROOT_<name>.
# Returns 1 (and the caller says so) when it has neither.
remote_root_access() {
  local name="$1" uid
  uid="$(on "${name}" 'id -u' </dev/null | tr -d '[:space:]')"
  if [ "${uid}" = "0" ]; then
    printf -v "REMOTE_IS_ROOT_${name}" '%s' yes
    return 0
  fi
  printf -v "REMOTE_IS_ROOT_${name}" '%s' no
  on "${name}" 'sudo -n true' </dev/null >/dev/null 2>&1
}
