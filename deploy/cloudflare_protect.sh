#!/usr/bin/env bash
# deploy/cloudflare_protect.sh - Cloudflare-Schutzschicht fuer InfraNode (Security-Haertung 2026-06-21)
#
# Richtet die EDGE-seitige Verteidigung ein, die der App-Code nicht leisten kann:
#   1. Rate Limiting Rule: harte IP-Volumengrenze gegen Floods (grobe aeussere
#      Schicht; das feine 120/min;3000/h macht die App in config.py).
#   2. Cache Rule: API-JSON unter /api/v1/* wird am Edge gecached und RESPEKTIERT
#      das Origin-Cache-Control (max-age/s-maxage/stale-while-revalidate aus
#      infra/etag.py). Das ist der eigentliche DoS-/Scraping-Daempfer: ein
#      Scraper, der dieselben Endpunkte haemmert, trifft den Edge-Cache, nicht
#      das Origin.
#
# BEWUSST NICHT aktiviert: Bot Fight Mode / "Block AI bots". InfraNode ist eine
# ABSICHTLICH maschinenfreundliche, keylose API (MCP-Clients, Data-Science-
# Skripte, Agenten). Ein Bot-Blocker wuerde genau die legitimen Nutzer aussperren
# (Managed Challenge laesst sich von einem API-Client nicht loesen). Siehe
# docs/DEPLOYMENT.md, Pitfall "Bot-Fight-Mode-Blockade der Agenten-API".
#
# Voraussetzungen:
#   - CF_API_TOKEN: Token mit den Zone-Rechten "Zone WAF: Edit",
#     "Zone Cache Rules: Edit" (bzw. "Dynamic Redirect/Config Rules: Edit").
#   - CF_ZONE_ID:  Zone-ID von infranode.dev (Cloudflare Dashboard -> Overview).
#   - curl, jq.
#
# Nutzung:
#   CF_API_TOKEN=... CF_ZONE_ID=... bash deploy/cloudflare_protect.sh
#   # nur anzeigen, nichts aendern:
#   CF_API_TOKEN=... CF_ZONE_ID=... bash deploy/cloudflare_protect.sh --dry-run
#
# Das Skript ist IDEMPOTENT: es schreibt den Entrypoint der jeweiligen Phase
# deklarativ (PUT). WARNUNG: bestehende eigene Regeln in den Phasen
# http_ratelimit und http_request_cache_settings werden dabei ersetzt. Vorher
# mit --dry-run den aktuellen Stand pruefen.

set -euo pipefail

API="https://api.cloudflare.com/client/v4"
DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

: "${CF_API_TOKEN:?CF_API_TOKEN fehlt (Token mit Zone WAF + Cache Rules Edit)}"
: "${CF_ZONE_ID:?CF_ZONE_ID fehlt (Zone-ID von infranode.dev)}"

# Konfigurierbare Schwellen (Env-overridebar). Die Edge-Grenze liegt bewusst
# DEUTLICH ueber dem App-Limit (120/min): sie kappt nur grobe Volumen-Floods,
# das feine Limit macht die App. period in Sekunden, mitigation_timeout = wie
# lange eine ueberschreitende IP geblockt bleibt.
# WICHTIG: Der Cloudflare-Free-Plan erlaubt fuer Rate-Limiting-Rules NUR period=10
# (API-Fehler sonst: "not entitled to use the period 60"). Default daher 100/10s
# (entspricht effektiv 600/min). Auf hoeheren Plaenen sind groessere Perioden via
# RL_PERIOD moeglich.
RL_REQUESTS="${RL_REQUESTS:-100}"
RL_PERIOD="${RL_PERIOD:-10}"
RL_TIMEOUT="${RL_TIMEOUT:-10}"

