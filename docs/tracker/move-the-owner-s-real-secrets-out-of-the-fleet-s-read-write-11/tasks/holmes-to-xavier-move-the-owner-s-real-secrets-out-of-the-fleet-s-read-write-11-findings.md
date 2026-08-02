# Security review (design, phase 2) — move the owner's real secrets out of the fleet's read-write mount

**From:** Sherlock Holmes (`security-holmes`)
**To:** Charles Xavier (architect), cc Pepper Potts (`dev-potts`)
**Task:** `move-the-owner-s-real-secrets-out-of-the-fleet-s-read-write-11` — task 2 of 18, epic `directive-90be25f3-9`
**Reviewed:** `xavier-to-potts-…-11.md` (the implementation spec) and `xavier-to-holmes-…-11-review.md`, against the tree at `50fe8c1`
**Phase:** 2 — design review, before implementation. No code exists on this task yet; every finding is against the spec.

> **Filename note.** The review task (§5) asks for
> `holmes-security-review-move-the-owner-s-real-secrets-out-of-the-fleet-s-read-write-11.md`;
> my dispatch named this file. This is the only findings document — there is no second one.

---

## 0. Compliance with the prohibition, and one incident I am reporting against myself

I did not `cat`, `head`, `tail`, open, copy, move or delete `/repo/.env`, and I did not
run `git diff` over it.

**But I did print two of its lines, and you should know exactly how.** Enumerating
leak-back paths (axis 3) I ran a tree-wide `grep -rn "\.env\b" .` for *references to*
the env file. The pattern matched **inside `/repo/.env` itself**, and two lines were
printed:

```
./.env:1:# hashi — environment template. Copy to .env and fill in.
./.env:2:# Every value here is FAKE or blank. Never commit a real one; never print .env.
```

Those are the two comment lines of `.env.example`, verbatim; **no variable, value or
credential was disclosed**, and I stopped there. I did not re-run the search.

I report it because it is not an aside — **it is this task's threat model executing
live, on the first ordinary command a reviewer runs.** I had the prohibition in my
system prompt, twice, in capitals, from two separate authors, and a routine
repository-wide grep for the *string* `.env` read the real file anyway. Inside the
warden container the overlay would have masked it and the same command would have
printed `.env.example`. Outside it, nothing did. This is the empirical answer to
review-task §4's question "is the control we built theatre?": no — **the prompt-level
prohibition is what is theatre, and this task correctly stops depending on it.**

Metadata I did read (permitted — existence and mode, never contents):
`/repo/.env` exists and is mode **0664** (group-writable, world-readable). That fact
is load-bearing for finding **M-2**.

Also verified without reading contents: `.env` is **untracked**, and
`git log --all --name-only -- .env` is **empty** — the secret has never entered git
history, so `.git/` (which *is* inside the read-write mount) does not hold a copy.
That is a genuinely good result and it closes the one path the spec never discusses.

---

## 1. Verdict first

**One CRITICAL finding. The design goes back to the architect before implementation.**

The critical finding is not "the task fails to close the risk" — the spec is honest
that only the owner's `mv` closes it, and I accept that framing. The critical finding
is that **the design contains a documented, one-command path that silently produces
the half-migrated state, permanently silences its own guard, and boots the product
stack on the placeholder secrets published in `.env.example` — while the owner's real
`.env` stays inside the read-write mount.** The fix is small, it is entirely inside
the spec's own boundary, and it is far cheaper now than after Potts writes it.

The answer to the question the owner will actually ask is at the end of this file.

---

## Finding C-1: `make env` manufactures the half-migration, and the guard then never fires again

