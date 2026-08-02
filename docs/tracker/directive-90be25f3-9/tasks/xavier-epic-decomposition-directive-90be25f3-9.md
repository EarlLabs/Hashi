# Epic decomposition — a working VPN service

**From:** Charles Xavier (architect) · **Task:** `directive-90be25f3-9` · **Date:** 2026-08-02
**Mode:** EPIC DECOMPOSER, phase 2 — the ordered list the fleet is dispatched from.
**Inputs:** the owner directive; `docs/product/charter.md`; `docs/product/backlog.md`
(Ohno's items, reused as-is and unrenumbered); the frozen acceptance text in
`docs/research/product-owner-ohno-4/research.md` §3.
**Answers in force:** the six defaults in
`xavier-epic-questions-directive-90be25f3-9.md` were accepted verbatim as the
owner's answers for this unattended run. They are not reopened here.

## How to read this file

Eighteen tasks in four stages. Each is **one `/develop`-shaped run and one PR**.
None of Ohno's items was merged with another or split in two — his slicing
survived my own review (`approved-with-changes`, four blockers, applied in
revision 3) and re-cutting it would be me taking `what` decisions.

**The agent that runs a task sees only that task's *Intent*.** Each Intent is
therefore self-contained: it names the zone, the backlog item id, the files, and
it carries verbatim any decided text the write-protected rulebooks contradict.

Two standing rules for every task below:

- **Merge model (X1):** the fleet opens one PR per task into `develop` and merges
  it itself once the review verdict is `CLEAN`, security is clean and the zone's
  verify command passed **when run by the reviewer**. **`main` is never
  agent-merged.** Blockers, red gates and questions escalate immediately through
  `scripts/notify.sh` and stop the queue — batching lowers noise, never escalation.
- **Honesty rule (X3):** this environment has **no container runtime** (no
  `docker`, no `/var/run/docker.sock`, no `podman`) and no system Postgres.
  **Never weaken a scenario to make it runnable.** A scenario that cannot run
  skips loudly, and the acceptance report uses the words given in that task's
  *Skip-loudly note* — never the word "green".

---

# Stage 0 — preparation (architect and owner territory, no zone)

## 1. Prepare the tree: sync `develop`, land the architect-owned edits, publish the decisions the rulebooks cannot carry

**Kind:** `refactor`
**Depends on:** none
**Backlog item:** none — this is not a backlog item and **must not be added to
`docs/product/backlog.md`**, which is the Product Owner's file.

**Intent.**
This is architect and owner territory: `docs/**`, `pyproject.toml`, `.gitignore`
and git branch state. Do five things and nothing else. **(a)** Sync the
integration branch — `git checkout develop && git merge main --no-edit`; today
`origin/develop` exists but is **6 commits behind `main`**, so any task branched
before this sync starts from a tree missing six commits; do not delete or touch
the stale `origin/task/2-control-plane-…` branch. **(b)** Fix the packaging defect
in `pyproject.toml`: replace the explicit `[tool.setuptools] packages = [...]`
list with pattern-based discovery limited to `control*` and `edge*`, because the
current explicit list does not include `edge.transports.*` and every transport
therefore silently fails to reach the built image — this is charter criterion 4
broken in the build system, reproduced empirically. **(c)** Add, with **exact
`==` pins**, the dependencies this epic has already been designed around, and
replace the "deliberately absent" comment at `pyproject.toml:17-19` with a
pointer to this file: `sqlalchemy` (asyncio extra), `asyncpg`, `alembic` (task
9); `itsdangerous` and `argon2-cffi` (task 10); `cryptography` (task 11). No
other dependency is authorised anywhere in this epic; a task that needs one stops
and escalates. **(d)** Add a `.gitignore` entry for the local upstream-checker
binary directory that task 4 will populate (`.tools/`), since `.gitignore`
belongs to no zone and the infra developer may not edit it. **(e)** Write
`docs/tracker/directive-90be25f3-9/tasks/xavier-decisions-directive-90be25f3-9.md`
carrying, verbatim and in one place: the re-issued rulebook corrections A and B
from `docs/tracker/ohno-5/tasks/xavier-blocked-edits-ohno-5.md`; a **re-issued
correction C** rewritten against today's facts (`origin/develop` now exists, so
`gh pr create --base develop` works and `git pull origin develop` is executable —
the original C was written when `origin` carried only `main` and is now factually
stale); and the recorded autonomy raise from X1.
**Do not** edit anything under `.claude/**` — it is write-protected, verified by
probe in this session; that is exactly why (e) exists. **Do not** edit
`docs/product/backlog.md` or `docs/product/charter.md`. **Do not** touch
`control/**`, `edge/**` or `deploy/**`. **Do not** push to `main`.
**Acceptance bar:** `make test` passes; `pip install .` into a scratch target
produces a tree containing `edge/transports/`; `git log --oneline develop -1`
shows the merge; the decisions file exists and is cited by every later task.

**Skip-loudly note.** No acceptance scenarios; nothing to skip. The one check that
could be blocked is the `pip install --target` verification of (b) — it needs
network egress only, which this environment has. If it is blocked, report
"packaging fix landed but **not verified by installation**" and stop, because
tasks 3 and 5 both stand on it.

---

# Stage 1 — M1: "a config Xray itself accepts, and a second protocol is one directory"

Charter criterion **4** closes here. Zero money, zero live hosts.

## 2. Move the owner's real secrets out of the fleet's read-write mount

**Kind:** `develop` · **Zone:** `infra`
**Depends on:** task 1
**Backlog item:** `0` — `infra-env-out-of-warden-mount`

