# M34 — what the real-host walk must check

Built on `task/M34` (stacked on `task/M33`). Nothing here touched a real host. The walk is the
orchestrator's, the phone half the owner's. Everything below is an observation no test here
can make; the loopback measurements in `tests/edge/test_listed_sites_leave_from_the_entry.py`
are what each one is the real-network version of.

**Test destinations.** Before using either, type it into the Routing screen's *Where would it
go?* box — the answer must be the one named here, or pick another.

- **Listed, refuses or reacts to foreign IPs:** `showip.net` — on the narrow itdoginfo list
  and it prints the visitor's address, so it answers the question by itself. For a real
  "does not open from abroad" site, `gosuslugi.ru` (also on the list): from a foreign address
  it fails or degrades; with the switch on it must open.
- **Unlisted, shows the address:** `ifconfig.me` — on no list *while only the narrow list is
  on*. (It IS on the roscomvpn whitelist; if that source is switched on, use another echo
  site and check it with the lookup first.)

Steps:

1. **Upgrade.** Pull `task/M34`, `make up-panel` (or the shape in use). Migration `0011` runs;
   every node reads *direct sites* off; the Nodes screen's config cell for the entry must stay
   **in sync** (off is byte-identical — the entry must NOT read behind after the upgrade).
2. **Routing screen.** The schedule line names the backup hour and zone from `.env` (no "is
   not set"/"is not a zone" sentence if `HASHI_BACKUP_TZ` is set). Suggestions list four
   sources. **add** `itdoginfo-russia-outside` → row "on", "nothing yet". **fetch now** →
   the button reads "fetching…", then the row shows a version, ~39 entries, "fetched less than
   an hour ago". The control log has one line per source, no domain names.
3. **Switch on.** Nodes → entry → **direct sites**: a resolver equal to the node's M16
   resolver is refused; `127.0.0.53` is refused; the provider's resolver from `resolvectl
   status` on the entry is accepted. **switch on**, **apply** the entry. Then on the entry:
   `docker exec <xray container> cat` the config (or read it under the node's config dir) —
   it has an outbound `direct`, rules with `domain:showip.net`, and `log.access: none`,
   `dnsLog: false`.
4. **Phone (VLESS link through the entry):** `showip.net` shows the ENTRY's address;
   `ifconfig.me` shows the LEAF's. `gosuslugi.ru` opens.
5. **Never direct.** Routing → **add entry** → never direct → `showip.net`; **apply
   entries**. Phone: `showip.net` now shows the LEAF's address. Remove the entry and apply.
6. **Hop down.** On the leaf, `docker stop` the hop container. Phone: `showip.net` opens (entry
   address), `ifconfig.me` does not open at all (no fallback). `docker start` it again.
7. **Off.** Switch off, apply: both sites show the leaf's address, and the rendered config's
   digest equals the one from before step 3 (the Nodes config cell reads in sync).
8. **Last good stays.** On the control host, make GitHub unreachable for the control container
   (e.g. an `/etc/hosts` override inside it, or a firewall rule), **fetch now**: the row says
   "last fetch … failed: the list's host could not be reached …" and still shows the version
   and its age; the entry's config is unchanged.
9. **Nothing recorded.** After the phone steps: `docker logs` of the entry's Xray container
   holds no destination name; the control log holds none; `psql` over the four `routing_*`
   tables holds lists only (no per-user, per-connection row); the audit screen shows "direct
   sites switched on on <entry>", "routing source … added", "never direct list changed" —
   never a site name.
10. **The first night.** The day after, the Routing screen's "Last nightly run" is that date;
    the entry was applied only if a list changed (its config cell in sync either way).

Not provable by any test or walk here: that the narrow list is the RIGHT list for the owner's
users — that is learned by use, and the owner's own *always direct* list is where it is fixed.
