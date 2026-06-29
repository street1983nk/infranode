"""Pro-Datensatz-Lizenz-Mapper map_license (GOV-04 Kern, T-10-CONTAM).

Reine Funktion ``map_license(raw) -> (LicenseId, LicenseTier)``: bildet einen
rohen Lizenz-String (oder eine Lizenz-URL) deterministisch auf das vorhandene
``LicenseId``/``LicenseTier``-Enum-Paar ab. Sie ist die einzige Quelle der
Wahrheit für die Lizenz->Tier-Zuordnung (REST-Regel 6) und wird vom
destination.one-Mapper PRO Record aufgerufen (D-05).

SICHERHEITSKRITISCHE PRÜFREIHENFOLGE (Pitfall 1, GOV-04): ShareAlike wird VOR
CC-BY geprüft. Andernfalls matcht "cc-by-sa-4.0" fälschlich als "cc-by" und ein
Copyleft-Record (Tier B) würde als Tier A getaggt und kontaminiert das
Produkt. Leer/None/unbekannt -> Tier C (Fail-safe, NIE Tier A).

Rein: keine Systemuhr, kein I/O, keine Log-Aufrufe.
"""

from __future__ import annotations

from infranode.normalization import LicenseId, LicenseTier


def map_license(raw: str | None) -> tuple[LicenseId, LicenseTier]:
    """Bildet einen rohen Lizenz-String auf ``(LicenseId, LicenseTier)`` ab.

    Normalisiert ``raw`` case-insensitive (lower, "-"/"_" zu Leerzeichen, strip)
    und prüft die Lizenz-Muster in einer sicherheitskritischen Reihenfolge
    (ShareAlike zuerst). Eine Lizenz-URL wie
    ``https://creativecommons.org/licenses/by-sa/4.0/`` wird korrekt erkannt, weil
    "by-sa" nach der Normalisierung "by sa" ergibt. Unbekannt/None -> Tier C
    (Fail-safe), niemals Tier A.
    """
    s = (raw or "").lower().replace("-", " ").replace("_", " ").strip()
    if not s:
        # NO_LICENSE/unbekannt -> NICHT Tier A (D-04, Fail-safe).
        return LicenseId.UNKNOWN, LicenseTier.C
    # Ein Creative-Commons-Indikator deckt sowohl Kürzel ("cc", "cc by") als auch
    # die kanonische Lizenz-URL (creativecommons.org) ab.
    is_cc = "cc" in s or "creativecommons" in s
    # CC-BY-SA -> Tier B (VOR cc-by!, Kontaminationsschutz, Pitfall 1). MITTEL-Fix
    # (Audit 2026-06-29): auf "by sa" gehärtet (vormals bloßes "sa"-Substring,
    # das z.B. in "rosa"/Freitext fälschlich ShareAlike erkannt hätte). "by sa"
    # fängt sowohl das Kürzel "cc by sa" als auch die Lizenz-URL
    # .../licenses/by-sa/4.0/ (nach Normalisierung "-" -> " "), analog "by nd".
    if is_cc and ("by sa" in s):
        return LicenseId.CC_BY_SA_4_0, LicenseTier.B
    # DL-DE VOR cc0/zero prüfen, sonst fängt "zero" ein "dl de zero" fälschlich
    # als CC0 (eigene DL-DE/Zero-ID wäre verloren).
    if "dl de" in s and "zero" in s:
        return LicenseId.DL_DE_ZERO_2_0, LicenseTier.A
    if "dl de" in s:
        return LicenseId.DL_DE_BY_2_0, LicenseTier.A
    if "cc0" in s or "zero" in s or "publicdomain" in s:
        return LicenseId.CC0, LicenseTier.A
    # CC-*-ND (No Derivatives) VOR cc-by: InfraNode normalisiert (= Bearbeitung),
    # was ND untersagt. Daher NIE Tier A, sondern Fail-safe Tier C (der aufrufende
    # Mapper schließt ND-Records zusätzlich ganz aus). ND ist stets "by-nd" ->
    # Substring "by nd" matcht Kürzel und URL, ohne falsche "nd"-Teiltreffer.
    if is_cc and "by nd" in s:
        return LicenseId.UNKNOWN, LicenseTier.C
    if is_cc and "by" in s:  # CC-BY (ohne SA/ND) -> Tier A
        return LicenseId.CC_BY_4_0, LicenseTier.A
    return LicenseId.UNKNOWN, LicenseTier.C  # Fail-safe: unbekannt -> NIE Tier A