**Intent.**
`deploy/warden/docker-compose.yml:49` mounts this repository **read-write** into
the container where an unattended agent has `Bash`, `Write`, `Edit` and network
egress, and the owner's real `.env` sits inside that mount. The only thing
protecting it today is prompt text ("NEVER read or print `.env`") with no deny
rule and no filesystem separation behind it. Change the **configuration** so the
warden stack reads its environment file from a path **outside** every mounted
path, and so that starting it without that file fails loudly and names the
required action instead of substituting empty strings; fold in the related defect
at `Makefile:98`, which runs the warden compose **without** `--env-file` — safe
today only because that file contains no `${VAR}`, and silently broken the moment
one appears. **You must not read, print, `cat`, copy, move, delete or otherwise
open the real `.env` file** — your scenarios assert on the **compose files and
the mount configuration**, never on any file's contents; `.env.example` is the
only env file you may read. **Do not** change anything else under
`deploy/warden/`, **do not** add tests for warden, and **do not** touch privilege
separation inside the container — the fleet-tooling freeze holds and this item is
one of its only two exceptions, because it protects secrets rather than improving
tooling. **Acceptance bar:** the two frozen scenarios — **S1** no file carrying
real secrets is under any path mounted into the agent container, and **S2** the
warden stack starts from the new location while a start without the env file
fails with a clear error. The remaining risk is not removed by this task: the
owner must still perform one action, moving the file. **Notify the owner through
`scripts/notify.sh` the moment this lands** — do not wait for the stage report.

**Skip-loudly note.** **S2 cannot execute here** — it starts a compose stack and
there is no container runtime. The command that would prove it is `make
warden-up` on a machine with Docker. The report must say: *"S2 not executed — no
container runtime in this environment; the warden stack was not started. S1
executed statically against the compose files."* Not "green".

## 3. Express the transport contract in code and ship the first transport: VLESS + Reality + XTLS-Vision

**Kind:** `develop` · **Zone:** `edge`
**Depends on:** task 1
**Backlog item:** `1` — `edge-transport-contract-vless-reality`

**Intent.**
Make hashi able to render, for a described node, a VLESS + Reality +
XTLS-Vision **server config** and a **client entry**, with the contract that every
future transport will implement. The transport lives entirely in
`edge/transports/<name>/`; the contract types live in `edge/registry.py`.
Rendering is **pure**: no database, no network, no clock, no randomness, no key
generation — keys and credentials are passed in, and templates are loaded at
import time rather than during a render call. **Carry these architect decisions;
the rulebook in the tree contradicts two of them and is stale in exactly these
places.** (i) `.claude/projects/02-edge-rulebook.md:66` says `render_client(node,
credential) -> dict`. **That is wrong.** `render_client` returns a `ClientEntry`
carrying four fields: `entry` — the transport's own complete serialisation of one
client entry, one line, ready to place in a subscription and **without** a display
label; `display_label` — the human-readable name a client should show;
`country_label` — the exit country, taken from the node record's location label
and **never** from a geo lookup on an address; `node_id` — which node the entry
points at, so the control plane can order, filter and revoke without ever parsing
`entry`. The transport owns URI serialisation end to end, because every part of a
`vless://` URI is protocol-specific (the scheme *is* the protocol name; the query
carries `security`, `pbk`, `sid`, `fp`, `sni`, `flow`) and a control plane that
assembled it from parts would have to branch on the protocol. (ii) The same
rulebook's *Where a new file goes* forbids editing `edge/registry.py`
unconditionally. **One exception is authorised, inside this task and only this
task**: add the default **port range** to `TransportMeta`, add the `ClientEntry`
type, and add the declaration described next. This is the contract being
completed for the first time, not widened for a special case; from the second
transport onward the ban applies without appeal. (iii) The **declaration** a
transport publishes must let the control plane act without ever learning a
protocol name: name, family, TLS need, default port range, a flag saying whether
the transport **is expressible in the v1 subscription format** (a base64 list of
URIs), and the **key material it requires**, expressed as named slots whose kinds
come from a small closed vocabulary owned by `edge` — for M1 that vocabulary is
`x25519_keypair`, `random_hex(n)` and `uuid4`. A control plane generates by
**kind**, never by transport name; a transport needing a kind that does not exist
is a contract change and comes back to the architect. (iv) The **node record** —
the `node` argument to both renderers — is defined here, in `edge`, imports
nothing from `control`, and is the input to both renderers; the control plane's
SQLAlchemy models will later **map onto** it rather than being it. (v) In the same
run, bring `edge/AGENTS.md` into line: lines 20-32 still say the next transport is
AmneziaWG (it is now VLESS + WS + TLS) and state the registry ban without the
one-time exception above — that file is in your zone, so it is yours to fix.
**Out of scope:** any database work, any SSH, any real host, the second transport,
the subscription as a whole, and **key-material generation** — keys arrive as
input. **Do not edit `pyproject.toml`** (task 1 already fixed the packaging) and
**do not touch `control/**`**.
**Acceptance bar:** the six frozen scenarios — **S1** a render matching a
checked-in golden file byte for byte, with fixed fake keys and decoy
`example.com`; **S2** the rendered server config accepted by the stock checker
`xray run -test -config`; **S3** two identical calls producing identical bytes and
the call itself touching neither network, filesystem, clock nor randomness; **S4**
params with **no** decoy destination rejected with a validation error, so that no
project-wide default decoy can exist to be borrowed — a shared decoy is what makes
the whole fleet enumerable; **S5** `render_client` returning a ready entry plus
protocol-neutral metadata carrying this node's own host, port and decoy; **S6** the
declaration in (iii) readable without comparing against a protocol name. Red-first
proof is required for each: break it, watch the right assertion fail, restore it.

**Skip-loudly note.** **S2 cannot execute yet** — the Xray binary arrives in task
4. It must **skip loudly** with an explicit message and must never be counted
green. The report must say, verbatim: *"S2 skipped, the validation half of
criterion 4 is not proven."* **M1 is not closed until at least one scenario with
the upstream checker has actually run for real** (task 4 makes that possible and
task 6 re-runs it). Everything else in S1, S3-S6 executes natively here.

## 4. Make the upstream Xray checker reproducibly available, without Docker

**Kind:** `develop` · **Zone:** `infra`
**Depends on:** task 3
**Backlog item:** `1a` — `infra-upstream-checkers`

