"""VLESS + Reality + XTLS-Vision over TCP — the first transport profile.

The package boundary is the point: everything this protocol knows about itself
lives in these four files, and nothing outside them mentions "reality" or
"vless". See ``edge/registry.py`` for the contract these files implement.
"""
