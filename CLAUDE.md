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

## Requirements

- Python `3.9+` (uses PEP 585 built-in generic types, e.g. `list[str]`)
- Windows only — relies on `LOCALAPPDATA`, drive-letter path encoding, and `shutil.move` Windows semantics

## Commands

```bash
# Run the tool (normal)
python claude_mover.py <source> <target>

# Preview what would happen without making changes
python claude_mover.py <source> <target> --dry-run
```

All three path formats are accepted for `<source>` and `<target>`:
- CMD style: `D:\workspace\myapp`
- Git Bash style: `/d/workspace/myapp`
- Claude dashed: `D--workspace-myapp`

Logs are written to `%LOCALAPPDATA%\ClaudeMover\logs\` alongside stdout.

## Architecture

The entire tool is a single self-contained script: [`claude_mover.py`](claude_mover.py). There are no external dependencies beyond the Python standard library.

The file is organized into clearly delimited sections:

| Section | Responsibility |
|---|---|
| **Logging** | File + stdout logging setup; dry-run prefix |
| **Path utilities** | `encode_path` (absolute path → dashed key), `normalize_path` (accepts all three input formats), `_decode_dashed_naive` |
| **Path variant helpers** | `_path_variants` returns the `5` string representations of a path that may appear in files; `patch_content` replaces all of them in a string |
| **Validation** | `validate_source` / `validate_target` — existence checks with actionable error messages |
| **Parent directory** | `ensure_parent` — interactive prompt when the target parent is missing |
| **Backup** | `backup_context` / `restore_backup` / `remove_backup` — safety net around the context rename |
| **Patching** | `patch_file` (generic), `patch_jsonl` (line-by-line for `.jsonl` files) |
| **Migration** | `migrate` — orchestrates the five steps and rolls back on failure |
| **Summary** | `print_summary` — final report |
| **Entry point** | `main` — argument parsing, calls `migrate`, surfaces errors |

### Key design points

- `_path_variants` emits `5` representations for each path (`D:\p`, `D:/p`, `/d/p`, `/D/p`, `D--p`) so that `patch_content` replaces every form that could appear in JSON or JSONL files regardless of how the path was serialized.
- The Claude context directory is renamed **before** session files are patched; if patching targets the renamed directory, `dry_run` mode reads from the original to avoid mutating state.
- Backup is created before any write and removed only on full success. On any exception, `restore_backup` puts the context directory back so the source project remains intact.

## Domain knowledge

- `~/.claude/projects/<encoded-path>/` — one directory per project; contains `.jsonl` session files.
- Path encoding: drive colon + backslash → `--`, remaining backslashes → `-`. E.g. `D:\workspace\myapp` → `D--workspace-myapp`.
- `~/.claude/history.jsonl` — global history index; contains absolute path references that must be rewritten on move.
- `.claude/` folder and `CLAUDE.md` inside the project folder travel with the folder automatically — no special handling needed.
- `.mcp.json` may contain absolute paths and must be patched if present.

## Tests

There is no test suite. The tool is tested manually via `--dry-run` against real Claude project directories.

## Deferred features

- **Merge mode:** combine Claude session histories from two related project paths into one target directory.
- **pip package:** distribute as an installable Python package (`pip install claude-mover`).
