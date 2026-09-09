# M1 — proven on real hardware, 2026-09-09

Same node, same evening, before and after. The measurement that opens this
milestone is in `field-measurement.md`; this is what changed.

## 1. A config change now reaches the daemon

| | before the fix | after |
|---|---|---|
| container started | `01:39:46` | `02:13:50.923` |
| config written | `01:48:11` | `02:13:50.422` |
| relationship | config **8m25s later** than the process serving it | process **0.5s later** than the config |

And the container now carries the digest it was created with:

```
label     = f8e4751c35924fd7b4b08c69090b013aecec423dc6b45c76d1397b749be0e8de
sha256sum = f8e4751c35924fd7b4b08c69090b013aecec423dc6b45c76d1397b749be0e8de  conf/vless-reality.json
```

The label is not a second opinion about the file; it is the value that made
Compose recreate the container. The two halves of the fix cannot disagree.

## 2. The health probe stopped lying

The stale container from before the fix — the one that had reported
`healthy: true, drifted: []` — reported, the moment the new control plane came
up and **before** anything was re-applied:

```
healthy: false, drifted: [], stale: ["vless-reality"],
detail: "still running an older configuration: vless-reality"
```

`drifted: []` is still correct: the file on disk genuinely does match what was
pushed. That is exactly why the old answer was so convincing, and why `stale`
had to be a separate fact rather than folded into drift.

## 3. One hop, with a real client

A throwaway `xray-core` container on the operator's machine, driven from the
friend's own subscription document, removed afterwards.

| | address the internet reported |
|---|---|
| direct, no tunnel | the operator's own address |
| through the tunnel | **the node's address** |

`https://example.com` returned `HTTP 200`, 559 bytes, through the tunnel.

## 4. Revocation stops the friend AT THE NODE — the milestone's whole point

Revoked in the panel. The node's container was recreated on the spot:

```
before revoke: label=f8e4751c…  started=02:13:50.923
after  revoke: label=ca7e9e90…  started=02:15:08.137
```

and the new label again equals the `sha256sum` of the rewritten config.

**The same client, unchanged, could no longer connect** — `SSL_ERROR_SYSCALL`,
twice. Reading the config file did not count, and was never the evidence.

**The control that makes this conclusive.** A failure to connect could just mean
the node broke. So a second friend was added and applied, and both clients were
run against the same node at the same moment:

| client | result |
|---|---|
| revoked friend | refused |
| live friend | connected, exited at the node's address |

The node was serving. Only the revoked credential was dead. That is criterion 6
holding on real hardware, which is the thing `make test` cannot establish.
