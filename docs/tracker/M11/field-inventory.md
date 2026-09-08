# M11 — field inventory of the two hosts, before anything was changed

**Taken:** 2026-09-08, read-only, before the first mutating command of the
overnight field run.

**Why the addresses are not here.** Both hosts' public addresses are node-record
and local-configuration data, never repository data — the same rule that keeps a
country, a provider or a port out of the code (`CLAUDE.md`, hard rules). This
file names the two hosts by the role the owner assigned them. Whoever reads it
gets the addresses from the node records or from their own untracked config.

---

## ENTRY host — Russia · entry node + control plane + panel

The role is new as of 2026-09-08. On the day of this inventory the box carried
none of it: it was somebody else's application server.

| | |
|---|---|
| OS | Ubuntu 24.04.4 LTS, kernel 6.8.0-111 |
| CPU / RAM | 2 vCPU · 3.8 Gi total, 3.0 Gi available |
| Disk | 29 G, 14 G free |
| Docker | 29.3.0, Compose v5.1.0 — **already present**, so `node-bootstrap.sh` has an idempotent path to exercise here |
| Access | `esinilyadev`, not root; in the `docker` group; passwordless sudo confirmed |
| Firewall | **`ufw` inactive**, and `/var/log/ufw.log` does not exist |
| Listening | `:22` sshd · `:8000` docker-proxy (foreign app) · `127.0.0.1:38281` VS Code remote server · systemd-resolve on loopback |

### What was running, and what deploys it

Two foreign compose projects, up three months, which the owner has confirmed are
dead:

| project | containers | published |
|---|---|---|
| `zhurabli_backend` | `zhurabli_app`, `zhurabli_db` (postgres:15-alpine) | `0.0.0.0:8000` |
| `zhuravli_bot` | `zhuravli-bot` | none |

**The trap, and it is the whole reason this section exists.** Neither project is
deployed by hand. Both are deployed by a self-hosted GitHub Actions runner
registered as a systemd service:

| service | state on the day | working tree |
|---|---|---|
| `actions.runner.earlzdev-zhurabli_backend.zhuravli.service` | loaded, **failed** | `~/backend-runner/_work/…` |
| `actions.runner.earlzdev-zhuravli_bot.zhuravli.service` | loaded, **active (running)** | `~/bot-runner/_work/…` |

Stopping the containers does not clear the host. The bot runner is live and
listening for jobs, so the next push to that repository would redeploy what was
removed — and the backend runner, though failed today, would take `:8000` back
the moment it is restarted. Both services are stopped and disabled as part of
this milestone; the compose projects go with them. **Nothing else is touched** —
in particular the VS Code remote server stays, because it may be how the owner
gets back in.

### Also present

`~/Hashi` — a 3.0 M checkout at `537f12f`, not deployed and not running. Left
alone.

---

## LEAF host — Amsterdam · exit only

Today it runs the whole product, control plane included. That moves to the entry
box; this host keeps only its data plane.

| | |
|---|---|
| OS | Ubuntu 22.04.5 LTS, kernel 5.15.0-130 |
| CPU / RAM | 1 vCPU · 957 Mi total, **445 Mi available**, 1.0 Gi swap |
| Disk | 20 G, 13 G free |
| Docker | 29.8.0, Compose v5.5.1 |
| Access | `root` |
| Firewall | **`ufw` active**, default deny in / allow out / deny routed. `22,80,443,49443/tcp` and `51820/udp` allowed |
| Logging | `ufw` logging already **off** — but `/var/log/ufw.log` still exists, **5840 bytes**, last written 12:49. Decision 5 says off and gone; the file is deleted in this run |
| Listening | `:22` sshd · `:80`,`:443` docker-proxy (Caddy) · `*:49443` xray · systemd-resolve on loopback |

### What was running

| project | containers | config |
|---|---|---|
| `hashi` | `hashi-control`, `hashi-db` (postgres:16.4-alpine), `hashi-caddy` (`:80`, `:443`) | `/opt/hashi-control/deploy/docker-compose.yml` + `docker-compose.public.yml` |
| `hashi-node` | `hashi-node-vless-reality-1` (`ghcr.io/xtls/xray-core:1.8.24`) | `/opt/hashi/docker-compose.yml` |

`/opt/hashi-control` is a full checkout **with no `.git`** — it was copied onto
the host, not cloned, which is exactly the "prepared by hand" shape M11 exists to
end. `/opt/hashi` is `root`-only (`0700`) and holds `docker-compose.yml` plus a
`conf/` directory: node state, all of it regenerable from the control database.
`~/Hashi` is a second, older copy of the checkout.

**The 463 Mi figure in the plan is confirmed and is the argument for the split.**
This box runs a control plane, Postgres, Caddy and a data plane in 957 Mi.

---

## What this changes about the plan

1. **M11 gets its idempotent path for free on the entry box** — Docker is already
   installed there, and `node-bootstrap.sh` must handle "already done" on a host
   that was prepared by somebody else, not only on a host it prepared itself.
2. **`ufw` is inactive on the entry box.** The runbook's `ufw enable` line runs
   there for the first time, which is precisely where M6.2's `ufw logging off`
   has to already be in place — otherwise the fleet creates the forbidden record
   on the Russian host, of all of them, while verifying that it does not.
3. **The provider firewall is a separate layer and is not visible from inside the
   host.** `ufw` being inactive on the entry box says nothing about whether the
   cloud security group lets a packet in. M11.2 names it; this run confirms it by
   probing from the leaf rather than trusting it.
