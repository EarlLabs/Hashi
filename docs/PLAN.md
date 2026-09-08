# hashi — plan

**Created:** 2026-09-08
**Status:** approved by the owner 2026-09-08 — M1–M11. **M12 was appended
during the overnight field run of 2026-09-08**, under the owner's standing rule
that a field bug no milestone covers becomes a new milestone: it concerns
something the plan already aimed at (walking M8–M10 on the stand) and it lands
in `infra`, so implementing it in the same run is pre-approved.
**Source:** the first real deployment. Every item below was found by *running* the
product on a rented host, not by reading the tree. None of them is caught by
`make test`, and none of them was visible from inside the repository.

Charter: `docs/product/charter.md`. Frozen acceptance criteria:
`docs/research/product-owner-ohno-4/research.md` §3. Provider research:
`docs/research/research-vps-provider-shape-a/research.md`.

---

## General rules for every milestone below

- **M1 gates the verification of everything else.** Until `apply` takes effect, a
  correct change and an incorrect one both look broken on a live node. Order the
  work accordingly.
- **The lesson that produced this plan:** everything checkable by *rendering*
  works; everything checkable only by *running* does not. A milestone is not done
  because its output looks right.
- **Do not rent the Russian host yet.** It would cost money and buy nothing until
  M2 and M3 are done — you would get two working nodes and no working hop between
  them.
- **Where a milestone says `acceptance: yes`, its scenario needs a real node.**
  The disposable stand in `scripts/acceptance/stand.sh` brings up a control plane,
  a database and a delivery endpoint — it has no data plane, no tunnel and no
  second host. M1, M2, M3 and M7 are therefore field observations on rented
  hardware, and the stand cannot discharge them. Say so in the verdict rather
  than passing them on a panel that looked right.
- **M8, M9 and M10 are the exception to that rule.** They are panel work, and the
  stand is exactly the right instrument for them: a control plane, a database and
  a delivery endpoint is all their scenarios need. Walk them on the stand — and
  walk them, rather than passing them because the screenshot matched the design.
- **`make test` never proves a tunnel carries traffic**, and it cannot prove the
  charter's first success criterion. See "What this plan does not cover".

---

## Where things stand

One host, rented and live: **Amsterdam, NL — 45.151.69.107**, AS216139 Iron
Hosting Centre, Ubuntu 22.04, 1 vCPU, 957 Mi RAM. Runbook **Shape A**: control
plane, panel, delivery endpoint and one node on the same box.

**Works, verified over the public internet:** `panel-bootstrap.sh` → Let's Encrypt
certificate → panel login → register node → enable transport → `apply` → friend →
subscription → a real client connects and carries traffic. Operator auth fails
closed (401 unauthenticated). The API returns public keys and withholds private
and preshared ones.

**The charter's hardest invariant holds on real hardware.** A live subscription
token appears **zero** times in container logs and **zero** times in Docker's
on-disk JSON logs; `/sub/` is never recorded; uvicorn's access log is empty and
Caddy emitted four lines across the whole deployment. No unit test could have
established this.

**Two hosts as of 2026-09-08, roles set by the owner.** The Amsterdam box is the
**leaf** and exits traffic. A second host — 3.9 Gi RAM, in Russia — is the
**entry**, and carries the control plane and the panel as well. That moves the
control plane off the 957 Mi box, which had 463 Mi free while running control,
Postgres, Caddy and a node together. It also puts every node key and every friend
credential on a Russian host: deliberate, and the reason M7 stops being optional.

**Does not work:** everything in M1–M3 below. The pattern is worth stating once,
because it is the lesson of the whole exercise:

> Everything checkable by **rendering** works. Everything checkable only by
> **running** does not.

---

## → M1 — `apply` must actually take effect · planned 2026-09-08

**Blocking prerequisite for everything else.** Until this is fixed, no other fix
can be verified on a live node: a correct change and an incorrect one both look
broken.

**The bug.** `node_stack.restart()` runs `docker compose up -d --remove-orphans`.
Compose is declarative — it compares the desired *service definition* against the
running container and does nothing when they match. A bind-mounted config file's
**contents are not part of that definition**, so the container is never recreated,
and Xray parses its config only at process start. Measured on the live node:
container started `12:57:53`, config last written `17:01:39`, with three applies
and one revocation in between — **none reached the process**.

The comment at `node_stack.py:249` asserts the opposite in as many words: *"`up -d`
rather than `restart`: it is the same command whether the stack was never started,
is partly running, or **needs a changed config picked up**."* That last clause is
the defect.

**Why it stayed invisible:** `running_services()` asks which services are up, and
the container genuinely *is* up — just stale. So `apply` returns 200 and writes
`applied_digest` to the database, which then records a state the node is not in.

