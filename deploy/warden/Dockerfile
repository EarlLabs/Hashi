# =============================================================================
# hashi Warden image — deploy/warden/Dockerfile
# =============================================================================
# WHAT: the Warden daemon plus everything the fleet needs to actually work in
#       this repo: the `claude` CLI, git, and the project's own toolchain.
#
# WHY it is bigger than the dummy project's image: the dummy does no work, so it
#       needs grpcio and nothing else. This one RUNS the fleet — that means the
#       CLI, node to host it, git for the branch discipline in workflow.md, and
#       make/python so the agents can run `make test-<zone>` before handing over.
#       A Warden that cannot run the zone's verify command would let every
#       developer persona hand over an unverified build.
#
# WHY the build context is the repo root: the vendored kit lives at
#       deploy/warden/vendor/ and the Warden imports it as `infra.*`.
#       See deploy/warden/README.md for why it is vendored rather than installed.
# =============================================================================

FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/vendor \
    DISABLE_AUTOUPDATER=1

# git: the fleet branches and diffs. make: the zone verify commands.
# nodejs/npm: the claude CLI runs on node. curl/ca-certificates for the install.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      git make curl ca-certificates gnupg \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && npm install -g @anthropic-ai/claude-code \
 && apt-get purge -y gnupg && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

# The kit's entire runtime dependency set — grpcio for the transport, protobuf
# because the committed generated stubs import it. wardenkit deliberately
# hand-rolls its flat-YAML reader so this list stays this short.
RUN pip install --no-cache-dir "grpcio>=1.83,<2" "protobuf>=7.35,<8"

WORKDIR /app

# Everything this project vendors from Kaizen: the generated contract + the kit.
COPY deploy/warden/vendor/infra /app/vendor/infra
# ...and the project's own half.
COPY deploy/warden/warden.py /app/warden.py

CMD ["python", "/app/warden.py"]
