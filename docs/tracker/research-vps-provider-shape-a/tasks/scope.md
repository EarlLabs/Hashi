# Scope — research-vps-provider-shape-a

**Phase 0 (who owns this question).** Technical *and* product: "what does it cost
to run, is it feasible" is architect territory, but "which provider do we trust
with the fleet's first host" is a decision about *what*. `/product` is not
installed in this project (solo topology, `charter.md` §Fleet), so both halves
fall to me — the documented fallback, not the norm. The report therefore
recommends and does not decide: §7 leaves three questions to the owner.

**Phase 1 (scope).** No clarifying questions were sent. One was tempting — which
payment rail the owner can actually use — but the answer partitions the shortlist
rather than blocking it, so the report covers every rail and asks the question at
the end (§7.1) instead of stopping the pipeline for it.

**Brief.** Decisive axes, in the order they turned out to matter:
1. Is the provider's ASN already subject to the TSPU data-cap?
2. Will the provider accept a Russian customer at all?
3. Is the provider sanctioned (OFAC / EU)?
4. Which payment rails work from Russia in 2026?
5. KYC demands; AUP tolerance for VPN/proxy; IP-replacement policy.
6. Latency from Russia; price.

**Out of scope.** Testing any provider (nothing is rented yet); legal advice; and
recommending a shape — the owner has chosen Shape A and the report takes that as
given while naming what it can and cannot prove.
