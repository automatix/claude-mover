# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project purpose

**Claude Mover** is a tool that safely relocates Claude Code project folders.
When a project folder is moved naively (e.g. via Explorer/Finder), its session history stored under `~/.claude/projects/` becomes orphaned because Claude Code uses the **absolute path** of the project folder as the storage key (slashes encoded as dashes).

The correct migration order is:
1. Rename the encoded directory in `~/.claude/projects/` to match the new path.
2. Rewrite path references inside the `.jsonl` session files.
3. Move/rename the actual project folder.
4. Update any absolute paths in `.claude/settings.json` and `.mcp.json`.
5. Update path entries in `~/.claude/history.jsonl`.

## Domain knowledge

- `~/.claude/projects/<encoded-path>/` — one directory per project; contains `.jsonl` session files.
- Path encoding: every `/` (or `\` on Windows) in the absolute path is replaced by `-`. E.g. `D:\workspace\myapp` → `D--workspace-myapp`.
- `~/.claude/history.jsonl` — global history index; contains absolute path references that must be rewritten on move.
- `.claude/` folder and `CLAUDE.md` inside the project folder travel with the folder automatically — no special handling needed.
- `.mcp.json` may contain absolute paths and must be patched if present.