**Consequences:** a new friend cannot connect, and — worse — **a revoked friend is
not cut off.** The config file loses the credential, the subscription 404s, and
the running daemon keeps accepting the revoked key until something unrelated
restarts it. That is criterion 6 failing silently while the panel reports success.

*Rejected: simply swapping `up -d` for `restart`. That breaks the cases `up -d`
exists for — container never created, definition genuinely changed, stack partly
running.*

### M1.1 — Make the config part of the service definition

Put `digest_of(config)` into the rendered compose as a label or env var on the
service. A changed config then *is* a changed definition, and Compose recreates
the container by itself. `up -d` stays the single verb, and `digest_of()` already
computes the value.

### M1.2 — Prove the daemon loaded this config, not merely that a process exists

Replace the `running_services()` check with one that establishes the running
daemon is on the digest `apply` just pushed.

### M1.3 — Correct the comment at `node_stack.py:249`

It currently states the defect as the reason for the design.

**E2E:** none yet — the scenario that would catch this is M5.3, sequenced after
the fix so it can be written red against a node known to be broken.

**Done when**
- [ ] Changing a config and applying restarts the daemon, proven by a start
      timestamp later than the config's mtime.
- [ ] `apply` fails loudly if the running daemon's config does not match the
      digest it just pushed.
- [ ] Revoking a friend stops that friend **at the node**, verified by a client
      that could connect before and cannot after — not by reading the file.

acceptance: yes
On a live node with a transport enabled, add a friend and connect a real client as
that friend. Note when the data-plane container started. Now revoke the friend in
the panel and apply. Check that the container restarted *after* the config was
written, then try that same client again: it must no longer connect. Reading the
config file does not count — this is the milestone whose whole failure mode was
"the file looks right".

---

## → M2 — The WireGuard family must start at all · planned 2026-09-08

**The bug.** `node_stack.py:116,126` sets `command=("up", "{config}")` for
`amneziawg` and `wireguard`. Both images have an **empty ENTRYPOINT**
(`amneziavpn/amneziawg-go:3.0.3` → `Cmd=[/bin/sh]`;
`masipcat/wireguard-go:0.0.20230223` → `Cmd=[/entrypoint.sh]`), so `command`
becomes the entire argv and Docker tries to exec a binary named `up`:

```
exec: "up": executable file not found in $PATH   → exit 127, container stuck "Created"
```

The images **do** ship `awg-quick`, `awg`, `amneziawg-go`, `wg-quick` — so this is
a command bug, not an image swap.

The runbook's "Known-unproven" section named only the plain-WireGuard image. Both
are broken, and `amneziawg` is the transport the same runbook recommends for
Shape A and **mandates** for the entry→leaf hop.

### M2.1 — Give each WireGuard-family transport a command its image accepts

Note `awg-quick` derives the interface name from the config **filename**, so the
config path is part of the fix, not incidental to it.

### M2.2 — Check the same assumption for every transport in the registry

Including any added later. The Xray family happens to be correct, which is luck,
not design.

**E2E:** none yet — M5.1 and M5.2 are the scenarios that pin this.

**Done when**
- [ ] `amneziawg` and `wireguard` containers reach `Up`, not `Created`, on a real
      node.
- [ ] A client on a WireGuard-family transport carries traffic.
- [ ] A test asserts the container command against the image's real entrypoint
      (see M5).

acceptance: yes
On a live node, enable `amneziawg`, apply, and look at the container: it must be
`Up`, not `Created`. Then take a client onto that transport and load a page
through it. Repeat for `wireguard`.

---

## → M3 — The entry node must route friend traffic into the hop · planned 2026-09-08

**This is the charter's core claim, and it is not implemented.**

`vless_reality/server.j2:58` (and `vless_ws_tls` identically) hardcodes a single
outbound:

```json
"outbounds": [{"tag": "direct", "protocol": "freedom"}]
```

No routing rules, nothing conditional on the node having a hop. `edge/relay.py:174`
defines `exit_address()` — *"the in-tunnel address the entry forwards friend
traffic to… what an entry node's data plane uses as its outbound target"* — and it
is called from **exactly one place in the tree: its own unit test**
(`tests/edge/test_relay.py:135`).

So on an entry node with a friend-facing transport and a hop to a leaf, friend
traffic arrives at Xray and leaves **straight out of the entry node's own
interface, in Russia.** The hop is genuinely built — keys minted, both ends
rendered, entry-dials-leaf asymmetry handled, `AllowedIPs` deliberately narrow so
the control plane's own SSH is not swallowed, rotation and drift detection working.
Every piece except the one that makes it a relay.

