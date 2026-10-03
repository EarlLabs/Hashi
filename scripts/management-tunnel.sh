#!/usr/bin/env bash
# WHAT: generates the management tunnel the owner reaches the admin console over —
#       this host's end, and one obfuscated client config per device, printed once.
# WHY:  M7 takes the panel off the public internet, and the panel then has to be
#       reachable over something. That something is a dedicated AmneziaWG tunnel
#       (docs/decisions.md, 2026-09-09: decision 2 reversed), and it has to be built
#       HERE rather than in the panel, because the panel cannot hand you the config
#       you need to reach the panel. That chicken-and-egg is the whole reason this
#       file exists and the reason it prints a private key to a terminal.
#
#       Three properties are the decision, not the implementation:
#
#       1. IT IS NOT A `node_transports` ROW. That shape carries ONE
#          `peer_tunnel_address` and therefore serves exactly one device (M17). An
#          owner has a laptop and a phone, so this tunnel takes N peers by
#          construction — `HASHI_MGMT_PEERS` is a list, and adding a device is a
#          re-run with one more entry.
#       2. IT IS OBFUSCATED, not plain WireGuard. ТСПУ matches WireGuard's
#          fixed-shape handshake, and this is the one tunnel that must work when
#          everything else is being blocked. The junk packets and the four rewritten
#          magic headers below are the same wire format as
#          edge/transports/amneziawg/, and their values are drawn per host: a set of
#          values shared across the fleet would itself be the fingerprint, exactly
#          like a shared Reality decoy.
#       3. IT HAS NO FORWARDING AND NO NAT. This tunnel carries traffic TO this host,
#          not THROUGH it. M14's PostUp/PostDown rules are deliberately absent, and
#          the client's AllowedIPs is this host's tunnel address alone rather than
#          `0.0.0.0/0` — rendering either would quietly turn the admin tunnel into an
#          exit node. tests/infra/test_management_tunnel_script.py fails on both.
# HOW:  scripts/management-tunnel.sh [--env-file PATH] [--out DIR] [--configs-to DIR]
#                                     [--check]
#       Two ways in, both passing HASHI_MGMT_DIR and HASHI_MGMT_CONFIGS_TO through from
#       their own environment: `make panel-bootstrap` runs it as part of an install,
#       and `make mgmt-tunnel` runs it alone, touching no container — that is the one
#       for adding or removing a device on a host that is already serving (M33.4).
#
#       --check runs every refusal below and then stops, having created and changed
#       nothing, so a caller can ask "would this run refuse?" before doing anything of
#       its own (scripts/panel-bootstrap.sh is that caller; M33.4, finding D2).
#
# The properties this script holds itself to, each asserted by
# tests/infra/test_management_tunnel_script.py rather than promised here:
#
#   1. IDEMPOTENT, AND IT CONVERGES. A second run with the same peers changes nothing
#      and prints nothing new. A run with one more peer adds exactly that peer; a run
#      with one fewer removes exactly that peer and says so. The host file's peers are
#      HASHI_MGMT_PEERS after every run — a list that could only grow was a device you
#      could not take access away from (M33, finding 4).
#   2. NOT ONE INTERACTIVE QUESTION. Every input comes from the env file, like
#      panel-bootstrap's. There is no `read` in this file and there must never be.
#   3. IT HANDS OUT EACH DEVICE'S CONFIG EXACTLY ONCE, and keeps no copy of it. The
#      private half of a peer's key is generated, handed over and forgotten — a device
#      whose config was lost gets a NEW peer, it does not get the old one reprinted.
#      "Handed over" is the terminal by default, or with --configs-to one 0600 file per
#      device in a directory the operator names. That option exists because the
#      terminal is an SSH session whose scrollback mixes keys with progress lines, and a
#      phone wants a file it can turn into a QR code; it does not weaken the property,
#      because this script never reads such a file back, never writes one twice, and
#      refuses a directory inside the checkout exactly as it refuses one for the host
#      key. Moving the file to the device and deleting it is the operator's, as copying
#      it out of the scrollback always was (docs/decisions.md, 2026-10-03, M33).
#   4. IT TOUCHES NO NETWORK INTERFACE and runs nothing as root. It writes files and
#      prints; bringing the tunnel up is the operator's own command, which it prints
#      with this host's real paths. A script that raises an interface on the host it is
#      reached over is a script that can lock you out of that host.
#   5. IT KEEPS NO HOST END THE ENV FILE NO LONGER DESCRIBES. A host file whose
#      Address, ListenPort or MTU differs from the env file is refused, with both values
#      and the way to retire it, rather than kept as it is while the operator believes
#      the new values are live (M33, finding 1).
set -euo pipefail

