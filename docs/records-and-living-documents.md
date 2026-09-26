# Records and living documents

**WHAT:** which files in this repository may be reworded and which may not, with
the test for a file that is not listed, and the commands that prove a record was
left alone.

**WHY:** this repository keeps two kinds of writing in the same directory tree. A
**living document** says what is true *now* — reword it and it gets truer. A
**record** says what happened, or what was said, *then* — reword it and it
becomes a lie about the past that nothing else can contradict, because the record
was the only witness. M29 (renaming the person who uses hashi from *friend* to
*user*, ~3650 occurrences across 239 files) is the first change large enough that
somebody will reach for `sed -i` over `docs/`, and that one command crosses this
line in every file at once. A second `sed` does not un-cross it: the words that
were there are gone from the working tree, and only `git show` remembers them.

**HOW:** find the file in the table. If it is not there, apply the test. If the
test does not settle it, treat it as a record and ask the owner — the cost of
leaving a living document stale for one milestone is a stale sentence; the cost
of the other mistake is permanent.

This file is not about M29. M29 is the milestone that forced it to be written
down, and the line binds every later bulk edit too.

---

## The test, for anything not in the table

> **Does this file say what is true now, or what was said and done then?**

"Then" wins ties. A file whose value is that a later reader can tell what a
person actually typed, saw or decided — a walk, an acceptance, a field
measurement, a decision journal row, a finished milestone — is a record, and its
words are evidence. Evidence is not improved by being brought up to date.

Two corollaries that are easy to get wrong:

- **A record can be wrong and stays wrong.** The way to correct a record is to
  add something new that says so — `docs/decisions.md` has done this repeatedly
  (see its rows marked *Correction to the row above*). Never by editing.
- **A living document can be old and still living.** Nobody has touched
  `docs/product/backlog.md` in weeks; its roadmap is still a statement about what
  is wanted now, so it moves. Its decision journal does not — one file, two
  classes, see below.

---

## The table

| Path | Class | What a rename may do to it |
|---|---|---|
| `docs/tracker/**` | **record** | nothing. Walks, acceptances, field proofs, outcomes, carry-overs and step notes are what an agent or the owner saw at the time. |
| `docs/decisions.md` — existing rows | **record** | nothing. The file is **append-only**; new rows at the bottom, existing ones untouched, exactly as its own header says. |
| `docs/PLAN.md` — every `## ✅` milestone | **record** | nothing. A completed milestone states what was found and what was shipped, in the words used then. |
| `docs/PLAN.md` — `## Decisions needed from you` | **record** | nothing. It is a question list with the owner's dated answers under it; rewording an answer falsifies what they were asked. Its decision 9 of 2026-09-08 is the one M29 reverses — see below. |
| `docs/PLAN.md` — `## Where the field run left the plan, 2026-09-09` | **record** | nothing. A dated retrospective. |
| `docs/PLAN.md` — every `## →` (open) milestone, and `## What this plan does not cover` | living | reword. Both are statements about work not yet done. |
| `docs/PLAN.md` — `## Where things stand` | living | reword. Classified here by the test, 2026-09-22: it says what is open *now* and is rewritten whenever that changes. See below. |
| `docs/product/charter.md` | living | reword, including the one-liner's *"~30–50 friends"* (owner-settled, 2026-09-22). The same sentence is copied into `project.json` and `deploy/warden/warden.py`; all three move together. |
| `docs/deploy/runbook.md` | living | reword. It is followed at 3am; it must match the panel the operator is looking at. |
| `docs/product/backlog.md` — everything above `## Журнал решений` | living | reword, ids included — they are the file's own *«изменяемое состояние»*. The one exception is an id that is also a heading in the frozen `research.md` §3; see below. Not on the owner's enumerated list; classified here by the test. |
| `docs/product/backlog.md` — `## Журнал решений` | **record** | nothing. A dated decision journal in the same `\| Дата \| Решение \| Причина \|` shape as `docs/decisions.md`, and the file's own header says its entries are *«реальная история решений … не переписаны задним числом»*. |
| `docs/security/threat-model.md` | living | reword the vocabulary. The *threats* are not this milestone's to restate. |
| `README.md`, `CLAUDE.md` | living | reword. `CLAUDE.md` is owner/architect territory: propose, do not help yourself. |
| `.claude/**` (workflow, rulebooks, invariants) | living | reword. These instruct the next agent, so a stale noun here reproduces itself in new code. Same owner/architect caveat. |
| `control/migrations/versions/*.py` — already applied | **record, in code** | nothing: not the file name, not the revision id, not the table and column names inside it. See below. |
| git history, commit messages, PR bodies | **record** | nothing, and rewriting published history is forbidden outright. |
| all other code, templates, tests, fixtures | living | reword. Test *names* included — a test is a statement about what the system does now. |

