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

---

## What was changed on the hosts during this run, and what was confirmed

### Entry host — cleared

- Both self-hosted runner services **stopped and disabled**
  (`systemctl is-enabled` → `disabled` for each). The backend unit's `failed`
  state was reset. No `Runner.Listener` process survives.
- Both compose projects **removed** (`docker compose down --remove-orphans`).
  `docker compose ls -a` is empty and `docker ps -a` is empty.
- **`:8000` is free.** The only listeners left are sshd and the VS Code remote
  server on loopback, which the owner asked to keep.
- **Their volumes were deliberately kept** — `zhurabli_backend_app_logs` and
  `zhurabli_backend_postgres_data`. "Remove the compose projects and the runner
  services, nothing else" is satisfied without them, and a volume is the one
  thing here that could not be recreated if the owner turns out to want it.
  Deleting them is a one-line follow-up whenever they say so.
- The runner *registrations* still exist on the GitHub side and will simply
  show as offline. Removing them needs a token, which no agent reads.

### Firewall logging — both hosts, before any traffic test

`ufw logging off` on both. The leaf's 5840-byte `/var/log/ufw.log` is deleted.
Nothing this run does creates a new record.

**A finding that belongs to M6, and it is the more useful half.** Deleting
`/var/log/ufw.log` is *not sufficient*, and the runbook implies it is. The same
lines are written by rsyslog and journald as well — on the leaf, 22 identical
`UFW …` records with source addresses were still present in `/var/log/syslog`,
`/var/log/kern.log` and the kernel journal after `ufw.log` was gone. They predate
this run. **The lasting fix is not a cleanup at all**: `ufw logging off` must be
in place *before* `ufw enable` ever runs, which is exactly what M11's script and
M6.2's runbook line are for. A host that never logs has nothing to purge from
four places.

### Provider firewall — confirmed, not trusted

Probed from the **leaf** (Amsterdam), so this is a genuinely external vantage and
not a loopback or same-VPC shortcut. A listener was bound on the entry host, one
port at a time, and removed afterwards:

| port | result from Amsterdam |
|---|---|
| `22/tcp` | reachable |
| `443/tcp` | reachable |
| `8443/tcp` | reachable |
| `49443/tcp` | reachable |
| `51820/udp` | reachable — replied through the tunnel port the hop needs |

The cloud security group in front of the entry host is genuinely permissive.
**This is worth the ten minutes it cost:** a closed security group and a broken
transport look identical from the panel, and every later failure tonight can now
be attributed to the layer that actually caused it.

`443/tcp` first appeared closed for a reason worth recording — the probe process
was running as the non-root account and simply could not bind a privileged port.
That is what a false negative looks like here, and it would have been read as
"the provider blocks 443".
