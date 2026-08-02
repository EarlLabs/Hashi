# Epic intake — clarifying questions, defaults, and the backlog mapping

**From:** Charles Xavier (architect) · **Task:** `directive-90be25f3-9` · **Date:** 2026-08-02
**Mode:** EPIC DECOMPOSER, phase 1 (questions only — no decomposition in this file)
**Run type:** **unattended.** Nobody is at the keyboard. `scripts/ask_owner.sh` is
deliberately **not** called: it cannot fetch an answer and it would stop the run.
Every question below therefore carries the answer I will proceed on if none arrives.

---

## 0. What the request is

Owner directive, verbatim (Russian), reduced to its four operative clauses:

1. Plan it yourself, cut the tasks, the fleet builds it.
2. Act autonomously; research what is missing; ask only when research has no answer.
3. The output is **a working VPN service**.
4. **After each big stage:** a status report and a PR. **Small PRs are the fleet's
   own business** — review and merge them yourselves; the owner sees finished
   features only.

Clause 4 is the one that changes engineering behaviour, and it is in tension with
`.claude/git-workflow.md` ("This project runs at **L0** — the fleet opens a PR and
stops") and with `.claude/workflow.md` rule 8 ("auto-merge is opt-in per task").
See **X1**.

Nothing in the directive is a scope change to the charter. It is an instruction
about **cadence and autonomy**, plus a "go" on a route that had been waiting for
one (`docs/tracker/ohno-6/tasks/ohno-plan-for-the-owner.md`, first table row:
"Маршрут — Согласен с M1 → M5?").

## 1. What "a working VPN service" means here, and what is out of scope

**In scope for this epic** — the part of the charter that can be finished without
the owner spending a rouble or exposing a host:

- the transport contract expressed in code, and two real transports behind it
  (VLESS+Reality+XTLS-Vision, VLESS+WS+TLS), each validated by **Xray's own**
  `xray run -test -config`, not by our opinion of a correct config;
- packaging that actually ships those transports into the built image (today it
  does not — `pyproject.toml:30`);
- a control plane with a real spine: Postgres, Alembic, operator auth, secrets
  encrypted at rest, key material generated rather than pasted;
- node and friend records, and **one subscription link per friend** that a stock
  client parses into a labelled server list;
- **revocation** that removes a friend from every node × every transport the
  control plane knows about;
- the privacy guards that make the above safe to run: no access logging of
  `/sub/**` anywhere in the stack, images pinned, secrets never in a response,
  a template context or an error string.

**Explicitly out of scope for this decomposition** (and each for a stated reason,
not by omission):

| Out of scope | Why |
|---|---|
| Renting any host; any real provider account | Charter §Autonomy — spending money is always-ask. Unanswered: **Q4** |
| Any traffic actually flowing through a node (criterion 5's second half, all of criterion 1) | Needs a host. Criterion 1 additionally needs a real Russian mobile network and is **owner-accepted forever**, by no test in this repository |
| Publishing any port to the internet | Charter §Autonomy. Unanswered: **Q6** |
| Real Reality decoy destinations | Charter/core invariants §6: never a shared default. Needs the owner's **selection principle** (**Q5**). Fixtures stay `example.com` / `192.0.2.0/24` |
| The admin panel beyond what auth needs | Backlog §6.2 — no panel before M4. Criteria 2 and 3 are worded "from the panel", so the panel arrives with them |
| AmneziaWG on a friend's device | Inexpressible in the v1 subscription format; backlog sketch 25, `blocked`. On the cross-border hop it returns in M4 item 16 |
| Clash / sing-box as a second subscription format | Backlog §6.8 — a second render path for clients nobody has confirmed using |
| Any further work on `deploy/warden/` or `scripts/` | Backlog §6.1 tooling freeze. Two named exceptions only: item 0, and item 1a's checker |
| Payments, signup, advertising, multi-tenancy, quotas, our own client | Charter non-goals. The advertising one carries a legal penalty for the owner |

## 2. Where the ceiling of unattended work sits

**The last thing the fleet can finish with zero money and zero live hosts is
backlog item 10 — i.e. the end of M2.** This is not my invention; it is the
construction Ohno's route was built around and I confirmed it against the tree:

- M1 and M2 are stated as `0 ₽, 0 хостов` in three independent places
  (`backlog.md` roadmap table; `ohno-plan-for-the-owner.md` lines 20–28;
  `research.md` §2 argument 4, §5 opening).
- M3 item 11 onward cannot start without **Q4 (money), Q5 (decoy principle),
  Q6 (port publication)** — three separate owner decisions, all on the charter's
  always-ask list.

One nuance I want on the record, because it is the only place the ceiling could
honestly be argued higher: item 11 `infra-node-stack`'s own acceptance is "the
node stack comes up **locally** and answers a handshake" — zero money, zero live
hosts. I am **not** taking it. See **X2** for why, and for the default.

## 3. Clarifying questions

Six. Each is here because a different answer produces a different task list — not
because it is interesting.

---

### X1 — Merge authority and what counts as a "big stage"

**Question.** Clause 4 of the directive ("small PRs — merge them yourselves;
give me only a finished feature") contradicts `.claude/git-workflow.md`, which
records this project at **L0 — open a PR and stop**, and `.claude/workflow.md`
rule 8 ("auto-merge is opt-in per task; there is no global auto-merge switch").
The charter's §Autonomy also lists "creating a remote repository, pushing, or
publishing anything" as always-ask. Concretely: (a) may the fleet **push task
branches and merge its own PRs into `develop`** once every gate is green? (b) Is
a "big stage" a **milestone** (two owner-facing PRs: M1, then M2), or something
smaller, such as "the transport contract" and "the subscription"?

**Why it changes the decomposition.** It decides the number of deliverables and
the shape of the task list. At L0, each of the 13 backlog items becomes a stop —
an unattended run would halt after item 0 and never reach a "working VPN
service", which is the one thing the directive actually asks for. At
milestone-granularity the epic is 2 owner-facing PRs and ~13 internal ones. It
also decides whether `develop` is a real integration branch or a queue of open
PRs that conflict with each other.

**Default if unanswered.** Read the directive as an explicit, task-scoped raise to
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

---

### X2 — Does the epic stop at the end of M2, or reach into M3 with local stand-ins?

**Question.** M3's first item (`infra-node-stack`) is acceptance-worded "comes up
locally"; items 12–13 (node bootstrap over SSH, node health) could in principle be
exercised against a throwaway container acting as a fake host. Do you want the
fleet to push into M3 using local stand-ins, or to stop cleanly at the end of M2
and hand you the decision list?

**Why it changes the decomposition.** It is the difference between a 13-item epic
and a 17-item one, and between a run that ends with a decision gate and one that
ends with code whose central assumption (a real host, a real SSH target, a real
decoy) has never met reality. It also decides whether Q5 (decoy principle) becomes
blocking inside this epic instead of after it.

**Default if unanswered.** **Stop at the end of M2 — item 10 is the last item
dispatched.** Reasons, in order of weight:
1. Item 12's own acceptance text names the trap: Reality fails on clock skew with
   errors "that look like blocking". A bootstrap validated only against a
   container we control teaches the fleet nothing about the failure it exists to
   survive, and would be re-done at M3 anyway.
2. Items 11–14 are `queued (эскиз)` — sketches, not frozen acceptance criteria.
   Building against a sketch means I would be writing the acceptance text myself,
   which is a **product** decision and not mine to take.
3. Q5 has no safe default. There is no such thing as a conservative shared decoy —
   a shared decoy is precisely what makes the fleet enumerable
   (`00-core-invariants.md:100-103`). "Use `example.com` on a real node" is not a
   cautious choice, it is a broken one.
   M3 is where the epic ends and the owner's decisions begin, and I would rather
   deliver two milestones that are genuinely finished than four that are
   provisionally finished.
4. The epic therefore ends with a **decision gate**, not with code: a short report
   naming exactly what Q4/Q5/Q6/Q7 must say for M3 to start, and confirming that
   everything doable without them is done.

---

### X3 — There is no container runtime in the unattended environment

**Question.** This environment has **no Docker and no Docker socket** (verified:
`docker` not on `PATH`, `/var/run/docker.sock` absent; also no `podman`, no local
`postgres`, no `psql`). Network egress and `root` + `apt-get` **are** available,
so an upstream binary can be fetched and a package can be installed. Ohno's
Q9 already asked you to accept that "all M1–M2 acceptance runs on one developer's
laptop"; unattended, that laptop is an agent container with no container runtime.
Do you accept a milestone whose stack-dependent scenarios are **written and not
executed**, or should the fleet install what it needs (e.g. Postgres via `apt`)
to execute them here?

**Why it changes the decomposition.** It splits the backlog into what can actually
be *proved* here and what can only be *written* here, and that split does not
follow milestone boundaries:

| Runs natively here | Cannot run here (needs a container runtime) |
|---|---|
| item 1 S1, S3, S4, S5, S6 — pure render, golden files, contract shape | item 2 S1/S3 — needs an **image build** |
| item 1 S2 and item 3 S1 — `xray run -test -config`, once item 1a fetches a pinned binary | item 3a S1/S2/S3 — needs a raised stack |
| item 3 S2/S3/S4/S5 — static tree checks and registry behaviour | item 4 S1/S2/S3, item 6 S1/S2, item 8 S1–S5, item 9 — need a **real Postgres** |
| item 10 S1/S2/S3 — static file assertions | item 10 S4 — stack-wide log check |

Left unaddressed, this produces the exact failure the backlog was written to
prevent: `make test-e2e` **exits 0 when zero tests are collected**, so an
unexecuted milestone reports green.

**Default if unanswered.** Three rules, applied without exception:
1. **Never weaken a scenario to make it runnable here** (core invariants §6). A
   stack-dependent scenario stays stack-dependent and **skips loudly**, with the
   reason and the exact command you must run printed in the skip message.
2. **Item 1a delivers a Docker-free preparation path** — a Make target that fetches
   an **exactly pinned** Xray release and puts it where the scenarios find it. This
   is not a workaround; it is what its own S1/S2 already demand ("the documented
   test-environment preparation command", "the version is pinned exactly"), and it
   makes M1 genuinely provable here.
3. **A local Postgres may be installed** (natively, pinned to 16) purely so the
   `control` zone's scenarios execute — but the items whose subject *is* the stack
   (2, 3a, 10 S4) are **not** simulated: they land as code plus scenarios, and the
   Stage-2 report states, verbatim and per scenario, `not executed — no container
   runtime`, with the command. Under Ohno's rule that makes **M2 delivered but not
   accepted** until you or a machine with Docker runs it. I would rather hand you
   that sentence than a green tick.

---

### X4 — Item 0: your `.env` is inside a mount this fleet holds read-write

**Question.** `deploy/warden/docker-compose.yml:49` mounts the repository
read-write into the unattended agent's container, and the real `.env` with live
secrets sits inside that mount. The only rule protecting it is prompt text
("NEVER read or print `.env`") with no deny rule and no filesystem separation
behind it — and this very run is that agent. Item 0 fixes the **configuration**;
the **file move** is one action only you can take. Do you want the fleet to land
the configuration half now (compose reads the env file from outside the mount,
`Makefile:98` gains its missing `--env-file`, tests assert no secret file under
any mounted path), leaving you a single move to perform?

**Why it changes the decomposition.** It decides whether item 0 is in this epic at
all, and whether it ships before or with M1. Ohno holds it `blocked` awaiting your
"yes"; the directive says act autonomously. If the fleet lands the config half,
the epic gains a first task and Stage 1's PR carries a required owner action.

**Default if unanswered.** **Land the configuration half as the first task of
Stage 1**, under these constraints:
- the `infra` developer **does not read, print, copy, move or delete** the real
  `.env` — its scenarios assert on the **mount configuration and the compose
  files**, never on the file's contents;
- the new location is required, not optional: a start without it fails loudly and
  names the action, rather than silently substituting empty strings (item 0 S2);
- because the config half does not reduce the risk by itself, the owner is
  notified through `scripts/notify.sh` **the moment it lands**, not at the end of
  the stage. This is the one item where waiting for the stage report is wrong.
- Also folded in, per Ohno: `Makefile:98` runs the warden compose without
  `--env-file` — harmless only until the first `${VAR}` appears in that file.

---

### X5 — Q10: the rulebooks cannot be corrected, and one correction has itself gone stale

**Question.** Three architect corrections are decided, final and mechanical
(`docs/tracker/ohno-5/tasks/xavier-blocked-edits-ohno-5.md`, sections A/B/C), and
cannot be written: `.claude/**` is write-protected. **I re-verified it in this
session** — a probe write to `.claude/` was refused. The cost is concrete: the
item-1 developer opens `.claude/projects/02-edge-rulebook.md` and reads
`render_client(node, credential) -> dict` (the opposite of the assignment) and an
unconditional ban on the `edge/registry.py` edit the assignment requires. Do you
apply the ready text, lift the protection, or accept two documents disagreeing?

**Why it changes the decomposition.** If the rulebooks stay stale, **every** `edge`
spec in this epic must carry the decided contract text inline and name the rulebook
wrong at a specific line — otherwise a correct developer reads the rulebook, and
correctly escalates, on day one. It also adds a permanent non-zone task.

**Default if unanswered.** Proceed under option (c), and pay the tax explicitly:
- each affected spec carries the decided text **verbatim** and names
  `02-edge-rulebook.md:66` and its *Where a new file goes* section as stale, in
  those two places only;
- the item-1 spec additionally instructs the `edge` developer to bring
  `edge/AGENTS.md:30-32` into line **in the same run** — that file *is* in his
  zone, so it is the one of the four documents that can actually be fixed;
- I re-issue the three corrections as one owner-applicable patch under
  `docs/tracker/directive-90be25f3-9/`, and the epic carries a non-zone stage
  item **"apply architect rulebook corrections"** that only you can execute.

**One correction has expired and I am re-issuing it, not repeating it.** Section C
was written when `origin` carried only `main`. That is no longer true:
`origin/develop` now exists (`77493c9`), and `develop` is **6 commits behind
`main`**, with a stale `origin/task/2-control-plane-…` branch also present. So
`gh pr create --base develop` **does** work today and `git pull origin develop`
**is** executable — which means the directive's "send me a PR" is achievable, and
also that the pre-task sync (`git checkout develop && git merge main`) is not
optional: skip it and the fleet branches from a tree missing six commits. Section
C's replacement text must be rewritten against these facts before it is applied.

---

### X6 — Q7: which clients do your friends actually use?

**Question.** The whole subscription contract rests on one assumption: a base64
list of URIs is read by v2rayNG, Hiddify, Amnezia and streisand. Which clients do
your friends actually have? Ohno flags **Amnezia as the weakest of the four
precisely on subscription URLs** — historically it imports config files rather
than subscribing.

**Why it changes the decomposition.** It is the **only** assumption in the plan
whose refutation is discovered by a friend and not by a test, and it lands inside
this epic's scope (item 8, mid-Stage-2). If the answer is "Amnezia, mostly", the
v1 format's coverage must be recomputed **before** the link leaves for a device —
which would add a second delivery format, i.e. a new item, a new render path and
a `control` change, and would reopen amendment A.

**Default if unanswered.** Build item 8 exactly as frozen (base64 URI list, one
entry per node × enabled transport, country label as a URI fragment), and:
- **do not** add Clash or sing-box (§6.8), and **do not** guess a second format;
- keep the transport's self-declaration "am I v1-expressible" (item 1 S6) as the
  mechanism — so a future second format is a transport-side change, not a
  `control` rewrite;
- the Stage-2 report and its PR body lead with a **required owner action**: paste
  the produced subscription into your real client, before this goes to anyone
  else. That step is manual owner acceptance and is deliberately **not** a pytest
  scenario.

---

## 4. Recommendation: how backlog items 0–25 map onto this epic

**Reuse as-is, in Ohno's order, without renumbering. Regroup only for delivery.
Replace nothing.**

The backlog is not a draft to be improved — it is a decomposition I already
reviewed (verdict `approved-with-changes`, four blockers), whose corrections were
applied in revision 3, and whose acceptance text is **frozen** in
`docs/research/product-owner-ohno-4/research.md` §3. Rewriting it would be me
taking `what` decisions. It is Ohno's file; I do not touch it.

### 4.1 What the epic takes

| Epic stage | Backlog items, in dispatch order | Owner-facing deliverable |
|---|---|---|
| **Stage 0** — architect, no zone, no PR | rulebook corrections (X5); branch sync `develop ← main`; recording the autonomy raise (X1) | notification only |
| **Stage 1 — M1** "a config Xray itself accepts, and a second protocol is one directory" | **0 → 1 → 1a → 2 → 3** | one PR + status report. Criterion **4** closed |
| **Stage 2 — M2** "one link to a friend, and taking it back" | **3a → 4 → 5 → 6 → 6a → 7 → 8 → 9 → 10** | one PR + status report. Criterion **6** half; **5** advanced |
| **Stage 3** — decision gate, no code | — | report naming what Q4/Q5/Q6/Q7 must say for M3 to start |

Item 10 has no dependencies and may be pulled forward inside Stage 2 if the queue
stalls.

### 4.2 Why this order and not another

- **The dependency graph already encodes the traps.** `3a` before `4` is the only
  cross-zone dependency in M2 and exists because `deploy/docker-compose.yml:39-41`
  gives control no DB variable at all — without it, a `control` developer would be
  judged on something he is not allowed to fix. `6 → 6a → 7` exists because key
  generation was assigned to nobody while three items assumed it. `1` before `7`
  and `8` exists because **an empty registry is a passing test today**
  (`tests/edge/test_scaffold.py`) — reorder that and both items go green
  vacuously. Any regrouping I invented would have to rediscover all three.
- **One item = one zone = one `/develop` run** is what keeps three developers out
  of each other's files. Every merge I could propose (e.g. folding `1a` into `1`,
  or `3a` into `4`) creates a two-zone task, which this fleet has no mechanism to
  execute.
- **Ordering the queue as `1 → 1a → 2 → 3` deliberately differs from `depends_on`**
  and that is correct: `1a` depends on nothing, but is useless before `1` and too
  late after `2`.

### 4.3 What the epic does **not** take, and why

- **Items 11–15 (M3)** — first money, first host. Blocked on Q4/Q5/Q6. See **X2**.
- **Items 16–20 (M4)** — second host, in Russia; item 20 is your field test and
  **no test in this repository may ever claim criterion 1**.
- **Items 21–25 (M5)** — panel, backups, rotation; item 25 is `blocked` on a
  second subscription format.

These stay `queued (эскиз)` in Ohno's file, untouched. Sketch text is not
acceptance text, and I will not promote it to acceptance text on my own authority.

### 4.4 The one thing I am adding, and it is not a backlog item

Stage 0 is **architect and owner work on documents** — the rulebook corrections,
the branch sync, the recorded autonomy level. It is not a `/develop` item, has no
zone and no acceptance scenarios, and must not appear in `docs/product/backlog.md`.
Ohno's tooling freeze (§6.1) is untouched by it: no tests for `warden`, no `/e2e`
command, nothing new reading `.e2e/profile.yml`.

## 5. Execution corner cases that could break this epic

Named so nobody rediscovers them at 3am.

1. **No container runtime here** — see **X3**. The largest single risk to honest
   acceptance in this run.
2. **`make test-e2e` exits 0 on zero collected tests.** A milestone whose scenarios
   were never written reports green. Every stage report must state the number of
   scenarios **collected** and **executed**, per zone, or the report is worthless.
3. **The empty transport registry is a passing test.** Items 7 and 8 would go green
   vacuously if M1 slipped. Hence `1` before `7`/`8`, non-negotiable.
4. **`pyproject.toml:30`** lists packages explicitly, so `edge.transports.*` never
   reaches the container — criterion 4 broken in the build system, reproduced
   empirically. Fixed by me inside item 1 (it is architect territory); item 2 then
   proves it and proves it **can fail**.
5. **`deploy/docker-compose.yml:39-41`** passes control no DB URL; `.env.example`
   declares no client URL; `alembic upgrade head` is invoked nowhere. All `infra`.
   Item 3a, before item 4.
6. **`control/app/settings.py:27`** defaults `public_host` to `"localhost"` — the
   failure a friend finds, not a test. Item 8 S5 makes it fatal at startup.
7. **`deploy/docker/control.Dockerfile:7`** floats on `python:3.14-slim`, and
   `tests/infra/test_compose.py:49` misses it because it exempts built services.
   Item 10. After item 10, write "`control.Dockerfile` is pinned" — **not** "images
   are pinned": `deploy/warden/Dockerfile:20` stays unpinned deliberately.
8. **Stale rulebooks** — see **X5**. A correct developer escalates on day one.
9. **`develop` is 6 commits behind `main`** and a stale `origin/task/...` branch
   exists. Sync before the first task or every branch starts from the wrong tree.
10. **Adding a dependency is mine, not a developer's.** This epic needs several
    (`sqlalchemy`, `asyncpg`, `alembic`, a session mechanism, a crypto library for
    at-rest encryption — `pyproject.toml:10-15` has none). Each is named in the
    spec that needs it, before dispatch, or the developer is blocked by design.

## 6. Security and privacy risks this epic carries

- **Subscription tokens are bearer credentials in a URL path.** Every place a path
  can be recorded is a leak: uvicorn's access log, Caddy's access log, an exception
  handler echoing the path, a traceback, shell history in bootstrap code. Item 10
  makes this test-held instead of doctrine-held; item 8 S3 covers the application
  half. **Both halves are needed and they live in different zones on purpose.**
- **Unknown and revoked tokens both return 404.** A 403 confirms a token existed.
- **Secrets at rest.** `HASHI_SECRET_KEY` is mandatory today and used by nothing.
  Item 6 makes it load-bearing: no key, no start — never a degraded mode that
  writes plaintext. Item 6 S4 keeps the secret out of responses, template contexts
  and error strings.
- **The `.env` inside the agent's own read-write mount** — X4. Live right now.
- **No shared Reality decoy, ever.** Item 1 S4 makes an unset decoy a validation
  error, so no project-wide default can exist to be borrowed.
- **No connection, traffic or DNS logs**, at any level including debug. Nothing in
  this epic collects any; anything that appears to is a finding by definition.
- **Node names and friend nicknames are untrusted input** — they reach rendered
  configs and, later, SSH command lines. Jinja autoescape stays on; no `|safe`.
- Holmes reviews the design of both stages before dispatch, per Phase 2.

## 7. What "done" looks like for this epic

Given the owner sees only finished features, the epic is done when **all** hold:

1. **Stage 1 PR** exists on `develop` and: a rendered VLESS+Reality server config
   is accepted by `xray run -test -config` for real at least once (M1 is **not**
   closed on a skipped checker — the report then says "S2 skipped, the validation
   half of criterion 4 is not proven", never "green"); a second transport was added
   as **one directory**, with no edit to `edge/registry.py`, to the other
   transport, to `control/**` or to `pyproject.toml`; and `discover()` finds both
   **inside a built image**, not only in an editable install.
2. **Stage 2 PR** exists on `develop` and: an operator authenticates, creates a
   node and a friend, enables a transport without typing a key, and gets one link;
   `GET /sub/{token}` returns a base64 URI list with one labelled entry per
   node × enabled transport; revoking a friend makes that link 404 and removes the
   credential from **all** node × transport renders, not just the last; and no
   token appears in any log of any service in the stack.
3. Every acceptance criterion in scope traces to a scenario, with a **red-first**
   proof recorded — break it, watch the right assertion fail, restore it.
4. Every stage report states **how and where** the scenarios were run, and lists
   every scenario **not executed** with the reason and the command (X3).
5. No zone was edited by two owners; each zone's verify command passes.
6. The epic ends at a **decision gate**, and the final report says plainly:
   criterion 4 closed; criterion 6 half-closed (DB and render, no push to a live
   node); criterion 5 advanced to "a stock client parses the link" and **not**
   closed; criteria 2, 3 and 1 untouched — **and criterion 1 is not closable by any
   test in this repository, now or later.**

## 8. Assumptions in force while answers are missing

Carried from `research.md` §5 unchanged, plus three of mine:

| # | Assumption | Source |
|---|---|---|
| 1 | Q1 = yes — the owner has working circumvention access today. **This is the one assumption whose failure flips the whole route** toward "two hosts as fast as possible" | Ohno §5 |
| 2 | Subscription format = base64 URI list (amendment A) | Ohno, decided |
| 3 | Fixtures use `example.com` / `192.0.2.0/24` until M3 (Q5) | Ohno §5 |
| 4 | Q9 option (a): M1–M2 acceptance is local, and each report says how it ran | Ohno §5 |
| 5 | "e.g. AmneziaWG" in criterion 3 is an example; the criterion closes on VLESS+WS+TLS (amendment E) | Ohno §1.E, owner pending |
| 6 | The repository stays as it is (public/private) until M4 (Q3) | Ohno §5 |
| 7 | **New:** the directive is the owner's "yes" to the M1 → M2 route. Anything changing the **route** still goes to the owner; changing the **slicing** does not | mine, X1 |
| 8 | **New:** the directive raises autonomy to L2 for `develop` only; `main` stays human | mine, X1 |
| 9 | **New:** the epic stops at item 10 and ends in a decision gate | mine, X2 |

Every one of these costs at most a rework inside one milestone if wrong — except
assumption 1, which costs the route. It is stated outright rather than buried.

---

*Charles Xavier — architect. This file is questions and mapping only. Nothing here
is a spec, nothing here is dispatched, and no acceptance criterion in
`docs/product/backlog.md` or `research.md` §3 has been reworded, weakened or
dropped.*
