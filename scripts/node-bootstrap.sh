#!/usr/bin/env bash
# WHAT: prepares a bare host to be driven as a hashi node — a container runtime, the one
#       public key the control plane authenticates with, the host firewall, and one empty
#       directory for the control plane to write into, owned by the account it logs in as.
#       Nothing else, and in particular no hashi code and no hashi state.
# WHY:  `edge/bootstrap/node_stack.py` refuses a host that has no docker, and says so in
#       as many words: hashi configures upstream data-plane containers and does not
#       install a container runtime for you. That is the right boundary for the library
#       and it left a hole in the product — `scripts/panel-bootstrap.sh` brings a control
#       plane up in one command, and a leaf had no equivalent, so every leaf host so far
#       was prepared by hand.
#
#       A hand-prepared host is a host you cannot rebuild at three in the morning, which
#       is exactly when you rebuild one. The charter's "destroy and replace in ten
#       minutes" is a claim about a script; this is that script.
# HOW:  on the host itself:
#
#         ./scripts/node-bootstrap.sh --authorized-key "ssh-ed25519 AAAA... hashi-control" \
#                                     --port <number>/udp
#
#       or, from the machine that holds this repository, without copying it anywhere:
#
#         make node-bootstrap NODE=user@host ARGS="--authorized-key '<public key>' --port <number>/udp"
#
#       which is `ssh <host> 'bash -s -- <args>' < scripts/node-bootstrap.sh`. The script
#       is therefore SELF-CONTAINED: it sources nothing, reads no file from this
#       repository, and never assumes the repository is on the host. It also never reads
#       stdin — when it is piped in, stdin *is* the script.
#
# The five properties this script holds itself to, each asserted by
# tests/infra/test_node_bootstrap_script.py rather than merely promised here:
#
#   1. IDEMPOTENT. Every step checks the state it wants before changing anything, so the
#      second run on the same host reports "already" and changes nothing. Both field
#      hosts already have docker, and one already has an active firewall with rules —
#      "already done by somebody else" is the normal case, not the exception.
#   2. NOT ONE INTERACTIVE QUESTION. No `read`, no `sudo` password prompt, no apt
#      dialogue, no `ufw enable` confirmation. This runs over a flaky SSH session while
#      the owner is replacing a host: a prompt is a run that hangs until the session dies.
#   3. IT VERIFIES BEFORE IT REPORTS SUCCESS. The last section asks the host the same
#      questions the control plane will ask it. `echo ok` is how an operator ends up
#      believing a broken node is ready.
#   4. IT LEAVES NO HASHI CODE, NO HASHI STATE AND NO PRIVATE KEY BEHIND. A node holds
#      nothing that cannot be regenerated from the control database (core invariants §3),
#      and that property is what makes destroying a node safe. This script must not
#      invent the first exception: it does not clone this repository, does not install
#      python, and does not write a config the control plane would later have to reconcile
#      with. It installs a PUBLIC key; the private half stays on the control plane and is
#      never generated here.
#
#      It DOES create /opt/hashi — one EMPTY directory, owned by the account the control
#      plane logs in as — and that is not the exception it looks like. State is what
#      cannot be regenerated; an empty directory is not state, it is the permission to
#      write one, and deleting it still costs a node nothing but an apply. Why it is
#      created here rather than by the control plane is section 4 below, and it is the
#      decision M13 exists for.
#   5. THE HOST NEVER STARTS RECORDING WHO CONNECTED. `ufw enable` turns logging ON by
#      default and immediately begins writing source addresses — the one record the
#      charter forbids at any level. `ufw logging off` therefore runs BEFORE the firewall
#      can come up, not after (docs/decisions.md, decision 5).
#
# WHAT THIS SCRIPT DOES NOT DO, and in most cases cannot. The five properties above are
# what it holds itself to; this is the other half of the same contract. Every item here is
# something an operator reasonably assumes "the host is ready" already covers, and each one
# fails in a way that points at the wrong component.
#
#   A. THE PROVIDER'S OWN FIREWALL IS NOT TOUCHED, AND CANNOT BE. A security group lives in
#      the provider's control panel, in front of the host; this script runs on the host,
#      and can neither see it nor change it. That matters more than it sounds, because a
#      closed security group LOOKS EXACTLY LIKE A BROKEN TRANSPORT: the host firewall
#      allows the port, the container is up, every check at the end of this run is green,
#      and the client still times out — so the operator goes and debugs the transport,
#      where there is nothing to find. Open the ports your transports listen on, and the
#      management port, in the provider's console; then confirm it from a machine on a
#      different network instead of believing the console. And beware the false negative
#      one layer further out: in the field a probe reported a privileged port shut when it
#      was in fact open, because the probing side was running unprivileged and could not
#      bind that port at all. Satisfy yourself that the probe can do what you think it is
#      doing before you conclude the security group is the problem.
#   B. IT DOES NOT REGISTER THE NODE. When this finishes the host is drivable and the fleet
#      still does not know it exists. Nothing here writes to the control database, and a
#      node never dials the control plane — the direction is control plane to node, always.
#      The node record, holding the private half of this key, is created in the panel.
#   C. THE ufw LOG SWEEP IS NOT A CLEANUP. It removes the file ufw itself writes, and on a
#      host that has already logged, rsyslog and journald put the same lines into the
#      system log, into kern.log and into the kernel journal. Nothing done here reaches any
#      of those. Switching logging off BEFORE the firewall comes up is the real protection,
#      and it only protects a host that had not yet logged; a host that already did needs
#      an operator, not a script (docs/tracker/M11/field-inventory.md).
#   D. IT NEVER CLOSES ANYTHING. Runs are additive by design: a port opened by an earlier
#      run stays open when a later run omits it, and a management port detected once keeps
#      its rule. A script that withdrew rules could withdraw the one carrying the session
#      running it — so the rule set is the union of every run so far, and only an operator
#      narrows it.
#   E. IT IS NOT HOST HARDENING. It does not disable password authentication, does not
#      install unattended upgrades or a ban daemon, does not touch time synchronisation and
#      does not tune the kernel. "Ready" here means ready to be driven by the control
#      plane, and nothing wider: in particular, the account it authorises a key for may
#      still accept a password, which belongs to whoever owns the host.
#   F. IT PROVES NOTHING ABOUT REACHABILITY. The verification at the end asks THIS HOST
#      questions; it never sends a packet anywhere. Whether a friend inside Russia can
#      reach this node is a field observation on a real network, and no run of this script
#      is evidence for it.
set -euo pipefail

