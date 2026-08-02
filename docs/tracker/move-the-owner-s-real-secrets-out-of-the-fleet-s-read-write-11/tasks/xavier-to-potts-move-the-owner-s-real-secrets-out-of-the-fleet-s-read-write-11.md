# Spec — move the owner's real secrets out of the fleet's read-write mount

**From:** Charles Xavier (architect)
**To:** Pepper Potts (`dev-potts`) — zone `infra`, the only developer on this task
**Task:** `move-the-owner-s-real-secrets-out-of-the-fleet-s-read-write-11` —
task 2 of 18 of epic `directive-90be25f3-9` (Stage 1 / M1)
**Backlog item:** `0` — `infra-env-out-of-warden-mount`
**Kind:** `develop` · **Depends on:** task 1 (landed)
**Baseline:** `50fe8c1cd2e82cddd1e4d4bc1db5690eeceaec3e`
**Branch:** `task/2-env-out-of-warden-mount-directive-90be25f3-9`
**Verify:** `make test-infra`

---

## 0. The one prohibition that outranks everything else in this file

**You must not read, print, `cat`, `head`, `tail`, `grep`, copy, move, delete or
otherwise open `/repo/.env`.** Not once, not "just to check the format", not
inside a debugging step, not through `git diff`, not through a script you wrote.
`.env.example` is the only env file you may read.

If you need to know whether `.env` exists, `test -f .env` is allowed and its
contents are not. **You do not move the file either** — the move is the owner's
one action, and an agent that moves it has read the directory it is moving it
into and touched a file full of live credentials. See §9.

Every scenario in this task asserts on **the compose files, the Makefile and the
`.e2e` profile**. None of them asserts on the contents of any env file.

---

## 1. Context, in the owner's terms

`deploy/warden/docker-compose.yml:65` mounts this repository **read-write** into
the container where an unattended agent has `Bash`, `Write`, `Edit` and network
egress. The owner's real `.env` — the key that encrypts every node credential,
the database password, the fleet's GitHub token — sits inside that mount. The
only thing protecting it is prompt text ("NEVER read or print `.env`") plus one
masking mount. There is no deny rule and no filesystem separation.

After this task the project's **canonical env-file location is outside the
repository**, every compose invocation reads it from there, and a warden start
without it fails loudly and names the action the owner must take. The owner then
performs one `mv` and the secret is genuinely gone from the mount.

**This task does not remove the risk on its own.** It removes the tooling's
dependence on the dangerous location and makes the omission impossible to miss.
Until the owner runs the `mv` in §9, the real `.env` is still sitting under the
mount. Say that plainly in your report; do not describe the risk as closed.

---

## 2. What is already fixed, and must not be claimed again

**The `--env-file` half of the folded-in defect is already in the tree.**
`Makefile:102` reads `COMPOSE_WARDEN := docker compose --env-file .env -f
deploy/warden/docker-compose.yml`, with the explanatory comment at `Makefile:98-101`.
It landed in commit `303f1a0 fix(warden): actually deliver GH_TOKEN to the
container`. I verified this against the tree at the baseline commit.

The epic's Intent still names "`Makefile:98` runs the warden compose **without**
`--env-file`" because it was written before that commit. **The flag is there. The
remaining work is the PATH, not the flag.**

Your report must state this in one sentence — that the `--env-file` half was
already fixed by `303f1a0` and this task did not do it. Do not claim it. Equally,
do not let the fixed half hide the broken one: the flag points at `.env`, which is
inside the mount, and that is exactly what is still wrong.

---

## 3. Questions and defaults in force

This is an unattended run. `scripts/ask_owner.sh` cannot return an answer, so I
formed the questions once and answered each myself with the most conservative
option available. Each default below is **in force** for this task. A default may
settle a fact or a process; per §1.5 of
`docs/tracker/directive-90be25f3-9/tasks/xavier-decisions-directive-90be25f3-9.md`
it never grants a permission the charter reserves to the owner, and none of these
does.

### Q1. Does S1 mean the *warden stack's* env file, or the project's single `.env` that also feeds the product stack?

**Default: the project's single env file. It moves wholesale, and every compose
invocation — product, dev, e2e and warden — reads it from the new path.**

