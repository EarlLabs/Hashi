# hashi — charter

## One-liner

A self-hosted, multi-protocol VPN for its owner and ~30–50 friends: a Russian
entry node fronting foreign exit nodes, where both **nodes and protocols are
data** — either can be added, swapped or destroyed in minutes, by one script,
without a user touching their device.

Surviving Russian DPI is **phase 2**, not phase 1 — see *Success criteria*. The
topology is built for it from day one; the transports that defeat it are not
shipped first.

## Users and jobs

| User | Job |
|---|---|
| Owner (operator) | Add/remove nodes and transports, watch node health, issue and revoke access, rotate anything that gets blocked — all from one admin panel |
| Friends (~30–50) | Paste one subscription URL into a standard client (Amnezia / Hiddify / v2rayNG / streisand) once, and thereafter just connect; pick an exit country |

Friends never receive raw configs and never re-add anything. The subscription URL
is the only artefact they hold — that is what makes "swap a protocol in minutes"
real rather than theoretical.

## Non-goals

- **No payments or billing.** The paid future is deliberately out of v1; it
  changes the legal exposure and it can be added on top of a working system.
- **No client application of our own.** Standard subscription formats only, so
  every existing client works.

  **Open question, and the biggest one in phase 1** (raised 2026-08-02 by the
  phase-1 protocol choice, against decision D of 2026-08-01 in
  `docs/product/backlog.md`): a v1 subscription is a base64 list of client-entry
  URIs, and **AmneziaWG has no URI form** — it is a config file, not a link.
  Shipping WireGuard and AmneziaWG as first-class transports therefore needs an
  answer to *how they reach a friend in one link*. Either the target client
  (Happ) accepts a richer subscription than a base64 URI list, or the delivery
  endpoint serves per-client config files behind the same token, or criterion 5
  ("onboarding is one link") weakens for these transports. **Which one is a
  product decision, not an implementation detail** — it must be settled with a
  real client before the first transport is built, not discovered during it.
- **No reseller / multi-tenancy.** One operator, one fleet.
- **No traffic logging, no DNS logs, no per-user analytics.** Not "off by
  default" — absent, so there is nothing to seize or subpoena.
- **No per-user traffic quotas** in v1.
- **No cloud-provider API drivers** in v1. Bring-your-own-SSH only: any host,
  zero API lock-in, and it stays the fallback when an API driver later breaks.
- **No Kubernetes** — see Stack for the reasoning.
- **No public signup**, and **no public advertising of the service** (art. 14.3
  KoAP now covers VPN advertising).

## Success criteria

**Two phases, decided by the owner on 2026-08-02.** Build a working
multi-protocol VPN first; make it survive Russian DPI second. The criteria are
**not renumbered** — the backlog traces to these numbers — but they are split:

| Phase | Criteria | Means |
|---|---|---|
| **1 — it works** | 2, 3, 4, 5, 6 | A friend connects with a stock client, picks an exit, and any node or protocol can be swapped without them touching anything. Verified on an unrestricted network |
| **2 — it survives** | **1** | The same system keeps working from a Russian mobile network under whitelist restriction and TSPU inspection |

Nothing in phase 1 may make phase 2 unreachable: the entry→leaf topology, the
"nodes and protocols are data" rule and the no-logging rule are all phase-1
constraints precisely because retrofitting them later is a rewrite. What phase 1
does **not** require is that any given transport survive DPI today.

1. **Survives a whitelist shutdown.** — **PHASE 2, deferred.**
   *Given* a Russian mobile network under whitelist restriction,
   *when* I connect using my hashi subscription,
   *then* traffic reaches a foreign site via the Russian entry node and a foreign
   leaf, because the only address my phone talks to is a Russian one.

   Deferred deliberately, not dropped. Until it is taken up, "hashi works" means
   "works on a network that is not actively blocking it" — which is a real,
   testable, useful product for anyone abroad or on an unrestricted Russian
   connection, and an honest half-answer for anyone else. Say so in that many
   words; never report phase 1 as though it settled this.