**Why this is the worst of the three: the failure is invisible.** The friend
connects, pages load, the panel shows two `active` nodes and a live hop — and the
exit is in Russia. The protection the topology exists to provide is absent while
everything looks healthy.

### M3.1 — Render the entry node's outbound and routing rule

Target `exit_address(leaf)`, and send friend inbound traffic to it.

### M3.2 — Keep it data-driven

The entry must not learn protocol names. A node with no hop keeps today's
`freedom` outbound unchanged.

### M3.3 — Decide and document what happens when the hop is down

Fail closed (no exit) is almost certainly right, because failing open means
exiting in Russia without anyone being told. This is decision 3 below.

**E2E:** none yet — M5.4 is the hop scenario that asserts the exit address.

**Done when**
- [ ] A client connected to the entry node shows the **leaf's** public address as
      its exit IP.
- [ ] A node with no hop still exits directly, unchanged.
- [ ] Tearing the hop down does not silently fall back to a Russian exit.

acceptance: yes
With an entry node and a leaf node joined by a live hop, connect a friend's client
to the entry and ask the internet what address it sees — it must be the leaf's,
not the entry's. Then take the hop down and check again: the friend must not
quietly end up exiting in Russia. Nothing short of observing the exit IP proves
this.

---

## → M4 — Failures must report themselves honestly · planned 2026-09-08

Two defects, both about a wrong message at the worst moment.

**A node's first apply cannot record its own failure.** `apply_node` marks a node
`degraded` on failure (`apply.py:257,265`), but the state machine forbids
`draft → degraded` — and `draft` is exactly where a first apply starts. The
operator gets `409: a node cannot go from draft to degraded` instead of "amneziawg
did not come up", and the real reason reaches no log either. This is how M2 hid
itself on the first run.

**Revoking a friend returns 500.** `MissingGreenlet` at `apply.py:276` —
`node.transports` is lazy-loaded after `friends.revoke` committed the session.
`apply_many` (`apply.py:303`) catches only `NodeOperationFailed`, so the SQLAlchemy
error escapes. The operator never receives the `RevocationOutcome` naming which
nodes still carry the credential — which is the reporting criterion 6 exists for.

### M4.1 — Let a first apply record its own failure

Allow `draft → degraded`, or give the first apply its own path. A node that has
been written to and failed is not still a draft.

### M4.2 — Remove the lazy load from `apply_node`

Eager-load what it needs, or refresh explicitly, so no lazy I/O happens outside
the greenlet context.

### M4.3 — Widen `apply_many`'s except clause

An unexpected error becomes a reported per-node failure rather than a 500 for the
whole fan-out.

**E2E:** none from `tests/e2e/` — this is control-zone territory and the gate that
applies is `make test-control`.

**Done when**
- [ ] A first apply that fails leaves the node `degraded` with the real reason in
      `state_detail`.
- [ ] Revocation returns `RevocationOutcome`, listing any node that still carries
      the credential.
- [ ] No operator-facing 500 on either path.

acceptance: no
Provable by test once M1 is in.

---

## → M5 — Tests that catch "renders but does not run" · planned 2026-09-08

Nothing in `tests/e2e/` or `tests/edge/` asserts the data-plane container command,
and nothing asserts that traffic transits a hop.
`test_every_image_pin_resolves.py` proves a tag exists and says nothing about
whether the image starts. That gap is why M1, M2 and M3 all survived to a rented
host.

Every scenario red-first: break it, watch the right assertion fail, restore.

### M5.1 — Assert each transport's command against its image's real entrypoint
### M5.2 — Assert a container reaches `Up` and stays up, not merely that it was created
### M5.3 — Assert that a config change reaches the running daemon

Pairs with M1.

### M5.4 — A hop scenario that asserts the exit address, not the rendered config

**E2E:** this milestone *is* the e2e work — its four steps are the scenarios, and
they land under `tests/e2e/<zone>/`. The existing suite stays green.

**Done when**
- [ ] Reverting any of M1–M3 turns a specific scenario red.

acceptance: no

---

## → M6 — Deployment hygiene · planned 2026-09-08

**`panel-bootstrap.sh` reports a URL nothing serves.** Confirmed on the live host:
it verified the stack from inside the compose network and printed
`The panel is at https://…/panel/` while ports 80 and 443 were closed, because the
base compose publishes nothing. The runbook documents this and tells you to write
`deploy/docker-compose.public.yml` by hand. Either publish, or do not print an
address that has not been proven reachable.

**`ufw enable` turns on connection logging.** The runbook's own line produces
`/var/log/ufw.log` full of source addresses — the record the charter forbids *at
any level*. It had collected 5,840 bytes within minutes on the live host. I ran
`ufw logging off`; the runbook still lacks the line and `panel-bootstrap.sh` has
no check.

