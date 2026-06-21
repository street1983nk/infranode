#!/usr/bin/env bash
# deploy/harden_firewall.sh - CF-only-Origin-Firewall fuer InfraNode (Security-Audit HIGH-2)
#
# Beschraenkt die Origin-Ports 80/443 auf die offiziellen Cloudflare-IP-Ranges.
# Ohne diese Beschraenkung kann jeder, der die Origin-IP kennt, Cloudflare
# umgehen UND mit gefaelschten CF-Connecting-IP-Headern das gesamte Rate-Limiting
# aushebeln (jeder Request ein frischer Bucket). Diese Datei giesst die im
# Runbook (docs/DEPLOYMENT.md, Abschnitt 2) dokumentierten Schritte in ein
# idempotentes Skript mit Verify- und Refresh-Modus.
#
# AUF DER BOX als root ausfuehren (nicht lokal). SSH (22) bleibt offen.
#
# Modi:
#   sudo bash harden_firewall.sh            # voller Setup (ufw + CF-only 80/443)
#   sudo bash harden_firewall.sh --refresh  # nur CF-Ranges neu setzen (fuer Cron)
#   sudo bash harden_firewall.sh --check     # nur pruefen, exit 1 bei Befund

set -euo pipefail

MODE="apply"
case "${1:-}" in
  --refresh) MODE="refresh" ;;
  --check)   MODE="check" ;;
  "")        MODE="apply" ;;
  *) echo "Unbekannter Modus: $1 (erlaubt: --refresh, --check)"; exit 2 ;;
esac

V4_URL="https://www.cloudflare.com/ips-v4"
V6_URL="https://www.cloudflare.com/ips-v6"

fetch_ranges() {
  # Gibt alle CF-Ranges (v4 + v6) zeilenweise aus; bricht ab, wenn leer.
  local v4 v6
  v4="$(curl -fsS "$V4_URL")" || { echo "Konnte $V4_URL nicht laden" >&2; exit 1; }
  v6="$(curl -fsS "$V6_URL")" || { echo "Konnte $V6_URL nicht laden" >&2; exit 1; }
  printf '%s\n%s\n' "$v4" "$v6" | grep -E '[0-9a-fA-F:.]+/[0-9]+' || {
    echo "Keine CF-Ranges erhalten (leere Antwort)" >&2; exit 1;
  }
}

require_root() {
  [[ "$(id -u)" == "0" ]] || { echo "Bitte als root ausfuehren (sudo)." >&2; exit 1; }
}

# --- CHECK: nur verifizieren -----------------------------------------------------
if [[ "$MODE" == "check" ]]; then
  fail=0
  if ! command -v ufw >/dev/null; then echo "FAIL: ufw nicht installiert"; exit 1; fi
  status="$(ufw status 2>/dev/null || true)"
  # Generische (quell-lose) 80/443-Regeln duerfen NICHT existieren.
  if echo "$status" | grep -E '^(80|443)(/tcp)?[[:space:]]+ALLOW[[:space:]]+Anywhere' >/dev/null; then
    echo "FAIL: generische ALLOW-Regel fuer 80/443 von Anywhere vorhanden (CF-Bypass moeglich)"
    fail=1
  fi
  # Mindestens eine quellbeschraenkte 80/443-Regel sollte existieren.
  if ! echo "$status" | grep -E 'ALLOW' | grep -E '80|443' | grep -vq 'Anywhere'; then
    echo "FAIL: keine quellbeschraenkte 80/443-Regel gefunden (CF-Ranges fehlen?)"
    fail=1
  fi
  if [[ "$fail" == "0" ]]; then echo "OK: 80/443 nur quellbeschraenkt (CF-only)."; fi
  exit "$fail"
fi

require_root

# --- APPLY: Grundgeruest (nur im vollen Setup) ----------------------------------
if [[ "$MODE" == "apply" ]]; then
  if ! command -v ufw >/dev/null; then
    echo "-> Installiere ufw ..."
    apt-get update && apt-get install -y ufw
  fi
  echo "-> Setze Default-Policies + SSH ..."
  ufw default deny incoming
  ufw default allow outgoing
  ufw allow 22/tcp
fi

# --- APPLY + REFRESH: CF-Ranges fuer 80/443 zulassen ----------------------------
echo "-> Lade aktuelle Cloudflare-IP-Ranges ..."
mapfile -t RANGES < <(fetch_ranges)
echo "   ${#RANGES[@]} Ranges erhalten."

echo "-> Erlaube 80/443 nur von Cloudflare ..."
for r in "${RANGES[@]}"; do
  # ufw dedupliziert bestehende Regeln selbst (idempotent).
  ufw allow from "$r" to any port 80,443 proto tcp >/dev/null
done

# Generische (quell-lose) 80/443-Regeln entfernen, falls vorhanden (best effort).
echo "-> Entferne generische 80/443-Regeln (falls vorhanden) ..."
ufw delete allow 80/tcp 2>/dev/null || true
ufw delete allow 443/tcp 2>/dev/null || true
ufw delete allow 80,443/tcp 2>/dev/null || true

if [[ "$MODE" == "apply" ]]; then
  echo "-> Aktiviere ufw ..."
  ufw --force enable
fi

echo
echo "Aktueller ufw-Status:"
ufw status verbose | sed 's/^/   /'

echo
echo "Fertig ($MODE)."
echo " - Die CF-Ranges aendern sich selten. Monatlichen Re-Check als Cron einrichten:"
echo "     echo '0 4 1 * * root $(readlink -f "$0") --refresh >> /var/log/cf-firewall.log 2>&1' > /etc/cron.d/infranode-cf-firewall"
echo " - Verifizieren: sudo bash $(basename "$0") --check"
echo " - Langfristig ideal: Cloudflare Tunnel, dann ist die Origin-IP gar nicht exponiert."
