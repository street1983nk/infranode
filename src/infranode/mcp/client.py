"""httpx-Wrapper um die lokale InfraNode-Live-FastAPI (DX-05).

Die MCP-Tools rufen ihre Daten ueber diesen Wrapper, nie direkt bei Upstreams.
Die Funktion ``get_resource`` baut die URL ausschliesslich aus der konfigurierten
Base-URL plus einem festen ``/cities/{slug}/{resource}``-Schema und gibt das
geparste JSON unveraendert zurueck (keine Mapping-/Lizenz-Logik, D-07/D-08).

Sicherheit:

- T-12-MCP-SSRF: Die Base-URL stammt ausschliesslich aus der Env
  ``INFRANODE_MCP_API_BASE`` (Default ``http://localhost:8000/api/v1``). Ihr Host
  wird gegen eine Allowlist geprueft; ein nicht-allowlisteter Host wird mit
  ``ValueError`` abgelehnt, bevor ein Request rausgeht. Eine arbitrary URL aus
  Tool-Argumenten ist nicht moeglich.
- T-12-MCP-INJECT: ``resource`` wird gegen die Konstante ``ALLOWED_RESOURCES``
  validiert und ``slug`` als reiner Pfadbestandteil url-gequotet, bevor die URL
  gebaut wird. Ein unbekannter ``resource`` oder ein Slug mit Pfad-/Host-Anteilen
  loest einen ``ValueError`` aus, bevor ein Request rausgeht.
"""

from __future__ import annotations

import os
from urllib.parse import quote, urlsplit

import httpx

# Default-Base-URL der lokalen Live-API (Loopback). Aus der Env ueberschreibbar,
# aber nur auf einen allowlisteten Host (siehe ALLOWED_HOSTS).
_DEFAULT_BASE_URL = "http://localhost:8000/api/v1"

# T-12-MCP-SSRF: Host-Allowlist. Die Liste ist bewusst eng gehalten; ein
# nicht-allowlisteter Host wird abgelehnt, bevor ein Request rausgeht.
# - localhost/127.0.0.1/::1: lokaler Subprozess (stdio) gegen eine lokale API.
# - api: der interne Compose-Service-Name. Im Remote-Betrieb (Phase 2) ruft der
#   MCP-Container die API ueber das Compose-Netz (http://api:8000/api/v1), NICHT
#   die oeffentliche URL (sonst teilen sich alle Nutzer eine IP -> Rate-Limit).
ALLOWED_HOSTS: frozenset[str] = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "::1",
        "api",
    }
)

# Header, mit dem der MCP-Server seine internen API-Aufrufe markiert. Die API-
# MetricsMiddleware erkennt ihn und macht MCP-Aktionen im Dashboard sichtbar +
# loest einen ntfy-Push aus (Owner-Wunsch: MCP-Aktionen verfolgen). Best-effort-
# Kennung, kein Auth-Mechanismus.
_MCP_SOURCE_HEADER = "X-Infranode-Mcp"

# T-12-MCP-INJECT: erlaubte Ressourcen-Namen, exakt die City-Sub-Ressourcen aus
# docs/openapi.yaml (GET /api/v1/cities/{slug}/<resource>). Roher Tool-Input wird
# gegen diese Konstante geprueft, bevor er in die URL gelangt.
ALLOWED_RESOURCES: frozenset[str] = frozenset(
    {
        "base",
        "air",
        "air-uba",
        "weather",
        "pois",
        "traffic",
        "transit",
        "charging",
        "water-level",
        "flood",
        "pollen-uv",
        "demographics",
        "energy",
        "geo",
        "election",
        "holidays",
        "health",
        "icu-live",
        "road-events",
        "events",
        "webcams",
        # SMARD/DWD (frueher ergaenzt, in der MCP-Allowlist nachgezogen).
        "power-load",
        "power-price",
        "weather-warnings",
        # DATA-27/28/29: KBA + GENESIS-Trio + Unfallatlas (Tier A, Kreis-Jahreswerte).
        "vehicle-registrations",
        "unemployment",
        "tourism",
        "construction",
        "accidents",
        # DATA-30: Tankerkoenig Spritpreise (Tier A, aggregiert je Stadt).
        "fuel-prices",
        # DATA-33: GBFS-Bike-/Scooter-Sharing (Tier A, aggregiert je Stadt).
        "sharing",
        # DATA-32: INKAR/BBSR sozialoekonomische Indikatoren je Kreis (Tier A).
        "indicators",
        # DATA-34: DB-Timetables Bahnhof-Abfahrten + -Ankuenfte Metropolen-Hbf (Tier A).
        "station-departures",
        "station-arrivals",
    }
)

# T-12-MCP-INJECT: erlaubte Live-Ressourcen-Pfade unter GET /api/v1/live/{slug}/...
# Mehrsegmentige Pfade sind hier zulaessig, weil sie gegen DIESE Allowlist
# geprueft werden (kein roher Tool-Input im Pfad ausser dem gequoteten slug).
ALLOWED_LIVE_RESOURCES: frozenset[str] = frozenset(
    {
        "transit/departures",
    }
)

