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
# HOW:  scripts/management-tunnel.sh [--env-file PATH] [--out DIR]
#       Normally not run by hand: `make panel-bootstrap` runs it.
#
# The properties this script holds itself to, each asserted by
# tests/infra/test_management_tunnel_script.py rather than promised here:
#
#   1. IDEMPOTENT. A second run with the same peers changes nothing and prints
#      nothing new. A run with one more peer adds exactly that peer.
#   2. NOT ONE INTERACTIVE QUESTION. Every input comes from the env file, like
#      panel-bootstrap's. There is no `read` in this file and there must never be.
#   3. IT PRINTS EACH DEVICE'S CONFIG EXACTLY ONCE, and stores no copy of it. The
#      private half of a peer's key is generated, printed and forgotten — a device
#      whose config was lost gets a NEW peer, it does not get the old one reprinted.
#   4. IT TOUCHES NO NETWORK INTERFACE and runs nothing as root. It writes files and
#      prints; bringing the tunnel up is the operator's own command, from the
#      runbook. A script that raises an interface on the host it is reached over is
#      a script that can lock you out of that host.
set -euo pipefail

# Every file this script creates holds key material. 077 before anything is written,
# so there is no window in which the config is world-readable.
umask 077

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-${REPO_ROOT}/.env}"
# Outside the repository on purpose, and checked below: this directory holds this
# host's tunnel private key, and a checkout is the one place it must never be.
OUT_DIR="${HASHI_MGMT_DIR:-${HOME:-/root}/.hashi/management}"

while [ $# -gt 0 ]; do
  case "$1" in
    --env-file) ENV_FILE="$2"; shift 2 ;;
    --env-file=*) ENV_FILE="${1#*=}"; shift ;;
    --out) OUT_DIR="$2"; shift 2 ;;
    --out=*) OUT_DIR="${1#*=}"; shift ;;
    -h|--help)
      echo "usage: $0 [--env-file PATH] [--out DIR]"
      exit 0 ;;
    *)
      echo "unknown argument: $1" >&2
      echo "usage: $0 [--env-file PATH] [--out DIR]" >&2
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

value_of() {
  # First assignment wins, surrounding quotes stripped. `awk NR==1` rather than
  # `head -1`: under pipefail a closed pipe reads as a failed command (M11's notes).
  sed -n "s/^[[:space:]]*$1=[[:space:]]*//p" "${ENV_FILE}" \
    | awk 'NR==1' | sed 's/^"\(.*\)"$/\1/; s/^'"'"'\(.*\)'"'"'$/\1/'
}

