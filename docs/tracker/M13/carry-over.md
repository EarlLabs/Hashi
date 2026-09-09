# M13 — carry-over

Non-blocking findings left open, with the reason each was left.

- **"Refused at registration" is not literally implemented, and the reviewer said
  so.** M13's own "done when" reads *"applies successfully, or is refused at
  registration with a reason that names the problem."* Registration does no SSH
  probe — before or after this milestone — and under shape one there is no way to
  know at registration time whether a host is prepared without connecting to it.
  What actually happens is: **applies, or fails at first apply** with
  `HOST_NOT_PREPARED`, a sentence naming host preparation, the script, and the
  by-hand repair. The reviewer read the bullet's "or" as accommodating whichever
  shape was chosen and accepted it; that reading is reasonable and it is recorded
  here rather than buried, because the owner may read the bullet the other way.

- **`make test-edge` alone cannot catch a divergence introduced from the edge
  side.** The agreement suite lives in `tests/infra/` and imports `edge`, because
  a cross-check must read both halves and the shell script cannot be imported.
  Changing `NODE_ROOT` in `edge/bootstrap/node_stack.py` alone is invisible to a
  developer running only that zone's verify command; `make test` and CI catch it.
  Both `NODE_ROOT`'s comment and the suite's docstring say so.

- **The panel's node form still defaults `ssh_user` to `root`** with no hint about
  the account the bootstrap script prepared. Not a hazard under shape one — root
  always works, and an unprepared non-root account fails cleanly rather than
  silently — but the panel is where an operator makes this choice, and it offers
  no help. A candidate for the M8/M9 console work.

- **A node switched from root to a non-root account keeps root-owned files.** The
  script hands over the directory only; the files an earlier apply left inside
  still belong to root. `chown -R` them, or delete them — the next apply
  regenerates all of them. Recorded because "re-run the script" looks like it
  should be sufficient and is not.