# Bekannte AGGRESSIVE SEO-/Scraper-Bots ohne API-Mehrwert, die typischerweise
# verteilt abgrasen (Scraping-Haertung). BEWUSST NICHT in der Liste:
#   - AI-Crawler (GPTBot/ClaudeBot/PerplexityBot/Google-Extended): via robots.txt
#     ABSICHTLICH erlaubt (GEO/Auffindbarkeit in KI-Antworten),
#   - generische HTTP-Clients (python-requests/httpx/curl/node-fetch): das sind
#     legitime Data-Science-/Vibecoder-Nutzer der keylosen API.
# Diese Bots sind kommerzielle SEO-Crawler, die InfraNode-Daten ohne Nutzen
# abgreifen und oft robots.txt ignorieren -> harte Block-Regel (kein Challenge,
# das wuerde nur CPU kosten ohne dass ein Bot es loest). Per BAD_BOTS (kommagetrennt,
# Substring-Match auf den lowercased User-Agent) anpassbar; leer = WAF-Regel aus.
BAD_BOTS="${BAD_BOTS:-ahrefsbot,semrushbot,mj12bot,dotbot,blexbot,dataforseobot,petalbot,barkrowler,zoominfobot}"

cf() {
  # cf METHOD PATH [JSON-BODY]
  local method="$1" path="$2" body="${3:-}"
  if [[ -n "$body" ]]; then
    curl -sS -X "$method" "$API$path" \
      -H "Authorization: Bearer $CF_API_TOKEN" \
      -H "Content-Type: application/json" \
      --data "$body"
  else
    curl -sS -X "$method" "$API$path" \
      -H "Authorization: Bearer $CF_API_TOKEN" \
      -H "Content-Type: application/json"
  fi
}

check_ok() {
  # liest die Cloudflare-Antwort von stdin, bricht bei success:false ab.
  local resp; resp="$(cat)"
  if [[ "$(jq -r '.success' <<<"$resp")" != "true" ]]; then
    echo "FEHLER von Cloudflare:" >&2
    jq -r '.errors' <<<"$resp" >&2
    exit 1
  fi
  echo "$resp"
}

echo "== InfraNode Cloudflare-Schutz =="
echo "Zone: $CF_ZONE_ID"
echo "Rate-Limit: > ${RL_REQUESTS} Requests / ${RL_PERIOD}s pro IP -> block ${RL_TIMEOUT}s"
echo

# --- Phase 1: Rate Limiting Rule -------------------------------------------------
# characteristics enthaelt cf.colo.id: auf Free-/Pro-Plaenen zaehlt Cloudflare
# pro Rechenzentrum (per-colo). ip.src ist der eigentliche Schluessel.
RL_BODY="$(jq -n \
  --argjson req "$RL_REQUESTS" --argjson per "$RL_PERIOD" --argjson to "$RL_TIMEOUT" '{
  rules: [{
    action: "block",
    description: "InfraNode: harte IP-Volumengrenze (Flood-Schutz; feines Limit macht die App)",
    expression: "(http.host eq \"infranode.dev\") or (http.host eq \"mcp.infranode.dev\")",
    ratelimit: {
      characteristics: ["ip.src", "cf.colo.id"],
      period: $per,
      requests_per_period: $req,
      mitigation_timeout: $to
    }
  }]
}')"

# --- Phase 3: WAF Custom Rule (Bad-Bot-Block) ------------------------------------
# Blockt bekannte aggressive SEO-/Scraper-Bots per User-Agent-Substring. Eine
# Custom-WAF-Regel (mehrere OR-Bedingungen = 1 Regel; im Free-Plan verfuegbar).
# Greift NUR auf den InfraNode-Hosts. Leeres BAD_BOTS -> Regelsatz leer (Phase aus).
WAF_EXPR=""
if [[ -n "$BAD_BOTS" ]]; then
  IFS=',' read -ra _bots <<<"$BAD_BOTS"
  _ua=""
  for b in "${_bots[@]}"; do
    b="$(echo "$b" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')"
    [[ -z "$b" ]] && continue
    cond="(lower(http.user_agent) contains \"$b\")"
    _ua="${_ua:+$_ua or }$cond"
  done
  # nur auf den eigenen Hosts greifen, sonst Bot-UA egal.
  WAF_EXPR="((http.host eq \"infranode.dev\") or (http.host eq \"mcp.infranode.dev\")) and (${_ua})"
