# fix-e2e-transit-subnet

**Type:** fix
**Zone:** edge (`tests/e2e/edge/**`)
**Symptom:** on CI's engine (docker 28.0.4) nine hop and leaf scenarios in
`tests/e2e/edge/test_a_user_exits_at_the_leaf_and_not_at_the_entry.py` error at setup:
`docker run --network hashi-m5-transit-… --ip …` fails with "user specified IP address is
supported only when connecting to networks with user configured subnets". The scenarios
never ran, so `make verify` was red and nothing measured the exit or the lookup path.
**Expected:** the fixture brings the fleet up on any engine and the nine scenarios run.
**Reproduction:** on engine 28.0.4, `docker network create n`, read its subnet, then
`docker create --network n --ip <an address in that subnet> alpine true` is refused. Engine
29.7.2 accepts the same commands, so a developer's Mac does not show this.
Seen in CI runs 42010652973 (`105c731`) and 38367192152 (`a63f581`).
