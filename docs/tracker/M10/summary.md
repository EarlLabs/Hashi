# M10 — what landed

**Closed 2026-09-11.** Four steps, **10 review rounds**, acceptance **good on the
first round**. `make verify` green: 230 edge, 162 infra, 149 e2e, 508 control.

| step | rounds | what it was |
|---|---|---|
| M10.1 | 2 | the decision — what Settings may show, what the trail may record |
| M10.2 | 3 | Settings, read-only |
| M10.3 | 3 | the trail itself |
| M10.4 | 3 | the audit log screen |

## The milestone's own question, answered

M10's prose warned that an audit log is *"a new durable record naming friends and
times, sitting on the one machine most worth seizing"*, against a charter whose
argument is that such records are **absent, so there is nothing to subpoena**.

So the question was whether the trail makes the database a worse target. **It does
not, and that was checked rather than assumed.** `Friend` already carries
`created_at` and `revoked_at`, and nothing in the codebase deletes a friend or
renames a nickname — so the trail's entries about people duplicate facts the
inventory already holds. What it genuinely adds is a history of **operator
actions on surviving rows**: two rotations, a state that went active → degraded →
active. That is about nodes and transports, never about a person.

The acceptance walk pressed the other half: five subscription fetches, a bad
token, a short token, a fetch after revocation, a logout, a sign-in and a **failed**
sign-in — the audit count never moved.

## What was refused, and why

- **No operator source address.** An address against a time is the record the
  charter says is absent; and since the console moved behind the management
  tunnel the value is near-constant anyway.
- **No "last login."** It passes the letter of the cell test but fails what that
  test proxies for: it would be the only place in the codebase where a human
  merely being present writes a durable row.
- **No free-text or JSON column, ever.** The load-bearing rule. A blob is how a
  trail acquires a token in eighteen months without anyone deciding to. Enforced
  by a column whitelist proven to catch an appended `details`.
- **No reason on a row.** A refusal's text can come from a remote host. The
  consequence — the trail cannot tell an operator's state change from one the
  product made after a failure — is recorded as a decision rather than papered
  over.
- **`action` is an enum, and a label is EQUAL to an inventory value**, never
  composed. The 64-character guard is *not* what carries that: a composed
  `f"{node.name}: refused"` fits. The equality test is.

## Settings

Read-only, rendering the **live `Settings` object** — so it cannot show a stale
value, and a variable this process does not read has no attribute to render.
Secrets appear as the single word `configured` and in no other form, held by two
complementary sweeps: cell-equality, and a document-wide hunt over prefixes,
lengths and a digest under every algorithm `hashlib` guarantees, in **both** the
raw and unescaped page — the unescaped half is load-bearing, not belt-and-braces,
because Jinja autoescapes and a raw search walks past a secret containing `&`.

## Three things for the owner

- **You cannot currently change the retention window.**
  `HASHI_AUDIT_RETENTION_DAYS` is not passed into the container — one of five
  variables the panel names but compose never forwards. First on
  `infra-followup.md`, because it governs how long the only record naming friends
  is kept.
- **Three refusals were decided rather than asked** — the source column, last
  login, and the 30-day default. Each is reversible with one line and each is in
  the journal.
- The trail says **what** changed; the node row says **why**. A reader who wants
  both looks at both.
