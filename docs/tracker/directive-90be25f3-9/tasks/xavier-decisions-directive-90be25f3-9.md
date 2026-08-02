# Architect decisions carried outside `.claude/**` — epic `directive-90be25f3-9`

**From:** Charles Xavier (architect)
**Task:** `prepare-the-tree-sync-develop-land-the-architect-owned-edits-10` —
task 1 of 18 of epic `directive-90be25f3-9` (Stage 0 — preparation)
**Date:** 2026-08-02
**Status:** **in force** (except `DEC-D`, which is explicitly *proposed* — see §5)

This file exists because `.claude/**` is write-protected — re-verified by probe in
this session — and three decided corrections plus one autonomy raise have nowhere
else to live where a later task can read them.

---

## 0. How to cite this file

| Id | What it decides | Where |
|---|---|---|
| `DEC-A` | `render_client` returns a `ClientEntry`, not a `dict`; `02-edge-rulebook.md:66` and its contract-table row are stale | §2, block `## A` |
| `DEC-B` | The `edge/registry.py` edit is authorised **once**, inside the first transport only; the rulebook's unconditional ban is stale in that one place | §2, block `## B` |
| `DEC-C` | What `origin` actually is, and the branch/PR rules that follow from it | §3 |
| `DEC-X1` | Merge authority: L2 for `develop` only; `main` never agent-merged; a "big stage" is a milestone | §4 |
| `DEC-D` | The same drift in `.claude/git-workflow.md` — **proposed, not in force** | §5 |
| `OBL-1` | Task 4 must verify the Xray asset against a **committed SHA-256** and fail closed | Appendix B, §B1 |
| `OBL-2` | Package data, the `include-package-data` trap, the banned `control/**/secrets/` package name, and enumerating the artifact boundary | Appendix B, §B2 |
| `OBL-3` | `DEC-X1` is escalated but unanswered; every stage gate restates that it is the architect's unconfirmed reading | Appendix B, §B3 |

The `OBL-` rows are **obligations**, not amendments: they do not correct a
rulebook, they bind a later task's implementation, and they are cited by id the
same way. Appendix A is a **record** of the dependency set, not a decision — the
decision lives in `pyproject.toml`. Appendix C records where this file exceeds
what §1(e) of the decomposition authorises.

A spec cites the decision **id** plus this path — for example *"per `DEC-B`,
`docs/tracker/directive-90be25f3-9/tasks/xavier-decisions-directive-90be25f3-9.md`"*.
A spec **never paraphrases the decided text**: the wording below is the decision,
and a restatement in a spec is a second source that can drift from it.

---

## 1. Precedence

1. Where this file and a file under `.claude/**` disagree **on a point recorded
   here**, **this file governs**, and the rulebook is stale at the named line.
   The rulebook is not wrong everywhere — it is wrong there.
2. It governs **nothing else**. Every rule in every rulebook that is not amended
   below stands, unmodified and unweakened, including every rule in the same file
   and the same section as an amended one.
3. It grants **no permission** beyond `DEC-X1`. Nothing here may be read as
   licence to widen a zone boundary, to add a dependency, to touch `main`, or to
   skip a gate.
4. It is **not a substitute for applying the corrections**. When the owner lifts
   the write protection on `.claude/**`, corrections A, B and C are applied from
   here **unchanged**, and this file's §2 and §3 become the record of what was
   applied rather than the place the rule lives.
5. **A "Default if unanswered" may settle facts and process. It never grants a
   permission the charter reserves to the owner.** An architect's default is an
   agent's own reading of silence; it can decide *how* the fleet proceeds, what a
   term means, or which of two readings of an instruction to run on. It cannot
   manufacture consent. **Where this file claims a permission, it must cite the
   owner's own words** — the directive, the charter, or a written answer — and
   name the clause. A default may then stand *beside* that citation as the
   elaboration of what the owner said; it may never stand *instead* of one. This
   rule is why §4 is sourced to the directive's clause 4 and why §5 holds `DEC-D`
   back, and the two are the same standard applied twice, not two standards.

---

## 2. Corrections A and B — verbatim, unchanged

Copied byte for byte from
`docs/tracker/ohno-5/tasks/xavier-blocked-edits-ohno-5.md` (task `ohno-5`,
2026-08-01), where they were written, resolved to final text, and left unapplied
because `.claude/**` is write-protected. The block below runs from that file's
`## A` heading to the line before its `## C` heading, contiguous and unedited —
no re-heading, no renumbering, no reflowing, and no fixing of anything. Its
contiguity is proved mechanically by the check in §8.2 of this task's spec, which
is also why the decision ids `DEC-A` and `DEC-B` live in §0's table and **not** as
inserted lines above `## A` and `## B`: an inserted line would break the copy and
make "verbatim" unprovable.

## A — `.claude/projects/02-edge-rulebook.md` — B1, `render_client`'s return

### A1. Layout block

Replace:

```
      render.py      render_server(node, params) -> str
                     render_client(node, credential) -> dict
```

with:

```
      render.py      render_server(node, params) -> str
                     render_client(node, credential) -> ClientEntry
```

### A2. Contract table row

Replace:

```
| `render_client(node, credential) -> dict` | pure | a fragment the subscription renderer can serialise without knowing the protocol |
```

with:

```
| `render_client(node, credential) -> ClientEntry` | pure | the transport's own finished serialisation of one client entry, plus protocol-agnostic metadata — see below |
```

### A3. New section, inserted directly after the closing sentence of *Interfaces this zone exposes* ("…has broken the charter's "new protocol is one package"."), before `## Testing`

