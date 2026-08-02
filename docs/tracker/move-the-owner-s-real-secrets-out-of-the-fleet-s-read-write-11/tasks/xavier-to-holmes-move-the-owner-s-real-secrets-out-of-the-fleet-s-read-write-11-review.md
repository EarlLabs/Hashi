# Security review — move the owner's real secrets out of the fleet's read-write mount

**From:** Charles Xavier (architect)
**To:** Sherlock Holmes (`security-holmes`)
**Task:** `move-the-owner-s-real-secrets-out-of-the-fleet-s-read-write-11` —
task 2 of 18 of epic `directive-90be25f3-9`
**Zone under review:** `infra`
**Verify command:** `make test-infra`

---

## 0. Why this review is the substantive gate

**This task is not a feature with a security angle. It is a security control.**
Everything else in this epic is reviewed for whether it broke something; this one
is reviewed for whether it actually does the thing it exists to do. If the design
merely relocates the symptom, a clean review here is worse than no review,
because the item will be marked done and the owner will believe the secret is out
of the mount when it is not.

Please treat "the design is fine" as a claim that has to survive an attempt to
break it, not as a default.

---

## 1. The prohibition, binding on you too

**Do not read, print, `cat`, `head`, `grep`, copy, move or delete `/repo/.env`.**
Do not run any command that could print its contents, and do not run `git diff` in
a way that would. `test -f .env` is allowed; its contents are not. `.env.example`
is the only env file anyone on this task may read.

If your review needs to establish something about the real file's contents, that
is itself a finding — say so instead of looking.

---

## 2. What to review

- The spec:
  `docs/tracker/move-the-owner-s-real-secrets-out-of-the-fleet-s-read-write-11/tasks/xavier-to-potts-move-the-owner-s-real-secrets-out-of-the-fleet-s-read-write-11.md`
  — §3 (*Questions and defaults in force*) is where every judgement call is
  recorded. Attack the defaults, not just the code.
- Pepper Potts's implementation on branch
  `task/2-env-out-of-warden-mount-directive-90be25f3-9`: `Makefile`,
  `deploy/warden/docker-compose.yml`, `deploy/warden/README.md`,
  `deploy/docker-compose.yml`, `deploy/AGENTS.md`, `.env.example`,
  `.e2e/profile.yml`, `tests/infra/test_warden_env_location.py`.
- The frozen acceptance text: `docs/research/product-owner-ohno-4/research.md`
  §3, item `0. infra-env-out-of-warden-mount` (around line 523), and lines 42–51
  and 555–559 of the same file.

---

## 3. The questions I want answered

### 3.1 Does this actually remove the secret from every mount, or only move the symptom?

Enumerate, yourself, from the compose file — do not take the spec's list on
trust — **every** host path that reaches the agent container:

- `../..:/repo`, read-write;
- `../../.env.example:/repo/.env:ro`;
- the named volume `hashi-warden-state:/state`;
- `build.context: ../..`, which is not a mount but is a copy of the tree sent to
  the daemon;
- anything Potts added.

Then answer: after this change, is `$(HASHI_ENV_FILE)`'s default
(`$(HOME)/.config/hashi/hashi.env`) reachable from inside the container by **any**
of them? Consider the awkward cases: a repository checked out under `$HOME` such
that `~/.config` is *not* under the repo but the repo is under `$HOME` (fine), a
repository checked out **at** `$HOME` (is it?), a symlinked `~/.config`, a
symlink or hardlink left inside the repo pointing at the new location, and
`$HOME` being unset or empty when Make expands it — what does
`HASHI_ENV_FILE` become then, and does the guard still fail closed?

### 3.2 Can the file come back in?

This is the failure I expect, if there is one. Look for every path by which a file
carrying real secrets ends up inside the repository again:

- any Make recipe that writes, copies or creates `.env` at the repo root —
  `make env` above all (spec §5.4);
- any *documented instruction* that tells the owner to create `.env` in the repo:
  the `${VAR:?set VAR in .env}` messages in `deploy/docker-compose.yml`
  (spec Q10), `deploy/AGENTS.md:32`, `.e2e/profile.yml:44`,
  `deploy/warden/README.md`, `.env.example`'s header, and the two files I own and
  Potts may not touch — root `README.md:59` and `CLAUDE.md`. **Tell me if I have
  missed one of mine**; an instruction that reintroduces the defect is a finding
  wherever it lives.
- a fallback in the Makefile that silently re-reads `./.env` if
  `$(HASHI_ENV_FILE)` is absent. There must be none. Spec §5.3 authorises a
  bare-compose fallback for `warden-down` and `warden-logs` only — check that it
  does not read a repo-root file, and that it did not leak into any other verb.

### 3.3 The build context — the one I most want a second pair of eyes on

`build.context: ../..` sends the entire repository to the Docker daemon. Today
`.dockerignore:10` excludes `.env`, `*.key`, `*.pem` and `secrets/`, and the
warden `Dockerfile` copies only three named paths — no `COPY . .`. So the context
looks safe.

Confirm it, and then answer the harder questions:

- Does `.dockerignore` at the **repo root** actually apply to a build whose
  context is `../..` from `deploy/warden/`? (I believe yes — the context root's
  file is used — but I want it stated as a checked fact, not an assumption.)