**Intent.**
Task 3's central scenario is validated by **Xray's own** checker, not by our
opinion of a correct config, and right now that only works "for whoever installed
the binary by hand". Add a Make verb that fetches a specific upstream Xray release
into the repository-local `.tools/` directory (already gitignored by task 1),
verifies it against a recorded checksum, and is idempotent — running it twice does
nothing the second time. **It must not require Docker**: this environment has no
container runtime, and a Docker-based delivery would make M1 unprovable, which is
precisely the failure this task exists to prevent. Document the verb in
`README.md`'s verification table and make the `edge` scenarios locate the binary
by a documented path or environment variable rather than by `PATH` alone. **Out of
scope:** an e2e job in CI — deliberately, the tooling freeze holds and there is no
stack worth raising until M3; a checker for the WireGuard family — unnecessary,
because both M1 transports are validated by the same `xray run -test -config`.
**Acceptance bar:** the two frozen scenarios — **S1** on a clean machine with this
repository, running the documented preparation command makes the checker-using
scenarios **execute rather than skip**; **S2** the version is pinned **exactly**,
never `latest` and never a bare major, because an upstream that changes its
validation rules between two runs looks exactly like our regression. After this
lands, re-run task 3's S2 for real and record the result — that is what closes
M1's validation half.

**Skip-loudly note.** This task is the one that **removes** a skip, so it must not
introduce one. Its own scenarios run natively; the fetch needs network egress,
which this environment has. If egress is blocked at run time, that is a
**blocker, not a skip**: stop, escalate through `scripts/notify.sh`, and record
that M1 cannot be closed in this environment. Do not substitute a hand-installed
binary and call it done.

## 5. Make the built image actually ship every transport, and keep it that way

**Kind:** `develop` · **Zone:** `infra`
**Depends on:** task 3
**Backlog item:** `2` — `infra-image-ships-transports`

**Intent.**
`deploy/docker/control.Dockerfile:15` runs `pip install .`, so whatever the
packaging configuration omits simply is not in the container — and until task 1
the configuration omitted every transport, which meant `discover()` returned `{}`
inside the image while finding transports fine on a laptop's editable install.
That is charter criterion 4 broken invisibly, in the build system. Prove it is
fixed and make it impossible to break silently again. **Out of scope:** the
contents of any transport; base-image pinning (that is task 16); and the assertion
"this task's diff contains nothing extraneous" — a test in `tests/e2e/infra/`
knows neither the base commit nor the task boundary, so that one is a **review
gate** for Granger and my phase-7 check, not a scenario. **You may not edit
`pyproject.toml`** — it belongs to no zone and task 1 already changed it; if you
believe it needs another change, stop and escalate.
**Acceptance bar:** the three frozen scenarios — **S1** an image built from
`deploy/docker/control.Dockerfile` contains the task-3 transport, i.e.
`edge.registry.discover()` run **inside the container** returns it and not an
empty mapping; **S2** the packaging configuration admits transport packages **by
pattern**, and no file outside a transport directory lists transports by name, so
that adding a directory requires an edit nowhere else; **S3** a freshly added
transport package reaches the container after a rebuild. Red-first here is a
**demonstration, not a work order**: the packaging fix is already in the tree, so
show that S1 **is able to fail** — temporarily revert it, watch the right
assertion go red, restore it, and say so in the report.

**Skip-loudly note.** **S1 and S3 cannot execute here** — both build and run a
container image. The commands that would prove them are `docker build -f
deploy/docker/control.Dockerfile .` followed by running `edge.registry.discover()`
inside the resulting image. The report must say: *"S1 and S3 not executed — no
container runtime in this environment; the image was not built, and criterion 4's
packaging half is unproven here."* **S2 executes** statically and must be run.
The red-first demonstration applies to S2 in this environment; note explicitly
that S1's red-first was **not** demonstrated.

## 6. Add the second transport as one directory: VLESS + WS + TLS

**Kind:** `develop` · **Zone:** `edge`
**Depends on:** task 4, task 5
**Backlog item:** `3` — `edge-transport-vless-ws-tls`

**Intent.**
This is the e2e proof of charter criterion 4: a protocol hashi never supported
becomes **one new package** and nothing else. Add VLESS + WS + TLS behind a
camouflage front as a second transport directory under `edge/transports/`. It was
originally going to be AmneziaWG; it is not, and that is a settled product
decision, not an oversight — AmneziaWG is **inexpressible** in the v1 subscription
format (a base64 list of URIs): no v2ray subscription scheme expresses it, its
obfuscation parameters have no URI representation, and the client that justified
the format does not read WireGuard-family entries at all. It returns in M4 on the
cross-border entry↔leaf hop, where node configuration consumes it rather than a
friend's device. **The point of this task is not the protocol; it is the
hypothesis that the contract is not narrow.** Therefore: **do not edit
`edge/registry.py`** — the contract was frozen at task 3's acceptance and a
transport that needs a registry edit is a contract failure, so stop and escalate
to the architect instead of special-casing; **do not touch the other transport,
`control/**`, or `pyproject.toml`**. **Out of scope:** the cross-border hop and
MTU handling (both M4), any real node, and AmneziaWG.
**Acceptance bar:** the five frozen scenarios — **S1** a render matching a golden
file with fake keys and camouflage host `example.com`, **accepted by `xray run
-test -config`** (after task 4 a skip here is **not permitted**); **S2** the static
proof that the addition required no surgery — (a) no identifier in `control/**`
equals any name `discover()` returns, (b) the package imports nothing from `edge/`
beyond the public registry types and nothing at all from `control/`, (c) the
second transport appears in `discover()` with no by-name exception written
anywhere; **S3** both transports visible at once with the package traversal order
permuted, the two mappings equal; **S4** two packages declaring the same name
producing a noisy error rather than a silent loss (a regression sentinel — this
behaviour already exists at `edge/registry.py:36-37`, so do not count it as new
proof); **S5** the transport declaring itself expressible in the v1 subscription
format, with no code in `control/**` establishing that by name comparison. If S2
fails, the fault is in the **contract**, so the work goes back to task 3 — it does
not become a widened exception here.

