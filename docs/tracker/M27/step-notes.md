# M27 — step notes
Conventions established here. They bind later steps, and later milestones in this
codebase, until something supersedes them. Follow them; do not relitigate.

## From M27.1 — what travels to a delivery host, and what is in it

**Stopped at its round cap with one High open** (carried to M27.2, below). Everything else
was verified against the code in both rounds.

**The control plane pre-renders delivery material and pushes it on apply**, placed under
`/opt/hashi` by the apply path that already exists — which places, restarts, and verifies the
daemon came back on this config and stayed up (`control/app/services/apply.py`).

**What serves it is the node stack**, running the Caddy tag the project already uses, reading
a placed directory. *"Caddy or the node stack"* was a false choice: Caddy is what runs, the
node stack is where it is declared. **The tag is chosen and reviewed, but it is not a pin a
node can use** — `deploy/docker/caddy.Dockerfile` is the control host's image in the infra
zone; node images are pinned in `edge/bootstrap/node_stack.py`, keyed by `ConfigFormat`
(2026-08-09 row). M27.2 adds one there or makes a deliberate cross-zone reference: a line of
cost, not a second decision.

**A property of the node, not a transport-like row.** A transport is what a `Credential`
points at and a subscription is rendered *from*, so a purpose that can never be granted and
must never appear in a subscription would need a carve-out at every reader of that table —
`TransportPurpose.relays()` is exactly that, at **seven** production call sites each doing
something different (`services/rotation.py:237,505,651`, `panel/routes.py:1888`,
`services/relay.py:48,570`, `services/apply.py:511`). A second one is `if transport ==`
spelled differently. The material is per-node by construction: the union over every
user-facing transport the host carries and every user holding a credential on one.

**Narrowing is possible and costs nothing in the motivating arrangement.** A subscription is a
*list* of client entries; a shorter list is valid in both shapes it is served in — `render`
answers an empty document, `archive_of` writes a note into an empty archive. Where exactly one
node carries user-facing transports, the narrowed artifact and the full subscription are **the
same document**.

**What narrowing costs from the second such node onward:** a refresh against a delivery host
returns strictly less than the control plane would, so it can **remove** working nodes from a
client — partial, in a direction a user cannot tell apart from revocation. **A pushed
subscription is not only a snapshot, it is a slice**, and M27.5 owns both halves. It also
raises the price of M27.7's multi-URL option: N delivery URLs become N disjoint slices rather
than N chances at one document.

### The gap this milestone inherits rather than a cleanup

**There is no teardown.** `docs/decisions.md` 2026-09-13 records it twice — *"there is no
teardown action anywhere"*, and an apply *"never removes what an earlier one wrote"*, measured
with a leaf's `wireguard.conf` and its `PrivateKey` still on disk after the row was deleted.
Node services carry `restart: unless-stopped`, so deleting the directory would not even stop
the containers.

**Carried to delivery: a host that STOPS being a delivery host keeps its last artifact, and
whatever token store M27.2 lands, on disk.** Worse than the measured leftover key, which was
regenerable material the node held while it served; a token is a **user's** credential and
opens the control plane's own endpoint too. **M27.4's "absent, not inert" does not cover
this** — that requirement is about the co-location arrangements, i.e. a host that never served
delivery, not one that stops.

### The one that reframes the milestone

**Narrowing removes the leaf addresses. It does not remove the tokens.** A stateless server
looks a request up by what the path carries, and the path carries the token, so the naive
store is one file per token — and a seized delivery host yields the live bearer credential of
every user it serves, in the clear, which the control **database** holds only as ciphertext
(`Subscription.token` is `EncryptedText`, lookup through a keyed digest). That token then
fetches the **un-narrowed** document from the control plane, and the same token answers both
shapes on the same route. A subscription token has **no expiry** and is the only artefact a
user holds, so the repair is re-issuing every affected URL through a channel M27.7 records the
product as not having.

**M27's done-when is not satisfied by writing this down:** it requires what a seized delivery
host yields to be *no wider than today* **or** the widening to be a recorded decision. No
non-control host holds a token today, so any token store is strictly a widening.


