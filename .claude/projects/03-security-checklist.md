# Security checklist — hashi

<!--
WHAT: The must-check list for Sherlock Holmes and the self-check list for every
      developer touching an externally reachable surface.
WHY:  security review that improvises finds different things every time. A list
      makes a missing check visible.
HOW:  pre-read by security review (design and code) and by any developer adding
      a surface. The project-specific section at the bottom matters most.
-->

## Identity and authorization

- [ ] Identity comes from the verified request context — never from a
      client-supplied field.
- [ ] Every new surface states who may reach it, and the check is enforced in
      code (a router dependency), not merely documented.
- [ ] Authorization is checked on the object being touched, not only on the route.
- [ ] Privilege escalation paths considered: can a caller reach an operator
      action by changing an id?

## Input

- [ ] Every field validated at the trust boundary: type, range, size, format.
- [ ] Untrusted input never reaches a query, a shell, a path, or a template
      unescaped. **Node names and user nicknames are untrusted** — they end up in
      rendered configs and in SSH command lines.
- [ ] Size and rate limits exist wherever a caller controls volume.

## Secrets and data

- [ ] No secrets in code, fixtures, logs, error messages or test output.
- [ ] Secrets come from the environment/secret store; the app fails loudly when
      one is missing rather than starting degraded.
- [ ] Personal data: only what is needed, only where it is needed, never in logs.

## Errors and logging

- [ ] Outward errors carry no internals — no stack traces, no SQL, no paths, no
      host names.
- [ ] Logs carry no tokens, no payloads with personal data, no full credentials.
- [ ] Failures fail closed: an error in an authorization path denies access.

## Dependencies

- [ ] New dependencies are justified, pinned, and from a maintained source.
- [ ] No dependency added inside a task whose spec did not mention it.

## Project-specific

This product's adversary is not only a remote attacker — it is **a censor with
network position** and **a hosting provider legally obliged to act against its own
client**. These checks come from that, and they outrank the generic list above
when the two ever seem to conflict.

- [ ] **No connection, traffic or DNS logging**, at any level, including debug and
      including "temporarily while we debug". A log line recording who connected
      to what is a finding by definition.
- [ ] **Subscription tokens are bearer credentials in a URL path.** Check every
      place a request path can be recorded: application access log, Caddy access
      log, exception handlers, error reporting, shell history in bootstrap code.
- [ ] **Revocation is total** — a revoked user loses access on every node and
      every transport, not only the one they last used. Trace the fan-out in the
      code; do not accept "the record is marked revoked".
- [ ] **Unknown and revoked subscription tokens both return 404.** A 403 confirms
      a token once existed.
- [ ] **Fingerprintability is a security property.** A new listener, a fixed port
      across nodes, a shared Reality decoy destination, a self-signed certificate,
      a predictable path or a distinctive packet rhythm is a finding — it makes
      the whole fleet enumerable, not just one node.
- [ ] **No key material is shared between nodes.** One seized node reveals
      nothing about any other.
- [ ] **Nodes never dial the control plane.** An inbound connection from a node is
      both a fingerprint and a path back from a seized machine.
- [ ] **Node private keys and provider credentials** live encrypted in the control
      plane. Never in git, never in a task or status file, never in a log, never
      in a rendered template committed to the repository.
- [ ] **The admin panel is the highest-value target in the system** — it can add a
      node and read every credential. Every route authenticated; no unauthenticated
      read; no endpoint that is "internal" merely by being undocumented.
- [ ] **Assume the control-plane host can be seized or terminated.** Nothing
      recoverable only from that host; backups encrypted with a key that is not on
      it; relocation is a `.env` change plus a restore.