# Upstream docker's own installer. Named in a variable and overridable because it is the
# one address in this file, and because a host behind an air gap or a mirror needs to
# point it elsewhere. It is not fleet topology — no country, provider, node or port is
# ever chosen here; the ports this script opens all arrive as arguments.
DOCKER_INSTALL_URL="${DOCKER_INSTALL_URL:-https://get.docker.com}"

AUTHORIZED_KEY=""
TARGET_USER=""
SSH_PORTS=""
OPEN_PORTS=()

usage() {
  cat <<'USAGE'
usage: node-bootstrap.sh --authorized-key "<ssh public key>" [options]
       node-bootstrap.sh --authorized-key-file <path on this host> [options]

  --authorized-key TEXT     the PUBLIC key the control plane will authenticate with
  --authorized-key-file P   the same, read from a file already on this host
  --user NAME               the account the control plane logs in as
                            (default: the invoking user, or SUDO_USER under sudo)
  --port PORT[/PROTO]       a port to open, repeatable — one per transport this node
                            will run, e.g. --port <number>/udp
  --ssh-port N              the port sshd listens on, if it cannot be detected
USAGE
}

say() { printf '==> %s\n' "$1"; }
fail() { printf 'node-bootstrap: %s\n' "$1" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --authorized-key) AUTHORIZED_KEY="$2"; shift 2 ;;
    --authorized-key=*) AUTHORIZED_KEY="${1#*=}"; shift ;;
    --authorized-key-file)
      [ -f "$2" ] || fail "no such file: $2"
      AUTHORIZED_KEY="$(head -1 "$2")"; shift 2 ;;
    --authorized-key-file=*)
      [ -f "${1#*=}" ] || fail "no such file: ${1#*=}"
      AUTHORIZED_KEY="$(head -1 "${1#*=}")"; shift ;;
    --user) TARGET_USER="$2"; shift 2 ;;
    --user=*) TARGET_USER="${1#*=}"; shift ;;
    --port) OPEN_PORTS+=("$2"); shift 2 ;;
    --port=*) OPEN_PORTS+=("${1#*=}"); shift ;;
    --ssh-port) SSH_PORTS="${SSH_PORTS} $2"; shift 2 ;;
    --ssh-port=*) SSH_PORTS="${SSH_PORTS} ${1#*=}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      printf 'unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2 ;;
  esac
