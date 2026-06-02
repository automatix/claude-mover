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
6. Update `~/.claude.json` (global app config — project list and GitHub repo map; this is what the Claude desktop app reads to display the "open project" path).
7. Update `cwd`/`originCwd` in the Claude **desktop app** session store (`%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\claude-code-sessions\**\local_*.json`). This store is separate from `~/.claude/` and is what drives the app's trust dialog, "Show in Explorer", and "Copy path".

## Requirements

- Python `3.9+` (uses PEP 585 built-in generic types, e.g. `list[str]`)
- Windows only — relies on `LOCALAPPDATA`, drive-letter path encoding, and `shutil.move` Windows semantics

## Workflow

After every PR is merged: merge it via `gh pr merge --squash --delete-branch` (or `--merge` if squash is not appropriate), then switch the local working copy back to `master` and pull.

## Commands

```bash
# Run the tool (normal)
python claude_mover.py <source> <target>

# Preview what would happen without making changes
python claude_mover.py <source> <target> --dry-run

# Clean up leftover artifacts from a failed migration, then retry
python claude_mover.py <source> <target> --resume
```

All path formats are accepted for `<source>` and `<target>`:
- CMD style: `D:\workspace\myapp`
- Git Bash style: `/d/workspace/myapp`
- Claude dashed: `D--workspace-myapp`
- UNC (WSL): `\\wsl.localhost\Ubuntu\home\user\myapp`
- UNC forward-slash: `//wsl.localhost/Ubuntu/home/user/myapp`
- Claude dashed (UNC): `--wsl-localhost-ubuntu-home-user-myapp` (requires `--` separator on CLI)

Logs are written to `%LOCALAPPDATA%\ClaudeMover\logs\` alongside stdout.

## Architecture

The entire tool is a single self-contained script: [`claude_mover.py`](claude_mover.py). There are no external dependencies beyond the Python standard library.

The file is organized into clearly delimited sections:

| Section | Responsibility |
|---|---|
| **Logging** | File + stdout logging setup; dry-run prefix |
| **Path utilities** | `encode_path` (absolute path → dashed key), `normalize_path` (accepts all path formats), `_decode_dashed_naive`, `_decode_dashed_unc_naive`, `_UNC_DASHED_SERVERS` |
| **Path variant helpers** | `_path_variants` returns the `5` string representations of a path that may appear in files; `patch_content` replaces all of them in a string |
| **Validation** | `validate_source` / `validate_target` — existence checks with actionable error messages |
| **Parent directory** | `ensure_parent` — interactive prompt when the target parent is missing |
| **Backup** | `backup_context` / `restore_backup` / `remove_backup` — safety net around the context rename |
| **Patching** | `patch_file` (generic), `patch_jsonl` (line-by-line for `.jsonl` files), `app_session_files` (locate the desktop app session store) |
| **Directory move** | `_move_directory` — robocopy-based move for long-path safety; `_rmtree_robust` — robocopy /MIR fallback for deletion |
| **Checkpoint** | `_write_checkpoint` / `_read_checkpoint` / `_clear_checkpoint` — persist migration state to `%LOCALAPPDATA%\ClaudeMover\checkpoints\` |
| **Migration** | `migrate` — orchestrates the seven steps and rolls back on failure |
| **Summary** | `print_summary` — final report |
| **Entry point** | `main` — argument parsing, calls `migrate`, surfaces errors |

### Key design points

- On any failure, the rollback now cleans up all three artefacts: restores the source context from backup, deletes the stale target context, and removes any partial project copy at the target location using `_rmtree_robust`.
- A checkpoint file (`%LOCALAPPDATA%\ClaudeMover\checkpoints\<source-encoded>.json`) is written after the backup step and updated with the error message on failure. It is deleted on success. Running with `--resume` reads this checkpoint, cleans up stale artefacts, and restarts the migration cleanly.
- `_path_variants` emits `6` representations for each path so that `patch_content` replaces every form that could appear in JSON or JSONL files:
  - Drive-letter paths: `D:\p`, `D:/p`, `/d/p`, `/D/p`, `D--p`, `D:\\p` (JSON-encoded)
  - UNC paths: `\\server\share\p`, `//server/share/p` (×3, no Git Bash equivalent), `--server-share-p`, `\\\\server\\share\\p` (JSON-encoded)
  - The JSON-encoded 6th variant is what `history.jsonl` uses for its `"project"` field (each backslash doubled).
- The Claude context directory is renamed **before** session files are patched; if patching targets the renamed directory, `dry_run` mode reads from the original to avoid mutating state.
- Backup is created before any write and removed only on full success. On any exception, `restore_backup` puts the context directory back so the source project remains intact.

