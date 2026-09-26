# Core invariants — hashi

<!--
WHAT: The rules that hold everywhere in this repository, in every zone.
WHY:  personas describe the procedure; this file describes THIS project. An agent
      that follows the procedure and breaks these has still broken the project.
HOW:  every developer and reviewer pre-reads this file. Keep it short — a
      rulebook nobody finishes is a rulebook nobody follows.
-->

## 1. Architecture invariants

- **Nodes and transports are data, not code paths.** There is no
  `if provider == "..."`, no `if country == "..."`, no `if transport == "..."`
  anywhere outside a transport's own package. A new exit country is a row in the
  node registry; a new protocol is one new package under `edge/transports/`.
  *Why: the product promise is "swap a node or a protocol in minutes". Every
  branch on a specific node or protocol turns that into a code change and a
  deploy.*

- **The control plane never carries user traffic.** It stores state, renders
  configuration, and serves subscriptions. Tunnels terminate on nodes, in
  upstream software (Xray, AmneziaWG, WireGuard) that we configure and never
  reimplement.

- **Control flows one way: control plane → node, over SSH.** Nodes never dial the
  control plane, for anything, including health and metrics. The control plane
  polls.
  *Why: an outbound connection from a node to a fixed endpoint is both a
  fingerprint for a censor and a path back to the crown jewels if the node is
  seized. A node must be disposable without being trusted.*

- **`edge` is a pure library; `control` imports it, never the reverse.** Config
  rendering does no I/O: no database, no network, no clock, no filesystem. Given
  the same node record and parameters it returns the same bytes.
  *Why: rendering is the part that must be testable with golden files and
  reviewable as a diff. The moment it reads a database, drift becomes invisible.*

- **The subscription is the only contract with a user.** Any change to what a
  user connects to — new node, new protocol, rotated key, retired country — must
  be expressible as a new subscription render, with no action on their device.
  A feature that requires users to re-import a config has failed the charter.

## 2. Ownership

- Zones are defined in `.claude/workflow.md`. A developer edits only their zone.
- Cross-zone work is split into separate tasks — never shared files.
- **A transport lives entirely in `edge/transports/<name>/`.** Adding one must
  not touch another transport, the registry, the subscription renderer, or the
  control plane. If it does, the profile contract is wrong — raise it with the
  architect instead of reaching across.
- **Database schema changes go through Alembic migrations**, owned by `control`.
  *Why: this database holds node credentials and user identities that exist
  nowhere else. `create_all` on a changed model silently diverges from a live
  database, and the failure mode is "every user is locked out".*

## 3. Data and state

- **The control database is the single source of truth.** A node holds nothing
  that cannot be regenerated from it. Destroying and rebuilding a node is always
  safe — that is what makes fast rotation possible.
- **Never stored, at any level, including debug:** connection logs, traffic logs,
  DNS queries, user IP addresses, timestamps of individual connections.
  *Why: it is a non-goal in the charter, and data that does not exist cannot be
  seized, subpoenaed, or leaked. Health means "is this node serving", never "who
  used it".*
- **Secrets are encrypted at rest** with a key supplied by the environment. The
  application fails loudly at boot when the key is missing — it never starts in a
  degraded mode that writes plaintext.
- **Rendering is idempotent.** Rendering the same node twice produces
  byte-identical output, so configuration drift on a node is detectable by
  comparison.

## 4. Error handling

- Outward API errors use the typed envelope `{"error": {"code", "message"}}`.
  A raw exception string never crosses the boundary — no stack traces, no SQL,
  no paths, no host names.
- **Authorization fails closed.** An error inside an auth path denies access; it
  never falls through to the resource.
- **A partially applied node operation marks the node `degraded`, never
  `active`.** Silence about a half-configured node is worse than an outage,
  because users get routed onto it.

## 5. Dependencies

- Adding a dependency is an architect decision, not an implementation detail. A
  task whose spec does not mention a dependency does not get to add one.
- **Data-plane binaries and images are pinned to an exact patch version**, and to
  a digest as well once pulled on a real host. Never `latest`, never a bare major.
  *Why: an unpinned upstream that changes its TLS fingerprint or default
  parameters silently changes how detectable every node is.*

## 6. Things that are never done here

- **Never log who connected to what.** Not at debug, not "temporarily". It is the
  one record that can hurt a real person.
- **Never hardcode a country, provider, IP, domain or port in code.** It belongs
  in a node record or in configuration. A hardcoded value is a node you cannot
  rotate away from.
- **Never ship a shared default for a Reality decoy destination.** If every hashi
  node borrows the same site's handshake, that is itself the fingerprint that
  identifies hashi. Per-node, chosen deliberately.
- **Never commit secrets, tokens, real host names or real personal data.**
  Fixtures are fake; `.env.example` carries fake values only.
- **Never add a public signup route, a payment flow, or anything that advertises
  the service.** All three are charter non-goals, and the third carries a legal
  penalty for the owner.
- **Never write a comment that asserts what another module, another channel or a
  neighbouring branch does.** Describe the code it sits on, record why the
  decision was taken and what was rejected, and *name* the other thing rather
  than paraphrasing its behaviour. Nothing in this file changes when that
  behaviour changes, so the sentence rots silently and the suite stays green.
  M28 paid for this fifteen times: the shell claiming what the panel reads, the
  panel claiming what `make backup-status` prints, a gate comment claiming what
  the neighbouring state does — each true when written, each false within a step.
- **Never leave TODO / FIXME / stubbed logic in work handed to review.**
- **Never weaken a test to make it pass**; fix the product, or explain why the
  test was wrong.
