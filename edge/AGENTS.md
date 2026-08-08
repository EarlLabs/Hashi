# edge — orientation

The data plane: transport profiles, node bootstrap, config rendering and health
probing. This is the zone that decides whether a node survives a censor.

**Zone owner:** Ohno (`alfred`) — solo topology, see docs/product/charter.md §Fleet.
**Rules:** `.claude/projects/02-edge-rulebook.md` — read it before editing.
**Verify:** `make test-edge`.

## What is here

| Path | What it holds |
|---|---|
| `transports/<name>/` | one self-contained protocol profile — meta, params, templates, renderers |
| `registry.py` | discovers those packages; never a hardcoded list |
| `bootstrap/` | SSH: install, place compose files, start, verify |
| `health/` | liveness probing, always initiated by the control plane |

## What is true today

A scaffold. `registry.discover()` works and returns `{}` — no transport is
implemented yet. The first ones planned are Xray VLESS+Reality+XTLS-Vision, then
AmneziaWG.

## The three things newcomers get wrong

1. **Rendering is pure.** No database, no network, no clock, no randomness, no
   key generation. Keys are passed in. This is what makes golden-file tests
   meaningful.
2. **A new protocol is a new directory and nothing else.** If your change needs
   an edit in `registry.py` or in the control plane, the profile contract is too
   narrow — say so rather than special-casing.
3. **Plain WireGuard is protocol-blocked in Russia.** It is allowed only on links
   that never cross the border — and the entry-node → leaf-node hop *does* cross
   it.
