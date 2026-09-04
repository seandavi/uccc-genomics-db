# UCCC Genomics MCP (v2) Server

Official Model Context Protocol (MCP v2) server providing read-only access to the de-identified UCCC genomics database (`genomics.duckdb`) over **Streamable HTTP** with **Tailscale HTTPS**.

Running live as a continuous systemd user service on `onclappc02` and proxied over Tailscale MagicDNS with valid TLS certificates.

---

## Live Endpoint (Tailnet HTTPS)

* **URL**: `https://onclappc02.tail892754.ts.net:8088/mcp`
* **Transport**: MCP v2 Streamable HTTP (POST / streaming responses with `Mcp-Session-Id`)

---

## Tools Provided

* **`list_tables(schema: str = "")`**: Lists all available tables and views across schemas (`unified`, `caris`, `fmi`).
* **`describe_tables(tables: list[str])`**: Returns column definitions, data types, and nullability for one or more tables (e.g. `['unified.patient', 'unified.variant']`).
* **`query(sql: str, limit: int = 100)`**: Executes read-only SQL queries (`SELECT`, `WITH`, `DESCRIBE`). Enforces safety by rejecting schema modifications and capping row output (max 1,000 rows) to protect LLM context windows.
* **`get_documentation(topic: str = "overview")`**: **Context-protection tool**. Retrieves structured schema documentation and copy-pasteable SQL cohort queries on demand (`overview`, `unified`, `vendor_schemas`, `examples`, `all`) so large documentation is not dumped into your initial prompt context.

---

## Tailnet HTTPS Architecture

```
Client (Claude / Cursor / Pi)
         │
         │  HTTPS (MagicDNS TLS)
         ▼
[tailscale serve :8088] (terminates TLS at onclappc02.tail892754.ts.net:8088)
         │
         │  HTTP (localhost)
         ▼
[genomics-mcp.service] (uv run genomics-mcp --transport streamable-http --host 127.0.0.1 --port 8089)
         │
         ▼
[genomics.duckdb] (AES-256-GCM encrypted, read-only)
```

1. **Backend Service (`genomics-mcp.service`)**:
   Runs on `127.0.0.1:8089` under systemd `--user`.
2. **Tailscale Proxy (`tailscale serve`)**:
   Exposes port `8088` with valid MagicDNS HTTPS and proxies to `127.0.0.1:8089`:
   ```bash
   tailscale serve --https=8088 --bg --yes 8089
   ```

---

## Client Configuration Examples

### Claude Desktop / Cursor / Pi (Over the Tailnet)
```json
{
  "mcpServers": {
    "uccc-genomics": {
      "url": "https://onclappc02.tail892754.ts.net:8088/mcp"
    }
  }
}
```

### Local Stdio (Alternative for local scripts)
```json
{
  "mcpServers": {
    "uccc-genomics": {
      "command": "/home/davsean/.local/bin/uv",
      "args": [
        "run",
        "--directory",
        "/home/davsean/Documents/git/uccc-genomics-db",
        "genomics-mcp",
        "--transport",
        "stdio"
      ]
    }
  }
}
```

---

## Service Management

```bash
# View service status
systemctl --user status genomics-mcp.service

# View streaming logs
journalctl --user -u genomics-mcp.service -f

# Tailscale serve status
tailscale serve status
```

---

## Status & Open Testing Items

* **Local Verification**: Passed on host (`onclappc02`). Systemd unit runs stably, DuckDB connects read-only with decryption key, and tools respond correctly.
* **Tailnet Remote Testing (In Progress / Needs Further Testing)**:
  * Remote access from secondary client devices on the tailnet reported unresponsive.
  * **Items to verify**:
    1. Tailscale ACLs / peer connectivity between client device and `onclappc02`.
    2. MagicDNS resolution of `onclappc02.tail892754.ts.net` from client environments.
    3. Client MCP transport compatibility (whether client expects Streamable HTTP on `/mcp` vs legacy SSE on `/sse` vs direct stdio bridge).