### M6.1 — Make bootstrap's final message match what is actually reachable
### M6.2 — Add `ufw logging off` to the runbook, and a check to bootstrap
### M6.3 — Decide what to do with the existing `/var/log/ufw.log` on the live host

This is decision 5 below.

**E2E:** none from `tests/e2e/` — the real check is a fresh host following the
runbook, and no suite rents one. `make test-infra` covers what can be asserted
about the script itself.

**Done when**
- [ ] Bootstrap's success line is reachable from outside, or it does not print one.
- [ ] A fresh host following the runbook produces no connection log.

acceptance: no

---

## → M7 — Panel off the public internet · planned 2026-09-08

**Owner request:** reach the admin console over Tailscale rather than from a public
address. The reasoning is sound: the panel holds every node key and every friend
credential, and there is deliberately **no lockout on failed logins**
(`control/app/auth.py`), so password length is the entire defence.

**What makes it more than a one-line change:** the panel and the delivery endpoint
are the same Caddy site today —
`{$HASHI_PUBLIC_HOST} { reverse_proxy control:8000 }`. And `/sub/{token}` **must
stay public**: a friend refreshes their config from inside Russia at exactly the
moment a node was blocked. So the site has to split in two:

- **public** — serves only `/sub/*`, everything else 404;
- **tailnet** — `/panel/*` and `/api/*`, bound to the Tailscale interface, cert
  from `tailscale cert`.

**Blocked on two owner decisions — 1 and 2 below.** This is a charter amendment,
and the project's own rule is consent first, then the charter, then the plan — in
that order, never the reverse.

### M7.1 — Split the Caddy site in two
### M7.2 — Bind the panel and API to the private interface, with its own certificate
### M7.3 — Document the way back in when the private network is unavailable

SSH remains the fallback either way.

**E2E:** none — the check is reachability from two different networks, which no
suite running on one machine can stage.

**Done when**
- [ ] The panel is unreachable from a public address.
- [ ] `/sub/{token}` still resolves from an ordinary network, unchanged.
- [ ] A documented way back in when the private network is unavailable.

acceptance: yes
From an ordinary public network, try to open the panel — it must not be there.
From the tailnet, open it and sign in normally. Then, from the ordinary network
again, fetch a friend's `/sub/{token}` and confirm the subscription still
resolves. Last, with the private network unavailable, follow the documented route
back in and confirm it works.

---

## → M8 — The console the owner actually lives in · planned 2026-09-08

The panel today is one scrolling page plus a node detail page, dressed in twenty
lines of inline CSS. `design/` holds a finished, high-fidelity redesign of it:
nine screens behind a persistent sidebar, every creation flow in a dialog, and the
24-field hop form collapsed behind a disclosure. The job it optimises for —
*"add a user, hand them their subscription link, and see at a glance whether the
mesh is healthy"* — is criteria 2 and 3 word for word, so this is not decoration.

**The source of truth is the three written documents**, not the prototype:
`design/README.md` (the handoff), `design/UI-PATTERNS.md` (how to add a screen
without the panel drifting) and `design/design-system/styles.css` (the tokens).
`design/VPN Admin.dc.html` is a reference drawing — it links a `_ds/` bundle and a
`support.js` the handoff does not ship, so it does not even render standalone.
Recreate the design in the stack the panel already has; do not copy its markup.

**No framework arrives with this.** "Sidebar navigation swaps the main region; no
page reload" is HTMX against a `#main` target, which is what the project already
serves from its own `/static`. The stack rule stands: Jinja2 + HTMX, no bundler.

**Three things in the design cannot be built as drawn, and one of them matters.**

- *The stylesheet fetches fonts from Google.* `styles.css:2` is
  `@import url('https://fonts.googleapis.com/…')`. The panel must not fetch
  anything from a third party — `base.html` already refuses a CDN for HTMX,
  because "the panel must work on a network where the CDN is blocked, which is the
  same network the operator uses to fix a blocked node," and M7 puts the panel on
  an interface where that request may have no route at all. It also tells a US
  company every time the owner opens their VPN console. The `@import` goes;
  decision 7 says what replaces it.
- *Four cells measure people.* "throughput now" (Overview), "last seen" (Users),
  node "load" (Nodes) and the whole **Traffic screen** — per-user down, up,
  sessions and busiest node. The charter's non-goals name all of it: *"No traffic
  logging, no DNS logs, no per-user analytics. Not 'off by default' — absent, so
  there is nothing to seize or subpoena."*
  `tests/control/test_zone_invariants.py::test_no_model_records_anything_about_a_connection`
  turns red the moment a model grows a field for any of them. The design is right
  about the layout and wrong about those four cells, because it was drawn without
  the charter in hand. Decision 6 chooses what stands in their place; the layout
  survives either way.