```markdown
### What `render_client` returns, and why it is not a dict of parts

The v1 subscription format is a base64-encoded list of client-entry URIs
(`docs/product/charter.md`, amendment A). Every part of a VLESS + Reality URI is
protocol-specific: the scheme *is* the protocol name, and the query carries
`security`, `pbk`, `sid`, `fp`, `sni`, `flow`. If `control` assembled that URI
from a dict of parts it would have to branch on the protocol — breaking core
invariants §1 and the charter's fourth success criterion in the same move.

So the transport owns its serialisation end to end. `render_client` returns a
`ClientEntry` carrying:

| Field | What it is |
|---|---|
| `entry` | the complete serialised client entry for this node × this transport — one line, ready to place in the subscription, **without a display label** |
| `display_label` | the human-readable name this entry should show in a client |
| `country_label` | the exit country, taken from the node record's location label — **never** a geo lookup on the node's address |
| `node_id` | which node this entry points at, so `control` can order, filter and revoke without ever parsing `entry` |

`control`'s half of the contract, and all of it: order the entries, compose the
display text from `display_label` and `country_label`, append it as the URI
fragment, join, base64-encode. It treats every field as opaque text — it never
parses `entry`, never branches on any value, and never compares a label or a
transport name against a literal. Labelling stays in `control` deliberately: the
fragment is a property of the *subscription format*, shared by every scheme in
it, so the charter's one-link-many-countries behaviour is written once instead of
once per transport.

The test of this contract is arithmetic: adding a transport adds **zero** lines
to the subscription renderer.

A transport whose serialisation cannot carry an externally appended display
label is not deliverable in the v1 subscription format. That is a question about
*which transport to ship*, and it belongs to the PO — it is not a licence to move
assembly back into `control`.
```

### A4. Testing bullet

Replace:

```
- Unit tests only for pure branchy logic: parameter validation, port allocation,
  client-fragment serialisation.
```

with:

```
- Unit tests only for pure branchy logic: parameter validation, port allocation,
  client-entry serialisation.
```

---

## B — `.claude/projects/02-edge-rulebook.md` — B3, the registry edit

### B1. Cross-reference in *Where a new file goes*

Replace:

```
**Where a new file goes:** a new protocol is a new directory under `transports/`
and nothing else. If a change needs an edit in `registry.py`, the profile
contract is too narrow — say so instead of special-casing.
```

with:

```
**Where a new file goes:** a new protocol is a new directory under `transports/`
and nothing else. If a change needs an edit in `registry.py`, the profile
contract is too narrow — say so instead of special-casing. One exception exists,
scoped to the first transport only — see *Completing the contract* below.
```

### B2. New section, inserted immediately after section A3 above

```markdown
### Completing the contract — authorised once, in the first transport

Two symbols in the table are ahead of the code, and closing that gap is a
deliberate, single, architect-authorised act:

- `TransportMeta` (`edge/registry.py`) carries `name`, `family` and `needs_tls`,
  and **not** the default port range the table requires;
- `ClientEntry` does not exist yet.

Adding both to `edge/registry.py` is authorised **inside M1 item 1
(`edge-transport-contract-vless-reality`) and only there** — architect decision,
recorded in §7.2–§7.3 of
`docs/tracker/product-owner-ohno-4/tasks/xavier-review-ohno-product-owner-ohno-4.md`.
This is the contract being completed for the first time, not widened to fit a
special case, which is why it is not the failure the rule above describes.

From the second transport onward that rule applies unchanged and without appeal:
**a transport that needs an edit to `registry.py` is a contract failure.** Stop
and raise it with the architect. The contract is fixed by its first
implementation; every transport after it is one directory and nothing else.
```

**Note for the item-1 spec, not for this file:** `edge/AGENTS.md:30-32` still
says flatly that a change needing a `registry.py` edit means the contract is too
narrow. That file is in the `edge` zone, so it is Neumann's to change, not mine.
Item 1's spec must carry the authorisation explicitly *and* instruct him to bring
`edge/AGENTS.md` into line in the same run — otherwise he reads it on day one and
correctly escalates.

---

## 3. DEC-C — correction C, re-issued against the tree of 2026-08-02

The original section C was written when `origin` carried only `main`.
`origin/develop` exists today (`77493c9`), task 1 of this epic fast-forwarded it
to `main`, and the stale `origin/task/2-control-plane-…` branch is also present.
So `git pull origin develop` is executable and `gh pr create --base develop` has a
target. C is therefore **superseded, not repeated**; the text below replaces it in
full and is what gets applied to `.claude/workflow.md` when the protection is
lifted.

Replacement for rules 1–4 of *Iron rules (no exceptions)* in `.claude/workflow.md`:

````
1. Agents **never** push, merge or open PRs targeting `main`. `main` is the
   branch this repository publishes from, and releasing into it is a human
   action. This survives every autonomy raise, including the one in
   `DEC-X1` — read *What `origin` actually is* below before taking rule 1 and
   rule 3 as a contradiction.
2. Agents **never** run `git revert`, in any branch.
3. All PRs target `develop`, and `develop` is a real remote integration branch:
   `gh pr create --base develop` works today.
4. Before starting a task, sync the integration branch:
   ```bash
   git fetch origin
   git checkout develop && git merge --ff-only origin/develop
   git merge origin/main --no-edit      # only when `main` has moved ahead
   ```
   Skip it and you branch from a tree missing everything merged since. If the
   fast-forward is refused, `develop` and `origin/develop` have diverged: stop
   and escalate — do not force anything.

### What `origin` actually is