done

# --- 0. how this script becomes root ------------------------------------------
#
# Both shapes are real and neither is preferred: one field host is reached as root, the
# other as an ordinary account with passwordless sudo and membership of the `docker`
# group. `sudo -n` rather than `sudo`: without -n, a host whose sudo wants a password
# turns this into a prompt on a pipe that has no terminal, and the run hangs (property 2).
as_root() {
  if [ "${EUID}" -eq 0 ]; then
    "$@"
  else
    sudo -n "$@"
  fi
}

if [ "${EUID}" -ne 0 ]; then
  command -v sudo >/dev/null 2>&1 || fail \
    "this account is not root and there is no sudo(1) on this host. Run the script as root."
  sudo -n true 2>/dev/null || fail \
    "sudo(1) on this host wants a password, and this script must never prompt — it is run
  over an SSH session that may not have a terminal. Give this account passwordless sudo,
  or run the script as root."
fi

# --- 1. the key ---------------------------------------------------------------
#
# THE refusal, and it is the same shape as panel-bootstrap's: this script installs the
# PUBLIC half and will not create the private half here. The private key is what the
# control database holds, encrypted, to reach every node; generated on the node it would
# live in clear on the machine most likely to be seized, and one seized leaf would then
# be a key to the fleet. Generate it where the control plane lives, on the control plane's
# own terms, and paste the public half here.
[ -n "${AUTHORIZED_KEY}" ] || fail \
  "no public key given, so the control plane would have no way in.

  Generate the pair where the CONTROL PLANE lives, never on this host — the private half
  belongs in the node record, encrypted, and a key made here would sit in clear on the
  machine most likely to be seized. On the control plane run:  ssh-keygen -t ed25519 -f
  ~/.ssh/hashi-node -N '' — then pass the .pub half:

      --authorized-key \"\$(cat ~/.ssh/hashi-node.pub)\""

# A pasted PRIVATE key is the mistake worth catching by name: it is one hurried
# copy-paste away, it would put the fleet's key on the node in clear, and everything
# afterwards would appear to work.
case "${AUTHORIZED_KEY}" in
  *"PRIVATE KEY"*)
    fail "that is a PRIVATE key. It must never be copied onto a node — the node
  authenticates nothing, it only recognises the public half. Pass the .pub file's
  contents instead. If this key has already been on this host, treat it as compromised
  and issue a new pair on the control plane." ;;
esac

# Shape only: type, base64 body, optional comment. Not a cryptographic check — sshd is
# the authority on that — but it catches the truncated paste, which otherwise fails much
# later as an authentication error that looks like a network problem.
case "${AUTHORIZED_KEY}" in
  ssh-*\ *|ecdsa-*\ *|sk-*\ *) : ;;
  *) fail "that does not look like an SSH public key (expected '<type> <base64> [comment]')" ;;
esac

TARGET_USER="${TARGET_USER:-${SUDO_USER:-$(id -un)}}"
TARGET_HOME="$(getent passwd "${TARGET_USER}" | cut -d: -f6)"
[ -n "${TARGET_HOME}" ] || fail "no account '${TARGET_USER}' on this host"
TARGET_GROUP="$(id -gn "${TARGET_USER}")"

# --- 2. the container runtime -------------------------------------------------
#
# The one thing hashi genuinely needs from the host and deliberately will not do from the
# library. Everything above the runtime — the compose file, the transport configs — is
# rendered by the control plane and pushed over SSH, which is why no hashi code is
# installed here.
if command -v docker >/dev/null 2>&1; then
  say "docker is already installed — left exactly as it is"
else
  command -v curl >/dev/null 2>&1 || fail \
    "no curl on this host, so the runtime installer cannot be fetched. Install curl (or
  docker itself) and run this again."
  say "installing a container runtime from ${DOCKER_INSTALL_URL}"
  # Downloaded to a file and then run, never piped straight into a shell: a connection
  # that dies mid-transfer would otherwise execute half an installer, and half an
  # installer is a host in a state nobody has ever tested.
  INSTALLER="$(mktemp)"
  trap 'rm -f "${INSTALLER}"' EXIT
  curl -fsSL "${DOCKER_INSTALL_URL}" -o "${INSTALLER}"
  as_root sh "${INSTALLER}"