### Path encoding (drive-letter and UNC / WSL)

Claude Code derives the per-project directory name from the working directory
with a **single universal rule**, verified empirically against the directories
the real CLI creates: **every character that is not an ASCII letter or digit is
replaced by `-`, and the case is preserved.** There is no lowercasing and no
special-casing of the UNC server, share, or the `$` in `\\wsl$\`.

| Input character | Encoded as |
|---|---|
| ASCII letter / digit | unchanged (case preserved) |
| Backslash `\`, forward slash `/`, colon `:`, dot `.`, space, `$`, any other punctuation | `-` |

Each character maps to exactly one dash — consecutive separators are **not**
collapsed (e.g. the leading `\\` becomes `--`, and `$\` becomes `--`).

Examples:

| Path | Encoded directory key |
|---|---|
| `D:\workspace\myapp` | `D--workspace-myapp` |
| `D:\workspace\tools\Claude Mover` | `D--workspace-tools-Claude-Mover` |
| `\\wsl.localhost\ubuntu\home\automatix\workspace\FooBarWSL` | `--wsl-localhost-ubuntu-home-automatix-workspace-FooBarWSL` |
| `\\wsl$\Ubuntu\home\automatix\workspace\SleepNote` | `--wsl--Ubuntu-home-automatix-workspace-SleepNote` |

> A Windows→WSL move is **not** a cross-store migration: there is no `claude`
> CLI inside the WSL distro, so the desktop app runs the CLI on the Windows side
> with the UNC `cwd`, and sessions stay in the Windows `%USERPROFILE%\.claude\`
> store. Only the directory **key** changes — which is exactly why getting the
> encoding right matters. (See issue `#21`.)


## Domain knowledge

- `~/.claude/projects/<encoded-path>/` — one directory per project; contains `.jsonl` session files.
- Path encoding: every non-alphanumeric character → `-`, case preserved (see the [Path encoding](#path-encoding-drive-letter-and-unc--wsl) section). E.g. `D:\workspace\myapp` → `D--workspace-myapp`.
- `~/.claude/history.jsonl` — global history index; contains absolute path references that must be rewritten on move.
- `~/.claude.json` (in the **home directory**, NOT inside `~/.claude/`) — global app config read by the Claude desktop app; stores project settings keyed by path (both backslash and forward-slash forms) and the GitHub repo → local path map. The `backups/` folder inside `~/.claude/` contains timestamped backups of this file made before each write.
- `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\claude-code-sessions\<account>\<group>\local_<id>.json` — the Claude **desktop app** (MSIX) per-session store, **separate from `~/.claude/`**. Each file holds `cwd` and `originCwd`. These are what actually drive the app's "Trust this workspace?" dialog, "Show in Explorer", and "Copy path" (see `logs\main.log`: `LocalSessions.checkTrust: cwd=...`). They survive a folder move and must be patched, or the app keeps showing the old path even after `~/.claude.json` is fixed.
- `.claude/` folder and `CLAUDE.md` inside the project folder travel with the folder automatically — no special handling needed.
- `.mcp.json` may contain absolute paths and must be patched if present.
- WSL projects accessed from Windows via `\\wsl.localhost\...` stay in the Windows `%USERPROFILE%\.claude\` store — no cross-store migration needed. There is no `claude` CLI (and no `~/.claude`) inside the distro; the desktop app runs the CLI on the Windows side with the UNC `cwd`.
- **Canonical WSL form:** the desktop app registers a WSL project as `\\wsl.localhost\<distro-lowercased>\...` (e.g. `\\wsl.localhost\ubuntu\...`). The legacy alias `\\wsl$\Ubuntu\...` points to the same location but encodes to a **different** key (`--wsl--Ubuntu-...` vs `--wsl-localhost-ubuntu-...`). A move whose target uses the legacy alias works but is non-canonical and risks re-orphaning if the folder is later re-opened via the app's file picker. Move targets should be normalised to the canonical form — see issue `#23`.

## Tests

Run the test suite with:

```bash
python -m pytest test_claude_mover.py
```

`test_claude_mover.py` contains `147` tests across `21` test classes with `92%` line coverage. Coverage is measured via `pytest-cov` (`pip install pytest-cov`).

The uncovered lines (`ensure_parent` interactive prompt, `if __name__ == "__main__"`) require interactive `input()` mocking or direct script execution and are intentionally left for manual verification via `--dry-run`.

## Deferred features

- **Merge mode:** combine Claude session histories from two related project paths into one target directory.
- **pip package:** distribute as an installable Python package (`pip install claude-mover`).
