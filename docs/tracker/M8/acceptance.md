# M8 — acceptance, and two rounds lost to the orchestrator

**Rounds used: 3 of 3, and two of them were lost to my own process errors, not to
the product.** Recorded here rather than buried, because the point of this file
is to keep score honestly.

| round | outcome | why |
|---|---|---|
| 1 | **blocked** — one real defect | The back button stripped the console of all styling. A genuine product failure, found by pressing Back, which nothing in 801 tests does. |
| 2 | verdict `good`, **run voided** | I committed `docs/decisions.md` while the walk was in progress. The tree fingerprint moved and the gate voided the run — correctly. It cannot tell my docs commit from an agent patching the code it is judging, and it must not be able to. |
| 3 | **blocked** — could not check | I archived the captures and re-fingerprinted, but **never rebuilt the stand**, so round 2's three users were still in it. The scenario's first move is "judge it empty"; I made that impossible, and checklist line 5 went unverified. |

**The same class of error three times in one night**: writing to a shared
repository, or leaving shared state dirty, while an agent works in it. Earlier it
swept an implementer's in-progress file into a commit of mine, and an
implementer's history rewrite dropped a commit of mine. Here it cost a full
acceptance round and then a second one.

**What the product actually earned.** Across rounds 2 and 3, independently and
without the diff: no broken behaviour, nothing that lies, and **seven findings
confirmed fixed** including round 1's blocker. Both rounds verified, with
evidence, that nothing is measured (the schema holds no bytes, sessions,
last-seen, load or throughput column anywhere), that nothing is fetched from
outside (88 requests, every off-host one hard-aborted, **zero blocked**), and
that the bearer credential reaches neither the address bar, nor an attribute, nor
`localStorage`, `sessionStorage` or `document.cookie`.

## Findings the owner should see

Still open, all **clumsy**, none blocking:

- The link dialog prints and copies `http://localhost/sub/<token>` — no port — so
  "open it in another tab" fails when done literally. The token itself resolves
  `200` at the real endpoint. This is the stand's own `HASHI_PUBLIC_HOST`, not a
  product default; on a real deployment that value is the public name.
- The `active` status pill breaks mid-word into `activ / e` when a long nickname
  squeezes its column — **a regression from the fix for the long-nickname
  finding**, and the clearest reason acceptance re-runs whole rather than
  re-checking one point.
- A failure wears the same neutral banner as an ordinary notice, so what went
  wrong does not read as wrong.
- Switching screens shows no visible progress under latency — on the restricted
  network this console exists for, the owner will not know the click registered.
- A 5xx during add-user puts its explanation on the banner **behind** the modal.
- The Overview card silently shows five of seven users.
- The sidebar leaves a grey mark on the last-clicked entry, so two look selected.

Deferred deliberately, not defects: the old un-redesigned page, a dead band above
the heading below 900px, and layout escaping the viewport at 390px — outside this
milestone's stated 900px requirement.

## One rule violation, fixed rather than filed

The duplicate-name refusal said *"a **friend** called 'dima' already exists"*
while every other word on screen says "user". Decision 9 is explicit that no
`friend` → `user` rename travels past the rendered page — and this is the same
boundary in the other direction: the code's word leaking onto the page. Fixed.

---

## Round 4 — passed

**Verdict: good, gate exit 0.** No broken behaviour, nothing that lies. **All
eleven findings from earlier rounds confirmed fixed**, including round 1's
blocker. Spend: 80 actions of 220, ~22 minutes of 75.

Judged on a stand verified empty through the read-only role — `friends: 0`,
`nodes: 0`, `subscriptions: 0` — which is the precondition round 3 was denied.

**The empty state, the thing round 3 could not reach, passes.** Overview shows
four zeroed cards *and* "Nothing is configured yet" with the right first move
named: *"Start with a node. A user's subscription only ever resolves to nodes
that are serving, so adding a user first would hand them a link to nothing."*
Users has its own. Neither is a blank box.

**The render boundary proved itself exactly as designed:** the refusal now says
*"a user called 'dima' already exists"*, and a person actually nicknamed `friend`
is still refused **by their own name** — *"a user called 'friend' already
exists"*. Vocabulary translated, operator data not.

**Two clumsy findings remain for the owner**, in `acceptance-verdict.md`: a
failure still carries no error colour (it has its own treatment, but the rule is
the same slate as the primary button — only the wording says "wrong", and the old
page shows the palette has a danger hue available); and a revocation on one
device leaves another open session showing that row as `active` until a reload.

**A harness finding, worth its own note:** `scripts/acceptance/drive.py` pins the
viewport at 1440×900 and neither `begin` nor `open` takes a size, so the 900px
checklist line could not be walked with the supplied hands — the agent drove the
same installed browser directly instead. That is a gap in M12's instrument, not
in this milestone, and it means **the one checklist line about narrow windows
cannot currently be discharged by the tool the plan nominates for it.**
