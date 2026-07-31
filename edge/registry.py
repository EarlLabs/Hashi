"""Transport profile registry.

WHAT: discovers the transport packages under ``edge/transports/`` at runtime.
WHY:  the charter's fourth success criterion is that a brand-new protocol is one
      package and not surgery. Discovery is what makes that true: a hardcoded
      list here would mean every new transport edits this file, and then two
      developers edit it at once.
HOW:  each ``edge/transports/<name>/`` package exposes ``META`` in ``meta.py``.
      ``discover()`` imports them and returns them by name. No transports exist
      yet — it returns an empty mapping, which is correct, not broken.
"""

import importlib
import pkgutil
from dataclasses import dataclass

import edge.transports


@dataclass(frozen=True)
class TransportMeta:
    """What the control plane may know about a transport without knowing which."""

    name: str
    family: str          # "tcp-tls" | "udp" | ...
    needs_tls: bool


def discover() -> dict[str, TransportMeta]:
    """Return every installed transport profile, keyed by name."""
    found: dict[str, TransportMeta] = {}
    for module in pkgutil.iter_modules(edge.transports.__path__):
        if not module.ispkg:
            continue
        meta = importlib.import_module(f"edge.transports.{module.name}.meta").META
        if meta.name in found:
            raise ValueError(f"duplicate transport name: {meta.name!r}")
        found[meta.name] = meta
    return found
