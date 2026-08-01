# =============================================================================
# hashi Warden image — deploy/warden/Dockerfile
# =============================================================================
# WHAT: the Warden daemon plus everything the fleet needs to actually work in
#       this repo: the `claude` CLI, git, `gh`, and the project's own toolchain.
#
# WHY it is bigger than the dummy project's image: the dummy does no work, so it
#       needs grpcio and nothing else. This one RUNS the fleet — that means the
#       CLI, node to host it, git and gh for the branch/PR discipline in
#       .claude/git-workflow.md, and make/python so the agents can run
#       `make test-<zone>` before handing over. A Warden that cannot run the
#       zone's verify command would let every developer hand over an unverified
#       build.
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

# git: the fleet branches and diffs. gh: it opens the PR. make: the zone verify
# commands. nodejs/npm: the claude CLI runs on node.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      git make curl ca-certificates gnupg \
 && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
 && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get update \
 && apt-get install -y --no-install-recommends nodejs gh \
 && npm install -g @anthropic-ai/claude-code \
 && rm -rf /var/lib/apt/lists/*

# The kit's entire runtime dependency set — grpcio for the transport, protobuf
# because the committed generated stubs import it. wardenkit deliberately
# hand-rolls its flat-YAML reader so this list stays this short.
RUN pip install --no-cache-dir "grpcio>=1.83,<2" "protobuf>=7.35,<8"

WORKDIR /app

# Everything this project vendors from Kaizen: the generated contract + the kit.
COPY deploy/warden/vendor/infra /app/vendor/infra
# ...and the project's own half.
COPY deploy/warden/warden.py     /app/warden.py
COPY deploy/warden/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# The entrypoint wires git/gh from the environment, then execs the Warden — so
# the credential lives in git's config and never in an agent's context.
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "/app/warden.py"]