## From M27.2 — the push, and no token on a node

**Converged clean in two rounds.** control 1011/2, edge 929/3, infra 486, **e2e 224/0**.

**No token is written to a node, ever.** An artifact is named
`sha256(b"hashi/delivery-artifact-name/v1" + token)` — `control.app.services.delivery.artifact_name`.
Swept and verified: name, both file contents, the staging path, the two shell strings, the
logs and the audit trail all carry no token.

**Unkeyed is the load-bearing half.** `Subscription(` is constructed at exactly **one** site,
`subscriptions.issue`, with `secrets.token_urlsafe(32)` — 256 bits, no operator-chosen or
imported path — so there is no dictionary to run against a digest. A *keyed* digest would buy
unlinkability only against someone who already holds a token, and would cost the ability to
recompute the name without the master key, so nothing could ever map `/sub/{token}` onto a
file. **Do not "improve" this into a keyed digest.**

**The derivation carries no per-host component, and that is now a constraint on M27.3.** Under
the *hash-the-path-segment* route the digests on a seized host are inert. Under
*serve-the-digest-as-the-path* the digest **is** the fetch credential, and one seized host's
digests open the same users' artifacts on **every** delivery host. Salting with the node's own
id closes that and costs the hash-the-path route, because a node cannot hash what it has not
been told. **The route choice is a security decision.**

**Layout:** `/opt/hashi/delivery/<digest>.txt` (base64 v1 document) and `<digest>.zip`
(archive), files 0600, directory 0700, **a sibling of `conf/`** — never under it, because the
rendered node compose bind-mounts `conf/` into every data-plane container. `place_delivery`
stages into `delivery.incoming`, swaps, removes the previous directory. **Nothing else is ever
in that directory.**

**One renderer, not two.** `entries_for` / `config_files_for` / `render` take `over=<rows>`,
which **replaces** the fleet-wide serving filter; `services/delivery` is the only caller. A
second renderer here would be this project's recorded second-parser defect in a new place.

**Position in apply:** the read is a database question above the connection; the push is the
last step **inside** it. `confirm_serving` **measures** — the verdict is computed after the
connection block — so a node whose data plane did not come back is handed fresh material and
*then* marked degraded. Deliberate: the material is a function of the database, and
withholding it would leave the **staler** directory on a host about to be repaired.

**Content widening, recorded rather than silent:** a WireGuard-family *client* file carries a
`PrivateKey` the node's own server config does not hold. `Credential` is unique per
`(user_id, node_transport_id)`, so it impersonates that user only to the host the seizer
already has.

### The state that is NOT closed, and why reaching it was rejected

`apply_node` raises `NothingToApply` **above** the push. So disabling a host's last transport
and pressing Apply never reaches it, and the host keeps its ex-users' material. **Three
reasons reaching the push there was wrong, all verified:**

1. All three `_nothing_to_apply` sentences say *"nothing was pushed and nothing on the node was
   changed"* — M18.1's answer, walked at M18's acceptance.
2. `prepare` has not run. It exists **precisely** to replace a failing `mkdir` with a sentence
   (`test -d` / `test -w` → `HOST_NOT_PREPARED`), so pushing there would create `NODE_ROOT`
   where the account can — crossing M13's privilege boundary — or reintroduce the raw
   `Permission denied` that sentence was written to eliminate.
3. Its failure has nowhere to go: degrading contradicts M18.1, swallowing is the silent
   failure this codebase punishes hardest, raising replaces the sentence that explains the host
   keeps serving.

**What makes the residual defensible:** `NOTHING_STOPS_A_SERVING_HOST` — a host can only hold a
delivery directory if an apply once ran, and nothing since removes the config or stops the
daemon. So that box is **still terminating those people's tunnels**; the directory's marginal
contribution is the client-side lines. **A test pins the state and goes red the day anything
reaches that host.** The removal path is M27.4's, in its text since 2026-09-26.

