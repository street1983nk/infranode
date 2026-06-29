"""InfraNode MCP-Server-Paket (DX-05).

Ein dünner Wrapper, der die bestehende Live-FastAPI als MCP-Tools exponiert.
Die eigentliche Mapping-/Lizenz-Logik bleibt ausschließlich in der API; dieses
Paket ruft sie nur über httpx loopback auf und gibt das normalisierte JSON 1:1
zurück. Liegt bewusst in einer eigenen Dependency-Gruppe (mcp), damit das
Live-Docker-Image schlank bleibt (T-12-MCP-IMG).
"""
