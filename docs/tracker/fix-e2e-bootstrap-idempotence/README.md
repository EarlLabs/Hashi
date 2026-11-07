# fix-e2e-bootstrap-idempotence

**Type:** fix
**Zone:** infra (`scripts/**`, `tests/infra/**`)
**Symptom:** on CI, `tests/e2e/infra/test_panel_bootstrap.py::test_running_it_again_changes_nothing`
fails with "the second run replaced containers". `panel-bootstrap.sh` says a second run
recreates nothing, and on compose 2.38.2 it recreated `control` and `caddy` once.
**Expected:** a second run of the script leaves every container in place.
**Root cause, measured on engine 28.0.4, compose 2.38.2, buildx 0.38.1:** both image IDs were
identical across the two runs, so nothing was rebuilt. A container created by `up -d --build`
from an image built in the same call had no `com.docker.compose.image` label, and the next
`up` read the missing label as an outdated image. `db` is pulled, kept its label and was never
replaced.
**Reproduction:** on those versions, run `scripts/panel-bootstrap.sh` twice with the env file
the scenario writes and compare `docker compose ps -q`. Seen in CI runs 42010652973 (`105c731`)
and 38367192152 (`a63f581`).
