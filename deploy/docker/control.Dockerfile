# WHAT: the control-plane image.
# WHY:  the interpreter matches the one the local venv uses (3.14). A container
#       on a different minor than the developer's venv is the trap where "works
#       locally" and "works in the stack" quietly diverge.
# HOW:  built from the repo root (context: ..) because the package lives there.

FROM python:3.14-slim

# `age`, for scripts/backup.sh. It lives in this image rather than on the box for the
# same reason pg_dump runs inside the db container: a restore has to work on a host that
# was rented an hour ago, and "install age first" is a step nobody has at 3am. Nothing
# new is required of the control-plane host — see docs/deploy/runbook.md, "Backups".
#
# Deliberately not pinned to a Debian binary revision: that revision is a mirror snapshot
# Debian removes, so pinning it turns a rebuild into a failure at exactly the moment a
# rebuild is what you are doing. What has to stay stable is the FILE FORMAT, and age
# versions that itself — every artifact opens with `age-encryption.org/v1`.
RUN apt-get update \
 && apt-get install --yes --no-install-recommends age \
 && rm -rf /var/lib/apt/lists/*

# Build in /src and install, then throw the sources away and run from an empty
# directory. WHY the dance: the image used to `pip install .` in the same
# WORKDIR it then ran from, so `import edge` resolved to the COPIED tree (cwd is
# on sys.path), never to the installed distribution — the install was decoration
# and pyproject's package list was never exercised. A transport package missing
# from that list would have shipped fine here and vanished in any other
# consumer of the wheel. One copy of the code in the image, and it is the
# installed one.
WORKDIR /src

COPY pyproject.toml ./
COPY control ./control
COPY edge ./edge

RUN pip install --no-cache-dir . && rm -rf /src

WORKDIR /app

COPY deploy/docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Runs as a non-root user. This process holds the key to every node's credentials, so
# a remote-code-execution bug in it should not also be root on the container. Created
# with no home and no shell: nothing here ever logs in.
RUN useradd --system --no-create-home --shell /usr/sbin/nologin hashi
USER hashi

EXPOSE 8000

# Migrations run inside the entrypoint, before uvicorn — see that script for why a
# migration that is not part of boot is a migration that is missing in production
# exactly once.
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