**No image pin was added and no service declared.** A site block needs an address and a port:
hardcoding either is forbidden, an operator-set port is M27.4's forbidden flag, the name and
certificate are M27.6's, and what may be recorded there is M27.3's subject.
`test_every_image_pin_resolves` builds from `DATA_PLANES`, so a pin added now would be
unchecked. **Cost, recorded: until M27.3, every applied node holds material no user can
fetch.**


## From M27.3 — a delivery host serves the name, and records nothing

**Stopped at its round cap with two Highs open** (carried to M27.4). The central claim —
whatever serves `/sub/{token}` on a delivery host records no token, on every surface including
the container runtime — is measured, reproduced independently, and holds under adversarial
probing.

**The route: the artifact's name IS the path, salted with the node's id.**
`artifact_name(node_id, token) = sha256(b"hashi/delivery-artifact-name/v2" + node_id + b"\x00" + token)`,
still unkeyed, both arguments positional so **no path produces an unsalted name**. This closed
M27.2's open constraint; `test_one_subscription_is_a_different_name_on_every_host` pins it.

**Why this route rather than hashing the path segment**, and it is the step's own title: under
that route **the token is in every request line, in the clear, on the most seizable host in
the fleet** — a host compromised while *running* harvests live credentials, each of which
opens the control plane's un-narrowed route. Here there is no token to record, in flight or at
rest, so *records no token* is **structural rather than a discipline**. It is also the only
route plain Caddy can serve: a file server hashes nothing, so the alternative needs a program
on a node — new code, a new pin, and `/sub/{token}`'s rules taught a second time.

**The id, not the address** — an operator-editable address would dead-link every URL a user
holds the moment it is corrected.

### What measurement found that reading would not

**Caddy writes three lines before it applies the logging configuration it is given** —
`using config from file`, `adapted config to JSON`, `redirected default logger`. That is why
`logging: driver: none` is on the service: config-level silencing is a **discipline**, the
driver is a **structure**. Thirty probes, including traversal, `%00`, duplicate and
case-varied query keys: still exactly those three lines, no path, no name.

**Caddy resolves placeholders inside quoted tokens.** Without `_UNWRITABLE_IN_A_VALUE`, a
header value naming `{http.request.uri}` echoes the artifact name — which under this route *is*
the fetch credential — into **every response**. Verified twice by bypassing the guard and
watching real Caddy return `X-Thing: /sub/3fccc…`. **Never relax that guard.**

**Headers on an empty body are a signature.** Response headers sit behind a `file` matcher
inside each shape's `handle` block, so they attach only where an artifact really is; the
catch-all is a bare `respond 404`. Every refusal is byte-identical —
`404 / Server: Caddy / Content-Length: 0` — across unknown names, bad shapes, `/`,
`/panel/login`, traversal and the adversarial set. A fixed header set on every delivery host's
404 would be the enumerability `CLAUDE.md` bans a shared Reality decoy for.

**Two pre-existing Caddy behaviours, not defects of ours:** `//sub/<name>` normalises to a
200, and `?FORMAT=` reads as *no format* because the `query` matcher key is case-sensitive.

**A digest in a log is NOT acceptable** — under this route the name is that host's fetch
credential, so a log of names is a log of credentials, and a log of names plus a seizure is a
record of who fetched what.

**asyncssh logs the remote path at DEBUG** (`Sending open for <path>`, one line per SFTP
operation) — unreachable today and one `setLevel` away. Pinned to WARNING in
`configure_logging`. The M27.2 row's claim about `SFTPError` carrying the path was **measured
false** (OpenSSH sends generic reasons; `apply.py` uses `type(exc).__name__`), and a correcting
row was appended rather than editing the accepted one.

**Declared, not wired.** Nothing passes `compose_service` and no apply places the site file —
that needs M27.4's predicate and M27.6's name. `render_compose(delivery=None)` is
byte-identical, so a non-delivery host recreates nothing. The site file is
`/opt/hashi/delivery-site.Caddyfile`, deliberately **not** `delivery.*`, which is the push's
staging family and gets `rm -rf`'d. `restart` runs `up -d --remove-orphans`, so dropping the
service removes the container — M27.4's removal path, for free, though the *directory* still
needs `place_delivery(artifacts=[])`.


