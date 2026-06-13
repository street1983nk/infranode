"""Public-Stub des Stores: No-Op-Write, leerer Read (stateless API)."""
from __future__ import annotations


async def append_record(record, source=None, **kwargs):
    """No-Op: der oeffentliche Live-Proxy persistiert nichts."""
    return None


def read_records(*args, **kwargs):
    """Leer: kein Archiv im oeffentlichen Build."""
    return []
