# hashi — the acceptance agent's browser.
#
# WHAT: Chromium, the Playwright python package, and scripts/acceptance/drive.py,
#       in one image.
# WHY built rather than pulled, for two reasons the field supplied on the same day.
#      The upstream image ships the browsers but NOT the python package: it carries
#      /ms-playwright (chromium, firefox, webkit, ffmpeg) and a bare python, so
#      pulling it produced a stand that came up perfectly healthy and a driver that
#      died on `ModuleNotFoundError: No module named 'playwright'` at its first
#      verb — on the instrument M8, M9 and M10 are to be judged with. And a BIND
#      MOUNT of ./scripts/acceptance is resolved on the DAEMON's filesystem, which
#      is not this checkout whenever the engine is remote — the fleet's dind, or an
#      overnight run driving docker on another host. The driver would then be
#      missing or stale, and every verb would fail like a broken browser. This is
#      the lesson caddy.Dockerfile already paid for: what the container needs
#      travels with the image. Installing at container start instead would put a
#      package index on the critical path of every acceptance run.
# HOW:  built from the repo root (context: ..), like the other two images here.
#
# ONE version, written once. The package and the browser build it drives must be
# the same release or Playwright refuses to launch — a mismatch surfaces as
# "executable doesn't exist", several layers from its cause — so the tag is DERIVED
# from the pin rather than repeated beside it: PLAYWRIGHT_VERSION is declared before
# the first FROM (where an ARG can reach the tag) and re-declared after it (where an
# ARG can reach a RUN). Upgrading means changing this one line.
# tests/infra/test_the_hands_can_take_an_action.py holds that property.

ARG PLAYWRIGHT_VERSION=1.55.0

FROM mcr.microsoft.com/playwright/python:v${PLAYWRIGHT_VERSION}-noble

# An ARG declared before FROM is out of scope after it — this brings the same
# value back in, without naming it again.
ARG PLAYWRIGHT_VERSION

RUN pip install --no-cache-dir "playwright==${PLAYWRIGHT_VERSION}"

# The exact import drive.py's `serve()` does, run at BUILD time: a broken image
# then fails where somebody is watching a build, instead of at the first verb of
# an acceptance run where it looked like a broken stand.
RUN python -c "from playwright.sync_api import sync_playwright"

# The driver travels with the artefact. `stand.sh up` builds before it starts, so an
# edit to drive.py is picked up on the next stand rather than needing a manual
# rebuild anyone could forget at two in the morning.
COPY scripts/acceptance/drive.py /srv/acceptance/drive.py

WORKDIR /srv/acceptance
