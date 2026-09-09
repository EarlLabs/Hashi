# M7 — proven on real hardware, 2026-09-09

Deployed to the entry host and verified from the leaf in Amsterdam, which is a
genuinely public network rather than a second address on the same box.

## The panel is off the public internet

Every path the console lives on, asked from Amsterdam over the public address:

| path | answer |
|---|---|
| `/panel/` | **404** |
| `/panel/login` | **404** |
| `/api/nodes` | **404** |
| `/healthz` | **404** |
| `/` | **404** |

Empty bodies, and nothing that says another site exists.

**The console's own port is not reachable from outside at all** — the publication
binds it to the management tunnel's address and to loopback, never to `0.0.0.0`,
so a connection from Amsterdam gets nothing.

**Port 80 does not hand out the console's address.** A plain-HTTP request for a
panel path redirects to the **public** host, not to the private one:

```
HTTP/1.1 308 Permanent Redirect
Location: https://<public host>/panel/
```

That was a real leak before the fix — Caddy's automatic redirects answered with
`Location: https://<private host>:<private port>/…`, handing out the console's
address to anyone who asked port 80 the right question.

## A friend is unaffected

| | |
|---|---|
| `/sub/{a real token}` | **200**, with the real subscription document |
| `/sub/{a bogus token}` | **404** |

The delivery endpoint is unchanged and still public, which is the point: a friend
refreshes their config from inside Russia at exactly the moment a node was
blocked.

## The way back in is verified, not described

M7.3 was raised from "document" to "document and test" on 2026-09-09. Over the
documented SSH forward, with the management tunnel not in the path at all:

```
https://127.0.0.1:<port>/panel/login   ->  200
login                                  ->  303
create a friend, issue a subscription  ->  worked
```

So the fallback is a route that has been walked, not a paragraph.

## What this milestone cost, and the reason it was worth it

M7 passed review at `0 critical, 0 high` — the reviewer reproduced the port-80
leak, verified the key derivation five times against `wg pubkey`, and mechanically
deleted a log block to confirm the test caught it. **The console was then
unreachable the moment it met a real host.**

A TLS client sends no SNI for an IP literal; a WireGuard tunnel hands you an
address; the e2e stack gave the console `console.localhost`, a **name**, which
sends SNI. Every assertion passed and the feature did not work. The fix is
`default_sni` (see `docs/decisions.md` for the trade it forces), and the lasting
half is the scenario: the test stack's console is now an **address**, and one
scenario performs an explicitly SNI-less handshake from the only TLS client in
the stack that can be aimed — Caddy's own image ships busybox, which sends SNI
even for an address, which is how the old scenarios kept passing.

## Honest limits of this verification

- **ACME was never exercised.** The entry host has no DNS record, so
  `HASHI_PUBLIC_HOST` is its IP and Caddy issues an internal certificate. The
  routing split is proven; certificate issuance on the public site is not, and a
  public CA will not issue for a bare IP at all — see `docs/decisions.md`.
- **The tunnel was verified from the host and over loopback**, not from a phone
  on a mobile network. Whether the obfuscated handshake survives ТСПУ on the
  owner's own network is the one thing this fleet cannot answer.