fi

# systemd is not assumed — the runtime check below is what actually decides whether the
# daemon answers, so a host that starts docker some other way is not refused for it.
if command -v systemctl >/dev/null 2>&1; then
  as_root systemctl enable --now docker >/dev/null 2>&1 || true
fi

# Compose v2 as a plugin, never the legacy docker-compose: the node's data plane is
# brought up with `docker compose up -d` by edge/bootstrap, so a host without the plugin
# is a host that fails on apply rather than here, where the message can be useful.
docker compose version >/dev/null 2>&1 || fail \
  "docker is present but the compose v2 plugin is not. The node's data plane is brought
  up with 'docker compose up -d', so it would fail on the first apply. Install the
  docker-compose-plugin package and run this again."

# The account the control plane logs in as has to be able to reach the docker socket.
# Membership takes effect on the NEXT login, which is fine here and worth knowing: the
# control plane opens a new session every time, so it never sees the stale one.
if [ "${TARGET_USER}" != "root" ]; then
  if id -nG "${TARGET_USER}" | tr ' ' '\n' | grep -qx docker; then
    say "${TARGET_USER} is already in the docker group"
  else
    as_root usermod -aG docker "${TARGET_USER}"
    say "added ${TARGET_USER} to the docker group"
  fi
fi

# --- 3. the key, installed ----------------------------------------------------
SSH_DIR="${TARGET_HOME}/.ssh"
KEYS_FILE="${SSH_DIR}/authorized_keys"

as_root install -d -m 700 -o "${TARGET_USER}" -g "${TARGET_GROUP}" "${SSH_DIR}"
# `touch` only when there is nothing there. On an existing file touch(1) is a write, and
# the second run is meant to change nothing at all — not even an mtime somebody is using to
# see when this host was last altered. The chown and chmod below are a different kind of
# operation: they assert a state rather than change one, so running them every time
# converges the file instead of modifying it, and re-asserting them is exactly the point —
# sshd silently ignores an authorized_keys file that anyone else can write.
[ -e "${KEYS_FILE}" ] || as_root touch "${KEYS_FILE}"
as_root chown "${TARGET_USER}:${TARGET_GROUP}" "${KEYS_FILE}"
as_root chmod 600 "${KEYS_FILE}"

# Compared on type+body and not on the whole line, so re-running with a different comment
# does not append a second copy of the same key (property 1). The comment is a label; the
# body is the identity.
KEY_BODY="$(printf '%s' "${AUTHORIZED_KEY}" | awk '{print $1" "$2}')"

# Present, and present on a line sshd will actually honour. A plain substring search over
# the whole file also matches the key sitting in a COMMENTED-OUT entry — somebody's
# disabled key, or a note about one — and would then report "already authorised", and pass
# the verification at the end, for a key sshd ignores. That is the worst shape of untrue: a
# host that says it is ready and cannot be logged into. Commented lines are therefore
# skipped; everything else is left to sshd, which is the authority on what it accepts.
key_is_authorised() {
  as_root awk -v key="${KEY_BODY}" '
    /^[[:space:]]*#/ { next }
    index($0, key) { found = 1 }
    END { exit found ? 0 : 1 }
  ' "${KEYS_FILE}"
}

if key_is_authorised; then
  say "the control plane's key is already authorised for ${TARGET_USER}"
else
  # A file whose last line has no newline would otherwise swallow the new key onto it,
  # producing one corrupt entry and no working access. `read` is not used to test this,
  # deliberately: there must be no construct in this file that can consume stdin.
  if [ -s "${KEYS_FILE}" ] && [ "$(as_root tail -c1 "${KEYS_FILE}" | wc -l)" -eq 0 ]; then
    printf '\n' | as_root tee -a "${KEYS_FILE}" >/dev/null
  fi
  printf '%s\n' "${AUTHORIZED_KEY}" | as_root tee -a "${KEYS_FILE}" >/dev/null
  say "authorised the control plane's key for ${TARGET_USER}"
fi