Stated plainly, because two of the rules above read wrongly without it:

- `origin` **exists** and is a GitHub remote,
  `https://github.com/earlzdev/Hashi.git`.
- It carries **`main` and `develop`**. `develop` was six commits behind `main`
  until task 1 of epic `directive-90be25f3-9` fast-forwarded it; the two tips
  were equal at that moment. A stale `origin/task/2-control-plane-…` branch is
  also present and is left alone deliberately.
- `git pull origin develop` **is** executable and `gh pr create --base develop`
  **does** have a target. Neither was true when this rule was first written.
- Rule 1 is not contradicted by `main` being the published branch. The owner
  published it; an agent may not. Agents push **task branches and `develop`**,
  and nothing else. That permission is sourced to **clause 4 of the owner's
  directive** — *"small PRs are the fleet's own business — review and merge them
  yourselves"* — which cannot be carried out on a branch that was never pushed.
  `DEC-X1` is where the reading of that clause is recorded and bounded (§4); it
  is not itself the origin of the permission, and citing `DEC-X1` alone would be
  circular.
- The fleet's git credential is `GH_TOKEN`, wired into `git` and `gh` at
  container boot. No agent reads it. An **empty** `GH_TOKEN` is a supported
  mode: the push fails, the project stays local-only, and the completion report
  lists **which files changed** instead of a PR link. Do not treat that as a
  failure and do not work around it.
````

---

## 4. DEC-X1 — the autonomy raise

### 4.1 Where the permission comes from

Per §1.5, a permission must be sourced to the owner's own words. It is, and the
chain is shorter than an earlier draft of this file made it look.

**Quotation 0 — the owner's directive, clause 4**, as reduced to its operative
clauses at §0 of
`docs/tracker/directive-90be25f3-9/tasks/xavier-epic-questions-directive-90be25f3-9.md`:

```
4. **After each big stage:** a status report and a PR. **Small PRs are the fleet's
   own business** — review and merge them yourselves; the owner sees finished
   features only.
```

**What Quotation 0 is, and where the owner's own words are.** The block above is
byte-identical to §0 of that questions file, so a reviewer can verify
*decisions → questions* mechanically, by comparison. That does **not** close the
chain, because the questions file describes its own §0 as the owner's Russian
directive *"reduced to its four operative clauses"*. Quotation 0 is therefore an
**architect-authored English reduction** of the directive, not the owner's literal
words.

The owner's words are Russian, and they are recorded in **`docs/product/backlog.md`,
section *Журнал решений*, the decision-log row dated 2026-08-02
(`directive-90be25f3-9`)**, which quotes the directive — including
«…ревьютите и мержите их сами, мне только готовую фичу». That row is **itself
abridged**: it carries an elision mark between clauses 1 and 3
(«…команда флота разрабатывает проект**…**на выходе я хочу готовый сервис для
VPN»). **Clause 4, the one `DEC-X1` rests on, is quoted whole and unelided**, so
the authority chain is unaffected — but in a chain-of-authority document,
overclaiming precision is the exact failure this section exists to disclose.
A reviewer who wants the original must read that file. It is the **Product Owner's uncommitted work**, it is
correctly outside this task's boundary, and this task does **not** commit it.

The consequence is stated rather than hidden: *questions → owner* is **not**
verifiable from this PR. Security review checked the reduction against the Russian
original during this session and found it faithful — «ревьютите и мержите их сами»
is rendered exactly and the permission is not widened by the reduction — but that
check was possible only because this sandbox holds the uncommitted file, and it is
not reproducible by a reviewer reading the PR alone. The bottom link of the
authority chain is not in git; putting it there is the Product Owner's to do, not
this task's.

This is an **owner statement**, not an agent default. It is the source of the
permission, and the entailment is mechanical: a PR that is never pushed cannot be
opened, cannot be reviewed, cannot be merged, and cannot be shown to the owner as
a finished feature. Instructing the fleet to review and merge its own PRs is
therefore instructing it to **push the task branch and `develop`**. That push is
*entailed by the owner's instruction*; it is not inferred by an agent from
silence, and it is not a "Default if unanswered" doing work §1.5 forbids.

The charter's §Autonomy (`docs/product/charter.md:214`) lists "creating a remote
repository, pushing, or publishing anything" as always-ask. Clause 4 **is** the
owner asking for the thing that requires it, for this epic. The charter reserves
the decision to the owner; the owner took it.

### 4.2 What the permission does **not** cover

`DEC-X1` extends to **pushing task branches and `develop`, and to nothing else.**
It is **not** a precedent for defaulting any other always-ask item open.

The directive is silent on the rest of the charter's always-ask list, and silence
is not consent:

| Always-ask item | Directive says | Status |
|---|---|---|
| Publishing a port to the internet | nothing | **always-ask, unanswered — Q6** |
| Spending money / renting a host | nothing | **always-ask, unanswered — Q4** |
| Touching a live node, real provider account, real credentials | nothing | **always-ask, unanswered** |
| Changing what data is collected or retained | nothing | **always-ask, unanswered** |
| Pushing `main`, publishing a release | nothing | **always-ask; iron rule, never agent-taken** |

Every row above stops the queue and escalates through `scripts/notify.sh`. A task
that cites `DEC-X1` for any of them is misciting it, and that is a review finding.

### 4.3 Residual risk — recorded, not resolved

**The reading of clause 4 in §4.1 is the architect's. The owner has not confirmed
it in writing.** The directive says "merge them yourselves"; it does not say
"push". The step from one to the other is an inference, and although it is a
strong one — the instruction is unexecutable without it — an inference is what it
remains.