## From M27.4 — the predicate, derived and never flagged

**Converged clean.** control 1043/2, edge 967/3, e2e 239/0.

**`control.app.services.delivery.is_delivery_host(connection, *, enabled)` — call it, never re-derive
it, and never add a field or setting beside it.** Two halves, both read off things already true:

1. **Does anyone fetch from this host** — `any(row.purpose == TransportPurpose.USERS for row in
   enabled)`. A *purpose*, never a transport name. Settles every leaf in every arrangement
   **without dialling the host**.
2. **Is this host already the one that answers `/sub/`** — `CONTROL_STACK_PROJECT not in
   compose_projects(connection)`, i.e. `docker compose ls --all --quiet` over the connection the
   apply already holds.

**Why half 2 is measured on the host and cannot be a record comparison.** The runbook registers a
co-located box with its **public IP** for `address` and `ssh_host`, while `.env.example` and the
runbook require `HASHI_PUBLIC_HOST` to be a **DNS name**, because a public CA cannot issue for an
IP. Two truthful values for one machine, two different strings — so a record comparison answers
*"not co-located"* for **exactly the arrangement this step is about**.

**The failure directions are asymmetric, and that is what makes it affordable.** A host wrongly
judged co-located keeps no second copy — the control box already holds the database and the master
key. A host wrongly judged a stranger gets the second name, certificate and listener the step
forbids. So `compose_projects` **raises rather than answering empty**: an empty set reads as
"nothing of ours is here", which is the answer that puts a second listener on the box that already
answers.

**Named assumption, not checkable:** the control stack is deployed by compose, under that name, on
the engine the node's SSH account reaches. One run outside compose, or under a daemon that account
cannot see (rootless, a non-default context), is invisible — and its own box is then offered
delivery. Named rather than checked, because the alternative is the setting the predicate exists
not to have.

**`CONTROL_STACK_PROJECT` is pinned against `deploy/docker-compose.yml`** by a control test that
fires if that name changes. Node stacks are `hashi-node`, so a node never looks like the control
host.

### The removal path

**`remove_delivery(connection)` creates nothing** — `test -d` then `rm -rf` of the live directory
**and both staging siblings** — which is what makes it legal on a host `prepare` has never touched.
It is **not** `place_delivery(artifacts=[])`: that leaves an *empty* directory, the right state for
a delivery host carrying nobody; this leaves **no** directory, which is *absent, not inert*.

**A refused apply now dials the host** before refusing, and M27.2's three objections are answered
rather than overridden: the removal creates nothing, so the privilege boundary and
`HOST_NOT_PREPARED` are untouched; the clause *"nothing was pushed and nothing on the node was
changed"* is **replaced, never appended to**, on the one host where it is false, through the
substitution `panel/wording` already uses — with a test pinning that all three refusals still
contain the clause, or the swap would silently no-op; and a failure to reach never degrades.
Still 409, no state write, no render, no push.

**`DELIVERY_MAY_STILL_BE_THERE` is appended only to `NOTHING_LEFT_TO_APPLY`** — the refusal whose
evidence is a surviving `applied_at`. A hedge on the others would fire on every first-run apply.

**Three states the removal does not reach**, all recorded: `cannot_serve_again`, a node the fan-out
skips as not serving, and a node whose record is deleted.

**The wording names the directory, not its contents** — *"the delivery directory an earlier apply
left there is gone, with whatever it was holding"* — because `remove_delivery` measures the live
directory and nothing else, and that sentence is true of both the populated host and the empty one
this product creates on purpose. Counting files was weighed and refused: a second reading of the
host for a distinction that changes nothing an operator would do.

### The seam M27.6 inherits, and it is wider than a name

Nothing passes `compose_service`; nothing calls `place_delivery_site`. **The blocker is the port.**
A Caddy site address with a bare name takes 80/443, and the runbook puts `vless-reality` on **443
on the entry** — which is the delivery host in **both** arrangements that need the work. The
runbook also records that the co-located shape cannot have Reality on 443 *because Caddy holds it*.
So **M27.6 owns a port-sharing decision**, not only a name and a certificate. An operator-set port
is the flag M27.4 bans; a literal is the hardcoding `CLAUDE.md` bans.