Justification. The frozen S1 is *"файл окружения с настоящими секретами не
находится ни под одним из них"* — no env file carrying real secrets is under any
mounted path. `/repo/.env` carries `HASHI_SECRET_KEY` and `POSTGRES_PASSWORD`;
those are real secrets and that path is inside `../..:/repo`. Moving only a
warden-specific file would leave the key that encrypts every node credential
under the agent's read-write mount and would fail S1 as written. Narrowing a
frozen criterion is forbidden. The owner's own framing agrees and is singular:
*"От тебя нужно одно действие — переложить свой `.env` туда, куда его будет
читать compose"* (`docs/research/product-owner-ohno-4/research.md:49`).

The cost is real and is accepted deliberately: `make up`, `make up-dev`,
`make e2e-up` and friends stop reading `./.env`. That is a larger blast radius
than a warden-only change, and it is the smaller of the two risks.

### Q2. Where exactly does the file go, and how is the path expressed?

**Default: Make variable `HASHI_ENV_FILE ?= $(HOME)/.config/hashi/hashi.env`.**

- **Outside every mounted path.** The warden container's host-side paths are
  `../..` (the repo root, mounted read-write at `/repo`), `../../.env.example`
  (mounted read-only at `/repo/.env`) and the named volume `hashi-warden-state`.
  The build context is also `../..`. `~/.config/hashi/` is under none of them.
- **Not baked in.** `?=` and `$(HOME)` mean no absolute host path is written into
  the repository, and `make warden-up HASHI_ENV_FILE=/somewhere/else.env`
  overrides it — the same shape as the existing `KAIZEN ?= $(HOME)/stuff/...`
  at `Makefile:96`. A filesystem path is not one of the values CLAUDE.md forbids
  hardcoding (country, provider, IP, domain, port), but an unoverridable value is
  the same mistake in a different costume, and the infra rulebook's *"no absolute
  host paths"* trap points the same way.
- **`hashi.env`, not `.env`.** A non-hidden, project-named file is visible in a
  directory listing, is unambiguous if the owner keeps env files for several
  projects, and makes a stray copy back into the repo look wrong rather than
  normal.
- **Named `HASHI_ENV_FILE`, not `ENV_FILE`.** Make gives an exported shell
  variable precedence over `?=`; a generic name can be shadowed by accident.

### Q3. Should `warden-down` and `warden-logs` be blocked by the missing-file guard?

**Default: no. `warden-up` and `warden-scenarios` are guarded; `warden-down` and
`warden-logs` are not, and must keep working when the file is absent.**

Justification. Think about who is at the keyboard when the guard fires. An owner
whose env file is missing, renamed, or on an unplugged drive still has an
unattended agent container running with write access to his tree. The one thing
he must be able to do is **stop it and look at it**. A guard that blocks `down`
turns a security control into a way of trapping the fleet in the running state.
Guard what starts things; never guard what stops them.

`down` and `logs` need no interpolated value — every `${...}` in
`deploy/warden/docker-compose.yml` carries a `:-` default — so they can run
without `--env-file` at all. See §5.3 for the exact required behaviour.

### Q4. May `deploy/warden/docker-compose.yml` be edited at all, given "do not change anything else under `deploy/warden/`"?

**Default: yes — the comment text inside the `volumes:` block, and nothing else.**

Justification. The frozen out-of-scope line is *«любые другие изменения в
`deploy/warden/`»* — any **other** change. "Other" is relative to the change this
item authorises, which is *where the env file lives*. Lines 66–78 of that file
are the written explanation of the masking mount: they state that the real `.env`
lives on the host at the repo root and is resolved from there by `--env-file`.
After this task that is no longer where it lives. **A comment that lies about a
security control is a defect, and shipping one inside the task that changed the
control is the specific failure this item exists to prevent.**

The bound is mechanical and the reviewer checks it against the diff: **the diff of
`deploy/warden/docker-compose.yml` contains no change to a non-comment line.**
No service, key, image, mount, environment entry, network or volume changes.
Comment lines outside the `volumes:` block are not to be touched either.

### Q5. Keep or remove the `.env.example:/repo/.env:ro` overlay?

**Default: KEEP it, and hold it with a test assertion so removing it turns
something red.**