**Skip-loudly note.** All five scenarios execute natively **provided task 4
delivered the checker**. S1's checker half must not skip: after task 4, a skip
here is a **blocker**, not an accepted gap — stop and escalate. There is one
review gate that is deliberately not a scenario: "this task's diff contains no
change to `edge/registry.py`, to the other transport, to `control/**` or to
`pyproject.toml`" — Granger and I check that against the diff, and the report must
name it as a review gate rather than as acceptance.

## 7. Integrate M1, prove criterion 4, and produce the owner's first PR

**Kind:** `review`
**Depends on:** task 2, task 3, task 4, task 5, task 6
**Backlog item:** none — this is the milestone gate that honours the owner's
"report after each big stage, only finished features".

**Intent.**
Assemble Stage 1 into the **one** deliverable the owner sees. Verify against the
tree, not against status files: every acceptance criterion of items 0, 1, 1a, 2
and 3 traces to a scenario and a run result, including the **red-first** proof
(break it, watch the right assertion fail, restore it); the contracts between
`edge` and `infra` are consistent; **no zone was edited by two owners**; and each
zone's own verify command (`make test-edge`, `make test-infra`) passes when **you**
run it. Then open the owner-facing PR from `develop` to `main` — **open it, never
merge it**; releasing into `main` is a human action, always. The PR body states,
in this order: what the owner can now do; charter criterion **4** and whether its
two halves (packaging and validation) are both proven; the **complete list of
scenarios that were not executed**, each with the reason and the exact command
that would execute it; and the one action still owed by the owner from task 2
(moving the real `.env` out of the mount). Then send the stage report through
`scripts/notify.sh`. **Do not** fix code yourself — findings go to the zone's
developer. **Do not** claim anything about surviving DPI, about traffic reaching a
site, or about charter criterion 1: no test in this repository closes it, now or
ever.
**Acceptance bar:** the PR exists on `develop`; criterion 4 is reported as closed
**only if** an Xray-checker scenario actually ran for real at least once —
otherwise the report says M1 is incomplete and names which half is missing.

**Skip-loudly note.** State per zone the number of scenarios **collected** and
**executed** — not just pass/fail. `make test-e2e` **exits 0 when zero tests are
collected**, so a milestone whose scenarios were never written or never ran
otherwise reports green; that hole is known and stays under the tooling freeze,
which makes this count the only thing standing between the owner and a false
report.

---

# Stage 2 — M2: "one link to a friend, and taking it back"

Charter criterion **6** half-closes (database and render; delivery to a live node
is M3). Criterion **5** advances to "a stock client parses the link". Still zero
money, zero live hosts.

## 8. Wire the control plane's runtime: database URL, migrations on bring-up, mandatory settings

**Kind:** `develop` · **Zone:** `infra`
**Depends on:** task 7
**Backlog item:** `3a` — `infra-control-runtime-wiring`

**Intent.**
Without this, the next task would be judged on something its developer is not
allowed to fix: `deploy/docker-compose.yml:39-41` passes the control service
exactly `HASHI_SECRET_KEY` and `HASHI_PUBLIC_HOST` and **no database connection
variable at all**; `.env.example` declares `POSTGRES_*` for the `db` service only
and no client URL; and `alembic upgrade head` is invoked nowhere. All three live in
`deploy/**` and `.env.example`, which is your zone and not the control
developer's. Give the control service its connection setting, declare it in
`.env.example` alongside the rest, and apply migrations **before the application
starts serving** and exactly once per bring-up. In the same pass declare two more
mandatory variables that later tasks depend on — the operator username and an
operator **password hash** (never a plaintext password), and a **session signing
secret that is separate from `HASHI_SECRET_KEY`**: key separation is deliberate,
because `HASHI_SECRET_KEY` encrypts node credentials at rest and must not double as
a cookie key. Every required variable uses the `${VAR:?message}` form, and every
compose invocation passes `--env-file`; without it `${VAR}` silently becomes an
empty string, the database starts with an empty password and nothing errors.
**Out of scope:** the ORM, the models and the migrations themselves (task 9);
encryption (task 11); image pinning and log guards (task 16).
**Acceptance bar:** the three frozen scenarios — **S1** a stack raised by the
standard command shows the connection setting in the control service's
environment, and `.env.example` declares it alongside the rest; **S2** on a clean
database volume, migrations are applied before the app serves requests and a
repeat bring-up does not reapply them; **S3** with a mandatory variable unset, the
bring-up fails naming the variable and the container is never created at all —
which is why "the container does not become healthy" is meaningless to check here
and belongs to no scenario.

**Skip-loudly note.** **None of S1, S2 or S3 can execute here** — all three raise a
compose stack. The commands that would prove them are `make up` (or `make e2e-up`)
on a machine with Docker. The report must say: *"S1-S3 not executed — no container
runtime in this environment; only the static half was verified (the compose files
and `.env.example` were asserted directly)."* Assert that static half; do not
rewrite the scenarios to fit what runs.

## 9. Give the control plane a real persistence spine

**Kind:** `develop` · **Zone:** `control`
**Depends on:** task 8
**Backlog item:** `4` — `control-persistence-spine`

**Intent.**
Postgres is raised in the stack today and nobody connects to it. Give the control
plane an async engine, one `AsyncSession` per request injected with `Depends`, and
Alembic for every schema change — `create_all` is forbidden, because this database
holds node credentials and friend identities that exist nowhere else and a silent
divergence from a live schema means every friend is locked out. Configuration is
read **only** in `control/app/settings.py`; `os.environ` appears nowhere else, and
a missing required setting raises at boot rather than on the first request that
needs it. Use `expire_on_commit=False` on the async session, or attribute access
after commit triggers lazy I/O outside the session and raises at runtime rather
than in tests. The dependencies (`sqlalchemy` with the asyncio extra, `asyncpg`,
`alembic`) were added at exact pins in Stage 0 — **you may use them and you may
not add any other**; `pyproject.toml` belongs to no zone, so if you need something
else, stop and escalate. **Out of scope:** domain models, encryption, the panel,
authentication, and **everything under `deploy/**` and `.env.example`** — that was
task 8.
**Acceptance bar:** the three frozen scenarios — **S1** a clean database volume
comes up to a working state, `alembic current` shows head and `/healthz` answers
200; **S2** starting without a database connection setting fails **at startup**
with a clear error, not on the first request; **S3** applying migrations twice
changes no schema and succeeds. Tests run against a **real Postgres**, never
SQLite: async drivers, JSONB and constraints all behave differently, and a suite
that passes on SQLite proves nothing.