2. **A node is replaceable in ten minutes.**
   *Given* a leaf node has been blocked,
   *when* I destroy it and bootstrap a replacement from the panel,
   *then* it is serving traffic in under 10 minutes and **no user changes
   anything** — their subscription simply resolves to the new node.

3. **A protocol is swappable without touching users.**
   *Given* a transport that ships with hashi (e.g. AmneziaWG) is not enabled,
   *when* I enable it on a node from the panel,
   *then* it is live and present in every subscriber's config at their next
   refresh, with no code change and no redeploy.

4. **A new protocol is one package, not surgery.**
   *Given* a protocol hashi has never supported (e.g. Hysteria2),
   *when* a developer adds one transport-profile package,
   *then* it is selectable in the panel without modifying the control plane's
   core, the subscription renderer, or any other transport.

5. **Onboarding is one link.**
   *Given* a new friend,
   *when* I issue them a subscription URL,
   *then* they connect from Russia with an unmodified stock client and can choose
   an exit country.

6. **Revocation is total.**
   *Given* a user must lose access,
   *when* I revoke them,
   *then* their credentials stop working on **every node and every protocol**,
   not just the one they were last seen on.

## Stack and deployment

Nothing here re-implements a proxy. The product is the orchestration around
proven data-plane software; the data plane itself is upstream code we configure.

| Layer | Choice | Why |
|---|---|---|
| Control plane | Python 3.14, FastAPI, SQLAlchemy async, PostgreSQL | Matches what the owner already reads and maintains in Kaizen; one language across the repo means fewer rulebooks and no context switch. **3.14, not the 3.12 named at approval**: 3.12 is not installed on the owner's machine and 3.14 is, and a local venv on a different minor than the container is the trap where "works locally" and "works in the stack" quietly diverge |
| Admin panel | Server-rendered Jinja + HTMX | An internal panel for one operator. Keeps the panel inside the `control` zone instead of buying a frontend zone, a build pipeline and two more agents |
| Data plane, **phase 1** | **WireGuard** and **AmneziaWG**, both first-class and both shipped | Owner's call, 2026-08-02. They are the fastest route to a working multi-protocol fleet: mature, scriptable, and a client the owner already uses speaks them. Neither survives TSPU — see the row below — and that is accepted while criterion 1 is deferred |
| Data plane, **phase 2** | Xray-core: **VLESS + Reality + XTLS-Vision**; VLESS+WS+TLS behind a camouflage site | The only family reported working reliably against TSPU in 2026: Reality borrows a real third-party TLS handshake, so active probing sees the decoy site, not us. This is what criterion 1 will be built on |
| Plain WireGuard **from Russia** | Known-blocked, shipped anyway in phase 1 | TSPU protocol-blocks it, so it will not carry traffic from a restricted Russian network. It works everywhere else, and phase 1 is explicitly not about the restricted case. **Never present it to a friend as though it will work from a Russian mobile network** |
| Entry→leaf hop | **Never plain WireGuard**, in any phase | That hop crosses the border by definition, so a protocol-blocked transport there defeats the topology even in phase 1 |
| Reverse proxy | **Caddy** — control plane + node camouflage fronts; **never in front of Reality** | Automatic ACME and a tiny config where a proxy helps. Reality *is* the TLS terminator; fronting it breaks the property that makes it work |
| Node bootstrap | SSH + Ansible-style idempotent bootstrap; nodes run docker compose | Nodes are cattle with fixed identity, not a scheduling pool |
| Orchestration | **No Kubernetes** | On edge nodes it would mean a persistent, fingerprintable control channel from every node — including across the Russian border — to a fixed endpoint, which is precisely what gets a node burned; and it inverts the model, since a node's identity *is* its workload. On the control plane it buys HA that 30–50 users do not need. The app stays 12-factor, so k8s later is a deployment change, not a rewrite. Revisit at paying users + multi-region control plane |

**Deployment topology.** Location is a deploy-time choice everywhere; no
component hardcodes a country or a provider.

- **Entry node**: inside Russia. Under whitelist mode, foreign IPs are dropped
  inside the operator's network before the border, so a Russian address is the
  only thing that survives — this is the load-bearing reason for the hop, not
  latency.
