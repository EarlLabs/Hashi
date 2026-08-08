# Warden — driving hashi from Kaizen's tracker

The project side of Kaizen's tracker v2 contract. With it running and approved,
you can say «попроси hashi добавить VLESS+Reality» to Кая (or use the panel) and
this repo's own fleet does the work. hashi runs **solo topology**: the fleet is
one persona, `alfred` — display name "Ohno" (plus `reviewer-strict`, review-only, no edit tools).

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

The fleet is already defined in `.claude/` — the `alfred` persona (display name "Ohno"), commands,
rulebooks, the review-loop skill. The Warden does not reimplement any of it; it
maps a Directive `kind` to the matching slash command (or, for `ask`/`converse`,
to a direct conversation with `alfred` — no pipeline, no files) and forwards
status.

| Directive kind | Runs |
|---|---|
| `ask` | a text answer from `alfred` — no pipeline, no PR |
| `converse` | a live back-and-forth with `alfred` until the owner says «выход» |
| `develop` `fix` `refactor` `epic` `review` `research` `brainstorm` | the same-named slash command |

**There is no `/next` in this project, on purpose.** Work *arrives* by Dispatch.
`/next` polls a tracker CLI for a queue to pop, and hashi has no such CLI —
installing it would create a second, competing source of work.

## Run it

This is now its own stack, with its own Makefile and its own `.env` — always
run these from **this directory**, not the repo root:

```bash
# 0. The Kaizen stack must be up — this joins its network.
cd ~/stuff/projects/Kaizen && make up

# 1. Start the Warden (from THIS directory).
cd ~/stuff/projects/hashi/deploy/warden
make up

# 2. It is now PENDING. Approve it — any of these:
#    · ask Кая: «какие проекты просятся в трекер?» → «одобри hashi»
#    · the panel: http://localhost:8770/panel → Fleet → Approve
#    · curl -X POST -H "Authorization: Bearer $TRACKER_ADMIN_TOKEN" \
#           http://localhost:8770/projects/hashi/approve

make logs
```

**One-time CLI login**, still from `deploy/warden/` (same reason as Кая's — the
Max subscription, not API billing). Until this runs, every Directive fails with
"Not logged in":

```bash
make login
```

`DISABLE_AUTOUPDATER=1` is set in the process environment — without it the CLI
migrates itself into the mounted config volume, and the next volume wipe
deletes the binary.

`make up` chowns the state volume before starting — it is created root-owned
and the container runs as your uid (`HOST_UID`/`HOST_GID`, read automatically).
Started any other way, the entrypoint refuses with the exact `docker run …
chown` command to run by hand.

## Why the kit is vendored

`deploy/warden/vendor/infra/` is a copy of Kaizen's `infra/wardenkit` and
`infra/proto/gen` — the only things a project imports from Kaizen. hashi is a
separate repository and there is no package index to install them from, so they
are vendored, stamped with the source commit in `vendor/KAIZEN_COMMIT`, and
refreshed with `make vendor-kit` (from this directory; needs a local Kaizen
checkout, override with `KAIZEN=/path/to/Kaizen`). A deploy host does not need
this target — the vendored copy is committed.

The copy is 120 KB and its whole runtime dependency set is `grpcio` + `protobuf`
— wardenkit hand-rolls its flat-YAML reader precisely so that stays true.

**Refresh it when Kaizen's `warden.proto` or `wardenkit` changes.** A stale copy
fails at the wire, not at import, so it will look like a Hub problem.

## What to think twice about

- **The repo is mounted read-write.** An unattended fleet has the same write
  access to this working tree that you do. That is the point, and it is also the
  risk — `MAX_CONCURRENT: 1` is set because the fleet edits a real tree with no
  worktree isolation, so two Directives at once would interleave their diffs.
- **`GH_TOKEN` never reaches an agent.** The entrypoint stores it in `gh`'s own
  config and drops the variable before exec'ing the Warden — `printenv GH_TOKEN`
  inside the container returns nothing.
- **A finished Directive reports `review`, never `done`**, whenever it changed
  the tree. The changes sit in the working tree and no human has looked at them;
  only the owner closes that gap.
- **Nothing here touches the VPN product stack.** `make up` from the repo root
  (the app) and `make up` from here (the fleet) are independent, which is what
  you want while the project is under construction.
- **`warden-scenarios` (fake-pipeline contract tests) is currently retired.**
  `WARDEN_FAKE_PIPELINE` doesn't exist in kit v4's `warden.py` — the hand-rolled
  pipeline it hooked into was replaced by the shared `ClaudeRunner`.
  `scenarios.py` is kept but has nothing to drive it against; needs a follow-up
  decision (a real fake-pipeline hook upstream, or a different way to
  contract-test the Hub↔Warden path) rather than a patch here.
- **This project now runs `dind`** (`hashi-dind`, joined only by `warden` over
  its own `dind-net`) so `/e2e` can boot hashi's own compose stack from inside
  the fleet container — see `.e2e/profile.yml` and `docs/e2e/README.md` in
  Kaizen. Nothing else has a route to it or to the host's real docker daemon.