- *The design renames friends to users.* Its own note says the prototype "is still
  named `friends` internally — rename on implementation," which points the wrong
  way for us: `friend` is the word in the models, the services, the API, the tests
  and the charter. The recommendation is to keep `friend` in the code and decide
  only the visible label — decision 9.

This milestone lands the foundation and the two screens that carry the primary
job. The fleet screens follow in M9, and the two that need records the project
does not keep are M10. Until M9 lands, the sidebar keeps one entry pointing at
today's page for everything not yet ported — a dead nav link is worse than an
honest one.

### M8.1 — Vendor the design system, minus its third-party font fetch

Serve `styles.css` from `/static`. Every colour, space, radius and shadow comes
from its variables; nothing gets hard-coded past them.

### M8.2 — The shell: sidebar, header, panel body, and the 900px collapse

One breakpoint, per UI-PATTERNS §12. Grids are `repeat(N, minmax(0, 1fr))` so they
collapse under the rule that already exists rather than a new one.

### M8.3 — The toast and the dialog primitive

Every mutation emits a toast naming its object (`<nick> revoked — link is dead`),
one at a time. `.dialog` needs an opaque background — the design system's is
transparent, and the handoff says so twice.

### M8.4 — Overview

Four stat cards and the preview tables, carrying only facts the control plane
already holds.

### M8.5 — Users, with the add-user and subscription-link dialogs

Submitting the nickname creates the user, closes, and opens the link dialog by
itself. The link is a bearer credential: it may not reach a query string, a log
line or an error message.

### M8.6 — The states the design did not draw

Empty, loading, request failure, and field-level validation — for these two
screens. A first-time operator meets the empty state before anything else, which
is exactly the seed the acceptance stand uses.

**E2E:** the existing `tests/e2e/control/` scenarios stay green —
`test_the_owner_issues_and_revokes_access.py` and
`test_request_paths_are_never_logged.py` above all. Where one asserts a fact on
the old single page, it moves to the screen that now owns that fact; relaxing the
assertion instead is how this kind of rewrite loses its cover. One new scenario:
**the panel fetches nothing from a third party** — no font, script or stylesheet
from an origin that is not this host. It pins decision 7 permanently, and it is
the only part of this milestone a test can hold. `make test-control` is the gate.

**Done when**
- [ ] The panel opens on the new console — sidebar, header, framed panel — at the
      design's colours, type and spacing.
- [ ] The owner adds a user in a dialog and the link dialog follows on its own,
      with a copy button that works.
- [ ] No screen shows a per-user or per-connection number anywhere, and no model
      grew a field that could produce one.
- [ ] Every page loads from this host alone, proven with the machine's outbound
      network cut.
- [ ] Empty, loading and failure states are drawn for both screens: a fresh
      install shows an empty state that says what to do next, not a broken table.
- [ ] At 900px the sidebar becomes a top scroller and nothing runs off the side of
      the page.

acceptance: yes
On the stand, with nothing in it but the operator account, sign in. First judge it
empty: the console has to tell a first-time owner what to do next, not show blank
boxes. Add a user called `dima` from the header button — the link dialog should
appear by itself; copy the link and open it in another tab. It must resolve (the
empty stand has no node to offer yet, so an empty subscription is the correct
answer — a 404 or an error is not). Then go looking for anything the panel claims
to know about who connected, how long ago, or how much they used: it must not be
there, on any screen. Last, narrow the window below 900px and check the console is
still operable rather than merely still rendering.

---

## → M9 — The fleet screens, and the old page retires · planned 2026-09-08

Nodes, Hops, Transports and Keys & configs, with the add-node and establish-hop
dialogs. Same design, same rules as M8 — read its prose first, it carries the
constraints for all three of these milestones.

**The hop dialog is the biggest usability claim in the handoff.** Establishing a
hop asks 27 parameters today, all at once, in one flat form. The design asks three
— entry node, leaf node, transport — and puts the other 24 behind
`<details> advanced tuning — 12 parameters per end`, every field carrying its
transport default as a placeholder so an empty box visibly means "use the
default". This is the form the runbook has you open during a rotation, which is
the worst possible moment to read 27 labels.

**The old pages are deleted at the end of this milestone, not at its start.**
Until every action they carry has a new home, removing them removes the only way
to do the job.

### M9.1 — Nodes, with the add-node dialog

### M9.2 — Hops, with the establish-hop dialog and its advanced-tuning disclosure

### M9.3 — Transports — the read-only capability table

