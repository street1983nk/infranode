"""FastMCP-Server-Instanz des InfraNode-MCP-Servers (DX-05).

Der Server registriert je Stadtdaten-Ressource ein Tool. Die eigentliche
Tool-Logik liegt als freistehende async-Funktion in ``infranode.mcp.tools``
(Blocker-4-Aufrufvertrag): ``@mcp.tool()`` wird hier nur duenn ueber diese
Funktionen gelegt, sodass sie direkt als Coroutine testbar bleiben und der
Decorator dennoch das FunctionTool fuer die FastMCP-API registriert.

Es gibt KEINE Mapping-/Lizenz-Logik im Server: jedes Tool ruft ueber
``infranode.mcp.client.get_resource`` die Live-FastAPI und gibt deren
normalisiertes JSON 1:1 zurueck (D-07/D-08). Zwei Transporte:
- stdio (Default): lokaler Subprozess fuer Claude Desktop/Code.
- streamable-http: oeffentlicher Remote-Endpunkt (z.B. mcp.infranode.dev),
  hinter Caddy/Cloudflare, keylos wie die API. Per INFRANODE_MCP_TRANSPORT
  =streamable-http aktiviert; INFRANODE_MCP_API_BASE zeigt dann auf die
  oeffentliche API (https://infranode.dev/api/v1).
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from infranode.mcp import tools

mcp = FastMCP("infranode")

# Duenne Registrierung der freistehenden Tool-Funktionen (Blocker 4): der
# Decorator wird programmatisch ueber jede Funktion gelegt. Die Funktion selbst
# bleibt in infranode.mcp.tools unveraendert als Coroutine aufrufbar; FastMCP
# generiert das Schema aus den Typannotationen und Docstrings.
mcp.tool()(tools.get_city)
mcp.tool()(tools.air_quality)
mcp.tool()(tools.air_quality_live)
mcp.tool()(tools.weather)
mcp.tool()(tools.pois)
mcp.tool()(tools.traffic)
mcp.tool()(tools.transit)
mcp.tool()(tools.charging)
mcp.tool()(tools.water_level)
mcp.tool()(tools.flood)
mcp.tool()(tools.pollen_uv)
mcp.tool()(tools.demographics)
mcp.tool()(tools.energy)
mcp.tool()(tools.geo)
mcp.tool()(tools.election)
mcp.tool()(tools.holidays)
mcp.tool()(tools.health)
mcp.tool()(tools.icu_live)
mcp.tool()(tools.road_events)
mcp.tool()(tools.events)
mcp.tool()(tools.webcams)


def run() -> None:
    """Startet den Server im per Env gewaehlten Transport.

    stdio (Default): kein offener Port, lokaler Subprozess. streamable-http:
    bindet einen HTTP-Port (INFRANODE_MCP_HOST/-PORT) fuer den oeffentlichen
    Remote-Endpunkt. Host-Default 127.0.0.1; der Container-Service setzt
    INFRANODE_MCP_HOST=0.0.0.0, damit Caddy ihn ueber das Compose-Netz erreicht.
    """
    transport = os.environ.get("INFRANODE_MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        from mcp.server.transport_security import TransportSecuritySettings

        mcp.settings.host = os.environ.get("INFRANODE_MCP_HOST", "127.0.0.1")
        mcp.settings.port = int(os.environ.get("INFRANODE_MCP_PORT", "8081"))
        # Der MCP-Transport hat einen DNS-Rebinding-Schutz, der per Default nur
        # localhost-Hosts/-Origins erlaubt (gedacht fuer lokal gebundene Server).
        # Hinter Caddy/Cloudflare variieren Host/Origin; fuer eine oeffentliche,
        # keylose read-only API ist der Schutz nicht noetig und blockt sonst alle
        # Calls (HTTP 421). Default daher aus; per
        # INFRANODE_MCP_DNS_REBINDING_PROTECTION=1 mit expliziten Allowlists
        # (INFRANODE_MCP_ALLOWED_HOSTS/-ORIGINS, kommagetrennt) wieder scharf.
        if os.environ.get("INFRANODE_MCP_DNS_REBINDING_PROTECTION") == "1":
            hosts = [
                h.strip()
                for h in os.environ.get("INFRANODE_MCP_ALLOWED_HOSTS", "").split(",")
                if h.strip()
            ]
            origins = [
                o.strip()
                for o in os.environ.get("INFRANODE_MCP_ALLOWED_ORIGINS", "").split(",")
                if o.strip()
            ]
            mcp.settings.transport_security = TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=hosts,
                allowed_origins=origins,
            )
        else:
            mcp.settings.transport_security = TransportSecuritySettings(
                enable_dns_rebinding_protection=False,
            )
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    run()
