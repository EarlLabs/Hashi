# M21 — what landed

**Closed 2026-09-10.** `acceptance: no` — the plan's own answer, and the right
one: this milestone has no interface to walk. Its honest proof is running the
gate repeatedly, under load, and getting the same answer every time, which is
what each step did.

**M21.1 — assert the property, not the sentence.** 1 review round, clean. The two
unreachable-node tests stopped pinning the sentence M4.4's timeout arm writes.
The fact and the wording are now asserted separately: the fact where it is
actually recorded (`HealthResponse.reachable is False`; `isinstance(cause,
NodeUnreachable)`), the wording through a shared `assert_plain_reason` helper that
tests a property — one line, no traceback, real prose, no node address. Two tests
got stronger as a by-product. Tests only; no production code.

**M21.2 — stop depending on what an address happens to do.** 2 review rounds. The
fixtures no longer dial a reserved documentation address whose behaviour belongs
to the network; they dial a loopback socket the suite opens and holds. Round 1
returned clean with a Medium — the no-leak check had narrowed to the dialled
endpoint and no longer guarded the node's advertised address — and the fixes were
asked for anyway rather than banked, because a milestone about a trustworthy gate
is the wrong place to accept a coverage reduction. Round 2 verified both by
mutation. The timing assertion gained a floor to go with its ceiling, so it fails
if the blackhole target is ever repointed at a refusing one.

**M21.3 — the gate must be runnable on the owner's own machine.** 1 review round,
clean, no findings at any severity. Scope extended by the owner on 2026-09-10 and
recorded in the plan before any work started. Chosen answer: a portable idle in
production **plus** a POSIX-strict `sleep` shim in the test. The pair is the
point — the shim makes a non-portable idle red on Linux CI where it was
previously invisible, and the portable idle is what makes it green on a BSD host.
The production change was measured no worse inside the container rather than
argued to be, which was the owner's stated condition. One edit reached outside the
obvious file and had to: an e2e test poisoned the literal string `"sleep
infinity"` by `.replace`, so rewording the idle would have made its red half
vacuously green.

**Gate:** `make verify` green at close — 296 control, 230 edge (+3 skipped), 162
infra, 146 e2e, exit 0. This is the baseline every later milestone in this run is
measured against.

**Carry-over:** one Low, in `carry-over.md`. Nothing blocking.