Including the "on a filtering network" column, and the row that says a protocol is
identified and blocked and must never be offered as an exit. That sentence is
transport metadata, not a case statement in a template: no template may name a
transport, which is the same hard rule the code lives under.

### M9.4 — Keys & configs

Fingerprints truncated, rotation in place. UI-PATTERNS §9: where key material
could appear, the panel prints the rule instead. Nothing displays a private or
preshared key — the API already withholds both, and the panel must not become the
place they surface.

### M9.5 — Retire `pages/index.html` and `pages/node.html`

**E2E:** none new — the behaviour is unchanged and only the markup moves. The
scenarios that already cover it must stay green against the new screens:
`test_a_replacement_node_and_a_protocol_from_the_panel.py`,
`test_the_panel_never_offers_a_blocked_protocol_as_working.py`,
`test_a_hop_never_reaches_a_friend.py` and
`test_rotation_does_not_move_the_link.py`. `make test-control` is the gate.

**Done when**
- [ ] Every action the old pages offered has a home on a new screen: add node,
      enable and disable a transport, apply, probe, set state, establish and tear
      down a hop, rotate keys, replace params.
- [ ] Establishing a hop asks three questions; the other 24 parameters are behind
      the disclosure, each showing its own transport's default as a placeholder.
- [ ] No template names a transport, a country, an address or a port.
- [ ] No key material appears anywhere in the panel; fingerprints are truncated.
- [ ] `pages/index.html` and `pages/node.html` are gone and nothing links to them.

acceptance: yes
On the stand, register a node, enable a transport on it and apply — every step
from the new screens, with no URL typed by hand. Then establish a hop between two
nodes and check the dialog lets you answer three questions and leave the tuning
alone. Open the transports screen: it must name a protocol the panel refuses to
offer as an exit and say why, in words. Then hunt for a private key anywhere in
the console — you must not find one. Applying will fail on the stand, because
there is no real host behind the node; that is expected, and what is being judged
is that the failure arrives on the screen in plain words instead of a blank page
or a raw error. If the failure is the wrong message about a draft node, that is
M4's known bug and not a finding here.

---

## → M10 — The two screens that need records this project does not keep · planned 2026-09-08

Audit log and Settings. Both ask for something that does not exist, and one of
them may be something the charter should refuse outright — which is why they are
last and not folded into M9.

**Audit log.** There is no audit trail anywhere in the tree; `grep -ri audit
control edge docs` returns nothing. Building one means a new table written on
every mutation. It is *not* a connection log — it records what the operator did,
never who dialed what — but it is still a new durable record naming friends and
times, sitting on the one machine most worth seizing, and the charter's whole
argument is that such records are *absent, so there is nothing to subpoena*.
Whether it exists at all, what it may record, and whether it keeps the operator's
own source address, is decision 8.

**Settings.** The design draws an Admins table (user / role / last login) and a
form for mesh name, subscription base URL and log retention days. There is one
operator, configured from the environment (`HASHI_OPERATOR_USERNAME`,
`HASHI_OPERATOR_PASSWORD_HASH`); more than one is a charter non-goal — *"One
operator, one fleet"* — and there is no log to retain, by construction. A form
that saves a value the process only reads from the environment at boot is a lie
told in a text field. The proposal is a Settings screen that shows what this
control plane is configured with and says where each value is actually changed,
with a single-row Admins table. Also decision 8.

### M10.1 — Settle what Settings can honestly show, and what it may change

### M10.2 — Settings, read-only wherever the value comes from the environment

### M10.3 — The audit trail, if decision 8 says there is one

### M10.4 — The audit log screen

**E2E:** none new if decision 8 says no. If it says yes, one scenario asserting
the audit trail contains no token, no subscription URL and nothing about a
connection — a record that grows those is the failure mode worth a test.
`make test-control` is the gate either way, and
`test_no_model_records_anything_about_a_connection` already stands over any new
model without being asked.

**Done when**
- [ ] Settings shows the owner what this control plane is actually configured
      with, and names where a value is changed when the panel cannot change it.
- [ ] Nothing on Settings claims to save a value the running process would not
      then use.
- [ ] Decision 8 is written down in `docs/decisions.md`, whichever way it went.
- [ ] If an audit trail exists, it holds no token, no subscription URL and nothing
      about who connected.

acceptance: yes
On the stand, open Settings and check that every value it shows is true of the
control plane you are signed into, and that anything it will not let you change
says where it is changed instead. If the audit log shipped, change two things
about the fleet, then open it: both must be named in plain words, with no token
and no subscription link anywhere in sight.

---

## → M11 — One script prepares a host to be a node · planned 2026-09-08

