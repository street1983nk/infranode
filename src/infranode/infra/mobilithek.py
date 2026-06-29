"""Mobilithek-mTLS-Pull-Client (LIVE-04, Phase 20).

Das einzige genuin neue Infra-Modul der Phase: ein dedizierter
``httpx.AsyncClient``, der ein Client-Zertifikat NUR an ``mobilithek.info``
trägt (T-20-MTLS). httpx/ssl können ``.p12`` nicht direkt lesen, daher
konvertiert ``cryptography`` (pyca) das p12 beim Start zu PEM und baut daraus
einen ``ssl.SSLContext``.

Sicherheits-Invarianten:
- **PEM nie dauerhaft auf Disk** (T-20-PEM, Security V12): das entschlüsselte
  Schlüsselmaterial wird in eine kurzlebige tmpfs-Datei (``/dev/shm`` falls
  vorhanden) mit Modus 0600 geschrieben, von ``ssl.load_cert_chain`` gelesen und
  im ``finally`` SOFORT via ``os.unlink`` gelöscht.
- **gzip PFLICHT** (Pitfall 1): der Broker antwortet ohne
  ``Accept-Encoding: gzip`` mit leerem HTTP 400 (verifiziert 2026-06-12).
- **SSRF-Invariante** (T-20-SSRF): Host hartkodiert ``mobilithek.info:8443``,
  ``follow_redirects=False``, ``aboId`` NUR aus der Settings-Allowlist.
- **422 = no_data** (T-20-422): ein aktives Abo ohne Datenpaket liefert HTTP
  422; das wird als ``no_data`` behandelt (kein ``raise``, kein Breaker-Trip,
  kein Retry-Sturm). Nur 5xx/Netzfehler schlagen durch.
- **Passwort als SecretStr** (T-20-SECLOG): nie geloggt, nie im Cache-Key, nie
  in der Pull-URL.
"""

from __future__ import annotations

import os
import ssl
import tempfile

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12

from infranode.infra.http import USER_AGENT

#: PFLICHT-Header-Wert (Pitfall 1): ohne ``Accept-Encoding: gzip`` antwortet der
#: Broker mit leerem HTTP 400. Als Konstante exportiert (Test-Vertrag).
GZIP_HEADER = "gzip"

#: Mobilithek-Broker-Host HARTKODIERT (T-20-SSRF): nie aus Config/User-Input.
_MOBILITHEK_BASE = "https://mobilithek.info:8443/mobilithek/api/v1.0"

#: tmpfs-Verzeichnis für das kurzlebige PEM (T-20-PEM): ``/dev/shm`` hält das
#: entschlüsselte Schlüsselmaterial im RAM, nie auf der persistenten Disk.
_TMPFS_DIR = "/dev/shm" if os.path.isdir("/dev/shm") else None  # noqa: S108


def build_pull_url(abo_id: str, *, style: str = "path") -> str:
    """Baut die Mobilithek-Pull-URL für ein Abo (Host hartkodiert, SSRF).

    ``abo_id`` MUSS aus der Settings-Allowlist (``*_abo_id``) stammen, NIE aus
    User-Input (T-20-SSRF). Das Cert-Passwort taucht NIE in der URL auf
    (T-20-SECLOG). Der Host bleibt in JEDER Variante hartkodiert
    (``_MOBILITHEK_BASE``), die SSRF-Invariante gilt unverändert.

    Drei verifizierte Zugriffspunkt-Muster (Mobilithek-Portal/Service Desk):
    - ``style="path"`` (Default, die V2-Stadt-Abos): mit
      ``/subscription/{aboId}/clientPullService?subscriptionID={aboId}``.
    - ``style="query"`` (das eRound-AFIR-Abo, LIVE-11): OHNE das
      ``/{aboId}/clientPullService``-Pfadsegment, nur
      ``/subscription?subscriptionID={aboId}``.
    - ``style="container"`` (Legacy-Datenmodell, Techn. SST-Beschreibung
      Kap. 7.3.2.2.1; vom Mobilithek-Service-Desk 2026-06-15 für das
      DELFI-GTFS-RT-Abo bestätigt): ``/container/subscription?subscriptionID=
      {aboId}``. Der modernere ``path``-Zugriff (Kap. 6.2.1) gibt für dieses
      Legacy-Abo einen 4xx-Fehler.
    """
    if style == "container":
        return f"{_MOBILITHEK_BASE}/container/subscription?subscriptionID={abo_id}"
    if style == "query":
        return f"{_MOBILITHEK_BASE}/subscription?subscriptionID={abo_id}"
    return (
        f"{_MOBILITHEK_BASE}/subscription/{abo_id}/clientPullService"
        f"?subscriptionID={abo_id}"
    )


