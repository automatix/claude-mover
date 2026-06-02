#!/usr/bin/env python3
"""Comprehensive unit tests for claude_mover.py.

Run with:
    python -m unittest test_claude_mover
"""

import json
import logging
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Import the module under test.  setup_logging() is called inside main() only,
# so the module import is side-effect-free.
# ---------------------------------------------------------------------------
import claude_mover
from claude_mover import (
    _checkpoint_path,
    _clear_checkpoint,
    _decode_dashed_naive,
    _decode_dashed_unc_naive,
    _move_directory,
    _path_variants,
    _read_checkpoint,
    _remove_readonly,
    _rmtree_robust,
    _write_checkpoint,
    backup_context,
    encode_path,
    normalize_path,
    patch_content,
    patch_file,
    patch_jsonl,
    remove_backup,
    restore_backup,
    validate_source,
    validate_target,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _make_dir(base: Path, *parts: str) -> Path:
    """Create a directory (and all parents) and return its Path."""
    d = base.joinpath(*parts)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ===========================================================================
# encode_path  — pure, no mocking needed
# ===========================================================================

class TestEncodePath(unittest.TestCase):

    def test_drive_letter_basic(self):
        self.assertEqual(encode_path(Path(r"D:\workspace\myapp")), "D--workspace-myapp")

    def test_drive_letter_uppercase_drive_preserved(self):
        result = encode_path(Path(r"C:\Users\bob\project"))
        self.assertTrue(result.startswith("C--"))

    def test_drive_letter_lowercase_input_normalised_to_upper(self):
        # Path("d:\\...") on Windows resolves with an uppercase drive letter
        result = encode_path(Path("D:\\workspace\\myapp"))
        self.assertTrue(result.startswith("D--"))

    def test_drive_letter_nested_path(self):
        self.assertEqual(encode_path(Path(r"E:\a\b\c\d")), "E--a-b-c-d")

    def test_drive_letter_single_segment(self):
        self.assertEqual(encode_path(Path(r"D:\myproject")), "D--myproject")

    def test_unc_wsl_localhost(self):
        result = encode_path(Path(r"\\wsl.localhost\Ubuntu\home\user\myapp"))
        self.assertEqual(result, "--wsl-localhost-ubuntu-home-user-myapp")

    def test_unc_wsl_dollar(self):
        result = encode_path(Path(r"\\wsl$\Ubuntu\home\user\myapp"))
        self.assertTrue(result.startswith("--"))
        self.assertIn("wsl", result.lower())

    def test_unc_server_dots_become_dashes(self):
        result = encode_path(Path(r"\\wsl.localhost\Debian\projects\foo"))
        self.assertIn("wsl-localhost", result)

    def test_unc_share_lowercased(self):
        result = encode_path(Path(r"\\wsl.localhost\Ubuntu\home\myapp"))
        self.assertIn("ubuntu", result)
        self.assertNotIn("Ubuntu", result)

    def test_unc_path_components_preserve_case(self):
        result = encode_path(Path(r"\\wsl.localhost\Ubuntu\home\automatix\workspace\SleepNote"))
        self.assertIn("SleepNote", result)

    def test_unc_starts_with_double_dash(self):
        result = encode_path(Path(r"\\wsl.localhost\Ubuntu\home\myapp"))
        self.assertTrue(result.startswith("--"))


# ===========================================================================
# _decode_dashed_naive  — pure, no mocking needed
# ===========================================================================

class TestDecodeDashedNaive(unittest.TestCase):

    def test_valid_drive_path(self):
        self.assertEqual(_decode_dashed_naive("D--workspace-myapp"), Path(r"D:\workspace\myapp"))

    def test_valid_nested_path(self):
        self.assertEqual(_decode_dashed_naive("E--a-b-c-d"), Path(r"E:\a\b\c\d"))

    def test_lowercase_drive_letter_uppercased_in_result(self):
        result = _decode_dashed_naive("d--workspace-myapp")
        self.assertIsNotNone(result)
        self.assertEqual(str(result)[0], "D")

    def test_unc_prefix_returns_none(self):
        self.assertIsNone(_decode_dashed_naive("--wsl-localhost-ubuntu-home-myapp"))

    def test_no_double_dash_returns_none(self):
        self.assertIsNone(_decode_dashed_naive("D-workspace-myapp"))

    def test_empty_string_returns_none(self):
        self.assertIsNone(_decode_dashed_naive(""))

    def test_plain_path_returns_none(self):
        self.assertIsNone(_decode_dashed_naive("/d/workspace/myapp"))


# ===========================================================================
# _decode_dashed_unc_naive  — pure, no mocking needed
# ===========================================================================

class TestDecodeDashedUncNaive(unittest.TestCase):

    def test_wsl_localhost(self):
        result = _decode_dashed_unc_naive("--wsl-localhost-ubuntu-home-myapp")
        self.assertIsNotNone(result)
        self.assertIn("wsl.localhost", str(result))

    def test_wsl_localhost_starts_with_unc_prefix(self):
        result = _decode_dashed_unc_naive("--wsl-localhost-Ubuntu-home-user-project")
        self.assertTrue(str(result).startswith(r"\\wsl.localhost"))

    def test_wsl_shorthand_maps_to_wsl_dollar(self):
        # 'wsl' alone (not wsl-localhost) maps to wsl$
        result = _decode_dashed_unc_naive("--wsl-Ubuntu-home-myapp")
        self.assertIsNotNone(result)
        self.assertIn("wsl$", str(result))

    def test_unknown_server_falls_back_to_raw_replacement(self):
        result = _decode_dashed_unc_naive("--myserver-share-path")
        self.assertIsNotNone(result)
        self.assertTrue(str(result).startswith("\\\\"))

    def test_not_unc_prefix_returns_none(self):
        self.assertIsNone(_decode_dashed_unc_naive("D--workspace-myapp"))

    def test_empty_string_returns_none(self):
        self.assertIsNone(_decode_dashed_unc_naive(""))

    def test_double_dash_only_still_returns_path(self):
        result = _decode_dashed_unc_naive("--")
        self.assertIsNotNone(result)


# ===========================================================================
# _path_variants  — pure, no mocking needed
# ===========================================================================

class TestPathVariants(unittest.TestCase):

    def setUp(self):
        self.drive_path = Path(r"D:\workspace\tools\myapp")

    # --- drive-letter path ---

    def test_drive_path_returns_six_items(self):
        self.assertEqual(len(_path_variants(self.drive_path)), 6)

    def test_drive_path_item0_is_backslash_form(self):
        v = _path_variants(self.drive_path)
        self.assertIn("\\", v[0])
        self.assertTrue(v[0].startswith("D:"))

    def test_drive_path_item1_is_forward_slash_form(self):
        v = _path_variants(self.drive_path)
        self.assertIn("D:/", v[1])
        self.assertNotIn("\\", v[1])

    def test_drive_path_item2_is_git_bash_lower(self):
        v = _path_variants(self.drive_path)
        self.assertTrue(v[2].startswith("/d/"))

    def test_drive_path_item3_is_git_bash_upper(self):
        v = _path_variants(self.drive_path)
        self.assertTrue(v[3].startswith("/D/"))

    def test_drive_path_item4_is_encoded(self):
        v = _path_variants(self.drive_path)
        self.assertEqual(v[4], encode_path(self.drive_path))

    def test_drive_path_item5_is_json_encoded(self):
        v = _path_variants(self.drive_path)
        expected = json.dumps(str(self.drive_path.resolve()))[1:-1]
        self.assertEqual(v[5], expected)

    def test_drive_path_item5_contains_doubled_backslashes(self):
        v = _path_variants(self.drive_path)
        self.assertIn("\\\\", v[5])

    # --- UNC path ---

    def test_unc_path_returns_six_items(self):
        unc = Path(r"\\wsl.localhost\Ubuntu\home\myapp")
        self.assertEqual(len(_path_variants(unc)), 6)

    def test_unc_path_item0_is_backslash_form(self):
        unc = Path(r"\\wsl.localhost\Ubuntu\home\myapp")
        v = _path_variants(unc)
        self.assertTrue(v[0].startswith("\\\\"))

    def test_unc_path_item1_is_forward_slash_form(self):
        unc = Path(r"\\wsl.localhost\Ubuntu\home\myapp")
        v = _path_variants(unc)
        self.assertTrue(v[1].startswith("//"))
        self.assertNotIn("\\", v[1])

    def test_unc_path_item4_is_encoded(self):
        unc = Path(r"\\wsl.localhost\Ubuntu\home\myapp")
        v = _path_variants(unc)
        self.assertEqual(v[4], encode_path(unc))

    def test_unc_path_item5_is_json_encoded(self):
        unc = Path(r"\\wsl.localhost\Ubuntu\home\myapp")
        v = _path_variants(unc)
        expected = json.dumps(str(unc.resolve()))[1:-1]
        self.assertEqual(v[5], expected)

    def test_unc_path_item5_contains_quadruple_backslashes(self):
        # JSON-encoding \\server\... yields \\\\server\\...
        unc = Path(r"\\wsl.localhost\Ubuntu\home\myapp")
        v = _path_variants(unc)
        self.assertIn("\\\\\\\\", v[5])


# ===========================================================================
# patch_content  — pure, no mocking needed
# ===========================================================================

class TestPatchContent(unittest.TestCase):
    """patch_content must replace every path representation.

    We use clearly distinct path names (alpha / beta) so that assertions on the
    absence of the old value cannot spuriously pass because the new value is a
    substring.
    """

    OLD = Path(r"D:\workspace\alpha")
    NEW = Path(r"D:\workspace\beta")

    def test_replaces_backslash_form(self):
        result = patch_content(r"D:\workspace\alpha", self.OLD, self.NEW)
        self.assertNotIn(r"D:\workspace\alpha", result)

    def test_replaces_forward_slash_form(self):
        result = patch_content("D:/workspace/alpha", self.OLD, self.NEW)
        self.assertNotIn("D:/workspace/alpha", result)

    def test_replaces_git_bash_lower_form(self):
        result = patch_content("/d/workspace/alpha", self.OLD, self.NEW)
        self.assertNotIn("/d/workspace/alpha", result)

    def test_replaces_git_bash_upper_form(self):
        result = patch_content("/D/workspace/alpha", self.OLD, self.NEW)
        self.assertNotIn("/D/workspace/alpha", result)

    def test_replaces_encoded_form(self):
        result = patch_content("D--workspace-alpha", self.OLD, self.NEW)
        self.assertNotIn("D--workspace-alpha", result)

    def test_replaces_json_encoded_double_backslash_form(self):
        """JSON-encoded form uses doubled backslashes; must be replaced via 6th variant."""
        line = json.dumps({"project": str(self.OLD)})
        json_old = json.dumps(str(self.OLD))[1:-1]
        result = patch_content(line, self.OLD, self.NEW)
        self.assertNotIn(json_old, result)

    def test_noop_when_path_absent(self):
        content = "no paths here"
        self.assertEqual(patch_content(content, self.OLD, self.NEW), content)

    def test_case_insensitive_replacement(self):
        content = r"d:\WORKSPACE\alpha"
        result = patch_content(content, self.OLD, self.NEW)
        self.assertNotIn(r"d:\WORKSPACE\alpha", result)

    def test_result_contains_new_path(self):
        result = patch_content("D--workspace-alpha", self.OLD, self.NEW)
        self.assertIn("beta", result)

    def test_empty_content_returns_empty(self):
        self.assertEqual(patch_content("", self.OLD, self.NEW), "")


# ===========================================================================
# REGRESSION: JSON-encoded double-backslash form (named as specified)
# ===========================================================================

class TestPatchContentRegressionJsonDoubleBackslash(unittest.TestCase):
    """Explicit regression test for the JSON-encoded double-backslash bug.

    history.jsonl and session files store paths as
        D:\\workspace\\tools\\SleepNote   (two backslashes = JSON encoding).
    patch_content must replace this form via the 6th variant (_path_variants[5]).
    """

    def test_patch_content_replaces_json_encoded_double_backslash_form(self):
        old_path = Path(r"D:\workspace\tools\SleepNote")
        new_path = Path(r"\\wsl$\Ubuntu\home\automatix\workspace\SleepNote")
        # Simulate a line from history.jsonl: project field uses JSON-encoded backslashes
        content = json.dumps({"project": str(old_path), "sessionId": "abc"})
        # Sanity: confirm the JSON-encoded variant is actually present before patching
        json_encoded_old = json.dumps(str(old_path))[1:-1]
        self.assertIn(json_encoded_old, content)

        result = patch_content(content, old_path, new_path)
        self.assertNotIn(json_encoded_old, result)
        self.assertIn("wsl", result.lower())


# ===========================================================================
# patch_file  — filesystem (TemporaryDirectory)
# ===========================================================================

class TestPatchFile(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    OLD = Path(r"D:\workspace\myapp")
    NEW = Path(r"D:\workspace\newapp")

    def test_patches_content_and_writes_to_file(self):
        f = self.tmp / "settings.json"
        _write(f, json.dumps({"path": str(self.OLD)}) + "\n")
        patch_file(f, self.OLD, self.NEW, dry_run=False)
        self.assertIn("newapp", f.read_text(encoding="utf-8"))

    def test_returns_zero_when_no_change(self):
        f = self.tmp / "settings.json"
        _write(f, '{"unrelated": true}\n')
        self.assertEqual(patch_file(f, self.OLD, self.NEW, dry_run=False), 0)

    def test_returns_nonzero_when_changed(self):
        f = self.tmp / "settings.json"
        _write(f, json.dumps({"path": str(self.OLD)}) + "\n")
        result = patch_file(f, self.OLD, self.NEW, dry_run=False)
        self.assertGreater(result, 0)

    def test_dry_run_does_not_write(self):
        f = self.tmp / "settings.json"
        content = json.dumps({"path": str(self.OLD)}) + "\n"
        _write(f, content)
        patch_file(f, self.OLD, self.NEW, dry_run=True)
        self.assertEqual(f.read_text(encoding="utf-8"), content)


# ===========================================================================
# patch_jsonl  — filesystem (TemporaryDirectory)
# ===========================================================================

class TestPatchJsonl(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    OLD = Path(r"D:\workspace\myapp")
    NEW = Path(r"D:\workspace\newapp")

    def _jsonl_line(self, path: Path) -> str:
        return json.dumps({"p": str(path)}) + "\n"

    def test_patches_lines_in_file(self):
        f = self.tmp / "session.jsonl"
        _write(f, self._jsonl_line(self.OLD) + "unchanged line\n")
        patch_jsonl(f, self.OLD, self.NEW, dry_run=False)
        self.assertIn("newapp", f.read_text(encoding="utf-8"))

    def test_returns_correct_changed_line_count(self):
        f = self.tmp / "session.jsonl"
        _write(f, self._jsonl_line(self.OLD) + "no match\n" + self._jsonl_line(self.OLD))
        self.assertEqual(patch_jsonl(f, self.OLD, self.NEW, dry_run=False), 2)

    def test_dry_run_does_not_write(self):
        f = self.tmp / "session.jsonl"
        original = self._jsonl_line(self.OLD)
        _write(f, original)
        patch_jsonl(f, self.OLD, self.NEW, dry_run=True)
        self.assertEqual(f.read_text(encoding="utf-8"), original)

    def test_multiple_occurrences_on_one_line_count_as_one_changed_line(self):
        f = self.tmp / "session.jsonl"
        # Two occurrences of old_path on a single line (backslash form)
        line = str(self.OLD) + " and " + str(self.OLD) + "\n"
        _write(f, line)
        self.assertEqual(patch_jsonl(f, self.OLD, self.NEW, dry_run=False), 1)

    def test_returns_zero_when_no_match(self):
        f = self.tmp / "session.jsonl"
        _write(f, "no paths here\n")
        self.assertEqual(patch_jsonl(f, self.OLD, self.NEW, dry_run=False), 0)

    def test_json_encoded_double_backslash_form_is_patched(self):
        """Regression: JSON-encoded double-backslash paths must be replaced in .jsonl files."""
        f = self.tmp / "history.jsonl"
        old = Path(r"D:\workspace\tools\OldName")
        new = Path(r"D:\workspace\tools\BrandNew")
        # json.dumps produces the correctly JSON-escaped form
        _write(f, json.dumps({"project": str(old), "id": "x"}) + "\n")
        result = patch_jsonl(f, old, new, dry_run=False)
        self.assertEqual(result, 1)
        self.assertIn("BrandNew", f.read_text(encoding="utf-8"))


# ===========================================================================
# backup_context  — filesystem
# ===========================================================================

class TestBackupContext(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_creates_copy_of_ctx_dir(self):
        ctx = _make_dir(self.tmp, "ctx")
        _write(ctx / "session.jsonl", "line1\n")
        backup = backup_context(ctx, dry_run=False)
        self.assertTrue(backup.exists())

    def test_backup_contains_ctx_contents(self):
        ctx = _make_dir(self.tmp, "ctx")
        _write(ctx / "session.jsonl", "line1\n")
        backup = backup_context(ctx, dry_run=False)
        self.assertTrue((backup / "session.jsonl").exists())

    def test_backup_name_contains_bak_suffix(self):
        ctx = _make_dir(self.tmp, "ctx")
        backup = backup_context(ctx, dry_run=False)
        self.assertIn(".bak-", backup.name)

    def test_dry_run_skips_creation(self):
        ctx = _make_dir(self.tmp, "ctx")
        backup = backup_context(ctx, dry_run=True)
        self.assertFalse(backup.exists())


# ===========================================================================
# restore_backup  — filesystem
# ===========================================================================

class TestRestoreBackup(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_renames_backup_to_ctx_when_ctx_absent(self):
        backup = _make_dir(self.tmp, "ctx.bak-20240101-000000")
        ctx = self.tmp / "ctx"
        restore_backup(backup, ctx)
        self.assertTrue(ctx.exists())
        self.assertFalse(backup.exists())

    def test_noop_when_ctx_already_present(self):
        backup = _make_dir(self.tmp, "ctx.bak-20240101-000000")
        ctx = _make_dir(self.tmp, "ctx")
        restore_backup(backup, ctx)
        # backup must NOT have been moved because ctx was already there
        self.assertTrue(backup.exists())
        self.assertTrue(ctx.exists())

    def test_noop_when_backup_absent(self):
        backup = self.tmp / "ctx.bak-nonexistent"
        ctx = self.tmp / "ctx"
        restore_backup(backup, ctx)  # must not raise


# ===========================================================================
# remove_backup  — filesystem
# ===========================================================================

class TestRemoveBackup(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_deletes_backup(self):
        backup = _make_dir(self.tmp, "ctx.bak-20240101-000000")
        remove_backup(backup, dry_run=False)
        self.assertFalse(backup.exists())

    def test_dry_run_skips_deletion(self):
        backup = _make_dir(self.tmp, "ctx.bak-20240101-000000")
        remove_backup(backup, dry_run=True)
        self.assertTrue(backup.exists())

    def test_noop_when_backup_absent(self):
        backup = self.tmp / "ctx.bak-nonexistent"
        remove_backup(backup, dry_run=False)  # must not raise


# ===========================================================================
# _remove_readonly handler
# ===========================================================================

class TestRemoveReadonly(unittest.TestCase):

    def test_winerror_5_clears_chmod_and_retries(self):
        """Access-denied (WinError 5): chmod is called then func is retried."""
        exc = OSError("access denied")
        exc.winerror = 5
        func = MagicMock()
        path = "some\\path\\file.txt"
        with patch("claude_mover.os.chmod") as mock_chmod:
            _remove_readonly(func, path, (type(exc), exc, None))
        mock_chmod.assert_called_once_with(path, stat.S_IWRITE)
        func.assert_called_once_with(path)

    def test_winerror_32_raises_oserror_with_locked_in_message(self):
        """Sharing-violation (WinError 32): raises OSError with 'locked' in message."""
        exc = OSError("sharing violation")
        exc.winerror = 32
        path = "some\\path\\locked.txt"
        with self.assertRaises(OSError) as ctx:
            _remove_readonly(lambda p: None, path, (type(exc), exc, None))
        self.assertIn("locked", str(ctx.exception).lower())

    def test_other_oserror_clears_chmod_and_retries(self):
        """Any other OSError falls through to the chmod-then-retry path."""
        exc = OSError("some other error")
        exc.winerror = 3
        func = MagicMock()
        path = "path\\file.txt"
        with patch("claude_mover.os.chmod") as mock_chmod:
            _remove_readonly(func, path, (type(exc), exc, None))
        mock_chmod.assert_called_once()
        func.assert_called_once()


# ===========================================================================
# Checkpoint functions
# ===========================================================================

class TestCheckpoint(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        # Route all checkpoint I/O to the temp dir
        self._patcher = patch.object(claude_mover, "CHECKPOINT_DIR", self.tmp)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp.cleanup()

    # Shared fixtures
    _SRC = Path(r"D:\workspace\old")
    _TGT = Path(r"D:\workspace\new")
    _BAK = Path(r"D:\workspace\old.bak")

    # --- _write_checkpoint + _read_checkpoint round-trips ---

    def test_roundtrip_source(self):
        _write_checkpoint(self._SRC, self._TGT, self._BAK)
        self.assertEqual(_read_checkpoint(self._SRC)["source"], str(self._SRC))

    def test_roundtrip_target(self):
        _write_checkpoint(self._SRC, self._TGT, self._BAK)
        self.assertEqual(_read_checkpoint(self._SRC)["target"], str(self._TGT))

    def test_roundtrip_backup(self):
        _write_checkpoint(self._SRC, self._TGT, self._BAK)
        self.assertEqual(_read_checkpoint(self._SRC)["backup"], str(self._BAK))

    def test_failed_false_when_no_error(self):
        _write_checkpoint(self._SRC, self._TGT, self._BAK)
        self.assertFalse(_read_checkpoint(self._SRC)["failed"])

    def test_failed_true_with_error_string(self):
        _write_checkpoint(self._SRC, self._TGT, self._BAK, error="something went wrong")
        data = _read_checkpoint(self._SRC)
        self.assertTrue(data["failed"])
        self.assertEqual(data["error"], "something went wrong")

    # --- _clear_checkpoint ---

    def test_clear_removes_checkpoint_file(self):
        _write_checkpoint(self._SRC, self._TGT, self._BAK)
        _clear_checkpoint(self._SRC)
        self.assertIsNone(_read_checkpoint(self._SRC))

    def test_clear_noop_when_absent(self):
        # Must not raise even when there is no checkpoint file
        _clear_checkpoint(self._SRC)

    # --- _read_checkpoint edge cases ---

    def test_read_returns_none_for_absent_file(self):
        self.assertIsNone(_read_checkpoint(Path(r"D:\workspace\nonexistent")))

    def test_read_returns_none_for_corrupt_json(self):
        src = Path(r"D:\workspace\corrupt")
        cp = _checkpoint_path(src)
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text("not valid json {{{{", encoding="utf-8")
        self.assertIsNone(_read_checkpoint(src))


# ===========================================================================
# _move_directory  — subprocess mocked
# ===========================================================================

class TestMoveDirectory(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_returncode_1_success_calls_rmtree_on_source(self):
        """robocopy exit code 1 (some files copied) = success; source must be deleted."""
        src = _make_dir(self.tmp, "src")
        tgt = self.tmp / "tgt"
        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch("subprocess.run", return_value=mock_result), \
             patch("shutil.rmtree") as mock_rmtree:
            _move_directory(src, tgt)
        mock_rmtree.assert_called_once_with(str(src), onerror=_remove_readonly)

    def test_returncode_0_success_calls_rmtree(self):
        """robocopy exit code 0 (nothing to do) = success; source must be deleted."""
        src = _make_dir(self.tmp, "src")
        tgt = self.tmp / "tgt"
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result), \
             patch("shutil.rmtree") as mock_rmtree:
            _move_directory(src, tgt)
        mock_rmtree.assert_called_once()

    def test_returncode_8_raises_runtime_error(self):
        """robocopy exit code 8 = copy error; RuntimeError must be raised."""
        src = _make_dir(self.tmp, "src")
        tgt = self.tmp / "tgt"          # does not exist
        mock_result = MagicMock()
        mock_result.returncode = 8
        mock_result.stdout = "error detail"
        with patch("subprocess.run", return_value=mock_result), \
             patch("shutil.rmtree"):
            with self.assertRaises(RuntimeError) as ctx:
                _move_directory(src, tgt)
        self.assertIn("robocopy failed", str(ctx.exception))

    def test_returncode_8_with_existing_target_calls_rmtree_with_ignore_errors(self):
        """When robocopy fails and a partial target exists, it must be cleaned up."""
        src = _make_dir(self.tmp, "src")
        tgt = _make_dir(self.tmp, "tgt")   # exists → partial copy scenario
        mock_result = MagicMock()
        mock_result.returncode = 8
        mock_result.stdout = "error"
        with patch("subprocess.run", return_value=mock_result), \
             patch("shutil.rmtree") as mock_rmtree:
            with self.assertRaises(RuntimeError):
                _move_directory(src, tgt)
        mock_rmtree.assert_called_once_with(str(tgt), ignore_errors=True)

    def test_returncode_8_without_existing_target_does_not_call_rmtree(self):
        """When robocopy fails and target does NOT exist, no rmtree should be called."""
        src = _make_dir(self.tmp, "src")
        tgt = self.tmp / "no-such-tgt"
        mock_result = MagicMock()
        mock_result.returncode = 8
        mock_result.stdout = "error"
        with patch("subprocess.run", return_value=mock_result), \
             patch("shutil.rmtree") as mock_rmtree:
            with self.assertRaises(RuntimeError):
                _move_directory(src, tgt)
        mock_rmtree.assert_not_called()


# ===========================================================================
# _rmtree_robust  — subprocess mocked
# ===========================================================================

class TestRmtreeRobust(unittest.TestCase):
    """Tests for _rmtree_robust.

    When shutil.rmtree is patched module-wide, tempfile.TemporaryDirectory
    (used internally by _rmtree_robust) also triggers the mock on cleanup.
    We provide enough side-effect entries to cover all internal calls.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_first_rmtree_succeeds_no_subprocess_call(self):
        d = _make_dir(self.tmp, "to_remove")
        with patch("subprocess.run") as mock_run, \
             patch("shutil.rmtree") as mock_rmtree:
            mock_rmtree.return_value = None   # success
            _rmtree_robust(d)
        mock_run.assert_not_called()
        mock_rmtree.assert_called_once()

    def test_first_rmtree_raises_oserror_calls_robocopy_mir(self):
        d = _make_dir(self.tmp, "to_remove")
        # Side effects for all shutil.rmtree calls inside _rmtree_robust:
        #   call 1: rmtree(path, onerror=...)         → OSError  (triggers fallback)
        #   call 2: TemporaryDirectory.__exit__ cleanup → None
        #   call 3: rmtree(path, ignore_errors=True)  → None
        side_effects = [OSError("locked"), None, None]
        with patch("subprocess.run") as mock_run, \
             patch("shutil.rmtree", side_effect=side_effects):
            _rmtree_robust(d)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertIn("robocopy", cmd)
        self.assertIn("/MIR", cmd)

    def test_first_rmtree_raises_then_final_rmtree_uses_ignore_errors(self):
        d = _make_dir(self.tmp, "to_remove")
        side_effects = [OSError("locked"), None, None]
        with patch("subprocess.run"), \
             patch("shutil.rmtree", side_effect=side_effects) as mock_rmtree:
            _rmtree_robust(d)
        # The third call (index 2) must use ignore_errors=True
        third_call = mock_rmtree.call_args_list[2]
        self.assertTrue(third_call[1].get("ignore_errors", False))


# ===========================================================================
# validate_source
# ===========================================================================

class TestValidateSource(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_exits_when_source_does_not_exist(self):
        nonexistent = self.tmp / "ghost"
        with self.assertRaises(SystemExit):
            validate_source(nonexistent)

    def test_exits_when_ctx_does_not_exist(self):
        src = _make_dir(self.tmp, "src")
        fake_projects = _make_dir(self.tmp, "projects")
        # No ctx directory for src inside fake_projects
        with patch.object(claude_mover, "PROJECTS_DIR", fake_projects):
            with self.assertRaises(SystemExit):
                validate_source(src)

    def test_returns_ctx_when_both_exist(self):
        src = _make_dir(self.tmp, "src")
        fake_projects = _make_dir(self.tmp, "projects")
        encoded = encode_path(src)
        ctx = _make_dir(fake_projects, encoded)
        with patch.object(claude_mover, "PROJECTS_DIR", fake_projects):
            result = validate_source(src)
        self.assertEqual(result, ctx)


# ===========================================================================
# validate_target
# ===========================================================================

class TestValidateTarget(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_exits_when_target_folder_exists(self):
        tgt = _make_dir(self.tmp, "tgt")
        fake_projects = _make_dir(self.tmp, "projects")
        with patch.object(claude_mover, "PROJECTS_DIR", fake_projects):
            with self.assertRaises(SystemExit):
                validate_target(tgt)

    def test_exits_when_target_ctx_exists(self):
        tgt = self.tmp / "tgt"            # folder does NOT exist
        fake_projects = _make_dir(self.tmp, "projects")
        encoded = encode_path(tgt)
        _make_dir(fake_projects, encoded)  # but ctx DOES exist
        with patch.object(claude_mover, "PROJECTS_DIR", fake_projects):
            with self.assertRaises(SystemExit):
                validate_target(tgt)

    def test_passes_when_neither_target_nor_ctx_exist(self):
        tgt = self.tmp / "brand-new-target"
        fake_projects = _make_dir(self.tmp, "projects")
        with patch.object(claude_mover, "PROJECTS_DIR", fake_projects):
            validate_target(tgt)          # must not raise


# ===========================================================================
# normalize_path
# ===========================================================================

class TestNormalizePath(unittest.TestCase):

    def test_cmd_style_backslash(self):
        self.assertEqual(normalize_path(r"D:\workspace\myapp"), Path(r"D:\workspace\myapp"))

    def test_cmd_style_forward_slash(self):
        self.assertEqual(normalize_path("C:/workspace/myapp"), Path(r"C:\workspace\myapp"))

    def test_git_bash_lowercase_drive(self):
        self.assertEqual(normalize_path("/d/workspace/myapp"), Path(r"D:\workspace\myapp"))

    def test_git_bash_uppercase_drive(self):
        self.assertEqual(normalize_path("/C/workspace/myapp"), Path(r"C:\workspace\myapp"))

    def test_unc_backslash_style(self):
        result = normalize_path(r"\\wsl.localhost\Ubuntu\home\myapp")
        self.assertEqual(result, Path(r"\\wsl.localhost\Ubuntu\home\myapp"))

    def test_unc_forward_slash_style(self):
        result = normalize_path("//wsl.localhost/Ubuntu/home/myapp")
        self.assertEqual(result, Path(r"\\wsl.localhost\Ubuntu\home\myapp"))

    def test_unc_forward_slash_wsl_dollar(self):
        result = normalize_path("//wsl$/Ubuntu/home/myapp")
        self.assertIn("wsl$", str(result))

    def test_trailing_backslashes_stripped(self):
        self.assertEqual(
            normalize_path(r"D:\workspace\myapp\\"),
            Path(r"D:\workspace\myapp"),
        )

    def test_trailing_forward_slashes_stripped(self):
        self.assertEqual(
            normalize_path("D:/workspace/myapp/"),
            Path(r"D:\workspace\myapp"),
        )

    def test_claude_dashed_drive_no_projects_dir(self):
        """Falls back to _decode_dashed_naive when PROJECTS_DIR does not exist."""
        with patch.object(claude_mover, "PROJECTS_DIR", Path(r"C:\nonexistent\projects")):
            result = normalize_path("D--workspace-myapp")
        self.assertEqual(result, Path(r"D:\workspace\myapp"))

    def test_claude_dashed_drive_with_matching_ctx(self):
        """When a matching ctx dir exists in PROJECTS_DIR, uses the decoded path."""
        with tempfile.TemporaryDirectory() as tmp:
            fake_projects = Path(tmp) / "projects"
            (fake_projects / "D--workspace-myapp").mkdir(parents=True)
            with patch.object(claude_mover, "PROJECTS_DIR", fake_projects):
                result = normalize_path("d--workspace-myapp")   # lowercase input
        self.assertEqual(result, Path(r"D:\workspace\myapp"))

    def test_claude_dashed_unc_no_projects_dir(self):
        """Falls back to _decode_dashed_unc_naive when PROJECTS_DIR does not exist."""
        with patch.object(claude_mover, "PROJECTS_DIR", Path(r"C:\nonexistent\projects")):
            result = normalize_path("--wsl-localhost-ubuntu-home-myapp")
        self.assertIn("wsl.localhost", str(result))

    def test_claude_dashed_unc_with_matching_ctx(self):
        """When a matching UNC ctx dir exists in PROJECTS_DIR, uses the decoded path."""
        with tempfile.TemporaryDirectory() as tmp:
            fake_projects = Path(tmp) / "projects"
            (fake_projects / "--wsl-localhost-ubuntu-home-myapp").mkdir(parents=True)
            with patch.object(claude_mover, "PROJECTS_DIR", fake_projects):
                result = normalize_path("--wsl-localhost-ubuntu-home-myapp")
        self.assertIn("wsl.localhost", str(result))


# ===========================================================================
# encode_path / _decode_dashed_naive round-trip
# ===========================================================================

class TestEncodeDecodeRoundTrip(unittest.TestCase):

    def test_roundtrip_basic_drive_path(self):
        original = Path(r"D:\workspace\tools\SleepNote")
        self.assertEqual(_decode_dashed_naive(encode_path(original)), original)

    def test_roundtrip_nested_drive_path(self):
        original = Path(r"E:\a\b\c\d")
        self.assertEqual(_decode_dashed_naive(encode_path(original)), original)


# ===========================================================================
# Integration smoke test  — migrate() with tmp dirs
# ===========================================================================

class TestMigrateSmoke(unittest.TestCase):
    """Light integration tests for migrate().  Filesystem operations use
    real temp directories; subprocess (_move_directory) is mocked."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _setup(self):
        """Return (source, target, projects_dir, ctx_src, checkpoint_dir)."""
        projects_dir = self.base / "projects"
        source = self.base / "src_project"
        target = self.base / "dst_project"
        source.mkdir()
        ctx_src = _make_dir(projects_dir, encode_path(source))
        _write(ctx_src / "session.jsonl", json.dumps({"cwd": str(source)}) + "\n")
        checkpoint_dir = self.base / "checkpoints"
        checkpoint_dir.mkdir()
        return source, target, projects_dir, ctx_src, checkpoint_dir

    @patch("claude_mover.HISTORY_FILE", Path(r"Z:\nonexistent\history.jsonl"))
    @patch("claude_mover.CLAUDE_JSON", Path(r"Z:\nonexistent\.claude.json"))
    def test_dry_run_leaves_source_and_ctx_intact(self):
        source, target, projects_dir, ctx_src, checkpoint_dir = self._setup()
        with patch.object(claude_mover, "PROJECTS_DIR", projects_dir), \
             patch.object(claude_mover, "CHECKPOINT_DIR", checkpoint_dir):
            claude_mover.migrate(source, target, dry_run=True)
        self.assertTrue(source.exists())
        self.assertTrue(ctx_src.exists())
        self.assertFalse(target.exists())

    @patch("claude_mover.HISTORY_FILE", Path(r"Z:\nonexistent\history.jsonl"))
    @patch("claude_mover.CLAUDE_JSON", Path(r"Z:\nonexistent\.claude.json"))
    def test_migrate_returns_summary_with_expected_keys(self):
        source, target, projects_dir, ctx_src, checkpoint_dir = self._setup()
        with patch.object(claude_mover, "PROJECTS_DIR", projects_dir), \
             patch.object(claude_mover, "CHECKPOINT_DIR", checkpoint_dir), \
             patch("claude_mover._move_directory"):
            summary = claude_mover.migrate(source, target, dry_run=False)
        for key in ("source", "target", "sessions_migrated", "history_lines_patched"):
            self.assertIn(key, summary)

    @patch("claude_mover.HISTORY_FILE", Path(r"Z:\nonexistent\history.jsonl"))
    @patch("claude_mover.CLAUDE_JSON", Path(r"Z:\nonexistent\.claude.json"))
    def test_migrate_counts_session_files(self):
        source, target, projects_dir, ctx_src, checkpoint_dir = self._setup()
        # Add a second session file
        _write(ctx_src / "session2.jsonl", json.dumps({"cwd": str(source)}) + "\n")
        with patch.object(claude_mover, "PROJECTS_DIR", projects_dir), \
             patch.object(claude_mover, "CHECKPOINT_DIR", checkpoint_dir), \
             patch("claude_mover._move_directory"):
            summary = claude_mover.migrate(source, target, dry_run=False)
        self.assertEqual(summary["sessions_migrated"], 2)


# ===========================================================================
# setup_logging
# ===========================================================================

class TestSetupLogging(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()
        # Reset root logger handlers to avoid polluting subsequent tests
        root = logging.getLogger()
        root.handlers.clear()

    def test_creates_log_file(self):
        with patch.object(claude_mover, "LOG_DIR", self.tmp):
            log_file = claude_mover.setup_logging(dry_run=False)
        self.assertTrue(log_file.exists())

    def test_log_file_is_in_log_dir(self):
        with patch.object(claude_mover, "LOG_DIR", self.tmp):
            log_file = claude_mover.setup_logging(dry_run=False)
        self.assertEqual(log_file.parent, self.tmp)

    def test_dry_run_true_returns_log_file(self):
        with patch.object(claude_mover, "LOG_DIR", self.tmp):
            log_file = claude_mover.setup_logging(dry_run=True)
        self.assertIsInstance(log_file, Path)


# ===========================================================================
# _path_to_str  — covers the single-leading-backslash branch (line 67)
# ===========================================================================

class TestPathToStr(unittest.TestCase):

    def test_unc_double_backslash_returned_as_is(self):
        class _P:
            def __str__(self): return r"\\wsl.localhost\Ubuntu\home"
            def resolve(self): return self
        self.assertEqual(claude_mover._path_to_str(_P()), r"\\wsl.localhost\Ubuntu\home")

    def test_single_leading_backslash_restored(self):
        # Simulates pathlib stripping one backslash from \\wsl$\...
        class _P:
            def __str__(self): return r"\wsl$\Ubuntu\home"
            def resolve(self): return self
        result = claude_mover._path_to_str(_P())
        self.assertEqual(result, r"\\wsl$\Ubuntu\home")

    def test_drive_letter_path_calls_resolve(self):
        class _P:
            def __str__(self): return r"D:\workspace\myapp"
            def resolve(self): return self
        result = claude_mover._path_to_str(_P())
        self.assertEqual(result, r"D:\workspace\myapp")


# ===========================================================================
# normalize_path fallback
# ===========================================================================

class TestNormalizePathFallback(unittest.TestCase):

    def test_plain_string_falls_through_to_resolve(self):
        # A string with no recognised prefix just gets resolved via Path().resolve()
        result = normalize_path("some_relative_path")
        self.assertIsInstance(result, Path)


# ===========================================================================
# validate_source  — not-a-directory branch
# ===========================================================================

class TestValidateSourceNotDir(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_exits_when_source_is_a_file_not_dir(self):
        f = self.tmp / "notadir.txt"
        f.write_text("content", encoding="utf-8")
        with self.assertRaises(SystemExit):
            validate_source(f)


# ===========================================================================
# migrate()  — additional coverage: session logging, config files,
#              history.jsonl, claude.json, and exception rollback
# ===========================================================================

class TestMigrateAdditional(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _setup(self):
        projects_dir = self.base / "projects"
        source = self.base / "src_project"
        target = self.base / "dst_project"
        source.mkdir()
        ctx_src = _make_dir(projects_dir, encode_path(source))
        checkpoint_dir = self.base / "checkpoints"
        checkpoint_dir.mkdir()
        return source, target, projects_dir, ctx_src, checkpoint_dir

    def test_session_logging_line_when_content_matches(self):
        """Line 530: logging when session file content actually changes."""
        source, target, projects_dir, ctx_src, checkpoint_dir = self._setup()
        # Use the fully-resolved path so variant[0] matches even on systems
        # where tempfile returns 8.3 short-name paths (e.g. AUTOMA~1).
        src_resolved = str(source.resolve())
        _write(ctx_src / "session.jsonl", f"project={src_resolved}\n")

        history = self.base / "history.jsonl"
        claude_json = self.base / ".claude.json"

        with patch.object(claude_mover, "PROJECTS_DIR", projects_dir), \
             patch.object(claude_mover, "CHECKPOINT_DIR", checkpoint_dir), \
             patch.object(claude_mover, "HISTORY_FILE", history), \
             patch.object(claude_mover, "CLAUDE_JSON", claude_json), \
             patch("claude_mover._move_directory"), \
             patch("claude_mover.logging.info") as mock_log:
            claude_mover.migrate(source, target, dry_run=False)

        logged = " ".join(str(c) for c in mock_log.call_args_list)
        self.assertIn("line(s) updated", logged)

    def test_config_files_patched_when_present(self):
        """Lines 547-550: config files inside the moved project get patched."""
        source, target, projects_dir, ctx_src, checkpoint_dir = self._setup()
        _write(ctx_src / "session.jsonl", "nothing\n")

        history = self.base / "history.jsonl"
        claude_json = self.base / ".claude.json"

        # Mock _move_directory to create the config file at the target location
        # (simulating what the real move would produce)
        def fake_move(src, tgt):
            settings = tgt / ".claude" / "settings.json"
            _write(settings, json.dumps({"path": str(src)}) + "\n")

        with patch.object(claude_mover, "PROJECTS_DIR", projects_dir), \
             patch.object(claude_mover, "CHECKPOINT_DIR", checkpoint_dir), \
             patch.object(claude_mover, "HISTORY_FILE", history), \
             patch.object(claude_mover, "CLAUDE_JSON", claude_json), \
             patch("claude_mover._move_directory", side_effect=fake_move):
            summary = claude_mover.migrate(source, target, dry_run=False)

        self.assertTrue(any("settings.json" in p for p in summary["config_files_patched"]))

    def test_history_jsonl_patched_when_present(self):
        """Lines 554-557: history.jsonl is patched when it exists."""
        source, target, projects_dir, ctx_src, checkpoint_dir = self._setup()
        _write(ctx_src / "session.jsonl", "nothing\n")

        # Use the resolved path so the variant matches despite 8.3 short names.
        history = self.base / "history.jsonl"
        src_str = str(source.resolve())
        _write(history, f"project={src_str}\n")

        claude_json = self.base / ".claude.json"

        with patch.object(claude_mover, "PROJECTS_DIR", projects_dir), \
             patch.object(claude_mover, "CHECKPOINT_DIR", checkpoint_dir), \
             patch.object(claude_mover, "HISTORY_FILE", history), \
             patch.object(claude_mover, "CLAUDE_JSON", claude_json), \
             patch("claude_mover._move_directory"):
            summary = claude_mover.migrate(source, target, dry_run=False)

        self.assertGreater(summary["history_lines_patched"], 0)

    def test_claude_json_patched_when_present(self):
        """Lines 561-564: ~/.claude.json is patched when it exists."""
        source, target, projects_dir, ctx_src, checkpoint_dir = self._setup()
        _write(ctx_src / "session.jsonl", "nothing\n")

        history = self.base / "history.jsonl"
        claude_json = self.base / ".claude.json"
        # Use the resolved path to avoid 8.3 short-name mismatch.
        _write(claude_json, f"project={str(source.resolve())}\n")

        with patch.object(claude_mover, "PROJECTS_DIR", projects_dir), \
             patch.object(claude_mover, "CHECKPOINT_DIR", checkpoint_dir), \
             patch.object(claude_mover, "HISTORY_FILE", history), \
             patch.object(claude_mover, "CLAUDE_JSON", claude_json), \
             patch("claude_mover._move_directory"):
            summary = claude_mover.migrate(source, target, dry_run=False)

        self.assertTrue(
            any(p.endswith(".claude.json") or ".claude.json" in p
                for p in summary["config_files_patched"])
        )

    def test_exception_in_move_triggers_rollback(self):
        """Lines 571-586: exception path — rollback runs and exception re-raises."""
        source, target, projects_dir, ctx_src, checkpoint_dir = self._setup()
        _write(ctx_src / "session.jsonl", "nothing\n")

        history = self.base / "history.jsonl"
        claude_json = self.base / ".claude.json"

        with patch.object(claude_mover, "PROJECTS_DIR", projects_dir), \
             patch.object(claude_mover, "CHECKPOINT_DIR", checkpoint_dir), \
             patch.object(claude_mover, "HISTORY_FILE", history), \
             patch.object(claude_mover, "CLAUDE_JSON", claude_json), \
             patch("claude_mover._move_directory", side_effect=RuntimeError("disk full")):
            with self.assertRaises(RuntimeError):
                claude_mover.migrate(source, target, dry_run=False)
            # Read checkpoint while CHECKPOINT_DIR patch is still active
            cp = _read_checkpoint(source.resolve())

        self.assertIsNotNone(cp)
        self.assertTrue(cp["failed"])

    def _patch_checkpoint_dir(self, checkpoint_dir):
        return patch.object(claude_mover, "CHECKPOINT_DIR", checkpoint_dir)


# ===========================================================================
# print_summary
# ===========================================================================

class TestPrintSummary(unittest.TestCase):

    def _run(self, config_files=None, dry_run=False):
        summary = {
            "source": r"D:\workspace\old",
            "target": r"D:\workspace\new",
            "sessions_migrated": 3,
            "history_lines_patched": 7,
            "config_files_patched": config_files or [],
        }
        import io
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            claude_mover.print_summary(summary, Path(r"C:\log\file.log"), dry_run=dry_run)
        return buf.getvalue()

    def test_output_contains_source(self):
        self.assertIn("old", self._run())

    def test_output_contains_target(self):
        self.assertIn("new", self._run())

    def test_output_contains_session_count(self):
        self.assertIn("3", self._run())

    def test_output_contains_dry_run_prefix(self):
        self.assertIn("DRY RUN", self._run(dry_run=True))

    def test_output_contains_config_files_when_present(self):
        out = self._run(config_files=[r"D:\workspace\new\.claude\settings.json"])
        self.assertIn("settings.json", out)

    def test_output_no_config_section_when_empty(self):
        out = self._run(config_files=[])
        self.assertNotIn("Config files", out)


# ===========================================================================
# main()
# ===========================================================================

class TestMain(unittest.TestCase):

    _SUMMARY = {
        "source": r"D:\workspace\src",
        "target": r"D:\workspace\tgt",
        "sessions_migrated": 1,
        "history_lines_patched": 0,
        "config_files_patched": [],
    }

    def test_normal_run(self):
        with patch("sys.argv", ["claude-mover", r"D:\workspace\src", r"D:\workspace\tgt"]), \
             patch("claude_mover.setup_logging", return_value=Path(r"C:\fake.log")), \
             patch("claude_mover.migrate", return_value=self._SUMMARY), \
             patch("claude_mover.print_summary"):
            claude_mover.main()

    def test_dry_run_flag(self):
        with patch("sys.argv", ["claude-mover", r"D:\workspace\src", r"D:\workspace\tgt", "--dry-run"]), \
             patch("claude_mover.setup_logging", return_value=Path(r"C:\fake.log")), \
             patch("claude_mover.migrate", return_value=self._SUMMARY) as mock_migrate, \
             patch("claude_mover.print_summary"):
            claude_mover.main()
        _, _, dry_run = mock_migrate.call_args[0]
        self.assertTrue(dry_run)

    def test_exception_exits_with_1(self):
        with patch("sys.argv", ["claude-mover", r"D:\workspace\src", r"D:\workspace\tgt"]), \
             patch("claude_mover.setup_logging", return_value=Path(r"C:\fake.log")), \
             patch("claude_mover.migrate", side_effect=RuntimeError("oops")):
            with self.assertRaises(SystemExit) as ctx:
                claude_mover.main()
        self.assertEqual(ctx.exception.code, 1)

    def test_system_exit_propagates(self):
        with patch("sys.argv", ["claude-mover", r"D:\workspace\src", r"D:\workspace\tgt"]), \
             patch("claude_mover.setup_logging", return_value=Path(r"C:\fake.log")), \
             patch("claude_mover.migrate", side_effect=SystemExit(0)):
            with self.assertRaises(SystemExit):
                claude_mover.main()

    def test_resume_no_stale_artifacts(self):
        """--resume with nothing to clean up: logs 'Nothing to clean up'."""
        with tempfile.TemporaryDirectory() as tmp:
            projects_dir = Path(tmp) / "projects"
            projects_dir.mkdir()
            with patch("sys.argv", ["claude-mover", r"D:\workspace\src", r"D:\workspace\tgt", "--resume"]), \
                 patch("claude_mover.setup_logging", return_value=Path(r"C:\fake.log")), \
                 patch.object(claude_mover, "PROJECTS_DIR", projects_dir), \
                 patch("claude_mover._read_checkpoint", return_value=None), \
                 patch("claude_mover.migrate", return_value=self._SUMMARY), \
                 patch("claude_mover.print_summary"), \
                 patch("claude_mover.logging.info") as mock_log:
                claude_mover.main()
        logged = " ".join(str(c) for c in mock_log.call_args_list)
        self.assertIn("Nothing to clean up", logged)

    def test_resume_removes_stale_ctx(self):
        """--resume with stale target context: removes it."""
        with tempfile.TemporaryDirectory() as tmp:
            projects_dir = Path(tmp) / "projects"
            target_encoded = encode_path(Path(r"D:\workspace\tgt"))
            stale_ctx = projects_dir / target_encoded
            stale_ctx.mkdir(parents=True)
            with patch("sys.argv", ["claude-mover", r"D:\workspace\src", r"D:\workspace\tgt", "--resume"]), \
                 patch("claude_mover.setup_logging", return_value=Path(r"C:\fake.log")), \
                 patch.object(claude_mover, "PROJECTS_DIR", projects_dir), \
                 patch("claude_mover._read_checkpoint", return_value=None), \
                 patch("claude_mover.migrate", return_value=self._SUMMARY), \
                 patch("claude_mover.print_summary"):
                claude_mover.main()
            self.assertFalse(stale_ctx.exists())

    def test_resume_warns_on_checkpoint_target_mismatch(self):
        """--resume: logs a warning when checkpoint target differs from CLI target."""
        cp = {"target": r"D:\workspace\completely-different"}
        with patch("sys.argv", ["claude-mover", r"D:\workspace\src", r"D:\workspace\tgt", "--resume"]), \
             patch("claude_mover.setup_logging", return_value=Path(r"C:\fake.log")), \
             patch("claude_mover._read_checkpoint", return_value=cp), \
             patch("claude_mover.migrate", return_value=self._SUMMARY), \
             patch("claude_mover.print_summary"), \
             patch("claude_mover.logging.warning") as mock_warn:
            claude_mover.main()
        warned = " ".join(str(c) for c in mock_warn.call_args_list)
        self.assertIn("different target", warned)


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    unittest.main()