- **Escalated — a completed fact, not a promise.** The orchestrator sent it to the
  owner through `scripts/notify.sh` at **`2026-08-02T10:04:22Z`**, recorded at
  **line 55 of `docs/tracker/notifications.log`**, subject *"OWNER DECISION
  REQUESTED — epic `directive-90be25f3-9`, task 1 of 18 (`prepare-the-tree-…-10`),
  PR #3 -> `develop`"*. Its content, so that this file is readable without the log:
  that `DEC-X1` was originally sourced to an **architect's own default** against a
  charter always-ask item; that it has since been re-sourced to **clause 4 of the
  owner's own directive**; that security review accepted that chain as stronger
  than a default and verified the quotation byte-exact; that **the reading is the
  architect's and is unconfirmed in writing**; that if the owner disagrees the
  remedy is to **stop self-merging** and **not** to unwind `develop`; that nothing
  is on `main`; and that **Q4** (money and hosts) and **Q6** (publishing a port)
  remain always-ask and unanswered. What is **not** done is the owner's answer —
  that residue is carried as `OBL-3` (Appendix B, §B3).
- **If the owner disagrees, the remedy is to stop self-merging** — the fleet
  reverts to opening PRs and stopping, and `DEC-X1` is struck. The remedy is
  **not** to unwind what is already on `develop`: that work was reviewed, gated
  and merged in good faith, and `main` — the only branch the owner publishes
  from — has never been touched by an agent and never will be.
- Nothing in this section is a licence to proceed further while the escalation is
  outstanding than §4.2 already allows.

### 4.4 The recorded reading, verbatim

The two quotations below are the *elaboration* of clause 4 — the architect's
worked-out reading of what the owner's words mean operationally. Per §1.5 they
stand **beside** Quotation 0, never instead of it.

**Quotation 1** — the *Default if unanswered* of **X1** in
`docs/tracker/directive-90be25f3-9/tasks/xavier-epic-questions-directive-90be25f3-9.md`,
quoted verbatim:

```
Read the directive as an explicit, task-scoped raise to
**L2 for `develop` only**:
- the fleet opens one PR per backlog item into `develop` and **merges it itself**
  after all L2 gates are green (review `VERDICT: CLEAN`, security clean, the
  zone's verify command run by the reviewer, no cross-zone edits);
- **`main` is never agent-merged**, at any level, for any reason — that iron rule
  survives the directive untouched, and releasing `develop` into `main` stays a
  human action;
- a **"big stage" = a milestone**. Two owner-facing deliverables in this epic:
  **Stage 1 = M1** (items 0, 1, 1a, 2, 3) and **Stage 2 = M2** (items 3a, 4, 5, 6,
  6a, 7, 8, 9, 10), each ending in a `develop → main` PR for the owner to review,
  plus a status report through `scripts/notify.sh`;
- the raise is recorded in `docs/tracker/directive-90be25f3-9/`, **not** in
  `.claude/git-workflow.md` — that path is write-protected (see **X5**), and I
  will not have two documents disagreeing about who may merge.
- Blockers, red gates and questions still escalate **immediately** and stop the
  queue, at every level. Batching lowers noise, never escalation.
```

**Quotation 2** — the *Merge model (X1)* standing rule from the header of
`docs/tracker/directive-90be25f3-9/tasks/xavier-epic-decomposition-directive-90be25f3-9.md`,
quoted verbatim:

```
the fleet opens one PR per task into `develop` and merges
  it itself once the review verdict is `CLEAN`, security is clean and the zone's
  verify command passed **when run by the reviewer**. **`main` is never
  agent-merged.** Blockers, red gates and questions escalate immediately through
  `scripts/notify.sh` and stop the queue — batching lowers noise, never escalation.
```

**Architect's note, not part of either quotation.** This raise is **task-scoped to
epic `directive-90be25f3-9`**: it is the reading of the owner's directive for this
epic and it expires with it, so no task outside the epic may cite `DEC-X1` as
authority. It is recorded here and deliberately **not** in
`.claude/git-workflow.md` — that path is write-protected, and two documents
disagreeing about who may merge is precisely the failure being avoided. It changes
**nothing** about `main`: `main` is never agent-merged and never pushed to, at any
autonomy level, for any reason.

---

## 5. DEC-D — proposed, not in force

> **Status: proposed — not in force. Owner decision required.**
>
> D is carried here in full so that whoever eventually edits
> `.claude/git-workflow.md` has the text in one place, and **for no other
> reason**. It is not applied, it is not cited as authority, and no spec in this
> epic may quote it as a decision.
>
> Two of its four points describe what an agent is *allowed to do*, not merely
> what is true, and a permission is the owner's to grant. The permission this
> epic actually runs on comes from the owner's own directive, recorded as
> `DEC-X1`; **D adds nothing to it and takes nothing from it.**
>
> Where D's factual claims overlap `DEC-C` — that the remote exists, that
> `git pull origin develop` works, that `gh pr create --base develop` has a
> target — **`DEC-C` governs**, because C is re-issued against today's tree and
> D was written against yesterday's. Where they do not overlap, D is inert.

The proposed text, verbatim from the `ohno-5` file:

## D — `.claude/git-workflow.md` — same drift, flagged not assumed

Not one of the three §7.7 items. It is my document, it carries the identical
factual drift, and once C lands the two contradict each other — which is the
exact failure C exists to remove. I am proposing it rather than deciding it,
because two of the four points touch what an agent is *allowed to do*, not just
what is true.

