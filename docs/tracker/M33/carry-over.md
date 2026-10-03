# M33 — what the real-host walk must check

Built on `task/M33` (code + docs). Nothing here touched a real host. The walk is the
orchestrator's; these are the observations no test can make. Paths below assume the
bootstrap user's home; the bootstrap prints the real ones.

1. **The live host's current state first.** It carries the walker's hand-made setup: the
   `/etc/amnezia/amneziawg/awg-mgmt.conf` symlink, `awg-quick@awg-mgmt` enabled, and a
   docker drop-in `10-hashi-awg-mgmt.conf`. Pull `task/M33`, re-run `make panel-bootstrap`
   with `.env` unchanged: the run must say the tunnel is kept, list every device as
   `already a peer`, print no key, and leave `awg-mgmt.conf` byte-identical
   (`sha256sum` before and after).
2. **ip_nonlocal_bind, the delivery half of finding 3.** Run the printed `sysctl` lines.
   Then `sudo systemctl stop awg-quick@awg-mgmt`, `make up-panel` (or restart caddy): Caddy
   must come up, and `curl -sS -o /dev/null -w '%{http_code}' https://<public host>/sub/<a
   real token>` must answer 200 **from outside**. `sudo systemctl start awg-quick@awg-mgmt`:
   the console must answer over the tunnel without restarting Caddy.
3. **Reboot.** `sudo reboot`. After it: `ip -brief link | grep awg` shows exactly one
   `awg-mgmt`; delivery answers from outside; the console answers over the tunnel from the
   laptop and the phone with no `ssh -L` running. The docker drop-in can stay or go — the
   decision row says it is not needed; if it is removed, reboot once more and re-check.
4. **Removing a device.** Take one device out of `HASHI_MGMT_PEERS`, re-run: `==> removed
   <name> (<route>)`. Before the reload that device still reaches the console; after
   `sudo systemctl reload awg-quick@awg-mgmt` it does not, and `sudo awg show awg-mgmt
   peers` no longer lists its key. The other device stays connected through the reload.
5. **Adding a device**, with `HASHI_MGMT_CONFIGS_TO=~/mgmt-devices make panel-bootstrap`:
   one `0600` file appears, nothing secret in the terminal; `qrencode -t ansiutf8 <
   <file>` on the laptop scans cleanly into the AmneziaWG phone app (finding 6's em dash
   is gone); after `reload` the new device reaches the console. Delete the directory.
6. **The refusal.** Change `HASHI_MGMT_PORT` in `.env` and re-run: the bootstrap stops at
   the tunnel step naming the port with both values, the `mv ... .retired-<date>` line and
   `ufw delete allow <old port>/udp`; `awg-mgmt.conf` is unchanged. Put the port back.
   (Optionally walk the full "Starting the tunnel over" sequence from the runbook.)
7. **Old firewall rules.** `sudo ufw status` lists exactly one rule for the management
   port; any rule for a retired tunnel port is deleted.
8. **The fallback**: `ssh -L` + the runbook's `curl … /panel/login` → `200`.

Not provable by any test here: that the tunnel survives the owner's home or mobile network
(the charter's first criterion stays a field observation).
