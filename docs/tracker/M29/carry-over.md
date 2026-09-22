# M29 — carry-over
Non-blocking findings left open, with the reason each was left. Read them as
BACKGROUND: they tell you what is known-wrong so you do not mistake it for the
intended design. Do not fix them as part of another step.

## From M29.1, review round 1 — Medium

**`docs/product/backlog.md` is classified monolithically as living, and it is
half a record.** `docs/records-and-living-documents.md:59` and
`docs/tracker/M29/step-notes.md:80` both say `living | reword` for the whole
file. But the file carries its own `## Журнал решений` section (from line 533),
a dated decision journal in the same `| Date | Decision | Reason |` shape as
`docs/decisions.md` — which that very document treats as append-only. The row
`2026-08-01 (ohno-6)` records a transport decision whose text contains
"friend-facing вариант".

The same "half record, half living" lens was applied correctly to
`docs/PLAN.md` (its dated sections carved out) and even to migration comments,
but not to this file — which M29.1 added to scope on its own initiative rather
than from the owner's enumerated list, and that is exactly where the miss is
costliest.

**Left open because** M29.1 renamed nothing, so nothing is wrong in the tree
today. **It must be closed before M29.7 executes**, which is the step that
rewords the living documents and would otherwise follow the table literally and
falsify a record. M29.7's brief carries this finding as a required input.

**Shape of the fix:** a carve-out row saying `## Журнал решений` is a record and
stays untouched, while the mutable backlog above it (roadmap items, statuses,
IDs, the "Как читать этот файл" prose) is living; then extend the record check
to cover that slice before M29.7 runs.

## From M29.1, accepted residuals (not defects)

- **`docs/tracker/field-checklist.md`** holds 56 occurrences in a file that is a
  live instrument rather than a record, but it sits inside the owner's
  path-drawn never-touched set. Path wins. The residual — a checklist saying
  *friend* in front of a panel saying *user* — is accepted. Closing it means
  promoting the file out of `docs/tracker/`, which is the owner's call, not a
  step's.
- **No pointer in `CLAUDE.md`** to `docs/records-and-living-documents.md`, which
  is where an agent would actually look. M29.7 owns that file with the owner's
  sanction and should add the one line. Until then discoverability rests on the
  `docs/decisions.md` row and the step notes.
