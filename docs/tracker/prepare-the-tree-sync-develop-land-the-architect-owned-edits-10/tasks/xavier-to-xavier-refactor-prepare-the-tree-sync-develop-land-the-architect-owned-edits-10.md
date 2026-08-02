# Refactor spec — prepare the tree: sync `develop`, land the architect-owned edits, publish the decisions the rulebooks cannot carry

**From:** Charles Xavier (architect) · **To:** the executor of Phase 2 (architect territory — no zone developer may execute this)
**Task:** `prepare-the-tree-sync-develop-land-the-architect-owned-edits-10`
**Epic:** `directive-90be25f3-9`, task **1 of 18** (Stage 0 — preparation)
**Kind:** `refactor` · **Zone:** none — `docs/**`, `pyproject.toml`, `.gitignore`, git branch state
**Depends on:** nothing. **Blocks:** every other task in the epic.
**Authoritative source:** §1 of
`docs/tracker/directive-90be25f3-9/tasks/xavier-epic-decomposition-directive-90be25f3-9.md`.
This spec **executes** that section; it does not re-decide it. Where this spec and
§1 disagree, §1 wins and the disagreement is a defect in this spec.

---

## 1. Goal, in the fleet's terms

The next seventeen tasks must branch from a tree that is:

1. **not six commits stale** — `origin/develop` is a strict ancestor of `main`, so
   anything branched from it today starts from a tree missing six commits;
2. **able to ship `edge/transports/*` into a built image** — today the explicit
   package list names `edge.transports` but none of its children, so every
   transport package a developer writes silently fails to reach the container.
   That is charter criterion 4 broken inside the build system;
3. **already carrying every dependency this epic was designed around**, at exact
   pins, so that no developer is blocked by design by a rule he is right to obey
   (adding a dependency is an architect decision, core invariants §5);
4. **able to read the architect's decided contract text somewhere that is not
   write-protected** — `.claude/**` cannot be written, and three decided
   corrections plus one autonomy raise live nowhere else.

**Behaviour change: none.** No runtime code is touched. `pyproject.toml` changes
what the *build collects* and what the *environment contains*; every import path,
every entry point and every test assertion stays exactly as it is.

---

## 2. Boundary

### 2.1 Files this task may create or modify — the complete list

| Path | Part | Action |
|---|---|---|
| git branch state: local `develop`, `origin/develop`, one task branch | (a) | create / fast-forward / push |
| `pyproject.toml` | (b), (c) | modify, in exactly the three places named in §5 and §6 |
| `.gitignore` | (d) | append one commented entry |
| `docs/tracker/directive-90be25f3-9/tasks/xavier-decisions-directive-90be25f3-9.md` | (e) | create |
| `docs/tracker/prepare-the-tree-.../status/architect-xavier.yml` | housekeeping | create / update |
| `docs/tracker/prepare-the-tree-.../` report and this spec | housekeeping | create / update |

**Nothing else.** A diff touching any other path is a boundary violation and the
PR is rejected on that ground alone, before any other review point.

> **Declared deviation, added in fix round 1 — see §13, D1.** One further path set
> was committed by this task and is **not** in the table above: the epic's own
> architect-authored source documents,
> `docs/tracker/directive-90be25f3-9/{README.md, children.json, status/**,
> tasks/xavier-epic-decomposition-…md, tasks/xavier-epic-questions-…md}`. They
> were untracked, which made this task's own deliverable dangle — the decisions
> file quotes them as authority, and a reviewer on the PR could not resolve a
> single citation. They are architect territory (`docs/**`) and this epic's own
> charter. They land in **a commit of their own**. The deviation is declared here
> rather than absorbed silently, because a boundary list that quietly grows is
> not a boundary.

### 2.2 Out of scope — must not be touched

- **`.claude/**`** — write-protected, re-verified by probe. Part (e) exists
  *because of* this. Do not attempt a shell workaround; a refused write is the
  correct outcome and routing around it would be the finding.
- **`docs/product/backlog.md`** and **`docs/product/charter.md`** — the Product
  Owner's files. `backlog.md` additionally carries an **uncommitted change from a
  previous task that is not yours**: do not commit it, do not revert it, do not
  stage it, do not edit it. Same for `docs/tracker/notifications.log`.
- **`control/**`, `edge/**`, `deploy/**`, `tests/**`, `Makefile`, `scripts/**`,
  `.github/**`, `.env.example`** — zone territory. In particular **no test file
  may be created, edited or deleted by this task** (see §8).
- **`.env`** — never read, never printed, never copied. `.env.example` is the only
  env file that may be opened, and this task has no reason to open either.
- **`main`** — never pushed to, never agent-merged, never rebased. Releasing
  `develop` into `main` is a human action.