# --- 4. the directory the control plane writes into ---------------------------
#
# THE PRODUCT'S PRIVILEGE BOUNDARY, and the decision M13 was opened to take. `/opt` is
# root-owned on every distro, and `edge/bootstrap/node_stack.py` drives a node as exactly
# the account in the node record and never escalates. So on a host prepared by THIS
# SCRIPT with a non-root account — which it supports, puts in the docker group, and ends
# by telling the operator to register — every apply died on
#
#     mkdir: cannot create directory '/opt/hashi': Permission denied
#
# The two halves of the product disagreed, and the disagreement was invisible from either
# side alone. Three fixes were possible: create the directory here, teach the library to
# `sudo`, or refuse a non-root account at registration. This one wins because this script
# already runs privileged and already grants this account the docker socket — handing it
# a directory it will own is the same category of act, done where the privilege already
# is — while the second gives a deliberately pure library a privilege model, and the
# third gives up every host whose provider offers no root account.
#
# What is created is EMPTY and stays empty until an apply: property 4 above, and the
# reason this is not the first piece of hashi state on a node.
#
# `install -d` rather than `mkdir`, and unconditional: one call that asserts the
# directory, its mode and its owner instead of changing them, exactly as the .ssh
# directory above is asserted. On a second run it converges and nothing moves.
#
# The name and the value both match NODE_ROOT in `edge/bootstrap/node_stack.py`, and
# tests/infra/test_node_bootstrap_agrees_with_the_control_plane.py goes red if either
# side changes alone. Do not change one alone: that is the fault this section is the fix
# for.
NODE_ROOT="/opt/hashi"
if [ -d "${NODE_ROOT}" ]; then NODE_ROOT_EXISTED=1; else NODE_ROOT_EXISTED=0; fi
as_root install -d -m 700 -o "${TARGET_USER}" -g "${TARGET_GROUP}" "${NODE_ROOT}"
if [ "${NODE_ROOT_EXISTED}" -eq 1 ]; then
  say "${NODE_ROOT} was already here — its contents were left alone, and ${TARGET_USER} owns the directory"
else
  say "created ${NODE_ROOT}, empty and owned by ${TARGET_USER}"
fi

# --- 5. the host firewall -----------------------------------------------------
if ! command -v ufw >/dev/null 2>&1; then
  command -v apt-get >/dev/null 2>&1 || fail \
    "no ufw on this host and no apt-get to install it with. Install ufw and run this
  again — this script will not leave a node without a host firewall."
  say "installing ufw"
  # Both flags are property 2: apt asks about configuration files and about restarting
  # services unless told not to, and either question hangs a piped run for ever.
  as_root env DEBIAN_FRONTEND=noninteractive apt-get update -qq
  as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ufw >/dev/null
fi

# LOGGING OFF FIRST, before the firewall can possibly come up. `ufw enable` turns logging
# on by default and starts writing source addresses to /var/log/ufw.log immediately —
# that is a connection log, the charter forbids it at any level, and it is the one record
# that can hurt a real person. Doing this after `enable` would still create the file
# (docs/decisions.md, decision 5).
#
# Read before writing, because `ufw logging off` is not a no-op when logging is already
# off: it rewrites ufw's config, reloads the firewall, and prints a line of its own into
# the middle of ours. The check fails in the safe direction on purpose — a missing or
# unreadable config leaves this empty, empty is not "off", and the command runs. There is
# no arrangement of this file in which logging stays on because a probe failed.
UFW_LOGLEVEL="$(as_root grep -m1 '^LOGLEVEL=' /etc/ufw/ufw.conf 2>/dev/null | cut -d= -f2 || true)"
if [ "${UFW_LOGLEVEL}" = "off" ]; then
  say "ufw logging was already off"
else
  as_root ufw logging off
fi
# And any file a previous life of this host left behind. It holds exactly the record we
# refuse to keep, so leaving it in place while switching logging off would be keeping the
# evidence and only stopping the note-taking.
#
# Know what this line is NOT. On a host that has already logged, the same UFW lines were
# also written by rsyslog and journald — /var/log/syslog, /var/log/kern.log and the kernel
# journal each hold a copy, and no cleanup here reaches all four. That is why the ordering
# above is the real protection and this is only the obvious sweep: a host that never logs
# has nothing to purge from anywhere. A host that already did needs the operator, not a
# script (docs/tracker/M11/field-inventory.md).
as_root sh -c 'rm -f /var/log/ufw.log /var/log/ufw.log.*'
say "ufw logging is off; the log file it may have had is gone (syslog and the journal may
    still hold older copies — this script cannot reach those)"