`edge/bootstrap/node_stack.py:212` refuses a node that has no docker, and says
why in as many words: *"hashi configures upstream data-plane containers and does
not install a container runtime for you."* That is the right boundary for the
library and it leaves a hole in the product. `scripts/panel-bootstrap.sh` brings
a control plane up in one command; a leaf has no equivalent, so every leaf host so
far was prepared by hand.

**A hand-prepared host is a host you cannot rebuild at three in the morning** —
which is precisely when you rebuild one. The charter's "destroy and replace in ten
minutes" is a claim about a *script*, and there isn't one.

**Owner's requirement, 2026-09-08:** every host configuration is reproducible from
this repository, and a new leaf comes up with one script. Nothing the fleet does
to a host by hand may stay by hand. **Sequenced first in the field run**, ahead of
M1: the two hosts it prepares are what M1, M2 and M3 are then verified on, and
writing the script while doing the work is the only way it ends up true.

### M11.1 — `scripts/node-bootstrap.sh` — docker, the key, the firewall, nothing else

No hashi code and no state. A node holds nothing that cannot be regenerated from
the control database, and this script must not invent the first exception.

### M11.2 — Make it idempotent, and say what it does not do

The cloud-level firewall — a provider's security groups — sits outside the host
and outside the script's reach. It gets named in the runbook, not silently
assumed, because a closed security group looks exactly like a broken transport.

### M11.3 — The runbook grows a leaf section

### M11.4 — Prove it on a host that has never run hashi

**E2E:** `tests/e2e/infra/`, following `test_panel_bootstrap.py`. The real proof is
an untouched host, which no suite rents; the scenario asserts what can be asserted
about the script itself. `make test-infra` is the gate.

**Done when**
- [ ] A fresh host becomes a usable node with one command, plus the provider's
      firewall.
- [ ] No step in the sequence survives only in someone's shell history.
- [ ] Running the script twice on the same host changes nothing and breaks
      nothing.
- [ ] `ufw logging off` is part of it — a node must never start collecting the one
      record the charter forbids.

acceptance: yes
Take a host that has never run hashi. Run the one script, then register it in the
panel and apply — it must become a working node without a second command typed on
the box itself. Then run the script again on that same host and check nothing
breaks and nothing changes. If a step still has to be done by hand, this milestone
is not done, however well the node works afterwards.

---

## → M12 — The acceptance hands must actually hold a browser · found in the field 2026-09-08

**Appended during the overnight field run, not planned.** Found by running
`scripts/acceptance/drive.py` for the first time against a stand that had just
come up cleanly. It is the same lesson as M1, M2 and M3, one layer further out:
everything checkable by *rendering* works, everything checkable only by *running*
does not — and this time the thing that did not run was the instrument the plan
intends to judge M8, M9 and M10 with.

**The bug.** `deploy/docker-compose.e2e.yml:70` pins the browser service to
`mcr.microsoft.com/playwright/python:v1.55.0-noble`. That image ships the browser
binaries under `/ms-playwright` and it ships `pip` — it does **not** ship the
`playwright` Python package. `drive.py` imports it at `serve()`:

```
ModuleNotFoundError: No module named 'playwright'
```

so every verb fails, and the stand around it is perfectly healthy while it does.

**Why it stayed invisible, and this is the part worth keeping.** `begin` starts
the in-container server with `stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL`
(`drive.py:469`), then waits for a socket that never appears and reports the one
thing it can still see:

```
[drive] action failed: the browser did not come up inside the stand
```

That message names the *symptom* and hides the *cause*, and it points at the
stand — which was fine. An agent reading it would go and debug compose, the
profile, the network and the health checks, all of them working, for as long as
its patience lasted. The traceback existed the whole time and had been thrown
away on the line above.

**Confirmed, not guessed:** installing `playwright==1.55.0` inside the running
container made `begin` and `open` succeed immediately, returning the panel's
accessibility tree and writing its screenshot. Nothing else was wrong.

### M12.1 — The browser image carries the package it is imported for

Build the browser service from a small Dockerfile rather than pulling the bare
upstream image, exactly as `deploy/docker/caddy.Dockerfile` already does and for
the recorded reason — *config must travel with the image*. The `playwright`
package version and the image tag are the same version and must not be able to
drift: derive one from the other with a build argument rather than writing
`1.55.0` twice.

Installing at container start instead is the wrong shape: it puts a package
index on the critical path of every acceptance run, and an acceptance stand that
cannot come up without the network is one more thing to debug at three in the
morning.

### M12.2 — A failed verb must report the cause, not only the symptom

`begin` discards the in-container server's stderr. Keep the diagnosis: capture it
and print it when the socket does not appear. "The browser did not come up inside
the stand" sent the reader to the one layer that was working.

