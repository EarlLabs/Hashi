# M24 — carry-over: what only the real-host walk can confirm

Code, tests and a disposable stand only. **No real host was dialled, written to or
restarted by M24.** The orchestrator's walk is what accepts it (PLAN, M24, `acceptance:
yes`): take a user on a node serving only `amneziawg`, follow exactly what the panel hands
the operator, and get a working configuration onto a device.

What it must see with its own eyes:

1. **The dialog.** Users → *show link* on a user whose only node serves `amneziawg`: two
   blocks, *subscription link* then *config-file link*, each with its own copy button
   (*copy subscription link*, *copy config-file link*). Under the subscription link:
   "Carries nothing <nick> holds today, and opens as an empty document — not an error."
   Under the config-file link: "Carries for <nick>: amneziawg." once the node is active
   (before that, "…amneziawg arrives in it once its node is serving").
2. **The copy button copies the right one.** Paste each into a text field — the second
   ends in `?format=client-config-file`. (Stand tests read the DOM text, not the
   clipboard; `static/app.js` copies by element id, which is now `subscription-url-N`.)
3. **The device.** Open the config-file link on a phone/desktop: an archive
   `hashi-configs.zip` downloads; unzip; import the `.conf` into the AmneziaWG app; it
   handshakes and carries traffic (after the node has been applied for that user — the
   dialog's own "not on the nodes yet" note says when it has not).
4. **A user on a VLESS-only node** sees one link, no config-file link, "One URL, every
   serving node."
5. **Nothing recorded.** `docker compose logs control caddy` after the walk holds neither
   the token nor `format=client-config-file`.
6. **The Nodes screen** row for an offered `amneziawg` reads "…gets it from the config-file
   link shown beside their subscription link under “show link” on the Users screen".

## Open owner question

- **"Users never re-add anything" does not hold for a config-file user.** An imported
  `.conf` does not refresh: after a key rotation or a replaced node they download the
  config-file link again and re-import. Inherent in option (b) (2026-08-09), not
  introduced by M24 — the dialog now says it instead of the opposite. Whether the charter
  wording should be narrowed, or the family needs something more, is the owner's call.

## Known, not fixed here

- **Per-host delivery URLs (M27.7)** are still composed by no screen — M27's, not M24's.
- The 3 edge failures in `tests/edge/test_upstream_validation.py` (`[wireguard]`) are
  environmental (the system `wg-quick` calls `sudo`). Reported, not fixed.
