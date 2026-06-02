#!/usr/bin/env python3
"""claude-mover: safely relocates Claude Code project folders on Windows."""

import argparse
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

APP_NAME = "ClaudeMover"
CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"
HISTORY_FILE = CLAUDE_DIR / "history.jsonl"
LOG_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_NAME / "logs"
CHECKPOINT_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_NAME / "checkpoints"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(dry_run: bool) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"claude-mover-{datetime.now():%Y-%m-%d_%H-%M-%S}.log"

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    if dry_run:
        logging.info("[DRY RUN] No changes will be made.")

    return log_file


# ---------------------------------------------------------------------------
# Path utilities
# ---------------------------------------------------------------------------

def encode_path(path: Path) -> str:
    """Encode a Windows absolute path to Claude's dashed directory name.

    Examples:
      D:\\workspace\\myapp                    ->  D--workspace-myapp
      \\\\wsl.localhost\\Ubuntu\\home\\myapp  ->  --wsl-localhost-ubuntu-home-myapp
    """
    s = str(path.resolve())
    if s.startswith('\\\\'):
        # UNC path: leading \\ -> --, server+share lowercased, dots and backslashes -> dashes
        parts = [p for p in s[2:].split('\\') if p]
        encoded = [parts[i].lower().replace('.', '-') if i < 2 else parts[i]
                   for i in range(len(parts))]
        return '--' + '-'.join(encoded)
    # Drive letter path: D:\... -> D--...
    s = re.sub(r'^([A-Za-z]):\\', lambda m: m.group(1).upper() + "--", s)
    s = s.replace("\\", "-")
    return s


def _decode_dashed_naive(dashed: str) -> Optional[Path]:
    m = re.match(r'^([A-Za-z])--(.+)$', dashed)
    if not m:
        return None
    drive = m.group(1).upper()
    rest = m.group(2).replace("-", "\\")
    return Path(f"{drive}:\\{rest}")


_UNC_DASHED_SERVERS: dict[str, str] = {
    'wsl-localhost': 'wsl.localhost',
    'wsl': 'wsl$',
}


def _decode_dashed_unc_naive(dashed: str) -> Optional[Path]:
    """Best-effort decode of a Claude-dashed UNC path back to a Windows UNC Path.

    Example: --wsl-localhost-ubuntu-home-automatix-workspace-SleepNote
          -> \\\\wsl.localhost\\ubuntu\\home\\automatix\\workspace\\SleepNote
    Lossy: dashes in component names are indistinguishable from path separators.
    """
    if not dashed.startswith('--'):
        return None
    s = dashed[2:]
    for dashed_server, real_server in _UNC_DASHED_SERVERS.items():
        if s.lower().startswith(dashed_server + '-'):
            rest = s[len(dashed_server) + 1:]
            return Path(f'\\\\{real_server}\\' + rest.replace('-', '\\'))
    return Path('\\\\' + s.replace('-', '\\'))


def normalize_path(path_str: str) -> Path:
    """Normalize any of the supported path formats to a Windows Path.

    Accepted formats:
      - CMD style:              C:\\workspace\\myapp
      - Git Bash style:         /c/workspace/myapp
      - Claude dashed (drive):  C--workspace-myapp
      - UNC style:              \\\\wsl.localhost\\Ubuntu\\home\\myapp
                                //wsl.localhost/Ubuntu/home/myapp
                                //wsl$/Ubuntu/home/myapp
      - Claude dashed (UNC):    --wsl-localhost-ubuntu-home-myapp
    """
    s = path_str.strip().rstrip("/\\")

    # CMD style: C:\... or C:/...
    if re.match(r'^[A-Za-z]:[/\\]', s):
        return Path(s)

    # UNC style: \\server\... or //server/...
    m = re.match(r'^[/\\]{2}([^/\\].*)$', s)
    if m:
        return Path('\\\\' + m.group(1).replace('/', '\\'))

    # Git Bash style: /c/rest/of/path
    m = re.match(r'^/([A-Za-z])/(.+)$', s)
    if m:
        drive = m.group(1).upper()
        rest = m.group(2).replace("/", "\\")
        return Path(f"{drive}:\\{rest}")

    # Claude dashed drive style: C--workspace-myapp
    if re.match(r'^[A-Za-z]--', s):
        if PROJECTS_DIR.exists():
            for ctx_dir in PROJECTS_DIR.iterdir():
                if ctx_dir.name.lower() == s.lower():
                    decoded = _decode_dashed_naive(ctx_dir.name)
                    if decoded:
                        return decoded
        decoded = _decode_dashed_naive(s)
        if decoded:
            return decoded

    # Claude dashed UNC style: --wsl-localhost-ubuntu-...
    if s.startswith('--'):
        if PROJECTS_DIR.exists():
            for ctx_dir in PROJECTS_DIR.iterdir():
                if ctx_dir.name.lower() == s.lower():
                    decoded = _decode_dashed_unc_naive(ctx_dir.name)
                    if decoded:
                        return decoded
        decoded = _decode_dashed_unc_naive(s)
        if decoded:
            return decoded

    # Fallback: resolve relative path
    return Path(s).resolve()


