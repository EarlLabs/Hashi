# An `infra` change M10 could not make — recorded 2026-09-11

M10.2's Settings screen names, beside each value, the environment variable it is
read from. For **four of those variables the named place does nothing**, and the
reason is in a different zone, so it is written down here rather than fixed in a
`control` diff.

## What is wrong

`deploy/docker-compose.yml`'s `control` service has an explicit `environment:`
allow-list with **five** entries:

```
HASHI_SECRET_KEY  HASHI_PUBLIC_HOST  HASHI_DATABASE_URL
HASHI_OPERATOR_USERNAME  HASHI_OPERATOR_PASSWORD_HASH
```

These four are **never passed into the container**:

- `HASHI_PUBLIC_HTTPS`
- `HASHI_SESSION_MAX_AGE`
- `HASHI_NODE_SSH_TIMEOUT`
- `HASHI_NODE_CONNECT_TIMEOUT`

So an owner who reads the Settings screen, puts one of them in `.env` and
restarts gets **silence** — `--env-file` feeds compose *interpolation*, not the
container's environment, and `CLAUDE.md` already warns that running compose
without that flag turns every `${VAR}` into an empty string with no error. The
four run on their declared defaults today and cannot be changed without editing
the compose file.

**The values the screen prints are still true** — it renders the live `Settings`
object, so it shows what the process is actually using. What was over-promised is
only *where to change it*, and M10.2 narrowed that footnote to say a variable
nothing passes in yet must be **added** to the environment rather than edited
somewhere the process never reads.

## The fix, when someone takes it

Add the four to that `environment:` block as pass-throughs of the same name, and
give `.env.example` commented entries for them so there is somewhere obvious to
put them. Two notes from the implementer that save a rediscovery:

- `deploy/docker-compose.e2e.yml` **already** sets `HASHI_PUBLIC_HTTPS=false` for
  the e2e stack, so the dev/prod block is the gap rather than both.
- **`HASHI_DATABASE_URL` is a separate and deliberate case, not part of this.**
  Compose composes it from `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB`, and
  `.env.example:99` says it is *"NOT set here on purpose… Set it by hand only when
  running the app outside compose"*. So the standard deployment overwrites
  whatever `.env` holds. The honest fix there is a **decision about what that row
  should name**, not a compose edit — leave it naming the variable the process
  actually reads until someone decides otherwise.

## Why it was not done here

`deploy/**` is the `infra` zone and `CLAUDE.md` keeps cross-zone work in separate
diffs. Doing it inside a milestone about two panel screens would put an
unreviewed deployment change under a `control` review.

Found by M10.2's reviewer, which checked the screen's claim against the shipped
compose file rather than against `settings.py` alone.
