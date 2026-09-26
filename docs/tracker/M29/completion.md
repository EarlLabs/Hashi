# M29 — what landed

**Done 2026-09-23.** Thirteen steps, 37 commits on `task/M29`, `make verify` green on
the closing tree (control 219 passed / 697 skipped — the no-Postgres baseline; edge 911
/ 3; infra 241; e2e 192).

Six steps were added mid-run — M29.2b, M29.3b, M29.4a, M29.4b, M29.4c, M29.8 — plus
M29.9 from the real-host walk. Every one of them existed to satisfy a "Done when" the
owner had already approved rather than to widen it, and each was committed with its
reasoning so it could be reversed on its own.

## Review rounds

One round each for M29.1, M29.2b, M29.3, M29.3b, M29.4a, M29.4b, M29.4c, M29.5, M29.6
and M29.9. Two each for M29.2, M29.4, M29.7 and M29.8. Nothing hit the cap and no
reviewer reversed itself.

Four rounds found something that mattered:
- **M29.2 r1** — the hand-off understated the blast radius: 28 e2e failures, not two.
- **M29.4 r1** — `make test-control` was red and the builder called it pre-existing; the
  reviewer showed baseline clean. The fix, one `session.expire_all()`, was then proven
  non-vacuous by patching the service to write the wrong state.
- **M29.7 r1** — tightening a regex to drop the retired word opened a silent skip. This
  repository's own decisions log names "a verification that cannot fail" as its
  signature defect, ~17 instances.
- **M29.8 r1** — two justifications written into the governance document were false.
  One id was not a key into the frozen research document at all.

## Acceptance — two verdicts, and they say different things

**Stand:** BLOCKED by the mechanical gate, on two checklist lines a disposable stand
cannot observe. No `broken`, no `lies`, tree unmodified, four of six lines passed on the
agent's own evidence. Lifted by the owner on 2026-09-23 —
`docs/tracker/M29/acceptance-override.md` carries the reasoning and the limits the
override does **not** raise.

**Real hosts:** PASSED on the central claim. A subscription issued by the pre-M29 code
into the pre-M29 schema, fetched from a second machine before and after both
migrations: same URL, same token, same status and headers, byte-identical VLESS body,
every functional line of the AmneziaWG config identical. `0008` and `0009` reversed
exactly; the panel worked in all three states; a revoked token and a never-issued one
were indistinguishable on status, body, headers and timing.

It found two defects in M29's own runbook text, both fixed and reviewed in M29.9: a
rollback procedure that **could not be executed as written and took the delivery
endpoint down when attempted**, and a "nothing on anybody's device changes" claim that
was true of the URL and false of the file it hands over.

## Not covered, and not claimed

Whether a tunnel survives a Russian mobile whitelist shutdown. That is a field
observation on a real mobile network; nothing in this milestone is evidence for it.
