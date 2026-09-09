# M11 — outcome

**Steps:** M11.1, M11.2, M11.3, M11.4 — all built, all reviewed, **one review
round each, no Critical or High at any point**. M11.3 drew one Medium (the
runbook's headline command used angle-bracket placeholders inside a runnable
fence, so pasting it produced a shell redirection error naming neither the
command nor the unfilled field). It was fixed rather than filed, because this
milestone's whole premise is that command working under time pressure; the
implementer recorded no disagreement, and a new test pins it.

**Gate at close:** `make test` green — 153 control, 132 edge (3 skipped), 90
infra. The control zone runs against a real Postgres here, so 85 tests that CI
never runs are included in that number.

**Acceptance: half-discharged, and the milestone stays open.** The script half is
proven on two hosts of deliberately different shape. The `register it in the
panel and apply` half is blocked on M4's `draft → degraded` bug and is not
outstanding work on this milestone. Detail in `field-inventory.md` and in the
plan's own status note.

**What the hosts taught us that a test run could not:** see
`field-inventory.md` (both hosts, before and after) and `step-notes.md` §M11.4.
The one worth repeating here is the `AuthorizedKeysCommand` condition — a host
can be reachable with no `authorized_keys` file at all, and this script verifies
its own work by reading back the file it just wrote. That verification is true
on a host where sshd never consults that file. It is in `carry-over.md`.

---

## Acceptance completed 2026-09-09, after M4, M13, M1, M2, M14 and M3

M11's scenario ends *"register it in the panel and apply — it must become a
working node without a second command typed on the box itself."* That half was
blocked when this milestone's steps closed, and it is now discharged.

**Both field hosts were prepared by `scripts/node-bootstrap.sh` alone**, and both
became working nodes with nothing else typed on either box:

| | entry host | leaf host |
|---|---|---|
| prepared by | the script | the script |
| account | non-root with passwordless sudo | root |
| docker | already installed | already installed |
| firewall before | `ufw` inactive | `ufw` active with its own rules |
| registered and applied | yes — `active`, `healthy` | yes — `active`, `healthy` |
| carried real traffic | a friend's client exits here | a friend's traffic exits here via the hop |

Every port either host needed — the friend-facing transport's, the hop's — was
opened by re-running the same script with another `--port`, which is the
idempotent path M11.2 built and M11.4 proved byte-identical.

**Nothing that reached either host stayed by hand.** The one thing done outside
the script was the control plane itself on the entry box, which is
`scripts/panel-bootstrap.sh`'s job and not a node's.

**So the milestone's own criterion — "a fresh host becomes a usable node with one
command, plus the provider's firewall" — is met**, and the provider's firewall
was confirmed by probing from the other host rather than trusted. See
`field-inventory.md`.

**One thing it did not prove.** Both hosts already had Docker. The script's
install path was never exercised tonight, only its "already present" path. That
is the honest limit of this acceptance: M11.4's idempotency claim is proven, its
bare-host claim is not.