### The plan is half record and half living document, and not only at the ✅

The obvious half of `docs/PLAN.md` is the finished milestones. The half that gets
missed is the three sections after the last milestone: two of them are dated and
are record, one is not and moves. The clearest illustration of why is decision 9
of *Decisions needed from you*, answered by the owner on **2026-09-08** with
*"the panel says users; `friend` stays the word in the models, the services, the
API and the tests"* — the exact decision M29 reverses on the owner's instruction
of 2026-09-22. Reword it and the repository loses the fact that it was ever
decided the other way, which is the one thing a future reader most needs in order
not to decide it back. The reversal is recorded in `docs/decisions.md`; the
question and its original answer stay as they were typed.

The fourth section, `## Where things stand`, was in neither list until 2026-09-22
and is the one the test settles cleanly. It opens on a date — *"Run stopped by
the owner on 2026-09-16"* — which is what made it look like the dated pair above,
but a date at the top is not what makes a record: the section says which
milestones are open, which findings are unfixed and what the next person picks
up, and it is rewritten every time that changes. It is living, and it moves.

### The backlog is half record and half living document too, and for the same reason

`docs/product/backlog.md` was classified whole, and it is two documents in one
file. Everything above `## Журнал решений` — the roadmap tables, the statuses,
the per-item prose — says what is wanted now. The journal is a dated
`| Дата | Решение | Причина |` table, the same instrument as `docs/decisions.md`,
and the file's own header says in so many words that the entries above and below
it are the real history of decisions taken by a fleet composition that no longer
exists and were **not rewritten after the fact**. A journal row is a record; the
one dated `2026-08-01 (ohno-6)` contains the old word inside a recorded decision
and keeps it.

**An id in the `id` column moves, unless it is a key into the frozen research
document.** The backlog's own "Как читать этот файл" draws that line itself: the
ids, zones, dependencies and statuses here are *«изменяемое состояние»*, while
the goal and acceptance **text** in `docs/research/product-owner-ohno-4/research.md`
§3 is **frozen** and is the contract for what *done* means. So an id that is also
a heading in that frozen §3 is a key held at both ends, and rewording the end that
may move leaves the backlog pointing at an item that does not exist — worse than
the stale noun. That is *mention versus use*: a use of the word for the person who
uses hashi moves, a mention of something's name does not.

Exactly one id met that test in M29: **`control-node-and-friend-records`**
(item 7), which is the heading of `research.md` §3 item 7 at line 1026. It keeps
the old word. **`control-per-friend-tunnel-address`** (item 33) looked like the
same case and is not: it appears nowhere in `research.md`, because it is one of
the rows the backlog itself files under *«Заведено во время исполнения очереди»*
— raised during execution, after the frozen document was written, and referenced
by nothing else in the tree. It is ordinary mutable state, and it was renamed to
`control-per-user-tunnel-address`. The rule is the frozen counterpart, not the
`done` status and not the fact that something is written in code font.

**The Russian noun *друг* was left alone, and only part of it has a line-based
reason.** Two or three sites genuinely may not move: the milestone heading
`## M2 — «Я могу выдать другу ссылку и отобрать её»` is a verbatim quotation of the
frozen criterion at `research.md:382` and `:809`, the roadmap table above it carries
the same sentence in short form, and a word swap inside a quotation falsifies what
the contract says. The remaining ten or so are ordinary retrospective prose,
several of them in the very *«Заведено во время исполнения очереди»* section that
postdates the frozen document — and one of them, item 33's note, now reads
*"AmneziaWG как user-facing транспорт … для одного друга на узел"*, with the
English word swept and the Russian one beside it left. There is no record/living
argument for those ten. They were left because **the owner settled an English
word, and whether that decision reaches a second document's Russian vocabulary is
a question nobody has put to them.** Deciding it inside a step, in either
direction, would be a step deciding product vocabulary on its own initiative. It
is the owner's, and it is open.