**Skip-loudly note.** No system Postgres and no container runtime exist here. You
**may install a local Postgres 16 natively** so that the control-zone scenarios
genuinely execute — that is the sanctioned fallback and it must be recorded. S2
and S3 then execute fully. **S1 executes only in part**: the migration and
`/healthz` half runs, the "clean e2e stack volume" half does not. The report must
say: *"S2 and S3 executed against a locally installed Postgres 16. S1 executed in
part — migrations and `/healthz` proven, the e2e-stack-with-clean-volume half not
executed, no container runtime; `make e2e-up && make test-e2e` would prove it."*

## 10. Close `/api/**` and `/panel/**` to everyone but the operator

**Kind:** `develop` · **Zone:** `control`
**Depends on:** task 9
**Backlog item:** `5` — `control-operator-auth`

**Intent.**
The admin panel is the highest-value target in this system — it can add a node and
read every credential — so it is closed by construction rather than by a check
someone remembers to write. Enforce operator authentication as a **router-level
dependency**, never as an `if` inside each handler: a route added to the
authenticated router inherits the rule, and a route needing a different rule says
so explicitly. **Architect decisions you are to implement, not re-litigate:**
operator credentials come from the **environment** — a username and an
**argon2 password hash**, declared and delivered by task 8, read only through
`control/app/settings.py`; the session is a signed cookie session using Starlette's
session middleware, signed with the **separate** session secret from task 8 and
**never** with `HASHI_SECRET_KEY`. The dependencies (`itsdangerous`,
`argon2-cffi`) were pinned in Stage 0; add nothing else. **Out of scope:**
`/sub/{token}`, which is unauthenticated **by construction** because the token *is*
the credential (task 14); multiple operators; password reset; and **lockout after
repeated failed logins, which is deliberately absent in v1** — one operator behind
a panel that is not publicly advertised, recorded as a decision so it is not
re-argued at security review.
**Acceptance bar:** the four frozen scenarios — **S1** an unauthenticated client is
refused on **any** path under `/api/**` or `/panel/**`, and the response contains
no hostname, no SQL and no traceback; **S2** an operator with correct credentials
authenticates and subsequent `/api/**` requests are served; **S3** an error raised
**inside** the authentication path denies access and never falls through to the
resource — authorization fails closed; **S4** a route added to the authenticated
router with no check of its own is still refused. Errors leave through the typed
envelope `{"error": {"code", "message"}}`; no handler returns a raw exception
string.

**Skip-loudly note.** All four execute natively — they are in-process HTTP calls
against the ASGI app and need no stack. If any of them needs a database, use the
locally installed Postgres from task 9 and say so. Nothing here may be reported as
covered by `make test-control` alone: state which command you ran.

## 11. Encrypt node secrets at rest, and make `HASHI_SECRET_KEY` finally do something

**Kind:** `develop` · **Zone:** `control`
**Depends on:** task 9
**Backlog item:** `6` — `control-encrypted-secrets`

**Intent.**
`HASHI_SECRET_KEY` is mandatory at startup today and used by nothing — at-rest
encryption exists as doctrine without implementation. Make it load-bearing: node
and transport secrets are stored encrypted, with the key supplied by the
environment, and the application **fails loudly at boot** when the key is missing.
It never starts in a degraded mode that writes plaintext. **Architect decision:**
use the `cryptography` library's authenticated symmetric encryption (Fernet), with
`HASHI_SECRET_KEY` as the key, applied at the persistence layer as a column type so
that encryption is not sprinkled through call sites; the dependency was pinned in
Stage 0 and no other crypto library is authorised. Decrypt at the point of use, and
never let a decrypted secret land in a variable that reaches a log record, a
template context or an exception message. **Out of scope:** key rotation and
backups (both M5), and **secret generation** — this task stores an already existing
value; generation is the next task.
**Acceptance bar:** the four frozen scenarios — **S1** with the key set, a stored
secret reads back equal while a direct SQL query against the column shows no
plaintext; **S2** a secret stored under one key and read under a different one
fails **loudly**, never returning garbage; **S3** with the key absent, the
application **process** exits non-zero naming the variable, rather than failing on
the first request; **S4** a stored secret is absent from any `/api/**` response,
from any template context, and from the text of any error. Note for S3: the
stack-level version of that check ("compose does not even create the container",
because `${HASHI_SECRET_KEY:?}` at `deploy/docker-compose.yml:40` aborts before
creation) is task 8's S3 and belongs to `infra` — do not duplicate it here.

**Skip-loudly note.** All four execute natively against the locally installed
Postgres from task 9; S3 is a process-level check and needs nothing. Say which
command you ran and against which database. If Postgres could not be installed,
S1 and S2 **skip loudly** and the report says *"S1 and S2 not executed — no
database available; `make e2e-up && make test-e2e` would prove them"* — it does
not say the encryption works.

## 12. Generate key material so the operator never types a key

**Kind:** `develop` · **Zone:** `control`
**Depends on:** task 11
**Backlog item:** `6a` — `control-key-material`