1. **Branch flow** (`:29-34`) — same fix as C's rule 4: drop
   `git pull origin develop`, keep the local merge.
2. **Credentials** (`:110-113`) — "**This project has no remote; there is nothing
   to authenticate.**" is false. Replace with: the remote exists, the owner is
   the only one who has pushed to it, and agent pushing stays always-ask under
   the charter. The token paragraphs below it are already written as
   "when a remote is added" and become live guidance unchanged.
3. **Opening the PR** (`:52-57`) — `gh pr create --base develop` cannot succeed
   today. Gate the whole block on `develop` having been published *and* the push
   authorised for that task.
4. **When there is no remote** (`:134-138`) — retitle to *When there is no PR
   target* and state the current condition, since "no remote" is now wrong while
   the behaviour it prescribes is still right.

---

## Appendix A — the authorised dependency set

A **record, not a new decision**. The decision itself lives in `pyproject.toml`,
which is where a build reads it; this appendix exists so that a spec citing the
set has one place to point at.

| Package | Pin | Why this version |
|---|---|---|
| `sqlalchemy[asyncio]` | `==2.0.51` | Current 2.0 release and the only series with native asyncio; ships a `cp314` wheel, and the `asyncio` extra resolves `greenlet 3.5.4`, where 3.14 support landed |
| `asyncpg` | `==0.31.0` | **Forced, not preferred** — the only candidate pip sees on Python 3.14; it is a C extension, so there is no pure-Python fallback |
| `alembic` | `==1.18.5` | Current release, pure Python; pulls `Mako` and `MarkupSafe 3.0.3` (`cp314` wheel present) |
| `itsdangerous` | `==2.2.0` | Current release, pure Python, no compiled dependency; the signing primitive under Starlette's session middleware |
| `argon2-cffi` | `==25.1.0` | Current release, first to declare 3.14; pairs with `argon2-cffi-bindings 25.1.0` on `cffi 2.1.0`, the release with a `cp314` wheel |
| `cryptography` | `==50.0.0` | Current release; its `cp311-abi3` wheel covers 3.14 through the stable ABI. Fernet for node secrets at rest |

**No other dependency is authorised anywhere in this epic.** Not "not yet" — the
six above are the complete set for all eighteen tasks. A task that needs a seventh
**stops and escalates to the architect**; it does not edit `pyproject.toml`, which
belongs to no zone precisely so that this decision cannot be taken by an
implementer (core invariants §5).

The four pre-existing dependencies — `fastapi`, `uvicorn`, `pydantic-settings`,
`jinja2` — stay **unpinned**. Pinning them is defensible and is a separate owner
decision; it was not authorised for this epic and was not smuggled in here.

### A.1 Security-patch escape hatch — a bump is not a new dependency

The rule above forbids a **seventh package**. Read literally it also appeared to
forbid **moving an authorised pin**, which would be a hole: `cryptography`
statically bundles OpenSSL, so an OpenSSL advisory against `50.0.0` is remediable
in exactly one way — a version bump. A rule that freezes the fleet on a known-bad
crypto build is a worse rule than no rule.

**The hatch is not patch-level, and cannot be.** An earlier wording pre-authorised
only a **patch** bump, which fails in the exact case it was written for:
`cryptography` has historically shipped bundled-OpenSSL fixes in a new **minor**,
so an advisory against `50.0.0` may well be remediable only at `50.1.0` or
`51.0.0`. A patch-only hatch does not cover that, and the fleet stops on a
known-bad crypto build. It fails *closed* — the bump routes to escalation rather
than proceeding unverified, which is the safe direction — but stalling is not the
job the hatch exists to do.

So, explicitly:

- **Moving an already-authorised package to the minimum version carrying the fix
  for a published advisory is pre-authorised, whatever the level of that
  version — patch, minor or major.** It does not stop the queue and does not wait
  for the architect. What is pre-authorised is the **minimum** version that
  carries the fix; going further than the fix requires is an ordinary version
  change and escalates.
- The pre-authorisation requires a **published advisory id**. No id, no hatch.
- The pin stays an exact `==` pin. Nothing here loosens a pin to a range.
- It requires a note in this file's change log naming the package, the old and new
  pins, and the advisory id — and, **when the bump is not patch-level, saying so
  explicitly and naming the level** ("minor", "major") together with the reason no
  lower version carries the fix. A minor or major bump may carry behaviour change
  with it; the reader of the change log is entitled to know that a bump was one
  without diffing the pins themselves.
- **It is not a new dependency.** The authorised set is still the six packages
  named above; only a version moved.
- A bump for **any reason other than a published advisory** is **not** covered,
  at any level: that is a behaviour change wearing a security costume. Stop and
  escalate to the architect.
- **Adding a package still stops and escalates**, advisory or not. If the only
  remediation is a new package, that is an architect decision (core invariants
  §5) and the queue waits.
- The bump is a `pyproject.toml` change, so the **architect makes the edit**; the
  pre-authorisation removes the *deliberation*, not the ownership. A developer
  who finds the advisory reports it and does not touch the file.

### A.2 Re-check point at each stage gate

The six pins are **re-checked against published advisories at every stage gate**
— at **M1** (end of Stage 1, items 0, 1, 1a, 2, 3) and at **M2** (end of Stage 2,
items 3a, 4, 5, 6, 6a, 7, 8, 9, 10) — before the `develop → main` PR is raised for
the owner. A pin that has gone stale against an advisory is remediated under §A.1
in that gate, not carried into the owner's review unmentioned. The gate's status
report states which pins were checked and the outcome, even when the outcome is
"no advisories".

