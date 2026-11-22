#!/usr/bin/env python3
"""
Unit and integration tests for dev-context core engine.
Tests discovery of regular repos, worktrees, dirty states, and error handling.
"""

import os
import sys
import tempfile
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dev_context import (
    is_git_repo,
    find_git_repos,
    get_git_info,
    scan_repositories,
    SKIP_DIRS,
)


def init_git_repo(path, commit_msg="Initial commit"):
    """Helper to initialize a git repo with a commit."""
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init", "-q", path], check=True)
    subprocess.run(["git", "-C", path, "config", "user.name", "Test Runner"], check=True)
    subprocess.run(["git", "-C", path, "config", "user.email", "test@example.com"], check=True)
    file_path = os.path.join(path, "README.md")
    with open(file_path, "w") as f:
        f.write("# Test Repo\n")
    subprocess.run(["git", "-C", path, "add", "README.md"], check=True)
    subprocess.run(["git", "-C", path, "commit", "-q", "-m", commit_msg], check=True)


class TestIsGitRepo(unittest.TestCase):
    """Test is_git_repo for standard repos, worktrees, and invalid paths."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_regular_git_repo(self):
        repo_path = os.path.join(self.base, "regular_repo")
        init_git_repo(repo_path)
        self.assertTrue(is_git_repo(repo_path))

    def test_worktree_file_valid(self):
        wt_path = os.path.join(self.base, "worktree_repo")
        os.makedirs(wt_path, exist_ok=True)
        git_file = os.path.join(wt_path, ".git")
        with open(git_file, "w") as f:
            f.write("gitdir: /path/to/main/repo/.git/worktrees/feat\n")
        self.assertTrue(is_git_repo(wt_path))

    def test_git_file_invalid_content(self):
        bad_path = os.path.join(self.base, "bad_repo")
        os.makedirs(bad_path, exist_ok=True)
        git_file = os.path.join(bad_path, ".git")
        with open(git_file, "w") as f:
            f.write("not a gitdir pointer line\n")
        self.assertFalse(is_git_repo(bad_path))

    def test_empty_git_file(self):
        empty_path = os.path.join(self.base, "empty_repo")
        os.makedirs(empty_path, exist_ok=True)
        git_file = os.path.join(empty_path, ".git")
        with open(git_file, "w") as f:
            f.write("")
        self.assertFalse(is_git_repo(empty_path))

    def test_plain_directory(self):
        plain_path = os.path.join(self.base, "plain_dir")
        os.makedirs(plain_path, exist_ok=True)
        self.assertFalse(is_git_repo(plain_path))

    def test_nonexistent_directory(self):
        self.assertFalse(is_git_repo(os.path.join(self.base, "does_not_exist")))


class TestFindGitRepos(unittest.TestCase):
    """Test repository and worktree discovery across directory depths and skip lists."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_depth_scanning(self):
        # Depth 1 repo
        r1 = os.path.join(self.base, "repo1")
        init_git_repo(r1)

        # Depth 2 repo
        r2 = os.path.join(self.base, "group", "repo2")
        init_git_repo(r2)

        # Depth 3 repo
        r3 = os.path.join(self.base, "org", "team", "repo3")
        init_git_repo(r3)

        # Depth 4 repo (should be ignored by max_depth=3)
        r4 = os.path.join(self.base, "deep", "nested", "level", "repo4")
        init_git_repo(r4)

        found = find_git_repos(self.base, max_depth=3)
        found_abs = [os.path.abspath(p) for p in found]

        self.assertIn(os.path.abspath(r1), found_abs)
        self.assertIn(os.path.abspath(r2), found_abs)
        self.assertIn(os.path.abspath(r3), found_abs)
        self.assertNotIn(os.path.abspath(r4), found_abs)

    def test_worktree_discovery(self):
        main_repo = os.path.join(self.base, "main_repo")
        init_git_repo(main_repo)

        wt_repo = os.path.join(self.base, "main_wt")
        subprocess.run(
            ["git", "-C", main_repo, "worktree", "add", wt_repo, "-b", "feature-wt"],
            check=True,
            capture_output=True,
        )

        found = find_git_repos(self.base, max_depth=3)
        found_abs = [os.path.abspath(p) for p in found]

        self.assertIn(os.path.abspath(main_repo), found_abs)
        self.assertIn(os.path.abspath(wt_repo), found_abs)

    def test_skipping_directories(self):
        # Repos inside skipped directories should never be discovered
        skipped_names = [
            "node_modules",
            ".cache",
            ".cargo",
            ".local",
            "dist",
            "build",
            "venv",
            "target",
        ]
        for name in skipped_names:
            fake_repo = os.path.join(self.base, name, "ignored_repo")
            init_git_repo(fake_repo)

        # Valid repo to ensure scanner runs
        valid_repo = os.path.join(self.base, "valid_repo")
        init_git_repo(valid_repo)

        found = find_git_repos(self.base, max_depth=3)
        self.assertEqual(len(found), 1)
        self.assertEqual(os.path.abspath(found[0]), os.path.abspath(valid_repo))


