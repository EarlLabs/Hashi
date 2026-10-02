# M31 — step notes (2026-10-02)

Asked by the owner on 2026-10-02: fix every defect the real-host field walk and the restore
walk found that day. Branch `task/M31`, stacked on `task/M26-fix-round-5` (baseline
`e57fb35`). Solo topology; closed with the review-loop skill (`reviewer-strict`). **No real
host was touched.** Decisions: `docs/decisions.md`, the three 2026-10-02 rows tagged M31.

| step | what changed | test red before it |
|---|---|---|
| M31.1 | Caddyfile public site `tls {$HASHI_PUBLIC_TLS:internal}`; `docker-compose.public.yml` sets it to the ACME email. Runbook (DNS, `caddy_data`, "does not do" 2) and the restore's closing screen say "move DNS, then publish". | `tests/infra/test_caddyfile.py::test_the_public_site_defaults_to_its_own_ca`, `::test_only_the_publishing_overlay_switches_public_issuance_on`; e2e `test_an_unpublished_stack_asks_no_public_ca.py` (real `caddy adapt`, both shapes) |
| M31.2 | Every optional `Settings` field passed through the base compose as `${VAR:-}`; `Settings(env_ignore_empty=True)`; `.env.example` documents the interval and `0`; e2e stack pins them blank; restore-from-bucket holds the interval at 0 until publication. **Why the rule missed it:** it only asked about variables with an `^VAR=` line in `.env.example`, and this one (and five the Settings screen names) had none; it now asks the settings model, with two reasoned exceptions. | `tests/infra/test_compose.py` (3 red), `tests/control/test_a_blank_setting_takes_its_default.py` (1 red), `tests/infra/test_what_a_restore_says_it_did.py::test_a_rebuild_from_the_bucket_holds_the_remeasure_loop`, e2e S16 |
| M31.3 | `node_stack.restart_services` (edge); `apply_node` reads lives before `up -d` and restarts once a refused config on the pushed digest that `up -d` left alone, then measures again; advice depends on what was tried; `restarted_to_serve`, panel toast. | `tests/control/test_an_apply_repairs_what_up_d_left_alone.py` — the walk's exact 502 text reproduced on the old code; `tests/edge/test_a_daemon_can_be_restarted_on_the_file_it_has.py` |
| M31.4 | `NodeResponse.last_probe_finding`, `last_probe_at`. | same file, `test_the_api_shows_the_finding_an_apply_left_on_the_row` |
| M31.5 | `ApplyResponse.serving_port_only`; schema contract restated. | same file, `test_a_transport_only_its_port_can_confirm_is_named_as_such` |
| M31.6 | `held_counts` after every restore; "NO nodes and NO users" warning, again on the closing screen. | `tests/infra/test_what_a_restore_says_it_did.py`, e2e S16 |
| M31.7 | `need_bash` before every Make recipe that runs a `scripts/*.sh`; runbook prerequisite list names bash. | same infra file (the guard is executed under a PATH with no bash) |
| M31.8 | The restore restarts the control plane itself and waits for health; one wrong-key sentence for both paths. | same infra file; e2e S16 |
| M31.9 | The confirmation names the compose project from the running db container's label. | same infra file |
| M31.10 | Runbook Shape B: `node-bootstrap --user <node-account>` from a sudo account, `ssh_user` = that account, `ssh_host` = E's public address, and why. | docs only |

Tests changed rather than added, and why none is weaker:
- `test_a_bare_host_can_finish_the_restore.py::test_the_restore_does_not_end_by_unpublishing_the_host`
  — still forbids `make down && make up`; `make restart-control` is now the fallback text.
- `test_the_restore_comes_from_the_bucket.py::test_the_last_thing_on_the_screen_is_what_it_did_not_do`
  — the wrong-key sentence is a shared variable; the test resolves it and asserts the same words.
- `test_compose.py` — the pass-through rule asks the settings model instead of `.env.example`
  (strictly wider), and the blank-allowed set is derived from fields with defaults.
- `conftest.accepting_nodes` pins `restart_services` as an accepted step, like `restart`.
- e2e S16 — asserts the restart, the counts and the hold instead of the old instruction.

## Appended 2026-10-02 — two lows from the real-host re-walk, fixed on `task/M27.8`

Reported by the orchestrator from its re-walk of M31 and M24 on the real hosts; fixed in
commits tagged `M31.10 (infra)` and `M31.10 (control)` (the tag the request named — not the
M31.10 step of this milestone, which is the Shape B account text).

- **infra** — `make restore-from-bucket` printed the wrong-key paragraph twice, word for word.
  `command_restore` now skips it when `CLOSING_SCREEN_FOLLOWS=1`, which only
  `command_restore_from_bucket` sets; its closing screen keeps it as the last paragraph.
  Test: `tests/infra/test_what_a_restore_says_it_did.py::test_the_bucket_path_says_the_wrong_key_sentence_once`
  (red on the previous script).
- **control** — an applied, serving `amneziawg` row on the Nodes screen still said "the node
  serves it once applied". `console._standing` takes the row's own `applied_at`;
  `OFFER_NOT_IN_THE_LINK_APPLIED` is the applied variant. Test:
  `tests/control/test_the_panel_hands_over_the_config_file_link.py::test_an_applied_config_file_row_does_not_say_it_will_serve_once_applied`
  (red on the previous console).
