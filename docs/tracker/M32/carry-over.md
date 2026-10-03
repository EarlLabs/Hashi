# M32 — what the real-host walk must check

Built on `task/M32`, gated on a disposable stand. Nothing here touched a real host. The
walk is the orchestrator's; these are the observations no test can make.

1. **The owner's finding, closed.** In the panel, add one user (one nickname). Do not press
   anything else. The dialog lists each serving node and applies them one after another;
   each row ends `✓ <node> — took the new configuration`. The line under the rows reads
   "Their link works through <nodes> now." Import the subscription link on a phone and
   connect — the done-when box that only the field can tick.
2. **Several at once.** Add three nicknames, one per line. Each node row appears once. On
   the node: one restart of the user-facing daemons per node for the three (connected
   clients drop for ~1–2 s once, not three times).
3. **A node that cannot be reached.** Make one leaf unreachable from the control plane
   (block its SSH port), add a user. Its row reads `✗ <leaf> — … could not be reached …`
   with a **retry**; the line says the link does not work through it yet. The leaf stays
   `active` on the Nodes screen and in an existing user's link. Unblock, press retry: `✓`.
4. **The block.** Change a transport parameter on a node without applying it. Overview,
   Users and Nodes each show the steel-blue NOT APPLIED block: "<node> is still on the old
   configuration: your changes have not reached it." with **Apply <node>**; "details"
   opens the long text. Pressing the button applies that node (toast, block gone on every
   screen without a reload). Open a user's link dialog while a node is behind: the block
   is ABOVE the link, and its button answers inside the dialog without closing it.
5. **Long requests.** Each node row is one request of an apply's length (~20–40 s). Over
   `ssh -L` and over the management tunnel, nothing in the path cuts it; if a row never
   resolves, that is a finding (proxy or browser timeout) — record which path.
6. **Closing the dialog mid-way** leaves the remaining nodes unapplied; they must then show
   in the NOT APPLIED block. Expected, recorded in `docs/decisions.md`.
7. **API.** `POST /api/users` answers `complete`, `nodes_updated`, `nodes_failed`,
   `summary`; `POST /api/users/batch` with `{"nicknames": [...]}` likewise, with `users`.