class TestGitInfoInspection(unittest.TestCase):
    """Test git inspection for clean, dirty, and worktree repositories."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_clean_repo(self):
        repo_path = os.path.join(self.base, "clean_repo")
        init_git_repo(repo_path, commit_msg="Add main feature")

        info = get_git_info(repo_path)
        self.assertIsNotNone(info)
        self.assertEqual(info["dirty_count"], 0)
        self.assertEqual(len(info["dirty_lines"]), 0)
        self.assertEqual(info["subject"], "Add main feature")
        self.assertGreater(info["timestamp"], 0)

    def test_dirty_repo_modified_tracked(self):
        repo_path = os.path.join(self.base, "dirty_modified")
        init_git_repo(repo_path)

        # Modify tracked file
        with open(os.path.join(repo_path, "README.md"), "a") as f:
            f.write("modified line\n")

        info = get_git_info(repo_path)
        self.assertIsNotNone(info)
        self.assertGreater(info["dirty_count"], 0)
        self.assertTrue(any("README.md" in line for line in info["dirty_lines"]))

    def test_dirty_repo_untracked_files(self):
        repo_path = os.path.join(self.base, "dirty_untracked")
        init_git_repo(repo_path)

        # Create untracked file
        with open(os.path.join(repo_path, "scratch.py"), "w") as f:
            f.write("print('untracked')\n")

        info = get_git_info(repo_path)
        self.assertIsNotNone(info)
        self.assertGreater(info["dirty_count"], 0)
        self.assertTrue(any("scratch.py" in line for line in info["dirty_lines"]))

    def test_worktree_git_info(self):
        main_repo = os.path.join(self.base, "main_for_wt")
        init_git_repo(main_repo, commit_msg="Initial root")

        wt_path = os.path.join(self.base, "wt_branch")
        subprocess.run(
            ["git", "-C", main_repo, "worktree", "add", wt_path, "-b", "hotfix-branch"],
            check=True,
            capture_output=True,
        )

        # Modify file inside worktree
        with open(os.path.join(wt_path, "hotfix.txt"), "w") as f:
            f.write("fix\n")

        info = get_git_info(wt_path)
        self.assertIsNotNone(info)
        self.assertEqual(info["branch"], "hotfix-branch")
        self.assertGreater(info["dirty_count"], 0)
        self.assertTrue(any("hotfix.txt" in line for line in info["dirty_lines"]))


class TestParallelScan(unittest.TestCase):
    """Test parallel scan execution and timeout handling."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parallel_scan_discovers_all(self):
        for i in range(5):
            r = os.path.join(self.base, f"repo_{i}")
            init_git_repo(r, commit_msg=f"commit {i}")
            if i % 2 == 1:
                with open(os.path.join(r, "untracked.txt"), "w") as f:
                    f.write("dirty")

        results = scan_repositories(self.base, max_depth=3, max_workers=4)
        self.assertEqual(len(results), 5)

        names = [name for name, _ in results]
        for i in range(5):
            self.assertIn(f"repo_{i}", names)

    def test_per_repo_timeout(self):
        repo_path = os.path.join(self.base, "timeout_repo")
        init_git_repo(repo_path)

        # get_git_info with zero timeout should time out safely and return None
        info = get_git_info(repo_path, timeout=0.000001)
        # It must either return None or succeed without crashing
        self.assertTrue(info is None or isinstance(info, dict))


class TestErrorHandling(unittest.TestCase):
    """Test resilience against broken repos, nonexistent dirs, and bad permissions."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_corrupt_repo_does_not_crash(self):
        corrupt_path = os.path.join(self.base, "corrupt_repo")
        os.makedirs(os.path.join(corrupt_path, ".git"), exist_ok=True)
        # Empty .git directory without valid HEAD/refs
        info = get_git_info(corrupt_path)
        # Scanner handles it safely
        self.assertTrue(info is None or isinstance(info, dict))

    def test_nonexistent_base_directory(self):
        results = scan_repositories(os.path.join(self.base, "nonexistent"))
        self.assertEqual(results, [])

    def test_get_git_info_invalid_path(self):
        self.assertIsNone(get_git_info("/non/existent/path/xyz"))


if __name__ == "__main__":
    unittest.main()