**Known gap, recorded deliberately: between M1 and M2 nothing triggers a check.**
The gates are the only scheduled re-check, and in between the sole trigger is *a
developer happening to notice an advisory* — which is not a mechanism, because
nothing in this epic causes it to happen. An advisory published the day after M1
is discovered at M2 or not at all. This is accepted rather than fixed: the epic
reaches **no live host and no published port**, the artifacts are a repository and
an unshipped image, and the exposure of a stale pin here is a build that would be
rebuilt before it ever served traffic. **Do not build a scanner for it** — adding
dependency scanning is tooling work under the fleet-tooling freeze and is not in
this epic's scope. It is written down so that the first task that *does* reach a
live host inherits a known gap rather than an assumption of coverage.

---

## Appendix B — forward obligations on later tasks

**Binding.** Unlike Appendix A, which records a decision taken elsewhere, this
appendix *creates* obligations. They arose from the security review of task 1 and
they bind the tasks named. A task cites them by id (`OBL-1`, `OBL-2`, `OBL-3`)
exactly as it cites a `DEC-`. Holmes holds each named task to its obligation at
code review, and a task that lands without it is a review finding, not a
follow-up.

### B1 — `OBL-1`: task 4 must checksum the Xray binary, and fail closed

Task 1 added `.tools/` to `.gitignore` for the upstream-checker binary that task 4
fetches. The ignore rule is correct and stays — a binary in history is not
reviewable — but it has a consequence worth stating plainly: **a substituted
binary under `.tools/` leaves no trace in git.** Nothing in the repository would
show it. The only control that can exist is the one at fetch time, and task 1 did
not build it: task 1 wrote a comment describing a control that task 4 has not yet
implemented.

So it is written down as an obligation rather than assumed:

- Task 4's Make verb **verifies a pinned SHA-256 of the release asset**, and that
  digest is **committed in this repository** — in the Make verb, or in a checksum
  file next to it that the verb reads. It is reviewable in a diff.
- **The authoritative digest is the one committed here.** If both a repository
  constant (Makefile or checksum file) and an upstream-published checksum file
  exist, the **committed** value is the one compared against, and an upstream
  checksum file is not a substitute for it: an attacker who can serve a substituted
  asset can serve a matching checksum beside it. Verifying only the upstream file
  satisfies the letter of this obligation and none of its purpose, and is a review
  finding.
- **Verify before the artifact can be used.** The digest is checked **before** the
  downloaded bytes reach their final path under `.tools/` and **before** anything
  makes them executable. Download to a temporary location, verify, and only then
  move into place and set the executable bit. A download → `chmod +x` → verify
  ordering does not satisfy this obligation even though it ends in a check: it
  leaves a runnable binary of unverified provenance on disk, in the window between
  the two steps.
- **A pinned release tag is not sufficient and does not satisfy this obligation.**
  A tag is mutable: upstream can move or re-cut it, and a re-pointed tag fetches
  different bytes through an unchanged pin. The digest is the control; the tag is
  only how the asset is located.
- **Fail closed.** On digest mismatch the verb exits non-zero, removes or refuses
  to install the downloaded file, and says what mismatched. It does not warn and
  continue, does not fall back to an unverified copy, and does not re-download in
  the hope of a better result.
- The digest is updated only by deliberately re-pinning to a new upstream release,
  in a diff a reviewer can see, with the new version stated.

### B2 — `OBL-2`: package data, and the packaging traps around it

Task 1 replaced the explicit package list in `pyproject.toml` with pattern-based
discovery. Two facts about the result must reach tasks 3, 5 **and 13** intact,
because both are easy to discover the wrong way round.

**Task 13 is named deliberately**, and it was missed when this obligation was
first written. It is the `control`-zone task that creates the operator's node and
friend forms, so it is the task most likely to add `.html` templates under
`control/` — and it would hit the uninstalled-package-data trap below unwarned,
masked by `control.Dockerfile`'s copy exactly as the status quo is masked today.

**Package data is installed by neither the old configuration nor the new one.**
`*.j2` and `*.html` under `control/` and `edge/` do not reach an installed
distribution. This is not a regression introduced by task 1 and it was recorded at
the time as assumption **A6** of that task's spec. It is currently **masked**:
`control.Dockerfile` also copies `control/` and `edge/` into `/app`, so the
templates are present in the running image by that route and everything appears to
work. **That accident must not be mistaken for correct packaging.** Anything that
relies on `pip install .` producing templates — a wheel, a slimmer image, an
editable-install test, a second image stage — will fail, and it will fail at
runtime rather than at build time.

**When templates must ship, the fix is an explicit glob and nothing else:**

- Use `[tool.setuptools.package-data]` naming the packages and the exact patterns
  (`*.j2`, `*.html`).
- **Never** `include-package-data = true`, and **never** a `MANIFEST.in`
  `recursive-include`. Both sweep by location instead of by pattern, and either
  one can pull a key, a certificate or an `.env`-shaped file into a wheel — a
  wheel being an artifact that gets copied to places a repository checkout never
  goes. The narrow glob is not pedantry; it is the whole control.
- **In the same edit, make the artifact boundary enumerated rather than implied.**
  `include = ["control*", "edge*"]` auto-collects any future package under those
  roots, so the set of things that can reach a distribution is defined by what
  happens to exist rather than by what was chosen. A `[tool.setuptools.package-data]`
  block must therefore be **paired with an explicit `exclude` in
  `[tool.setuptools.packages.find]`** naming what is not shipped, so that adding a
  package under `control/` or `edge/` is a decision someone takes rather than a
  side effect they inherit. The ban on a package named `secrets` below is one
  instance of this class; the `exclude` is the control for the class itself.

