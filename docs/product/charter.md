# hashi — charter

## One-liner

A self-hosted, multi-protocol VPN for its owner and ~30–50 friends that keeps
working from Russia: a Russian entry node fronting foreign exit nodes, where both
**nodes and protocols are data** — either can be added, swapped or destroyed in
minutes without a user touching their device.

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

1. **Survives a whitelist shutdown.**
   *Given* a Russian mobile network under whitelist restriction,
   *when* I connect using my hashi subscription,
   *then* traffic reaches a foreign site via the Russian entry node and a foreign
   leaf, because the only address my phone talks to is a Russian one.

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
| Control plane | Python 3.12, FastAPI, SQLAlchemy async, PostgreSQL | Matches what the owner already reads and maintains in Kaizen; one language across the repo means fewer rulebooks and no context switch |
| Admin panel | Server-rendered Jinja + HTMX | An internal panel for one operator. Keeps the panel inside the `control` zone instead of buying a frontend zone, a build pipeline and two more agents |
| Data plane (primary) | Xray-core: **VLESS + Reality + XTLS-Vision** | The only family reported working reliably against TSPU in 2026: Reality borrows a real third-party TLS handshake, so active probing sees the decoy site, not us |
| Data plane (fallback) | **AmneziaWG** (obfuscated WG), VLESS+WS+TLS behind a camouflage site | Independent failure modes: when TLS handshakes are being degraded, a UDP-shaped transport may live, and vice versa |
| Plain WireGuard | **Only for links that never cross the border** | It is protocol-blocked by TSPU; using it for the entry→leaf hop would defeat the design |
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
| `control` | Control plane: API, admin panel, subscription delivery, persistence | `control/**`, `tests/control/**` | `01-control-rulebook.md` | `make test-control` |
| `edge` | Data plane: transport profiles, node bootstrap, config rendering, health | `edge/**`, `tests/edge/**` | `02-edge-rulebook.md` | `make test-edge` |
| `infra` | Deployment and operations: compose stacks, Caddy, CI, backups, secrets | `deploy/**`, `.github/**`, `Makefile`, `tests/infra/**` | `04-infra-rulebook.md` | `make test-infra` |

`docs/**` and `.claude/**` belong to no zone: they are owner and architect
territory, written by whoever the workflow assigns.

Path sets checked pairwise — no overlap.

## Fleet

Eight agents. Kit v1 identities, assigned in order.

| Agent | Role | Zone | Model |
|---|---|---|---|
| `architect-xavier` | Architect; also acts as every dev's lead | all | opus |
| `security-holmes` | Security | all | opus |
| `product-owner-ohno` | Product owner — owns the backlog from this charter | — | opus |
| `researcher-curie` | Researcher — what still works against TSPU this month | — | opus |
| `dev-anderson` | Developer | `control` | opus |
| `dev-neumann` | Developer | `edge` | opus |
| `dev-potts` | Developer (infra identity) | `infra` | opus |
| `reviewer-granger` | Reviewer | all three zones | sonnet |

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