**For acceptance:** the co-located arrangements are currently absent by **two** constructions — the
predicate says no, **and** no listener exists anywhere. So the walk's second scenario cannot yet
distinguish a feature absent by derivation from one absent because nothing was built. It becomes
meaningful only after M27.6.

## From M27.9 — the gate that was red four hours a day

**`make verify` was unusable between 00:00 and 04:00 UTC from M28's merge until 2026-09-27.**
The fixture built its record's `due_date` from the calendar day while `scripts/backup-run.sh`
computes the schedule's owed day from the configured `at` window, so inside that window the
record was a day ahead and the script correctly answered `clock=ahead`. **The product was
right.** Green in every run anyone happened to make, which is why it survived a merge.

**`day_owed_in(zone, at)` in `tests/infra/test_backup_schedule.py` is the oracle** — any infra
fixture needing *the date the schedule is on* calls it with the zone and hour **the env file
under test names**, never the calendar. `today_in` is deleted. Record fixtures are **functions**
(`a_real_run_half_an_hour_ago(tmp_path)`, `a_due_date_ahead_on_its_own(tmp_path, …)`), never
module constants — a `@parametrize` list is built at collection, so a constant there is the
import-time half of this defect.

**A test oracle is allowed to be a second implementation, and this one must be.** The
M28.12/M28.13 lesson is about two implementations **in the product**, both reachable by users.
An oracle's job is to be a second opinion: asking the script for the date would be satisfied by
the script being consistently wrong, and one of these tests asserts on what a `tick` actually
wrote. **But the line runs through the assertion, not the file:** implement the date when the
assertion is *about* the date; **ask the script when the date is only scaffolding** under some
other assertion — `test_the_backup_surfaces_record_nobody.py::test_a_tick_with_nothing_owed_says_nothing_at_all`
is the canonical second case, and the two files now name each other.

**An oracle without a pin is the drift it was written to prevent, and this one had already
drifted at birth.** `test_the_day_this_suite_seeds_is_the_day_the_script_owes` compares
`day_owed_in` against the real `due` output over 6 zones × 8 spellings. Against the helper as
first written it was **red in 11 of 48**.

**Three properties of that pin, all load-bearing:**
- **the grid is chosen by timezone offset, not by hour** — a pin written against `Etc/UTC`
  alone would itself be hour-dependent, which is this defect inside its own remedy;
- **`Nowhere/Useful` is in the zone list precisely because it is not a zone** — the
  pass-through-to-`date` assumption is checked rather than assumed;
- **the oracle is read on both sides of the invocation** (`assert answered in {before, after}`)
  because two clock reads a fifth of a second apart straddling the configured minute would make
  the pin red for one second a day.

**Mirror `resolve_schedule` completely or not at all.** `the_hour_the_script_resolves` mirrors
the `sanitised` character class, the accepted shape, the `%02d` pad and the `04:00` fallback.
Padding alone is not enough: the script **strips a space and accepts the result**, so
`HASHI_BACKUP_AT=1 2:00` resolves to `12:00 configured`. Mutation-tested — dropping the
sanitiser, the pad or the fallback each turns the pin red. (Dropping `[:64]` does not; see
carry-over.)

**Ask the script for configuration; compute the date yourself.**
`the_hour_no_env_here_configures(tmp_path)` runs `due` with no `HASHI_BACKUP_AT` and reads
`at=` off the first line, so the fallback cannot part from `resolve_schedule`. The constant it
replaced carried a false safety claim — that a changed fallback would go *red rather than
quiet* — when it would have been red only during the hour between the old value and the new.

**To simulate an hour, nothing in the suite freezes a clock:** substitute `Etc/GMT±N` for the
zone the module names, which moves the local hour the script compares against `at`. For tests
pinned at `at=00:01`, move the configured hour instead. **That method shifts hours, not
minutes**, so sub-minute cases are not covered by it.
