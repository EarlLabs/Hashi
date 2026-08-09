# WHAT: the reverse-proxy image, with this repo's Caddyfile baked in.
# WHY:  the Caddyfile used to arrive as a bind mount from the repo. A bind mount
#       is resolved by the DOCKER DAEMON, not by the client — so the moment the
#       daemon is not the one holding this checkout (the fleet's dind engine,
#       a remote host, a rootless VM), `./caddy/Caddyfile` does not exist there
#       and Docker helpfully creates a DIRECTORY at that path, then fails to
#       mount it over the image's file. That is a boot failure of the whole
#       stack, and it only ever appears off the developer's own laptop.
#       Baking the file in makes the config travel with the image instead.
# HOW:  built from the repo root (context: ..), same as the control image.
#       Editing deploy/caddy/Caddyfile now needs a rebuild — `make up`, `make
#       up-dev` and `make e2e-up` all pass --build, so that is already the
#       normal path.

FROM caddy:2.8.4-alpine

COPY deploy/caddy/Caddyfile /etc/caddy/Caddyfile
