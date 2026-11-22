#!/usr/bin/env python3
"""
Reliability and edge-case test suite for dev-context:
1. Repository deleted during discovery loop.
2. Git command times out / subprocess exits with error.
3. Task deleted while an agent references its ID.
4. Subprocess handling when git is not available or corrupt .git directory.
"""

import os
import sys
import json
import shutil
import tempfile
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dev_context import (
    is_git_repo,
    find_git_repos,
    get_git_info,
    scan_repositories,
    get_resume_context,
    cmd_start,
    cmd_done,
    cmd_block,
    cmd_rm,
    handle_mcp_tool_call,
    change_task_state,
)
import dev_context_mcp
from dev_context_mcp import get_recent_changes, get_resume_handoff


def _create_mock_repo(path, commit_msg="Initial commit"):
    """Helper to create a minimal valid git repository."""
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init", "-q", path], check=True)
    subprocess.run(
        ["git", "-C", path, "-c", "user.name=Test", "-c", "user.email=t@e.co", "commit", "-q", "--allow-empty", "-m", commit_msg],
        check=True,
    )


class TestRepoDeletedDuringDiscovery(unittest.TestCase):
    """Edge cases where repositories are deleted during discovery or scan."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="dc_del_test_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_repo_deleted_before_get_git_info(self):
        """Repository exists during find_git_repos but is deleted before get_git_info."""
        repo1 = os.path.join(self.temp_dir, "repo1")
        repo2 = os.path.join(self.temp_dir, "repo2")
        _create_mock_repo(repo1)
        _create_mock_repo(repo2)

        found = find_git_repos(self.temp_dir)
        self.assertIn(repo1, found)
        self.assertIn(repo2, found)

        # Delete repo1 before inspecting
        shutil.rmtree(repo1, ignore_errors=True)

        info1 = get_git_info(repo1)
        self.assertIsNone(info1, "Deleted repo path must return None from get_git_info")

        info2 = get_git_info(repo2)
        self.assertIsNotNone(info2, "Existing repo path must return valid dict")
        self.assertEqual(info2["subject"], "Initial commit")

    def test_repo_deleted_during_scan_repositories(self):
        """Repository deleted dynamically while parallel scan runs."""
        repo_a = os.path.join(self.temp_dir, "repo_a")
        repo_b = os.path.join(self.temp_dir, "repo_b")
        repo_c = os.path.join(self.temp_dir, "repo_c")
        _create_mock_repo(repo_a)
        _create_mock_repo(repo_b)
        _create_mock_repo(repo_c)

        original_get_git_info = get_git_info

        def side_effect(path, timeout=5):
            # When repo_b is queried, delete it from disk
            if "repo_b" in path and os.path.exists(path):
                shutil.rmtree(path, ignore_errors=True)
            return original_get_git_info(path, timeout)

        with patch("dev_context_bin.get_git_info", side_effect=side_effect):
            results = scan_repositories(self.temp_dir)

        found_names = [name for name, _ in results]
        self.assertIn("repo_a", found_names)
        self.assertIn("repo_c", found_names)
        # repo_b was deleted mid-scan, so it should be safely excluded without crash
        self.assertNotIn("repo_b", found_names)

    def test_nested_repo_deleted(self):
        """Deeply nested repo deleted during directory walk."""
        nested = os.path.join(self.temp_dir, "org", "team", "repo_nested")
        _create_mock_repo(nested)

        shutil.rmtree(nested, ignore_errors=True)
        results = scan_repositories(self.temp_dir, max_depth=3)
        self.assertEqual(len(results), 0)


class TestGitTimeoutAndSubprocessErrors(unittest.TestCase):
    """Resilience against git command hangs, timeouts, and non-zero exit codes."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="dc_timeout_test_")
        self.repo_path = os.path.join(self.temp_dir, "target_repo")
        _create_mock_repo(self.repo_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_git_info_timeout_handled(self):
        """git command hangs and raises TimeoutExpired in get_git_info."""
        with patch("subprocess.check_output", side_effect=subprocess.TimeoutExpired(cmd=["git", "status"], timeout=5)):
            info = get_git_info(self.repo_path, timeout=5)
            self.assertIsNone(info, "Timeout in get_git_info must be caught and return None")

    def test_scan_repositories_resilience_to_hanging_repo(self):
        """scan_repositories handles one hanging repo without failing others."""
        repo1 = os.path.join(self.temp_dir, "r1")
        repo2 = os.path.join(self.temp_dir, "r2")
        repo3 = os.path.join(self.temp_dir, "r3")
        _create_mock_repo(repo1)
        _create_mock_repo(repo2)
        _create_mock_repo(repo3)

        real_check_output = subprocess.check_output

        def selective_timeout(cmd, *args, **kwargs):
            if any("r2" in str(arg) for arg in cmd):
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=5)
            return real_check_output(cmd, *args, **kwargs)

        with patch("subprocess.check_output", side_effect=selective_timeout):
            results = scan_repositories(self.temp_dir)

        found_names = [name for name, _ in results]
        self.assertIn("r1", found_names)
        self.assertIn("r3", found_names)
        self.assertNotIn("r2", found_names)

    def test_subprocess_called_process_error(self):
        """git command exits with return code 128 (e.g. fatal git error)."""
        err = subprocess.CalledProcessError(returncode=128, cmd=["git", "log"], output=b"", stderr=b"fatal: bad revision")
        with patch("subprocess.check_output", side_effect=err):
            # get_git_info should recover with fallback or None
            info = get_git_info(self.repo_path)
            # Either None or safe fallback with empty subject
            if info is not None:
                self.assertEqual(info.get("subject", ""), "")

    def test_get_recent_changes_timeout_safe(self):
        """get_recent_changes returns safe default data when git commands timeout."""
        with patch("subprocess.check_output", side_effect=subprocess.TimeoutExpired(cmd=["git", "diff"], timeout=5)):
            resp = get_recent_changes(project=self.repo_path, limit_commits=5)
            self.assertFalse(resp.get("result", {}).get("isError", False))
            data = json.loads(resp["result"]["content"][0]["text"])
            self.assertEqual(data.get("recent_commits"), [])
            self.assertEqual(data.get("modified_files"), [])

    def test_get_resume_handoff_with_git_timeout(self):
        """get_resume_handoff succeeds even if git log/diff encounters a timeout."""
        session_file = os.path.join(self.temp_dir, "sessions.json")
        dev_context_mcp.update_session(project=self.repo_path, objective="Test objective", cwd=self.repo_path, session_file=session_file)
        with patch("subprocess.check_output", side_effect=subprocess.TimeoutExpired(cmd=["git", "diff"], timeout=5)):
            handoff = get_resume_handoff(project=self.repo_path, format="markdown", cwd=self.repo_path, session_file=session_file)
            self.assertFalse(handoff.get("result", {}).get("isError", False))
            content = handoff["result"]["content"][0]["text"]
            self.assertIn("Session Handoff", content)
            self.assertIn("Test objective", content)


