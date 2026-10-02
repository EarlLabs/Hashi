# M31 — carry-over: what only the real-host re-walk can confirm

Code, tests and a disposable stand only. **No real host was dialled, written to or
restarted by M31.** The orchestrator's re-walk is what accepts it; this is the list of what
it must see with its own eyes, in priority order.

1. **M31.1 — no ACME before publication.** On a fresh restore (`make restore-from-bucket`)
   and on a fresh `make panel-bootstrap`: `/data/caddy/acme` in the `caddy-data` volume
   holds **no** account, lock or challenge while the stack is unpublished. Then, with DNS
   pointing at the host, `make up-panel-over-ssh` (or `make up-panel`): Caddy is recreated,
   obtains a public certificate for `HASHI_PUBLIC_HOST`, and `/sub/{token}` serves with a
   certificate a stock client accepts. (Stand proof: `caddy adapt` in both shapes — e2e
   `test_an_unpublished_stack_asks_no_public_ca.py`. Not proven: the switch on real ACME.)
   Watch for one thing the stand cannot show: whether Caddy, on switching issuer, picks up
   the internal certificate it stored for the same name instead of asking ACME.
2. **M31.2 — the setting reaches the container.** `HASHI_FINDING_REMEASURE_INTERVAL=0` in
   `.env`, publish, `docker compose exec control env | grep REMEASURE` shows `0`. After a
   `restore-from-bucket`, before publishing: the same command shows `0` and the closing
   screen said "It dials no node on its own"; after publishing with the line blank, the
   value is blank (default 60).
3. **M31.3 — the walk's repair, on the real daemon.** On the leaf: `awg set <if> peer
   <key> remove`, then `POST /api/nodes/{id}/apply` → **200**, `restarted_to_serve`
   names the transport, the hop handshakes again. And the not-repairable case (e.g. a wrong
   peer key in the record): 502 naming the restart, no "probe it in a minute". Confirm a
   healthy re-apply restarts nothing (no session drop for users).
4. **M31.4** — `GET /api/nodes` shows `last_probe_finding` / `last_probe_at` after a 502 that
   kept a node in service.
5. **M31.5** — an apply of `vless-reality` returns `serving_port_only: ["vless-reality"]`.
6. **M31.6/8/9** — a restore of an artifact with rows prints its counts, `compose project:
   hashi`, "Restarted the control plane on the restored database.", and the one wrong-key
   sentence; an empty artifact prints "NO nodes and NO users" twice.
7. **M31.7** — on a host without bash, `make restore-from-bucket` prints the bash sentence
   and exits 1 (not 127).
8. **M31.10** — Shape B's documented `ssh_user` / `ssh_host` for an entry on the control
   plane's own host, followed as written.

## Known, not fixed here

- **The bucket-restore e2e scenarios were SKIPPED in this run** (S13–S17 in
  `tests/e2e/infra/test_restore_proves_the_backup.py`: the pinned minio image could neither
  be pulled nor found locally). Their M31 assertions — counts on the closing screen, "It
  dials no node on its own", "Restarted the control plane" — are therefore unrun; the file
  restore path (`make restore`, which shares `command_restore`) ran and passed with the
  restart and the counts. Item 2 and 6 above are the first end-to-end run of the bucket path.

- The 3 edge failures in `tests/edge/test_upstream_validation.py` are environmental (the
  system `wg-quick` calls `sudo`, which the sandbox blocks). Reported, not fixed.
- The panel shows no port-only qualifier on a healthy apply (M31.5 is API-only, recorded
  in `docs/decisions.md`). If the owner wants the panel to say it, that is a follow-up.
- `make restore` (the file variant) does not hold the re-measure loop — it only restarts,
  because recreating `control` from the base file would drop a dev stack's published port.
