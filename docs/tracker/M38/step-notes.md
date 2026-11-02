# M38 — step notes
Conventions established here. They bind later steps, and later milestones in
this codebase, until something supersedes them. Follow them; do not relitigate.
Everything in `docs/tracker/M37/step-notes.md` binds here too — M38 is built on
M37's bot.

## From M38.1 (`/nodes`, and the add's reply offers `/apply`) — commit 8e9b28c, review clean in round 1

- **`/nodes`** is a `_COMMANDS` entry (`_nodes`, argument ignored). It reads `console.nodes_missing_what_they_would_be_given(session)` only — never the probe, no network — and replies through `_messages` with one block per behind node: the console's `NOT_PUSHED` sentence filled for that one node, then `APPLY_IT = "apply it: /apply {name}"`. Empty list → `NOTHING_BEHIND = "Every serving node holds the configuration it would be given."` (the e2e asserts this literal on a fresh stand).
- **Node naming.** A node is named by its `name`, unquoted, verbatim (names may hold spaces, max 64) — never its id or address. `/apply` must take its whole argument as the name.
- **The add's reply** when a node could not be updated: links, then `AddOutcome.headline()` (the summary's unchanged opening `"<n> user(s) added and pushed to <k> node(s), but <m> node(s) could NOT be updated and do not know them yet:"`), then per failed node `onboarding.why_not_reached(kind, name=name)` + `APPLY_IT`; nodes the add reached get no offer; "no node is serving" still appends `summary()`. `AddOutcome.summary()` was split into `headline()` + `ReachOutcome.not_updated()` (`[(name, kind)]` sorted by name) with byte-identical output.
- **USAGE** now: `/adduser <nickname> — one nickname per line — adds them, pushes them to every serving node and replies with their links. /nodes — which serving nodes are behind what would be pushed, with the /apply for each. /apply <name> — the Nodes screen's Apply, for that one node. Everything else is on the panel.` A test asserts every `_COMMANDS` key appears in it, so registering `/apply` needs no USAGE change.
- **Helpers:** `_not_updated_block(name, kind)`, `_behind_block(node: console.BehindNode)` (formats `console.NOT_PUSHED` with singular fillers; if that template gains a placeholder this call site follows). Test harness: `a_node_left_behind(client, hosts_down, address=...)`; the node-name no-leak pattern in `test_a_node_that_is_behind_is_named_in_the_reply_and_in_no_log_record`; `"a stranger's /nodes"` in `STRANGERS` — add `/apply` the same way.
- **e2e:** `test_nodes_answers_what_the_nodes_screens_block_says` compares the names after `apply it: /apply ` with the Nodes screen's `Apply <name>` buttons (`GET /panel/nodes/table`); keep it last in the file.
- **To delete when `/apply` lands:** the `APPLY_IT` comment clause "`/apply` is M38.2's: this step prints the line that step answers".