# ---------------------------------------------------------------------------
# Path variant helpers for string patching
# ---------------------------------------------------------------------------

def _path_variants(path: Path) -> list[str]:
    """Return all string representations of a path that may appear in files.

    6 variants are returned so that patch_content covers every form that can
    appear in JSON, JSONL, or plain-text files:
      - Backslash form (as-is on Windows)
      - Forward-slash forms (3 variants: D:/, /d/, /D/ or // for UNC)
      - Claude dashed-encoded form
      - JSON-encoded backslash form (each backslash doubled, as stored in
        history.jsonl "project" fields and similar JSON key-value pairs)
    """
    p = path.resolve()
    p_str = str(p)
    json_encoded = json.dumps(p_str)[1:-1]  # strip surrounding quotes

    if p_str.startswith('\\\\'):
        # UNC path: backslash, forward-slash, and dashed variants.
        # Git Bash has no UNC equivalent; forward-slash form is the closest substitute
        # for variants 3 and 4.
        backslash = p_str                        # \\wsl.localhost\Ubuntu\home\myapp
        forward = p_str.replace('\\', '/')       # //wsl.localhost/Ubuntu/home/myapp
        encoded = encode_path(p)                 # --wsl-localhost-ubuntu-home-myapp
        return [backslash, forward, forward, forward, encoded, json_encoded]

    drive = p.drive  # e.g. 'D:'
    rest_backslash = p_str[len(drive):]
    rest_forward = rest_backslash.replace("\\", "/")
    drive_letter = drive[0]
    return [
        p_str,                                              # D:\workspace\myapp
        p_str.replace("\\", "/"),                          # D:/workspace/myapp
        f"/{drive_letter.lower()}{rest_forward}",          # /d/workspace/myapp
        f"/{drive_letter.upper()}{rest_forward}",          # /D/workspace/myapp
        encode_path(p),                                     # D--workspace-myapp
        json_encoded,                                       # D:\\workspace\\myapp (JSON)
    ]


def patch_content(content: str, old_path: Path, new_path: Path) -> str:
    """Replace all known representations of old_path with new_path in content."""
    old_variants = _path_variants(old_path)
    new_variants = _path_variants(new_path)

    result = content
    for old_v, new_v in zip(old_variants, new_variants):
        result = re.sub(re.escape(old_v), lambda _: new_v, result, flags=re.IGNORECASE)
    return result


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_source(path: Path) -> Path:
    """Validate source path and return its Claude context directory."""
    if not path.exists():
        logging.error(f"Source folder does not exist: {path}")
        logging.error("Verify the path and try again.")
        sys.exit(1)
    if not path.is_dir():
        logging.error(f"Source path is not a directory: {path}")
        sys.exit(1)

    encoded = encode_path(path)
    ctx = PROJECTS_DIR / encoded
    if not ctx.exists():
        logging.error(f"No Claude context found for: {path}")
        logging.error(f"Expected: {ctx}")
        logging.error("This folder does not appear to be a Claude Code project.")
        sys.exit(1)

    return ctx