# Every file this script creates holds key material. 077 before anything is written,
# so there is no window in which the config is world-readable.
umask 077

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-${REPO_ROOT}/.env}"
# Outside the repository on purpose, and checked below: this directory holds this
# host's tunnel private key, and a checkout is the one place it must never be.
OUT_DIR="${HASHI_MGMT_DIR:-${HOME:-/root}/.hashi/management}"
# Where new device configs go instead of the terminal, when set (property 3). Empty is
# the terminal. From the environment as well as the flag so `make panel-bootstrap`,
# which runs this script with a fixed argument list, can be given it per run without
# the operator editing the env file — it is a choice about this run, not about the host.
CONFIGS_TO="${HASHI_MGMT_CONFIGS_TO:-}"
CHECK_ONLY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --env-file) ENV_FILE="$2"; shift 2 ;;
    --env-file=*) ENV_FILE="${1#*=}"; shift ;;
    --out) OUT_DIR="$2"; shift 2 ;;
    --out=*) OUT_DIR="${1#*=}"; shift ;;
    --configs-to) CONFIGS_TO="$2"; shift 2 ;;
    --configs-to=*) CONFIGS_TO="${1#*=}"; shift ;;
    --check) CHECK_ONLY=1; shift ;;
    -h|--help)
      echo "usage: $0 [--env-file PATH] [--out DIR] [--configs-to DIR] [--check]"
      exit 0 ;;
    *)
      echo "unknown argument: $1" >&2
      echo "usage: $0 [--env-file PATH] [--out DIR] [--configs-to DIR] [--check]" >&2
      exit 2 ;;
  esac
done

say() { printf '==> %s\n' "$1"; }
fail() { printf 'management-tunnel: %s\n' "$1" >&2; exit 1; }

# --- 1. the env file -----------------------------------------------------------
#
# Read for values, never printed, and never `source`d — sourcing an env file RUNS
# it, so a stray backtick in a password becomes a command on this host. Same rule
# and same reason as scripts/panel-bootstrap.sh.

[ -f "${ENV_FILE}" ] || fail "no env file at ${ENV_FILE}. Copy .env.example to .env and
  fill in the HASHI_MGMT_* keys, or pass --env-file."

# Values come out of the file through the one parser this repository has, and this script
# is the reason it is a library (M28.13). Its own version took the FIRST assignment and
# left `\r` on the value, so an env file saved by a Windows editor — an ordinary thing to
# do while rebuilding a host from a laptop — wrote `Address`, `ListenPort`, `MTU` and
# `Endpoint = <host>^M:<port>^M` into the file below AND into every device config printed
# for an operator to paste onto a phone. Nothing refuses a carriage return there: the
# tunnel simply never comes up, from a file that looks correct.
# shellcheck source=lib/env-value.sh
. "${REPO_ROOT}/scripts/lib/env-value.sh"

MGMT_ADDRESS="$(env_value_of "${ENV_FILE}" HASHI_MGMT_ADDRESS)"
MGMT_PORT="$(env_value_of "${ENV_FILE}" HASHI_MGMT_PORT)"
MGMT_ENDPOINT="$(env_value_of "${ENV_FILE}" HASHI_MGMT_ENDPOINT)"
MGMT_MTU="$(env_value_of "${ENV_FILE}" HASHI_MGMT_MTU)"
MGMT_PEERS="$(env_value_of "${ENV_FILE}" HASHI_MGMT_PEERS)"

