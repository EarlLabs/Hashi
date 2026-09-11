# M9 — what landed

**Closed 2026-09-11.** Six steps, **18 review rounds**, two post-acceptance fix
loops, and **two acceptance rounds** — round 1 blocked, round 2 good.

| step | rounds | what it was |
|---|---|---|
| M9.1 | 3 (+2 fix-loop) | Nodes, add-node dialog, and the owner's carried refusal-colour finding |
| M9.2 | 3 | Hops, and the establish-hop dialog's disclosure |
| M9.3 | 2 | Transports — the read-only capability table |
| M9.4 | 3 (+2 fix-loop) | Keys & configs, rotation and replace-params |
| M9.5 | 3 | enable / withdraw / set state — **a step the plan did not have** |
| M9.6 | 4 | the old pages retire |

**M9.5 was added on 2026-09-10.** M9's own "done when" required enable/withdraw a
transport and set node state to have a home, and no step named them — M9.1 is node
lifecycle, M9.3 is read-only, M9.4 is keys. Unallocated scope, not new scope.
Retirement moved to M9.6.

## The two things the milestone taught that were not in it

**The plan promised a default that could not exist.** The hop dialog was to show
*"its own transport's default as a placeholder"*. No shipped transport declares a
default for any hop parameter it **requires**, and none may be invented: the junk
counts and magic headers are the fleet-wide-fingerprint case, `port` and the
tunnel addresses are barred outright, and `mtu` — the one that looks mechanical —
is the one the transport most explicitly refuses. The plan's line was left in
place with a correction beside it, the acceptance line was corrected to match, and
the reasoning went in `docs/decisions.md`. What ships instead is a disclosure that
says, **before it is opened**, how many boxes this transport requires — derived
from the transport, never written down. Acceptance walked it twice and confirmed
the count honest.

**A milestone about deleting pages ended in a security fix and a data-loss fix.**
M9.4's third round found that the console could render a node's decrypted private
key — the allow-list closed the class of *locations* and not of *messages*, so a
validator reading `info.data` filed its complaint at a real box name and the
sentence printed verbatim. Closed by redacting in the service where the values are
still in scope. And M9's acceptance walk found a failed hop-end rotation saying
*"Nothing was changed"* when the key **had** changed, leaving the two ends
mismatched and the tunnel down. Closed by making a hop rotation one transaction
across both ends.

## The recurring defect, found six times

A check that cannot fail. The banner scan blind to the syntax this codebase
writes; a `loc` guard closing two instances and not the class; an assertion
printing the secret it was proving absent; a sweep passing against a leaking route
because SQLAlchemy's identity map returned the same rows twice; a test proven only
against a fake of its own producer; a phrase list standing in for a pairing. Each
was found by review rather than by the suite, and each is written up where the next
implementer will meet it rather than in a commit message.

Two root causes were worth the hunt: **`app.js` cleared the banner slot on
`htmx:afterRequest`, which fires *after* the swap**, so every banner the panel ever
sent on a 2xx was written and wiped in the same exchange; and **`[hidden]` is a
user-agent rule**, beaten by any author `display` rule, which is why one dialog's
transport groups all showed at once while the other's did not.

## Gate

`make verify` green at close. Acceptance round 2: **good, nothing blocks**, all six
"done when" passed with evidence, all five of round 1's findings verified fixed,
seven **clumsy** findings recorded for the owner.

**Carry-over:** see `carry-over.md`, `fix-notes.md` and `gate-hazard.md`. The one
worth reading first is `gate-hazard.md` — the gate is not safe to run concurrently
and nothing in the project says so, which manufactured a "flake" that cost real
time before it was understood.
