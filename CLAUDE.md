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
| **Path utilities** | `encode_path` (absolute path → dashed key), `normalize_path` (accepts all path formats), `_canonicalize_wsl` (WSL UNC → canonical `wsl.localhost` form), `_is_noncanonical_wsl_input`, `_decode_dashed_naive`, `_decode_dashed_unc_naive`, `_UNC_DASHED_SERVERS` |
| **Path variant helpers** | `_path_variants` returns the `5` string representations of a path that may appear in files; `patch_content` replaces all of them in a string |
| **Validation** | `validate_source` / `validate_target` — existence checks with actionable error messages |
| **Parent directory** | `ensure_parent` — interactive prompt when the target parent is missing |
| **Backup** | `backup_context` / `restore_backup` / `remove_backup` — safety net around the context rename |
| **Patching** | `patch_file` (generic), `patch_jsonl` (line-by-line for `.jsonl` files), `app_session_files` (locate the desktop app session store) |
| **WSL translation** | `_wsl_endpoint` (WSL UNC → `(distro, linux_path)`), `_drive_to_wsl_mount` (drive path → `/mnt/<d>/…`), `_wsl_path_in_distro` (path as seen inside a given distro) |
| **Copy verification** | `_manifest_windows` / `_manifest_wsl` / `_parse_find_manifest` (build a `{relpath: (kind, size)}` manifest), `_compare_manifests` / `_verify_or_raise` (confirm every source entry reached the target) |
| **Directory move** | `_move_directory` — dispatches to `_move_directory_wsl` (native `wsl.exe cp -a` for any WSL endpoint) or robocopy (long-path safety) — both verify before deleting the source; `_run_wsl_bash` (run a bash script in a distro via stdin); `_delete_source` (remove a verified source, non-fatal on lock); `_rmtree_robust` — robocopy /MIR fallback for deletion |
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
- **Copy-then-verify-then-delete (issue `#26`):** the folder move never deletes the source until every source entry is confirmed present in the target. `_move_directory` copies, builds a manifest of both trees (relative path + kind + file size), and only deletes the source when `_compare_manifests` finds no missing or mismatched entries; otherwise it raises with the source left intact. This closes a data-loss bug where a copy reported success but was silently incomplete.
- **WSL moves copy natively, not via robocopy:** robocopy over the `\\wsl$\` / `\\wsl.localhost\` 9P redirector is unreliable — it silently drops writes under load (reporting an exit code `< 8` that looks like success) and cannot replicate Linux symlinks (exit `9`, empty/wrong entries). When either endpoint is a WSL UNC path, `_move_directory_wsl` runs the copy inside the distro with `cp -a` (preserving symlinks and permissions). The copy **and both verification manifests run in a single `wsl.exe` invocation**, because separate invocations can observe stale `drvfs` metadata — a split copy/verify could otherwise let an incomplete copy verify as complete. Cross-distro moves (different WSL distros, not cross-mounted) fall back to robocopy with the same verification.
- **Bash scripts are piped to `wsl.exe … bash` on stdin, never as `bash -c "…"`:** `subprocess.list2cmdline` double-quotes an argument containing spaces and escapes inner quotes, but `wsl.exe` re-parses the command line after `--` and corrupts that escaping (e.g. a `"$dst"` reference arrives empty). `_run_wsl_bash` delivers the script on stdin so embedded quotes survive verbatim.
- **Source deletion is non-fatal after a verified copy:** once the copy is verified complete, a locked source file (one still open in an editor or the Claude app) leaves the source folder in place with a warning rather than discarding the verified target. WSL moves delete via `rm -rf` inside the distro, which removes Linux symlinks on a Windows source cleanly (`shutil.rmtree` raises `WinError 1920` on them).

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
- **Canonical WSL form:** the desktop app registers a WSL project as `\\wsl.localhost\<distro-lowercased>\...` (e.g. `\\wsl.localhost\ubuntu\...`). The legacy alias `\\wsl$\Ubuntu\...` points to the same location but encodes to a **different** key (`--wsl--Ubuntu-...` vs `--wsl-localhost-ubuntu-...`); a move whose target used the legacy alias would be non-canonical and could re-orphan if the folder is later re-opened via the app's file picker. `normalize_path` therefore runs `_canonicalize_wsl` on every WSL UNC path: server `wsl$`/`wsl.localhost` → `wsl.localhost` and the distro component → lowercase. So `\\wsl$\Ubuntu\...` and `\\wsl.localhost\ubuntu\...` both resolve to the single canonical key `--wsl-localhost-ubuntu-...`, regardless of which alias/casing was typed (issue `#23`). `main` logs a notice when an input form was rewritten.

## Tests

Run the test suite with:

```bash
python -m pytest test_claude_mover.py
```

`test_claude_mover.py` contains `195` tests across `39` test classes with `93%` line coverage. Coverage is measured via `pytest-cov` (`pip install pytest-cov`).

The uncovered lines (`ensure_parent` interactive prompt, `if __name__ == "__main__"`) require interactive `input()` mocking or direct script execution and are intentionally left for manual verification via `--dry-run`.

## Deferred features

- **Merge mode:** combine Claude session histories from two related project paths into one target directory.
- **pip package:** distribute as an installable Python package (`pip install claude-mover`).
