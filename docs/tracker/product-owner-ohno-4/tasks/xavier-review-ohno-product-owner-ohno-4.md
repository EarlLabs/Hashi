# Architect review of the product plan — `product-owner-ohno-4`

**Reviewer:** Charles Xavier (architect)
**Reviewing:** `docs/research/product-owner-ohno-4/research.md` §§0–7, `docs/product/backlog.md`
**Against:** `docs/product/charter.md`, `CLAUDE.md`, `.claude/workflow.md`, `.claude/projects/*.md`
**Commit:** `1cfd7d7`
**Date:** 2026-08-01

---

## Verdict

**`approved-with-changes`**

The route is sound and technically reachable. Every factual claim ohno makes about
the tree is correct — I re-verified all five named in my brief, including
reproducing the packaging defect myself. Two of his claims are *understated*, none
overstated. The bottom-up ordering (renderer before storage) is the right technical
call and I would have made it myself for the reason he gives: the node-record shape
is determined by its consumer.

What stops this being `approved` is not the priorities — those are his — but four
findings that block specific items as written, plus a contradiction between
charter amendment A and M1's own choice of second transport that only he can
resolve.

None of it requires reordering milestones. Item 1 can be dispatched as soon as I
have written B1 and B3 into its spec.

---

## Scope of this review

I own **how**, not **what**. I do not comment on whether M1 before M3 is the right
product call, on the value of any item, or on ohno's priorities. I comment on
whether the plan is *executable*: single-zone items, verifiable scenarios,
reachable sequencing, and contracts a developer can start against on day one.

---

## 1. Factual accuracy — all five claims verified

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | `pyproject.toml:30` packaging defect breaks criterion 4 | **CONFIRMED** | reproduced independently, below |
| 2 | Transport contract exists only as prose | **CONFIRMED, understated** | `02-edge-rulebook.md:61-66`; `edge/registry.py:20-39` |
| 3 | Node-record type undefined | **CONFIRMED** | no definition anywhere in the tree |
| 4 | `origin` exists despite `workflow.md` | **CONFIRMED, understated** | `workflow.md:36` vs. `git remote -v` |
| 5 | warden mounts the repo read-write with real `.env` inside | **CONFIRMED** | `deploy/warden/docker-compose.yml:49`; `.env` present at repo root |

**Claim 1 — reproduced.** I copied the tree, added
`edge/transports/demo/{__init__.py,meta.py}`, and ran
`pip install --target /tmp/pkgout --no-deps .`. Exit 0. The installed tree
contains `edge/`, `edge/transports/` and **no `demo/`**.
`deploy/docker/control.Dockerfile:15` runs `pip install .`, so
`registry.discover()` returns `{}` inside the container while an editable install
on a laptop finds the transport. ohno's characterisation — criterion 4 broken in
the build system, silently — is exact and not overstated.

**Claim 2 — understated.** He says `Params` / `render_server` / `render_client`
exist only as prose. True. He does not notice that `TransportMeta` in
`edge/registry.py:20-26` (`name`, `family`, `needs_tls`) is *missing a field the
same contract table requires*: `02-edge-rulebook.md:63` specifies "unique `name`,
protocol family, whether it needs TLS, **default port range**". See B3 — this
turns into a day-one collision with his own §6.4.

**Claim 4 — understated.** `workflow.md:36` says in bold "This repository has no
`origin` yet." It does. Two further drifts in the same rule set that ohno does not
name: rule 4 instructs `git pull origin develop`, but `origin` carries **only
`main`** (`remotes/origin/main`; no `origin/develop`), so the literal instruction
fails; and rule 1 says agents never push `main`, while `main` is precisely the
branch that is pushed. He is right that this is my document to fix and right that
it must happen before an agent follows it.

**Claim 5 — confirmed, with one addition.** `deploy/warden/docker-compose.yml:49`
mounts `../..:/repo` read-write; `.env` exists at the repo root (925 bytes,
untracked, in `.gitignore` and `.dockerignore`). The `CLAUDE.md` prohibition is
prompt-level with no enforcement behind it. His recommendation (a) — move `.env`
outside the mount — is the correct one for the reason he gives: it is the only
option that does not depend on what a model decides to do. It is small `infra`
work. Addition: `Makefile:98` runs the warden compose **without** `--env-file`,
which is safe today only because that file uses no `${VAR}` interpolation; anyone
adding one there gets the silent-empty-string trap the rest of the repo guards
against.

