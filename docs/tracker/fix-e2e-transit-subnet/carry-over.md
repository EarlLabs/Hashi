# fix-e2e-transit-subnet — carry-over

Non-blocking, as background. Do not fix as part of another step.

- Low, accepted: a hard kill between the probe's create and its `finally` can leave a
  `hashi-m5-*-probe-*` network behind, because `Fleet.down` only knows the networks it kept. The
  window is tiny and the network holds nothing.