Justification, including the part that is uncomfortable. The overlay is a **real
and valuable** mitigation: today it is the reason an agent that `cat`s
`/repo/.env` sees fake values, and it is the reason the risk in this repository is
"the file is reachable in principle" rather than "the file was already read". It
is not worthless and I am not going to pretend it is.

It is also **not sufficient for S1**, and the distinction is precise:

- S1 is about **where the file lives**. The overlay is about **what one container
  sees**. The host file `/repo/.env` remains inside the mounted directory tree
  `../..` whatever the container's mount table says.
- The overlay masks exactly one path. `.env.bak`, `.env.local`, a second checkout,
  an editor's swap file — none are covered.
- It depends on the container's mount table being exactly right on every start.
  A future edit, a hand-written `docker run`, a debug container mounting the same
  repo, or a compose invocation with a different overlay file removes the
  protection with nothing turning red.
- The host-side `--env-file .env` keeps the file's **canonical** location inside
  the repository, so every document, every habit and every new tool points back
  into the mount. That is the thing this task changes.

Keeping the overlay after the move costs nothing and defends against the file
coming back — which is the realistic failure, not the exotic one. Removing it
would be trading a working control for tidiness.

### Q6. Where does S1 live, and does an S1 test violate "do not add tests for warden"?

**Default: `tests/infra/test_warden_env_location.py`, a new file. It does not
violate the frozen out-of-scope line.**

My reading, stated explicitly so it can be disagreed with: *«тесты на warden»*
means tests that exercise **warden's runtime and its Python code** —
`deploy/warden/warden.py`, `scenarios.py`, `entrypoint.sh`, the gRPC paths, the
Hub protocol. That is fleet tooling, and the freeze holds over it. **S1 is not
that.** S1 is the acceptance scenario of backlog item `0` itself, and item `0` is
one of the freeze's two named exceptions. It asserts on configuration files as
text and YAML. It imports nothing from `deploy/warden/`, executes nothing from
it, and starts nothing.

The bound is in §7. Nothing outside that assertion list is authorised.

A **new file** rather than an addition to `tests/infra/test_compose.py`, for two
reasons: S1 stays identifiable as this item's acceptance rather than dissolving
into a general compose test, and task 16 of this epic edits `test_compose.py` —
two tasks in one file is how a merge conflict becomes a lost assertion.

### Q7. Is a skipped test the right artefact for S2, which cannot execute here?

**Default: yes — one unconditionally skipped test whose reason names the exact
command, plus `-rs` on `make test-infra` so the reason is actually printed.**

`pytest.mark.skip` imports nothing, runs nothing and needs no runtime, so the
"only if it can be done without importing or running warden code" condition is
met. It must be an **unconditional** `skip`, never `skipif(docker is absent)`: a
conditional version would *run* on the owner's machine and start containers
during `make test-infra`, and a static verify command that boots a stack is a
worse defect than the one being fixed.

With `pytest -q` a skip's reason is not printed, only counted. `-rs` makes it
visible. That is a flag on `test-infra` only — not on `test-control` or
`test-edge`, whose reports belong to other tasks that are running against them.

### Q8. Does `make env` survive, and where does it write?

**Default: it survives, unchanged in meaning, and writes to `$(HASHI_ENV_FILE)`.**

If `make env` kept writing `./.env`, a **documented verb** would put a
secret-shaped file straight back inside the mount — the leak-back path is the
project's own Makefile. It also creates the parent directory, and the file it
creates is `0600` (and the directory `0700`). It never touches a file that
already exists, and it never touches `/repo/.env`.

The infra rulebook allows adding a verb and forbids changing what an existing one
means. `make env` still means "make sure this project has an env file to start
from"; only its location changed, and the location is now the project's stated
one.

### Q9. Does the fleet perform the move?

**Default: no, never.** See §0 and §9. The `mv` is the owner's, the guard names
it, and the report states that the risk is not closed until he runs it.

### Q10. Do the `${VAR:?set VAR in .env}` messages in `deploy/docker-compose.yml` count as cosmetic?

**Default: no — they are a leak-back path and must be corrected.**