def build_mtls_context(p12_path: str, password: str) -> ssl.SSLContext:
    """Baut einen ``ssl.SSLContext`` aus einer ``.p12``-Datei (mTLS, T-20-PEM).

    Liest die p12-Bytes, entschlüsselt Key + Cert (+ Chain) via
    ``cryptography`` (pyca), serialisiert sie als PEM in eine kurzlebige
    tmpfs-Datei (Modus 0600), lädt diese in den Context und LÖSCHT sie sofort
    im ``finally`` (entschlüsseltes Schlüsselmaterial nie dauerhaft auf Disk,
    Security V12 / Pitfall 2). ``password`` ist der entschlüsselte SecretStr-
    Wert; er wird nie geloggt.
    """
    with open(p12_path, "rb") as fh:
        p12_bytes = fh.read()

    key, cert, chain = pkcs12.load_key_and_certificates(p12_bytes, password.encode())
    if key is None or cert is None:
        raise ValueError("p12 enthaelt keinen Private-Key oder kein Zertifikat")

    pem = cert.public_bytes(serialization.Encoding.PEM)
    pem += key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    for ca in chain or []:
        pem += ca.public_bytes(serialization.Encoding.PEM)

    ctx = ssl.create_default_context()
    # Datei mit restriktivem Modus (0600) auf tmpfs (RAM) erzeugen; delete=False,
    # damit wir Pfad an load_cert_chain geben können, dann im finally unlink.
    tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115
        mode="wb", delete=False, dir=_TMPFS_DIR, suffix=".pem"
    )
    try:
        os.chmod(tmp.name, 0o600)
        tmp.write(pem)
        tmp.flush()
        tmp.close()
        ctx.load_cert_chain(certfile=tmp.name)
    finally:
        # Entschlüsseltes PEM SOFORT löschen (T-20-PEM / Security V12).
        os.unlink(tmp.name)
    return ctx


def create_mobilithek_client(settings) -> httpx.AsyncClient:
    """Baut den dedizierten mTLS-Client NUR für Mobilithek (T-20-MTLS).

    Analog ``infra/http.create_http_client``, ABER mit ``verify=SSLContext``
    (Client-Cert) und PFLICHT-Header ``Accept-Encoding: gzip``. Ein EIGENER
    Client, NICHT der geteilte ``app.state.http`` (das Cert darf nie an fremde
    Hosts gehen). ``follow_redirects=False`` hält die SSRF-Invariante.
    """
    ctx = build_mtls_context(
        settings.mobilithek_cert_path,
        settings.mobilithek_cert_password.get_secret_value(),
    )
    return httpx.AsyncClient(
        verify=ctx,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Encoding": GZIP_HEADER,  # PFLICHT (Pitfall 1)
        },
        # Konservativer Default; Mobilithek kann minutenfrisch sein, aber nicht
        # ewig hängen dürfen.
        timeout=httpx.Timeout(connect=2.0, read=10.0, write=5.0, pool=1.0),
        follow_redirects=False,  # SSRF-Invariante (T-20-SSRF)
    )


async def close_mobilithek_client(client: httpx.AsyncClient | None) -> None:
    """Schliesst den Mobilithek-Client samt Pool sauber (no-op bei None)."""
    if client is not None:
        await client.aclose()


async def pull_subscription(client: httpx.AsyncClient, url: str) -> dict:
    """Pullt ein Mobilithek-Abo: 422 = no_data, sonst raise_for_status (T-20-422).

    ``url`` MUSS via ``build_pull_url`` aus einer Allowlist-``abo_id`` gebaut
    sein (Host hartkodiert, SSRF). HTTP 422 (Abo aktiv, kein Datenpaket) liefert
    ``{"status": "no_data", "body": None}`` OHNE ``raise`` (kein Breaker-Trip,
    kein Retry-Sturm). 200 liefert ``{"status": "ok", "body": <bytes>}``; 5xx/
    sonstige Fehler schlagen via ``raise_for_status`` durch.
    """
    resp = await client.get(url)
    if resp.status_code == 422:
        return {"status": "no_data", "body": None}
    resp.raise_for_status()
    return {"status": "ok", "body": resp.content}
