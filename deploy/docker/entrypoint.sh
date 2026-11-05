#!/bin/sh
# WHAT: the control container's entrypoint — migrate, then serve.
# WHY:  backlog item 3a. `alembic upgrade head` was called from nowhere, so the
#       schema existed only on whichever machine someone had run it by hand. A
#       migration that is not part of boot is a migration that is missing in
#       production exactly once, at the worst time.
# HOW:  migrations run to completion BEFORE uvicorn starts, and a failure aborts the
#       boot rather than serving against an old schema. `set -e` is what makes that
#       true — without it, a failed upgrade would be a log line and the app would
#       start anyway, answering requests against a schema it does not match.
set -e

# The database is `depends_on: service_healthy`, so it is accepting connections by
# the time we get here. This loop covers the remaining case: Postgres reports healthy
# via pg_isready the moment it accepts a socket, which is slightly before it will
# accept our credentials on first initialisation.
attempt=0
until python -c "
import asyncio, sys
import asyncpg
from control.app.settings import Settings
url = Settings().database_url.replace('postgresql+asyncpg://', 'postgresql://')
async def check():
    connection = await asyncpg.connect(url)
    await connection.close()
asyncio.run(check())
" 2>/dev/null; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 30 ]; then
    echo "database did not become reachable after 30 attempts — refusing to start" >&2
    exit 1
  fi
  echo "waiting for the database ($attempt)…"
  sleep 1
done

# The bot process reuses this image, waits for the same database, and then runs the
# Telegram poller instead of uvicorn — M39.1. The dispatch is BEFORE the migrations: the
# control service (no `command:`) owns `alembic upgrade head`, so the bot must not also run
# it — two services racing the same migration is the kind of thing that works until the one
# time it does not. The bot waits for the control service to be healthy (compose
# `depends_on`), by which time the schema it shares is already there.
if [ "${1:-}" = "bot" ]; then
  echo "starting telegram bot"
  exec python -m control.app.botmain
fi

# Found through the INSTALLED package rather than a copied path. The image
# deliberately throws its sources away and runs from an empty /app, so there is no
# checkout to point at — and hardcoding a site-packages path would break on a Python
# minor bump. alembic.ini ships inside the package (see pyproject's package-data), and
# its `script_location = %(here)s/migrations` resolves relative to wherever it landed.
ALEMBIC_INI="$(python -c 'import control, pathlib; print(pathlib.Path(control.__file__).parent / "alembic.ini")')"

echo "applying migrations…"
alembic -c "${ALEMBIC_INI}" upgrade head

echo "starting control plane"
# --no-access-log is not a performance choice: uvicorn's access log records the
# request path, and subscription tokens live in the path.
exec uvicorn control.app.main:create_app --factory \
  --host 0.0.0.0 --port 8000 --no-access-log "$@"