# Which port SSH actually arrives on, worked out rather than assumed. A literal here would
# be a port this fleet could not move away from, and — worse — a wrong guess enables a
# firewall that locks the operator out of the host they are in the middle of building.
# Two independent sources: the port THIS session came in on, and every port the daemon
# itself reports. Their union, so a host mid-migration between two ports keeps both.
SESSION_PORT="$(printf '%s' "${SSH_CONNECTION:-}" | awk '{print $4}')"
detect_ssh_ports() {
  printf '%s\n' "${SESSION_PORT}"
  if command -v sshd >/dev/null 2>&1; then
    as_root sshd -T 2>/dev/null | awk '/^port /{print $2}' || true
  elif [ -x /usr/sbin/sshd ]; then
    as_root /usr/sbin/sshd -T 2>/dev/null | awk '/^port /{print $2}' || true
  fi
}
SSH_PORTS="$(printf '%s\n%s\n' "${SSH_PORTS// /$'\n'}" "$(detect_ssh_ports)" \
  | grep -E '^[0-9]+$' | sort -un || true)"
[ -n "${SSH_PORTS}" ] || fail \
  "could not work out which port sshd listens on, and this script will not enable a
  firewall it cannot prove leaves you a way back in. Pass --ssh-port N."

# Management first, and before `enable` below. The order is the whole safety property:
# a firewall that comes up before its own admission rule is a locked door with the key
# inside.
#
# Unlike the data-plane loop below, this one does not distinguish "added" from "already
# there": the line it prints states the resulting STATE rather than an action, so it is
# equally true on the first run and the tenth. ufw deduplicates the rule itself, and its
# own chatter about that is discarded.
for port in ${SSH_PORTS}; do
  as_root ufw allow "${port}/tcp" >/dev/null
done
say "management access allowed on tcp: $(printf '%s' "${SSH_PORTS}" | tr '\n' ' ')"

# The data plane's ports, exactly as given. Never a literal and never a guess: which port
# a node listens on is a property of the transport enabled on it, held in the node record,
# and the operator passes the same number they entered there. A transport moved to a new
# port is one more --port on the next run.
for spec in ${OPEN_PORTS[@]+"${OPEN_PORTS[@]}"}; do
  case "${spec}" in
    *[!0-9/tcpud]*|"") fail "not a port: '${spec}' (expected N or N/tcp or N/udp)" ;;
  esac
  number="${spec%%/*}"
  proto="${spec#*/}"
  case "${number}" in
    ""|*[!0-9]*) fail "not a port: '${spec}' (expected N or N/tcp or N/udp)" ;;
  esac
  [ "${number}" -ge 1 ] && [ "${number}" -le 65535 ] || fail "port out of range: '${spec}'"
  if [ "${proto}" != "${spec}" ]; then
    case "${proto}" in
      tcp|udp) : ;;
      *) fail "unknown protocol in '${spec}' (expected tcp or udp)" ;;
    esac
  fi
  # ufw refuses to add a rule it already holds and says so, and that answer is the whole
  # difference between "opened" and "was already open" — a second run that claims it opened
  # a port it did not touch is the script lying about its own effect. Captured rather than
  # piped into grep: under pipefail a `grep -q` that closes the pipe early can leave the
  # pipeline reporting ufw's SIGPIPE instead of the match. LC_ALL=C so a translated build
  # does not move the sentence out from under the comparison; if it does anyway, the cost
  # is one wrong word in the output and nothing else, because ufw deduplicates the rule
  # either way. A genuine refusal still stops the run — it is not swallowed.
  if ! opened="$(as_root env LC_ALL=C ufw allow "${spec}" 2>&1)"; then
    fail "ufw refused to open ${spec}: ${opened}"
  fi
  case "${opened}" in
    *"Skipping adding existing rule"*) say "${spec} was already open" ;;
    *) say "opened ${spec}" ;;
  esac
done

