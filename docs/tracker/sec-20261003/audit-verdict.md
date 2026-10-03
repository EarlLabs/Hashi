# Security audit · http://127.0.0.1:54200 · gray-box · round 1: CLEAN — nothing exploitable found

## What I could not reach, and why

No exploitable crossing was found: all ten §3 boundaries held under live probing (27 requests). What was NOT reached or could not be proven exploitable: (1) §3.6 cryptographic forgery against the REAL signing key — forged/tampered/unsigned hashi_operator cookies were all denied fail-closed (023,024,025), but the strength of HASHI_SECRET_KEY itself was not tested: reading .env is forbidden and the stand uses a throwaway test key, so a weak-key forgery on a production deploy remains a config question this stand cannot answer. (2) §3.2/§3.3 full byte-level cross-tenant match — user_a's and user_b's config archives (020,021) are distinct and each carries a single config filtered by Credential.user_id, but the DB tunnel_address column is encrypted (SecretBox), so I could not decrypt it to byte-match archive-to-owner; isolation is structural (user_id filter) and confirmed distinct, not decrypted-matched. (3) §3.8 hostile-but-reachable list body — the probe fence allows only the stand origin, so the control plane's outbound fetch was exercised only against an UNREACHABLE https host (026,027): last_error was a bounded composed sentence and the URL/body reached neither the audit table nor any version row, but a live malicious list body's effect on rendering/escaping was reviewed in source only, not exercised. (4) The data plane, real nodes, and apply-over-SSH are out of scope (§4) and cannot run on this stand (no SSH hosts); apply was therefore never exercised. (5) The nightly routing-refresh timing window and the finding-remeasurer loop were not driven. Budget was not the limiter: 27/800 requests, 8/45 min.

## Scanners

- gitleaks: clean
- osv-scanner: 0 advisories

Spend: 27 requests, 8 minutes.
