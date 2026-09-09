# M14 — proven on real hardware, 2026-09-09

## 1. The rules land where they have to land

After an apply, the rendered config carries the hooks and the host's netfilter
carries the rules:

```
PostUp   = iptables -t filter -I FORWARD 1 -i %i -j ACCEPT; … -o %i …;
           iptables -t nat -I POSTROUTING 1 -s 10.77.0.0/24 ! -o %i -j MASQUERADE
PostDown = the exact inverse, each delete with || true
```

```
nft FORWARD:  -P DROP
              -A FORWARD -o amneziawg -j ACCEPT     ← ahead of ufw's own rules
              -A FORWARD -i amneziawg -j ACCEPT
nft nat:      -A POSTROUTING -s 10.77.0.0/24 ! -o amneziawg -j MASQUERADE
```

`net.ipv4.ip_forward = 1`. No interface name is hardcoded anywhere: `%i` is
wg-quick's own substitution and the masquerade matches "left by anything that is
**not** the tunnel".

## 2. A friend reaches the internet, and exits at the node

A real AmneziaWG client, built from the friend's own `client-config-file`
subscription, in a throwaway container, removed afterwards.

| destination | result through the tunnel |
|---|---|
| `example.com` | `HTTP 200`, 559 B |
| `www.wikipedia.org` | `HTTP 200`, **119 573 B** |
| `cloudflare.com` | `HTTP 301`, 167 B |
| an address echo | **the node's own public address** |

Tunnel counters afterwards: 164.36 KiB received, 27.56 KiB sent. Before M14 the
same client completed a handshake and every request timed out.

## 3. Disabling the transport leaves nothing behind

Disabled in the panel, then applied:

| | before | after disable | after re-enable |
|---|---|---|---|
| masquerade rules for the tunnel subnet | 1 | **0** | 1 |
| FORWARD rules naming the interface | 2 | **0** | 2 |
| the interface | present | **gone** | present |
| the container | present | **gone** | present |

Exactly one and two after re-enabling — not two and four. A disable/re-enable
cycle leaves no duplicate and no residue, which is what M14.2 asked for.

---

## Two wrong turns, recorded because the method matters more than the result

Both were **my** errors as the operator, not the product's, and both looked
exactly like product bugs for several minutes.

**I blamed MTU.** A small response (an address echo) succeeded through the tunnel
while `example.com` timed out — the classic signature of a path-MTU blackhole.
Lowering the client's interface MTU to 1280 changed nothing, which should have
been the clue and instead read as "worse than expected".

**Then I blamed ICMP filtering.** A ping sweep through the tunnel reported every
payload size blocked, including 500 bytes, which fits no MTU story at all.

**The actual cause was my own test harness.** `getent hosts` returns whatever the
resolver ranks first, and for `example.com`, `www.wikipedia.org` and
`cloudflare.com` on this machine that is an **IPv6** address. I was pinning those
into `curl --resolve` and asking an IPv4-only tunnel to carry them. `api.ipify.org`
happened to answer with IPv4, which is the only reason anything worked and the
only reason the failure looked selective. `getent ahostsv4` resolved it in one
step, and all four destinations then returned 200.

**Why this is worth keeping.** This milestone exists because a handshake succeeded
and nothing moved — a true-looking signal covering a real fault. The debugging
above is the same shape in the other direction: a real-looking fault produced
entirely by the instrument. Both are arguments for the same discipline, which is
to keep asking the next question rather than accepting the first coherent story.
The node was never the problem, and two plausible diagnoses were wrong before the
third was right.
