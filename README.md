# hashi

A self-hosted, multi-protocol VPN for its owner and a small circle of friends,
built to keep working from Russia: a Russian entry node fronting foreign exit
nodes, where **both nodes and protocols are data** — either can be added, swapped
or destroyed in minutes without anyone touching their device.

Not a product, not a business, not advertised. See
[`docs/product/charter.md`](docs/product/charter.md) for what it is and — more
usefully — what it is deliberately not.

## Status

**Scaffold.** The repository boots and verifies; it does not yet do anything
useful. Concretely, what exists today:

- a control-plane application that serves `/healthz` and nothing else
- a transport registry that discovers profile packages — with zero profiles
  implemented
- a compose stack (Postgres + control plane + Caddy) that builds and starts
- three zone verification commands that run and pass

What does **not** exist: persistence, authentication, the admin panel,
subscription delivery, node bootstrap, and every transport. Those are the
backlog.

## Run it

```bash
make setup      # create .venv and install dependencies (needs Python 3.14)
make test       # verify every zone
make up-dev     # build and start the stack, ports on 127.0.0.1 only
curl -fsS http://127.0.0.1:54100/healthz
make down
```

`make up` starts the same stack in production shape — **nothing published**. That
is deliberate: publication is a decision made where the stack is deployed, not a
leftover from a laptop.

## Verify it

| Command | Covers |
|---|---|
| `make test-control` | the control plane — API, panel, delivery, persistence |
| `make test-edge` | the data plane — transport profiles, rendering, bootstrap |
| `make test-infra` | the deployment description — exposure, healthchecks, pinning |
| `make test` | all three, statically — no Docker needed |
| `make test-e2e` | acceptance scenarios, against the disposable stack `make e2e-up` starts |

A green suite proves the code holds together. It proves nothing about whether a
transport survives DPI, and nothing about the charter's first success criterion —
that is a field observation on a real Russian mobile network, and no test in this
repository can stand in for it.

## Ports

Published ports live in the block **54100–54299**, bound to `127.0.0.1` only and
driven from `.env`. Nothing here uses a service's default, so this stack can run
alongside any other project on the same machine.

| | dev | e2e |
|---|---|---|
| control HTTP | `54100` | `54200` |
| Postgres | `54132` | `54232` |

## Layout

| Path | Zone | Owner |
|---|---|---|
| `control/` | `control` | Thomas Anderson (`dev-anderson`) |
| `edge/` | `edge` | John von Neumann (`dev-neumann`) |
| `deploy/`, `Makefile`, `.github/` | `infra` | Pepper Potts (`dev-potts`) |
| `docs/` | — | the owner and the architect |

Each zone has an `AGENTS.md` next to its code and a rulebook in
`.claude/projects/`. The fleet and how it coordinates are described in
[`.claude/workflow.md`](.claude/workflow.md).

## Working on it

Open a session in this directory — the agent fleet lives in *this* repo's
`.claude/`:

- `/product` — plan or re-plan the backlog from the charter
- `/develop <task>` — build one backlog item, end to end
- `/fix <bug>`, `/refactor <target>`, `/research <question>`

Or drive it remotely: `deploy/warden/` registers hashi with Kaizen's tracker, so
Кая and the panel can dispatch work to this fleet. See
[`deploy/warden/README.md`](deploy/warden/README.md). Work arrives by dispatch,
which is why there is no `/next` here — nothing polls a queue.

## Legal note

Running a VPN for personal use is not an offence in Russia. Two things are:
deliberately accessing material on the federal extremist list through a bypass
tool (art. 13.53 KoAP), and **advertising** VPN services (art. 14.3). This project
is not advertised and has no public signup — both are charter non-goals, and
neither is a detail to be relaxed later without deciding to.
