# hashi — the acceptance agent's browser.
#
# WHAT: Chromium, Playwright and scripts/acceptance/drive.py in one image.
# WHY built rather than pulled, for the same reason caddy.Dockerfile exists: a bind
#      mount of ./scripts/acceptance is resolved on the DAEMON's filesystem, which
#      is not this checkout whenever the engine is remote — the fleet's dind, or an
#      overnight run driving docker on another host. The driver would then be
#      missing or stale, and every acceptance verb would fail with something that
#      reads like a broken browser.
# WHY the upstream image ships the browsers but NOT the python package: it carries
#      /ms-playwright (chromium, firefox, webkit, ffmpeg) and a bare python. The
#      `playwright` package has to be installed, and its version must match the tag
#      or the client and the bundled browser build disagree — a mismatch surfaces as
#      "executable doesn't exist", several layers from its cause.
# HOW:  pinned like every other image in this repository. Bump the tag and the pip
#       pin together, never one alone.
FROM mcr.microsoft.com/playwright/python:v1.55.0-noble

RUN pip install --no-cache-dir playwright==1.55.0

# The driver travels with the artefact. `stand.sh up` builds before it starts, so an
# edit to drive.py is picked up on the next stand rather than needing a manual
# rebuild anyone could forget at two in the morning.
COPY scripts/acceptance/drive.py /srv/acceptance/drive.py

WORKDIR /srv/acceptance