### M12.3 — A check that the hands work, before a milestone leans on them

`stand.sh up` reports ready on a stand whose driver cannot take a single action.
Prove the instrument, not just the subject: the cheapest honest check is one real
verb through the real driver.

**E2E:** `tests/infra/`, beside `test_drive.py`, which already exists and did not
catch this — it tests the driver's argument handling on the host and never asks
whether the container can import what the driver imports. The assertion worth
adding is the one that would have gone red: the browser image the compose file
names can import `playwright`. `make test-infra` is the gate.

**Done when**
- [ ] `drive.py begin` succeeds against a freshly built stand with no package
      installed by hand.
- [ ] The playwright package version and the browser image tag cannot drift
      apart.
- [ ] A `begin` that fails prints why, not only that it did.
- [ ] Bringing the stand up and taking one real action is a single documented
      step, and something runs it.

acceptance: no
Its own proof is a verb that works, and every acceptance run from M8 onward
exercises it. A milestone whose subject is the acceptance instrument cannot be
judged by that instrument.

---
## Decisions needed from you

| # | Decision | Blocks |
|---|---|---|
| 1 | Charter amendment: panel leaves the public URL | M7 |
| 2 | Tailscale or Headscale | M7 |
| 3 | Behaviour when a hop is down — fail closed, or exit locally and say so | M3 |
| 4 | Whether to bump `xray-core` from the pinned `1.8.24` (roughly two years behind the ≥ `25.12.8` that 2026 field guidance names as the detection threshold). A data-plane pin bump has a security argument on both sides — new upstream means new defaults and new detectability | — |
| 5 | What to do with `/var/log/ufw.log` on the live host | M6 |
| 6 | What replaces the design's per-user numbers — "throughput now", "last seen", node "load" — and whether the Traffic screen is dropped outright. All four are charter non-goals; the design was drawn without the charter | M8 |
| 7 | Vendor Barlow and Barlow Condensed as woff2 files in the repository (OFL, a few hundred kilobytes), or drop to a system-font fallback and accept that the console is not quite the drawing. The design system's stylesheet fetches them from Google, which the panel must not do | M8 |
| 8 | Whether an audit log exists at all and what it may record, and what a Settings screen may change when the values come from the environment | M10 |
| 9 | The visible word for a person who uses the mesh: the design says "users", the charter and the whole codebase say "friends". Recommended: keep `friend` in the code, decide only the label | M8 |

**Answered by the owner on 2026-09-08**, ahead of the field run:

- **1 — yes.** The panel leaves the public URL; the charter is amended.
- **2 — Tailscale.** Chosen over Headscale with the lock-out risk below understood.
- **3 — fail closed.** No exit at all beats a silent Russian one.
- **5 — off and gone.** `ufw logging off`, and the existing file deleted. Both
  hosts are test hardware and their data is expendable.
- **6 — the proposal below**, as written.
- **7 — vendor the woff2 files.** The panel fetches nothing from a third party.
- **8 — a simple audit log**, and a Settings screen to match.
- **9 — "users".** The panel says users; `friend` stays the word in the models,
  the services, the API and the tests. The label is a template concern and does
  not travel into the code.
- **Still open: 4** (the `xray-core` pin), which blocks nothing.

**On decision 2, the trade-off worth restating:** Tailscale's coordination is a US
service that may be unreachable from Russia. If it is down exactly when an
emergency rotation is needed, you are locked out of your own panel — the failure
lands precisely on the scenario the panel exists for. **Headscale** (self-hosted
coordination) avoids that.

**On decision 6, what I would propose if you want a default:** keep all four
positions in the layout and fill them with facts the control plane already holds —
nodes online, active friends, hops established and transports enabled for the stat
cards; `added` instead of `last seen` in the friends table; drift against the
applied digest instead of node `load`. Drop the Traffic screen outright and give
its sidebar slot to nothing: a screen that exists to say "we do not measure this"
is an invitation to add the measurement later.

Still open from before: **C** and **E** in `docs/product/backlog.md`, both awaiting
you, E wanted by M4.

---

## What this plan does not cover

- **Criterion 1 — "survives a mobile whitelist shutdown".** Not reachable by any
  foreign box from any provider at any price: whitelist mode leaves roughly 57
  *Russian* services reachable. No item here moves it, and none pretends to.
- **Throughput and DPI survival.** The live client proves a tunnel carries traffic;
  it proves nothing about speed, or about how long this IP stays unblocked.
- **The second host.** Nothing here requires it, and M2 and M3 should land before
  it is rented.
- **A leaf node's console.** There is none, deliberately — a node runs only its
  data-plane container, exposes nothing for management, and never dials the control
  plane. Nothing to build.
