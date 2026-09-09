# M7 — outcome

**Three steps, one commit plus a fix commit, `infra` zone. Two review rounds.**
Round 1 returned `0 critical, 0 high`. **The field then found a blocking defect
that no review and no test could have caught**, and round 2 verified the fix and
returned CLEAN with one Low (two stale comments, corrected inline).

**Acceptance: yes, discharged in the field.** Evidence in `field-proof.md`, taken
from the leaf in Amsterdam — a genuinely public network rather than a second
address on the same host.

**Gate at close:** `make verify` — 218 control, 230 edge (3 skipped), 147 infra,
**140 e2e**.

## This milestone is the run's clearest argument for field acceptance

M7 passed a review in which the reviewer reproduced the port-80 redirect leak,
verified the openssl X25519 fallback five times against `wg pubkey`, and
mechanically deleted a `log { output discard }` block to confirm the test named
it. Everything it checked was true.

**The console was then unreachable by every route the moment it met a real host.**

Nothing was misconfigured: the tunnel was up, the publication restricted exactly
as designed, and Caddy held certificates for both private addresses. The cause is
that **a TLS client sends no SNI when the host is an IP literal** — OpenSSL
silently refuses to set one, which the round-2 reviewer proved by packet-capturing
two handshakes — and a WireGuard tunnel hands you an address. With several
certificates and no name to look up, Caddy aborts.

**Why the suite could not see it:** the e2e stack gave the console
`console.localhost`, a **name**. Names send SNI. The field does not use names.
And the one client inside the stack that might have noticed — busybox in Caddy's
own image — sends SNI even for an address.

The same defect was already live on the **public** site, so `/sub/{token}` was
dead for any client dialling an address. Nobody had asked.

## What was fixed, and the decision it forced

`default_sni` is a **global** Caddy option — no per-site form exists, and
`tls internal { default_sni … }` is rejected by the adapter at 2.8.4, which was
tried. So one value serves both listeners, and the choice is a real trade,
recorded in `docs/decisions.md`: pointing it at the console discloses an
unroutable tunnel address to a no-SNI client on `:443`; pointing it at the public
host gives the owner a certificate-name error on **every** visit to their own
console, forever. The first was taken — training the single operator to click
through TLS warnings on the surface that must never be impersonated is the worse
failure, and that habit outlives the warning.

## The lasting half is the scenario, not the fix

`tests/e2e/infra/test_a_client_that_sends_no_sni_can_reach_the_sites.py`
performs an explicitly SNI-less handshake, run from the control container because
it holds the only aimable TLS client in the stack. **And the test stack's console
is now an address rather than a name** — which is the change that makes the whole
class of defect visible, not just this instance of it.

A third scenario uses the ordinary SNI-sending client as a guard, so a red run
cannot be misread as "the stack is broken" when it means "SNI is still broken".
The round-2 reviewer confirmed that guard stays green against the broken
configuration, which is what makes it a discriminator.

## Honest limits

- **ACME was never exercised.** The entry host has no DNS record, so
  `HASHI_PUBLIC_HOST` is its IP and Caddy issues an internal certificate. A public
  CA will not issue for a bare IP at all, so `/sub/{token}` needs a real name
  before a friend can use it. Recorded in `docs/decisions.md`; nothing yet refuses
  an address there at boot, which would be a `control` change.
- **No phone on a mobile network was tested.** Whether the obfuscated handshake
  survives ТСПУ on the owner's own network is the question they raised and the one
  thing this fleet cannot answer.
