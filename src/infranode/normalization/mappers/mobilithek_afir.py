"""Reiner eRound-AFIR-Mapper (LIVE-11, CC0/Tier A, Phase 20).

Übersetzt das rohe Adapter-dict aus ``adapters/mobilithek_afir.py``
(``points``, eRound AFIR-Recharging, EnergyInfrastructureStatusPublication V3)
deterministisch in einen ``CanonicalRecord`` mit ``ChargingStatusPayload`` und
SourceId.EROUND_CHARGING (LIVE-11, schließt die DATA-09-Belegungslücke Laden).

Lizenz (Owner-Verifikation 2026-06-12, Checkpoint-Entscheid ``cc0-tier-a``): das
eRound-Angebot (mobilithek.info/offers/961629419076456448, Tab
Nutzungsbedingungen) weist als Standard-Lizenz **Creative Commons CC Zero**
(http://dcat-ap.de/def/licenses/cc-zero) aus -> ``license_id=CC0``,
``license_tier=A``. CC0 verlangt keine Attribution; Projekt-Konvention führt sie
dennoch konsistent ("Hamburger Energienetze GmbH / eRound").

Schablone ist ``mappers/mobilithek_parken.py`` (exakt): rein (kein HTTP, kein
Parse, keine Systemuhr), ``retrieved_at`` keyword-only injiziert
(deterministisch). Reine Live-Daten -> ``geo=None`` (der dynamische Feed trägt
nur Ladepunkt-IDs/Status); ``observed_at`` aus der DATEX-II ``publicationTime``
(``as_of``) falls vorhanden, sonst ``None`` (ehrlich, keine Systemuhr).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    ChargingStatusPayload,
    LicenseId,
    LicenseTier,
    SourceId,
)

_CC0_URL = "http://dcat-ap.de/def/licenses/cc-zero"
_EROUND_ATTRIBUTION = "Hamburger Energienetze GmbH / eRound"


def _parse_as_of(raw: dict) -> datetime | None:
    """Liest ``as_of`` (DATEX-II publicationTime) als aware ``datetime`` oder None.

    Rein (keine Systemuhr). Ein nicht-parsebarer/fehlender Wert -> ``None``
    (ehrlich, kein Fehler).
    """
    text = raw.get("as_of")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None


def map_eround_charging(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet die eRound-Ladesäulen-Belegung (points) auf einen ``CanonicalRecord`` ab.

    Die ``points`` (je Ladepunkt refill_point_id + status/observed_at, LIVE-11)
    wandern in den ``ChargingStatusPayload``. ``observed_at`` aus der DATEX-II
    ``publicationTime`` (``as_of``) falls vorhanden. ``retrieved_at`` injiziert
    (keine Systemuhr im Mapper). Tier A, CC0 (Owner-Verifikation, Checkpoint
    cc0-tier-a), Attribution "Hamburger Energienetze GmbH / eRound". Schließt
    die DATA-09-Echtzeit-Ladesäulenbelegungslücke.
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=_parse_as_of(raw),
        retrieved_at=retrieved_at,
        source=SourceId.EROUND_CHARGING,
        license_id=LicenseId.CC0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_EROUND_ATTRIBUTION,
            license_url=_CC0_URL,
        ),
        payload=ChargingStatusPayload(
            points=raw.get("points", []),
        ),
    )
