# M1 — step notes

Conventions established here. They bind later steps, and later milestones in
this codebase, until something supersedes them. Follow them; do not relitigate.

## What "the node is running our config" means now

- **`node_stack.CONFIG_DIGEST_LABEL` = `io.hashi.config-digest`**, written onto
  each compose service by `services_for`, which now takes the rendered *configs*
  rather than their names. A changed config is therefore a changed service
  definition and `up -d` recreates the container by itself. One verb, unchanged.
- **`running_services()` is gone. Use `loaded_digests(connection)`** — service →
  the digest that container was *created with*. It has no other callers to update;
  there were none left behind.
- **Why labels and not something else.** A label is fixed when the container is
  created, so reading it back reports what the process was *started from*, not
  what happens to be on disk beside it — which is what every other check already
  reads. It needs no cooperation from the daemon inside, it is identical for every
  transport family (no protocol name in shared code), and it is *the same value*
  that made Compose recreate the container, so the two halves of the fix cannot
  disagree. Verified against a real Docker engine: `docker update` has no
  `--label`, so a running container's label cannot be rewritten and the read-back
  cannot lie by mutation.
- Rejected: start-time vs config mtime (a cross-machine clock comparison; an
  unrelated restart reads as fresh) and asking the daemon (protocol-specific).

## `stale` and `drifted` are different faults — keep them apart

- **`drifted`** — the file on disk differs from a fresh render.
- **`stale`** — the container is up on a config we did not push.

Folding staleness into drift would tell the operator that somebody edited a file
nobody touched, which is the same true-but-misleading shape this milestone is
about. The field proof shows exactly why: the stale node reported
`drifted: [], stale: ["vless-reality"]` — `drifted` was empty **and correct**,
because the file really did match. `HealthResponse.stale` is `[]` for an
unreachable node, never a guess.

## Test harness to reuse rather than rebuild

- **`tests/control/test_apply_must_reach_the_daemon.py::_FakeHost`** — a node as a
  shell plus a filesystem plus a container table, with `recreates=True/False`. It
  runs the *real* `node_stack` end to end. Point it with
  `host_for(monkeypatch, host)`, which must patch `NodeConnection` in **both**
  `services.apply` and `services.health` — they import the class, not the package.
- **`tests/edge/…::_FakeNode`** is the lighter unit-level version.
- Both deliberately still answer the pre-M1 `docker compose ps --services`
  question, so any future revert fails **by assertion** rather than by
  `AttributeError`. Keep that property.

**What these fakes do NOT prove, stated in both files' headers and worth
repeating here:** the control fake models exactly one rule of Docker — Compose
compares the desired service definition against the running container and leaves
it alone when they match. It does **not** prove that real Docker recreates on a
label change. That is M5.3's job, on a real stand. This milestone's whole lesson
is "renders but does not run", and a fake that models Docker's behaviour can
reproduce that same class of error one level up.

**The real proof is in `field-proof.md`** — on live hardware, with a real client.

## Operator-facing wording introduced here

`still running an older configuration: <names>` — used in apply's 502 body, in
`state_detail`, and in the health detail. It carries transport names only, never
a host or address. The panel's stale hint ends `Applying again recreates the
container.` Match these rather than inventing a fourth shape.
