# hashi — threat model for the security audit

<!--
WHAT: what the gray-box security audit is aimed at — the assets, the trust
      boundaries it must try to cross, and what it is NOT allowed to conclude
      anything about.
WHY:  `security.box: gray` in `aikit.yml` means the hunter is given partial
      knowledge instead of discovering the surface by poking at it. That
      knowledge has to be written down and approved, or "gray box" degrades into
      "whatever the agent happened to read", and a finding that leans on a
      premise nobody approved gets to block a release.
HOW:  §1 the assets, §2 the surfaces, §3 the boundaries that must hold, §4 what
      is out of scope and why, §5 what a finding has to show.

STATUS: DRAFT — written by /aikit:init on 2026-09-22, NOT yet approved by the
        owner. `docs/security-audit.md` in the plugin requires this file to be
        owner-approved before a gray-box hunt; until the owner replaces this line
        with an approval, a finding that rests on §3 is a ranked line, not a
        blocker.
-->

## 1. What is worth protecting

Ordered by what it costs a real person, not by how interesting the bug is.

1. **The record of who connected to what.** The charter's position is that this
   record must not exist — no connection, traffic or DNS logs, at any level,
   including debug. So the asset here is an *absence*, and the finding class is
   "something writes it down after all". A request path containing a
   subscription token that lands in an access log is exactly this, and it is the
   highest-severity thing the audit can find: every other asset costs the owner
   money or time, this one can cost a friend their safety.
2. **Node credentials.** SSH keys and transport key material, held encrypted in
   the control plane's database (`control/app/crypto.py`). Reading them is full
   control of the fleet.
3. **Subscription tokens.** 32 bytes of urlsafe entropy, and the *only*
   authentication on `/sub/{token}`. A leak of one is one friend deanonymised to
   whoever holds it; a way to enumerate them is all of them.
4. **The operator session.** Cookie `hashi_operator`, signed, `SameSite=Lax`,
   `HttpOnly`, `Secure` whenever the deployment is https. It reaches every asset
   above.
5. **The fleet's own shape** — which addresses, which countries, which decoy
   destinations. Not secret from the owner's friends, but an enumerable fleet is
   a blockable fleet, which is the charter's whole threat.

## 2. The surfaces the hunter is told about

Four, and that is all of them. `control/app/main.py` mounts nothing else.

| Surface | Auth | Shape |
|---|---|---|
| `/panel/login` (GET, POST) | none — it is the door | HTML form: `username`, `password` |
| `/panel/**` | operator session, as a **router-level** dependency | HTML + HTMX; POSTs mutate |
| `/api/**` | operator session, same cookie, router-level | JSON |
| `/sub/{token}` | the token in the path, nothing else | base64 document or a ZIP of config files |
| `/healthz`, `/`, `/robots.txt` | none | fixed responses; `/` redirects to the login page |

Two things worth knowing that a black-box run would spend budget learning:

- Auth is attached to the **router**, not to each handler, on purpose: a route
  added to a guarded router inherits the guard. A route that turns out NOT to
  inherit it is therefore a finding about the wiring, not about one handler.
- There is **no CSRF token**. Cross-site protection on the panel's mutating
  routes is `SameSite=Lax` alone. Whether that is sufficient depends on no
  mutating route answering a top-level `GET` — which is the thing to test, not
  to assume.

## 3. The boundaries that must hold

A crossing of any of these is a finding. This is the list the audit is for.

1. **anon → operator.** No `/panel/**` or `/api/**` route answers anything but a
   401 or a redirect to the login page without a valid session. Fail closed: a
   malformed, expired or wrong-key-signed cookie denies, never falls through.
2. **friend A → friend B.** Holding A's token yields A's configuration and
   nothing of B's — not B's entries, not B's nickname, not the fact that B
   exists.
3. **token holder → the fleet.** `/sub/{token}` tells its holder about their own
   entries and nothing more: no node count, no country, no other person, and no
   statement about whether this token ever existed.
4. **revoked → unknown.** A revoked token's answer is indistinguishable from a
   token that was never issued. Distinguishing them turns a revocation into a
   confirmation that someone was once a user.
5. **the token stays out of every record.** No log line, error body, redirect
   `Location`, referrer, template or stack trace carries a `/sub/` path or a
   token. Access logging is off in uvicorn and discarded in Caddy; a new place
   that records a path is a finding even if nothing is misconfigured today.
6. **the operator cannot be impersonated by a forged session.** The cookie is
   signed with a key derived from `HASHI_SECRET_KEY`; a session accepted without
   that key is critical.

## 4. Out of scope, and why

Named here so a "could not reach" line is a known boundary and not a gap.

- **The nodes.** The stand has none — no real host, no SSH, no running
  transport. Everything about what a node does with a config it was given is a
  field question (`make verify` cannot answer it either; see `CLAUDE.md`).
- **The data plane.** Tunnel crypto is upstream binaries' (`xray`, `amneziawg`);
  this project renders their configuration and does not implement their
  protocols. A weakness in one is an upstream advisory, which is `security.scan`'s
  job, not the hunter's.
- **Denial of service.** Deliberately. There is no login lockout and that is a
  recorded decision, not an oversight: with a single operator and a slow KDF, a
  lockout is a denial of service against the one person who needs the panel
  during an emergency rotation (`control/app/auth.py`). Do not file it again.
- **The charter's first success criterion** — surviving a mobile whitelist
  shutdown. A field observation on a real Russian network; no audit of a
  loopback stand can speak to it.
- **The owner's own machine.** The fence in `bin/probe` allows one origin, the
  stand's. That is not a promise in a prompt; it is a target the tool will not
  send to.

## 5. What a finding has to show

The same bar the plugin's gate enforces, restated here because it is the reason
this file is short: a finding is paid for with a transcript a second agent
replays against a stand it did not build. For the boundaries in §3 that means

- for §3.2 and §3.3, the **truth source** confirming the row really belonged to
  the other person — `scripts/acceptance/query.py`, the read-only role the audit reuses. A screen
  showing B's nickname is not proof that it came from B's record;
- for §3.4 and §3.5, a **pair** of transcripts whose difference is the whole
  finding: revoked vs never-issued, or the same request with and without the
  token in the path.

An "it looks like" with no transcript is not a finding. It is a line in the
"could not reach" block, which is mandatory and is where honest uncertainty goes.