class TestTaskDeletedWhileReferencedByID(unittest.TestCase):
    """Handling tasks deleted concurrently or while referenced by agents."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="dc_task_edge_")
        self.roadmap_path = os.path.join(self.temp_dir, "ROADMAP.md")
        with open(self.roadmap_path, "w", encoding="utf-8") as f:
            f.write(
                "# Roadmap\n\n"
                "## Active Sprint\n"
                "- [ ] Fix database connection leak <!-- id:a101 -->\n"
                "- [ ] Add integration benchmarks <!-- id:b202 -->\n"
                "- [ ] Refactor API routing <!-- id:c303 -->\n"
            )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_referencing_already_deleted_task_cli(self):
        """Attempting to start/done/block a deleted task returns False cleanly."""
        # 1. Delete task b202
        deleted = cmd_rm("b202", file_path=self.roadmap_path, quiet=True)
        self.assertTrue(deleted)

        # 2. Subsequent operations on b202 must return False and not throw
        res_done = cmd_done("b202", file_path=self.roadmap_path, quiet=True)
        self.assertFalse(res_done)

        res_start = cmd_start("b202", file_path=self.roadmap_path, quiet=True)
        self.assertFalse(res_start)

        res_block = cmd_block("b202", file_path=self.roadmap_path, quiet=True)
        self.assertFalse(res_block)

        # Remaining tasks must be intact
        with open(self.roadmap_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("a101", content)
        self.assertNotIn("b202", content)
        self.assertIn("c303", content)

    def test_mcp_mark_task_status_deleted_id(self):
        """MCP mark_task_status returns error result when ID no longer exists."""
        # Delete task a101 first
        cmd_rm("a101", file_path=self.roadmap_path, quiet=True)

        resp = handle_mcp_tool_call(
            req_id="req-edge-1",
            tool_name="mark_task_status",
            tool_args={"id": "a101", "status": "done"},
            roadmap_file=self.roadmap_path,
        )
        self.assertTrue(resp.get("result", {}).get("isError", False))
        error_msg = resp["result"]["content"][0]["text"]
        self.assertIn("not found", error_msg.lower())

    def test_roadmap_file_deleted_mid_operation(self):
        """Operations handle roadmap file disappearing between discovery and edit."""
        os.remove(self.roadmap_path)
        success = change_task_state("a101", new_state="completed", file_path=self.roadmap_path, quiet=True)
        self.assertFalse(success)

        resp = handle_mcp_tool_call(
            req_id="req-edge-2",
            tool_name="mark_task_status",
            tool_args={"id": "a101", "status": "start"},
            roadmap_file=self.roadmap_path,
        )
        self.assertTrue(resp.get("result", {}).get("isError", False))


class TestGitUnavailableOrCorruptGitDir(unittest.TestCase):
    """Behavior when git binary is missing or .git directory is corrupt."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="dc_corrupt_test_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_git_binary_not_found_oserror(self):
        """git binary is missing from PATH (FileNotFoundError)."""
        repo_path = os.path.join(self.temp_dir, "normal_repo")
        _create_mock_repo(repo_path)

        fnf_err = FileNotFoundError(2, "No such file or directory: 'git'")
        with patch("subprocess.check_output", side_effect=fnf_err):
            info = get_git_info(repo_path)
            self.assertIsNone(info, "Missing git binary must return None from get_git_info")

            resp = get_recent_changes(project=repo_path)
            self.assertFalse(resp.get("result", {}).get("isError", False))
            data = json.loads(resp["result"]["content"][0]["text"])
            self.assertEqual(data.get("recent_commits"), [])
            self.assertEqual(data.get("modified_files"), [])

    def test_corrupt_dot_git_file(self):
        """Corrupt .git file that is not a directory and contains garbage."""
        corrupt_dir = os.path.join(self.temp_dir, "corrupt_gitfile")
        os.makedirs(corrupt_dir)
        git_file = os.path.join(corrupt_dir, ".git")
        with open(git_file, "wb") as f:
            f.write(b"\x00\xff\xfe\x01\x02\x03BINARY_TRASH")

        self.assertFalse(is_git_repo(corrupt_dir), "Garbage .git file must not be recognized as git repo")

    def test_corrupt_dot_git_dir_unreadable_head(self):
        """A .git directory where HEAD is corrupted."""
        corrupt_repo = os.path.join(self.temp_dir, "bad_head_repo")
        os.makedirs(os.path.join(corrupt_repo, ".git"), exist_ok=True)
        head_path = os.path.join(corrupt_repo, ".git", "HEAD")
        with open(head_path, "w") as f:
            f.write("corrupted-not-a-ref")

        # is_git_repo returns True because .git is a directory
        self.assertTrue(is_git_repo(corrupt_repo))

        # get_git_info should not crash even if git returns error code 128
        info = get_git_info(corrupt_repo)
        # It handles subprocess errors and either returns None or safe dictionary
        if info is not None:
            self.assertIn("branch", info)

    def test_git_fatal_error_exit_code_128(self):
        """git exits with fatal error code 128 (e.g. invalid repository object)."""
        repo_path = os.path.join(self.temp_dir, "fatal_repo")
        _create_mock_repo(repo_path)

        called_err = subprocess.CalledProcessError(
            returncode=128,
            cmd=["git", "branch", "--show-current"],
            output=b"",
            stderr=b"fatal: not a git repository (or any of the parent directories): .git"
        )
        with patch("subprocess.check_output", side_effect=called_err):
            info = get_git_info(repo_path)
            # Must not crash
            if info is not None:
                self.assertEqual(info.get("branch"), "HEAD")


if __name__ == "__main__":
    unittest.main()