def validate_target(path: Path) -> None:
    """Validate that target path and its Claude context do not already exist."""
    if path.exists():
        logging.error(f"Target folder already exists: {path}")
        logging.error("Choose a different target path or remove the existing folder first.")
        sys.exit(1)

    encoded = encode_path(path)
    ctx = PROJECTS_DIR / encoded
    if ctx.exists():
        logging.error(f"A Claude context already exists for target path: {path}")
        logging.error(f"Conflicting context: {ctx}")
        logging.error("Remove or relocate the existing context before proceeding.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Parent directory
# ---------------------------------------------------------------------------

def ensure_parent(path: Path, dry_run: bool) -> None:
    """Ensure the parent directory of path exists; prompt the user if it does not."""
    parent = path.parent
    if parent.exists():
        return

    print(f"\nThe parent directory does not exist: {parent}")
    print("Options:")
    print("  1  Abort")
    print("  2  Create the missing directories automatically")
    print("  3  Create them yourself, then retry")

    while True:
        choice = input("Your choice [1/2/3]: ").strip()
        if choice == "1":
            logging.info("Aborted by user (missing parent directory).")
            sys.exit(0)
        elif choice == "2":
            if not dry_run:
                parent.mkdir(parents=True, exist_ok=True)
                logging.info(f"Created: {parent}")
            else:
                logging.info(f"[DRY RUN] Would create: {parent}")
            return
        elif choice == "3":
            input(f"\nPlease create '{parent}', then press Enter to retry...")
            if parent.exists():
                logging.info("Parent directory found. Continuing.")
                return
            print(f"Directory still missing: {parent}")
        else:
            print("Please enter 1, 2, or 3.")


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def backup_context(ctx_dir: Path, dry_run: bool) -> Path:
    backup = ctx_dir.with_name(ctx_dir.name + f".bak-{datetime.now():%Y%m%d-%H%M%S}")
    if not dry_run:
        shutil.copytree(ctx_dir, backup)
        logging.info(f"Backup created: {backup}")
    else:
        logging.info(f"[DRY RUN] Would create backup: {backup}")
    return backup


def restore_backup(backup: Path, ctx_dir: Path) -> None:
    if backup.exists() and not ctx_dir.exists():
        backup.rename(ctx_dir)
        logging.info(f"Context restored from backup: {ctx_dir}")


def remove_backup(backup: Path, dry_run: bool) -> None:
    if not dry_run:
        if backup.exists():
            shutil.rmtree(backup)
            logging.info("Backup removed.")
    else:
        logging.info("[DRY RUN] Would remove backup.")


# ---------------------------------------------------------------------------
# Patching
# ---------------------------------------------------------------------------

def patch_file(file_path: Path, old_path: Path, new_path: Path, dry_run: bool) -> int:
    """Patch a single file. Returns number of changed lines (jsonl) or 1/0 for json."""
    text = file_path.read_text(encoding="utf-8")
    patched = patch_content(text, old_path, new_path)
    if patched == text:
        return 0
    if not dry_run:
        file_path.write_text(patched, encoding="utf-8")
    return text.count("\n") - text.replace(
        text, patched
    ).count("\n") if text != patched else sum(
        1 for a, b in zip(text.splitlines(), patched.splitlines()) if a != b
    ) or 1


def patch_jsonl(file_path: Path, old_path: Path, new_path: Path, dry_run: bool) -> int:
    """Patch a .jsonl file line by line. Returns number of changed lines."""
    lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
    changed = 0
    patched_lines = []
    for line in lines:
        new_line = patch_content(line, old_path, new_path)
        if new_line != line:
            changed += 1
        patched_lines.append(new_line)
    if changed and not dry_run:
        file_path.write_text("".join(patched_lines), encoding="utf-8")
    return changed


# ---------------------------------------------------------------------------
# Directory move (robocopy for long-path safety)
# ---------------------------------------------------------------------------

def _remove_readonly(func, path, exc_info) -> None:
    """onerror handler for shutil.rmtree: clear the read-only bit, then retry.

    Git sets objects in .git/objects/ as read-only on Windows; without this
    handler shutil.rmtree raises [WinError 5] Access is denied on those files.

    WinError 32 (sharing violation) means another process holds the file open
    and cannot be fixed by chmod — raise immediately with an actionable message.
    """
    exc = exc_info[1]
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) == 32:
        raise OSError(
            f"[WinError 32] A file is locked by another process: {path}\n"
            "Close any editors, terminals, or Claude Code sessions that have "
            "files in the source project open, then retry with --resume."
        ) from exc
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _move_directory(source: Path, target: Path) -> None:
    """Move a directory tree using robocopy to handle Windows MAX_PATH limits.

    shutil.move uses CreateFileW which caps at 260 chars; robocopy uses the
    extended-length path API internally, so files at the 260-char boundary copy
    correctly.  Source deletion uses _remove_readonly to handle read-only files
    (e.g. .git/objects) that shutil.rmtree cannot delete by default on Windows.
    """
    result = subprocess.run(
        [
            "robocopy", str(source), str(target),
            "/E",    # copy subdirectories, including empty ones
            "/NFL",  # suppress file listing
            "/NDL",  # suppress directory listing
            "/NJH",  # suppress job header
            "/NJS",  # suppress job summary
            "/R:0",  # 0 retries on copy errors
            "/W:0",  # 0 s wait between retries
        ],
        capture_output=True,
        text=True,
    )
    # robocopy exit codes 0–7 mean success (varying levels of work done); 8+ mean error
    if result.returncode >= 8:
        if target.exists():
            shutil.rmtree(str(target), ignore_errors=True)
        raise RuntimeError(
            f"robocopy failed (exit {result.returncode}):\n{result.stdout.strip()}"
        )
    shutil.rmtree(str(source), onerror=_remove_readonly)


