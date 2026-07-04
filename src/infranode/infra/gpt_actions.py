"""Erkennung von ChatGPT-GPT-Action-Traffic (OpenAI Custom GPTs).

Hintergrund: Das InfraNode-GPT im GPT Store ruft die API über OpenAI-Egress
auf. OpenAI sendet dabei dokumentierte Kennungs-Header mit (je Aufruf):

- ``openai-gpt-id``: welches GPT den Aufruf ausgelöst hat,
- ``openai-ephemeral-user-id``: pseudonyme, je Nutzer+GPT stabile Kennung,
- ``openai-conversation-id``: die Unterhaltung,

plus den User-Agent ``ChatGPT-User`` (Cloudflare-verifizierter Bot). Diese
Signale speisen drei Verbraucher (analog zum MCP-Kanal):

1. ntfy-Push je Aktion (ops/firstseen.note_gpt_action),
2. Metrik-Kanal ``gpt`` (Dashboard/Digest, main.MetricsMiddleware),
3. eigenes Rate-Limit je GPT-Nutzer (api/v1/gpt_guard), weil ALLE
   ChatGPT-Nutzer serverseitig über WENIGE OpenAI-Egress-IPs kommen und ein
   per-IP-Limit sie kollektiv drosseln würde (gleiches Muster wie
   Anthropic-Egress beim MCP-Server, s. infra/allowlist.py).

SPOOFING-EINORDNUNG: Die Header sind clientseitig fälschbar. Ein Spoofer
gewinnt dadurch aber NICHTS: die IP-basierten Limits (slowapi + AbuseGuard)
gelten für nicht-allowlistete IPs unverändert weiter, das GPT-Limit kommt
nur ZUSÄTZLICH dazu. Nur die Kanal-Beschriftung (Metrik/ntfy) wäre falsch;
die ntfy-Flut-Drossel (ops/notify) begrenzt den Schaden.

Stdlib-only (wie infra/allowlist.py), damit auch Nicht-FastAPI-Pfade das
Modul ohne Settings-/slowapi-Import nutzen können.
"""

from __future__ import annotations

from collections.abc import Mapping

# Dokumentierte OpenAI-Actions-Header (Starlette-Header sind case-insensitiv,
# .get() erwartet Kleinschreibung).
GPT_ID_HEADER = "openai-gpt-id"
GPT_USER_HEADER = "openai-ephemeral-user-id"
GPT_CONVERSATION_HEADER = "openai-conversation-id"

# UA-Marker der Actions-Aufrufe ("ChatGPT-User/1.0 (+https://openai.com/bot)").
_UA_MARKER = "chatgpt-user"


def is_gpt_action(headers: Mapping[str, str]) -> bool:
    """True, wenn der Request wie ein ChatGPT-GPT-Action-Aufruf aussieht.

    Erkennung über die OpenAI-Kennungs-Header ODER den ChatGPT-User-Agent;
    beide Signale zusammen decken auch Teil-Setups ab (z.B. UA ohne Header
    beim Actions-Import/Schema-Fetch).
    """
    if (
        headers.get(GPT_ID_HEADER)
        or headers.get(GPT_USER_HEADER)
        or headers.get(GPT_CONVERSATION_HEADER)
    ):
        return True
    return _UA_MARKER in headers.get("user-agent", "").lower()


def gpt_rate_ident(headers: Mapping[str, str], client_ip: str) -> str:
    """Zaehlschluessel für das GPT-Rate-Limit: Nutzer > Konversation > GPT > IP.

    Die ephemere Nutzer-Kennung ist je Nutzer+GPT stabil und damit der
    fairste Schluessel (jeder ChatGPT-Nutzer bekommt sein eigenes Budget).
    Fehlt sie, fallen wir auf die Konversation, dann das GPT, zuletzt die
    IP zurück (nie ohne Schluessel).
    """
    return (
        headers.get(GPT_USER_HEADER)
        or headers.get(GPT_CONVERSATION_HEADER)
        or headers.get(GPT_ID_HEADER)
        or client_ip
    )