# T-12-MCP-INJECT: erlaubte slug-lose Top-Level-Endpunkte (GET /api/v1/<name>),
# optional mit Query-Parametern. "compare" faechert eine Ressource ueber mehrere
# Staedte (cities/resource als Query, kein roher Input im Pfad).
ALLOWED_COLLECTIONS: frozenset[str] = frozenset(
    {
        "cities",
        "sources",
        "compare",
    }
)

# Timeout fuer den loopback-Call. Grosszuegig, da einige Upstreams hinter der
# Live-API langsam sein koennen, aber endlich (kein haengender Agent).
_TIMEOUT_SECONDS = 30.0


class UpstreamError(RuntimeError):
    """Lesbarer Fehler aus dem Antwort-Envelope der Live-API.

    Wird bei einem 4xx/5xx-Status geworfen, statt einen rohen
    ``httpx.HTTPStatusError``-Traceback an den Agenten zu geben. FastMCP wandelt
    eine geworfene Exception in einen Tool-Fehler um, dessen Text das Modell
    sieht; mit dieser Klasse traegt der Text die strukturierte API-Meldung inkl.
    ``hint``, sodass sich das Modell selbst korrigieren kann (z.B. ``list_cities``
    bei unbekanntem Slug aufrufen).
    """


def _build_upstream_error(response: httpx.Response) -> UpstreamError:
    """Formt aus einer Fehler-Response eine lesbare ``UpstreamError``.

    Bevorzugt den kanonischen API-Fehler-Envelope ``{"error": {"message",
    "hint", "code"}}``; faellt auf den (gekuerzten) Rohtext bzw. den HTTP-Grund
    zurueck, falls die Antwort kein erwartetes JSON ist.
    """
    detail = ""
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        err = body["error"]
        detail = " ".join(
            str(part) for part in (err.get("message"), err.get("hint")) if part
        )
    if not detail:
        detail = response.text[:200].strip() or response.reason_phrase
    return UpstreamError(f"InfraNode-API {response.status_code}: {detail}")


def _base_url() -> str:
    """Liest die Base-URL aus der Env und prueft den Host gegen die Allowlist.

    Gibt die validierte Base-URL ohne abschliessenden Schraegstrich zurueck.
    Loest ``ValueError`` aus, wenn das Schema nicht http/https ist oder der Host
    nicht in ``ALLOWED_HOSTS`` liegt (T-12-MCP-SSRF).
    """
    # Basis-URL aus INFRANODE_MCP_API_BASE, sonst Default. So
    # funktioniert die nach aussen dokumentierte Variable, ohne den bestehenden
    # Env-Vertrag zu brechen.
    raw = os.environ.get("INFRANODE_MCP_API_BASE", _DEFAULT_BASE_URL)
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https"):
        raise ValueError(
            f"Ungueltiges Schema fuer INFRANODE_MCP_API_BASE: "
            f"{parts.scheme!r}. Erlaubt sind nur http/https."
        )
    if parts.hostname not in ALLOWED_HOSTS:
        raise ValueError(
            f"Host {parts.hostname!r} ist nicht allowlistet (T-12-MCP-SSRF). "
            f"Erlaubt: {', '.join(sorted(ALLOWED_HOSTS))}."
        )
    return raw.rstrip("/")


def _validate_slug(slug: str) -> str:
    """Validiert und quotet den Slug als reinen Pfadbestandteil (T-12-MCP-INJECT).

    Ein Slug darf keine Pfad-Trenner oder Host-Anteile (``/``, ``@``, ``:``,
    Whitespace) enthalten; solche Eingaben koennten die URL umlenken. Gibt den
    url-gequoteten Slug zurueck oder loest ``ValueError`` aus.
    """
    if not slug or not isinstance(slug, str):
        raise ValueError("Slug muss ein nicht-leerer String sein.")
    # Reiner Pfadbestandteil: kein Slash/At/Doppelpunkt/Whitespace. Diese Zeichen
    # koennten Host/Userinfo/Pfad umlenken (z.B. "hamburg@evil.example/internal").
    forbidden = set("/@:\\ \t\n\r?#")
    if any(ch in forbidden for ch in slug):
        raise ValueError(
            f"Ungueltiger Slug {slug!r}: enthaelt unzulaessige Zeichen "
            "(Pfad-/Host-Trenner)."
        )
    return quote(slug, safe="")


