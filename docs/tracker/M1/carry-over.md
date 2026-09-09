# M1 — carry-over

Non-blocking findings left open, with the reason each was left. Read them as
BACKGROUND: they tell you what is known-wrong so you do not mistake it for the
intended design. Do not fix them as part of another step.

## Read this one before starting M2

- **`edge/health/probe.py` resolves a config path with `config_path(...)` where it
  should use `config_path_for(...)`.** The former defaults to
  `ConfigFormat.XRAY_JSON` and therefore the `.json` extension. It is latent
  today only because the single live transport is an Xray one. **The moment a
  WireGuard-family transport exists — which is exactly M2 — drift detection will
  look for a `.conf` config at a `.json` path, not find it, and report that
  transport permanently drifted.**

  Left out of M1 deliberately: it is a pre-existing defect in the *drift* path,
  orthogonal to M1's *staleness* fix, and fixing it inside M1 would have been the
  scope creep this convention exists to prevent. It is one line. The reviewer
  agreed with deferring it and disagreed — correctly — with not writing it down,
  which is why this file now exists.

## Process, for the next shared-`edge`-API change

- **An intermediate commit was red, and the zone rule is what made it so.**
  `services_for`'s signature changed; it is an `edge` API that `control` calls;
  cross-zone work may not land in one diff. So at the edge-only commit,
  `make test-control` fails by construction (19 failed, 6 errors), and a
  `git bisect` or a per-commit CI would land on it. Each zone's gate is green at
  its own commit for its own zone, and HEAD is fully green, which is the standard
  M4 set — but the gap is real.

  **The shape to use next time:** additive first. Land the new signature
  alongside the old one (or under a temporary name), migrate the caller in the
  second commit, drop the old shape in a third. Every intermediate commit then
  builds, and the zone rule is still honoured.

## Minor

- **`loaded_digests`' `running != "true"` filter is defensively dead.**
  `docker compose ps -q` without `-a` never returns a stopped container's id, so
  `docker inspect` never sees one to filter out. The check is correct, just not
  reachable through the documented pipeline, and its test validates the filter in
  isolation rather than the real mechanism (omission from `ps -q`). Worth a
  comment so a later reader does not assume it is load-bearing.
