# Claude Code hook

Stops prompts, and `Write`/`Edit`/`Bash` tool inputs, that contain Indian PII. It prints only types and counts.

```bash
pip install saaf
```

Add to `.claude/settings.json` (project) or `~/.claude/settings.json` (user):

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [{ "type": "command", "command": "python /path/to/saaf_hook.py prompt" }] }
    ],
    "PreToolUse": [
      { "matcher": "Write|Edit|Bash",
        "hooks": [{ "type": "command", "command": "python /path/to/saaf_hook.py tool" }] }
    ]
  }
}
```

`SAAF_HOOK_MODE=block` (default, exit code 2), `warn`, or `off`.
