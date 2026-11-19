#!/usr/bin/env bash
# WHAT: sets up one Mac to use hashi through sing-box in TUN mode, without the Happ app's
#       own tunnel: installs ~/hashi-vpn.sh (the runner) and three zsh commands — vpnon,
#       vpnoff, vpnwhich. Or, with --bundle, writes a ready-to-send copy of itself with one
#       person's subscription inside, which that person runs with no arguments.
# WHY:  on the owner's and Adel's Macs on 2026-11-19/20, Happ's tunnel carried nothing while
#       sing-box on the same network, with the same routes, passed every check. Two facts
#       about the network shaped the runner:
#       1. ONE ROUTE AT A TIME GETS CUT. Russian networks cut the port a route is used on
#          for a minute or two after VPN traffic, and some routes are dead from Russia
#          altogether. So every route in the subscription goes into one sing-box `urltest`
#          group that re-measures them every 30 s and uses the fastest that answers; a dead
#          route is simply never picked. The list is read from the subscription at every
#          start, never written here — a node added or removed reaches the Mac at its next
#          vpnon with nothing to reinstall, which is the charter's "nodes are data" seen
#          from the client.
#       2. THE WAY BACK TO HASHI IS CUT. Traffic leaves through a leaf abroad, and the path
#          from there to a Russian-hosted subscription endpoint can be blocked, so hashi's
#          own hosts (the subscription's and every route's) bypass the tunnel.
#       Destinations that should never enter the tunnel (`--direct-suffix ru`, for example)
#       are the operator's per-person choice and have no default here: a suffix written
#       into this file would be a country hardcoded into the project.
#       sing-box is the copy that ships inside Happ, so the person installs one App Store app
#       and nothing else; `/usr/bin/python3` is deliberately not used, because on a Mac
#       without developer tools it opens an installer dialog instead of running.
# HOW:  scripts/client-setup-macos.sh --subscription URL [--direct-suffix SUFFIX]...
#             install for the macOS account running it
#       scripts/client-setup-macos.sh --subscription URL [--direct-suffix SUFFIX]... --bundle FILE
#             write FILE (mode 600, it holds a bearer credential) to send to that person;
#             they run `bash FILE`. Refused inside this repository.
#       scripts/client-setup-macos.sh --subscription URL [...] --print-runner
#             print the runner that would be installed, and change nothing
#       Unknown argument: exit 2. Missing or malformed value: exit 1 with a sentence.

set -euo pipefail

# Filled in by --bundle and by nothing else; empty in the repository.
BUNDLED_SUBSCRIPTION=""
BUNDLED_DIRECT_SUFFIXES=""

# Client-side choices, not fleet data — none of them names a node, a provider or a country.
SING_BOX=/Applications/Happ.app/Contents/MacOS/tun/sing-box

die()   { echo "client-setup-macos: $1" >&2; exit "${2:-1}"; }
usage() { sed -n '/^# HOW:/,/^# *Unknown argument/p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }
# Checked per argument, before it joins the space-separated list: checked after, a value
# with a space in it ("exa mple") would split into two valid-looking suffixes.
valid_suffix() {
  printf '%s' "$1" | grep -Eq '^[a-z0-9-]+(\.[a-z0-9-]+)*$' \
    || die "--direct-suffix '$1' is not a domain suffix (lowercase; punycode for a non-Latin one, e.g. xn--example)"
}

SUBSCRIPTION="$BUNDLED_SUBSCRIPTION"
DIRECT_SUFFIXES="$BUNDLED_DIRECT_SUFFIXES"
BUNDLE=""
PRINT_RUNNER=""
while [ $# -gt 0 ]; do
  case "$1" in
    --subscription)  [ $# -ge 2 ] || die "--subscription needs a URL"; SUBSCRIPTION="$2"; shift 2 ;;
    --direct-suffix) [ $# -ge 2 ] || die "--direct-suffix needs a domain suffix"; valid_suffix "$2"
                     DIRECT_SUFFIXES="${DIRECT_SUFFIXES:+$DIRECT_SUFFIXES }$2"; shift 2 ;;
    --bundle)        [ $# -ge 2 ] || die "--bundle needs a file path"; BUNDLE="$2"; shift 2 ;;
    --print-runner)  PRINT_RUNNER=1; shift ;;
    *)               echo "client-setup-macos: unknown argument: $1" >&2; usage ;;
  esac
