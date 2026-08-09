"""VLESS over WebSocket behind TLS — the second transport profile.

This package exists to falsify a claim rather than to add a feature: the charter's
fourth criterion says a new protocol is one directory and nothing else. Adding it
touched no other transport, not ``edge/registry.py``, and not one line of
``control`` — it needed only key-material *kinds* that already existed. That
arithmetic is the proof, and ``tests/e2e/edge/`` asserts it.
"""
