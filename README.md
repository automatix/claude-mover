# Claude Mover

A tool that safely moves Claude Code project folders while keeping their session history intact.

## What it does — and what it does not

Claude Code stores session history under `~/.claude/projects/`, using the **absolute path** of the project folder as the directory name (with slashes encoded as dashes). When you move a project folder naively — via Explorer, `mv`, or any other tool — Claude Code can no longer find the sessions, because the path-based key no longer matches.

**Claude Mover fixes this** by performing the move in the correct order:

1. **Rename** the context directory in `~/.claude/projects/` to the new encoded path
2. **Rewrite** all path strings inside the `.jsonl` session files
3. **Move** the project folder itself
4. **Patch** absolute paths in `.claude/settings.json` and `.mcp.json` inside the project
5. **Update** path entries in `~/.claude/history.jsonl`

**What it does NOT do:** The session files themselves stay where they are — inside `%USERPROFILE%\.claude\projects\` on Windows. Claude Mover only **renames** that directory and rewrites the path strings inside it. No session data is moved to a different store, even when the project is moved to WSL.

## Requirements

- Python `3.9+`
- Windows only

## Before you run

Close any active Claude Code session for the project you want to move, and close the Claude desktop app if it is running. On Windows, open file handles can prevent the folder move from completing.

## Usage

```
python claude_mover.py <source> <target> [--dry-run] [--resume]
```

| Argument | Description |
|---|---|
| `source` | Current location of the project folder |
| `target` | New location to move it to |
| `--dry-run` | Preview all changes without writing anything |
| `--resume` | Clean up leftovers from a previous failed migration, then retry |

Always run with `--dry-run` first to verify the plan before committing.

### Supported path formats

All formats are accepted for both `<source>` and `<target>`:

| Format | Example |
|---|---|
| CMD / PowerShell | `D:\workspace\myapp` |
| Git Bash | `/d/workspace/myapp` |
| Claude dashed | `D--workspace-myapp` |
| UNC (WSL) | `\\wsl.localhost\Ubuntu\home\user\myapp` |
| UNC forward-slash | `//wsl.localhost/Ubuntu/home/user/myapp` |
| Claude dashed (UNC) | `--wsl-localhost-ubuntu-home-user-myapp` ¹ |

¹ Requires `--` separator on the command line to prevent the argument parser from treating it as a flag:
`python claude_mover.py -- --wsl-localhost-ubuntu-... D:\new\location`

---

## Examples

### Rename a project on the same drive

**CMD & PowerShell**
```cmd
python claude_mover.py D:\workspace\old-name D:\workspace\new-name
```

**Git Bash**
```bash
python claude_mover.py /d/workspace/old-name /d/workspace/new-name
```

---

### Move a project across drives

**CMD & PowerShell**
```cmd
python claude_mover.py D:\projects\myapp E:\code\myapp
```

**Git Bash**
```bash
python claude_mover.py /d/projects/myapp /e/code/myapp
```

---

### Move a project from Windows to WSL

Target path contains `$`, which PowerShell and Git Bash treat as the start of a variable — **use single quotes**.

**CMD** (no quoting needed for `$`)
```cmd
python claude_mover.py D:\workspace\tools\SleepNote \\wsl$\Ubuntu\home\automatix\workspace\SleepNote
```

**PowerShell** (single quotes prevent `$` from being interpreted as a variable)
```powershell
python claude_mover.py D:\workspace\tools\SleepNote '\\wsl$\Ubuntu\home\automatix\workspace\SleepNote'
```

**Git Bash** (single quotes for the same reason)
```bash
python claude_mover.py /d/workspace/tools/SleepNote '//wsl$/Ubuntu/home/automatix/workspace/SleepNote'
```

With `--dry-run` first (recommended):

**PowerShell**
```powershell
python claude_mover.py D:\workspace\tools\SleepNote '\\wsl$\Ubuntu\home\automatix\workspace\SleepNote' --dry-run
```

If your system uses `wsl.localhost` instead of `wsl$` (check your `~/.claude/projects/` for the prefix), replace accordingly — `wsl.localhost` contains no `$`, so quoting is not required in any shell.

---

### Move a project from WSL back to Windows

**PowerShell**
```powershell
python claude_mover.py '\\wsl$\Ubuntu\home\automatix\workspace\SleepNote' D:\workspace\tools\SleepNote
```

**Git Bash**
```bash
python claude_mover.py '//wsl$/Ubuntu/home/automatix/workspace/SleepNote' /d/workspace/tools/SleepNote
```

---

## Notes

### Do sessions and project settings remain valid after the move?

Yes, fully. Claude Code will find all previous sessions at the new path exactly as before. The session content is not modified — only the path strings inside it are updated. Project settings (`.claude/settings.json`, `.mcp.json`) are patched in place.

### Does this work with the Claude desktop app and IDE extensions?

Claude Code CLI, the VS Code and JetBrains extensions, and the Claude desktop app all share the same `~/.claude/projects/` store. A move performed with Claude Mover is transparent to all of them.

It has no effect on **Claude.ai** (the web app) — web conversations are stored server-side and are unrelated to the local project store.

### Must Claude be closed before running the script?

Yes, as a precaution. If a Claude Code session for the source project is open, it may hold file handles on the context directory or the project folder, which can cause the move to fail on Windows. Close any active sessions and the Claude desktop app before running the script.

---

## Rollback

If anything goes wrong during migration, Claude Mover automatically:

1. Restores the original Claude context directory from the backup created at the start
2. Removes the stale target context directory (if it was already renamed)
3. Removes any partial project copy at the target location

The source folder and its session history are left exactly as they were before the run.

## Recovering from an interrupted migration

If the process is killed mid-run (e.g. power loss, `Ctrl+C`, or a hard error), the automatic rollback may not complete. In that case, use `--resume`:

```powershell
python claude_mover.py <source> <target> --resume
```

`--resume` inspects the target path and the Claude projects directory, removes any leftover artifacts from the previous attempt (stale target context, partial project copy), and then runs the full migration from scratch.

A checkpoint file is written to `%LOCALAPPDATA%\ClaudeMover\checkpoints\` at the start of every migration. It records the source, target, backup path, and — on failure — the error message. The file is deleted on success.

## Logs

Each run writes a timestamped log file to `%LOCALAPPDATA%\ClaudeMover\logs\`. The path is printed in the summary at the end of every run.
