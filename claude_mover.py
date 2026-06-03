#!/usr/bin/env python3
"""claude-mover: safely relocates Claude Code project folders on Windows."""

import argparse
import json
import logging
import os
import re
import shlex
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
CLAUDE_JSON = Path.home() / ".claude.json"   # global app config (project list, GitHub repo map)
LOG_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_NAME / "logs"
CHECKPOINT_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_NAME / "checkpoints"

# Per-session metadata store of the Claude desktop app (MSIX package). Each
# local_<id>.json holds cwd/originCwd, which survive a folder move and otherwise
# keep pointing at the old path (driving the trust dialog and "Copy path").
APP_PACKAGES_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Packages"
APP_SESSION_GLOB = "Claude_*/LocalCache/Roaming/Claude/claude-code-sessions/**/local_*.json"


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

def _path_to_str(path: Path) -> str:
    """Return the canonical string for path, restoring the UNC \\\\ prefix.

    pathlib on Windows does not recognise \\\\wsl$\\... as a UNC path (the '$'
    in the server name confuses the parser) and strips one leading backslash,
    turning \\\\server\\share into \\server\\share.  This helper detects that
    case and restores the correct form before any further processing.
    For normal drive-letter paths, resolve() is called so relative paths work.
    """
    raw = str(path)
    if raw.startswith('\\\\'):
        return raw                        # already a well-formed UNC
    if raw.startswith('\\') and not (len(raw) >= 2 and raw[1] == ':'):
        return '\\' + raw                 # restore the stripped leading backslash
    return str(path.resolve())            # drive-letter path: resolve is safe


def encode_path(path: Path) -> str:
    """Encode a Windows absolute path to Claude's dashed directory name.

    Claude Code derives the per-project directory name from the working
    directory with a single universal rule: every character that is not an
    ASCII letter or digit is replaced by a dash, and the case is preserved.
    The same rule applies to drive-letter and UNC (WSL) paths alike — the
    colon, backslashes, dots, spaces, and the ``$`` in ``\\\\wsl$\\`` are all
    just non-alphanumeric characters mapped to ``-``.

    Examples:
      D:\\workspace\\myapp                    ->  D--workspace-myapp
      D:\\workspace\\Claude Mover             ->  D--workspace-Claude-Mover
      \\\\wsl.localhost\\ubuntu\\home\\myapp  ->  --wsl-localhost-ubuntu-home-myapp
      \\\\wsl$\\Ubuntu\\home\\myapp           ->  --wsl--Ubuntu-home-myapp
    """
    return re.sub(r'[^A-Za-z0-9]', '-', _path_to_str(path))


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


# WSL UNC server aliases that both resolve to the same distro filesystem.
_WSL_UNC_SERVERS = {'wsl$', 'wsl.localhost'}
_CANONICAL_WSL_SERVER = 'wsl.localhost'


def _canonicalize_wsl(path_str: str) -> str:
    """Normalize a WSL UNC path string to the form the Claude desktop app uses.

    Both ``\\\\wsl$\\<Distro>\\...`` and ``\\\\wsl.localhost\\<distro>\\...`` point
    to the same WSL filesystem location, but they encode to different directory
    keys. The desktop app always registers WSL projects as
    ``\\\\wsl.localhost\\<distro-lowercased>\\...``, so a move target must be
    normalized to that canonical form -- otherwise the migrated history lands
    under a key the app never reads (see issue #23). Concretely:

      - server ``wsl$`` / ``wsl.localhost`` (any case) -> ``wsl.localhost``
      - the distro/share component               -> lowercased
      - all remaining path components            -> unchanged

    Non-WSL paths (drive letters, other UNC servers) are returned unchanged.
    """
    if not path_str.startswith('\\\\'):
        return path_str
    parts = path_str[2:].split('\\')
    if not parts or parts[0].lower() not in _WSL_UNC_SERVERS:
        return path_str
    parts[0] = _CANONICAL_WSL_SERVER
    if len(parts) > 1:
        parts[1] = parts[1].lower()            # distro / share -> lowercase
    return '\\\\' + '\\'.join(parts)


