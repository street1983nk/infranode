"""Kanonisches Daten-Schema als einzige Quelle der Wahrheit (CORE-01).

Definiert den ``CanonicalRecord``-Envelope mit gemeinsamen Meta-Feldern (Geo,
Zeitstempel, Quelle, Lizenz, Tier, Attribution) plus austauschbarer, ueber das
``kind``-Feld diskriminierter Payload-Union. Lizenz und Tier sind Pflichtfelder
(kein Default), damit kein Datensatz ohne Tier-Tag ins System gelangt
(GOV-Fundament). ``extra="forbid"`` weist stumme Zusatzfelder ab und deckt so
Mapper-Tippfehler frueh auf.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import orjson
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from infranode.normalization.enums import LicenseId, LicenseTier, SourceId
from infranode.normalization.payloads import PayloadUnion

# Version des kanonischen Schemas. Additive Schema-Aenderungen zaehlen diese
# Konstante hoch (ARCH-02 Reproduzierbarkeit): ein Record traegt so
# die Schema-Version, unter der er entstanden ist. Bewusst NICHT Teil von
# ``content_hash`` (Dedup soll ueber Versionsgrenzen stabil bleiben).
SCHEMA_VERSION = 1


class GeoPoint(BaseModel):
    """Geokoordinate mit deklarativer Wertebereichs-Validierung (Wert-Objekt)."""

    model_config = ConfigDict(frozen=True)

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Attribution(BaseModel):
    """Wortgenaue Namensnennung plus optionale Lizenz-URL (Attribution-Pflicht)."""

    model_config = ConfigDict(frozen=True)

    text: str
    license_url: str | None = None
    modified: bool = False


class CanonicalRecord(BaseModel):
    """Einheitlicher Envelope fuer jeden normalisierten Stadt-Datensatz.

    Traegt die gemeinsamen Meta-Felder jeder Quelle plus eine ueber ``kind``
    diskriminierte Payload. ``license_tier`` ist Pflicht (kein Default), damit
    kein Datensatz ohne Tier-Tag entsteht. ``extra="forbid"`` verhindert stumme
    Zusatzfelder.

    Identitaet (ARCH-02): ``schema_version`` haelt die Schema-Version fest,
    ``record_id`` und ``content_hash`` sind deterministisch aus den Record-Daten
    abgeleitete ``computed_field``-Werte (kein Mapper setzt sie manuell). ``ags``
    und ``wikidata_qid`` sind Join-Keys auf amtliche bzw. Wikidata-Identifikatoren.

    Sicherheit: ``ags`` ist ein reines Datenfeld (amtlicher Gemeindeschluessel).
    Es darf NIE als Pfadsegment in einem Store verwendet werden (T-06.6-02); die
    Store-Pfade nutzen ausschliesslich die slug/tier-Allowlist. ``record_id`` und
    ``content_hash`` beziehen NUR offene Nutzdaten ein, die ohnehin im Envelope
    stehen, keine Secrets/PII (T-06.6-04, ASVS L1) -- alle Felder sind Open-Data.
    """

    model_config = ConfigDict(extra="forbid")

    city_slug: str
    geo: GeoPoint | None = None
    observed_at: datetime | None = None
    retrieved_at: datetime
    source: SourceId
    license_id: LicenseId
    license_tier: LicenseTier
    schema_version: int = SCHEMA_VERSION
    ags: str | None = None
    wikidata_qid: str | None = None
    attribution: Attribution
    payload: PayloadUnion

    @model_validator(mode="after")
    def _normalize_observed_at_utc(self) -> CanonicalRecord:
        """Fuehrt ``observed_at`` kanonisch als timezone-aware UTC.

        Naive Zeit (ohne tzinfo) wird als UTC interpretiert, aware Zeit nach UTC
        konvertiert; ``None`` bleibt ``None``. Garantiert vergleichbare Zeitanker
        ueber alle Quellen (ARCH-02).
        """
        if self.observed_at is not None:
            if self.observed_at.tzinfo is None:
                object.__setattr__(
                    self, "observed_at", self.observed_at.replace(tzinfo=UTC)
                )
            else:
                object.__setattr__(
                    self, "observed_at", self.observed_at.astimezone(UTC)
                )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def content_hash(self) -> str:
        """Deterministischer Hash der reinen Nutzdaten (Dedup-Schluessel).

        Schliesst bewusst ``retrieved_at``, ``record_id``, ``content_hash`` UND
        ``schema_version`` aus: zwei Abrufe derselben Nutzdaten (anderer
        ``retrieved_at``) oder eine additive Schema-Erhoehung duerfen den
        Dedup-Hash NICHT veraendern (T-06.6-03). Kanonisch via
        ``orjson.OPT_SORT_KEYS`` (dict-order-unabhaengig) + sha256.
        """
        payload = {
            "city_slug": self.city_slug,
            "geo": self.geo.model_dump(mode="json") if self.geo else None,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "source": self.source.value,
            "license_id": self.license_id.value,
            "license_tier": self.license_tier.value,
            "attribution": self.attribution.model_dump(mode="json"),
            "payload": self.payload.model_dump(mode="json"),
            "ags": self.ags,
            "wikidata_qid": self.wikidata_qid,
        }
        canonical = orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
        return hashlib.sha256(canonical).hexdigest()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def record_id(self) -> str:
        """Deterministische Identitaet eines Records (stabiler Primaerschluessel).

        Stabiler Schluessel aus Quelle, Stadt, Zeitanker (``observed_at`` falls
        gesetzt, sonst ``retrieved_at`` -- statische Quellen haben kein
        ``observed_at``), Payload-``kind`` und dem fachlichen Schluessel
        (``station_id``/``stop_id``/``poi_type``). Gleiche Eingabe -> gleiche ID;
        anderes ``observed_at`` oder anderer fachlicher Schluessel -> andere ID.
        Kanonisch via ``orjson.OPT_SORT_KEYS`` + sha256 (T-06.6-03).
        """
        anchor = self.observed_at if self.observed_at else self.retrieved_at
        business_key = (
            getattr(self.payload, "station_id", None)
            or getattr(self.payload, "stop_id", None)
            or getattr(self.payload, "poi_type", None)
        )
        key = {
            "source": self.source.value,
            "city_slug": self.city_slug,
            "anchor": anchor.isoformat() if anchor else None,
            "kind": self.payload.kind,
            "business_key": business_key,
        }
        canonical = orjson.dumps(key, option=orjson.OPT_SORT_KEYS)
        return hashlib.sha256(canonical).hexdigest()
