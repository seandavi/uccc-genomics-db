# UCCC Genomics MCP (v2) Server

Official Model Context Protocol (MCP v2) server using **Streamable HTTP** transport to provide read-only access to the de-identified UCCC genomics database (`genomics.duckdb`).

Designed to run as a continuous service on your Tailnet or as a local tool provider.

## Tools Provided

* **`list_tables(schema: str = "")`**: Lists all available tables and views across schemas (`unified`, `caris`, `fmi`).
* **`describe_tables(tables: list[str])`**: Returns column definitions, data types, and nullability for one or more tables (e.g. `['unified.patient', 'unified.variant']`).
* **`query(sql: str, limit: int = 100)`**: Executes read-only SQL queries (`SELECT`, `WITH`, `DESCRIBE`). Enforces safety by rejecting schema modifications and capping row output (max 1,000 rows) to protect LLM context windows.
* **`get_documentation(topic: str = "overview")`**: **Context-protection tool**. Retrieves structured schema documentation and copy-pasteable SQL cohort queries on demand (`overview`, `unified`, `vendor_schemas`, `examples`, `all`) so large documentation is not dumped into your initial prompt context.

---

## Running on the Tailnet (Streamable HTTP)

### Direct CLI
```bash
# Starts MCP v2 Streamable HTTP server on port 8088
uv run genomics-mcp --transport streamable-http --host 0.0.0.0 --port 8088

# Endpoint on Tailnet: http://100.74.53.55:8088/mcp
```

### Continuous Background Service (Systemd User Service)
A preconfigured service unit is provided in `systemd/genomics-mcp.service`:

```bash
# Install and start user service
ln -sf /home/davsean/Documents/git/uccc-genomics-db/systemd/genomics-mcp.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now genomics-mcp.service

# Verify service is active
systemctl --user status genomics-mcp.service
journalctl --user -u genomics-mcp.service -f
```

---

## Client Configuration (MCP v2 Streamable HTTP)

Connect your MCP client (Claude Desktop, Cursor, Pi, LibreChat, etc.) to the Tailnet Streamable HTTP endpoint:

```json
{
  "mcpServers": {
    "uccc-genomics": {
      "url": "http://100.74.53.55:8088/mcp"
    }
  }
}
```

Or for local stdio:
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
