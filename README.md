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

## Requirements

- Python `3.9+`
- Windows only

## Usage

```
python claude_mover.py <source> <target> [--dry-run]
```

| Argument | Description |
|---|---|
| `source` | Current location of the project folder |
| `target` | New location to move it to |
| `--dry-run` | Preview all changes without writing anything |

Always run with `--dry-run` first to verify the plan before committing.

### Path formats

All formats are accepted for both `<source>` and `<target>`:

| Format | Example |
|---|---|
| CMD / PowerShell | `D:\workspace\myapp` |
| Git Bash | `/d/workspace/myapp` |
| Claude dashed | `D--workspace-myapp` |
| UNC (WSL) | `\\wsl.localhost\Ubuntu\home\user\myapp` |
| UNC forward-slash | `//wsl.localhost/Ubuntu/home/user/myapp` |
| Claude dashed (UNC) | `--wsl-localhost-ubuntu-home-user-myapp` ¹ |

¹ Requires `--` separator on the command line to prevent argparse from interpreting it as a flag:
`python claude_mover.py -- --wsl-localhost-ubuntu-... D:\new\location`

### Examples

Move a project to a new location on the same drive:

```
python claude_mover.py D:\workspace\old-name D:\workspace\new-name
```

Preview a move across drives without making changes:

```
python claude_mover.py D:\projects\myapp E:\code\myapp --dry-run
```

Move a project from a Windows drive into WSL:

```
python claude_mover.py D:\workspace\myapp "\\wsl.localhost\Ubuntu\home\user\workspace\myapp"
```

Move a project from WSL to a Windows drive:

```
python claude_mover.py "\\wsl.localhost\Ubuntu\home\user\workspace\myapp" D:\workspace\myapp
```


Use Git Bash path format:

```
python claude_mover.py /d/workspace/myapp /d/clients/myapp
```

## Rollback

If anything goes wrong during migration, Claude Mover automatically restores the original Claude context directory from a backup created at the start. The project folder is only moved after session files are patched, so a failure at any earlier step leaves the source untouched.

## Logs

Each run writes a timestamped log file to `%LOCALAPPDATA%\ClaudeMover\logs\`. The path is printed in the summary at the end of every run.