Seven messages in `deploy/docker-compose.yml` tell the owner to set a variable
"in `.env`". After this change, an owner who follows that instruction creates a
file full of live secrets at the repo root, inside the mount. That is not stale
prose; it is an instruction to reintroduce the defect. The change is bounded to
the **message text inside the existing `${VAR:?...}` forms** — no variable added,
removed, renamed or re-defaulted. That file is in your zone and is not under
`deploy/warden/`, so the frozen out-of-scope line does not reach it.

### Q11. What about `deploy/warden/entrypoint.sh:54` ("Set it in `.env` to enable pushing")?

**Default: leave it. Record it in the report as a known, deliberate stale
string.**

The line I drew in Q4 is: a file under `deploy/warden/` may be edited **only**
where it describes the control being changed or the start procedure that would
otherwise be wrong. `entrypoint.sh:54` is a runtime hint about setting a
variable, printed inside the container; the owner does still set `GH_TOKEN` in
his env file, so the sentence is imprecise rather than false, and it is squarely
inside *«любые другие изменения в `deploy/warden/`»*. Leaving it and saying so is
more honest than editing it and hoping nobody counts.

---

## 4. Scope — what you own on this task

1. Introduce the env-file location as a Make variable and point every compose
   invocation and the `env` target at it.
2. Add a loud, actionable guard to the warden targets that start things.
3. Keep the warden targets that stop and inspect things working without the file.
4. Correct the places that would otherwise instruct a reader to put the real env
   file back inside the repository, or that describe the old topology of a
   security control.
5. Write S1 as a static, TREE-provable scenario, red-first proven.
6. Write S2 as a loud, unconditional skip that names the command that would prove
   it.
7. Report honestly, including what you did not do and what is not closed.

### 4.1 File allowlist — you may touch these and nothing else

| Path | What may change |
|---|---|
| `Makefile` | the variable, the guard, the four compose invocations, the `env` target, `-rs` on `test-infra`, the comments explaining all of it |
| `deploy/docker-compose.yml` | the **message text** inside the seven existing `${VAR:?...}` forms only |
| `deploy/warden/docker-compose.yml` | **comment lines inside the `volumes:` block only** — no non-comment line may change |
| `deploy/warden/README.md` | the env-file location, the owner's one-line move, and one line in *What to think twice about* — nothing else |
| `deploy/AGENTS.md` | the `--env-file` rule at line 32, so it names the right file |
| `.env.example` | a header comment naming the destination and stating that the real file never lives in this repository. **No variable added, removed, renamed or given a different value** |
| `.e2e/profile.yml` | the `--env-file` in the `on_fail` command (line 40) and the `where:` note (line 44) |
| `tests/infra/test_warden_env_location.py` | **new file** — S1 and the S2 skip |
| `docs/tracker/<task-id>/status/dev-potts.yml` | your status file |

### 4.2 Explicitly not yours on this task

- **`/repo/.env`** — never opened, never moved, never deleted. §0.
- Anything else under `deploy/warden/`: `Dockerfile`, `warden.py`,
  `entrypoint.sh`, `scenarios.py`, `vendor/**`.
- `tests/infra/test_compose.py` — task 16 edits it.
- `.dockerignore` and `.gitignore` — they belong to **no zone**; they are
  architect territory. Both already do the right thing (`.dockerignore:10`
  excludes `.env` from the build context). You may **assert** on `.dockerignore`
  in S1; you may not edit it. If an assertion on it fails, that is an escalation
  to me, not an edit.
- `README.md` and `CLAUDE.md` at the repo root — no zone, mine to update. I have
  flagged them; do not edit them and do not treat their staleness as your defect.
- `pyproject.toml`, `.claude/**`, `docs/product/**`, `control/**`, `edge/**`.
- `deploy/caddy/**`, `deploy/docker/**`, `deploy/docker-compose.dev.yml`.

### 4.3 Non-goals — do not do these even if they look adjacent

- **Privilege separation inside the container** (frozen out of scope).
- **Tests exercising warden's runtime or Python code** (frozen out of scope).
- Docker secrets, `sops`, a vault, an encrypted env file, a secret manager — none
  is authorised and each would be a dependency decision that is not yours.
- Removing or narrowing the `../..:/repo` read-write mount. That mount is the
  fleet's whole job; narrowing it is a different task nobody has approved.
