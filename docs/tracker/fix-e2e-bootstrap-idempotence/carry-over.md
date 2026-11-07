# fix-e2e-bootstrap-idempotence — carry-over

Non-blocking, as background. Do not fix as part of another step.

- The Makefile's `up`, `up-dev`, `up-panel`, `up-panel-over-ssh` and `e2e-up` still use
  `up -d --build`, so on a compose with this behaviour the `up` after a rebuild recreates
  `control` and `caddy` once more. Left alone to keep this fix to the failing path. No scenario
  covers it. It costs a brief restart and no data, because `db` is pulled.