- **Leaf nodes**: outside Russia, any provider reachable over SSH.
- **Delivery endpoint** (subscription URLs): must be reachable *from inside
  Russia* — otherwise friends cannot refresh their configs at exactly the moment
  a node has been blocked and they most need to. It may be co-located on the
  entry node.
- **Database and admin panel**: owner's choice at deploy time. If placed inside
  Russia, secrets are encrypted at rest with a key that does not live on that
  host — that box holds every user credential and every node key, and Russian
  hosters are now obliged to terminate clients running bypass infrastructure.
- **Public URL**: required for the delivery endpoint and the panel (behind auth).

**Everything is deployed by one script.** Owner's requirement, 2026-08-02. Two
of them, and no third path:

| Script | Brings up | Run when |
|---|---|---|
| node bootstrap | one leaf or one entry node, from a bare host to serving traffic | a node is added or replaced |
| panel bootstrap | the control plane, its database and the delivery endpoint | first install, a move, a rebuild from backup |

What "one script" has to mean, or it is not worth having:

- **Idempotent.** Running it twice changes nothing the second time. This is what
  makes "replace a node in ten minutes" (criterion 2) a script and not a
  procedure someone follows carefully at 3am.
- **No interactive questions.** Every input arrives as a node record or an
  environment file, so the same run works from the panel and from a shell.
- **Verifies before reporting success.** It ends by checking the daemon accepts
  its own config and the node answers a health probe — a script that reports
  success on a host that is not serving is worse than one that fails.
- **The panel's script never generates the secret key on the host it installs.**
  If the panel sits on the entry node inside Russia, the key that encrypts every
  node credential must arrive from outside it — see the topology note above.

## Backups

Owner's requirement, 2026-08-02. Absent from the first version of this charter,
which was a hole: the control plane's database holds every friend's credential
and every node key, and losing it means re-issuing to all 30–50 people by hand.

| What | Why it must survive |
|---|---|
| Control-plane database | friend records, node inventory, which transports are enabled where |
| Node and transport secrets | Reality private keys, WG keys, SSH keys — encrypted at rest, and the backup is encrypted with a key **not stored beside it** |
| Panel configuration | so the panel script can rebuild a working install, not an empty one |

Rules:

- **Nodes are not backed up.** They are cattle — a lost node is replaced by the
  bootstrap script, which is exactly what criterion 2 already demands. Backing
  one up would create a second source of truth for what a node is.
- **A backup that has never been restored is not a backup.** Restoring into a
  disposable stack is what proves it, and that belongs in the e2e suite.
- **Never back up what is never collected.** There are no traffic, DNS or
  connection logs to lose, and a backup must not become the place they appear.

## Data

| Data | Real? | Notes |
|---|---|---|
| Friend records | nickname + credentials + expiry only | No names, no emails, no phone numbers, no payment data |
| Node inventory | real | Host, SSH key, location label, enabled transports |
| Node & transport secrets | real from day one | Reality private keys, WG keys, SSH keys — encrypted at rest, never in git |
| Traffic logs, DNS logs, connection history | **never collected** | Absent by construction. Health checks report liveness, not who connected |

## Budget

No owner-imposed ceiling on tokens or wall-clock. The discipline is scope per
task, not a cap: one backlog item per `/develop` run, and the PO slices the
backlog so that any single item is independently verifiable.

## Autonomy

**Agents decide alone:** code, database schema, transport-profile design, tests,
documentation, local compose changes, anything runnable on the owner's machine.

**Agents must ask the owner:**
- spending money (renting any host)
- touching a live node, a real provider account, or real user credentials
- exposing a port to the public internet
- creating a remote repository, pushing, or publishing anything
- any change to what data is collected or retained

## Zones

| Key | Label | Paths | Rulebook | Verify |
|---|---|---|---|---|
| `control` | Control plane: API, admin panel, subscription delivery, persistence | `control/**`, `tests/control/**`, `tests/e2e/control/**` | `01-control-rulebook.md` | `make test-control` |
| `edge` | Data plane: transport profiles, node bootstrap, config rendering, health | `edge/**`, `tests/edge/**`, `tests/e2e/edge/**` | `02-edge-rulebook.md` | `make test-edge` |
| `infra` | Deployment and operations: compose stacks, Caddy, CI, backups, secrets | `deploy/**`, `.github/**`, `Makefile`, `scripts/**`, `.e2e/**`, `.env.example`, `tests/infra/**`, `tests/e2e/infra/**` | `04-infra-rulebook.md` | `make test-infra` |

