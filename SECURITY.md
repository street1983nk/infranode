# Security Policy

## Reporting a vulnerability

Please report security issues privately. Do **not** open a public issue for
security problems.

- Preferred: use GitHub's private vulnerability reporting on this repository
  (the **Security** tab -> **Report a vulnerability**). This opens a private
  advisory visible only to the maintainers.

We aim to acknowledge a report within a few days and will keep you informed
about the fix and disclosure timeline.

## Supported versions

InfraNode is operated as a single, continuously deployed service. Only the
latest released version (currently `1.x`) and the live hosted endpoint receive
security fixes.

## Security model

InfraNode is intentionally small in attack surface:

- **Read-only.** Every MCP tool and every API route is a `GET`-style read.
  There are no write, delete, or mutating operations. All MCP tools are
  annotated `readOnlyHint: true`, `destructiveHint: false`,
  `idempotentHint: true`.
- **Keyless.** The public API and the hosted MCP server
  (`https://mcp.infranode.dev/mcp`, streamable HTTP) require no API key and
  store no per-user credentials. There is no user account system and no secret
  to leak on the client side.
- **No personal data.** InfraNode proxies and normalizes public open data
  from German official sources (e.g. DWD, Umweltbundesamt, Mobilithek,
  GovData). It does not process end-user personal data and sets no cookies.
- **SSRF protection.** The MCP client resolves only to the configured InfraNode
  API base; outbound request targets are validated before each request, so a
  tool argument cannot redirect a request to an arbitrary host.
- **Injection protection.** Tool inputs (city slugs, resource names, filters)
  are validated against fixed allowlists / typed parameters before they reach
  the upstream API. There is no shell, template, or SQL evaluation of user
  input on the proxy path.

## Scope

In scope: the source in this repository and the hosted endpoints
`https://infranode.dev` (API) and `https://mcp.infranode.dev` (MCP).

Out of scope: vulnerabilities in upstream third-party data providers, and
denial-of-service via request volume (the service is rate limited).
