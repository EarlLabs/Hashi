# Warden — driving hashi from Kaizen's tracker

The project side of Kaizen's tracker v2 contract. With it running and approved,
you can say «попроси hashi добавить VLESS+Reality» to Кая (or use the panel) and
this repo's own fleet does the work.

## What it actually does

One translation, and nothing else:

```
Hub --Dispatch--> Warden --> claude -p "/develop <intent>"  (in this repo)
                     ^                      |
                     |                      v
              docs/tracker/{task}/status/*.yml   ← the fleet writes these
                     |
              push_status --> Hub --> the panel / Кая
```

The fleet is already defined in `.claude/` — personas, commands, rulebooks, the
review loop. The Warden does not reimplement any of it; it maps a Directive
`kind` to the matching slash command and forwards status.

| Directive kind | Runs |
|---|---|
| `develop` `fix` `refactor` `epic` `review` `research` `product` | the same-named slash command |

**There is no `/next` in this project, on purpose.** Work *arrives* by Dispatch.
`/next` polls a tracker CLI for a queue to pop, and hashi has no such CLI —
installing it would create a second, competing source of work.

## Run it

```bash
# 0. The Kaizen stack must be up — this joins its network.
cd ~/stuff/projects/Kaizen && make up

# 1. Refresh the vendored kit and start the Warden.
cd ~/stuff/projects/hashi
make warden-sync
make warden-up

# 2. It is now PENDING. Approve it — any of these:
#    · ask Кая: «какие проекты просятся в трекер?» → «одобри hashi»
#    · the panel: http://localhost:8770/panel → Fleet → Approve
#    · curl -X POST -H "Authorization: Bearer $TRACKER_ADMIN_TOKEN" \
#           http://localhost:8770/projects/hashi/approve

make warden-logs
```

**One-time CLI login** (same as Кая's, and for the same reason — the Max
subscription, not API billing):

```bash
docker compose -f deploy/warden/docker-compose.yml exec warden claude
```

`DISABLE_AUTOUPDATER=1` is set in both the image and the process environment.
Without it the CLI migrates itself into the mounted config volume, and the next
volume wipe deletes the binary.

## Why the kit is vendored

`deploy/warden/vendor/infra/` is a copy of Kaizen's `infra/wardenkit` and
`infra/proto/gen` — the only things a project imports from Kaizen. hashi is a
separate repository and there is no package index to install them from, so they
are vendored, stamped with the source commit in `vendor/KAIZEN_COMMIT`, and
refreshed with `make warden-sync`.

The copy is 120 KB and its whole runtime dependency set is `grpcio` + `protobuf`
— wardenkit hand-rolls its flat-YAML reader precisely so that stays true.

**Refresh it when Kaizen's `warden.proto` or `wardenkit` changes.** A stale copy
fails at the wire, not at import, so it will look like a Hub problem.

## What to think twice about

- **The repo is mounted read-write.** An unattended fleet has the same write
  access to this working tree that you do. That is the point, and it is also the
  risk — `MAX_CONCURRENT: 1` is set because the fleet edits a real tree with no
  worktree isolation, so two Directives at once would interleave their diffs.
- **Tool permissions are allow-listed**, not bypassed (`ALLOWED_TOOLS` in
  `warden.py`). `--dangerously-skip-permissions` is refused when running as root
  anyway, and a list is something a reviewer can check.
- **A finished Directive reports `review`, never `done`**, whenever it changed
  the tree. The changes sit in the working tree and no human has looked at them;
  only the owner closes that gap.
- **Nothing here touches the VPN product stack.** `make up` / `make warden-up`
  are independent, which is what you want while the project is under
  construction.