**Intent.**
Three later tasks silently assumed this existed and nothing produced it. Make
secrets be **born in one place**, land in storage already encrypted, and be passed
into the renderer from outside — so that enabling a transport on a node, or issuing
access to a friend, requires the operator to see and type nothing. **The control
plane must not learn what any protocol needs.** It reads the requirement
declaration the transport publishes (task 3, decision (iii)): named slots whose
kinds come from `edge`'s closed vocabulary — `x25519_keypair`, `random_hex(n)`,
`uuid4` — and it generates **by kind**. If you find yourself writing "Reality needs
an x25519 pair", stop: that is the control plane learning a protocol name, and it
breaks core invariants §1 and charter criterion 4 in one move. A transport
requiring a kind that does not exist is a **contract failure** in task 3, and the
work goes back there rather than adding a branch here. Use a cryptographic
randomness source; secrets are never derived from a nickname, a node name, a
timestamp or a counter. **Out of scope:** rotation (M5), delivery to a live node
(M3), and the subscription itself (task 14).
**Acceptance bar:** the four frozen scenarios — **S1** enabling a transport on a
node requires the operator to pass no secrets, the required material appears, the
node becomes renderable, and the operator has neither seen nor typed a key;
**S2** material generated for two enablements on different nodes differs — for
**every** secret, not merely the first; **S3** a render call creates no secret, all
key material arriving as input; **S4** two friends receive different credentials,
and re-issuing to the same friend creates a **new** credential rather than
returning the old one. No key material is ever shared between nodes: one seized
node must reveal nothing about any other.

**Skip-loudly note.** All four execute natively against the locally installed
Postgres from task 9. S3 needs nothing but the pure renderer. Record the command.

## 13. Let the operator create nodes and friends, and enable transports on a node

**Kind:** `develop` · **Zone:** `control`
**Depends on:** task 12, task 6
**Backlog item:** `7` — `control-node-and-friend-records`

**Intent.**
Give the operator the three records the product is made of: create a node, create
a friend, enable a transport on a node. A friend record holds **only** a nickname,
a credential and an expiry — no name, no email, no phone number, no payment data,
no IP address and no connection time. Node names and friend nicknames are
**untrusted input**: they end up in rendered configs and later in SSH command
lines, so validate them at the boundary and keep Jinja autoescape on — a `|safe` on
any of them is an injection. Transports are referred to **by the name
`discover()` returned**, never by a name written in `control/**`. **Out of scope:**
real node bootstrap (M3), the `degraded`/`active` state machine (M4), and the
panel. This task depends on task 6 as well as task 12, and the reason matters: an
**empty transport registry is a passing test today**
(`tests/edge/test_scaffold.py`), so a scenario that enables "a transport
`discover()` returned" would go green **vacuously** if the transports did not
exist yet.
**Acceptance bar:** the five frozen scenarios — **S1** an authenticated operator
creates a node with host, location label and role, the node appears in the list,
and its secrets are absent from the response; **S2** enabling a transport by a name
from the registry works, and an unknown name is rejected with an error in the
`{"error": {"code", "message"}}` envelope; **S2a** a transport that declared itself
**inexpressible** in the v1 subscription format is rejected out loud on enablement,
in the same envelope, naming the reason — a subscription is never silently
incomplete, because a friend who does not know he has no access is worse than an
error; **S3** the friend table schema holds only nickname, credential and expiry,
with no column for email, phone, IP or connection time; **S4** statically, no
identifier and no string constant anywhere in `control/**` equals any name
`discover()` returns, nor a provider name, nor a country name.

**Skip-loudly note.** All five execute natively against the locally installed
Postgres from task 9; S4 is a static tree check and needs nothing. Record the
command and the database. If the registry is empty when you run S2, that is a
**blocker**, not a pass — stop and escalate.

## 14. Deliver one subscription link per friend

**Kind:** `develop` · **Zone:** `control`
**Depends on:** task 13
**Backlog item:** `8` — `control-subscription-delivery`

**Intent.**
The subscription is the **only contract with a user**: any change to what a friend
connects to — new node, new protocol, rotated key, retired country — must be
expressible as a new render, with no action on their device. Serve `GET
/sub/{token}` as a base64-encoded list of client-entry URIs, one entry per "node ×
enabled transport" pair, each labelled with its exit country so the stock client's
own switcher lets a friend choose where to exit — **one link with several labelled
entries, never a separate link per country**. **Your half of the contract, and all
of it:** take each `ClientEntry` from `render_client`, order the entries, compose
the display text from `display_label` and `country_label`, append it as the URI
fragment, join, base64-encode. Treat every field as **opaque text** — never parse
`entry`, never branch on any value, never compare a label or a transport name
against a literal. The arithmetic test of this contract is that adding a transport
adds **zero** lines to the subscription renderer. `/sub/{token}` is
unauthenticated **by design**: the token *is* the credential, looked up in constant
time. **The token is a bearer credential sitting in a URL path**, so every place a
path can be recorded is a leak — the application access log, an exception handler
that echoes the path, a traceback. **Out of scope:** real traffic through nodes
(M3); Clash and sing-box, which are not in v1; and Caddy's output, which is task 16.
**Acceptance bar:** the five frozen scenarios — **S1** a friend with a token and
two nodes with enabled transports gets a base64 URI list with one entry per pair,
every entry labelled with its exit country; **S2** an unknown token returns
**404** — not 403 and not 401, because a 403 confirms a token once existed;
**S3** neither the path nor the token appears in the control plane's output or in a
response body, including after an error is deliberately triggered on that path;
**S4** the token comes from a cryptographic randomness source, carries at least 32
bytes of entropy, and N consecutively issued tokens are pairwise distinct; **S5**
the application **fails at startup** when its public host is not explicitly set —
`control/app/settings.py:27` currently defaults to `"localhost"`, which is exactly
the failure a friend discovers rather than a test.
Two things are deliberately **not** scenarios and must be reported as such:
constant-time token comparison, which is a review point for Granger and Holmes
because a timing test flaps and then gets disabled; and the manual owner check —
pasting the produced subscription into a real client — which is owner acceptance,
not pytest.

