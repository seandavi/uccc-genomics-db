# UCCC Genomics MCP (v2) Server

Model Context Protocol (MCP) server providing read-only access to the de-identified UCCC vendor-genomics database (`genomics.duckdb`).

Designed to run as a continuous service on your Tailnet or as a local stdio / SSE tool provider.

## Tools Provided

* **`list_tables(schema: str = "")`**: Lists all available tables and views in `unified`, `caris`, and `fmi` schemas (or filtered by schema).
* **`describe_tables(tables: list[str])`**: Returns column definitions, data types, and nullability for one or more tables (e.g. `['unified.patient', 'unified.variant']`).
* **`query(sql: str, limit: int = 100)`**: Executes read-only SQL queries (`SELECT`, `WITH`, `DESCRIBE`). Enforces safety by rejecting schema modifications and capping row output (max 1,000 rows) to protect context window limits.
* **`get_documentation(topic: str = "overview")`**: Retrieves structured schema documentation and copy-pasteable SQL cohort query examples on demand (`overview`, `unified`, `vendor_schemas`, `examples`, `all`) so large documentation is not dumped into your initial prompt context.

## Running Locally

### Development (SSE transport)
```bash
uv run genomics-mcp --transport sse --host 0.0.0.0 --port 8088
# Endpoint: http://<tailnet-ip>:8088/sse
```

### Development (Streamable HTTP transport)
```bash
uv run genomics-mcp --transport streamable-http --host 0.0.0.0 --port 8088
# Endpoint: http://<tailnet-ip>:8088/mcp
```

### Development (stdio transport)
```bash
uv run genomics-mcp --transport stdio
```

## Running as a Systemd Service (on the Tailnet)

To run the MCP server continuously on your machine accessible over Tailscale:

```bash
# Link user unit and start service
ln -sf /home/davsean/Documents/git/uccc-genomics-db/systemd/genomics-mcp.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now genomics-mcp.service

# Check status and logs
systemctl --user status genomics-mcp.service
journalctl --user -u genomics-mcp.service -f
```

The service binds to port `8088`. On the Tailnet, connect to:
`http://100.74.53.55:8088/sse`

## Client Configuration Examples

### Claude Desktop / Cursor (Remote SSE via Tailnet)
```json
{
  "mcpServers": {
    "uccc-genomics": {
      "url": "http://100.74.53.55:8088/sse"
    }
  }
}
```

### Claude Desktop / Cursor (Local stdio over SSH or local clone)
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