MISSING=()
[ -n "${MGMT_ADDRESS}" ] || MISSING+=(HASHI_MGMT_ADDRESS)
[ -n "${MGMT_PORT}" ]    || MISSING+=(HASHI_MGMT_PORT)
[ -n "${MGMT_ENDPOINT}" ]|| MISSING+=(HASHI_MGMT_ENDPOINT)
[ -n "${MGMT_MTU}" ]     || MISSING+=(HASHI_MGMT_MTU)
[ -n "${MGMT_PEERS}" ]   || MISSING+=(HASHI_MGMT_PEERS)
if [ ${#MISSING[@]} -gt 0 ]; then
  # Nothing is defaulted, and the reason is the same one edge/transports/amneziawg
  # gives for refusing to default its own parameters: a value that is the same on
  # every host that ever runs this script is a value the fleet cannot rotate away
  # from, and an address range shared with a hop collides with it silently.
  fail "these keys are missing or empty in ${ENV_FILE}: ${MISSING[*]}.
  See .env.example for what each one is. Nothing here is defaulted: an address range,
  a port and an MTU are per-deployment facts, and a default would be the same value on
  every host that ever runs this script."
fi

# --- 2. where the files go -----------------------------------------------------
#
# Refused rather than gitignored. A private key inside a checkout is one `git add -A`
# away from being published, and the person doing it will be in a hurry.
#
# Made absolute FIRST, without touching the filesystem: the paths are compared against
# the checkout, and they are printed into root commands at the end — a relative path
# there is resolved against whatever directory root happens to be in, and `~` in a root
# shell is /root, which is how the runbook's own command pointed at a file that did not
# exist (M33, finding 2). Not `cd && pwd`, because that needs the directory to exist and
# the refusal below must happen before anything is created.
absolute() { case "$1" in /*) printf '%s' "$1" ;; *) printf '%s/%s' "${PWD}" "$1" ;; esac; }

refuse_inside_checkout() {
  case "${2%/}/" in
    "${REPO_ROOT%/}/"*)
      fail "the $1 ${2} is inside the repository at ${REPO_ROOT}.

  It would hold a tunnel PRIVATE KEY. A key inside a checkout is one \`git add -A\` away
  from being committed, and that will happen on the day somebody is in a hurry. $3" ;;
  esac
}

OUT_DIR="$(absolute "${OUT_DIR}")"
refuse_inside_checkout "output directory" "${OUT_DIR}" \
  "Pass --out with a path outside the repository, or set HASHI_MGMT_DIR."
if [ -n "${CONFIGS_TO}" ]; then
  CONFIGS_TO="$(absolute "${CONFIGS_TO}")"
  refuse_inside_checkout "device-config directory" "${CONFIGS_TO}" \
    "Pass --configs-to with a path outside the repository, or set HASHI_MGMT_CONFIGS_TO."
fi

# Named here and created only in section 5, after every refusal: section 4 reads it if it
# exists, and a --check run must leave a host with no tunnel exactly as it found it.
CONF="${OUT_DIR}/awg-mgmt.conf"

# --- 3. key material -----------------------------------------------------------
#
# Two backends, because the panel host may not have wireguard-tools yet on the run
# that generates the config — the config is what tells the operator to install it.
# Both produce the same thing: 32 bytes of X25519 in standard, padded base64, which
# is what the daemon accepts (edge/transports/amneziawg/params.py refuses the
# URL-safe unpadded encoding for the same reason).
if command -v wg >/dev/null 2>&1; then
  KEYGEN=wg
elif command -v openssl >/dev/null 2>&1; then
  KEYGEN=openssl
else
  fail "neither \`wg\` nor \`openssl\` is on this host, so no key can be generated.
  Install wireguard-tools (which you need to bring the tunnel up anyway) and run this
  again; a second run is safe."
fi

# Prints "PRIVATE PUBLIC". The DER is carried base64-encoded through a variable
# rather than a temporary file: a temp file holding a private key is a file that
# survives a killed run, and shell variables cannot hold the NUL bytes of raw DER.
generate_keypair() {
  local private public der
  if [ "${KEYGEN}" = wg ]; then
    private="$(wg genkey)"
    public="$(printf '%s' "${private}" | wg pubkey)"
  else
    der="$(openssl genpkey -algorithm X25519 -outform DER | base64 | tr -d '\n')"
    # The last 32 bytes of a PKCS#8 X25519 key are the scalar itself, already
    # clamped by OpenSSL — which is exactly what WireGuard's base64 private key is.
    private="$(printf '%s' "${der}" | base64 -d | tail -c 32 | base64 | tr -d '\n')"
    public="$(printf '%s' "${der}" | base64 -d \
      | openssl pkey -inform DER -pubout -outform DER | tail -c 32 | base64 | tr -d '\n')"
  fi
  printf '%s %s\n' "${private}" "${public}"
}

# A per-peer pre-shared key. Symmetric, so it is minted once and written into both
# ends here — the mistake edge/registry.py's `shared_between_peers` exists to prevent
# is minting it twice and getting two valid files that never handshake.
generate_psk() { head -c 32 /dev/urandom | base64 | tr -d '\n'; }

# An integer in [min, max]. Modulo bias is irrelevant here: these are obfuscation
# parameters, not keys, and their job is to differ between hosts rather than to be
# uniform.
rand_int() {
  local min="$1" max="$2" raw
  raw="$(od -An -N4 -tu4 < /dev/urandom | tr -d ' \n')"
  printf '%s' "$(( min + raw % (max - min + 1) ))"
}

# --- 4. what the env file asks for, checked before anything is written ------------
#
# Everything in this section reads and refuses; nothing is created or changed until it
# has all passed. A run that refuses halfway through a list of devices would leave a host
# file that is neither the old list nor the new one.

# The maximum prefix for the family, so a peer is allowed exactly one address and the
# client is routed to exactly this host. Derived rather than written down: an owner
# on IPv6 gets /128 without a second code path.
max_prefix_for() { case "$1" in *:*) printf '128' ;; *) printf '32' ;; esac; }

HOST_IP="${MGMT_ADDRESS%%/*}"
HOST_ROUTE="${HOST_IP}/$(max_prefix_for "${HOST_IP}")"

# --- 4a. the devices the env file lists
#
# N of them, by construction. This is the half that must not be a node_transports
# row: that shape holds one peer address, so it would serve one device, and an owner
# locked out of the console because they were holding the wrong one has lost the
# thing this milestone exists to protect.
#
# Split on commas without `read`: property 2 is "no `read` anywhere", and a test
# enforces it by looking for the word, because the difference between `read` from a
# here-string and `read` from a terminal is one edit and a hung deployment.
# `set -f` because a device address is data and must never be expanded as a glob.
SAVED_IFS="${IFS}"
IFS=','
set -f
PEER_SPECS=(${MGMT_PEERS})
set +f
IFS="${SAVED_IFS}"

WANT_NAMES=()
WANT_ROUTES=()
for spec in ${PEER_SPECS[@]+"${PEER_SPECS[@]}"}; do
  spec="$(printf '%s' "${spec}" | tr -d '[:space:]')"
  [ -n "${spec}" ] || continue
  case "${spec}" in
    *=*) ;;
    *) fail "HASHI_MGMT_PEERS entry ${spec} is not name=address. Each device is written
  \`laptop=10.x.y.2/32\`, and the list is comma separated." ;;
  esac
  name="${spec%%=*}"
  address="${spec#*=}"
  [ -n "${name}" ] && [ -n "${address}" ] || fail \
    "HASHI_MGMT_PEERS entry ${spec} has an empty name or an empty address."
  # A name is a comment line in the host file, the key this script matches a device by
  # on every later run, and with --configs-to a file name. Letters, digits, `.`, `_`
  # and `-`, not starting with a dot: anything wider is a path or a second token.
  case "${name}" in
    .*|*[!A-Za-z0-9._-]*) fail "HASHI_MGMT_PEERS has a device named ${name}. A device
  name is letters, digits, '.', '_' and '-', and does not start with a dot - it becomes a
  line in the host file and, with --configs-to, a file name." ;;
  esac

  peer_ip="${address%%/*}"
  peer_route="${peer_ip}/$(max_prefix_for "${peer_ip}")"

  [ "${peer_ip}" != "${HOST_IP}" ] || fail \
    "the device ${name} is given this host's own tunnel address ${peer_ip}. One of the
  two would never be reached."

  for i in ${WANT_NAMES[@]+"${!WANT_NAMES[@]}"}; do
    [ "${WANT_NAMES[$i]}" != "${name}" ] || fail \
      "HASHI_MGMT_PEERS names the device ${name} twice. A name is how a device is
  matched on every later run, so it has to be unique."
    [ "${WANT_ROUTES[$i]}" != "${peer_route}" ] || fail \
      "the address ${peer_route} is already used by another device (${WANT_NAMES[$i]})
  in HASHI_MGMT_PEERS. AllowedIPs is WireGuard's routing table as well as its
  authorisation list, so the second device would silently take over the first one's
  route. Give each device its own address."
  done
  WANT_NAMES+=("${name}")
  WANT_ROUTES+=("${peer_route}")
done

# The index of a device in the env file's list, or nothing.
wanted_index() {
  local i
  for i in ${WANT_NAMES[@]+"${!WANT_NAMES[@]}"}; do
    [ "${WANT_NAMES[$i]}" = "$1" ] && { printf '%s' "${i}"; return 0; }
  done
  return 1
}

# --- 4b. an existing host end must be the one the env file describes
#
# M33, finding 1. This script used to keep an existing host file as it was, whatever the
# env file now said — correctly about the keys, which must survive a re-run, and silently
# about everything else. On the real host the operator changed the port, the MTU and the
# address range, re-ran, and got the OLD tunnel back with a "kept" message that read as
# success; the first new device then collided with an old one's address.
#
# Refused, not rewritten in place. Each of these three is inside every device config
# already handed out — a device dials the port, holds an address in the range, and the
# MTU was printed with it — and those configs are not stored here, so a host file
# "updated" to new values is a tunnel every existing device is silently cut off from.
# The two honest ways forward are to put the old values back, or to retire this host
# end and start over, and which one is the operator's call.
conf_value() { sed -n "s/^$1 = //p" "${CONF}" | awk 'NR==1'; }

if [ -f "${CONF}" ]; then
  DRIFT=""
  have="$(conf_value Address)"
  [ "${have}" = "${MGMT_ADDRESS}" ] || DRIFT="${DRIFT}
      HASHI_MGMT_ADDRESS  the host file has ${have:-nothing}, the env file says ${MGMT_ADDRESS}"
  HAVE_PORT="$(conf_value ListenPort)"
  [ "${HAVE_PORT}" = "${MGMT_PORT}" ] || DRIFT="${DRIFT}
      HASHI_MGMT_PORT     the host file has ${HAVE_PORT:-nothing}, the env file says ${MGMT_PORT}"
  have="$(conf_value MTU)"
  [ "${have}" = "${MGMT_MTU}" ] || DRIFT="${DRIFT}
      HASHI_MGMT_MTU      the host file has ${have:-nothing}, the env file says ${MGMT_MTU}"
  if [ -n "${DRIFT}" ]; then
    fail "the management tunnel already on this host is not the one ${ENV_FILE} describes,
  and nothing was changed:
${DRIFT}

  The host file is ${CONF}. Every device config already handed out carries the old
  values, so this script will not rewrite them under those devices. Either:

    - put the old values back in the env file and run this again - nothing on any device
      changes; or

    - retire this host end and start over. Every device then needs its NEW config, and
      the old one should be deleted from it:

        sudo systemctl disable --now awg-quick@awg-mgmt     # if it is running
        mv ${CONF} ${CONF}.retired-\$(date +%Y%m%d)
        sudo ufw delete allow ${HAVE_PORT:-<the old port>}/udp   # only if the port changed

      then run this again. docs/deploy/runbook.md, 'Starting the tunnel over', has the
      whole sequence."
  fi
fi

# --- 4c. what changes: which peers go and which are new
#
# The host file is converged to HASHI_MGMT_PEERS (property 1). A peer in the file whose
# name is no longer listed is removed. A listed name already in the file is kept with its
# keys — its private half was handed out once and is not stored, so there is nothing to
# re-issue. A listed name that is not in the file is new.
#
# Matched by NAME, and a name whose address changed is refused rather than re-issued: the
# address is inside the config on that device, so "the same device at a new address" is a
# new config whichever way it is done, and doing it silently would cut the device off
# while it still looks configured. A new name makes the swap explicit.

# One line per [Peer] block of the host file: "PUBLICKEY ROUTE NAME". The public key comes
# first because it is the one field every block has — a block written by hand, against
# the file's own header, has no `# peer:` line, and it is still a peer the interface
# accepts, so it is still something to converge away.
existing_peers() {
  awk '
    function out() { if (inpeer) print pub " " route " " name }
    /^\[Peer\]$/       { out(); inpeer = 1; pub = "-"; route = "-"; name = ""; next }
    /^\[/              { out(); inpeer = 0; next }
    inpeer && /^# peer: /      { name = substr($0, 9) }
    inpeer && /^PublicKey = /  { pub = substr($0, 13) }
    inpeer && /^AllowedIPs = / { route = substr($0, 14) }
    END { out() }
  ' "${CONF}"
}

DROP_KEYS="|"
DROP_LABELS=()
IN_FILE="|"
if [ -f "${CONF}" ]; then
  EXISTING="$(existing_peers)"
  SAVED_IFS="${IFS}"; IFS=$'\n'; set -f
  EXISTING_LINES=(${EXISTING})
  set +f; IFS="${SAVED_IFS}"
  for line in ${EXISTING_LINES[@]+"${EXISTING_LINES[@]}"}; do
    pub="${line%% *}"; rest="${line#* }"
    route="${rest%% *}"; name="${rest#* }"
    [ "${name}" != "${rest}" ] || name=""
    if [ -n "${name}" ] && idx="$(wanted_index "${name}")"; then
      [ "${WANT_ROUTES[$idx]}" = "${route}" ] || fail "the device ${name} is a peer of this
  tunnel at ${route}, and HASHI_MGMT_PEERS now gives it ${WANT_ROUTES[$idx]}. Nothing was
  changed.

  A device's address is inside the config on that device, so moving it is a new config
  either way. Give the device a NEW name with the new address (for example
  ${name}2=${WANT_ROUTES[$idx]}): the run then removes ${name}, hands out a config for
  the new name, and the device imports that one in place of the old."
      IN_FILE="${IN_FILE}${name}|"
    else
      DROP_KEYS="${DROP_KEYS}${pub}|"
      DROP_LABELS+=("${name:-an unnamed peer with public key ${pub}} (${route})")
    fi
  done
fi

NEW_IDX=()
for i in ${WANT_NAMES[@]+"${!WANT_NAMES[@]}"}; do
  case "${IN_FILE}" in *"|${WANT_NAMES[$i]}|"*) ;; *) NEW_IDX+=("${i}") ;; esac
done

# --- 4d. where the new configs go
#
# A file already at a new device's name is refused rather than overwritten: it is a
# config somebody has not moved to its device yet, from an earlier run or an earlier
# tunnel, and overwriting it is how the only copy of a working key disappears.
if [ -n "${CONFIGS_TO}" ]; then
  for i in ${NEW_IDX[@]+"${NEW_IDX[@]}"}; do
    target="${CONFIGS_TO}/${WANT_NAMES[$i]}.conf"
    [ ! -e "${target}" ] || fail "${target} already exists, and nothing was changed. It
  is a device config nobody has moved to its device yet, or one left from an earlier
  tunnel. Move it to its device (or delete it, if it belongs to a tunnel you retired)
  and run this again."
  done
fi

# --- 4e. a --check run ends here, with nothing created or changed
#
# Every refusal this script has is above this line, and nothing above it writes; that is
# what lets a caller ask "would this run refuse?" before it does anything of its own. A
# check that wrote, or that skipped a refusal, would make panel-bootstrap's "nothing was
# changed" untrue in one direction or the other.
if [ "${CHECK_ONLY}" = 1 ]; then
  say "checked: the management tunnel ${ENV_FILE} describes can be written to ${CONF} -
  nothing was created or changed by this check"
  exit 0
fi

# --- 5. this host's end --------------------------------------------------------

mkdir -p "${OUT_DIR}"
chmod 700 "${OUT_DIR}"

if [ -f "${CONF}" ]; then
  say "this host's tunnel already exists at ${CONF} - its keys and its obfuscation
  values are kept, because regenerating them would break every device already using it"
else
  HOST_KEYPAIR="$(generate_keypair)"
  HOST_PRIVATE="${HOST_KEYPAIR%% *}"
  HOST_PUBLIC="${HOST_KEYPAIR##* }"

  # Drawn per host. Shared values would be the fingerprint — the same reasoning as a
  # shared Reality decoy destination, and the reason edge's Params validates these
  # rather than defaulting them. The four magic headers must be DISTINCT: two equal
  # values make two message types indistinguishable and the tunnel never comes up.
  JC="$(rand_int 4 12)"
  JMIN="$(rand_int 40 70)"
  JMAX="$(( JMIN + $(rand_int 30 180) ))"
  H1="$(rand_int 5 2147483000)"
  H2="$(( H1 + $(rand_int 1 100000) ))"
  H3="$(( H2 + $(rand_int 1 100000) ))"
  H4="$(( H3 + $(rand_int 1 100000) ))"

  cat > "${CONF}" <<CONFIG
# hashi - the management tunnel this host's admin console is reached over.
#
# Generated by scripts/management-tunnel.sh. Do not edit by hand: this file is the
# only copy of this host's tunnel private key, every device's config was built from
# the obfuscation values below, and every run converges the [Peer] blocks to
# HASHI_MGMT_PEERS - a block added by hand is removed by the next run.
#
# There is deliberately NO PostUp, NO PostDown and NO Table here. This tunnel carries
# traffic TO this host - an admin console - and never THROUGH it, so it needs neither
# forwarding nor NAT. Adding M14's rules would quietly turn it into an exit node.
#
# PublicKey = ${HOST_PUBLIC}
[Interface]
PrivateKey = ${HOST_PRIVATE}
Address = ${MGMT_ADDRESS}
ListenPort = ${MGMT_PORT}
MTU = ${MGMT_MTU}

# AmneziaWG obfuscation - drawn for this host alone. A device's config must carry
# these values exactly; one mismatched header is a tunnel that never comes up, with
# nothing in any log to say why, because nothing here logs.
Jc = ${JC}
Jmin = ${JMIN}
Jmax = ${JMAX}
H1 = ${H1}
H2 = ${H2}
H3 = ${H3}
H4 = ${H4}
CONFIG
  chmod 600 "${CONF}"
  say "generated this host's end of the management tunnel at ${CONF}"
fi

# Read back rather than kept in variables, so a run that only ADDS a peer builds that
# peer's config from what the file actually says. The alternative — regenerating the
# values — is how a new device gets a config the tunnel rejects.
HOST_PUBLIC="$(sed -n 's/^# PublicKey = //p' "${CONF}" | awk 'NR==1')"
JC="$(conf_value Jc)"; JMIN="$(conf_value Jmin)"; JMAX="$(conf_value Jmax)"
H1="$(conf_value H1)"; H2="$(conf_value H2)"; H3="$(conf_value H3)"; H4="$(conf_value H4)"

# --- 6. devices no longer listed lose their peer -------------------------------
#
# M33, finding 4: deleting a name from HASHI_MGMT_PEERS used to change nothing, so a lost
# phone kept its way into the console for as long as nobody edited this file by hand.
#
# The file is rewritten through a temporary file in the same 0700 directory and renamed
# over the original, so a run killed halfway leaves the old file or the new one and never
# half of each. Blank lines are held back until something follows them, which keeps one
# blank line between blocks whichever block was dropped, and none at the end.
if [ "${DROP_KEYS}" != "|" ]; then
  TMP_CONF="${CONF}.tmp.$$"
  awk -v drop="${DROP_KEYS}" '
    function emit(l) {
      if (l == "") { blanks++; return }
      while (blanks > 0) { print ""; blanks-- }
      print l
    }
    function close_block(   i) {
      if (inpeer && index(drop, "|" pub "|") == 0) for (i = 1; i <= n; i++) emit(buf[i])
      inpeer = 0; n = 0
    }
    /^\[Peer\]$/ { close_block(); inpeer = 1; pub = "-" }
    /^\[/ && !/^\[Peer\]$/ { close_block() }
    inpeer { buf[++n] = $0; if ($0 ~ /^PublicKey = /) pub = substr($0, 13); next }
    { emit($0) }
    END { close_block() }
  ' "${CONF}" > "${TMP_CONF}"
  chmod 600 "${TMP_CONF}"
  mv -f "${TMP_CONF}" "${CONF}"
  for label in "${DROP_LABELS[@]}"; do
    say "removed ${label}: it is no longer in HASHI_MGMT_PEERS. Its access ends when
  the running interface reloads this file (below), not before"
  done
fi

# --- 7. devices newly listed get a peer, and their config handed out once ------

NEW_PEERS=0
for i in ${WANT_NAMES[@]+"${!WANT_NAMES[@]}"}; do
  name="${WANT_NAMES[$i]}"
  peer_route="${WANT_ROUTES[$i]}"
  case "${IN_FILE}" in
    *"|${name}|"*)
      # Idempotent, and silent about the key: the private half was handed out once and
      # never stored, so there is nothing here that could reprint it.
      say "the device ${name} is already a peer of this tunnel - its config was handed
  out when it was added and is not stored anywhere, so it cannot be printed again. A
  device that lost its config gets a NEW entry in HASHI_MGMT_PEERS, not this one back"
      continue ;;
  esac

  peer_keypair="$(generate_keypair)"
  peer_private="${peer_keypair%% *}"
  peer_public="${peer_keypair##* }"
  peer_psk="$(generate_psk)"

  cat >> "${CONF}" <<PEER

[Peer]
# peer: ${name}
PublicKey = ${peer_public}
PresharedKey = ${peer_psk}
AllowedIPs = ${peer_route}
PEER

  # ASCII ONLY, every byte of it. A phone imports this through a QR code, and on the real
  # host a QR decoder read the em dash that used to be in the first comment as something
  # else (M33, finding 6). The obligation is on this text rather than on the operator's
  # QR tool, because this is the one place that can guarantee it - and a test reads it
  # back byte by byte.
  CLIENT_CONFIG="# hashi - management tunnel, device: ${name}
# This file contains a private key. Import it on the device, then delete every other
# copy of this text.
[Interface]
PrivateKey = ${peer_private}
Address = ${peer_route}
MTU = ${MGMT_MTU}

# These must match the host exactly. They are the wire format, not preferences.
Jc = ${JC}
Jmin = ${JMIN}
Jmax = ${JMAX}
H1 = ${H1}
H2 = ${H2}
H3 = ${H3}
H4 = ${H4}

[Peer]
PublicKey = ${HOST_PUBLIC}
PresharedKey = ${peer_psk}
# The panel host and nothing else. This tunnel reaches an admin console; it is not an
# exit, and a default route here would send this device's whole internet through a
# host that has no forwarding configured - which fails silently rather than loudly.
AllowedIPs = ${HOST_ROUTE}
Endpoint = ${MGMT_ENDPOINT}:${MGMT_PORT}
PersistentKeepalive = 25"

  if [ -n "${CONFIGS_TO}" ]; then
    # Written once, 0600 under the umask above, into a 0700 directory, and never read
    # back. Property 3 is about this script keeping no copy: this file is the hand-over
    # itself, the same as the terminal, and moving it to the device and deleting it is
    # the operator's - the run's last lines say so.
    mkdir -p "${CONFIGS_TO}"
    chmod 700 "${CONFIGS_TO}"
    printf '%s\n' "${CLIENT_CONFIG}" > "${CONFIGS_TO}/${name}.conf"
    chmod 600 "${CONFIGS_TO}/${name}.conf"
    say "device ${name} added. Its configuration is in ${CONFIGS_TO}/${name}.conf, and
  that file is the only copy: move it to the device, then delete it from this host"
  else
    # Printed, never written. Property 3: the private half of this key exists in this
    # terminal and on the owner's device, and nowhere else — not in this repository, not
    # in .env, not in the panel, not in a file this script leaves behind.
    say "device ${name} added. Its configuration follows ONCE and is not stored anywhere:"
    printf '\n%s\n\n' "${CLIENT_CONFIG}"
  fi
  NEW_PEERS=$(( NEW_PEERS + 1 ))
done

# --- 8. what was and was not done ---------------------------------------------
#
# The same honesty panel-bootstrap ends with, for the same reason: this script has
# written files and printed text. It has not brought an interface up, has not opened a
# firewall port, and cannot have verified that anything reaches this host.
#
# The root commands are PRINTED, with this host's real paths, and never run (property
# 4). They used to live only in the runbook as `awg-quick up ~/.hashi/...`, which in a
# root shell is /root/.hashi and does not exist (M33, finding 2); and the runbook had no
# reboot story at all, so on the real host a reboot left docker unable to bind the
# console's address and took the delivery endpoint down with it (finding 3). Each
# command is safe to repeat, so they are printed on every run rather than only the first.
#
#   - The interface is a systemd unit (`awg-quick@`, shipped with amneziawg-tools) whose
#     config is a symlink to the file above, so it survives a reboot and every later
#     re-run's change reaches it with one `reload` — which is `awg syncconf`, and keeps
#     every other device's session up.
#   - ip_nonlocal_bind lets docker publish the console on the tunnel address while that
#     address does not exist yet. Without it, a tunnel that is late or broken at boot
#     fails the WHOLE caddy container, and the public delivery endpoint with it — the one
#     thing a user inside Russia needs on the day a node is blocked. The decision and the
#     alternatives are docs/decisions.md, 2026-10-03 (M33).
case "${HOST_IP}" in *:*) NONLOCAL=net.ipv6.ip_nonlocal_bind ;; *) NONLOCAL=net.ipv4.ip_nonlocal_bind ;; esac

if [ "${NEW_PEERS}" -gt 0 ] && [ -z "${CONFIGS_TO}" ]; then
  say "${NEW_PEERS} device config(s) printed above. Copy each one to its device now -
  scroll back is the only other copy, and this script keeps none"
elif [ "${NEW_PEERS}" -gt 0 ]; then
  say "${NEW_PEERS} device config(s) written to ${CONFIGS_TO}. Move each to its device
  and delete it here - this script keeps no other copy and never reads them back"
fi
say "done. Written: ${CONF}, this host's end of the tunnel."
say "NOT done, and not yet true: the tunnel is not up and this host is not listening.
  This script raises no interface and opens no port - one that did could lock you out of
  the host you ran it over. As root, once per host (every line is safe to repeat, and
  amneziawg-tools must be installed):

      sudo install -d -m 700 /etc/amnezia/amneziawg
      sudo ln -sfn ${CONF} /etc/amnezia/amneziawg/awg-mgmt.conf
      sudo ufw allow ${MGMT_PORT}/udp
      echo '${NONLOCAL} = 1' | sudo tee /etc/sysctl.d/60-hashi-mgmt.conf
      sudo sysctl --system
      sudo systemctl enable --now awg-quick@awg-mgmt

  After a later run that added or removed a device, load the change into the running
  interface - the other devices stay connected:

      sudo systemctl reload awg-quick@awg-mgmt

  Then publish the console on the tunnel address with make up-panel.
  docs/deploy/runbook.md, 'Reaching the panel', has the why of each line."
