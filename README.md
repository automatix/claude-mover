# Claude Mover

A tool that safely moves Claude Code project folders while keeping their session history intact.

## What it does — and what it does not

Claude Code stores session history under `~/.claude/projects/`, using the **absolute path** of the project folder as the directory name (with slashes encoded as dashes). When you move a project folder naively — via Explorer, `mv`, or any other tool — Claude Code can no longer find the sessions, because the path-based key no longer matches.

**Claude Mover fixes this** by performing the move in the correct order:

1. **Rename** the context directory in `~/.claude/projects/` to the new encoded path
2. **Rewrite** all path strings inside the `.jsonl` session files
3. **Move** the project folder itself
4. **Patch** absolute paths in `.claude/settings.json` and `.mcp.json` inside the project
5. **Update** path entries in `~/.claude/history.jsonl` and `~/.claude.json`
6. **Patch** `cwd`/`originCwd` in the Claude **desktop app** session store (separate from `~/.claude/` — this is what drives the app's trust dialog, "Show in Explorer", and "Copy path")

**What it does NOT do:** The session history files themselves stay where they are — inside `%USERPROFILE%\.claude\projects\` on Windows. Claude Mover only **renames** that directory and rewrites the path strings inside it. No conversation data is moved to a different store, even when the project is moved to WSL. (The Claude desktop app additionally keeps a small per-session `cwd` pointer in its own store; Claude Mover patches that pointer too — see step `6` above.)

## Requirements

- Python `3.9+`
- Windows only

## Before you run

**Close every Claude instance first** — the desktop app (including its tray icon) and any running Claude Code CLI or IDE-extension sessions. This is a correctness requirement, not just a precaution, for two independent reasons:

1. **File handles (Windows):** an open session for the source project holds handles on its context directory or the project folder, which can make the folder move fail.
2. **In-memory overwrite:** the Claude desktop app keeps `~/.claude.json` **and** its own session store (`claude-code-sessions\*.json`) in memory and rewrites them on its next save. If it is running during the move, it reverts the path patches from steps `5`–`6`, so the app keeps showing the **old** path even though the move otherwise succeeded.

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

You can give the target with either WSL alias (`\\wsl$\Ubuntu\…` or `\\wsl.localhost\ubuntu\…`) — they point to the same location. Claude Mover automatically normalizes WSL targets to the form the Claude desktop app uses itself (`\\wsl.localhost\<distro-lowercased>\…`), so the session history always lands under the key the app reads. It logs a notice when it rewrites the form. The `\\wsl.localhost` form contains no `$`, so it needs no quoting in any shell.

> **How the folder is copied to/from WSL.** For moves that touch WSL, Claude Mover copies the folder **natively inside the distro** (`wsl.exe … cp -a`) rather than across the `\\wsl$\` network redirector. The redirector silently drops files under load and cannot reproduce Linux symlinks, which could corrupt or lose data on a large project (e.g. one with a `.git` or `node_modules` folder). The native copy preserves symlinks and permissions, and the move is **verified** before the original is removed (see below).

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

Claude Code CLI, the VS Code and JetBrains extensions, and the Claude desktop app all share the same `~/.claude/projects/` store for session history. The Claude desktop app additionally keeps its own per-session `cwd`/`originCwd` pointers in a separate store (`%LOCALAPPDATA%\Packages\Claude_*\...\claude-code-sessions\`), which is what its trust dialog, "Show in Explorer", and "Copy path" rely on. Claude Mover patches that store too, so a move is transparent to all of them. **Note:** the desktop app must be fully closed when you run the move, otherwise it rewrites these pointers from memory and reverts the change.

It has no effect on **Claude.ai** (the web app) — web conversations are stored server-side and are unrelated to the local project store.

### Must Claude be closed before running the script?

Yes — completely, and for correctness, not just to avoid file-lock errors. Two things break if any Claude instance is running:

- A Claude Code session for the source project may hold file handles on the folder being moved, so the move can fail on Windows.
- The desktop app holds `~/.claude.json` and its per-session store in memory and rewrites them on save, **reverting** the path patches — so the app keeps displaying the old path even after an otherwise successful run.

Close the desktop app (including the tray icon) and exit all Claude Code CLI and IDE-extension sessions before running the script. (The bundled repair scripts enforce this with a process guard; the mover itself relies on you having closed everything.)

---

## Copy verification (no silent data loss)

The folder move always **copies first, verifies, and only then deletes the original**. After copying, Claude Mover builds a manifest of both trees — every file, directory, and symlink, with file sizes — and confirms that every source entry is present in the target. If anything is missing or mismatched, it aborts and **leaves the source untouched** rather than deleting an incomplete copy. Once the copy is verified, a source file that is still locked (e.g. open in an editor) is reported as a warning and left in place, never at the cost of the verified target.

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

## Tests

Run the test suite with:

```bash
python -m pytest test_claude_mover.py
```

To measure code coverage (requires `pytest-cov`):

```bash
pip install pytest-cov
python -m pytest test_claude_mover.py --cov=claude_mover --cov-report=term-missing
```

The test suite contains `195` tests across `39` test classes with `93%` line coverage.

## Logs

Each run writes a timestamped log file to `%LOCALAPPDATA%\ClaudeMover\logs\`. The path is printed in the summary at the end of every run.
