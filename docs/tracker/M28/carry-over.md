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