done

[ -n "$SUBSCRIPTION" ] || die "pass --subscription with the person's subscription URL (it is never defaulted)"
case "$SUBSCRIPTION" in
  https://*/*) ;;
  *) die "--subscription must be an https:// URL, got: $SUBSCRIPTION" ;;
esac
case "$SUBSCRIPTION" in
  *[[:space:]\"\'\\]*) die "--subscription contains a character a URL never holds" ;;
esac
for s in $DIRECT_SUFFIXES; do valid_suffix "$s"; done   # a bundle's baked-in list, too

# ---------------------------------------------------------------- --bundle
if [ -n "$BUNDLE" ]; then
  repo=$(cd "$(dirname "$0")/.." && pwd -P)
  dir=$(cd "$(dirname "$BUNDLE")" 2>/dev/null && pwd -P) || die "the folder for --bundle does not exist: $(dirname "$BUNDLE")"
  case "$dir/" in
    "$repo"/*) die "refusing to write a subscription (a bearer credential) inside the repository: $BUNDLE" ;;
  esac
  out="$dir/$(basename "$BUNDLE")"
  ( umask 077
    while IFS= read -r line || [ -n "$line" ]; do
      case "$line" in
        'BUNDLED_SUBSCRIPTION=""')    printf 'BUNDLED_SUBSCRIPTION="%s"\n' "$SUBSCRIPTION" ;;
        'BUNDLED_DIRECT_SUFFIXES=""') printf 'BUNDLED_DIRECT_SUFFIXES="%s"\n' "$DIRECT_SUFFIXES" ;;
        *) printf '%s\n' "$line" ;;
      esac
    done < "$0" > "$out" )
  chmod 600 "$out"
  echo "wrote $out — it holds this person's subscription; send it to them only."
  echo "they run, in Terminal:  bash ~/Downloads/$(basename "$out")"
  echo "then, in a new Terminal window, disconnect Happ and type:  vpnon"
  exit 0
fi

# ---------------------------------------------------------------- the runner
# Written to ~/hashi-vpn.sh with the two placeholders filled. Kept as a function that
# prints a quoted heredoc rather than a $(...) capture: bash 3.2, the macOS default,
# misparses `case` patterns inside a command substitution.
runner() {
cat <<'RUNNER'
#!/bin/bash
# hashi VPN for macOS without Happ's tunnel — installed by scripts/client-setup-macos.sh.
#   sudo bash ~/hashi-vpn.sh                 connect (vpnon does this in the background)
#   bash ~/hashi-vpn.sh --check              build the config from the subscription and validate it
#   bash ~/hashi-vpn.sh --config-from FILE   print the config built from a saved subscription
# Every route in the subscription goes into one "auto" group that uses the fastest one that
# answers; hashi's own hosts and the direct suffixes bypass the tunnel.

SUB_URL="__SUBSCRIPTION__"
DIRECT_SUFFIXES="__DIRECT_SUFFIXES__"
SB=/Applications/Happ.app/Contents/MacOS/tun/sing-box

field() { printf '%s' "$1" | tr '&' '\n' | sed -n "s/^$2=//p" | head -1; }

build_config() {   # build_config <base64 subscription> -> JSON on stdout, summary on stderr
  local s="$1" lines outs="" tags="" ips="" iprule="" sfx="" sfxdns="" sfxroute="" l frag name body uuid rest hostport query host port tag domains
  while [ $(( ${#s} % 4 )) -ne 0 ]; do s="$s="; done
  lines=$(printf '%s' "$s" | base64 --decode 2>/dev/null | tr -d '\r' | grep '^vless://')
  [ -n "$lines" ] || { echo "no route in the subscription" >&2; return 1; }
  domains="\"$(printf '%s' "$SUB_URL" | sed -E 's#^https?://([^/:]+).*#\1#')\""
  while IFS= read -r l; do
    frag=""; case "$l" in *'#'*) frag=${l##*#};; esac
    body=${l#vless://}; body=${body%%#*}
    uuid=${body%%@*}; rest=${body#*@}
    hostport=${rest%%\?*}; query=${rest#*\?}
    host=${hostport%:*}; port=${hostport##*:}
    # The route's node name, from a fragment like "Amsterdam%20%C2%B7%20leaf-ams2".
    name=${frag##*%C2%B7%20}; { [ -n "$name" ] && [ "$name" != "$frag" ]; } || name=$host
    tag="$name:$port"
    flow=$(field "$query" flow); fp=$(field "$query" fp)
    outs="$outs$(printf '{"type":"vless","tag":"%s","server":"%s","server_port":%s,"uuid":"%s","flow":"%s","domain_resolver":"local","tls":{"enabled":true,"server_name":"%s","utls":{"enabled":true,"fingerprint":"%s"},"reality":{"enabled":true,"public_key":"%s","short_id":"%s"}}},' \
      "$tag" "$host" "$port" "$uuid" "$flow" "$(field "$query" sni)" "${fp:-chrome}" "$(field "$query" pbk)" "$(field "$query" sid)")"
    tags="$tags\"$tag\","
    if printf '%s' "$host" | grep -Eq '^[0-9.]+$'; then
      case "$ips" in *"\"$host/32\""*) ;; *) ips="$ips,\"$host/32\"";; esac
    else
      case "$domains" in *"\"$host\""*) ;; *) domains="$domains,\"$host\"";; esac
    fi
  done <<< "$lines"
  ips=${ips#,}
  [ -n "$ips" ] && iprule="{\"ip_cidr\": [$ips], \"outbound\": \"direct\"},"
  for x in $DIRECT_SUFFIXES; do sfx="$sfx\"$x\","; done
  if [ -n "$sfx" ]; then
    sfxdns=",{\"domain_suffix\": [${sfx%,}], \"server\": \"local\"}"
    sfxroute=",{\"domain_suffix\": [${sfx%,}], \"outbound\": \"direct\"}"
  fi
  cat <<JSON
{
 "log": {"level": "warn"},
 "dns": {
  "servers": [{"type": "https", "tag": "remote", "server": "1.1.1.1", "detour": "auto"},
              {"type": "local", "tag": "local"}],
  "rules": [{"domain": [${domains}], "server": "local"}${sfxdns}],
  "final": "remote", "strategy": "ipv4_only"
 },
 "inbounds": [{"type": "tun", "tag": "tun-in", "address": ["172.19.0.1/30"], "mtu": 1400,
               "auto_route": true, "strict_route": true, "stack": "system"}],
 "outbounds": [
  {"type": "urltest", "tag": "auto", "outbounds": [${tags%,}],
   "url": "https://www.gstatic.com/generate_204", "interval": "30s", "tolerance": 100},
  ${outs}
  {"type": "direct", "tag": "direct"}
 ],
 "route": {
  "rules": [{"action": "sniff"},
            {"protocol": "dns", "action": "hijack-dns"},
            {"ip_is_private": true, "outbound": "direct"},
            ${iprule}
            {"domain": [${domains}], "outbound": "direct"}${sfxroute}],
  "final": "auto", "auto_detect_interface": true, "default_domain_resolver": "local"
 },
 "experimental": {"clash_api": {"external_controller": "127.0.0.1:19090"}}
}
JSON
  echo "routes: $(printf '%s' "${tags%,}" | tr -d '"' | sed 's/,/, /g')" >&2
}

if [ "${1:-}" = "--config-from" ]; then
  [ -r "${2:-}" ] || { echo "--config-from needs a readable file" >&2; exit 1; }
  build_config "$(cat "$2")"; exit $?
fi

[ -x "$SB" ] || { echo "sing-box not found at $SB (is Happ installed?)"; exit 1; }

if [ "${1:-}" = "--check" ]; then
  tmp=$(mktemp -t hashi-vpn); SUB=$(curl -s -m 15 "$SUB_URL")
  [ -n "$SUB" ] || { echo "could not fetch the subscription"; rm -f "$tmp"; exit 1; }
  build_config "$SUB" > "$tmp" && "$SB" check -c "$tmp" && echo "config OK"; rc=$?; rm -f "$tmp"; exit $rc
fi

[ "$(id -u)" -eq 0 ] || { echo "run it with sudo (or use the vpnon command)"; exit 1; }
if netstat -rn -f inet | grep -Eq '^(0/1|1|128\.0/1) '; then
  echo "another VPN (Happ or OpenVPN) is on - turn it off first, then run vpnon again"
  exit 1
fi

HOME_DIR=$(eval echo "~${SUDO_USER:-$USER}")
STATE="$HOME_DIR/.hashi-vpn"; CFG="$STATE/config.json"
mkdir -p "$STATE" && chmod 700 "$STATE"
umask 077   # the config holds this device's credential
SUB=$(curl -s -m 15 "$SUB_URL")
if [ -n "$SUB" ] && build_config "$SUB" > "$CFG.new" && "$SB" check -c "$CFG.new"; then
  mv "$CFG.new" "$CFG"
else
  rm -f "$CFG.new"
  [ -s "$CFG" ] || { echo "could not fetch the subscription and no saved config exists"; exit 1; }
  echo "could not refresh the config - using the last saved one"
fi
echo "connecting..."
exec "$SB" run -c "$CFG"
RUNNER
}

filled_runner() {
  runner | while IFS= read -r line || [ -n "$line" ]; do
    line=${line//__SUBSCRIPTION__/"$SUBSCRIPTION"}
    line=${line//__DIRECT_SUFFIXES__/"$DIRECT_SUFFIXES"}
    printf '%s\n' "$line"
  done
}

if [ -n "$PRINT_RUNNER" ]; then filled_runner; exit 0; fi

# ---------------------------------------------------------------- install
[ "$(uname)" = Darwin ] || die "installing is for macOS; on another system use --bundle or --print-runner"
[ -x "$SING_BOX" ] || die "Happ is not installed (no sing-box at $SING_BOX). Install Happ from the App Store, then run this again."

( umask 077; filled_runner > "$HOME/hashi-vpn.sh" )
chmod 700 "$HOME/hashi-vpn.sh"

# The three commands live between markers, so a re-run replaces them instead of appending.
ZRC="$HOME/.zshrc"; touch "$ZRC"
tmp=$(mktemp)
awk '/^# >>> hashi-vpn >>>$/{skip=1} !skip{print} /^# <<< hashi-vpn <<<$/{skip=0}' "$ZRC" > "$tmp" && cat "$tmp" > "$ZRC" && rm -f "$tmp"
cat >> "$ZRC" <<'ZSH'
# >>> hashi-vpn >>>
unalias vpnon vpnoff vpnwhich 2>/dev/null
vpnon()    { sudo -b bash ~/hashi-vpn.sh > /tmp/hashi-vpn.log 2>&1; sleep 4; tail -3 /tmp/hashi-vpn.log; }
vpnoff()   { sudo pkill -f '[.]hashi-vpn/config[.]json' && echo "hashi VPN off" || echo "hashi VPN was not running"; }
vpnwhich() { local r; r=$(curl -s -m 2 http://127.0.0.1:19090/proxies/auto); if [ -n "$r" ]; then echo "via $(printf '%s' "$r" | grep -o '"now": *"[^"]*"' | sed 's/.*"\([^"]*\)"$/\1/')"; else echo "hashi VPN is off"; fi; }
# <<< hashi-vpn <<<
ZSH

echo "installed ~/hashi-vpn.sh and the vpnon / vpnoff / vpnwhich commands"
if bash "$HOME/hashi-vpn.sh" --check; then
  echo
  echo "Done. If hashi VPN is running, type vpnoff first. Then open a NEW Terminal window,"
  echo "disconnect Happ, and type: vpnon"
else
  echo
  echo "Installed, but the check above failed — send this window's text to whoever sent you this file."
  exit 1
fi