**Skip-loudly note.** All five execute natively against the locally installed
Postgres from task 9, **except S3 as written**: it asserts on the control
**container's** output and there is no container runtime. Run the in-process
equivalent as supporting evidence and report: *"S3 not executed as written (it
asserts on the control container's output); the in-process equivalent was run as
supporting evidence and is not counted as acceptance. The stack-wide half is task
16's S4."* Also carry forward, prominently: **the owner has not confirmed which
clients his friends actually use.** That is the only assumption in this plan whose
refutation is discovered by a friend rather than by a test, and it must lead the
Stage 2 PR.

## 15. Make revocation total

**Kind:** `develop` · **Zone:** `control`
**Depends on:** task 14
**Backlog item:** `9` — `control-revocation-fanout`

**Intent.**
Revoking a friend must remove them from **everything the control plane knows** —
not from the one node they were last seen on. Trace the fan-out in code; "the
record is marked revoked" is not revocation. Re-issuing access after a revocation
is a **separate, explicit operator action producing a new token**, never a side
effect of anything else. **Out of scope:** delivering the change to a live node,
which is M3 and is exactly why charter criterion 6 stays **half** closed after
this task — the database and the render are done, the push to a node exists only
in theory, and criterion 6 is **not** marked done until it does not.
**Acceptance bar:** the three frozen scenarios — **S1** a revoked friend's
`GET /sub/{token}` answers **404**, the same code an unknown token gets, so that a
stranger learns nothing from the difference; **S2** a friend enabled on three nodes
with two transports disappears from the server render of **all six** combinations,
not only the last; **S3** re-issuing access to a revoked friend is a separate
explicit action with a new token.

**Skip-loudly note.** All three execute natively against the locally installed
Postgres from task 9. Record the command. The report must state plainly that
criterion 6 is **half** closed and name what is missing: delivery to a live node,
M3, `control-apply-and-push`.

## 16. Pin the image and hold the log guards with tests instead of doctrine

**Kind:** `develop` · **Zone:** `infra`
**Depends on:** task 8
**Backlog item:** `10` — `infra-pin-images-and-log-guards`

**Intent.**
This protects the one thing in the system that can compromise a real person: the
bearer token in the URL path. Today **no test checks any of it**. Make three
things test-held. First, pin the base image in
`deploy/docker/control.Dockerfile` to an exact patch version — it currently floats
on `python:3.14-slim`, a direct violation of the pinning invariant, and the
existing `test_images_are_pinned` misses it because
`tests/infra/test_compose.py:49` exempts built services. Second, assert that
uvicorn runs with access logging off. Third, assert that **both** loggers in
`deploy/caddy/Caddyfile` discard their output. For the second and the third,
removing the guard must make the test fail — a test that cannot fail is worse than
no test. This task has no dependency on the other Stage 2 work and may be pulled
forward if the queue stalls. **Out of scope:** everything in `control/**`.
**Acceptance bar:** the four frozen scenarios — **S1** the base image pinned
exactly; **S2** `--no-access-log` present, and its removal turning the test red;
**S3** both Caddy loggers set to discard, and removing either turning the test red;
**S4** with a stack raised, a request to `/sub/<string>` leaves that string in
**no** service's logs — a stack-wide check, which is why the Caddy half lives here
and not in task 14. **The report must name the file, not the invariant.**
`deploy/warden/Dockerfile:20` carries the same floating-tag defect and is left that
way **deliberately** under the fleet-tooling freeze, so after this task write
"`control.Dockerfile` is pinned" and never "images are pinned" — the second is
false repo-wide and would be a lie in a security report.

**Skip-loudly note.** **S1, S2 and S3 execute** — all three are static assertions
over files. **S4 cannot execute here**: it needs a raised stack. The command that
would prove it is `make e2e-up`, a request to `/sub/<string>`, then `make logs`.
The report must say: *"S4 not executed — no container runtime in this environment;
the stack-wide token-in-logs check is unproven."* This is the most
security-relevant unexecuted scenario in the epic and must be listed first among
the gaps in the Stage 2 PR.

## 17. Integrate M2, and produce the owner's second PR

**Kind:** `review`
**Depends on:** task 8, task 9, task 10, task 11, task 12, task 13, task 14, task 15, task 16
**Backlog item:** none — the second milestone gate.

**Intent.**
Assemble Stage 2 into the second and last owner-facing deliverable of this epic.
Verify against the tree: every acceptance criterion of items 3a, 4, 5, 6, 6a, 7, 8,
9 and 10 traces to a scenario and a run result with its **red-first** proof; the
`edge`↔`control` contract holds, meaning the subscription renderer gained **zero**
lines per transport; **no zone was edited by two owners**; and `make test-control`
and `make test-infra` pass when **you** run them. Open the owner-facing PR from
`develop` to `main` — **open it, never merge it**. The PR body leads with three
things, in this order: **(1) a required owner action** — paste the produced
subscription into the client your friends actually use, before this link goes to
anyone, because that assumption is the only one in the plan a test cannot refute;
**(2) the honest status of M2** — under the accepted answer to X3, M2 is
**delivered, not accepted**: every stack-dependent scenario is listed by id with
its reason and the exact command; **(3) what the owner can now do**, in his terms.
Then state the criteria precisely: criterion 6 **half** closed (database and
render; no push to a live node); criterion 5 advanced to "a stock client parses the
link" and **not** closed; criteria 2 and 3 untouched; **criterion 1 untouched and
unclosable by any test here, now or ever**. Send the stage report through
`scripts/notify.sh`. **Do not** fix code yourself.
**Acceptance bar:** the PR exists; every unexecuted scenario is named; nothing is
reported as "green" that did not run.

**Skip-loudly note.** State per zone the number of scenarios **collected** and
**executed**. `make test-e2e` exits 0 on zero collected tests, so the counts are
the only guard against a false report. A milestone that is delivered but not
accepted must be described in exactly those words.

---

# Stage 3 — the decision gate

## 18. Assemble the M3 decision pack for the owner: money, decoys, port publication, and two charter amendments

**Kind:** `research`
**Depends on:** task 17
**Backlog item:** none — this is where the epic ends and the owner's decisions
begin.