- **Severity**: **critical**
- **Location**: spec §5.4 (`make env` writes `$(HASHI_ENV_FILE)` from `.env.example`);
  spec §5.2 line 364 (`fresh clone:    make env` — inside the guard's own message);
  spec §5.2 ("`up`, `up-dev` and `e2e-up` keep their existing `env` prerequisite and
  are therefore **not** guarded"); `Makefile:27-28`, `Makefile:77`, `Makefile:81`,
  `Makefile:160`.

**Description.** `env` is a prerequisite of `up`, `up-dev` and `e2e-up`, and its
contract is "create the env file from the template if it is absent, never overwrite".
Point its destination at `$(HASHI_ENV_FILE)` and leave the rest, and the following is
the *default* outcome for the owner who has not yet run the `mv`:

1. Owner pulls this change. `~/.config/hashi/hashi.env` does not exist. His real
   `.env` is still at the repo root, still inside `../..:/repo`.
2. He runs `make up-dev` (or `make up`, or `make e2e-up`) — or he reads the guard's
   own message, sees the second suggestion `fresh clone:    make env`, and runs that.
3. `make env` **creates `~/.config/hashi/hashi.env` from `.env.example`** and prints
   "created — fill it in". Nothing errors. Nothing mentions the real file.
4. Compose now boots against that file. The stack comes up with
   `HASHI_SECRET_KEY=replace-me-with-48-random-bytes` and
   `POSTGRES_PASSWORD=replace-me` (`.env.example:7`, `:15`). `${VAR:?...}` does not
   fire — the values are present, they are merely *published in this repository*.
5. From this moment `test -f $(HASHI_ENV_FILE)` is **true**. The guard in §5.2 —
   the entire loud-failure control this task exists to add — **never fires again on
   this machine**, for any target, ever.
6. The real `.env` sits in the fleet's read-write mount indefinitely, and the one
   mechanism that was supposed to nag the owner about it has been switched off by
   following the mechanism's own printed advice.

**Risk.**

- *The control is defeated by its own instructions.* §1 promises "makes the omission
  impossible to miss". After step 3 the omission is not merely missable, it is
  invisible: everything works, nothing warns, and the fleet keeps running over the
  live secret. This is worse than not shipping the guard, because the owner now
  believes a guard is watching.
- *Silent substitution of a publicly-known encryption key.* Today `make up` on the
  owner's machine uses his real `.env`. After this change the same command silently
  switches to a fabricated file whose `HASHI_SECRET_KEY` is a string committed to
  this repository. `.claude/projects/00-core-invariants.md` §3 requires the app to
  fail loudly rather than "start in a degraded mode"; a placeholder is not missing,
  so it starts. Epic task 11 makes `HASHI_SECRET_KEY` encrypt node private keys and
  provider credentials at rest — at which point this path means **node key material
  encrypted under a key printed in `.env.example`**, on a stack the owner believes
  is configured. The security checklist's "secrets come from the environment; the
  app fails loudly when one is missing rather than starting degraded" is not met by
  a template that supplies a well-known constant.
- *Two files, one stale, one live* — exactly the regression you suspected in
  review-task §3.6/Q1, but arrived at **with no user error at all**. The owner does
  not have to half-migrate. `make up` half-migrates for him.
- The `.e2e` stack shares the same env file (`Makefile:156`), so `make e2e-up` does
  it too, and `make test-e2e` then runs against placeholder-secret services.

**Recommendation** (all inside §4.1's allowlist, none requires reading `.env`):

1. **`make env` must refuse to fabricate when `./.env` exists.** `test -f .env` is
   explicitly permitted by §0 (existence, not contents). If the repo-root file is
   present and `$(HASHI_ENV_FILE)` is not, `make env` must **exit non-zero** with the
   §9 `mv` command, not create anything. This is the single highest-value line in
   the whole task: it converts "the owner might forget" into "the tooling will not
   let him forget".
2. **Add the same repo-root existence check to the guard**, as a second, independent
   condition. The guard should fire when `$(HASHI_ENV_FILE)` is missing **or** when
   `./.env` still exists — the second is the state that actually matters, and it is
   the one the current design cannot detect. A one-line
   `test -f .env && echo "a .env still exists at the repo root — it is inside the
   fleet's read-write mount; move it: <mv command>"` on every env-consuming verb
   closes C-1 by itself.
3. **Guard `up`, `up-dev` and `e2e-up` too**, or make their `env` prerequisite the
   refusing version from (1). "Guard what starts things" (Q3) is the right principle;
   the product stack starts things.
4. **Remove `fresh clone:    make env` from the guard message**, or qualify it —
   "fresh clone, with no `.env` in the repo: `make env`". As written it offers the
   wrong remedy to the exact audience the guard was built for.

Recommendation (1) alone downgrades this finding to nothing. I would not merge the
spec without at least (1) and (2).

---

## Finding H-1: the infra rulebook still prescribes the message Q10 is removing — task 8 will put all seven back

- **Severity**: **high**
- **Location**: `.claude/projects/04-infra-rulebook.md:109` —
  `` every required variable is written `${VAR:?set this in .env}` so the failure is loud. ``
  Spec §10 ("**Task 8** … adds `${VAR:?message}` variables to `deploy/docker-compose.yml`").

**Description.** You asked (review-task §3.2) whether you had missed one of your own.
Yes, and this is the one that matters. Q10 correctly classifies
`${VAR:?set VAR in .env}` as a leak-back path — an instruction to recreate the file
inside the mount — and has Potts rewrite all seven in `deploy/docker-compose.yml`.
But the **template those seven were written from is the infra rulebook**, and the
rulebook is pre-read by every infra developer, including Potts on this task and
whoever implements task 8. Task 8's decomposition entry says in terms: *"Every
required variable uses the `${VAR:?message}` form"*, and it declares **three new
mandatory secrets** (a database URL, an operator password hash, a separate session
signing secret).

**Risk.** Task 8 lands three-to-five *new* `${VAR:?set … in .env}` messages in the
same file this task just cleaned, written in good faith from an unchanged rulebook,
and the leak-back path is fully restored inside the same epic — with more secrets
behind it than before. Nothing in this task's design detects that: see H-2.

**Recommendation.** `.claude/**` belongs to no zone and is yours. Update
`04-infra-rulebook.md:109` to `${VAR:?set this in $HASHI_ENV_FILE}` (or wording of
your choice that does not name a repo-root file) **in the same landing as this task**,
not as a follow-up — the interval between this task and task 8 is where the
regression lives. Same pass: `04-infra-rulebook.md:113` and
`.claude/projects/03-security-checklist.md:83` both describe relocation as "a `.env`
change plus a restore", which after this task names the wrong file.

---

## Finding H-2: no sentinel holds the leak-back corrections, so every one of them can regress silently

- **Severity**: **high**
- **Location**: spec §7, authorised assertions (a)–(e); against spec Q10, §9 and §4.1.

**Description.** Q5's reasoning is exactly right and I endorse it: *"KEEP it, and hold
it with a test assertion so removing it turns something red."* That reasoning is then
applied to precisely one control — the overlay, assertion (d) — and to none of the
others this task creates:

| Corrected by this task | Held by an assertion? |
|---|---|
| `deploy/docker-compose.yml` × 7 `${VAR:?… in .env}` messages (Q10) | **no** |
| `.env.example` header — "Copy to .env and fill in" (§9) | **no** |
| `deploy/AGENTS.md:32` (§4.1) | **no** |
| `deploy/warden/docker-compose.yml` volumes comment (§5.5) | **no** |
| `.e2e/profile.yml:40,44` | yes — (b), second sentence |
| the overlay | yes — (d) |
| `make env` destination | yes — (c) |

**Risk.** Q10 declares those seven messages "not stale prose; **it is an instruction
to reintroduce the defect**". An instruction to reintroduce the defect, corrected once
and held by nothing, is a regression waiting for the next author of that file — who,
per H-1, is task 8, in this same epic, in that same file. `.env.example:1` is worse:
it is the first line a human reads when asking "how do I configure this project", and
§4.1 authorises *adding* a header without requiring the contradicting line 1 to be
**replaced**. A `.env.example` whose new header says "the real file never lives in this
repository" three lines under "Copy to `.env` and fill in" is a document that tells
the reader to do the wrong thing.

**Recommendation.** Extend §7's authorised list by two assertions, both static, both
inside the existing forbidden-list bounds:

- **(f)** No file in `deploy/**`, `.env.example` or `.e2e/**` instructs a reader to
  create an env file at the repository root — concretely: no `${VAR:?…}` message in
  `deploy/docker-compose.yml` contains the token `.env` other than `.env.example`,
  and `.env.example`'s header contains no `cp`/"copy to `.env`" instruction. This is
  the assertion that stops task 8 regressing Q10.
- Pin in §4.1 that `.env.example:1` is **rewritten**, not merely supplemented.

---

## Finding M-1: the build-context control is half-asserted, and `.dockerignore` can be silently overridden

- **Severity**: **medium**
- **Location**: spec §7(e); `.dockerignore:10-13`; `deploy/warden/Dockerfile:51,53,54`;
  `deploy/docker/control.Dockerfile:11,12,13`; `deploy/warden/docker-compose.yml:27-29`;
  `deploy/docker-compose.yml:35-37`.

**Description — first, the facts you asked for as checked facts, not assumptions.**

- **Does the repo-root `.dockerignore` apply to a build whose `context: ../..`?**
  **Yes.** The exclusion file is resolved from the **build context root**, not from
  the directory holding the compose file or the Dockerfile. Context is `../..` from
  `deploy/warden/` = the repo root, and `/repo/.dockerignore` is there. Your belief
  is correct.
- **Can `.env` reach an image layer today?** **No, and two independent controls stop
  it.** `.dockerignore:10` excludes it from the context, *and* neither Dockerfile has
  a `COPY . .` — I enumerated every `COPY`/`ADD` in both: warden takes
  `deploy/warden/vendor/infra`, `warden.py`, `entrypoint.sh`; control takes
  `pyproject.toml`, `control`, `edge`. No `ADD` anywhere. The context is safe today.
- **Is the reliance on `.dockerignore` load-bearing?** Yes — it is the only thing
  standing between a future `COPY . .` and a baked secret, which is what
  `.dockerignore:1-8` says about itself.

**Two ways the control fails that (e) does not see:**

1. **A Dockerfile-specific ignore file silently overrides the root one.** Docker
   resolves `<dockerfile-path>.dockerignore` — here `deploy/warden/Dockerfile.dockerignore`
   — **in preference to** the context-root `.dockerignore`, and when it exists the
   root file is **not consulted at all**. There is none today (I checked: the only
   match tree-wide is `./.dockerignore`). Anyone adding one for an unrelated reason —
   trimming context size is the usual motive — disables `.env`, `*.key`, `*.pem` and
   `secrets/` in one stroke, and (e) stays green because it only reads the root file.
2. **`.dockerignore` excludes `.env`, not `.env*`.** `.env.bak`, `.env.local`,
   `.env.save`, an editor's `.env~` — every one enters the context, and after this
   task those are precisely the artefacts a half-migration or a nervous owner leaves
   behind. `.gitignore:9` has the same narrow pattern, so `.env.bak` is also
   *committable*. (e) asserts the four current patterns and would not notice.

Neither is theoretical for this task: the whole point of C-1's fix is that stray
env-shaped files at the repo root are the expected failure.

**Recommendation.**

- Strengthen (e): assert **no `*.dockerignore` sits beside either Dockerfile**, and
  assert **neither Dockerfile contains a `COPY`/`ADD` whose source is `.`, `./` or a
  path that spans the whole context**. The second half is the control `.dockerignore`
  is the backstop *for*; asserting only the backstop is assert-shaped.
- Architect action: widen `.dockerignore` and `.gitignore` to `.env*` with
  `!.env.example`. Safe — nothing `COPY`s `.env.example`, and the compose overlay
  mounts it from the host, not the context.
- **On ownership:** you asked whether `.dockerignore` should move into `infra`.
  **Yes, and I would take that decision.** It is not a neutral hygiene file; its own
  header calls it "the structural guard behind *never baked into an image layer* in
  `.claude/projects/04-infra-rulebook.md`". A security control for a zone, whose
  sentinel test lives in that zone, whose failure mode is that zone's rulebook trap,
  but which that zone's developer must escalate to edit, is an ownership boundary
  that will be crossed under time pressure. `.gitignore` I would leave where it is —
  it is genuinely cross-zone.

---

## Finding M-2: the guard's own pasted `mv` command leaves the secret group-writable — §5.2 and §9 disagree

- **Severity**: **medium**
- **Location**: spec §5.2, the message body:
  `move it once:   mkdir -p <dir> && mv .env <HASHI_ENV_FILE> && chmod 600 <HASHI_ENV_FILE>`
  versus spec §9:
  `mkdir -p ~/.config/hashi && chmod 700 ~/.config/hashi && mv .env … && chmod 600 …`

**Description.** §9's command is correct. **§5.2's is not** — it drops the
`chmod 700` on the directory. The two must be byte-identical, because the §5.2 one is
the one that gets pasted: it is printed at the exact moment the owner is stuck.

Why it matters concretely, using this machine's observed state:

- `/repo/.env` is mode **0664** and `.env.example` is 0664 — i.e. the owner's umask is
  **002**. That is not an accident, it is `make env`'s current `cp` at
  `Makefile:28` with no mode discipline.
- `mkdir -p ~/.config/hashi` under umask 002 creates the directory **0775 —
  group-writable**, and §5.2 never corrects it. Anyone in the owner's group can then
  rename or replace `hashi.env`: substitute a `HASHI_SECRET_KEY` of their choosing,
  or a `POSTGRES_PASSWORD` they know. That is a local integrity attack on the key
  that encrypts every node credential, introduced by the remediation.
- `mv` **preserves the source mode**, so the file arrives at the new path as 0664 and
  is world-readable until `chmod 600` runs. §9's ordering (`chmod 700` on the
  directory *before* the `mv`) closes that window completely, because nothing outside
  the owner can traverse into it regardless of the file's own mode. §5.2's ordering
  leaves the window open and the directory wrong forever.

**Risk.** The design's stated goal is that the secret ends up somewhere safer. Under
the §5.2 message it ends up somewhere with **weaker** permissions than it had
(0664 file in a 0755 repo, vs 0600 file in a 0775 group-writable directory that
anyone in the group can swap out).

**Recommendation.** Make §5.2's message character-for-character §9's command. State
in §5.2 that the directory `chmod 700` precedes the `mv` and that this ordering is
the control, not decoration. Pin it in §7 if you want it held.

**Related, §5.4:** "creates the parent directory … mode 0700; the file it creates is
`0600`" is right but does not say *how*. `cp` then `chmod` leaves the same
world-readable window (harmless there — the content is the template — but it is the
file the owner then fills in). Specify `(umask 077; mkdir -p …)` and
`install -m 600 .env.example $(HASHI_ENV_FILE)`, which has no window at all.
Note that `mkdir -p -m 700` applies the mode only to the **final** component, so an
existing `~/.config/hashi` at 0755 is left untouched — `make env` should chmod it
unconditionally.

---

## Finding M-3: the two-path `warden-down` / `warden-logs` fallback can act on a different compose project than the one that was started

- **Severity**: **medium**
- **Location**: spec §5.3; `Makefile:102`, `Makefile:127-128`, `Makefile:143-144`;
  `deploy/warden/docker-compose.yml:22` (`name: hashi-warden`).

**Description.** This answers review-task Q3 directly: **yes, mildly abusable, and
trivially fixable.** Q3's principle — never guard what stops things — is correct and I
endorse it without reservation. The implementation has a gap. §5.3 creates two
invocations that differ by whether `--env-file` is passed, and `--env-file` does not
only supply `${VAR}` interpolation: compose reads its **own** configuration variables
from it. `COMPOSE_PROJECT_NAME` takes precedence over the top-level `name:` attribute
at `docker-compose.yml:22`; `COMPOSE_FILE`, `COMPOSE_PROFILES` and `DOCKER_HOST` are
similarly honoured.

**Risk.** If the env file ever grows a `COMPOSE_PROJECT_NAME` (or the owner sets one
in his shell), `make warden-up` targets project X and the fallback path of
`make warden-down` targets `hashi-warden` — so **`warden-down` reports success and
stops nothing**, leaving the unattended agent container running with write access to
the tree. That is the precise failure Q3 exists to prevent, arriving through the
mechanism Q3 introduced. `DOCKER_HOST` is the sharper version: the two paths could
address different daemons.

`.env.example` defines no `COMPOSE_*` today, so this is latent, not live. But task 8
adds variables to `.env.example` and nothing forbids a `COMPOSE_*` among them.

**Recommendation.** Pin the project explicitly on the warden invocations —
`docker compose -p hashi-warden --env-file $(HASHI_ENV_FILE) -f …` — so both paths
provably address the same project. The repository already sets this precedent for
exactly this reason: `Makefile:156` pins `-p $(E2E_PROJECT)`, and `.e2e/profile.yml:38-39`
records why ("without it this collects logs from the dev project"). Optionally assert
in §7 that no `COMPOSE_*` or `DOCKER_HOST` variable appears in `.env.example`.

---

## Finding M-4: after the move, the owner can no longer stop or inspect the *product* stack — Q3's principle is applied to warden only

- **Severity**: **medium**
- **Location**: spec §5.2 last paragraph and §5.3 ("Do **not** generalise this
  fallback to the product stack"); `Makefile:84-91` (`down`, `logs`, `ps`),
  `Makefile:163-164` (`e2e-down`).

**Description.** Q3 argues, correctly, that an owner must always be able to stop and
look at what is running. That argument is applied to `warden-down`/`warden-logs` and
withheld from `down`, `logs`, `ps` and `e2e-down`, which after this change pass
`--env-file $(HASHI_ENV_FILE)` at a path that — in the single most likely post-landing
state, the un-migrated one — **does not exist**. Compose aborts with "env file not
found" and the owner cannot stop his database or read its logs, while his real `.env`
sits two directories away.

**Risk.** Availability, and the security-relevant kind: the operator loses `down` on
a live stack at the moment his configuration is in transition. §5.3's justification —
that task 8's `${VAR:?}` forms must abort — is sound as far as it goes, but
`docker compose down` evaluates those forms too, so after task 8 `make down` will
fail on a missing env file whether or not a fallback exists. The fallback is not what
makes `down` unsafe; the missing file is.

**Recommendation.** Do not extend the bare-compose fallback (§5.3 is right about
that). Instead, give the product-stack stop/inspect verbs the **same one-line
diagnostic** the warden fallback prints — name the path, name the `mv` — so the owner
gets the actionable message instead of compose's raw error. If C-1's recommendation
(2) is adopted, that diagnostic already exists and only needs wiring to four more
targets.

---

## Finding M-5: six architect-owned documents still point at the old location, and no task in the epic fixes them

- **Severity**: **medium**
- **Location**: `README.md:59`; `CLAUDE.md:70`; `CLAUDE.md:81`;
  `.claude/git-workflow.md:138`; `.claude/projects/03-security-checklist.md:83`;
  `.claude/projects/04-infra-rulebook.md:113` (and `:109`, which is **H-1**).

**Description.** You asked to be told if you had missed one of yours. You named
`README.md` and `CLAUDE.md`; here is the complete list I found, and the answer to the
question behind it — **no task in `xavier-epic-decomposition-directive-90be25f3-9.md`
covers any of them.** I grepped the decomposition for `README.md`, `CLAUDE.md`,
`HASHI_ENV_FILE` and the rulebook paths: the only hits are task 4 (`README.md`'s
verification table) and task 18 (an honesty sentence). Task 1 has already landed.
So these are flagged in your status file's `risks_escalated` and assigned to nobody.

- `CLAUDE.md:81` — "The fleet's git credential is `GH_TOKEN` in `.env`". `CLAUDE.md`
  is loaded into **every agent's context, including the unattended fleet inside the
  container**. After this task it tells every agent that the live credential is at a
  path inside its own read-write mount. Harmless in effect (the overlay masks it) but
  it is the single worst place in the repository to leave a pointer at a secret.
- `CLAUDE.md:70`, `README.md:59` — ports "driven from `.env`".
- `.claude/git-workflow.md:138` — "read out of `.env` into an agent's context".
- `03-security-checklist.md:83`, `04-infra-rulebook.md:113` — relocation is "a `.env`
  change plus a restore".

**Risk.** Documentation drift on a security control is how the control comes back
undone: the next reader reconciles the tree to the document rather than the other way
round. `CLAUDE.md` in particular is not documentation — it is the fleet's standing
instructions.

**Recommendation.** Land these in the same commit as this task, or open a task and
name it in the spec. Do not leave them as a status-file risk with no owner. Correcting
`CLAUDE.md:81` is one line and it is the one I would not defer.

---

## Finding L-1: `$HOME` is not a stable identity — `sudo`, a service user, or an empty `HOME` silently selects a different file

- **Severity**: low (**upgrade to high if C-1's fix is not taken**)
- **Location**: spec §5.1, §5.2 (`HASHI_ENV_FILE ?= $(HOME)/.config/hashi/hashi.env`).

You asked what `HASHI_ENV_FILE` becomes when `$HOME` is unset or empty, and whether
the guard still fails closed. Answers:

- **`HOME` unset/empty** → Make expands `$(HOME)` to the empty string →
  `/.config/hashi/hashi.env`. Still absolute, still outside the repo, and `test -f`
  is false — **the guard fails closed. That case holds.**
- **`sudo make up`** → `HOME=/root` → `/root/.config/hashi/hashi.env`, a *different*
  file from the owner's. Same for a systemd unit or a deploy user on the control-plane
  host, which is the machine the charter says must be relocatable in an afternoon.
- The failure is not the path — it is that in each of these cases the **unguarded**
  `env` prerequisite fabricates a placeholder file there and boots. That is C-1
  again, reached through a second door. With C-1 fixed, all three cases fail loudly
  and this is a documentation note.

**Recommendation.** Keep `$(HOME)` and `?=` — the reasoning in Q2 is right, and an
absolute host path in the repository would breach the infra rulebook's relocatability
trap. Add one line to the guard message and to `deploy/warden/README.md`: under
`sudo` or a service account, pass `HASHI_ENV_FILE=` explicitly.

---

## Finding L-2: S1 assertion (b) needs its `$HOME` semantics pinned

- **Severity**: low
- **Location**: spec §7(b) — "its default, after `$(HOME)`/`~` expansion, is an
  **absolute** path that is not inside the repository root".

You asked about a repository checked out **at** `$HOME`. In that case
`$HOME/.config/hashi/hashi.env` **is** inside the repository — S1 would fail, which
is the correct outcome, but the spec should say so rather than leave Potts to
discover it. Related: with `HOME` empty in the test process the expansion yields
`/.config/...` and the assertion passes for the wrong reason. A symlinked `~/.config`
pointing into the repo has the same effect and no static test can see it.

**Recommendation.** Pin in §7(b): resolve with `os.path.realpath` after expansion
(catches the symlink), and require the test to **fail explicitly** — not skip, not
pass vacuously — when `HOME` is empty or when `realpath(HOME) == realpath(repo_root)`.
Note in `deploy/warden/README.md` that a repo checked out at `$HOME` needs an explicit
`HASHI_ENV_FILE`.

---

## Finding L-3: nothing ever checks the mode of the file at the new location

- **Severity**: low
- **Location**: spec §5.2 ("checks only for the file's **existence** (`test -f`)"),
  §5.4; review-task Q2's sub-question.

You asked whether the mode of an *existing* file should be checked or enforced. My
answer: **checked and warned about, never silently enforced.** A guard that chmods a
file the owner did not ask it to touch is a surprising side effect on a live secret.
But `stat` reads metadata, not contents, so it is fully inside §0's prohibition, and
given that this machine's `.env` is 0664 and `mv` preserves mode (M-2), a 0664
`hashi.env` at the destination is the *expected* result of following §5.2's current
message.

**Recommendation.** In the guard, when the file exists and is group- or
world-readable, print one non-fatal line: the path, the observed mode, and
`chmod 600 <path>`. Never the contents, never a variable. Non-fatal, so it cannot
become a way to block `warden-down`.

---

## Finding L-4: S1 must be forbidden from asserting on the existence of a file at the repo root

- **Severity**: low
- **Location**: spec §7, "Forbidden inside this file, absolutely".

**Description.** The forbidden list bans reading `.env` but does not ban asserting
that `<repo>/.env` **does not exist** — the assertion a developer reaches for first
when writing a test called `test_warden_env_location`. It must be banned explicitly,
for two independent reasons:

1. **Inside the warden container — which is where `make test-infra` actually runs for
   the fleet — the overlay makes `/repo/.env` exist, always** (`docker-compose.yml:79`).
   The assertion is therefore permanently false there regardless of the host's state:
   it would report the defect as present on a correctly migrated machine.
2. On the owner's host the assertion is *about the real secret file*, which invites
   the next author to "improve" it by looking at what is in there.

The five authorised assertions (a)–(e) are all textual/structural and none does this
— the list is correct as written. The gap is that nothing forbids adding it.

**Recommendation.** Add to §7's forbidden list: "no assertion about the existence,
absence, mode or contents of any file at the repository root named `.env`". Note the
overlay's confounding effect in the module's WHY header — it is exactly the kind of
non-obvious decision `CLAUDE.md` asks to be explained where it is made.

---

## Finding I-1: the "known stale strings" list is incomplete — two more, both frozen

- **Severity**: info
- **Location**: `deploy/warden/warden.py:142`; `deploy/warden/docker-compose.yml:56`;
  (already known: `deploy/warden/entrypoint.sh:54`, Q11).

Q11 names one deliberately stale string. There are three:

- `warden.py:142` — "no docker socket, no route off the kaizen network, and
  `/repo/.env` masked by the template". Still true, but it is the file that states
  the container's security boundary and it now omits the boundary this task adds.
- `docker-compose.yml:56` — "`-` defaults keep the stack bootable from a bare `.env`".
  This sits in the `environment:` block, **outside** the `volumes:` block, so Q4's
  mechanical bound forbids fixing it in the same file whose comment Q4 fixes.

**This is the answer to review-task Q4/Q11's "defensible line, or inconsistency dressed
up as a principle?"** The *principle* you state — "only where the file describes the
control being changed" — is sound and I would apply it. The *bound* you actually
impose — "comment lines inside the `volumes:` block only" — is mechanical and does not
implement the principle: line 56 describes the control being changed at least as
directly as lines 66–78 do, and it is excluded purely by position. So it is not a
principle inconsistently applied; it is a principle replaced by a proxy at
enforcement time.

I do **not** ask you to widen it. A mechanically checkable bound on a frozen directory
is worth more than a judgement call an unattended developer has to make, and T2 is
reviewable. But the honesty ledger must be complete: report all three, not one, so
nobody later reads the single-item list as "everything else in `deploy/warden/` is
current".

---

## Finding I-2: `warden-scenarios` puts an admin token on a command-line assignment

- **Severity**: info — **pre-existing, out of scope, not this task's defect**
- **Location**: `Makefile:137`.

`TRACKER_ADMIN_TOKEN=$$(docker exec kaizen-tracker printenv TRACKER_ADMIN_TOKEN) $(PY) …`
places a live admin token in a process's `argv`-adjacent environment assignment, which
is readable via `/proc` by other users on the host for the process's lifetime. The
recipe is `@`-prefixed so Make does not echo it, and the comment at `Makefile:131-132`
is right that it never comes from `.env` — so this is not a leak-back path and not in
scope. Recording it so it is not rediscovered as new. A future task should pipe it on
stdin, the way `entrypoint.sh:45` correctly does with `GH_TOKEN`.

---

## 2. Direct answers to the eight axes

**1 — Does it remove the secret from every mount, or move the symptom?**
**It holds, for the mounts.** I enumerated the host-side paths myself from
`deploy/warden/docker-compose.yml`: `../..:/repo` rw (line 65), `../../.env.example:/repo/.env:ro`
(line 79), the named volume `hashi-warden-state:/state` (line 82), and `build.context: ../..`
(line 28). Potts has added nothing yet. There is **no docker socket mount**, so the
container cannot read named volumes or `docker cp` out of other containers — worth
recording as a real part of the boundary. `~/.config/hashi/hashi.env` is under none of
the four. `.git/` is inside the mount but `git log --all -- .env` is empty and `.env` is
untracked, so history holds no copy.
It is nevertheless **not** merely a symptom move: what changes is the file's
*canonical* location, which is what every document, habit and future tool follows.
That is the right control. **But C-1 means the design ships a documented command that
recreates the two-file state and switches the guard off, so in practice the symptom
can outlive the fix.**

**2 — The build context.** Holds today, via two independent controls; both stated as
checked facts in M-1. The root `.dockerignore` **does** apply to `context: ../..`.
Reliance on it is load-bearing and only half-asserted — (e) is a genuine sentinel over
the file's *content* but blind to a `Dockerfile.dockerignore` override and to a future
`COPY . .`. See **M-1**.

**3 — Leak-back paths.** Enumerated in full: `make env` (**C-1**, the worst),
`.env.example:1` and the seven `deploy/docker-compose.yml` messages (Q10 fixes them,
**H-2** notes nothing holds them), `.claude/projects/04-infra-rulebook.md:109`
(**H-1**, unfixed and feeding task 8), `README.md`/`CLAUDE.md`/`git-workflow.md`/
`03-security-checklist.md`/`04-infra-rulebook.md:113` (**M-5**, unassigned).
`.github/workflows/ci.yml` is **clean** — it runs `make setup` and `make test-<zone>`
only; no target it invokes has the `env` prerequisite, so CI creates no env file and
`docs/tracker/notifications.log` (which `scripts/notify.sh` commits into the repo)
receives only the §9 message, which contains a path and no value. No script under
`scripts/` writes an env file.

**4 — Can the loud failure print a secret VALUE?** **No, as specified — this holds.**
The guard is `test -f` plus an echo of `$(HASHI_ENV_FILE)` and its directory; it never
`source`s, `cat`s, `grep`s or `export`s; it fires before `docker compose`, so compose's
own error never appears on the guarded verbs. On the *unguarded* verbs compose does
error, but its "env file not found" names the path only, not contents. Make does not
run recipes under `set -x`; require the `@` prefix as `need_venv` does at
`Makefile:31-33` so the recipe line itself is not echoed. **I agree with you that
printing the path is acceptable** — the message is useless without it, and a path is
not a credential; note only that an owner passing `HASHI_ENV_FILE=` on the command line
puts that path in his shell history and in `ps`. `warden-logs` without an env file
prints nothing extra beyond §5.3's one line (see **M-3** for the project-identity
caveat).

**5 — File permissions at the new location.** **Partially holds.** §5.4 pins 0700/0600
for `make env` — good — but specifies no mechanism, so a `cp`-then-`chmod` leaves a
window and `mkdir -p -m 700` will not fix an existing directory. §5.2's message —
the one that is actually pasted — **does not pin the directory mode at all** and,
under the owner's observed umask 002, produces a group-writable directory and a
0664 file. See **M-2**. This is the one place where the remediation makes permissions
worse than they were.

**6 — Q1's widening.** **Necessary, and you read S1 correctly.** S1 says *«файл
окружения с настоящими секретами не находится ни под одним из них»*; `/repo/.env`
carries `HASHI_SECRET_KEY`, `POSTGRES_PASSWORD` and `GH_TOKEN`, and it is under
`../..:/repo`. A warden-only env file leaves all three there and fails the criterion
as frozen. Narrowing would have been the wrong call and you did not make it.
**And yes, it introduces a security regression of its own** — the one you suspected,
worse than you framed it. It is not "an owner who half-migrates ends up with two
files"; it is **`make up` producing the two-file state with no user error at all, and
booting the stack on `.env.example`'s published placeholder secrets**. That is **C-1**,
and it is the reason this review is not clean.

**7 — Keeping the `.env.example:/repo/.env:ro` overlay.** **Keeping it is right. Do
not remove it.** Your Q5 reasoning is sound in both directions and I endorse it,
including the honest limits. A fake `.env` inside the container does not create a
worse failure mode: it is `:ro`, so an agent cannot "fix" it; the values are visibly
placeholders, so the worst outcome is a confused agent, not a leak; and after C-1's fix
it is the only thing still masking a `.env` that reappears. Removing it would trade a
working control for tidiness. One condition attaches: **L-4** — because the overlay
makes `/repo/.env` exist inside the container unconditionally, S1 must be explicitly
forbidden from asserting on that file's presence, or the fleet's own `make test-infra`
will report the wrong answer.

**8 — Honesty.** **Holds, unhedged.** §1 lines 46–49 ("*This task does not remove the
risk on its own… do not describe the risk as closed*"), §9's heading, §12.7, §8's
verbatim sentence and the outright ban on "green" in connection with S2 are as clear
as I would write them, and the §9 notification carries the same sentence to the owner
at landing rather than at the stage report. No paper is placed over anything. Two
small gaps: nothing requires the residual risk in `status/dev-potts.yml` — the file
the Hub and the panel read, and the one that signals "done" — and nothing ever checks
whether the owner actually performed the `mv`. C-1's recommendation (2) supplies the
second for one line of shell.

---

## 3. Answers to the remaining questions in the review task

- **§3.6 / Q2 — better default?** No. `$(HOME)/.config/hashi/hashi.env` with `?=` is
  right: XDG-conventional, outside every mount and the context, overridable, no
  absolute host path in the repository, and the `hashi.env` (non-hidden, project-named)
  reasoning is good — a stray copy back into the repo *does* look wrong. `HASHI_ENV_FILE`
  over `ENV_FILE` is right for the shadowing reason you give. Mode of an existing file:
  warn, never enforce — **L-3**.
- **§3.6 / Q3 — is the unguarded path abusable?** Mildly, and fixably: not through the
  guard, through **compose project identity** — **M-3**. The principle is right.
- **§3.6 / Q4 & Q11 — defensible, or inconsistency dressed as principle?** The
  principle is defensible; the bound you enforce is a mechanical proxy that does not
  implement it (`docker-compose.yml:56`). Keep the bound — it is checkable, and on a
  frozen directory that is worth more than judgement. Fix the ledger: **I-1**.
- **§3.7 — the scenario.** Assertions (a)–(e) stay inside the authorised list: nothing
  imports, subprocesses or starts anything under `deploy/warden/`, nothing reads a real
  env file, nothing asserts on the diff (T2 is correctly named a review gate in §7).
  Gaps: (b) needs its `$HOME` semantics pinned (**L-2**); the forbidden list needs the
  repo-root-`.env` ban (**L-4**); (e) is assert-shaped over half its control (**M-1**);
  and the leak-back corrections have no sentinel at all (**H-2**). On **(d)**: it is a
  genuine sentinel, not a test that passes on a broken tree — it names a specific
  source→target→`ro` triple in a file whose non-comment lines T2 freezes, so it goes
  red the moment the line is removed or retargeted. It is the strongest of the five.
  Red-first proof for (a)–(e) is correctly required and I would refuse the hand-over
  without it.
- **§4 — is the out-of-scope list hiding the actual control?** No, and my own grep
  incident (§0) is the evidence: the strongest available control given `Bash` + a
  read-write `/repo` is to stop having the secret there, which is what this task does.
  Privilege separation inside the container and narrowing `../..:/repo` are the two
  larger controls and both are correctly frozen elsewhere. `deploy/warden/Dockerfile:20`
  (`FROM python:3.14-slim`, unpinned) I confirm as **known**, task 16's, not new —
  though I will note that an unpinned base image in the container that holds the
  fleet's `GH_TOKEN` is a supply-chain path into this repository, and task 16 should not
  slip.

---

## 4. Blockers and follow-ups

| # | Severity | Blocker for this task? | Owner |
|---|---|---|---|
| C-1 | critical | **yes — design returns to architect** | Xavier (spec §5.2/§5.4), then Potts |
| H-1 | high | yes — land with this task | Xavier (`.claude/**`) |
| H-2 | high | yes — extend §7 before implementation | Xavier |
| M-1 | medium | partly — (e) hardening before implementation; `.dockerignore` widening is architect follow-up | Xavier |
| M-2 | medium | **yes** — one-line spec correction | Xavier (spec §5.2) |
| M-3 | medium | yes — cheap, and it is in the recipe Potts is about to write | Xavier / Potts |
| M-4 | medium | no — follow-up, but before task 8 | Xavier |
| M-5 | medium | no — architect follow-up, needs an owner | Xavier |
| L-1…L-4 | low | no | Xavier |
| I-1, I-2 | info | no — report completeness only | Potts's hand-over |

---

## 5. The verdict, as its own line

**After this change and after the owner's `mv`: NO — no file carrying real secrets is
under any path mounted into the agent container**, provided all four of the following
hold, none of which the design currently asserts: (i) the repository root is not
`$HOME`; (ii) no `.env.bak`, `.env.local`, editor swap file or second checkout is left
in the tree (`.dockerignore` and `.gitignore` exclude `.env`, not `.env*`); (iii) no
hardlink inside the repository points at the new file; (iv) git history holds no copy —
**verified clean today**.

**After this change and WITHOUT the owner's `mv`: YES — the secret is still in the
mount, and per finding C-1 the design contains a documented command (`make env`, and
`make up` which invokes it) that leaves it there permanently while switching off the
guard that was supposed to say so.**

---

**VERDICT: CRITICAL — finding C-1 is critical. The design returns to Charles Xavier
before implementation begins.** No other finding blocks on its own; H-1, H-2, M-2 and
M-3 should be folded into the same revision. The design's direction is right, the
frozen-criterion reading in Q1 is right, the honesty in §1/§8/§9 is right, and Q5's
decision to keep the overlay is right — the defect is that the remediation's own
documented commands can produce the state it exists to prevent.

*Sherlock Holmes — security review, phase 2. No file's contents were read except
`.env.example`; the one exception is disclosed in §0 in full.*