- Pinning `deploy/warden/Dockerfile:20`. Task 16 of this epic leaves that floating
  tag **deliberately** under the freeze; do not "fix" it here.
- Adding any dependency. The authorised set is the six packages in Appendix A of
  `docs/tracker/directive-90be25f3-9/tasks/xavier-decisions-directive-90be25f3-9.md`
  and it is complete for all eighteen tasks. A seventh stops and escalates.
- An e2e job in CI, or any other fleet-tooling improvement.
- Renaming, reordering or re-defaulting any variable in `.env.example`.

---

## 5. The contract you are implementing

Described, not coded. The shapes below are the contract; the recipe is yours.

### 5.1 The location variable

- One variable, `HASHI_ENV_FILE`, defined with `?=` so the environment and the
  command line override it, defaulting to `$(HOME)/.config/hashi/hashi.env`.
- **Every** `docker compose` invocation in the Makefile passes
  `--env-file $(HASHI_ENV_FILE)` — the product stack, the dev overlay, the e2e
  stack and the warden stack. No invocation keeps a literal `.env`.
- The comment that currently sits at `Makefile:98-101` explaining why
  `--env-file` is not optional stays true and stays there; extend it to say why
  the file is not in the repository. Keep the existing reason (a bare `${VAR}`
  becomes an empty string) — it is correct and it is why task 8 depends on this
  shape holding.

### 5.2 The guard, and its exact text

A reusable guard in the same shape as the existing `need_venv` at
`Makefile:31-33`. It checks only for the file's **existence** (`test -f`). It
never reads it, never `source`s it, never echoes a value from it, and never
prints anything but the path.

The message, when the file is absent — this text, adjusted only for line
wrapping:

```
no hashi env file at <HASHI_ENV_FILE>
the real .env must live OUTSIDE this repository — the fleet mounts it read-write
move it once:   mkdir -p <dir> && mv .env <HASHI_ENV_FILE> && chmod 600 <HASHI_ENV_FILE>
fresh clone:    make env
or point at an existing file: make <target> HASHI_ENV_FILE=/path/to/hashi.env
```

`<HASHI_ENV_FILE>` and `<dir>` are the expanded values, so the instruction is
correct even when the owner has overridden the variable. The guard exits non-zero
**before** `docker compose` runs, so the failure is the guard's clear message and
not compose's "env file not found".

**Guarded:** `warden-up`, `warden-scenarios`.
**Not guarded, and must work without the file:** `warden-down`, `warden-logs` —
see §5.3.
`up`, `up-dev` and `e2e-up` keep their existing `env` prerequisite and are
therefore not guarded; `down`, `logs`, `ps` and `e2e-down` keep their present
shape and behaviour, which is unchanged by this task except for the path.

### 5.3 `warden-down` and `warden-logs` with no env file

Required behaviour:

- When `$(HASHI_ENV_FILE)` exists: behave exactly as today, with `--env-file`.
- When it does not: print **one** line saying the env file was not found at that
  path and that the stack is being stopped / tailed anyway, then run the same
  compose command **without** `--env-file`. This is safe for these two verbs and
  only these two: every interpolation in `deploy/warden/docker-compose.yml`
  carries a `:-` default, and neither `down` nor `logs` needs a value.
- The line names the path and nothing else. No variable value is ever printed.

Do **not** generalise this fallback to the product stack: after task 8 the base
compose file carries `${VAR:?}` forms that must abort, and a bare invocation
there would be exactly the silent-empty-string trap the whole repository is
defended against.

### 5.4 `make env`

- Destination `$(HASHI_ENV_FILE)`; source `.env.example`.
- Creates the parent directory if absent, mode `0700`; the file it creates is
  `0600`.
- Never overwrites an existing file, and prints the same "created — fill it in"
  style message with the **new** path.
- Never touches `./.env`, in any way, for any reason.

### 5.5 The comment in `deploy/warden/docker-compose.yml`

Rewrite only the comment text in the `volumes:` block so that it states, in the
file's existing voice:

- the repo is still mounted read-write, and that is still the mount worth
  thinking twice about;
- the real env file now lives **outside the repository**, at the path
  `HASHI_ENV_FILE` names (default `~/.config/hashi/hashi.env`), and `--env-file`
  resolves the `environment:` block from there;