async def get_resource(
    slug: str,
    resource: str,
    params: dict[str, str] | None = None,
) -> dict:
    """Ruft eine Stadt-Ressource der lokalen Live-API und gibt das JSON zurueck.

    Baut die URL ausschliesslich aus der allowlisteten Base-URL plus dem festen
    ``/cities/{slug}/{resource}``-Schema. ``resource`` wird gegen
    ``ALLOWED_RESOURCES`` geprueft, ``slug`` als reiner Pfadbestandteil gequotet
    und der Host der Base-URL gegen ``ALLOWED_HOSTS`` validiert, bevor ein Request
    rausgeht. Das Ergebnis (kanonischer ``{data, meta}``-Envelope der API) wird
    unveraendert zurueckgegeben, ohne jede Mapping-/Lizenz-Logik.

    Args:
        slug: Stadt-Slug (reiner Pfadbestandteil, z.B. ``"hamburg"``).
        resource: Ressourcen-Name aus ``ALLOWED_RESOURCES`` (z.B. ``"base"``).
        params: Optionale Query-Parameter (z.B. ``{"type": "hospital"}``).

    Raises:
        ValueError: Bei nicht-allowlistetem Host (T-12-MCP-SSRF) oder unbekanntem
            ``resource``/ungueltigem ``slug`` (T-12-MCP-INJECT), jeweils BEVOR ein
            Request rausgeht.
    """
    if resource not in ALLOWED_RESOURCES:
        raise ValueError(
            f"Unbekannte Ressource {resource!r} (T-12-MCP-INJECT). "
            f"Erlaubt: {', '.join(sorted(ALLOWED_RESOURCES))}."
        )
    safe_slug = _validate_slug(slug)
    # MCP-Kennung: der Ressourcen-Name (bereits gegen ALLOWED_RESOURCES validiert).
    return await _request(f"/cities/{safe_slug}/{resource}", params, tag=resource)


async def get_live(
    slug: str,
    live_resource: str,
    params: dict[str, str] | None = None,
) -> dict:
    """Ruft eine Live-Ressource ``/live/{slug}/{live_resource}``; gibt JSON zurueck.

    ``live_resource`` wird gegen ``ALLOWED_LIVE_RESOURCES`` geprueft, ``slug`` als
    reiner Pfadbestandteil gequotet und der Base-Host gegen ``ALLOWED_HOSTS``
    validiert, BEVOR ein Request rausgeht (T-12-MCP-SSRF/-INJECT). Envelope 1:1.

    Args:
        slug: Stadt-Slug (reiner Pfadbestandteil, z.B. ``"berlin"``).
        live_resource: Pfad aus ``ALLOWED_LIVE_RESOURCES`` (z.B.
            ``"transit/departures"``).
        params: Optionale Query-Parameter (z.B. ``{"stop_id": "..."}``).
    """
    if live_resource not in ALLOWED_LIVE_RESOURCES:
        raise ValueError(
            f"Unbekannte Live-Ressource {live_resource!r} (T-12-MCP-INJECT). "
            f"Erlaubt: {', '.join(sorted(ALLOWED_LIVE_RESOURCES))}."
        )
    safe_slug = _validate_slug(slug)
    return await _request(
        f"/live/{safe_slug}/{live_resource}", params, tag=f"live:{live_resource}"
    )


async def get_collection(
    name: str,
    params: dict[str, str] | None = None,
) -> dict:
    """Ruft einen slug-losen Collection-Endpunkt ``/{name}`` und gibt das JSON zurueck.

    ``name`` wird gegen ``ALLOWED_COLLECTIONS`` geprueft und der Base-Host gegen
    ``ALLOWED_HOSTS`` validiert, BEVOR ein Request rausgeht (T-12-MCP-SSRF/-INJECT).

    Args:
        name: Collection-Endpunkt aus ``ALLOWED_COLLECTIONS`` (``"cities"`` /
            ``"sources"``).
        params: Optionale Query-Parameter (z.B. Pagination).
    """
    if name not in ALLOWED_COLLECTIONS:
        raise ValueError(
            f"Unbekannter Collection-Endpunkt {name!r} (T-12-MCP-INJECT). "
            f"Erlaubt: {', '.join(sorted(ALLOWED_COLLECTIONS))}."
        )
    return await _request(f"/{name}", params, tag=f"collection:{name}")


async def _request(
    path: str,
    params: dict[str, str] | None,
    *,
    tag: str,
) -> dict:
    """Fuehrt den Loopback-GET gegen die allowlistete Base-URL aus (gemeinsamer Kern).

    ``path`` wird ausschliesslich aus bereits validierten Bestandteilen gebaut
    (gequoteter slug + allowlistete resource/collection); roher Tool-Input gelangt
    nie ungeprueft hierher. Der Base-Host wird in ``_base_url`` gegen die Allowlist
    geprueft. Die MCP-Kennung ``tag`` faehrt als Header mit (Dashboard/ntfy).
    """
    base = _base_url()
    url = f"{base}{path}"
    headers = {_MCP_SOURCE_HEADER: tag}

    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        response = await client.get(url, params=params, headers=headers)
        # Bei 4xx/5xx den strukturierten API-Fehler-Envelope als lesbare
        # UpstreamError durchreichen, statt einen rohen Traceback an den Agenten
        # zu geben (das Modell sieht so message + hint und kann sich korrigieren).
        if response.is_error:
            raise _build_upstream_error(response)
        return response.json()