# The two default policies, set only when they are not already what a node needs. Setting
# them unconditionally was wrong twice over: `ufw default` rewrites /etc/default/ufw and
# reloads the firewall every single time it is called, so a second run was a change; and on
# a host whose operator had chosen a policy of their own it silently overwrote that choice
# while the line further down still announced that the existing rules were kept. Read
# first, then set, and say so when it really is a change.
#
# The file rather than the live rule table, because it is what ufw itself consults, so it
# answers whether the firewall is up or not — the live output omits the defaults entirely
# while ufw is inactive, which is exactly the case this script exists to fix.
ufw_default() {
  as_root grep -m1 "^DEFAULT_${1}_POLICY=" /etc/default/ufw 2>/dev/null \
    | tr -d '"' | cut -d= -f2 || true
}

if [ "$(ufw_default INPUT)" = "DROP" ]; then
  say "incoming was already denied by default"
else
  as_root ufw --force default deny incoming >/dev/null
  say "incoming is now denied by default"
fi

if [ "$(ufw_default OUTPUT)" = "ACCEPT" ]; then
  say "outgoing was already allowed by default"
else
  as_root ufw --force default allow outgoing >/dev/null
  say "outgoing is now allowed by default"
fi

# `--force` because the confirmation ufw asks for here is the exact prompt property 2
# forbids. Only when it is not already up: a host that already has a firewall keeps the
# rules it has, and re-enabling one is a change where a no-op was promised.
# `grep '^Status: inactive'` and not `head -1 | grep`: with pipefail, a `head` that closes
# the pipe early can leave the pipeline reporting ufw's SIGPIPE rather than grep's answer,
# and the firewall would then never come up on the one host that needs it to.
if as_root ufw status | grep -q '^Status: inactive'; then
  as_root ufw --force enable >/dev/null
  say "the firewall is now up"
else
  say "the firewall was already up — its existing rules were kept"
fi

# --- 6. verify, and only then report success ----------------------------------
#
# The same questions the control plane will ask on its first connection, asked here where
# the answer can still be acted on. Nothing below reads a log, and nothing prints the
# firewall's rules: a rule can name an address an operator allowed, and this script has no
# reason to put one on a terminal.
as_root docker version --format '{{.Server.Version}}' >/dev/null 2>&1 || fail \
  "the docker daemon does not answer, so the control plane could reach this host and
  still be unable to start anything on it."

key_is_authorised || fail \
  "the control plane's key is not in ${KEYS_FILE} on a line sshd would honour — do not
  register this host until that is understood."

as_root ufw status verbose | grep -q 'Status: active' || fail \
  "ufw did not come up. The host is otherwise prepared, but it is exposed; fix the
  firewall before this node carries anyone's traffic."

as_root ufw status verbose | grep -qi 'Logging: off' || fail \
  "ufw is logging. That is a connection log — source addresses, written to disk — and the
  charter forbids it at any level. Run 'ufw logging off' and this script again before
  this host is used."

say "ready: docker $(docker --version | awk '{print $3}' | tr -d ,), key authorised, firewall up, logging off"
# The port to name is the one this session actually arrived on, when there was one: a host
# that answers on two ports still has exactly one that is known to work from outside.
say "register it in the panel with ssh_user ${TARGET_USER} and ssh_port ${SESSION_PORT:-$(printf '%s' "${SSH_PORTS}" | awk 'NR==1')}"
say "no hashi code and no hashi state was installed here — ${NODE_ROOT} is an empty directory owned by ${TARGET_USER}, and the control plane fills it on your first apply"
# On a re-run of a host the control plane has already applied to, the line above reads as
# "there is nothing of hashi's on this host", which would be false — the directory is
# there and it is not empty. What is true either way is that THIS SCRIPT wrote nothing
# into it and removed nothing from it.
if [ "${NODE_ROOT_EXISTED}" -eq 1 ]; then
  say "an earlier apply already left files in ${NODE_ROOT} — this run neither changed nor removed them, only re-asserted that ${TARGET_USER} owns the directory"
fi
# Said last because it is the operator's next move, and the moment they are most likely to
# blame the wrong layer. See section A of the header: this is the boundary that costs an
# evening, because the symptom is identical to a transport that does not work.
say "the provider's own firewall sits in front of this host and outside this script's reach:
    if a transport times out from outside while everything above is green, check the
    security group before you suspect the transport"
