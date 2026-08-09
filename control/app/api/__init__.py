"""JSON endpoints, one module per resource.

Every router here is mounted behind ``require_operator`` except ``delivery``, which
is unauthenticated by design — the subscription token in its path IS the credential.
"""
