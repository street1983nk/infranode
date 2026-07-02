"""IP-Allowlist für Rate-Limit-Bypass (Security-/Betriebs-Härtung 2026-07-02).

Hintergrund: Remote-MCP-Traffic aus dem Anthropic Connectors Directory kommt
serverseitig über WENIGE Anthropic-Egress-IPs. Ein per-IP-/Subnetz-Limit würde
dieses legitime Aggregat drosseln, obwohl dahinter viele verschiedene Endnutzer
stehen. Dieses Modul stellt den gemeinsamen CIDR-Check für ALLE Limiter bereit
(MCP-Middleware, AbuseGuard-Subnetz-Limit, slowapi-IP-Limit).

Eigenschaften:

- NUR Limit-Bypass, KEINE Authentifizierung/Autorisierung: eine allowlistete IP
  bekommt keinerlei zusätzliche Rechte, sie wird lediglich nicht gedrosselt.
- ENV-konfigurierbar ohne Code-Deploy: ``INFRANODE_RATELIMIT_ALLOWLIST`` als
  kommagetrennte CIDR-Liste (v4/v6 gemischt; nackte IPs zählen als /32 bzw.
  /128). Leer (Default) = Feature aus = bisheriges Verhalten.
- FAIL-SAFE: leere oder unparsebare Konfiguration allowlistet NIEMANDEN.
  Ungültige Einträge werden verworfen (Warnung geloggt), gültige Reste gelten
  weiter; eine unparsebare Client-IP ist nie allowlistet.
- Bewusst stdlib-only (``ipaddress``): der MCP-Service importiert dieses Modul,
  ohne den FastAPI-/Settings-Pfad zu ziehen (gleiches Prinzip wie die
  eigenständige ``client_ip``-Kopie in ``mcp/ratelimit.py``).

Die Client-IP stammt bei allen Aufrufern aus CF-Connecting-IP/XFF[0] und ist
nur unter der CF-only-Firewall vertrauenswürdig (s. ratelimit.real_client_ip);
die Allowlist erbt diese Vertrauens-Vorbedingung.
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Sequence
from functools import lru_cache

logger = logging.getLogger(__name__)

# Gemeinsamer Env-Name: identisch mit dem pydantic-Settings-Feld
# ``ratelimit_allowlist`` (Prefix INFRANODE_), damit EINE Variable API- und
# MCP-Container gleichermaßen konfiguriert.
ENV_VAR = "INFRANODE_RATELIMIT_ALLOWLIST"

_Network = ipaddress.IPv4Network | ipaddress.IPv6Network


@lru_cache(maxsize=16)
def parse_allowlist(raw: str | None) -> tuple[_Network, ...]:
    """Parst die kommagetrennte CIDR-Liste zu Netzwerken (fail-safe).

    Ungültige Einträge werden verworfen und EINMAL pro Konfigurationswert
    geloggt (lru_cache dedupliziert Wiederholungen); gültige Einträge derselben
    Liste bleiben wirksam. ``None``/leer/nur-Whitespace ergibt ``()`` = niemand
    allowlistet. ``strict=False`` erlaubt Host-Bits (z.B. "10.1.2.3/24").
    """
    if not raw or not raw.strip():
        return ()
    networks: list[_Network] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            networks.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            logger.warning(
                "Rate-Limit-Allowlist: ungueltiger CIDR-Eintrag %r verworfen.", part
            )
    return tuple(networks)


def ip_allowlisted(ip: str, networks: Sequence[_Network]) -> bool:
    """True, wenn ``ip`` in einem der Allowlist-Netze liegt (sonst/bei Müll False).

    IPv4-mapped IPv6-Adressen (``::ffff:203.0.113.5``) matchen auch reine
    v4-CIDRs, damit ein v6-Listener dieselbe Allowlist nutzt.
    """
    if not networks:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    mapped = getattr(addr, "ipv4_mapped", None)
    return any(
        addr in net or (mapped is not None and mapped in net) for net in networks
    )
