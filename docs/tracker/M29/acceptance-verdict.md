# Verdict · M29 · round 1: BLOCKED

## Report defects

- checklist items that did not pass: "The project's records are untouched."; "The migration has been run forward and back against a copy of real data.". The milestone's "done when" is not met

## For the owner (not blocking)

- **works, but awkward** — The subscription URL the panel hands the operator returns an empty 200 with a zero-length body when fetched as-is. The only enabled protocol on this node is a config-file shape, and the bare URL serves the URI-list shape, which is empty. An operator who pastes the link into a browser to check it before sending it sees a blank page and no word about why; the same URL with ?format=client-config-file returns a correct 1969-byte config zip. The panel does warn elsewhere that a config-file transport is fetched 'by asking for that shape', but nothing on the link dialog says the bare link will look dead. (Delivery endpoint /sub/{token}, reached from the 'show link' dialog on the Users screen) [screen:82-user-issued-082.png, db:SELECT id, transport_name, enabled, purpose, config_name FROM node_transports -> 1 row, amneziawg, enabled=True, purpose=users, config_name=amneziawg]

## Could not check

Three things. (1) The owner's 'restored from a real dump' half: the stand I was given is seeded empty (operator account only) and I have no access to any copy of the owner's data, so 'a subscription issued BEFORE the migration still fetches and still works on a device that already had it' could not be exercised - every subscription on this stand was issued after the migration. (2) The migrate-backwards half: I could not run the downgrade, so 'run the migration backwards and confirm the panel still works' is unverified here, and with it the checklist line about forward-and-back against real data. (3) 'The project's records are untouched' is not observable through the product on an empty seed - the audit log held nothing before my walk, so there was no prior record whose survival I could confirm. Two smaller gaps: the API's own responses could only be checked unauthenticated (/api/users answers 401 'operator login required', /api/friends answers 404), because the panel session cookie is not accepted by /api and I had no API credential; and 'code and the living documents' is not reachable through the product at all - what I can attest is that all eight rendered panel screens, every HTMX fragment they call, the static stylesheets, the delivered config file, the routes, the database schema and the stored audit actions contain zero occurrences of the old word. One process note: my first 'make verify' run failed on tests/e2e/infra/test_stack_boots.py because the acceptance stand's own browser container shares the hashi-e2e compose project and showed up as a fourth service. That is my stand contaminating the gate, not a product defect; re-run on a clean host it passed 192/192, exit 0.

Spend: 117 actions, 48 minutes.