**Do not create a package directory named `secrets` under `control/`.** The
find-pattern now auto-collects any future package under `control/` or `edge/`,
so the artifact boundary is implicit rather than enumerated. Holmes demonstrated
that a `control/app/secrets/__init__.py` **would** be collected. No key material
landed in that demonstration — setuptools collects only `.py` files without a
`package-data` entry, and `.gitignore` already excludes `secrets/`, `*.key` and
`*.pem` from the repository — but the name is now the kind of trap that reads as
safe. Pick another name.

**Either change comes back to the architect.** Adding a `package-data` block,
adding the paired `exclude`, or adjusting the find-pattern, is a `pyproject.toml`
change. That file belongs to no zone precisely so this class of decision is not
taken by an implementer (core invariants §5). A task that needs it **stops and
asks**; it does not edit the file.

### B3 — `OBL-3`: `DEC-X1` is unconfirmed, and every stage gate says so

§4.3 records that the escalation **has been sent** — `2026-08-02T10:04:22Z`, line
55 of `docs/tracker/notifications.log`. What has **not** happened is the owner
answering it. A sent escalation is not an answered one, and the gap between the
two is exactly where an unconfirmed reading quietly becomes settled practice by
repetition.

So, binding on the two stage gates — **task 7 (M1)** and **task 17 (M2)** — and on
any status report either sends through `scripts/notify.sh`:

- The report and the owner-facing PR body **restate that `DEC-X1` is the
  architect's reading of clause 4 of the owner's directive and is unconfirmed in
  writing**, naming the escalation's timestamp so the owner can find it. One short
  paragraph; it is not buried in a footnote and it is not dropped because the
  previous gate already said it.
- It restates the bound: `DEC-X1` covers **pushing task branches and `develop` and
  nothing else** (§4.2), and **`main` is never agent-merged**.
- It restates the remedy on disagreement: **stop self-merging**, strike `DEC-X1`,
  and **do not unwind `develop`**.
- **This obligation lapses the moment the owner answers**, in either direction,
  and the answer is recorded here in the change log with its date. Until then it
  is restated at every gate. Silence across two gates is still silence; it is
  never taken as agreement.

`OBL-3` grants nothing and withdraws nothing. It is a reporting obligation about a
permission whose scope is fixed in §4.2, and no task may cite it as authority for
anything.

---

## Appendix C — this file against §1(e) of the decomposition

Recorded because the reconciliation is the architect's and hiding it would be the
defect. **§1(e) of
`docs/tracker/directive-90be25f3-9/tasks/xavier-epic-decomposition-directive-90be25f3-9.md`
names four things this file must carry:** corrections A and B verbatim, a
re-issued correction C, and the recorded autonomy raise from X1. They are §2, §3
and §4.

Everything else in this file is **beyond that authorisation**:

