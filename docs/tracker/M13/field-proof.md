# M13 — proven on real hardware, 2026-09-09

The host is the entry box: reached as a **non-root account with passwordless
sudo**, the shape that had never worked in this project's history.

**Bootstrap, after M13.** The new line appears and nothing else changes:

```
==> created /opt/hashi, empty and owned by <user>
...
==> no hashi code and no hashi state was installed here — /opt/hashi is an empty
    directory owned by <user>, and the control plane fills it on your first apply
```

Verified on the host: `drwx------ 2 <user> <user> /opt/hashi`, empty, inside a
root-owned `/opt`.

**The apply that had failed twice.**

| attempt | result |
|---|---|
| first, before M4 | `409: a node cannot go from draft to degraded` — cause destroyed |
| second, after M4.1 | `502` naming the real cause: `mkdir: cannot create directory '/opt/hashi': Permission denied` |
| third, after M13 | **`200 {"transports_applied":["vless-reality"]}`** |

Node `state: active`, `state_detail: null`. Health probe: `reachable: true`,
`healthy: true`, `running: ["vless-reality"]`, nothing missing, nothing drifted.
On the host: the `xray-core` container is `Up`, `/opt/hashi/conf/vless-reality.json`
is in place, and the node is listening on the port its record names — every file
owned by the non-root account.

**What this proves about the chosen shape, and it is worth stating precisely.**
The control plane on that host was still running the **pre-M13 library** when the
apply succeeded. Nothing in `edge` had changed on it. So the fix that made a
non-root node work was the *script alone* — which is exactly what shape one
claims: the privilege boundary belongs to host preparation, and `edge` never
needs to learn about `sudo`. The library-side change that landed with it is not
what made this work; it is what turns a *missing* directory into a sentence
naming the repair instead of a `Permission denied` from `mkdir`.
