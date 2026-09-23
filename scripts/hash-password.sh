#!/usr/bin/env bash
# WHAT: prints the line that goes in HASHI_OPERATOR_PASSWORD_HASH, on a machine that
#       has nothing installed but a container runtime.
# WHY:  the restore runbook asks for four values in .env and says "nothing else is
#       needed". One of the four could not be produced on the machine it is needed on.
#       Measured on a rented Ubuntu 22.04 during M28's bare-host walk:
#
#         python3 -m control.cli hash-password   ->  ModuleNotFoundError
#         make setup                             ->  python3.14: No such file or directory
#
#       The hash is a scrypt digest from control/app/crypto.py, so producing it needs
#       this project's code, its dependencies and Python 3.14 — which on a bare host
#       means a second working computer. That is the gap between "the operator reads the
#       command" and "the operator has another machine", and it sits in the middle of a
#       rebuild after a seizure.
#
#       The control image has all three, and `make restore-from-bucket` builds it anyway.
#       Same answer this project already gives for pg_dump (the db container) and age
#       (the control container): the tool lives where the stack lives, and the host needs
#       nothing new. The ordering works out — the image is built from a checkout and
#       needs no env file to build, so this runs BEFORE .env can be filled in.
# HOW:  ./scripts/hash-password.sh   (or: make hash-password)
#
#       It prompts twice, prints the ready-to-paste line on stdout and everything else on
#       stderr, and writes nothing anywhere. The password is read from a prompt and never
#       from an argument, because an argument is world-readable in /proc and lands in
#       shell history — control/cli.py's own rule, and this only moves where it runs.
#
#       On a machine that DOES have the venv, `python -m control.cli hash-password` is
#       the same command without a build, and stays the documented route there.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

# A tag of this script's own, not the one compose builds. The layers are shared, so on a
# host that has already built the stack this is seconds and on a bare host it is the
# build the restore was going to do anyway — but a separate tag means nothing here can
# leave a half-built image where compose expects a finished one.
IMAGE="hashi-control-cli:local"
DOCKERFILE="deploy/docker/control.Dockerfile"

if ! command -v docker >/dev/null 2>&1; then
  cat >&2 <<'MSG'
this machine has no `docker`, and the hash is produced inside this project's control
image — which is also how a restore avoids needing anything installed on the host.

Two ways on from here, and neither is this script's to choose:

  - install a container runtime (the runbook's "What every box must already have" has
    the one command) and run this again; or
  - on any machine that already has this project set up — `make setup`, Python 3.14 —
    run `python -m control.cli hash-password` there and carry the line over. It is the
    same command and the same hash; only the password ever needs to stay with you.

Nothing was built and nothing was written.
MSG
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  cat >&2 <<'MSG'
the docker daemon is not answering on this machine, so there is nothing to build the
control image with. Nothing was built and nothing was written.

Start it — or, if you are not in the group that may talk to it, become a user who is.
MSG
  exit 1
fi

echo "building the control image, which is where the hashing code lives" >&2
echo "(on a fresh host this is the slow part; it is the same build a restore does)" >&2
# Build output goes to stderr on its own, which is what keeps stdout exactly the line to
# paste. BUILDX_NO_DEFAULT_ATTESTATIONS for the same reason every `up --build` in this
# project sets it: an attestation records the build time, so a fully cached rebuild still
# produces a new image digest and nothing downstream can tell a cached build from a churn.
if ! BUILDX_NO_DEFAULT_ATTESTATIONS=1 docker build -f "${DOCKERFILE}" -t "${IMAGE}" . >&2; then
  cat >&2 <<'MSG'

the control image did not build, so the hash could not be produced. Nothing was written.

Whatever the build said above is the thing to fix; it is about this machine or this
checkout, not about your password. A second run is safe.
MSG
  exit 1
fi

# -t only when there is a terminal on both ends. With one, the prompt is hidden the way
# `getpass` intends; without one, Python says so out loud and reads the password from
# stdin — which is what lets an acceptance scenario drive this without a pty, and is
# still honest about the echo. `--entrypoint python3`, because this image's own
# entrypoint boots the control plane and would answer about a database instead.
TTY=()
if [ -t 0 ] && [ -t 1 ]; then TTY=(-t); fi

echo "" >&2
docker run --rm -i "${TTY[@]}" --entrypoint python3 "${IMAGE}" -m control.cli hash-password
