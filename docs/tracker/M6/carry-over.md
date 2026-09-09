# M6 — carry-over

Non-blocking findings left open, with the reason each was left.

- **The runbook still tells operators to hand-write `deploy/docker-compose.public.yml`**,
  which the infra rulebook itself calls a bug in this zone: *"a documented
  `docker compose` incantation that is not in the Makefile"*. Shipping a public
  overlay plus a Make target is an **exposure decision for the owner** — what a
  host publishes to the internet is not a script's call — which is why M6.1 chose
  "do not print an address" over "publish one".

- **`deploy/e2e.env`'s comment still says "double every `$`"**. Still true for
  `hash_password()` used directly; now one step behind the CLI, which pre-escapes.

- **`Settings` raises `OperatorHashMalformed(RuntimeError)`** where every other
  invalid setting in that file raises pydantic `ValidationError`. Deliberate —
  pydantic embeds the offending input, and that input is a credential. Nothing
  catches `ValidationError` around `Settings()` today, but a future caller that
  wraps config loading would miss this one. Recorded because the divergence is
  invisible until it matters.

## Verified NOT a problem, recorded so it is not re-litigated

- **The database was never at risk from the attestation churn.** It is pulled by
  tag, not built. Only `control` and `caddy` were recreated.
- **`verify_password`'s new `validate=True` base64 decoding rejects no genuine
  hash** — standard `b64encode` output always passes it. It only stops a value
  already chewed by an interpolator from decoding to something plausible.
- **`test_builds_converge.py` generalises.** The reviewer injected a synthetic
  fourth `up -d --build` target with no guard and watched it fail, so a new
  stack-starting target inherits the rule rather than needing to be remembered.
- **`MemoryError` is caught only around the `hashlib.scrypt` call**, not around
  the request path, so a genuine host OOM still surfaces elsewhere rather than
  being absorbed into a silent login denial.