- the `.env.example` → `/repo/.env:ro` overlay is **kept deliberately, as defence
  in depth**, so that a `.env` reappearing at the repo root is still masked
  inside the container — and that it is a mask on one path, not the control;
- the control is the file's location.

No non-comment line changes.

---

## 6. Acceptance criteria

The two scenarios below are **frozen** in
`docs/research/product-owner-ohno-4/research.md` §3, item `0.
infra-env-out-of-warden-mount`. They are reproduced here in the original Russian,
unreworded, unnarrowed and unwidened. My English gloss follows each and is a
reading aid, not the criterion.

> - **S1 — секретов нет внутри монтирования.**
>   *Given* конфигурация стека warden,
>   *when* проверяется, какие пути монтируются в контейнер агента,
>   *then* файл окружения с настоящими секретами не находится ни под одним из них.
>
> - **S2 — стек warden поднимается из нового расположения.**
>   *Given* файл окружения перемещён,
>   *when* выполняется штатный запуск стека warden,
>   *then* он стартует, а запуск без указания файла окружения падает с внятной
>   ошибкой, а не молча подставляет пустые строки.

**S1** — given the warden stack's configuration, when you check which paths are
mounted into the agent container, then the env file with the real secrets is
under none of them.

**S2** — given the env file has been moved, when the standard warden start is
run, then it starts; and a start without the env file fails with a clear error
rather than silently substituting empty strings.

**Out of scope, frozen:** *«любые другие изменения в `deploy/warden/`; тесты на
warden (§6.1 — заморозка держится); разделение прав внутри контейнера.»* My
readings of the first two are Q4, Q6 and Q11; the third is absolute.

### Technical criteria I add (they do not weaken the two above)

- **T1.** `make test-infra` passes, including `ruff check tests/infra deploy/warden`.
  Any Python you add passes ruff at the project's configured settings.
- **T2.** The diff of `deploy/warden/docker-compose.yml` contains no change to a
  non-comment line.
- **T3.** No file added or changed by this task reads, prints or references the
  *contents* of any real env file.
- **T4.** Every scenario that executes is **red-first proven** — break it, watch
  the right assertion fail, restore it, and record which assertion failed.

---

## 7. S1 as an executable check — the authorised assertions

File: `tests/infra/test_warden_env_location.py` (new). Module header in the
project's WHAT/WHY/HOW form, explaining that this is backlog item `0`'s
acceptance and why it asserts on configuration rather than on a running stack.

**Exactly these assertions are authorised. Nothing else.**

- **(a) Mounted paths.** Parse `deploy/warden/docker-compose.yml` as YAML.
  Collect every host-side bind-mount source under `services.*.volumes` and the
  `build.context`. Resolve each relative to the compose file's directory. Assert
  that the env-file path the Makefile passes to `--env-file` for the warden stack
  resolves **outside every one of them**, and in particular outside the
  repository root.
- **(b) The Makefile's env-file path.** Read `Makefile` as text. Assert:
  every `--env-file` occurrence takes the `$(HASHI_ENV_FILE)` variable and not a
  literal path; `HASHI_ENV_FILE` is defined with `?=` (overridable); its default,
  after `$(HOME)`/`~` expansion, is an **absolute** path that is not inside the
  repository root and is not a bare `.env`. Apply the same "points outside the
  repository" assertion to every `--env-file` occurrence in `.e2e/profile.yml`.
- **(c) No verb puts it back.** Assert the `env` target's destination is
  `$(HASHI_ENV_FILE)`, and that no Make recipe writes, copies or creates a file
  named `.env` at the repository root. The failure this guards is a documented
  command reintroducing the defect.
- **(d) The overlay is still there.** Assert `deploy/warden/docker-compose.yml`
  still mounts `../../.env.example` at `/repo/.env` read-only. Q5's
  defence-in-depth control is held by a test, so removing it turns something red.
- **(e) The build context cannot carry it.** Assert the warden service's
  `build.context` is the repo root **and** that `.dockerignore` excludes `.env`,
  `*.key`, `*.pem` and `secrets/`. Nothing to change — this is a sentinel over a
  control that already exists and that a future edit could quietly remove. If it
  fails, escalate to me; `.dockerignore` is not yours to edit.