def _is_noncanonical_wsl_input(raw: str) -> bool:
    """Return True if the raw input is a WSL path that canonicalization rewrites.

    Used only to emit a user-facing notice that the path form was normalized:
      - any use of the legacy ``wsl$`` alias, or
      - a ``wsl.localhost`` path whose distro component is not already lowercase.
    """
    low = raw.lower()
    if 'wsl$' in low:
        return True
    m = re.search(r'[\\/]{2}wsl\.localhost[\\/]([^\\/]+)', raw, re.IGNORECASE)
    return bool(m and m.group(1) != m.group(1).lower())


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
        return Path(_canonicalize_wsl('\\\\' + m.group(1).replace('/', '\\')))

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
                        return Path(_canonicalize_wsl(str(decoded)))
        decoded = _decode_dashed_unc_naive(s)
        if decoded:
            return Path(_canonicalize_wsl(str(decoded)))

    # Fallback: resolve relative path
    return Path(s).resolve()


# ---------------------------------------------------------------------------
# WSL path translation (for native moves via wsl.exe)
# ---------------------------------------------------------------------------
# robocopy over the \\wsl$ / \\wsl.localhost 9P redirector silently drops files
# under load and cannot replicate Linux symlinks, which causes data loss. For
# any move touching WSL we instead drive the copy natively inside the distro via
# wsl.exe, which needs the path as seen from Linux (a /home/... path for a WSL
# endpoint, or a /mnt/<drive>/... path for a Windows drive endpoint).

_WSL_UNC_RE = re.compile(r'^\\\\(?:wsl\$|wsl\.localhost)\\([^\\]+)(?:\\(.*))?$',
                         re.IGNORECASE)


def _wsl_endpoint(path: Path) -> Optional[tuple[str, str]]:
    """If ``path`` is a WSL UNC path, return ``(distro, linux_path)``; else None.

    ``\\\\wsl.localhost\\Ubuntu\\home\\me\\app`` -> ``("Ubuntu", "/home/me/app")``.
    The distro is returned as written; the Linux path uses forward slashes.
    """
    m = _WSL_UNC_RE.match(_path_to_str(path))
    if not m:
        return None
    distro = m.group(1)
    rest = (m.group(2) or "").replace("\\", "/").rstrip("/")
    return distro, ("/" + rest if rest else "/")


def _drive_to_wsl_mount(path: Path) -> Optional[str]:
    """Translate a Windows drive path to its WSL ``/mnt`` mount point, or None.

    ``D:\\workspace\\app`` -> ``/mnt/d/workspace/app`` (reachable from any distro).
    """
    m = re.match(r'^([A-Za-z]):[\\/](.*)$', _path_to_str(path))
    if not m:
        return None
    drive = m.group(1).lower()
    rest = m.group(2).replace("\\", "/").rstrip("/")
    return f"/mnt/{drive}/{rest}" if rest else f"/mnt/{drive}"


def _wsl_path_in_distro(path: Path, distro: str) -> Optional[str]:
    """Path as seen inside ``distro``, or None if it is not reachable there.

    - A WSL UNC path in the *same* distro -> its Linux path.
    - A Windows drive path                -> its ``/mnt`` mount (any distro).
    - A WSL UNC path in a *different* distro -> None (not cross-mounted).
    """
    ep = _wsl_endpoint(path)
    if ep:
        return ep[1] if ep[0].lower() == distro.lower() else None
    return _drive_to_wsl_mount(path)


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
    p_str = _path_to_str(path)
    json_encoded = json.dumps(p_str)[1:-1]  # strip surrounding quotes

    if p_str.startswith('\\\\'):
        # UNC path: backslash, forward-slash, and dashed variants.
        # Git Bash has no UNC equivalent; forward-slash form is the closest substitute
        # for variants 3 and 4.
        backslash = p_str                        # \\wsl.localhost\Ubuntu\home\myapp
        forward = p_str.replace('\\', '/')       # //wsl.localhost/Ubuntu/home/myapp
        encoded = encode_path(path)              # --wsl-localhost-ubuntu-home-myapp
        return [backslash, forward, forward, forward, encoded, json_encoded]

    p = path.resolve()
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
    return 1


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


