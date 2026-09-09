# M6 — outcome

**Six steps.** M6.1, M6.2 and M6.3 were in the plan; M6.4, M6.5 and M6.6 were
appended during the field run. **Two review rounds** — round 1 found a Critical,
round 2 verified both fixes by reproduction and returned CLEAN.
`acceptance: no` per the plan.

**Gate at close:** `make verify` — the new gate — green: control 218, edge 230
(3 skipped), infra 110, and **130 e2e scenarios**, stand torn down.

## The Critical is the argument for this whole pipeline

The implementer built `OperatorHashMalformed` *specifically* so a malformed hash
could never reach a log, wrote the rationale down, and tested it against the
shapes compose actually produces. It then left one input shape that defeats the
entire mechanism: `_decoded()` parsed the cost fields **outside** its own
`try/except`, so `scrypt$notanumber$8$1$…` raised an uncaught `ValueError`,
pydantic wrapped it, and pydantic embeds the offending input — **the full
credential, salt and digest, in the boot-failure message.**

That is not carelessness. It is the blind spot of the person who chose the
design: every test they wrote covered the shape they had *seen*, and the shape
they had seen — compose eating the fields — leaves them empty, which the guarded
path already caught. A hand-typed or half-pasted hash is a different shape
entirely.

An independent reviewer constructing an input nobody had considered, and watching
the credential appear, is the value of the author not being the closer. The fix
brought a second one with it, unprompted: `hashlib.scrypt` raises `OverflowError`
on a cost that parses but exceeds a C unsigned long — a **well-formed** hash that
boots fine and then 500s on the login route, which the control rulebook says a
prober must not be able to distinguish from a wrong password.

**The lasting half is the test's shape.** `test_no_malformed_hash_ever_reaches_a_message`
asserts the hash appears in neither `str()` nor `repr()` of whatever was raised,
*however it was wrapped* — because asserting the exception **type** is precisely
the assertion that missed this.

## M6.5's cause was not in this repository

`panel-bootstrap.sh` claimed idempotency in its own header and an existing
scenario said otherwise. The cause: **BuildKit attaches a provenance attestation
recording when the build ran**, so a fully-cached rebuild still exports a
manifest with a new digest — and that digest is the image id compose compares
against the running container. `up -d --build` therefore recreated every
Dockerfile-built service on every run, and *which* one the scenario noticed
varied by build order.

Measured rather than inferred, and reproduced independently by the reviewer: two
cached builds gave different manifest digests with an identical image *config*
digest; with `BUILDX_NO_DEFAULT_ATTESTATIONS=1` both gave the same. `provenance:
false` in the compose `build:` block parses and **does not work** — compose's
bake path ignores it.

**A framing correction worth keeping.** The first telling of this — including
mine to the owner — was that every `make up` recreated the database. It did not:
the database is **pulled by tag, not built**, so it was never affected and no
data was ever at risk. The churn is `control` and `caddy`: a control-plane and
TLS restart on every routine deploy, and a `make up` that could not be used to
ask whether a stack was already converged. Smaller, and true.

## M6.6 — the gate, and why it existed to be built

`make test` excludes `tests/e2e/` deliberately, and correctly: *a gate that
silently needs Docker is a gate that gets skipped.* The defect was never that
exclusion — it was that **nothing else included those scenarios**. CI ran the same
three zone targets. So `tests/e2e/` was run by nobody, which is why
`panel-bootstrap.sh`'s own idempotency scenario had been failing since the day it
was written and was found by accident, eleven milestones into a field run.

`make verify` = `make test` + boot the stand + `tests/e2e/` + tear it down. A
missing Docker engine is a **failure with an explanation, never a skip**. CI gets
a plain job, not `continue-on-error` — an advisory job is a green tick with an
annotation nobody opens, which is the same hole one level up. `aikit.yml`'s
`verify_all` now points at it.

**The orchestrator was an instance of the finding.** Eleven milestones were gated
on `make test` because that is what `verify_all` said, and e2e ran only three
times all night, incidentally. The owner asked for the gate; it should not have
needed asking.
