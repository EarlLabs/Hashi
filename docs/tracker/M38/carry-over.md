# M38 — carry-over
Non-blocking findings left open, with the reason each was left. Read them as
BACKGROUND: they tell you what is known-wrong so you do not mistake it for the
intended design. Do not fix them as part of another step.

## M38.1 (review round 1: clean; 3 Low)

- Low — `_behind_block`'s docstring says "`console.not_pushed` composes the same sentence that way": a sentence about another module's behaviour. Name it and stop.
- Low — the `APPLY_IT` comment ("`/apply` is M38.2's…") and the usage line promise a command that does not exist until M38.2; delete the comment clause when it lands.
- Low — a badly wrapped line in the module's HOW paragraph ("could\n not update"). Cosmetic.
- Note — `ruff format --check` flags a pre-existing line in `onboarding.py` (~L217); the gate runs `ruff check` only. Not this milestone's.
