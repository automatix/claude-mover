# Claude Mover

A tool that safely relocates Claude Code project folders while preserving their session history.

## Problem

Claude Code stores session data under `~/.claude/projects/` using the **absolute path** of the project folder as the storage key. Moving a project folder naively (e.g. via Explorer/Finder) orphans all session history.

## Solution

Claude Mover handles the migration in the correct order:

1. Rename the encoded directory in `~/.claude/projects/`
2. Rewrite path references inside the `.jsonl` session files
3. Move the actual project folder
4. Update absolute paths in `.claude/settings.json` and `.mcp.json`
5. Update path entries in `~/.claude/history.jsonl`
