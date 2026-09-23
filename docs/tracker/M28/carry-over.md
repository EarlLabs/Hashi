# M28 — carry-over
Non-blocking findings left open, with the reason each was left. Read them as
BACKGROUND: they tell you what is known-wrong so you do not mistake it for the
intended design. Do not fix them as part of another step.

## From M28.1, review round 1 — two copies of the corrected half-truth, Medium

Both confirmed by the reviewer, both outside M28.1's fence, **both folded into
M28.2's fence** because the sentence becomes true the moment `age` lands:

- **`docs/product/charter.md:236`** — *"the backup is encrypted with a key not
  stored beside it"*. Describes the whole artifact as encrypted, which is false
  of today's plain-SQL-plus-gzip dump; only a column subset is. Same
  operator-facing safety claim just corrected in the script and the runbook, one
  file over.
- **`Makefile:203-204`** — the `backup:` target's comment says the dump is
  *"useless without HASHI_SECRET_KEY"* with no mention that the rest is a
  plaintext fleet map. A softer half-truth by omission, on the surface
  (`make backup`'s own comment) most likely to be read at the moment of decision.

## From M28.2, review round 1 — the fixture keypair looks real to a scanner, Low

`tests/e2e/infra/test_restore_proves_the_backup.py` commits a disposable `age`
keypair. The reviewer judged it acceptable and verified it is a real, working pair that
never protects real data — the stack under test receives only the public half.

The residual: **an age key cannot carry a "fake" marker inside its encoding.** The
adjacent `HASHI_SECRET_KEY` fixtures literally spell `-not-real-0000…` in the value, so
they are self-evident even in a scanner alert that shows only the matched string. The
age identities are not, so a gitleaks- or push-protection-style scanner would flag them
as high-confidence hits and a human would have to open the file and read the comment to
dismiss them.

**No scanner is wired into this repository today** — `aikit.yml`'s `security:` block
deliberately has no `scan:` key, because none of gitleaks, osv-scanner or semgrep is
installed and adding one is an architect decision. **Left open because** the fix is a
one-line `# gitleaks:allow`-style annotation that is only meaningful once a scanner
exists, and choosing that scanner is the owner's.

## From M28.2 — a marginal timeout that is not this milestone's, Low

The builder's first `make verify` failed on
`tests/e2e/infra/test_panel_bootstrap.py::test_a_control_plane_that_never_answers_is_reported_as_a_failure`
with `TimeoutExpired` at its 600s subprocess cap, spent inside `docker build`. Diagnosed
rather than guessed: that test alone takes ~364s cold and ~79s warm, and this machine's
builder cache is ~10GB with the disk 64% full, so BuildKit GC evicts the `pip install`
layer. The reviewer corroborated both numbers on the same machine and confirmed the test
file is untouched by M28.2.

**Left open because** it is a pre-existing marginal cap under disk pressure, not a
regression. If it recurs on the fleet's dind, the cap is the thing to look at.
