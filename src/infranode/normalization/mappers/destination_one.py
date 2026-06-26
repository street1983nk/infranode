"""Reiner Pro-Record-Event-Mapper map_destination_one_events (DATA-16, GOV-04).

Uebersetzt rohe destination.one-Events in eine LISTE von ``CanonicalRecord``s mit
``EventPayload``. ABWEICHUNG vom Phase-5/7/9-Muster (D-05/GOV-04): license_id und
license_tier werden NICHT pauschal hartkodiert, sondern PRO Record aus
``map_license(event["license_raw"])`` abgeleitet. Die Events werden nach dem
``map_license``-Ergebnis nach Tier GRUPPIERT; je Tier-Gruppe entsteht EIN
``CanonicalRecord`` (ein Record mit gemischter Liste kann nicht zwei Tiers tragen,
Open Question 1). ``license_tier`` am Record kennzeichnet die jeweilige Lizenz:
ein CC-BY-SA-Event traegt Tier B, ein CC0/CC-BY-Event Tier A (GOV-04, korrekte
Attribution und Weiternutzung je Record).

Zukunftsfilter (D-07, Pitfall 6): Events mit ``date_to`` vor dem
``retrieved_at``-Datum werden verworfen; ein Event ohne jedes verwertbare
Zukunftsdatum gilt als historisch und wird ausgeschlossen. Der Datums-Bezug
stammt aus dem injizierten ``retrieved_at`` (keine Systemuhr / ``datetime.now()``
im Mapper), damit der Test deterministisch bleibt.

Rein: kein HTTP, keine Log-Aufrufe, keine Systemuhr.
"""

from __future__ import annotations

from datetime import date, datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    EventPayload,
    LicenseId,
    LicenseTier,
    SourceId,
)
from infranode.normalization.mappers.licensing import map_license

# Lizenz-URL je license_id fuer die Attribution (wortgenau zur DATA-LICENSES.md).
_LICENSE_URLS: dict[LicenseId, str] = {
    LicenseId.CC0: "https://creativecommons.org/publicdomain/zero/1.0/",
    LicenseId.CC_BY_4_0: "https://creativecommons.org/licenses/by/4.0/",
    LicenseId.CC_BY_SA_4_0: "https://creativecommons.org/licenses/by-sa/4.0/",
    LicenseId.DL_DE_BY_2_0: "https://www.govdata.de/dl-de/by-2-0",
    LicenseId.DL_DE_ZERO_2_0: "https://www.govdata.de/dl-de/zero-2-0",
}

# destination.one verlangt UNABHAENGIG von der CC-Lizenz die wortgenaue Nennung
# "powered by open.destination.one" inkl. Backlink je Datensatz.
_ATTRIBUTION_TEXT = "powered by open.destination.one (https://open.destination.one)"


def _parse_iso_date(value: object) -> date | None:
    """Parst ein ISO-Datum (YYYY-MM-DD oder vollstaendiger Zeitstempel) defensiv.

    Liefert ``None`` bei fehlendem/unparsbarem Wert (kein Crash, [ASSUMED]-Felder).
    """
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _is_future(event: dict, *, today: date) -> bool:
    """True, wenn das Event noch nicht abgeschlossen ist (date_to >= today).

    Faellt auf ``date_from`` zurueck, wenn ``date_to`` fehlt. Ein Event ohne jedes
    verwertbare Datum gilt als historisch (D-07) und wird ausgeschlossen.
    """
    end = _parse_iso_date(event.get("date_to")) or _parse_iso_date(
        event.get("date_from")
    )
    if end is None:
        return False
    return end >= today


def map_destination_one_events(
    raw: dict | list[dict],
    *,
    retrieved_at: datetime,
    slug: str | None = None,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> list[CanonicalRecord]:
    """Bildet rohe destination.one-Events auf je-Tier-``CanonicalRecord``s ab.

    ``raw`` ist entweder das Adapter-dict (``{"slug": ..., "events": [...]}``) oder
    direkt eine Event-Liste; in letzterem Fall muss ``slug`` als Keyword gesetzt
    sein. Der Zukunftsfilter (D-07) verwirft Vergangenheits-/Statistik-Events
    anhand des injizierten ``retrieved_at`` (kein ``datetime.now()``). Die
    ueberlebenden Events werden je ``map_license``-Tier gruppiert; je Tier ein
    Record (Tier aus ``map_license``, GOV-04). Gibt eine leere Liste zurueck, wenn
    keine Events ueberleben.
    """
    if isinstance(raw, dict):
        events = raw.get("events", []) or []
        city_slug = raw.get("slug", slug)
    else:
        events = raw or []
        city_slug = slug
    if city_slug is None:
        raise ValueError("slug fehlt: weder im raw-dict noch als Keyword uebergeben")

    today = retrieved_at.date()

    # Pro Tier eine Gruppe (Tier + license_id aus map_license PRO Record). Nur
    # Zukunfts-Events ueberleben den D-07-Filter.
    groups: dict[LicenseTier, tuple[LicenseId, list[dict]]] = {}
    for event in events:
        if not _is_future(event, today=today):
            continue
        # CC-*-ND (No Derivatives): InfraNode normalisiert (= Bearbeitung), was ND
        # untersagt. Solche Events werden gar nicht ausgeliefert (nicht nur Tier-C).
        raw_lic = (event.get("license_raw") or "").lower()
        raw_lic = raw_lic.replace("-", " ").replace("_", " ")
        is_cc_raw = "cc" in raw_lic or "creativecommons" in raw_lic
        if is_cc_raw and "by nd" in raw_lic:
            continue
        license_id, license_tier = map_license(event.get("license_raw"))
        if license_tier not in groups:
            groups[license_tier] = (license_id, [])
        groups[license_tier][1].append(event)

    records: list[CanonicalRecord] = []
    for license_tier, (license_id, group_events) in groups.items():
        records.append(
            CanonicalRecord(
                city_slug=city_slug,
                geo=None,
                observed_at=None,  # Event traegt seine Zeit im Payload
                retrieved_at=retrieved_at,
                source=SourceId.DESTINATION_ONE,
                license_id=license_id,
                license_tier=license_tier,  # steuert physisch das Store-Tier (GOV-04)
                ags=ags,
                wikidata_qid=wikidata_qid,
                attribution=Attribution(
                    text=_ATTRIBUTION_TEXT,
                    license_url=_LICENSE_URLS.get(license_id),
                    modified=True,  # InfraNode normalisiert die Events (Bearbeitung)
                ),
                payload=EventPayload(
                    city_source="destination_one",
                    events=group_events,
                ),
            )
        )
    return records