fi

if [[ -n "$WAF_EXPR" ]]; then
  WAF_BODY="$(jq -n --arg expr "$WAF_EXPR" '{
    rules: [{
      action: "block",
      description: "InfraNode: bekannte aggressive SEO-/Scraper-Bots blocken (keine AI-Crawler, keine generischen HTTP-Clients)",
      expression: $expr
    }]
  }')"
else
  WAF_BODY="$(jq -n '{rules: []}')"
fi

# --- Phase 2: Cache Rule ---------------------------------------------------------
# set_cache_settings + respect_origin: Cloudflare cached /api/v1/* am Edge und
# folgt dem Origin-Cache-Control (max-age/s-maxage/swr). serve_stale aktiv lassen,
# damit stale-while-revalidate am Edge wirkt.
CACHE_BODY="$(jq -n '{
  rules: [{
    action: "set_cache_settings",
    description: "InfraNode: API-JSON am Edge cachen, Origin-Cache-Control respektieren",
    expression: "(starts_with(http.request.uri.path, \"/api/v1/\"))",
    action_parameters: {
      cache: true,
      edge_ttl: { mode: "respect_origin" },
      browser_ttl: { mode: "respect_origin" },
      serve_stale: { disable_stale_while_updating: false }
    }
  }]
}')"

if [[ "$DRY_RUN" == "1" ]]; then
  echo "[dry-run] Rate-Limit-Phase (http_ratelimit), aktueller Stand:"
  cf GET "/zones/$CF_ZONE_ID/rulesets/phases/http_ratelimit/entrypoint" | jq -r '.result.rules // []'
  echo
  echo "[dry-run] Cache-Phase (http_request_cache_settings), aktueller Stand:"
  cf GET "/zones/$CF_ZONE_ID/rulesets/phases/http_request_cache_settings/entrypoint" | jq -r '.result.rules // []'
  echo
  echo "[dry-run] WAF-Custom-Phase (http_request_firewall_custom), aktueller Stand:"
  cf GET "/zones/$CF_ZONE_ID/rulesets/phases/http_request_firewall_custom/entrypoint" | jq -r '.result.rules // []'
  echo
  echo "[dry-run] Wuerde Rate-Limit-Regel setzen:"; echo "$RL_BODY" | jq .
  echo "[dry-run] Wuerde Cache-Regel setzen:";       echo "$CACHE_BODY" | jq .
  echo "[dry-run] Wuerde Bad-Bot-WAF-Regel setzen:"; echo "$WAF_BODY" | jq .
  exit 0
fi

echo "-> Setze Rate-Limiting-Regel ..."
cf PUT "/zones/$CF_ZONE_ID/rulesets/phases/http_ratelimit/entrypoint" "$RL_BODY" | check_ok >/dev/null
echo "   ok."

echo "-> Setze Cache-Regel ..."
cf PUT "/zones/$CF_ZONE_ID/rulesets/phases/http_request_cache_settings/entrypoint" "$CACHE_BODY" | check_ok >/dev/null
echo "   ok."

echo "-> Setze Bad-Bot-WAF-Regel ..."
cf PUT "/zones/$CF_ZONE_ID/rulesets/phases/http_request_firewall_custom/entrypoint" "$WAF_BODY" | check_ok >/dev/null
echo "   ok."

echo
echo "Fertig. Hinweise:"
echo " - Bot Fight Mode bewusst NICHT aktiviert (wuerde MCP/Agenten/Data-Science blocken)."
echo " - Optional im Dashboard: Tiered Cache (Caching -> Tiered Cache) fuer weniger Origin-Hits."
echo " - Re-Check jederzeit: bash deploy/cloudflare_protect.sh --dry-run"
