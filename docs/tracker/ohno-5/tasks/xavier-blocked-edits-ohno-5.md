# Blocked edits — the §7 corrections I own, ready to apply

**From:** Charles Xavier (architect)
**To:** the project owner
**Task:** `ohno-5`
**Date:** 2026-08-01
**Status:** written, **not applied** — `.claude/**` is write-protected in this
session and I cannot self-authorise. Every tool and every path under `.claude/`
is refused, so this is not a tool quirk and not something I will route around
with a shell command.

These are the corrections recorded as mine in §7.2, §7.3 and §7.7 of
`docs/tracker/product-owner-ohno-4/tasks/xavier-review-ohno-product-owner-ohno-4.md`,
resolved to final text. Nothing below needs a decision — applying it is
mechanical. Anchors are quoted verbatim from the files at commit `b48ef90`.

Item D is **not** one of the three; it is the same drift in a fourth document of
mine, flagged rather than assumed.

---

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

## C — `.claude/workflow.md` — N2, the `origin` drift

Verified against the tree at `b48ef90`: `origin` is
`https://github.com/earlzdev/Hashi.git`; the only remote branch is
`remotes/origin/main`; `main` tracks it; `develop` exists locally only.

Replace rules 1–4 of *Iron rules (no exceptions)*:

```
1. Agents **never** push, merge or open PRs targeting `main`.
2. Agents **never** run `git revert`, in any branch.
3. All PRs target `develop`.
4. Before starting a task, sync the integration branch:
   ```bash
   git checkout develop && git pull origin develop && git merge origin/main --no-edit
   ```
   **This repository has no `origin` yet.** Until one exists, the local
   equivalent is `git checkout develop && git merge main --no-edit` — and if you
   skip it you will branch from a tree missing everything merged since.
```

with:

```
1. Agents **never** push, merge or open PRs targeting `main`. `main` is the
   branch this repository publishes from, and releasing into it is a human
   action — read *What `origin` actually is* below before taking this as a
   contradiction.
2. Agents **never** run `git revert`, in any branch.
3. All PRs target `develop`.
4. Before starting a task, sync the integration branch:
   ```bash
   git checkout develop && git merge main --no-edit
   ```
   Skip it and you branch from a tree missing everything merged since. If you
   want the remote's state first, fast-forward `main` and nothing else:
   `git fetch origin && git checkout main && git merge --ff-only origin/main`.

### What `origin` actually is

Stated plainly, because two of the rules above read wrongly without it:

- `origin` **exists** and is a GitHub remote. It carries **one branch, `main`**,
  and local `main` is what tracks it.
- `develop` is **local only**. There is no `origin/develop`, so
  `git pull origin develop` fails outright and `gh pr create --base develop` has
  nothing to target. That is why rule 4 is a local merge and not a pull.
- Rule 1 is not contradicted by `main` being the published branch. The owner
  published it; an agent may not. Pushing anything is on the charter's
  always-ask list (`docs/product/charter.md`, Autonomy), so **no agent pushes any
  branch — `develop` included — without the owner saying so for that task.**

Until the owner publishes `develop` and authorises pushing, the flow ends where
`.claude/git-workflow.md` says it does for a project with no usable PR target:
work stays on a local task branch, and completion reports **which files changed**
instead of a PR link. Do not create the branch on the remote to "finish
properly".
```

---

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

*Charles Xavier — architect. Nothing here is dispatched and nothing here is a
spec. Applying A, B and C is what leaves M1 item 1 with zero open architect
questions.*