- Is the S1 assertion (e) in spec §7 a sufficient sentinel over that control, or
  is it assert-shaped without being load-bearing?
- `.dockerignore` belongs to **no zone**, so Potts may not edit it. Is that the
  right ownership for a file that is a security control for this zone? If you
  think it should move into `infra`, say so — that is an architect decision and I
  will take it.
- Anything else that leaves the host with a copy of the tree: a build cache, the
  daemon's context tarball, `docker cp`, a bind mount added later.

### 3.4 Could the loud failure print a secret?

The guard (spec §5.2) is the new code path that runs precisely when something is
wrong, which is when people paste output into chats and issues. Check that it:

- prints the **path** and nothing read from the file;
- never `source`s, `cat`s, `grep`s or `export`s the env file;
- does not echo an environment variable that could hold a value from it;
- fires **before** `docker compose` runs, so compose's own error (which can name
  file contents in some versions) never appears;
- behaves the same when `HASHI_ENV_FILE` is overridden to a path the owner does
  not want in a transcript — the path is printed, which I consider acceptable;
  tell me if you disagree.

Also check the two unguarded verbs: does `warden-logs` without an env file print
anything it would not print with one?

### 3.5 Is the residual risk stated honestly, or papered over?

**The task does not close the risk. The owner's `mv` does.** Until he runs it, the
real `.env` is still inside the read-write mount. Check that this is stated —
without hedging, without "largely mitigated" — in:

- Potts's hand-over report;
- the `scripts/notify.sh` message (spec §9), which the frozen intent requires to
  be sent **the moment this lands**, not batched into the stage report;
- `deploy/warden/README.md`.

And check the S2 reporting: the frozen honesty rule requires the verbatim sentence
in spec §8 and forbids the word "green" in connection with S2. A report that
quietly implies the stack was proven to start is a finding.

### 3.6 The judgement calls in spec §3 — attack them

I answered eleven questions myself, unattended, with the most conservative option
I could find. Each is a place where I could be wrong:

- **Q1** — I read S1 as requiring the *whole* project env file to move, not just a
  warden-specific one, because `.env` holds `HASHI_SECRET_KEY` and
  `POSTGRES_PASSWORD`. That widens the change to the product-stack targets. Is
  the wider change correct, and did I trade one risk for a worse one?
- **Q3** — `warden-down` and `warden-logs` are deliberately **not** guarded, so an
  owner can always stop an unattended agent container. Is the unguarded path
  abusable? Could a missing env file plus the bare-compose fallback tear down the
  wrong project, or act on a different compose project than intended?
- **Q5** — I kept the `.env.example:/repo/.env:ro` overlay and argued it is a real
  mitigation but **not sufficient for S1**, because S1 is about where the file
  lives and the overlay is about what one container sees. Is that reasoning
  sound, and is keeping the overlay right? If you think removing it is safer,
  make the argument.
- **Q4 / Q11** — I authorised exactly two edits under `deploy/warden/` (the
  `volumes:` comment and the README) and refused a third
  (`entrypoint.sh:54`), on the line "only where the file describes the control
  being changed or a start procedure that would otherwise be wrong". Is that line
  defensible, or is it an inconsistency dressed up as a principle?
- **Q2** — `$(HOME)/.config/hashi/hashi.env`, `?=`, overridable. Better default?
  Should the *file mode* of an existing file be checked or enforced anywhere?

### 3.7 The scenario itself

- Does `tests/infra/test_warden_env_location.py` assert on anything outside the
  authorised list in spec §7? In particular: does it import or execute anything
  under `deploy/warden/`, read any real env file, start anything, or assert on
  the diff?
- Does it *fail* when the control is removed? Ask Potts for the red-first record
  and check that the assertion that went red is the one that should have.
- Is (d) — asserting the overlay is still mounted — a genuine sentinel or a test
  that would pass on a broken tree?

---

## 4. What is deliberately out of scope, and why — challenge these only if you think they are wrong

- **Privilege separation inside the container** — frozen out of scope for item
  `0` by the Product Owner (`research.md` §3, item `0`, *Вне области*).
- **Tests exercising warden's runtime or Python** — same frozen line, and the
  fleet-tooling freeze.
- **Narrowing the `../..:/repo` read-write mount** — that mount is the fleet's
  job; changing it is a different, unapproved task.
- **Pinning `deploy/warden/Dockerfile:20`** — task 16 leaves that floating tag
  deliberately under the freeze. If you find it, note it as known, not new.

If you believe any of these is the *actual* control and the one we built is
theatre, say so in the report — I would rather carry that finding to the Product
Owner than ship a comfortable one.

---

## 5. Output

Findings by severity, each with the file and line, the concrete failure scenario
(inputs/state → what leaks or breaks), and whether it is a **blocker** for this
task or a follow-up for the architect. Write to
`docs/tracker/move-the-owner-s-real-secrets-out-of-the-fleet-s-read-write-11/tasks/holmes-security-review-move-the-owner-s-real-secrets-out-of-the-fleet-s-read-write-11.md`.

State explicitly, as its own line, your verdict on the one question the owner will
actually ask: **after this change and after the owner's `mv`, is a file carrying
real secrets under any path mounted into the agent container — yes or no?**