def app_session_files() -> list[Path]:
    """Return every Claude desktop app per-session metadata file.

    The MSIX desktop app keeps its own session store, separate from ~/.claude/:
        %LOCALAPPDATA%\\Packages\\Claude_*\\LocalCache\\Roaming\\Claude\\
            claude-code-sessions\\<account>\\<group>\\local_<id>.json
    Each file holds cwd/originCwd, which survive a folder move and otherwise
    keep pointing at the old path. Returns an empty list when no store exists.
    """
    if not APP_PACKAGES_DIR.exists():
        return []
    return sorted(APP_PACKAGES_DIR.glob(APP_SESSION_GLOB))


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


# --- Copy verification ----------------------------------------------------
# A directory move copies the tree, then deletes the source. If the copy is
# silently incomplete (e.g. robocopy over the WSL 9P redirector dropping
# writes) deleting the source destroys data. Every move therefore builds a
# manifest of both trees and confirms each source entry reached the target
# *before* the source is removed. Manifest entries are keyed by relative POSIX
# path and carry (kind, size): kind is 'f' (file), 'l' (symlink), or 'd'
# (directory); size is the byte size for files only (directory sizes are
# filesystem-dependent and not comparable across volumes, so they are ignored).

def _manifest_windows(root: Path) -> dict[str, tuple[str, int]]:
    """Build a copy-verification manifest by walking ``root`` on Windows."""
    manifest: dict[str, tuple[str, int]] = {}
    if not root.exists():
        return manifest
    for dirpath, dirnames, filenames in os.walk(root):  # followlinks=False
        base = Path(dirpath)
        for name in dirnames + filenames:
            p = base / name
            rel = p.relative_to(root).as_posix()
            if p.is_symlink():
                manifest[rel] = ("l", 0)
            elif p.is_dir():
                manifest[rel] = ("d", 0)
            else:
                try:
                    manifest[rel] = ("f", p.stat().st_size)
                except OSError:
                    manifest[rel] = ("f", -1)
    return manifest


# find -printf format used to enumerate a tree inside WSL: type, size, path.
_WSL_FIND_PRINTF = r"find . -mindepth 1 -printf '%y\t%s\t%p\n'"


def _run_wsl_bash(distro: str, script: str) -> subprocess.CompletedProcess:
    """Run a bash ``script`` inside ``distro``, delivering it on stdin.

    The script is piped to ``bash`` via stdin rather than passed as a ``bash -c``
    argument: subprocess.list2cmdline wraps an argument containing spaces in
    double quotes and escapes inner quotes, but wsl.exe re-parses the command
    line after ``--`` and corrupts that escaping (e.g. a ``"$dst"`` reference
    arrives empty). Feeding the script on stdin sidesteps Windows command-line
    quoting entirely, so embedded quotes survive verbatim.
    """
    return subprocess.run(
        ["wsl.exe", "-d", distro, "--", "bash"],
        input=script.encode("utf-8"),
        capture_output=True,
    )


def _parse_find_manifest(text: str) -> dict[str, tuple[str, int]]:
    """Parse ``find -printf '%y\\t%s\\t%p\\n'`` output into a manifest dict."""
    manifest: dict[str, tuple[str, int]] = {}
    for line in text.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        ftype, size, path = parts
        rel = path[2:] if path.startswith("./") else path
        if ftype == "l":
            manifest[rel] = ("l", 0)
        elif ftype == "d":
            manifest[rel] = ("d", 0)
        else:
            manifest[rel] = ("f", int(size) if size.lstrip("-").isdigit() else -1)
    return manifest


