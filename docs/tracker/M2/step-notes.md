# M2 — step notes

Conventions established here. They bind later steps, and later milestones in
this codebase, until something supersedes them. Follow them; do not relitigate.

## How a WireGuard-family data plane is run

- **One shared POSIX shell line**, `node_stack._WG_QUICK_SUPERVISOR`, invoked as
  `/bin/sh -c <script> <tool> <config-path>`: the tool arrives as `$0`, the config
  as `$1`. One line serves the whole family and **no protocol name appears in
  shared code**. `wg-quick` for `WG_QUICK_PLAIN`, `awg-quick` for `WG_QUICK`, each
  declared by its own `DataPlane` entry.
- The shell does three things the quick tool alone cannot, each measured rather
  than assumed: it **holds the container open** (the tool configures and returns,
  so a bare command exits 0 and `restart: unless-stopped` becomes a restart loop);
  it **takes the interface down on SIGTERM** (the interface lives in the *node's*
  netns under `network_mode: host` and outlives a container that does not tear it
  down); and it **takes down a leftover interface before bringing one up**,
  because M1 now recreates containers on a config change and a stop that skipped
  the trap leaves the old interface, after which the replacement dies with
  ``wg-quick: `<name>' already exists``.
- `set -e` is deliberate: a failed `up` must kill the container rather than leave
  it `Up` and carrying nothing. The trap's `|| true` is also deliberate —
  without it `set -e` abandons the trap at a failing `down` and a normal stop
  reports exit 1.

## The interface name comes from the config filename

`DataPlane.interface_from_config_filename` declares that the tool works this way.
`services_for` then refuses, **at render time**, a transport whose config stem is
not a legal interface name — `node_stack.INTERFACE_NAME`,
`^[a-zA-Z0-9_=+.-]{1,15}$`, copied from wg-quick's own source — raising
`node_stack.UnrunnableTransport`. Use those two names; do not re-derive the rule,
and keep the refusal generic rather than a branch on today's transports.

## We override the plain-WireGuard image's own entrypoint, on purpose

Its `/entrypoint.sh` is correct in isolation and wrong for us, for three reasons
the reviewer verified independently:

1. It hardcodes `/etc/wireguard/wg0.conf`. A single-file bind mount there has its
   **source inode replaced by every apply** — `ssh.write_file` does
   `posix_rename` — and Docker silently creates a *directory* if the file is
   missing. Mounting our conf dir over `/etc/wireguard` instead would destroy the
   per-transport naming that stops two transports overwriting each other.
2. It hardcodes interface `wg0`, so two WireGuard-family transports on one node
   would both claim it in the host netns, and `wg0` can collide with an
   operator's own tunnel.
3. It has no pre-emptive `down`, so it crash-loops on exactly the recreate path
   M1 introduced.

**The cost, stated so nobody is surprised:** we no longer inherit upstream fixes
to that script, and the interface is named after the transport rather than `wg0`
— so `wg show wg0` is wrong on a hashi node. The template supports `command=()`
meaning "the image's own `Cmd` is right", if this is ever revisited.

## M2.2 — what the command check proves, and what it does not

Two layers, split on the network boundary:

- **Offline, in `make test-edge`:** walks `DATA_PLANES` itself, computes the argv
  Docker would exec (image entrypoint + declared command, or the image's `Cmd`),
  and asserts argv[0] and every declared executable resolves in that image, using
  facts recorded in `tests/edge/golden/image-facts.json`. **An image with no
  recorded facts fails rather than skips** — that is what makes it cover a
  transport added later instead of today's answers. A second assertion requires a
  command that runs an interpreter (`-c`) to declare `executables`, so hiding the
  real program in a quoted string fails.
- **Networked, in `tests/e2e/edge/`:** pulls each pinned image, re-derives the
  facts, and asserts the golden file still matches.
  `HASHI_RECORD_IMAGE_FACTS=1` re-records it — a golden update, reviewed as a
  diff.

**It does not prove** that the arguments are right (`awg-quick` exec-ing is not
`awg-quick` accepting that config), that a daemon starts, that an interface is
created, that a handshake completes, or that a byte moves. Nor that the recorded
facts are current if the e2e scenario has not run since a pin changed. All of
that is in the module docstring. **Adding or bumping an image pin requires
re-recording the golden file; the unit suite goes red until you do, on purpose.**

## Testing a shell command line without an engine

`tests/edge/test_the_wireguard_family_can_start.py::stub_tool` — a stub quick
tool in `tmp_path` that appends `"$1 $2"` to a `calls` file and exits 1 on
`down`; `run_supervisor()` runs the real `_WG_QUICK_SUPERVISOR` under `/bin/sh`
with `start_new_session=True`. That covers stays-alive, teardown-on-SIGTERM and
recovery-after-unclean-stop with no docker. Reuse it. `WG_FAMILY` in that file is
derived from `interface_from_config_filename`, never from a protocol name, so a
third family member is tested by arriving.

## Operator-facing wording introduced here

> transport '<name>' runs a tool that takes the network interface name from its
> config file, so it would ask for an interface called '<x>' — which is not one
> this kernel accepts (at most 15 characters from a-z A-Z 0-9 _ = + . -). Rename
> the transport.