- **`origin/task/2-control-plane-xavier-curie-pr-control-plane-3`** — the stale
  remote task branch. Left exactly as it is, deliberately. Do not delete it, do
  not check it out, do not mention it in the PR as work.
- **Any seventh dependency.** The six in §6 are the complete authorised set for
  the whole epic. Not "for this task" — for the epic.

---

## 3. Facts established before this spec was written

These were measured, not assumed. Do not re-derive them; do re-check the two
marked **(re-check)** immediately before acting, because the tree may have moved.

| # | Fact |
|---|---|
| F1 | `make test` passes at baseline: **3 control + 2 edge + 10 infra = 15 tests**, ruff clean, exit 0 |
| F2 | `origin/develop` (`77493c9`) is a **strict ancestor** of `main` — 0 ahead, 6 behind. There is **no local `develop`** branch **(re-check)** |
| F3 | The files differing between `origin/develop` and `main` are exactly: `.claude/projects/02-edge-rulebook.md`, `Makefile`, `deploy/warden/docker-compose.yml`, `deploy/warden/entrypoint.sh`, `deploy/warden/warden.py`, `docs/product/charter.md`. **None** is dirty in the working tree, so the checkout in §4 cannot lose an uncommitted change |
| F4 | The working tree carries uncommitted changes to `docs/product/backlog.md` and `docs/tracker/notifications.log` from a **prior task (the Product Owner's)**, plus untracked `docs/tracker/{directive-90be25f3-9,main-8,prepare-the-tree-…-10}/` **(re-check)** |
| F5 | `origin` = `https://github.com/earlzdev/Hashi.git`; local `main` == `origin/main`; base commit `1bf8deb` |
| F6 | No test anywhere in `tests/` reads `pyproject.toml` or asserts anything about the packages list — verified by grep. So (b) and (c) cannot change a test outcome |
| F7 | Under the baseline configuration, an installed tree contains `edge/transports/__init__.py` but **no child package of `edge.transports`** — reproduced empirically in a scratch copy of the repo (§5.3) |
| F8 | All six dependencies in §6 resolve on **CPython 3.14** with binary wheels, together, including their transitive set — reproduced empirically (§6.3) |

---

## 4. Part (a) — sync the integration branch

### 4.1 Exact sequence

```
git status --porcelain                    # record; must match F4
git fetch origin
git checkout -b develop origin/develop
git merge main --no-edit
git push origin develop
```

`git checkout -b develop origin/develop` moves the working tree back six commits.
That is safe **only** because of F3 — none of the six differing files is dirty.
**Re-check F3 and F4 before running the checkout.** If any file in F3's list is
dirty, or if `docs/product/backlog.md` has changed shape since, **stop and
escalate**; do not stash, do not `checkout --force`, do not commit someone else's
work to get past it.

### 4.2 What the merge actually does, stated so nobody reports it wrongly

Because `origin/develop` is a strict ancestor of `main`, `git merge main --no-edit`
**fast-forwards**. It creates **no merge commit**. §1's acceptance bar words this
as "`git log --oneline develop -1` shows the merge"; the faithful check for a
fast-forward is identity of tips:

```
test "$(git rev-parse develop)" = "$(git rev-parse main)"   # must be true
git log --oneline develop -1                                 # must print 1bf8deb (main's tip)
```

The report says *"`develop` fast-forwarded to `main`; no merge commit was created
because `origin/develop` was a strict ancestor"* — never *"merged"* without that
sentence, and never `--no-ff` to manufacture a commit that documents nothing.

### 4.3 The Product Owner's dirty files

After the checkout, after the merge, after the push, and again at the end of the
task:

```
git status --porcelain     # must still show ` M docs/product/backlog.md`
                           # and ` M docs/tracker/notifications.log`, unstaged
git diff --stat docs/product/backlog.md docs/tracker/notifications.log
```

The `--stat` output must be **identical** to the reading taken before §4.1 ran.
Those two files leave this task unstaged, uncommitted and byte-identical.

### 4.4 The task branch

```
git checkout -b task/1-prepare-the-tree-directive-90be25f3-9 develop
```

All of (b), (c), (d), (e) land on that branch. `develop` itself receives nothing
by direct commit.

### 4.5 If `GH_TOKEN` is empty

`git push` fails. That is a **supported mode**, not a failure: the task stays
local, `develop` is synced locally only, and the report lists the changed files
instead of a PR link (`CLAUDE.md`, *Published ports and credentials*). Never read
`GH_TOKEN` to find out — attempt the push and read the exit code.

---

## 5. Part (b) — the packaging fix

### 5.1 What is wrong today

`pyproject.toml:29-30`:

```toml
[tool.setuptools]
packages = ["control", "control.app", "edge", "edge.transports"]
```

The list names `edge.transports` and stops there. Every package a transport
developer creates — `edge/transports/vless_reality/`, and every one after it — is
**not** in the list, so `pip install .` does not install it. `pip install .` is
exactly what `deploy/docker/control.Dockerfile:15` runs. `discover()` then returns
`{}` for the installed distribution while finding transports fine in a developer's
editable install: the defect is invisible where it is written and fatal where it
runs.

### 5.2 The exact replacement

Replace lines 29-30 in full — the `[tool.setuptools]` table disappears, because
`packages` was its only key — with **exactly** this:

```toml
# WHAT: which packages the build collects.
# WHY:  the explicit list this replaces named `edge.transports` but none of its
#       children, so every transport package silently missed the built image —
#       charter criterion 4 broken in the build system, not in the code. Pattern
#       discovery means adding a transport requires an edit nowhere else.
# HOW:  `include` is a whitelist matched against full dotted package names, so
#       `tests*`, `deploy*` and `scripts*` cannot be swept in — none of them
#       begins with `control` or `edge`. `namespaces = false` keeps the candidate
#       set to directories that carry an `__init__.py`, so a template data
#       directory or a stray `__pycache__` can never be collected as a package.
[tool.setuptools.packages.find]
where = ["."]
include = ["control*", "edge*"]
namespaces = false
```

Three decisions inside that block, stated so the executor does not improvise:

- **`namespaces = false` is explicit and deliberate.** setuptools defaults it to
  `true` in `pyproject.toml` mode, which admits directories with no `__init__.py`.
  Both settings behave identically on today's tree — measured — but `false`
  reproduces the *semantics* of the list it replaces (every entry in that list is
  a real package) and removes a class of surprise the fix has no reason to buy.
  A transport that wants a subpackage writes an `__init__.py`, which it must do
  anyway to be importable.
- **`include` is a whitelist**, not a filter over an auto-discovered set. `tests`,
  `deploy`, `scripts`, `docs` and `.e2e` are not reachable by `control*` or
  `edge*`. An `exclude` key would therefore be decoration; it is deliberately not
  added, and §5.3 asserts the outcome empirically instead of trusting the reading.
- **`where = ["."]`** is stated rather than defaulted, because the packages live
  at the repository root and a future `src/` layout must be a visible edit.

### 5.3 The empirical proof — before and after

This is a **new check**, not a modified assertion. It runs in a **scratch copy of
the repository**, never in the working tree: this task must not create a file
under `edge/**`, not even a temporary one.

```
SCRATCH=$(mktemp -d); TGT_BEFORE=$(mktemp -d); TGT_AFTER=$(mktemp -d)
git archive HEAD | tar -x -C "$SCRATCH"             # HEAD of the task branch
mkdir -p "$SCRATCH/edge/transports/_probe"
printf '# probe\n' > "$SCRATCH/edge/transports/_probe/__init__.py"
printf 'x = 1\n'   > "$SCRATCH/edge/transports/_probe/render.py"

# BEFORE: the baseline packaging configuration, same probe package
git show 1bf8deb:pyproject.toml > "$SCRATCH/pyproject.toml"
( cd "$SCRATCH" && .venv-python -m pip install . --no-deps --target "$TGT_BEFORE" -q )

# AFTER: this task's packaging configuration, same probe package
git show HEAD:pyproject.toml > "$SCRATCH/pyproject.toml"
( cd "$SCRATCH" && .venv-python -m pip install . --no-deps --target "$TGT_AFTER" -q )
```

(`.venv-python` is `/repo/.venv/bin/python`; write the real path.)

Assertions, all of which must hold:

| # | Assertion | Target |
|---|---|---|
| P1 | `edge/transports/_probe/__init__.py` **absent** | `$TGT_BEFORE` |
| P2 | `edge/transports/__init__.py` **present** | `$TGT_BEFORE` — proves the probe is measuring the child gap, not a broken build |
| P3 | `edge/transports/_probe/__init__.py` and `_probe/render.py` **present** | `$TGT_AFTER` |
| P4 | `control/`, `control/app/`, `edge/`, `edge/transports/` all present | `$TGT_AFTER` |
| P5 | `tests/`, `deploy/`, `scripts/`, `docs/`, `.e2e/` **absent** | `$TGT_AFTER` |
| P6 | `hashi-0.0.0.dist-info/top_level.txt` contains exactly `control` and `edge` | both targets |

P1 + P3 together are the reproduction and the fix. Record the actual command
output in the report — not the words "verified".

If network egress is blocked and `pip install .` cannot fetch its build backend,
follow §1's *Skip-loudly note* exactly: report **"packaging fix landed but not
verified by installation"** and **stop**, because tasks 3 and 5 both stand on it.
Do not substitute a reading of the TOML for the check.

### 5.4 A gap this task deliberately does not close — read before task 3 starts

Measured in the same scratch run: **non-Python files inside a package are not
installed by either the old configuration or the new one.** A `.j2` template
placed in `edge/transports/<name>/templates/` reaches neither target, because
`include-package-data` has no `MANIFEST.in` and no VCS plugin to draw from.

This is **not** a regression introduced here and **not** in this task's scope —
§1(b) authorises pattern discovery and nothing more. It is recorded because task
3 renders from templates loaded at import time and task 5 asserts `discover()`
inside a built image. Two consequences, both to be carried into those specs:

- `control.Dockerfile` copies `control/` and `edge/` into `/app` **as well as**
  installing, so a template is reachable in the image today by source path. Do not
  let that accident be mistaken for correct packaging.
- If task 3 or task 5 finds that a data file must be installed, that is a
  `pyproject.toml` change, `pyproject.toml` belongs to no zone, and the developer
  **stops and escalates to the architect** rather than editing it. Both specs say
  so already; this paragraph is the reason.

---

## 6. Part (c) — the six dependencies, at exact pins

### 6.1 The exact edit

Replace the `dependencies` array at `pyproject.toml:10-15` with:

```toml
dependencies = [
    "fastapi",
    "uvicorn",
    "pydantic-settings",
    "jinja2",
    "sqlalchemy[asyncio]==2.0.51",
    "asyncpg==0.31.0",
    "alembic==1.18.5",
    "itsdangerous==2.2.0",
    "argon2-cffi==25.1.0",
    "cryptography==50.0.0",
]
```

The four existing entries keep their position and stay **unpinned**. Pinning them
is a separate decision, is not authorised by §1, and is not smuggled in here.

### 6.2 The versions, and why each is that version

Every one was resolved against **CPython 3.14** on this machine, not read from
memory. This repository requires `>=3.14`, which is young enough that "the latest
release" and "a release that installs" were not the same question.

| Package | Pin | Why this version |
|---|---|---|
| `sqlalchemy[asyncio]` | `==2.0.51` | Current 2.0 release and the only series with native asyncio; ships a `cp314` wheel, and the `asyncio` extra resolves `greenlet 3.5.4`, which is where 3.14 support landed — without a `cp314` greenlet wheel the extra would build from source in the image |
| `asyncpg` | `==0.31.0` | **Forced, not preferred.** On Python 3.14 pip sees exactly one candidate: `0.31.0`. `asyncpg==0.30.0` fails outright with *"from versions: 0.31.0"* — 0.31.0 is the first release with a `cp314` wheel, and the driver is a C extension, so there is no pure-Python fallback |
| `alembic` | `==1.18.5` | Current release, pure Python, `requires-python >=3.10`; pulls `Mako` and `MarkupSafe 3.0.3` (`cp314` wheel present) |
| `itsdangerous` | `==2.2.0` | Current release, pure Python, no compiled dependency; this is the signing primitive under Starlette's session middleware (task 10) and nothing newer exists |
| `argon2-cffi` | `==25.1.0` | Current release, the first to declare 3.14, and it pairs with `argon2-cffi-bindings 25.1.0` built against `cffi 2.1.0` — which is the release with a `cp314` wheel. Older `argon2-cffi` resolves too, but drags the 2021 bindings whose `abi3` wheel predates 3.14 and is untested on it; a password hash is the wrong place to be adventurous |
| `cryptography` | `==50.0.0` | Current release; its `cp311-abi3` wheel covers 3.14 through the stable ABI. This is Fernet for at-rest encryption of node secrets (task 11) — the newest release is the correct default for a crypto library, and no other crypto library is authorised |

### 6.3 The empirical proof

```
DL=$(mktemp -d)
/repo/.venv/bin/python -m pip download --only-binary=:all: -d "$DL" \
  "sqlalchemy[asyncio]==2.0.51" "asyncpg==0.31.0" "alembic==1.18.5" \
  "itsdangerous==2.2.0" "argon2-cffi==25.1.0" "cryptography==50.0.0"
ls "$DL"
```

Must succeed with every wheel binary-only. The resolved transitive set measured
while writing this spec, recorded so a later divergence is visible: `greenlet
3.5.4` (`cp314`), `typing_extensions 4.16.0`, `Mako 1.3.12`, `MarkupSafe 3.0.3`
(`cp314`), `argon2_cffi_bindings 25.1.0` (`cp39-abi3`), `cffi 2.1.0` (`cp314`),
`pycparser 3.0`.

**Do not install any of them into `/repo/.venv`, and do not run `make setup`.**
Nothing in this task imports them, `make test` does not need them, and an
unnecessary change to the venv is a change to the baseline this task must
preserve.

### 6.4 The comment at `pyproject.toml:17-19`

Replace:

```
# Persistence dependencies (sqlalchemy, asyncpg, alembic) are deliberately absent
# until the control plane actually has a database. Adding a dependency is an
# architect decision — see .claude/projects/00-core-invariants.md §5.
```

with **exactly**:

```
# Adding a dependency is an architect decision (.claude/projects/00-core-invariants.md
# §5), not an implementation detail. The six pinned above are the *complete*
# authorised set for epic directive-90be25f3-9: sqlalchemy[asyncio], asyncpg and
# alembic for the persistence spine; itsdangerous and argon2-cffi for operator
# auth; cryptography for secrets at rest. A task that needs anything else stops
# and escalates to the architect — it does not edit this file. The decision, and
# the epic's other decisions the write-protected rulebooks cannot carry, live in
# docs/tracker/directive-90be25f3-9/tasks/xavier-decisions-directive-90be25f3-9.md
```

---

## 7. Part (d) — `.gitignore`

Append to `/repo/.gitignore`, after the e2e-artifacts block and before `.DS_Store`:

```
# Local upstream checker binaries: a pinned Xray release, fetched and checksum-
# verified by the Make verb task 4 of epic directive-90be25f3-9 adds. Fetched,
# never committed — a binary in history is not reviewable, and pinning it in a
# fetch step is what makes "the version is exact" checkable.
.tools/
```

Do not name the Make verb: task 4 chooses it, and a wrong name here becomes a
wrong name in four documents. Do not create `.tools/` — the entry precedes the
directory on purpose, because `.gitignore` belongs to no zone and the `infra`
developer may not edit it.

---

## 8. Part (e) — the decisions file

**Create** `docs/tracker/directive-90be25f3-9/tasks/xavier-decisions-directive-90be25f3-9.md`.

This file is cited by every later task in the epic, so its **structure is a
contract**, not a matter of taste. Later specs quote decision ids; those ids must
be stable and must not move.

### 8.1 Required outline, in this order

| § | Heading | Content requirement |
|---|---|---|
| — | `# Architect decisions carried outside `.claude/**` — epic `directive-90be25f3-9`` | Header block: From (Charles Xavier, architect); Task; Date; Status (`in force`); the one-sentence reason the file exists (`.claude/**` is write-protected, re-verified by probe in this session) |
| 0 | `## 0. How to cite this file` | The citation table below, verbatim in content: five decision ids, what each decides, where it lives in this file. States that a spec cites `DEC-x` plus this path, and never paraphrases the decided text |
| 1 | `## 1. Precedence` | Four rules: (i) where this file and a file under `.claude/**` disagree **on a point recorded here**, this file governs and the rulebook is stale at the named line; (ii) it governs **nothing else** — every unamended rule in every rulebook stands; (iii) it grants no permission beyond `DEC-X1`; (iv) it is **not** a substitute for applying the corrections — when the owner lifts the write protection, A, B and C are applied from here unchanged |
| 2 | `## 2. Corrections A and B — verbatim, unchanged` | One sentence of provenance, then the **exact contiguous block** from `docs/tracker/ohno-5/tasks/xavier-blocked-edits-ohno-5.md` running from the line `## A — .claude/projects/02-edge-rulebook.md — B1, render_client's return` up to, and **not** including, the line `## C — .claude/workflow.md — N2, the origin drift`. No re-heading, no renumbering, no reflowing, no fixing of anything. This includes B's closing *"Note for the item-1 spec"* paragraph |
| 3 | `## 3. DEC-C — correction C, re-issued against the tree of 2026-08-02` | The re-issued text in §8.3 below, plus a short "what changed and why" preamble naming the original as **superseded, not repeated** |
| 4 | `## 4. DEC-X1 — the autonomy raise` | The verbatim quotations in §8.4 below |
| 5 | `## 5. DEC-D — proposed, not in force` | The verbatim `## D — ...` section from the `ohno-5` file, preceded by the status ruling in §8.5 |
| A | `## Appendix A — the authorised dependency set` | A record, not a new decision: the six pins from §6.1 with their one-line reasons, the sentence *"No other dependency is authorised anywhere in this epic"*, and the pointer to `pyproject.toml` as the place the decision actually lives |
| — | `## Change log` | One row: `2026-08-02 — created by task 1 of the epic. A and B copied verbatim; C re-issued; X1 recorded; D carried as proposed.` |

The citation table for §0:

| Id | What it decides | Where |
|---|---|---|
| `DEC-A` | `render_client` returns a `ClientEntry`, not a `dict`; `02-edge-rulebook.md:66` and its contract-table row are stale | §2, block `## A` |
| `DEC-B` | The `edge/registry.py` edit is authorised **once**, inside the first transport only; the rulebook's unconditional ban is stale in that one place | §2, block `## B` |
| `DEC-C` | What `origin` actually is, and the branch/PR rules that follow from it | §3 |
| `DEC-X1` | Merge authority: L2 for `develop` only; `main` never agent-merged; a "big stage" is a milestone | §4 |
| `DEC-D` | The same drift in `.claude/git-workflow.md` — **proposed, not in force** | §5 |

### 8.2 How "verbatim" is proved

After writing the file, prove the copy mechanically rather than by eye:

```
python3 - <<'PY'
src = open('docs/tracker/ohno-5/tasks/xavier-blocked-edits-ohno-5.md').read()
dst = open('docs/tracker/directive-90be25f3-9/tasks/xavier-decisions-directive-90be25f3-9.md').read()
a = src.index('## A — '); c = src.index('## C — ')
block = src[a:c]
assert block in dst, 'A+B block is not a verbatim substring of the decisions file'
d = src.index('## D — ')
assert src[d:].split('---')[0] in dst, 'D section is not verbatim'
print('verbatim OK:', len(block), 'chars')
PY
```

Both assertions must pass. This is why the decision ids live in §0's table and
**not** as inserted lines above `## A` and `## B` — an inserted line would break
contiguity and make "verbatim" unprovable.

### 8.3 The re-issued correction C — the text to carry

Preamble to write above it: *the original section C was written when `origin`
carried only `main`. `origin/develop` exists today (`77493c9`), task 1 of this
epic fast-forwarded it to `main`, and the stale
`origin/task/2-control-plane-…` branch is also present. So `git pull origin
develop` is executable and `gh pr create --base develop` has a target. C is
therefore **superseded, not repeated**; the text below replaces it in full and is
what gets applied to `.claude/workflow.md` when the protection is lifted.*

Replacement for rules 1-4 of *Iron rules (no exceptions)* in `.claude/workflow.md`:

```
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
  and nothing else — that permission comes from `DEC-X1` and from nowhere else.
- The fleet's git credential is `GH_TOKEN`, wired into `git` and `gh` at
  container boot. No agent reads it. An **empty** `GH_TOKEN` is a supported
  mode: the push fails, the project stays local-only, and the completion report
  lists **which files changed** instead of a PR link. Do not treat that as a
  failure and do not work around it.
```

### 8.4 DEC-X1 — what to quote verbatim

Two quotations, both marked as quotations and neither paraphrased:

1. The **five bullets** of *Default if unanswered* under **X1** in
   `docs/tracker/directive-90be25f3-9/tasks/xavier-epic-questions-directive-90be25f3-9.md`
   — from *"Read the directive as an explicit, task-scoped raise to L2 for
   `develop` only"* through *"Batching lowers noise, never escalation."*
2. The **Merge model (X1)** standing rule from the header of
   `xavier-epic-decomposition-directive-90be25f3-9.md` (*"the fleet opens one PR
   per task into `develop`…"* through *"…batching lowers noise, never
   escalation."*).

Then one paragraph of your own, clearly separated from the quotations: this raise
is **task-scoped to epic `directive-90be25f3-9`**, it is recorded here and
deliberately **not** in `.claude/git-workflow.md` (write-protected — two documents
disagreeing about who may merge is the failure being avoided), and it changes
**nothing** about `main`.

### 8.5 DEC-D — the ruling

Correction D was **flagged, not decided**, in the `ohno-5` file. The ruling this
task records, and the reasoning, both of which go into the file:

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

This ruling is deliberately the conservative option: carrying the text costs
nothing and loses no work, while *applying* it would mean the architect granting
himself a permission (see **Assumption A3**).

---

## 9. Order of operations

1. Record the baseline: `git status --porcelain`, `git diff --stat` of the two PO
   files, and a full `make test` run with its counts.
2. Part (a): §4.1, then the checks in §4.2 and §4.3.
3. Create the task branch (§4.4).
4. Part (b): §5.2. Part (c): §6.1 and §6.4. Part (d): §7. Part (e): §8.
5. Run the proofs: §5.3 (P1-P6), §6.3, §8.2.
6. Run `make test` again; compare against the baseline (§10).
7. Re-run §4.3 — the PO's two files must still be dirty and unchanged.
8. Update `docs/tracker/prepare-the-tree-…-10/status/architect-xavier.yml`.
9. Commit, push, open the PR (§11).

---

## 10. Behaviour-preservation proof

Named concretely, because "no behaviour change" is a claim and not an argument.

| # | Proof | Passing condition |
|---|---|---|
| B1 | `make test` before and after | **Identical**: 3 control, 2 edge, 10 infra = **15 passed**, ruff clean, exit 0. Not "still green" — the same three counts |
| B2 | No test file touched | `git diff --name-only develop..HEAD` contains **no path under `tests/`**. No test was added, edited, deleted, renamed, skipped or xfailed |
| B3 | No runtime code touched | The same diff contains no path under `control/`, `edge/`, `deploy/`, `scripts/`, `.github/`, and not `Makefile` or `.env.example` |
| B4 | No import path changed | Every module importable before is importable after and from the same dotted name: (b) only **widens** the collected set — `control`, `control.app`, `edge`, `edge.transports` are all still matched by `control*`/`edge*`. P4 and P6 in §5.3 assert this against an installed tree |
| B5 | The `pip install --target` check is **new empirical evidence**, not a changed assertion | It exists in no test file, changes no existing assertion, and lives only in this task's report. Report it as *"a new check introduced by this task"* — never as *"a test that now passes"* |
| B6 | The PO's uncommitted work is untouched | §4.3's `git diff --stat` reading is identical before and after, and both files are still unstaged at the end |
| B7 | The complete diff | `git diff --name-only develop..HEAD` equals exactly: `pyproject.toml`, `.gitignore`, `docs/tracker/directive-90be25f3-9/tasks/xavier-decisions-directive-90be25f3-9.md`, this task's own tracker files, and — **added in fix round 1 as declared deviation D2 (§14), not as a widening** — the epic's own source documents under `docs/tracker/directive-90be25f3-9/` (`README.md`, `children.json`, `status/**`, and the epic decomposition and questions files). Anything else is a boundary violation. In particular `docs/tracker/main-8/`, `docs/product/backlog.md` and `docs/tracker/notifications.log` must **not** appear |
| B8 | The venv is unchanged | `pip freeze` on `/repo/.venv` is identical before and after — the six pins were resolved with `pip download` into a scratch directory and installed nowhere |

---

## 11. Merge model for this task

Per `DEC-X1`, and no wider:

- **One PR**, from `task/1-prepare-the-tree-directive-90be25f3-9` into **`develop`**.
- Self-merged **only** on all three of: review verdict `CLEAN` from Granger;
  security review clean from Holmes; and the verify command **run by the
  reviewer** — here `make test`, whose passing condition is B1's three counts,
  not "exit 0".
- **`main` is never agent-merged and never pushed to.** This task pushes exactly
  two refs: `develop` (the fast-forward from §4.1) and the task branch.
- Any blocker, red gate or open question **escalates immediately** through
  `scripts/notify.sh` and stops the queue. Specifically: a dirty file in F3's
  list, a refused fast-forward, a failed P1/P3, a dependency that does not
  resolve, or a `.claude/**` write that unexpectedly succeeds.
- Stage 0's owner-facing deliverable is a **notification only** — no owner PR.
  On completion send one message through `scripts/notify.sh` naming the four
  landed parts and the PR link (or, on empty `GH_TOKEN`, the changed-file list).

---

## 12. Acceptance criteria

Restated from §1's acceptance bar. Nothing weakened; the one restatement is
marked and justified.

1. `make test` passes with **exactly** 3 control + 2 edge + 10 infra = 15 tests,
   ruff clean, exit 0 — identical to baseline.
2. A `pip install .` into a scratch target produces a tree containing a **child
   package of `edge/transports/`** that the baseline configuration omitted:
   P1 and P3 in §5.3, both recorded with their command output.
   *(§1 words this as "a tree containing `edge/transports/`". Taken literally,
   the baseline already satisfies it — `edge.transports` is in the old explicit
   list, and only its **children** are missing (F7). The check is therefore made
   sharper, not looser: it now fails on the baseline, which is the whole point.)*
3. `develop` and `main` point at the same commit, and the report says
   "fast-forwarded, no merge commit" rather than "merged" (§4.2).
   *(Restated from "`git log --oneline develop -1` shows the merge": a
   fast-forward creates no merge commit, and manufacturing one with `--no-ff`
   would document nothing.)*
4. `docs/tracker/directive-90be25f3-9/tasks/xavier-decisions-directive-90be25f3-9.md`
   exists, follows §8.1's outline exactly, and passes §8.2's verbatim check.
5. The six dependencies are present at exact `==` pins and resolve on Python 3.14
   (§6.3); the `pyproject.toml:17-19` comment points at the decisions file.
6. `.gitignore` ignores `.tools/`, with the comment from §7.
7. B1-B8 all hold.
8. Nothing under `.claude/**`, `docs/product/**`, `control/**`, `edge/**`,
   `deploy/**` or `tests/**` was modified.

---

## 13. Assumptions recorded

This is an **unattended run**: `scripts/ask_owner.sh` cannot return an answer.
Where a choice was genuinely the owner's, the conservative option was taken and
recorded here rather than deferred.

- **A1 — `namespaces = false`.** The owner's project prefers explicit
  configuration; setuptools' default (`true`) would silently admit directories
  with no `__init__.py`. Both were measured and behave identically on today's
  tree, so `false` costs nothing and preserves the semantics of the list it
  replaces. If a later task needs a namespace package under `edge/`, that is an
  architect change to `pyproject.toml`, not a developer's.
- **A2 — the four pre-existing dependencies stay unpinned.** Pinning
  `fastapi`, `uvicorn`, `pydantic-settings` and `jinja2` is defensible and is
  **not authorised by §1**. Adding it here would be scope this task invented.
  Flagged for the owner as a separate, one-line decision.
- **A3 — correction D is carried as `proposed — not in force`.** Two of its four
  points change what an agent is *allowed to do*. Recording the text costs
  nothing and loses no work; applying it would be the architect granting himself
  a permission. The conservative option is to carry and not apply. (§8.5)
- **A4 — the acceptance restatements in §12.2 and §12.3.** Both make a check
  **sharper**, never looser, and both are marked in place with the reason. If the
  Product Owner or the owner reads either as a weakening, this task is wrong and
  stops.
- **A5 — the fast-forward is accepted as the sync.** `--no-ff` was rejected: a
  merge commit that records no merge is noise in the history of the branch every
  later task starts from.
- **A6 — package data (`*.j2`, `*.html`) is knowingly left uninstalled.** §5.4.
  Not a regression, not in scope, and carried forward to tasks 3 and 5 with the
  escalation path named. **Fix round 1:** the carry-forward is now written down
  rather than assumed, as `OBL-2` in Appendix B of the decisions file — including
  that the gap is currently *masked* by `control.Dockerfile` copying `control/`
  and `edge/` into `/app`, that the eventual fix is an explicit
  `[tool.setuptools.package-data]` glob and never `include-package-data` or a
  `MANIFEST.in recursive-include`, and that no package under `control/` may be
  named `secrets`.
- **A7 — the six versions are pinned at the current release of each.** For a
  young interpreter that is the version that *has* a wheel; for `asyncpg` it is
  the only version that exists on 3.14 at all. If a pin later proves wrong, it is
  an architect change to `pyproject.toml` and a note in the decisions file — never
  a developer loosening a pin to get past a failure.

---

## 14. Deviations and defects declared in fix round 1

This section exists because §0 of this spec says: *"Where this spec and §1
disagree, §1 wins and the disagreement is a defect in this spec."* Two such
disagreements were found in review. Both are recorded; neither is papered over,
and **the epic decomposition file is not edited to make either go away.**

### D1 — the decisions file carries more than §1(e) names

**§1(e) names four things:** corrections A and B verbatim, a re-issued correction
C, and the recorded autonomy raise from X1. The file that landed also carries
`## 5. DEC-D` and `## Appendix A`, neither of which §1(e) names. Fix round 1 added
`## Appendix B` (forward obligations) and `## Appendix C` as well.

Per §0, §1 wins and **this is a defect in this spec**, not in §1.

Nothing is deleted. §5 is marked *proposed — not in force*, is not applied, and
may not be cited as authority by any spec in this epic. Appendix A is explicitly
a **record** of a decision that lives in `pyproject.toml`, not a second decision.
Both are inert, and deleting correct, clearly-marked, useful text to close a
documentation discrepancy would trade a small defect for a real loss.

Appendix B is called out separately because it is **not** inert: it binds tasks 3,
4 and 5 via `OBL-1` and `OBL-2`. It lives there because it arose from the security
review of this task and a forward obligation with no home is one nobody inherits.

**The architect owns the reconciliation** — either §1(e) is widened to name what
the file actually carries, or the surplus moves to a file of its own with the
citing specs updated. It is not a later task's problem and no later task may act
on the discrepancy. The same record is in Appendix C and the change log of
`docs/tracker/directive-90be25f3-9/tasks/xavier-decisions-directive-90be25f3-9.md`.

### D2 — the epic's source documents were committed, beyond §2.1

Declared in full at §2.1. In short: the decisions file cites the epic's README,
`children.json`, status files, decomposition and questions files as the source of
`DEC-X1`'s quotations and `DEC-C`'s factual claims, and all of them were
untracked — so no reviewer on the PR could verify a single citation and this
task's deliverable dangled. They are architect territory and this epic's own
charter, and they landed in a commit of their own, clearly labelled.

Explicitly **not** committed, and unchanged on disk: `docs/tracker/main-8/` (a
different task's artifact), `docs/product/backlog.md` and
`docs/tracker/notifications.log` (the Product Owner's, still dirty, byte-identical
and unstaged). Staging was by explicit path throughout — no `git add -A`, no
`git commit -a`.

---

*Charles Xavier — architect. This spec executes §1 of the approved decomposition.
It adds no scope, changes no acceptance criterion, and takes no `what` decision.
Fix round 1 corrected the authority chain and recorded two declared deviations;
it changed no behaviour, no test, no pin and no dependency.*