### The one conflict, recorded rather than resolved

`docs/tracker/field-checklist.md` is 56 occurrences of *friend* inside a
never-touched path, and it is not really a record: it is an instrument the owner
carries to the two hosts and works through. The owner drew the line by **path**
(`docs/tracker/**`), so the path wins and the checklist keeps the old word. The
cost is real and is accepted knowingly: a checklist that says *friend* in front
of a panel that says *user*. Closing it means promoting the checklist out of
`docs/tracker/` into a living home, which is a decision for the owner and is not
M29's to take on the way past.

---

## What "never touched" does not forbid

It forbids **rewording, rewriting, deleting or re-dating what is already
written**. It does not forbid a milestone from **adding its own new files** under
`docs/tracker/<milestone>/` — walks, step notes, acceptance — because those are
new record, not altered record. So a verification that `docs/tracker/**` is
untouched must look for *removed and changed lines*, not for a changed directory.
The commands below do exactly that, which is why they are written out rather than
left to whoever runs the check.

Likewise `docs/decisions.md` legitimately shows up as *modified* in every such
diff: rows were appended. The check is that nothing was **removed**.

## Applied migrations are records

`control/migrations/versions/0001_initial_schema.py` creates a table called
`friends`. That statement is a record of what was actually run against every
deployed database, and the whole of Alembic's model depends on it staying true:

- rewording it makes a **fresh** database disagree with a **deployed** one, while
  both report the same revision — the worst shape a schema bug can take;
- the revision ids and file names are the chain itself, and renaming a link
  breaks `downgrade` for anybody already past it.

So the rename of the table is a **new** migration that alters `friends` to
`users`, on top of `0007`, reversible; the six older migrations that mention the
old word (`0001`, `0002`, `0003`, `0004`, `0006`, `0007`) keep every word they
have. Their comments and docstrings stay too — a comment inside a record is part
of the record, and a migration that says `friends` while its docstring says
`users` is harder to read, not easier.

---

## Proving it, by diff and not by intention

`<baseline>` is the commit the milestone branched from (for M29: `1b60280`). Run
these from the repository root before opening a bulk-rename step for review.

```sh
# 1. No line removed or changed in any record file. Both must print nothing.
git diff <baseline> -- docs/tracker/ | grep -E '^-[^-]'
git diff <baseline> -- docs/decisions.md | grep -E '^-[^-]'

# 2. The plan's record half is byte-identical. Must print nothing. The awk
#    turns the accumulator ON at a record heading and OFF at the next `## ` of
#    any kind, which is what lets one file be half record and half living.
SLICE='/^## /{k = /^## ✅|^## Decisions needed from you|^## Where the field run left the plan/} k'
diff <(git show <baseline>:docs/PLAN.md | awk "$SLICE") <(awk "$SLICE" docs/PLAN.md)

# 3. The backlog's decision journal is byte-identical. Must print nothing. Same
#    awk idiom, one heading, because the same file is half record and half not.
JOURNAL='/^## /{k = /^## Журнал решений/} k'
diff <(git show <baseline>:docs/product/backlog.md | awk "$JOURNAL") <(awk "$JOURNAL" docs/product/backlog.md)
```

Check 1 catches a `sed -i` that ran one directory too wide, and catches a deleted
record too — a removed file is all `-` lines. Check 2 catches the subtler one,
where the plan is a single file and only half of it may move: a diff of the file
would be noise, since the open milestones are *supposed* to change, so the record
half is sliced out of both revisions and compared on its own. Measured at M29's
baseline, that half is 26 sections and 151 of the file's 212 occurrences of the
old word — nearly three quarters of what a careless `sed` over `docs/PLAN.md`
would have changed.

Check 3 is check 2 again on a second file that turned out to have the same shape,
and it was added on 2026-09-22 when `docs/product/backlog.md` was split. One
heading, 1 of the file's 8 occurrences of the old word — small, and it is the
kind of row that only one person ever notices is missing.

All three pass trivially on a tree where nothing happened, which is the point —
run them at the start of a step as well, so a failure at the end is known to be
yours.