**Intent.**
Everything achievable with zero money and zero live hosts is now done, and the
next backlog item cannot start without decisions only the owner may take. Produce
one short document to
`docs/tracker/directive-90be25f3-9/tasks/xavier-m3-decision-pack-directive-90be25f3-9.md`
that lets him answer **yes/no or pick-one**, never prose. Cover exactly six items,
each with the question, what it blocks, the options, and my recommendation.
**Q4 — money and hosts:** two are needed, a foreign one for M3 and a Russian one
for M4; what is needed now is a monthly ceiling and a "yes, we rent", not the hosts
themselves. *Recommendation: approve a ceiling and one foreign host to start M3.*
**Q5 — the selection principle for Reality decoy destinations:** there will never
be a shared default, because a shared decoy is exactly what makes the whole fleet
enumerable; what is needed is a **principle** (for example: large sites,
geographically close to the node, unrelated to the owner, non-Russian), with
concrete hosts chosen per node at bootstrap. *Recommendation: adopt a principle now;
fixtures stay `example.com` until a real node exists.*
**Q6 — publishing a port:** the delivery endpoint and the panel, and separately
whether they live under one name or two — their access rules are fundamentally
different, and delivery **must** be reachable from inside Russia while the panel
must not. *Recommendation: two names, and publish nothing until that split exists.*
**Q7 — which clients friends actually use:** carry forward the answer from the
Stage 2 PR if it arrived, and mark it blocking for anything past M3 if it did not.
**Amendment C — pending the owner:** record in the charter itself that criterion 1
("survives a whitelist shutdown") has **owner-side acceptance** and is closed by no
test in this repository. It is stated honestly in `README.md`, `CLAUDE.md` and
`.e2e/profile.yml` — but not where the criteria themselves live, and without that
line someone will present a green run in three months and call it done.
*Recommendation: yes.*
**Amendment E — pending the owner:** criterion 3's charter text says "a transport
shipped with hashi (**e.g. AmneziaWG**)"; the parenthesis is an example, not a
requirement, and criterion 3 closes on VLESS + WS + TLS. *Recommendation: replace
the example, or add one sentence saying friend-facing AmneziaWG awaits a second
subscription format.*
**Do not** write code, **do not** dispatch anything, **do not** edit
`docs/product/backlog.md` or `docs/product/charter.md` — an amendment is applied
only after the owner says yes, and in that order. Send the pack through
`scripts/notify.sh` and stop. **Acceptance bar:** the owner can reply to all six in
one message, in single words.

**Skip-loudly note.** No scenarios. The one thing this task must not do is present
the epic as complete: it ends with M3 **not started**, criteria 1, 2 and 3
untouched, criterion 5 half, criterion 6 half, and criterion 4 closed.

---

# Not taken, and why

Items **11-25** of `docs/product/backlog.md` stay exactly where they are, in
status `queued (эскиз)`, untouched by this epic. Sketch text is **not** acceptance
text, and promoting it would mean writing acceptance criteria myself — a `what`
decision that is not the architect's to take.

| Items | What they are | What blocks them |
|---|---|---|
| **11** `infra-node-stack` | compose for a node; pinned Xray/AmneziaWG images; Caddy camouflage front | Its acceptance is worded "comes up locally", so money is not the blocker — **Q5 is**: there is no conservative shared decoy, and a node built on `example.com` is not a cautious first node, it is a broken one |
| **12** `edge-node-bootstrap` | SSH install, lay out, start, verify; **time sync before Xray starts**, or Reality fails with errors that look like blocking | **Q4** — needs a real host. Validating it only against a container we control teaches nothing about the failure it exists to survive |
| **13** `edge-node-health` | liveness probing, initiated **only** by the control plane; a node never dials home | **Q4** |
| **14** `control-apply-and-push` | render and delivery on change — the task that finally makes charter criterion **6** whole, by removing a revoked friend's credential **on the node** | **Q4** |
| **15** `owner-first-connection` | owner acceptance: traffic through a foreign node; closes criterion **5** | **Q4**, and it is the owner's own acceptance |
| **16** `edge-entry-leaf-relay` | the obfuscated cross-border hop, explicit MTU handling, plain WireGuard forbidden here; **AmneziaWG returns here** | **Q4** — needs the second, Russian host |
| **17-19** node state machine, panel screens for nodes and transports | criteria **2** and **3** are worded "from the panel", so the panel arrives with them | M4; depends on 16 |
| **20** `owner-field-test-whitelist` | **owner acceptance of criterion 1**, on a real device on a real Russian mobile network under whitelist restriction | Nothing the fleet can do. **No test in this repository may ever claim criterion 1** — a test that did would be false witness |
| **21-24** full panel, backup/restore, key rotation, decoy rotation | M5 | M4 first |
| **25** `edge-transport-amneziawg-client` | AmneziaWG on a friend's device | `blocked` on adopting a **second subscription format**; until then, enabling it for friends is refused by an explicit error (task 13's S2a), never skipped silently |

**What unblocks them:** task 18's decision pack. Q4 unblocks 11-15, Q4 again
unblocks 16-19, Q5 unblocks any real node, Q6 unblocks the first exposure, and
amendment E should be answered before M4 so nobody reads a parenthesis as a
commitment three months from now.

Also deliberately not taken, and each for a stated reason: any further work on
`deploy/warden/` or `scripts/` (fleet-tooling freeze — two exceptions only, tasks
2 and 4); an e2e job in CI (same freeze — there is no stack worth raising until
M3); tests for `warden`; the `/e2e` command that `.e2e/profile.yml` refers to;
Clash or sing-box as a second subscription format; and payments, public signup,
advertising, multi-tenancy, per-user quotas and a client application of our own —
all charter non-goals, the advertising one carrying a legal penalty for the owner.

---

*Charles Xavier — architect. Eighteen tasks, four stages, two owner-facing PRs and
one decision pack. No acceptance criterion in `docs/product/backlog.md` or
`docs/research/product-owner-ohno-4/research.md` §3 has been reworded, weakened,
dropped or renumbered by this file.*