`docs/**` and `.claude/**` belong to no zone: they are owner and architect
territory, written by whoever the workflow assigns.

Path sets checked pairwise — no overlap.

## Fleet

Eight agents. Kit v1 identities, assigned in order.

| Agent | Role | Zone | Model |
|---|---|---|---|
| `architect-xavier` | Architect; also acts as every dev's lead | all | opus |
| `security-holmes` | Security | all | sonnet |
| `product-owner-ohno` | Product owner — owns the backlog from this charter | — | opus |
| `researcher-curie` | Researcher — what still works against TSPU this month | — | sonnet |
| `dev-anderson` | Developer | `control` | opus |
| `dev-neumann` | Developer | `edge` | opus |
| `dev-potts` | Developer (infra identity) | `infra` | opus |
| `reviewer-granger` | Reviewer | all three zones | sonnet |

**Models and effort are a budget decision, revisited 2026-08-02.** The
subscription — not the machine — is what limits how often the fleet can run at
all, so three of eight personas are sonnet, conversation (`ask`) runs on sonnet,
and reasoning effort defaults to `low` (`CLAUDE_EFFORT` in
`deploy/warden/docker-compose.yml`). That is the right setting while the fleet
writes plans, decisions and research. **Raise the effort before M1 starts
producing code:** effort not spent writing is effort a reviewer pays back with
interest. Xavier and the three developers stay on opus for the same reason.

**Deliberately omitted:**

- **No leads.** Three zones with one developer each; a lead would have one report
  and add a hop. The architect is each developer's escalation path instead.
- **No second reviewer.** One reviewer holds all three zones. If `control`
  (Python service) and `edge` (network/proxy configuration) prove too far apart
  in practice, `reviewer-mcgonagall` is the documented next addition.
- **No `analyst-lovelace`.** The owner wants a product layer, not living specs;
  the PO's backlog is the source of truth.
- **No `designer-davinci` / `ui-reviewer-rams`.** There is a UI, but no design
  system — and an operator panel for one person does not justify one.

**Commands installed:** `/product`, `/develop`, `/fix`, `/refactor`, `/epic`,
`/brainstorm`, `/review`, `/abort`, `/doc`, `/research`.
**Not installed:** `/analyze` (needs the analyst), `/design` (needs the design
personas), `/next` (needs a tracker *service*; this project has tracker files
only, so there is no queue to pop).

## Defaults assumed

- Branches `main` + `develop`
- Tracker root `docs/tracker`, product root `docs/product`, specs `docs/specs`
- One e2e scenario per acceptance criterion; unit tests only for pure branchy logic
- Agent reports, task files and commit messages in **English**; code and comments
  in English
- Personas named from the kit's identity list, never invented

## Context that shaped this charter (July 2026)

- WireGuard, OpenVPN, L2TP and SOCKS5 are protocol-blocked by TSPU, which covers
  >95% of Russian traffic. HTTPS-shaped transports are what survive.
- In May 2026 RKN escalated to ASN- and subnet-level blocking plus selective TLS
  handshake degradation — so **rotation beats cleverness**, which is why node and
  protocol agility is criterion 2 and 3 rather than a later feature.
- Mobile whitelist shutdowns drop foreign IPs inside the operator network; only
  Russian addresses pass.
- Russian hosting providers became legally responsible for cutting off clients
  who host bypass tooling ("anti-fraud 2.0"), and Yandex Cloud expanded its right
  to block clients on state instruction from 28 April 2026. Hence: the entry node
  is disposable by design, and no component assumes a specific provider.
- Using a VPN is not itself an offence in Russia; art. 13.53 KoAP penalizes
  deliberate access to listed extremist material *via* bypass tools, and art. 14.3
  covers VPN advertising. Non-commercial use among friends is the low-exposure
  shape — which is why billing is a non-goal and advertising is forbidden.