**Forbidden inside this file, absolutely:**

- importing, executing or subprocessing anything under `deploy/warden/`;
- reading `.env` or any file outside the repository;
- asserting on the contents of any env file other than `.env.example`;
- starting a container, touching a socket, or making a network call;
- any assertion about *the diff* — per the backlog's *«Сценарий не имеет права
  ассертить по диффу»*, S1 is TREE-provable and therefore a **static scenario**.
  T2 (the no-non-comment-change bound) is a **review gate** for Granger and my
  phase-7 check, and your report must name it as a review gate, not as acceptance.

### Red-first proof — required, per scenario

For each of (a)–(e): break it, run `make test-infra`, watch the **right**
assertion fail, restore it, re-run. Record in the report which assertion failed
for each. Suggested breaks, one at a time, all reverted:

| Assertion | Break |
|---|---|
| (a), (b) | point `HASHI_ENV_FILE`'s default back at `.env` |
| (b) | change `?=` to `:=` |
| (c) | point the `env` target's destination back at `./.env` |
| (d) | comment out the `.env.example:/repo/.env:ro` line |
| (e) | temporarily remove `.env` from `.dockerignore` — **restore it in the same step**; do not leave the tree in that state for a single commit |

A green run without a recorded red-first is not acceptance. That rule is the
backlog's, not mine.

---

## 8. S2 — what it is, and that it did not execute here

S2 needs a container runtime and the Kaizen network. **This environment has
neither.** The command that would prove it is `make warden-up` on a machine with
Docker, followed by `make warden-up HASHI_ENV_FILE=/nonexistent` to see the guard
fire.

**Artefact:** one test in the same new file, decorated with an **unconditional**
`pytest.mark.skip` whose reason names that command. Its body is a docstring
carrying the Given/When/Then of S2 verbatim and nothing executable. Never
`skipif` on Docker's presence — see Q7.

**Makefile:** `make test-infra`'s pytest invocation gains `-rs` so the skip reason
prints. Without it the skip is counted but not spoken, and a silent skip is the
thing the honesty rule exists to prevent.

**The report must contain this sentence, verbatim:**

> S2 not executed — no container runtime in this environment; the warden stack
> was not started. S1 executed statically against the compose files.

**The word "green" must not appear anywhere in your report in connection with
S2**, in any form, in any language. Not "green except S2", not "effectively
green". Report the counts: how many scenarios were **collected** and how many
**executed**, per the backlog rule that a green run with zero executed tests is a
false report.

---

## 9. The owner's remaining action

**This is the one thing that actually removes the secret from the mount, and no
agent may do it.**

The instruction, written so it can be pasted into a notification, run from the
repository root:

```
mkdir -p ~/.config/hashi && chmod 700 ~/.config/hashi && mv .env ~/.config/hashi/hashi.env && chmod 600 ~/.config/hashi/hashi.env
```

Where it is documented in the tree — both, because they are read by different
people at different moments:

- **`.env.example`**, in the header comment: this template is copied to
  `~/.config/hashi/hashi.env` (see `HASHI_ENV_FILE` in the `Makefile`), and the
  real file never lives in this repository. This is where someone looks when they
  ask "how do I configure this project".
- **`deploy/warden/README.md`**, in *Run it* and in one line of *What to think
  twice about*: the same command, plus the sentence that the repo is mounted
  read-write and the real env file therefore lives outside it. Ruled inside the
  authorised change by Q4's reasoning: the README's documented start procedure
  would otherwise be wrong the moment this lands.

Root `README.md` and `CLAUDE.md` also describe the env file's location. They
belong to **no zone** and are mine; I have flagged them and they are not your
defect.

### The notification

Item `0`'s frozen intent says to notify the owner **the moment this lands**, not
at the stage report. Send it through `scripts/notify.sh` at hand-over, with this
content — one message, no batching:

> ACTION REQUIRED — task 2 (`infra-env-out-of-warden-mount`) has landed. The
> project now reads its env file from `HASHI_ENV_FILE`, default
> `~/.config/hashi/hashi.env`, which is outside every path mounted into the agent
> container. **The risk is not closed until you move the file.** One action, from
> the repo root:
> `mkdir -p ~/.config/hashi && chmod 700 ~/.config/hashi && mv .env ~/.config/hashi/hashi.env && chmod 600 ~/.config/hashi/hashi.env`
> Until then your real `.env` is still inside the fleet's read-write mount.
> S2 not executed — no container runtime in this environment; the warden stack
> was not started. S1 executed statically against the compose files.

---

## 10. Dependencies on other zones

None. This task is `infra` only, start to finish. It touches no file in
`control/**` or `edge/**` and requires nothing from Anderson or Neumann.

Task 1 has landed; branch from the current `develop` per `DEC-C`,
`docs/tracker/directive-90be25f3-9/tasks/xavier-decisions-directive-90be25f3-9.md`.
The merge model is `DEC-X1` in the same file: one PR into `develop`, merged by the
fleet only after review is `CLEAN`, security is clean and `make test-infra` passed
**when the reviewer ran it**. `main` is never agent-merged.

**Task 8** of this epic depends on the shape you leave behind: it adds
`${VAR:?message}` variables to `deploy/docker-compose.yml` and needs every compose
invocation to keep passing `--env-file`. Do not remove the flag from anything, and
do not introduce a bare-compose fallback anywhere except the two verbs in §5.3.

---

## 11. Rulebooks this change must preserve

- `.claude/projects/00-core-invariants.md` — §3: secrets are supplied by the
  environment and never live in the tree.
- `.claude/projects/04-infra-rulebook.md` — *Traps*: `docker compose` must run
  with `--env-file`, and **the control plane stays relocatable — no absolute host
  paths**, which is exactly why §5.1 is a `?=` variable derived from `$(HOME)`.
  *Idioms*: secrets reach containers only through the env file, never through
  build args, never in a compose literal, never baked into a layer.
  *Interfaces*: adding a Make verb is fine; changing what an existing verb means
  is not — `make env` keeps its meaning (§5.4).
  *Testing*: a test that needs Docker skips **loudly** rather than passing
  vacuously (§8).
- `.claude/projects/03-security-checklist.md` — every item that touches secret
  handling.
- `CLAUDE.md` — never read or print `.env`; never log who connected to what;
  adding a dependency is an architect decision.
- `docs/product/backlog.md`, *Как читать этот файл* — a TREE-provable scenario is
  a **static** scenario; something that is really about the diff is a **review
  gate** and is called that; a green run without red-first is not acceptance; a
  scenario that cannot execute skips loudly and names the command that would
  execute it.

---

## 12. Hand-over — what your report must contain

1. Which files you changed, and confirmation that the allowlist in §4.1 was not
   exceeded.
2. **The sentence in §8, verbatim.** No "green" in connection with S2.
3. Scenarios **collected** and **executed**, as counts.
4. The red-first record for (a)–(e): what you broke, which assertion went red.
5. The exact command you ran (`make test-infra`) and its result — per the backlog
   rule that "how the scenarios were run" must be stated or green means nothing.
6. One sentence stating that the `--env-file` half of the folded-in `Makefile:98`
   defect was **already fixed by `303f1a0`** and that this task did not do it.
7. The residual risk, in plain words: the real `.env` is still inside the mount
   until the owner runs the `mv` in §9.
8. The known stale string you deliberately did not touch
   (`deploy/warden/entrypoint.sh:54`, Q11).
9. T2 named as a **review gate**, not as acceptance.
10. Confirmation that you did not at any point open, move, copy or delete
    `/repo/.env`.

**If anything in this spec turns out to be impossible, or if you find yourself
needing to touch a file outside §4.1 — stop and escalate to me through
`scripts/notify.sh`. Do not widen the boundary yourself.** In particular: needing
a dependency, needing to edit `.dockerignore`, `.gitignore`, `pyproject.toml` or
`tests/infra/test_compose.py`, or finding that S1 cannot be asserted without
importing warden code, are all escalations.

---

*Charles Xavier — architect. The frozen S1 and S2 are reproduced above unchanged.
Nothing in this spec reworded, weakened, dropped or renumbered a criterion in
`docs/product/backlog.md` or `docs/research/product-owner-ohno-4/research.md` §3.*