def _manifest_wsl(distro: str, linux_path: str) -> dict[str, tuple[str, int]]:
    """Build the manifest natively inside ``distro`` via ``find``.

    Enumeration runs in Linux because the \\\\wsl$ 9P redirector can
    under-report directory contents when the tree is read from Windows.
    """
    result = _run_wsl_bash(distro, f"cd {shlex.quote(linux_path)} && {_WSL_FIND_PRINTF}")
    return _parse_find_manifest(result.stdout.decode("utf-8", "replace"))


def _compare_manifests(src: dict[str, tuple[str, int]],
                       dst: dict[str, tuple[str, int]]) -> list[str]:
    """Return discrepancies: source entries missing from or mismatched in the
    target. Extra target entries are ignored — only loss of source data matters.
    """
    problems: list[str] = []
    for rel, (kind, size) in sorted(src.items()):
        if rel not in dst:
            problems.append(f"missing in target: {rel}")
            continue
        dkind, dsize = dst[rel]
        if dkind != kind:
            problems.append(f"type mismatch ({kind} -> {dkind}): {rel}")
        elif kind == "f" and size != dsize:
            problems.append(f"size mismatch ({size} -> {dsize} bytes): {rel}")
    return problems


def _verify_or_raise(src: dict[str, tuple[str, int]],
                     dst: dict[str, tuple[str, int]]) -> None:
    """Raise RuntimeError (leaving the source intact) if the copy is incomplete."""
    discrepancies = _compare_manifests(src, dst)
    if discrepancies:
        shown = "\n  ".join(discrepancies[:20])
        more = f"\n  ... and {len(discrepancies) - 20} more" if len(discrepancies) > 20 else ""
        raise RuntimeError(
            "Copy verification failed — source left intact. "
            f"{len(discrepancies)} discrepancy(ies):\n  {shown}{more}"
        )


def _delete_source(source: Path, distro: Optional[str] = None,
                   src_linux: Optional[str] = None) -> bool:
    """Delete the source after a *verified* copy. Never fatal.

    A locked file (e.g. one still open in an editor or the Claude app) leaves
    the source in place with a warning rather than discarding the verified
    target. Returns True if the source was fully removed.
    """
    try:
        if distro and src_linux:
            r = _run_wsl_bash(distro, f"rm -rf {shlex.quote(src_linux)}")
            if r.returncode != 0:
                raise OSError(r.stderr.decode("utf-8", "replace").strip() or
                              f"wsl rm exited {r.returncode}")
        else:
            shutil.rmtree(str(source), onerror=_remove_readonly)
        return True
    except OSError as exc:
        logging.warning(
            f"Copy verified, but the source could not be fully removed: {exc}\n"
            f"The migration is complete; delete the leftover source manually: {source}"
        )
        return False


