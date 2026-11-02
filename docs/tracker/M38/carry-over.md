# M38 — carry-over
Non-blocking findings left open, with the reason each was left. Read them as
BACKGROUND: they tell you what is known-wrong so you do not mistake it for the
intended design. Do not fix them as part of another step.

## M38.1 (review round 1: clean; 3 Low)

- Low — `_behind_block`'s docstring says "`console.not_pushed` composes the same sentence that way": a sentence about another module's behaviour. Name it and stop.
- Low — the `APPLY_IT` comment ("`/apply` is M38.2's…") and the usage line promise a command that does not exist until M38.2; delete the comment clause when it lands.
- Low — a badly wrapped line in the module's HOW paragraph ("could\n not update"). Cosmetic.
- Note — `ruff format --check` flags a pre-existing line in `onboarding.py` (~L217); the gate runs `ruff check` only. Not this milestone's.

## M38.2 (review round 1: clean; 2 Low; one pre-existing surface for the owner)

- Low — the module's HOW block's `/apply` paragraph is long. Taste.
- Low — the new e2e test's docstring says "the ceiling is for the poll"; odd wording, not wrong.
- Note, by design — "applying …" precedes the two 409 refusals, the same shape as `/adduser`'s "adding…" (validation lives in the service).
- **For the owner — pre-existing, outside M37/M38, found while building M38.2:** `POST /api/nodes/{id}/apply` answers a checker refusal (`ConfigRefused`) with a sentence built to quote the upstream checker's output, and that output can carry the node's key material; the M38.2 test establishes this on the API envelope as its premise. The bot deliberately does not relay that sentence. The operator-only API and the panel still do. Also pre-existing: `apply._record_failure` logs a failure's full reason at ERROR (not reached by a checker refusal). A milestone of its own, if the owner wants it: the checker's output should never join a sentence a person or a log sees.
