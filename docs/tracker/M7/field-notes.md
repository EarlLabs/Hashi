# M7 — field notes, taken before the implementation

Host preparation and reconnaissance done on the entry host ahead of M7's code, so
the implementer builds against a tailnet that exists rather than one imagined.
Addresses and the tailnet's own name are deliberately absent, for the same reason
the two hosts' addresses are: they are local configuration, not repository data.

## The finding that matters most: the official installer does not work in Russia

Measured from the entry host, which is the one host in the fleet where this
matters:

| endpoint | result |
|---|---|
| `tailscale.com` | **blocked** — TLS handshake killed (`SSL_ERROR_SYSCALL`, HTTP 000) |
| `www.tailscale.com` | **blocked**, same |
| `pkgs.tailscale.com` | `HTTP 200` |
| `controlplane.tailscale.com` | `HTTP 302` |
| `login.tailscale.com` | `HTTP 302` |

They resolve to different addresses, so this is per-host filtering of the
marketing site rather than a block on the company.

**So `curl -fsSL https://tailscale.com/install.sh | sh` — the command Tailscale's
own documentation gives, and the obvious thing for a runbook to copy — fails on
the one host in this fleet that is inside the country the product exists for.**
The package repository and the coordination plane both work fine.

What works instead, and what the runbook must say:

```
. /etc/os-release
curl -fsSL "https://pkgs.tailscale.com/stable/${ID}/${VERSION_CODENAME}.noarmor.gpg" \
  | sudo tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null
curl -fsSL "https://pkgs.tailscale.com/stable/${ID}/${VERSION_CODENAME}.tailscale-keyring.list" \
  | sudo tee /etc/apt/sources.list.d/tailscale.list >/dev/null
sudo apt-get update && sudo apt-get install -y tailscale
```

Note it derives the distribution and codename rather than naming them — the same
rule that keeps a country or a port out of the code applies to a distro release.

**This sharpens decision 2's recorded trade-off.** The plan already says
Tailscale's coordination is a US service that may be unreachable from Russia, and
that being locked out during an emergency rotation is the risk. Today the
coordination plane answers in 150 ms and the *website* is what is blocked — which
is a different and milder failure than the one that was feared, but it is also a
demonstration that the filtering is real, present, and applied per-hostname. What
is reachable today is not a promise about tomorrow.

## State after preparation

- `tailscale` 1.102.3 installed from the package repository; `tailscaled` is
  `active` and `enabled`.
- The entry host has joined the tailnet as `hashi-entry`, with a stable tailnet
  address and a MagicDNS name.
- Joined with `--accept-dns=false`, deliberately: the host runs a control plane
  and a data plane, and handing its resolver to the tailnet is a change to how
  the *node* resolves names, which is not M7's subject and would quietly
  interact with M16.
- A tailnet vantage point exists for verification and reaches the entry host
  (`tailscale ping` → `pong`, 8 ms, direct rather than via DERP).

## What M7's implementation still has to do with all this

Everything above was typed on a host by hand, which the owner's standing
requirement forbids leaving that way. **None of it is in the repository yet.**
The install and join belong in a script — `scripts/panel-bootstrap.sh` is the
control plane's own bootstrap and is the natural home, since this is the control
plane's network, not a node's. `scripts/node-bootstrap.sh` is explicitly *not*
the place: a node does not join the tailnet, and M11.1 says that script installs
docker, the key and the firewall and nothing else.

The auth key is a bearer credential. It lives in an untracked file outside the
repository, is read into a variable and never echoed, and ends up in
`tailscaled`'s own state on the host — which is inherent to joining, and worth an
operator knowing. It must never reach `.env`, a compose file or a log.

---

## Superseded, same day — and the notes above are why

The owner reversed decision 2 after reading the measurement above: **the panel is
reached over a dedicated WireGuard management tunnel, not Tailscale.**

Tailscale has been fully removed from the entry host — logged out, daemon
disabled, package purged, apt source and keyring removed, `/var/lib/tailscale`
deleted, no interface left. Both data planes were still running afterwards. The
auth key was deleted from the operator's machine; revoking it and deleting the
device record are the owner's to do in the admin console.

**The reconnaissance above is kept rather than deleted**, because it is the
evidence the decision was taken on, and because the finding outlives the choice:
a documented one-liner install from a vendor's own website can fail in the one
country this product exists for, while that vendor's package repository and API
work fine. Anything this project ever tells an operator to `curl | sh` deserves
the same check from the host that matters.

---

## The defect the field found, after the milestone passed review

M7 reviewed `0 critical, 0 high` and was then deployed to the real entry host,
where **the console could not be reached at all** — not over the tunnel, not over
loopback.

Everything around it was correct. The tunnel came up and held its address, the
publication restricted exactly as designed
(`0.0.0.0:80  0.0.0.0:443  <tunnel addr>:<port>  127.0.0.1:<port>`), and Caddy
held a certificate for **both** private addresses. And:

```
http://<loopback>:<port>/panel/login    -> HTTP 400   ("you spoke HTTP to an HTTPS port")
https://<loopback>:<port>/panel/login   -> HTTP 000   tlsv1 alert internal error
https://<tunnel addr>:<port>/panel/login-> HTTP 000   tlsv1 alert internal error
```

**The discriminator is SNI**, proved with openssl on the host:

| | |
|---|---|
| handshake **with** `-servername` | completes, certificate returned |
| handshake **without** it | `tlsv1 alert internal error`, `no peer certificate available` |

A TLS client sends **no SNI when the host is an IP literal** — true of curl, true
of a browser. With several certificates and no SNI, Caddy cannot choose one and
aborts. So the URL the runbook tells the owner to open, and the `curl` command it
gives for the M7.3 fallback, both fail.

## Why the suite could not have caught it, and why that is the point

The e2e scenarios give the console `console.localhost` — a **name**, which sends
SNI. A WireGuard tunnel hands you an **address**, which does not. Every assertion
passed, the reviewer independently reproduced every claim, and the feature did not
work.

This is the plan's own thesis holding one more time, in the milestone that had
just passed review: *everything checkable by rendering works; everything checkable
only by running does not.* It is also the sharpest example in the whole run of why
the acceptance step is a field observation and not a test run — nothing about the
configuration was wrong, and nothing short of asking a real client to connect
would have said so.

**The lasting half of the fix is the scenario**, not the fix: an assertion that a
client sending no SNI can complete a handshake with the console. Until that
exists, the same defect can return the next time this file is touched.