MGMT_ADDRESS="$(value_of HASHI_MGMT_ADDRESS)"
MGMT_PORT="$(value_of HASHI_MGMT_PORT)"
MGMT_ENDPOINT="$(value_of HASHI_MGMT_ENDPOINT)"
MGMT_MTU="$(value_of HASHI_MGMT_MTU)"
MGMT_PEERS="$(value_of HASHI_MGMT_PEERS)"

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
case "${OUT_DIR%/}/" in
  "${REPO_ROOT%/}/"*)
    fail "the output directory ${OUT_DIR} is inside the repository at ${REPO_ROOT}.

  This directory holds this host's tunnel PRIVATE KEY. A key inside a checkout is one
  \`git add -A\` away from being committed, and that will happen on the day somebody is
  in a hurry. Pass --out with a path outside the repository, or set HASHI_MGMT_DIR." ;;
esac

mkdir -p "${OUT_DIR}"
chmod 700 "${OUT_DIR}"
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

# --- 4. this host's end --------------------------------------------------------

# The maximum prefix for the family, so a peer is allowed exactly one address and the
# client is routed to exactly this host. Derived rather than written down: an owner
# on IPv6 gets /128 without a second code path.
max_prefix_for() { case "$1" in *:*) printf '128' ;; *) printf '32' ;; esac; }

HOST_IP="${MGMT_ADDRESS%%/*}"
HOST_ROUTE="${HOST_IP}/$(max_prefix_for "${HOST_IP}")"

if [ -f "${CONF}" ]; then
  say "this host's tunnel already exists at ${CONF} — its keys and its obfuscation
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
# hashi — the management tunnel this host's admin console is reached over.
#
# Generated by scripts/management-tunnel.sh. Do not edit by hand: this file is the
# only copy of this host's tunnel private key, and every device's config was built
# from the obfuscation values below.
#
# There is deliberately NO PostUp, NO PostDown and NO Table here. This tunnel carries
# traffic TO this host — an admin console — and never THROUGH it, so it needs neither
# forwarding nor NAT. Adding M14's rules would quietly turn it into an exit node.
#
# PublicKey = ${HOST_PUBLIC}
[Interface]
PrivateKey = ${HOST_PRIVATE}
Address = ${MGMT_ADDRESS}
ListenPort = ${MGMT_PORT}
MTU = ${MGMT_MTU}

# AmneziaWG obfuscation — drawn for this host alone. A device's config must carry
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
conf_value() { sed -n "s/^$1 = //p" "${CONF}" | awk 'NR==1'; }
HOST_PUBLIC="$(sed -n 's/^# PublicKey = //p' "${CONF}" | awk 'NR==1')"
JC="$(conf_value Jc)"; JMIN="$(conf_value Jmin)"; JMAX="$(conf_value Jmax)"
H1="$(conf_value H1)"; H2="$(conf_value H2)"; H3="$(conf_value H3)"; H4="$(conf_value H4)"

# --- 5. the owner's devices ----------------------------------------------------
#
# N of them, by construction. This is the half that must not be a node_transports
# row: that shape holds one peer address, so it would serve one device, and an owner
# locked out of the console because they were holding the wrong one has lost the
# thing this milestone exists to protect.

NEW_PEERS=0
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

  peer_ip="${address%%/*}"
  peer_route="${peer_ip}/$(max_prefix_for "${peer_ip}")"

  [ "${peer_ip}" != "${HOST_IP}" ] || fail \
    "the device ${name} is given this host's own tunnel address ${peer_ip}. One of the
  two would never be reached."

  if grep -q "^AllowedIPs = ${peer_route}\$" "${CONF}"; then
    if grep -q "^# peer: ${name}\$" "${CONF}"; then
      # Idempotent, and silent about the key: the private half was printed once and
      # never stored, so there is nothing here that could reprint it.
      say "the device ${name} is already a peer of this tunnel — its config was printed
  when it was added and is not stored anywhere, so it cannot be printed again. A device
  that lost its config gets a NEW entry in HASHI_MGMT_PEERS, not this one back"
      continue
    fi
    fail "the address ${peer_route} is already used by another device in ${CONF}.
  AllowedIPs is WireGuard's routing table as well as its authorisation list, so the
  second device would silently take over the first one's route. Give each device its
  own address."
  fi

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

  # Printed, never written. Property 3: the private half of this key exists in this
  # terminal and on the owner's device, and nowhere else — not in this repository, not
  # in .env, not in the panel, not in a file this script leaves behind.
  say "device ${name} added. Its configuration follows ONCE and is not stored anywhere:"
  cat <<CLIENT

# hashi — management tunnel, device: ${name}
# This file contains a private key. Import it on the device and delete this text.
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
# host that has no forwarding configured — which fails silently rather than loudly.
AllowedIPs = ${HOST_ROUTE}
Endpoint = ${MGMT_ENDPOINT}:${MGMT_PORT}
PersistentKeepalive = 25

CLIENT
  NEW_PEERS=$(( NEW_PEERS + 1 ))
done

# --- 6. what was and was not done ---------------------------------------------
#
# The same honesty panel-bootstrap ends with, for the same reason: this script has
# written files and printed text. It has not brought an interface up, has not opened a
# firewall port, and cannot have verified that anything reaches this host.

if [ "${NEW_PEERS}" -gt 0 ]; then
  say "${NEW_PEERS} device config(s) printed above. Copy each one to its device now —
  scroll back is the only other copy, and this script keeps none"
fi
say "done. Written: ${CONF}, this host's end of the tunnel."
say "NOT done, and not yet true: the tunnel is not up and this host is not listening.
  Bring it up as root, open the UDP port in the host firewall, and only then publish
  the panel on it — docs/deploy/runbook.md, 'Reaching the panel', has the commands.
  This script raises no interface: one that did could lock you out of the host you ran
  it over."