| Section | What it is | Why it is inert |
|---|---|---|
| §5 — `DEC-D` | The proposed `.claude/git-workflow.md` correction, carried as text | Marked **proposed — not in force**. Not applied, not citable as authority, and no spec in this epic may quote it as a decision (§5's own banner) |
| Appendix A | A record of the dependency set already decided in `pyproject.toml` | A **record, not a decision** — it decides nothing and adds nothing that the build does not already read from `pyproject.toml` |
| Appendix B | Forward obligations from the security review of task 1 | **Not inert** — see below |
| Appendix C | This section | Bookkeeping |

§5 and Appendix A are **not deleted**: deleting text that is correct, marked
non-authoritative and useful to a later reader would trade a documentation
discrepancy for a loss of work. But the discrepancy is real, and the task's own
spec says: *"Where this spec and §1 disagree, §1 wins and the disagreement is a
defect in this spec."* It is recorded here, in that spec, and in the change log.
**The reconciliation is the architect's** — either §1(e) is widened to name what
the file actually carries, or the surplus moves to a file of its own. It is not a
later task's problem and no later task may act on the discrepancy.

**The epic decomposition file is deliberately not edited** to make this go away.
It is the approved decomposition; amending it after the fact to match what was
built is how a record stops being one.

**Appendix B is a different case and is called out separately.** It also exceeds
§1(e), but it is **not inert** — it binds tasks 3, 4, 5 and 13 (`OBL-1`, `OBL-2`)
and the two stage gates, tasks 7 and 17 (`OBL-3`). It is carried here because it arose
from the security review of this very task, and because a forward obligation with
no home is an obligation nobody inherits. If the architect reconciles the surplus
by moving it, `OBL-1`, `OBL-2` and `OBL-3` move **with their citations updated in
the specs and in `children.json` that cite them**, not silently.

---

## Change log

| Date | Change |
|---|---|
| 2026-08-02 | created by task 1 of the epic. A and B copied verbatim; C re-issued; X1 recorded; D carried as proposed. |
| 2026-08-02 | **Fix round 1**, after review (`0 must-fix, 2 should-fix`) and security review (4 findings). §1: added precedence rule **5** — a "Default if unanswered" may settle facts and process but never grants a permission the charter reserves to the owner. §4: re-sourced `DEC-X1` to **clause 4 of the owner's directive** (Quotation 0) with the X1 default demoted to elaboration; added §4.2 (the permission covers pushing task branches and `develop` **and nothing else**; Q4 money and Q6 port publication remain always-ask and unanswered) and §4.3 (residual risk — the reading is the architect's, unconfirmed; escalated to the owner; the remedy on disagreement is to stop self-merging, not to unwind `develop`). §3: push authority re-sourced to the directive clause, removing the circular citation to `DEC-X1`. Appendix A: added **§A.1** security-patch escape hatch (a patch bump of an authorised package against a published advisory is pre-authorised and is not a new dependency; adding a package still stops and escalates) and **§A.2** a pin re-check at the M1 and M2 stage gates. Added **Appendix B** — `OBL-1` (task 4 verifies a committed SHA-256 of the Xray asset, not a mutable tag, and fails closed) and `OBL-2` (package data ships only via an explicit `package-data` glob; never `include-package-data` or `MANIFEST.in recursive-include`; no package named `secrets` under `control/`; either change returns to the architect). Added **Appendix C** — this file carries §5 and Appendix A beyond what §1(e) names; both inert, neither deleted, reconciliation owned by the architect. **No pin, no dependency, and no `[tool.setuptools.packages.find]` value changed.** |
| 2026-08-02 | **Declared deviation, fix round 1.** The epic's architect-authored source documents (`docs/tracker/directive-90be25f3-9/README.md`, `children.json`, `status/`, and the epic decomposition and questions files under `tasks/`) were committed by this task, in a commit of their own. They were untracked, so a reviewer on the PR could not verify `DEC-X1`'s quotations or `DEC-C`'s factual claims against their sources and this file's citations dangled. They are architect territory (`docs/**`) and this epic's own charter. This deviates from the task spec's §2.1 boundary list, which did not name them; the deviation is declared, not silent. `docs/tracker/main-8/` (another task's artifact), `docs/product/backlog.md` and `docs/tracker/notifications.log` (the Product Owner's, still dirty) were **not** committed and remain untouched. |
| 2026-08-02 | **Fix round 2 — documentation only, after review `VERDICT: CLEAN` (round 2 of 2) and the security review's five remaining low/info findings. No code, no test and no dependency changed; `pyproject.toml` was not touched at all.** §4.1: recorded that **Quotation 0 is an architect-authored English *reduction*, not the owner's literal words** — the Russian original is `docs/product/backlog.md`, section *Журнал решений*, decision-log row **2026-08-02** (`directive-90be25f3-9`), which is the **Product Owner's uncommitted work** and correctly outside this task's boundary, so *questions → owner* is **not** verifiable from this PR; security checked the reduction against the Russian original in-session and found it faithful, but only because this sandbox holds the uncommitted file. §4.3: the escalation bullet is now a **completed fact** — sent at **`2026-08-02T10:04:22Z`**, line 55 of `docs/tracker/notifications.log` — with its content summarised in place. **Appendix A §A.1:** the security-patch hatch is no longer patch-only; it now covers **the minimum version carrying the fix, whatever its level**, because `cryptography` has historically shipped bundled-OpenSSL fixes in a new *minor* and a patch-only hatch failed (closed, but failed) in the exact case it was written for. Published-advisory id, exact `==` pin and architect ownership of the edit are unchanged; a non-patch bump must **name its level** in this change log. Non-advisory bumps stay excluded and a seventh package still escalates. **§A.2:** recorded the known gap that **between M1 and M2 nothing triggers a pin re-check** except a developer happening to notice — accepted, not fixed, because this epic reaches no live host and no published port; **no scanner is to be built**. **`OBL-1`:** verification must happen **before** the bytes reach their final path or are made executable (temp → verify → move → `chmod`), and the **committed** digest is the authoritative one when an upstream checksum file also exists. **`OBL-2`:** a `[tool.setuptools.package-data]` block must be **paired with an explicit `exclude` in `[tool.setuptools.packages.find]`**, so the artifact boundary is enumerated rather than implied by `include = ["control*", "edge*"]` — the `secrets` name ban was one instance of that class, this is the control for the class. Added **`OBL-3`** (§B3): `DEC-X1` is escalated but **unanswered**, and each stage gate (tasks 7 and 17) restates that it is the architect's unconfirmed reading until the owner replies. |
| 2026-08-02 | **Fix round 2 — `children.json`, and why it was edited.** `OBL-1` and `OBL-2` bound at **review** but not at **dispatch**: `docs/tracker/directive-90be25f3-9/children.json` is what tasks 3, 4 and 5 are actually dispatched from, and it cited this file only generically, naming no obligation. `OBL-1` was added to task 4's intent, `OBL-2` to tasks 3 and 5, and `OBL-3` to the two stage gates, tasks 7 and 17. **`children.json` is the queue, not the record** — editing it is not the thing Appendix C refuses to do, and **the epic decomposition file was not edited**. The JSON was re-verified to parse and its 18 entries and their keys are unchanged in shape. |
| 2026-08-02 | **Assumptions taken in fix round 2**, unattended, recorded rather than asked. **(1)** "Each stage gate" in `OBL-3` means the two milestone gates that produce an owner-facing PR — **tasks 7 (M1) and 17 (M2)** — and not every task report. **(2)** `OBL-3` was **not** added to task 18's decision pack: that spec says "cover exactly six items", and adding a seventh would be a scope change rather than a citation. The unanswered `DEC-X1` reaches the owner through the gates and through the escalation already sent. **(3)** §A.1's "minimum version carrying the fix" is deliberately narrower than "latest release": going further than the advisory requires is an ordinary version change and still escalates. **(4)** The Russian original in `docs/product/backlog.md` is **cited, not copied** into this file and **not committed** — copying it here would create a second source that can drift from the Product Owner's, which is the failure §0 forbids for decided text. **(5)** `OBL-1`'s ordering requirement is stated as a property (verified before the file is usable), not as a command sequence — task 4 owns the implementation. |