def _rmtree_robust(path: Path) -> None:
    """Remove a directory tree; falls back to robocopy /MIR when paths exceed MAX_PATH."""
    try:
        shutil.rmtree(str(path), onerror=_remove_readonly)
    except OSError:
        with tempfile.TemporaryDirectory() as empty:
            subprocess.run(
                ["robocopy", empty, str(path), "/MIR",
                 "/NFL", "/NDL", "/NJH", "/NJS", "/R:0", "/W:0"],
                capture_output=True,
            )
        shutil.rmtree(str(path), ignore_errors=True)


# ---------------------------------------------------------------------------
# Checkpoint (migration state for --resume)
# ---------------------------------------------------------------------------

def _checkpoint_path(source: Path) -> Path:
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    return CHECKPOINT_DIR / f"{encode_path(source)}.json"


def _write_checkpoint(source: Path, target: Path, backup: Path, error: str = "") -> None:
    data = {
        "source": str(source),
        "target": str(target),
        "backup": str(backup),
        "failed": bool(error),
        "error": error,
        "timestamp": datetime.now().isoformat(),
    }
    _checkpoint_path(source).write_text(json.dumps(data, indent=2), encoding="utf-8")


def _read_checkpoint(source: Path) -> Optional[dict]:
    cp = _checkpoint_path(source)
    if cp.exists():
        try:
            return json.loads(cp.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _clear_checkpoint(source: Path) -> None:
    cp = _checkpoint_path(source)
    if cp.exists():
        cp.unlink()


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def migrate(source: Path, target: Path, dry_run: bool) -> dict:
    """Execute the full migration. Returns a summary dict."""
    source = source.resolve()
    target = target.resolve()

    summary = {
        "source": str(source),
        "target": str(target),
        "sessions_migrated": 0,
        "config_files_patched": [],
        "history_lines_patched": 0,
    }

    # --- Validate ---
    source_ctx = validate_source(source)
    validate_target(target)
    ensure_parent(target, dry_run)

    target_encoded = encode_path(target)
    target_ctx = PROJECTS_DIR / target_encoded

    logging.info(f"Source: {source}")
    logging.info(f"Source context: {source_ctx}")
    logging.info(f"Target: {target}")
    logging.info(f"Target context: {target_ctx}")

    # --- Backup ---
    backup = backup_context(source_ctx, dry_run)
    if not dry_run:
        _write_checkpoint(source, target, backup)

    try:
        # Step 1: Rename Claude context directory
        logging.info(f"Renaming context directory ...")
        if not dry_run:
            source_ctx.rename(target_ctx)
        else:
            logging.info(f"[DRY RUN] Would rename: {source_ctx} -> {target_ctx}")

        # Step 2: Patch path references in session files
        ctx_for_sessions = target_ctx if not dry_run else source_ctx
        jsonl_files = list(ctx_for_sessions.glob("*.jsonl"))
        logging.info(f"Patching {len(jsonl_files)} session file(s) ...")
        for jf in jsonl_files:
            changed = patch_jsonl(jf, source, target, dry_run)
            summary["sessions_migrated"] += 1
            if changed:
                logging.info(f"  {jf.name}: {changed} line(s) updated")

        # Step 3: Move project folder
        logging.info(f"Moving project folder ...")
        if not dry_run:
            _move_directory(source, target)
        else:
            logging.info(f"[DRY RUN] Would move: {source} -> {target}")

        # Step 4: Patch config files inside moved project
        config_candidates = [
            target / ".claude" / "settings.json",
            target / ".claude" / "settings.local.json",
            target / ".mcp.json",
        ]
        for cf in config_candidates:
            if cf.exists():
                changed = patch_file(cf, source, target, dry_run)
                if changed:
                    summary["config_files_patched"].append(str(cf))
                    logging.info(f"Patched: {cf}")

        # Step 5: Patch history.jsonl
        if HISTORY_FILE.exists():
            changed = patch_jsonl(HISTORY_FILE, source, target, dry_run)
            summary["history_lines_patched"] = changed
            if changed:
                logging.info(f"history.jsonl: {changed} line(s) updated")

        # Step 6: Remove backup
        remove_backup(backup, dry_run)
        if not dry_run:
            _clear_checkpoint(source)

    except Exception as exc:
        logging.error("Migration failed. Restoring from backup ...")
        if not dry_run:
            restore_backup(backup, source_ctx)
            # Remove the stale target context (renamed but now reverted in source_ctx)
            if target_ctx.exists():
                shutil.rmtree(str(target_ctx), ignore_errors=True)
                logging.info(f"Removed stale target context: {target_ctx}")
            # Remove any partial project copy at the target location
            if target.exists():
                logging.info(f"Removing partial project copy: {target}")
                _rmtree_robust(target)
            _write_checkpoint(source, target, backup, error=str(exc))
            logging.info(f"Recovery state saved: {_checkpoint_path(source)}")
            logging.info("Fix the issue, then re-run with --resume to retry.")
        raise

    return summary


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(summary: dict, log_file: Path, dry_run: bool) -> None:
    prefix = "[DRY RUN] " if dry_run else ""
    print("\n" + "=" * 60)
    print(f"{prefix}Migration {'preview' if dry_run else 'complete'}.")
    print(f"  Source:                {summary['source']}")
    print(f"  Target:                {summary['target']}")
    print(f"  Sessions migrated:     {summary['sessions_migrated']}")
    print(f"  History lines patched: {summary['history_lines_patched']}")
    if summary["config_files_patched"]:
        print(f"  Config files patched:  {len(summary['config_files_patched'])}")
        for cf in summary["config_files_patched"]:
            print(f"    - {cf}")
    print(f"  Log file:              {log_file}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="claude-mover",
        description="Safely move a Claude Code project folder, preserving session history.",
    )
    parser.add_argument(
        "source",
        help="Source project path (CMD, Git Bash, or Claude dashed format)",
    )
    parser.add_argument(
        "target",
        help="Target project path (CMD, Git Bash, or Claude dashed format)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making any changes",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Clean up leftover artifacts from a previous failed migration, then retry",
    )
    args = parser.parse_args()

    log_file = setup_logging(args.dry_run)

    source = normalize_path(args.source)
    target = normalize_path(args.target)

    logging.info(f"Resolved source: {source}")
    logging.info(f"Resolved target: {target}")

    if args.resume and not args.dry_run:
        cp = _read_checkpoint(source)
        if cp and cp.get("target") != str(target.resolve()):
            logging.warning(
                f"Checkpoint records a different target: {cp['target']}\n"
                f"  CLI target: {target}\n"
                f"  Proceeding with CLI target."
            )
        target_ctx = PROJECTS_DIR / encode_path(target)
        cleaned = False
        if target_ctx.exists():
            logging.info(f"[RESUME] Removing stale target context: {target_ctx}")
            shutil.rmtree(str(target_ctx), onerror=_remove_readonly)
            cleaned = True
        if target.exists():
            logging.info(f"[RESUME] Removing partial project copy: {target}")
            _rmtree_robust(target)
            cleaned = True
        if cleaned:
            logging.info("[RESUME] Cleanup complete. Starting migration ...")
        else:
            logging.info("[RESUME] Nothing to clean up. Starting migration ...")

    try:
        summary = migrate(source, target, args.dry_run)
        print_summary(summary, log_file, args.dry_run)
    except SystemExit:
        raise
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