**Nothing ohno claims is wrong.** §1's numbers, the "0 of 6 criteria" assessment,
the `make test-e2e` exit-0 characterisation (`Makefile:67-68`), the
`test_images_are_pinned` exemption (`tests/infra/test_compose.py:49`), the
`--no-access-log` and `output discard` observations — all check out against the
files.

---

## 2. BLOCKING findings

These prevent the item they name from being dispatched as written.

### B1 — `render_client`'s return shape contradicts amendment A. *Blocks item 1.*

`02-edge-rulebook.md:66` specifies `render_client(node, credential) -> dict`,
"a fragment the subscription renderer can serialise **without knowing the
protocol**". Amendment A fixes the wire format as a base64 list of `vless://`
URIs. A VLESS+Reality URI is protocol-specific in every part of it: the scheme is
the protocol name, and the query carries `security=reality`, `pbk`, `sid`, `fp`,
`sni`, `flow`.

So exactly one of these is true, and the plan does not say which:

- `control` assembles the URI from a dict of parts → `control` knows the protocol
  → violates core invariants §1 ("no `if transport ==` outside a transport's own
  package") and breaks criterion 4, whose text names the subscription renderer as
  a thing that must not be modified;
- `edge` assembles it → `render_client` returns the finished URI, and the
  rulebook's "dict" is wrong.

Item 1's own S5 ("returns a fragment that serialises without knowledge of the
protocol name") cannot be satisfied by the first design and is trivially satisfied
by the second. This is my decision, not ohno's; it is recorded in §7 below. But it
must be in item 1's spec before dispatch, because it determines the signature the
developer writes on day one and it is not recoverable later without touching every
transport.

### B2 — AmneziaWG cannot be carried in a base64 v2ray URI list. *Blocks item 3; product decision required.*

Three of ohno's decisions are mutually inconsistent:

- item 3 makes **AmneziaWG** the second transport (`research.md:367-400`);
- item 8 S1 requires one subscription entry **per node × enabled transport**
  (`research.md:543-548`);
- amendment A fixes the v1 format as a **base64 list of URIs**
  (`research.md:90-93`).

There is no URI scheme in the v2ray subscription family that expresses AmneziaWG.
Its obfuscation parameters (`Jc`, `Jmin`, `Jmax`, `S1`, `S2`, `H1`–`H4`) have no
URI representation, AmneziaWG is distributed as a WireGuard-shaped `.conf` or as
Amnezia's own `vpn://` blob, and v2rayNG — the client whose coverage is the stated
reason for choosing this format — does not consume WireGuard-family entries at
all. An AmneziaWG-enabled node is therefore **unrepresentable in the v1
subscription**.

Consequences: item 8 S1 becomes unsatisfiable once item 3 has landed, and
criterion 3 ("enable AmneziaWG from the panel → present in every subscriber's
config at their next refresh") becomes unreachable under amendment A.

This is a **what** decision, so it is ohno's. Technically the options are:

- **(a)** choose a different second transport. The charter already names
  **VLESS + WS + TLS behind a camouflage site** as a fallback
  (`charter.md:85`). It is a different *transport* with a different template,
  different params and a different camouflage story, it is expressible as a
  `vless://` URI, and it exercises the contract from a second direction. It does
  **not** prove the contract survives a non-URI-expressible family — but nothing
  in M1–M2 needs that proof, and item 3's stated purpose ("added as one directory,
  no surgery") is fully served. **This is my recommendation.**
- **(b)** keep AmneziaWG and accept a second delivery artefact for it. Directly
  contradicts core invariants §1 ("the subscription is the only contract with a
  user") — the same principle ohno invokes to justify amendment B.
- **(c)** adopt sing-box or Clash in v1, which do express AmneziaWG. ohno rejects
  this on client-coverage grounds (§6.8) and I agree with the rejection.

Note this does not weaken his argument for a second transport in M1. It changes
which one. If AmneziaWG stays, it belongs in M3/M4 alongside the entry→leaf hop,
where it is consumed by node configuration rather than by a friend's client.

### B3 — `TransportMeta` must change, and §6.4 forbids the change. *Blocks item 1.*

`02-edge-rulebook.md:63` requires `META` to carry a default port range.
`edge/registry.py:20-26` does not have it. Item 1's developer must therefore edit
`edge/registry.py`, which:

- ohno's §6.4 forbids outright ("do not touch `edge/registry.py`");
- item 3 S2 asserts must not appear in a transport's diff;
- `edge/AGENTS.md:30-32` and `02-edge-rulebook.md:37-39` both treat as evidence
  that "the profile contract is too narrow".

None of those framings applies here: this is the contract being *completed for the
first time*, not widened to accommodate a special case. But a developer reading
those three documents on day one will stop and escalate, correctly. The resolution
has to be in item 1's spec as an explicit architect instruction, together with the
freeze point after which §6.4 applies. Recorded in §7.

### B4 — Item 4 is not single-zone and its S1 cannot pass. *Blocks item 4.*

`control-persistence-spine` is declared zone `control` (`backlog.md:85`). Its S1
requires the e2e stack to come up with migrations applied and the app answering
`/healthz`. Today:

- `deploy/docker-compose.yml:39-41` passes `control` only `HASHI_SECRET_KEY` and
  `HASHI_PUBLIC_HOST` — **no database connection variable at all**;
- `.env.example` declares `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB`
  for the `db` service only, and no URL for the client;
- nothing anywhere invokes `alembic upgrade head`.

All three fixes live in `infra` (`deploy/**`, `.env.example` — see the zone table
in `CLAUDE.md`). ohno names only the `pyproject.toml` dependency addition and
`control/app/settings.py` (`research.md:431-434`). His own roadmap row for M2 says
zones `control`, **`infra`** (`backlog.md:45`), but the M2 backlog table contains
no infra item that supplies them — item 10 is image pinning and log guards, which
is unrelated and declared independent of everything.

**A separate `infra` item is missing from M2**: pass the connection setting to the
`control` service, add it to `.env.example`, and decide where `alembic upgrade
head` runs. It must be ordered before item 4, or item 4 must be split into a
`control` half and an `infra` half. As written, item 4's S1 fails for reasons the
`control` developer is not allowed to fix.

---

## 3. Fix before the item they affect

### F1 — Scenarios that assert on a git diff are not testable. *Items 2, 3, 7.*

- item 2 S2: "no file outside its directory changed"
- item 3 S2: "the diff of this task contains no change to `edge/registry.py`, to
  another transport, to `control/**`, or to `pyproject.toml`"
- item 7 S4: "no comparison against a specific transport, provider or country name
  appears in the diff"

A pytest scenario in `tests/e2e/<zone>/` has no baseline commit and no notion of
"this task". These are code-review gates, not e2e scenarios. This matters most for
item 3 S2, which `research.md:398` and `backlog.md:75` both designate as **the**
e2e proof of criterion 4 — as written, criterion 4 has no executable proof, which
is the same failure mode ohno rightly refuses to accept for criterion 1.

Two of the three convert to static tests over the *tree* rather than the diff, and
those are genuinely valuable:

- no identifier in `control/**` equals any name returned by `discover()` (item 7
  S4, and the durable half of item 3 S2);
- a transport package imports nothing under `edge/` except the registry's public
  types, and nothing under `control/` at all — a strengthened sibling of the
  existing `test_edge_never_imports_control`, whose matching is weak
  (`tests/edge/test_scaffold.py:25`, noted by Curie §3.4).

The genuinely diff-shaped remainder belongs in Granger's review checklist and in
my Phase 7 check, stated as such, not disguised as an acceptance scenario.

### F2 — Item 8 S3 and item 10 S4 are the same assertion in two zones.

Both assert that a string used in a `/sub/` path is absent from Caddy's log output
(`research.md:554-558` and `research.md:618-619`). Item 8 is `control`; Caddy's
configuration and its e2e scenarios are `infra` (`deploy/caddy/**`,
`tests/e2e/infra/**`). Two developers will write the same scenario and one of them
will be in the wrong directory — the exact collision the per-zone e2e split exists
to prevent.

Split: item 8 S3 asserts on the **control container's** output and on the response
body only; item 10 S4 keeps the Caddy half and the full-stack sweep.

### F3 — Item 6 S3 is not achievable as stated.

"Given `HASHI_SECRET_KEY` is absent, when the stack is brought up, then the
container does not reach healthy." `deploy/docker-compose.yml:40` writes
`${HASHI_SECRET_KEY:?set HASHI_SECRET_KEY in .env}`, so `docker compose` aborts
**before creating any container**. There is no unhealthy container to observe.

Restate as either: the application process exits non-zero at boot when the setting
is absent (already covered at unit level by `tests/control/test_scaffold.py`), or
`docker compose up` fails with a message naming the variable — and if the latter,
it is an `infra` scenario, not a `control` one.

### F4 — Missing dependency decisions for items 5 and 6.

ohno correctly routes the item-4 dependency addition to me
(`research.md:431-434`). He does not do the same for:

- **item 6** — encryption at rest needs a crypto library. Nothing in
  `pyproject.toml:10-15` provides one. Not mentioned anywhere in the plan.
- **item 5** — operator auth needs a session mechanism (Starlette's
  `SessionMiddleware` pulls `itsdangerous`) *and* a decision on **where operator
  credentials come from**: an env var, a seeded row, a bootstrap command. Nothing
  in the plan says. If it is an env var it also touches `.env.example` and
  `deploy/docker-compose.yml` — `infra` again, same shape as B4.

Both are day-one blockers for their items, and both are mine to decide, not the
developer's. See §7.

### F5 — Key generation is unassigned across the entire plan.

`02-edge-rulebook.md:45` and `edge/AGENTS.md:27` forbid renderers to generate key
material; keys are passed in. Curie flagged the gap (§4.5) and it is not closed
anywhere in the backlog. No item mints the Reality x25519 keypair, the short ID,
or a friend's credential. Item 7 creates node and friend records; item 8 renders a
subscription from them; nothing in between produces the secrets both depend on.

This belongs in `control/app/services/`, needs a dependency decision behind it,
and must be settled before item 7. Right now items 7, 8 and 9 all quietly assume
it exists.

### F6 — Item 1 S2 needs the xray binary, and placing it is `infra` work with no item.

ohno names it as an architect decision (`research.md:338`) but does not slice the
work. The binary reaches an automated run through `.github/workflows/ci.yml` or a
Make target — both `infra`, both closed to the `edge` developer. As the plan
stands, item 1 S2 will loud-skip in every automated run. The rulebook explicitly
permits that (`02-edge-rulebook.md:76-79`), and a loud skip is honest. But it means
item 1's headline claim — "the config is proven against reality, not against
prose", the reason it is first — is only ever demonstrated on a machine where
someone installed the binary by hand.

Either add the `infra` item, or state in the item's acceptance report that S2 was
skipped and criterion 4's validation half is unproven. Not both silently.

### F7 — No e2e scenario in this backlog runs in CI.

`.github/workflows/ci.yml:27-28` runs `make test-<zone>` only; there is no e2e job.
`make test-e2e` (`Makefile:63-68`) refuses to run without a stack on 8100. Every
acceptance criterion ohno defines is therefore a local, manual invocation whose
result nobody else can reproduce — and `make test-e2e` exits 0 with "no e2e
scenarios yet" when it collects nothing.

ohno's §6.1 freeze on fleet tooling forbids fixing this before M3. That is a
defensible product call and I do not contest it. But it is a property of *every
acceptance in M1 and M2* and it should be written down once, up front, rather than
discovered at item 8. The same document that refuses to let a green run stand in
for criterion 1 should say plainly that a green e2e run in M1–M2 is one
developer's laptop.

Related and minor: `make test-e2e` runs `pytest tests/e2e` across all three zones
and gates on the *control* stack being up, while items 1 and 3 are pure rendering
that needs no stack at all. Workable — `.e2e/profile.yml:31` gives a per-file
invocation — but it will confuse the first `edge` developer who runs it.

### F8 — M2's backlog dependencies omit every dependency on M1.

`backlog.md:85-91` records items 4–9 as depending only on each other. But:

- **item 7 S2** enables "a transport with a name returned by `discover()`" — needs
  item 1's transport package to exist;
- **item 8 S1** renders one entry per node × transport — needs item 1's
  `render_client`.

If M1 slipped and M2 were dispatched, items 7 and 8 would be built against an
empty registry and would pass vacuously — `discover()` returning `{}` is currently
a *passing* test (`tests/edge/test_scaffold.py`). Items 7 and 8 need
`depends_on: 1` recorded alongside their intra-M2 dependencies.

---

## 4. Zone discipline — item by item

Checked against the zone table in `CLAUDE.md` / `workflow.md:13-23`.

| # | id | Declared | Verdict |
|---|---|---|---|
| 1 | `edge-transport-contract-vless-reality` | `edge` | **leaks** — `pyproject.toml` (architect, ohno declares it) + xray binary in CI (`infra`, F6) |
| 2 | `infra-image-ships-transports` | `infra` | clean; S2 is a diff assertion (F1) |
| 3 | `edge-transport-amneziawg` | `edge` | clean on paths; blocked by B2; S2 is a diff assertion (F1) |
| 4 | `control-persistence-spine` | `control` | **leaks** — `deploy/docker-compose.yml`, `.env.example`, migration invocation (**B4**) |
| 5 | `control-operator-auth` | `control` | **likely leaks** — credential source may need `.env.example` + compose (F4) |
| 6 | `control-encrypted-secrets` | `control` | **leaks** — S3 is a compose-level assertion (F3); missing dependency (F4) |
| 7 | `control-node-and-friend-records` | `control` | clean on paths; S4 is a diff assertion (F1); depends on M1 (F8) |
| 8 | `control-subscription-delivery` | `control` | **leaks** — S3 asserts on Caddy logs (F2); depends on M1 (F8) |
| 9 | `control-revocation-fanout` | `control` | clean |
| 10 | `infra-pin-images-and-log-guards` | `infra` | clean |

Four items leak, one probably. Three of the leaks are the same leak wearing
different clothes: **M2 needs an `infra` item that does not exist.** Adding one
before item 4 — connection variable in compose and `.env.example`, migration
invocation, and the compose-level assertions currently stranded in items 6 and 8 —
resolves B4, F2 and F3 together and leaves items 4–9 genuinely single-zone.

`pyproject.toml` appears in items 1, 4, 5 and 6. ohno flags it for 1 and 4 and
misses it for 5 and 6. It is mine in all four cases and none of them is a zone
violation, but a developer who hits an undeclared one on day one will stop and
escalate, which costs a round trip.

---

## 5. Item sizing and sequencing

**Sizing.** Items 2, 3, 5, 6, 9 and 10 are correctly sized for one `/develop` run.

Three are large but defensible:

- **item 1** is the biggest thing in M1 — a contract expressed in code, a node
  record type, a Reality template, golden files, five scenarios, plus my
  `pyproject.toml` and `TransportMeta` decisions landing inside it. It is at the
  ceiling of one run. I am not asking for it to be split: splitting the contract
  from its first implementation would produce exactly the untested prose contract
  ohno is trying to eliminate. It needs a tight spec, not a smaller one.
- **item 4** carries engine, per-request session, Alembic initialisation *and*
  first migration. Defensible as one spine; watch it.
- **item 7** carries node records, friend records and per-node transport
  enablement — three model families and their operator surfaces. This is the one I
  would most likely have to split at spec time if item 4's shape comes out heavier
  than expected. Flagging, not requiring.

**Independent verifiability.** Every item is verifiable without a *later* item,
which is the property that matters. Items 7 and 8 need an *earlier* item across
the milestone boundary, which is fine once F8 records it.

**Sequencing — does item 1 unblock item 2?** Yes. Item 2 asserts a transport
appears in `discover()` inside the built image; item 1 produces the transport and
(via my `pyproject.toml` fix) the packaging that carries it. Correctly ordered.

One dependency hidden inside that: item 3 S2 asserts the diff touches no
`pyproject.toml`. That only holds if my item-1 fix switches to **auto-discovery**
rather than extending the explicit list. If I extended the list, every future
transport would edit `pyproject.toml` and criterion 4 would stay broken in a new
way. Recorded in §7 so the choice is not left to whoever gets there first.

**M2 internal order** (4 → 5, 6 → 7 → 8 → 9) is technically sound. Auth and
encryption both genuinely need the spine; records need both; delivery needs
records; revocation needs delivery. No inversions.

**M3 sketches** are consistent with the topology: `edge-node-health` explicitly
preserving control→node one-way flow, time sync before Xray, `degraded` on partial
bootstrap. All three are the rulebook's named traps and all three are in the right
milestone.

---

## 6. Given/When/Then scenarios as `tests/e2e/<zone>/` tests

**The important thing first: ohno has not smuggled criterion 1 into an automated
scenario anywhere.** I checked every scenario in §3. Criterion 1 appears only as
item 20 `owner-field-test-whitelist`, labelled owner acceptance in both documents,
plus an explicit §6.6 prohibition on ever writing a test that claims it. That is
correct and it is the single most important line in the plan.

Owner-executed steps are labelled in three places: item 8 S5, item 15
`owner-first-connection`, item 20. Good.

Beyond the blocking and fix-before items already given, these need restating:

- **Item 8 S5** is correctly labelled "owner acceptance, manual" but is listed
  under the heading "Scenarios (`tests/e2e/control/`)". A manual step should not
  sit in a pytest directory's list. Items 15 and 20 are placed correctly; S5
  should follow their pattern.
- **Item 8 S4** — "two consecutively issued tokens are not predictably related" is
  not falsifiable in a test and will become a vacuous assertion, which
  `workflow.md:113` names as worse than no test. Testable substitutes: the token
  is produced by `secrets.token_urlsafe` with ≥32 bytes of entropy (assert length
  and alphabet), and N issued tokens are pairwise distinct.
- **Item 1 S3** — "the call did not touch the network, the disk, the clock or a
  randomness source" is testable, but only by monkeypatching those surfaces, and
  the disk half is awkward: Jinja template loading *is* disk I/O unless templates
  are packaged and loaded once at import. Worth deciding in the spec rather than
  leaving the developer to discover it. Note core invariants §1 lists "no
  filesystem" while `02-edge-rulebook.md:44` lists it too — so the templates must
  be loaded outside the render call, not during it.
- **Item 3 S3** — "traversal order does not affect the result": `discover()`
  returns a dict keyed by name, so this is inherently true and the test cannot
  fail. Either drop it or make it meaningful (e.g. the mapping is equal across
  repeated calls with `pkgutil` order perturbed).
- **Item 3 S4** — duplicate names raise. Already covered by
  `edge/registry.py:36-37` and passing today. It is a regression guard, not an
  acceptance criterion; fine to keep, worth labelling so it is not counted as
  new evidence.

Everything else is testable as written against this stack, given a booted e2e
stack and, for item 1 S2 / item 3 S1, the upstream checker.

One correction on the checker: item 3 S1 says AmneziaWG's config "is accepted by
the standard checker (loud skip when the binary is absent — as in item 1 S2)".
It is not the same binary. `02-edge-rulebook.md:51` names `wg-quick strip`, but
upstream `wireguard-tools` rejects AmneziaWG's obfuscation keys as unknown; the
checker is `awg-quick` from `amneziawg-tools`. That is a *second* tool dependency
in the test environment, with the same `infra` problem as F6. Moot if B2 resolves
toward option (a).

---

## 7. Architect decisions I am taking now

These are mine under core invariants §5 and the zone table. Recording them here so
item 1's spec is not the first place anyone sees them, and so a developer does not
have to guess or escalate on day one.

1. **`pyproject.toml:30` → auto-discovery.** Replaced with
   `[tool.setuptools.packages.find]` scoped to `control*` and `edge*`, not an
   extended explicit list. Reason: an extended list re-breaks criterion 4 on the
   next transport, and item 3 S2 depends on this choice. Lands inside item 1, as
   ohno proposes — I agree that a one-line change is a handoff, not a `/develop`
   run, and item 2 turns it into a permanent guard.
2. **`render_client` returns the complete client entry, not a dict of parts**
   (B1). The transport owns its own URI serialisation; `control` concatenates,
   labels and base64-encodes, and never learns a protocol name. The return carries
   the serialised entry plus protocol-agnostic metadata (display label, exit
   country label, node id). `02-edge-rulebook.md:66` gets corrected to match —
   my document, my correction.
3. **`TransportMeta` gains the default port range** (B3), completing
   `02-edge-rulebook.md:63`. This one edit to `edge/registry.py` is authorised
   inside item 1 and only inside item 1. From item 3 onward, ohno's §6.4 applies
   unchanged and a transport that needs a registry edit is a contract failure.
4. **The node record lives in `edge`**, is the input to both renderers, imports
   nothing from `control`, and `control`'s SQLAlchemy models are mapped onto it
   rather than being it. This is the point of ohno's argument 2 and I am adopting
   it; it is what makes item 4's schema a consequence of item 1 rather than a
   guess.
5. **Country label comes from the node's location label**
   (`charter.md:114`), never from a geo lookup on the node's address. Otherwise
   amendment B acquires a geo dependency and a network call in a render path.
6. **Dependencies I will add when their item is specced**, so nobody adds them
   under pressure: persistence (item 4) as ohno states; a cryptography library
   (item 6); a session mechanism (item 5). Each lands with its item, none earlier.
   Runtime dependencies are currently unconstrained (`pyproject.toml:10-15`)
   against `03-security-checklist.md:46` — I will constrain them at the same time
   rather than as a separate item, consistent with ohno's dislike of ceremony.
7. **`.claude/workflow.md:36` and rule 4 corrected** for the `origin` drift, plus
   the two further drifts in N2 below. My document; ohno correctly declines to
   touch it. This happens before the next dispatch, not as a backlog item.

---

## 8. Nits

- **N1.** Item 2's "red-first is obligatory: S1 must fail on the current
  `pyproject.toml`" reads as a sequencing constraint, but ohno also places the
  `pyproject.toml` fix inside item 1 (`research.md:339`, `:680`). By the time item
  2 is dispatched the fix is already in. It remains a valid red-first
  *demonstration* — revert, watch the right assertion fail, restore, per
  `01-control-rulebook.md:97` — but the wording should say so, or items 1 and 2
  will argue about it at acceptance.
- **N2.** `workflow.md` drift is broader than reported: `origin` has only `main`,
  so rule 4's `git pull origin develop` fails literally; and rule 1 forbids
  pushing `main`, which is the pushed branch. Mine to fix (§7.7).
- **N3.** `control/app/settings.py:27` — `public_host: str = "localhost"` is the
  value the subscription URL is built from, and it fails quiet. Not in any item.
  Should become required before item 8 ships a URL to a friend's device.
- **N4.** Item 10 S1 pins `deploy/docker/control.Dockerfile:7`.
  `deploy/warden/Dockerfile:20` has the identical floating-tag defect plus an
  unversioned `npm install -g @anthropic-ai/claude-code`, and ohno's §6.1 freeze
  leaves it. Consistent with his position and I do not contest it — but "images
  are pinned" stays false repo-wide after item 10, and the acceptance report
  should say which file was pinned rather than claiming the invariant.
- **N5.** `backlog.md:167` maps item 8 to criterion 5 and `:168` maps item 9 to
  criterion 6, while the prose correctly says both are only partially closed until
  M3. The traceability table should carry the same "half" qualifier the prose
  does, or a later reader will read the table alone.
- **N6.** Item 5's out-of-scope list excludes "password reset" and "multiple
  operators" but does not say what happens on repeated failed authentication.
  Not a v1 requirement and I am not adding one — but Holmes will ask, so it is
  cheaper to write "no lockout in v1, deliberately" than to relitigate it in
  Phase 6.

---

## 9. The three charter amendments

**A — base64 URI list as the v1 subscription format. Technically the right call,
with one correction and one collision.**

It is the only format v2rayNG consumes at all, and Hiddify and streisand consume
it too, so the client-coverage argument holds for the transports it can express.
Rejecting Clash and sing-box for v1 is correct: a second format is a second render
path and twice the failure surface for clients nobody has confirmed anyone uses.

Two things attach to it:

- the correction is **B1** — it forces `edge` to own URI serialisation. Amendment
  A is fine; the rulebook's `-> dict` is what has to move.
- the collision is **B2** — it cannot carry AmneziaWG, which is M1's own second
  transport.

Also worth putting to the owner rather than assuming: Amnezia (the client) is the
weakest of the four named for *subscription* URLs specifically — it is
historically a config-import client rather than a subscription client. ohno's Q7
asks the right question; I would raise its priority from "not urgent" to "before
item 8", because it is the one assumption in the set whose failure is discovered
by a friend rather than by a test.

**B — one link, several country-labelled entries. Correct, and the right call.**

The URI fragment (`#label`) is the display name in v2rayNG, Hiddify and streisand,
and their stock per-server picker is exactly the "choose an exit country"
affordance criterion 5 describes. It preserves core invariants §1 — one artefact
in a friend's hands — and it avoids the failure mode where a friend holds a
per-country link that becomes stale when that country's node is destroyed, which
would defeat criterion 2 as well. No objection. Implementation note in §7.5.

**C — owner-executed acceptance for criterion 1. Outside my remit to approve;
technically accurate and I support recording it.**

Nothing in `tests/e2e/` can reach a Russian mobile network. The honesty already
exists in `.e2e/profile.yml:50-53`, `README.md:51-54` and `CLAUDE.md`, and ohno is
right that it is absent from the one document where the criteria themselves live.
His §6.6 — never write a test that claims criterion 1, and refuse acceptance if
one appears — is the correct engineering position and I will enforce it in
Phase 7.

---

## 10. FOR THE PROJECT OWNER — decisions this review surfaces

I am running unattended and cannot ask. These are additions to ohno's §5, not
replacements; his Q1–Q8 stand.

1. **B2 — AmneziaWG versus the base64 subscription format.** The plan's second
   transport cannot be delivered through the plan's subscription format. My
   technical recommendation is to make the M1 second transport
   **VLESS + WS + TLS behind a camouflage front** (already in `charter.md:85`) and
   move AmneziaWG to M3/M4 where it is consumed by node configuration rather than
   by a friend's client. **This is a `what` decision — it is ohno's call, not
   mine.** It must be made before item 3 is dispatched. It does not affect item 1
   and does not delay M1's start.
2. **ohno's Q7, raised in priority.** "Which clients do your friends actually
   use?" should be answered before **item 8**, not merely before M2 ends. If
   anyone's primary client is AmneziaVPN rather than v2rayNG or Hiddify, amendment
   A's coverage claim needs re-checking. This is the only assumption in the plan
   whose failure is discovered by a friend rather than by a test.
3. **ohno's Q2 (`.env` inside the warden mount) — I endorse option (a) and I
   endorse doing it now.** Confirmed at `deploy/warden/docker-compose.yml:49`.
   It is small `infra` work, it is secret protection rather than tooling
   investment, and it is the only option that does not depend on what an
   unattended model decides to do. Note the risk is live *while this review is
   being written* — the fleet is running under exactly that mount.
4. **Whether M1–M2 acceptance being local-only is acceptable (F7).** No e2e
   scenario in this backlog runs in CI, and ohno's tooling freeze forbids fixing
   that before M3. I think the freeze is the right call and the trade-off is worth
   naming out loud rather than inheriting silently.
5. **Everything else in ohno's §7 stands** — the M1→M5 route, Q1 (working access),
   Q3 (public or private repository), and permission for amendment C. I have no
   technical objection to any of them. On Q3 I will add only that `main` is
   already pushed, so the decision is about whether to *keep* it public, not
   whether to make it so.

---

## 11. What I do next, once the route is confirmed

1. Fix `.claude/workflow.md` (§7.7) — before any dispatch, since it governs every
   agent's branch behaviour.
2. Write `xavier-to-neumann-{task-id}.md` for item 1, carrying ohno's acceptance
   criteria verbatim and adding decisions §7.1–§7.5 as technical criteria.
3. Open the design security review for Holmes on that spec, per `workflow.md`
   Phase 2.
4. Return B2, F1–F8 and the M2 infra gap to ohno so the backlog is corrected by
   its owner. I have not edited `research.md` or `backlog.md` — report, not
   rewrite.

---

*Charles Xavier — architect. Verdict: `approved-with-changes`. Four blocking
findings, eight fix-before-item findings, six nits. No milestone reordering
required.*
