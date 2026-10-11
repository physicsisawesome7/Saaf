# saaf-mcp

An MCP server exposing `saaf_scan`, `saaf_mask`, `saaf_restore` and `saaf_entities`.

```bash
pip install saaf-mcp
claude mcp add saaf -- saaf-mcp
```

Claude Desktop (`claude_desktop_config.json`):
```json
{ "mcpServers": { "saaf": { "command": "saaf-mcp" } } }
```

`saaf_scan` never returns values. Mask/restore sessions live in memory (up to 256 named sessions).