def _move_directory_wsl(source: Path, target: Path, distro: str,
                        src_linux: str, tgt_linux: str) -> None:
    """Move a folder natively inside WSL via wsl.exe (cp -a + verify + delete).

    Used whenever either endpoint is a WSL UNC path. ``cp -a`` preserves
    symlinks and permissions and writes through the Linux VFS, avoiding the
    silent data loss of robocopy over the \\\\wsl$ 9P redirector.

    The copy and both verification manifests run in a *single* wsl.exe
    invocation so they share one consistent filesystem view: separate wsl.exe
    invocations can briefly observe stale drvfs metadata, which could otherwise
    let an incomplete copy verify as complete and lose data on source deletion.
    """
    logging.info(f"WSL-native copy in distro '{distro}': {src_linux} -> {tgt_linux}")
    marker = "===CLAUDE_MOVER_MANIFEST_SEP==="
    script = (
        "set -e; "
        f"src={shlex.quote(src_linux)}; dst={shlex.quote(tgt_linux)}; "
        'mkdir -p "$dst"; '
        'cp -a "$src/." "$dst/"; '
        f'( cd "$src" && {_WSL_FIND_PRINTF} ); '
        f'echo "{marker}"; '
        f'( cd "$dst" && {_WSL_FIND_PRINTF} )'
    )
    result = _run_wsl_bash(distro, script)
    if result.returncode != 0:
        err = result.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"wsl cp failed (exit {result.returncode}):\n{err}")
    # Verify every source entry reached the target before deleting the source.
    src_text, _, dst_text = result.stdout.decode("utf-8", "replace").partition(marker)
    _verify_or_raise(_parse_find_manifest(src_text), _parse_find_manifest(dst_text))
    # Delete the source via WSL too: rm -rf handles both /mnt and Linux paths and,
    # unlike shutil.rmtree, removes WSL symlinks on a Windows source cleanly.
    _delete_source(source, distro=distro, src_linux=src_linux)


def _move_directory(source: Path, target: Path) -> None:
    """Move a directory tree, verifying the copy before deleting the source.

    For any move touching WSL, copy natively via wsl.exe (_move_directory_wsl):
    robocopy over the \\\\wsl$ 9P redirector silently drops files under load and
    cannot replicate Linux symlinks, which previously caused data loss
    (issue #26). Otherwise use robocopy, which uses the extended-length path API
    internally so files at the 260-char MAX_PATH boundary copy correctly (where
    shutil.move's CreateFileW would fail). In all cases the source is deleted
    only after every source entry is confirmed present in the target, and source
    deletion uses _remove_readonly to clear the read-only bit on files such as
    .git/objects that shutil.rmtree cannot otherwise delete on Windows.
    """
    src_wsl = _wsl_endpoint(source)
    tgt_wsl = _wsl_endpoint(target)
    if src_wsl or tgt_wsl:
        distro = (tgt_wsl or src_wsl)[0]
        src_linux = _wsl_path_in_distro(source, distro)
        tgt_linux = _wsl_path_in_distro(target, distro)
        if src_linux and tgt_linux:
            _move_directory_wsl(source, target, distro, src_linux, tgt_linux)
            return
        logging.warning(
            "WSL endpoints span different distros (not cross-mounted); "
            "falling back to robocopy with verification."
        )

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
    # Verify the copy before deleting the source (prevents silent data loss).
    _verify_or_raise(_manifest_windows(source), _manifest_windows(target))
    _delete_source(source)


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
        "app_sessions_patched": 0,
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

        # Step 6: Patch ~/.claude.json (global app config: project list + GitHub repo map)
        if CLAUDE_JSON.exists():
            changed = patch_file(CLAUDE_JSON, source, target, dry_run)
            if changed:
                summary["config_files_patched"].append(str(CLAUDE_JSON))
                logging.info(f"Patched: {CLAUDE_JSON}")

        # Step 7: Patch the Claude desktop app session store (cwd/originCwd).
        # This store lives outside ~/.claude/ and is what drives the app's
        # trust dialog, "Show in Explorer", and "Copy path".
        app_files = app_session_files()
        if app_files:
            logging.info(f"Patching {len(app_files)} desktop app session file(s) ...")
            for sf in app_files:
                changed = patch_file(sf, source, target, dry_run)
                if changed:
                    summary["app_sessions_patched"] += 1
                    summary["config_files_patched"].append(str(sf))
                    logging.info(f"  {sf.name}: cwd/originCwd updated")

        # Step 8: Remove backup
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
    print(f"  App sessions patched:  {summary['app_sessions_patched']}")
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

    for label, raw in (("source", args.source), ("target", args.target)):
        if _is_noncanonical_wsl_input(raw):
            resolved = source if label == "source" else target
            logging.info(
                f"Normalized WSL {label} to the desktop app's canonical form: {resolved}"
            )

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
