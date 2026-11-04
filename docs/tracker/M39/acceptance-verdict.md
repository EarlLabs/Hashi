# Verdict · M39 · round 1: GOOD — may merge

## For the owner (not blocking)

- **works, but awkward** — Every /adduser reply is preceded by the fixed line 'adding, about a minute per node', emitted BEFORE the nickname is validated and regardless of how many nodes serve. So a duplicate name and an over-64-character name each show 'adding, about a minute per node' immediately followed by 'Nothing was added.', and on this empty fleet (0 nodes) the add is instant yet still announces 'about a minute per node'. Minor wording wrinkle; a line for the owner, not a blocker. It is pre-existing behaviour — M39 only relocated the bot to its own container and did not change any reply — so it is not an M39 regression. (Telegram bot, /adduser replies) [screen:tg-full-transcript.log]

## Could not check

(1) DEFERRED TO M40 (done-when item 4): the bot reaching Telegram from a real, blocked Russian host could not be observed — this stand's Telegram is a reachable fake, so the bot polls fine here; the 'polling is failing' blocked-host behaviour is M40 and not yet built. (2) The OPTIONAL enrichment of registering a node to see /nodes LIST a populated fleet, and a happy-path /apply against a serving node, were not exercised: the panel's add-node dialog did not complete a registration through the headless acceptance driver (it fell back to a native GET submission and the row never persisted — a driver/HTMX limitation, not an M39 change, and node-registration is control-plane machinery outside M39's scope), and a real /apply additionally needs a reachable host, which the stand does not seed. The scenario's primary /nodes and /apply checks were still met: /nodes → the empty-fleet 'Every serving node holds the configuration it would be given.' sentence, and /apply ghostnode → 'no node named \'ghostnode\'' (both require the BOT container to query the shared nodes table, which it did). (3) The charter's field criterion — surviving a real Russian mobile-whitelist shutdown — is not testable on any stand and was not claimed.

Spend: 35 actions, 16 minutes.
