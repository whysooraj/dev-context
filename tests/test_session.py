#!/usr/bin/env python3
"""
Unit and integration tests for dev-context Session Memory Engine.
Tests session state storage, serialization, goal setting, footprint calculation,
auto-recording, dashboard continuity cards, CLI commands, and error resilience.
"""

import os
import sys
import json
import time
import tempfile
import unittest
import subprocess
import re
from io import StringIO
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def strip_ansi(text):
    return re.sub(r'\x1b\[[0-9;]*m', '', text)

from dev_context import (
    get_session_file_path,
    load_sessions,
    save_sessions,
    calculate_footprint,
    record_session,
    set_active_goal,
    get_last_session,
    format_rel_time,
    cmd_goal,
    cmd_session,
    print_dashboard,
    find_repo_root,
)


def init_git_repo(path, commit_msg="Initial commit"):
    """Helper to initialize a git repo with an initial commit."""
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init", "-q", path], check=True)
    subprocess.run(["git", "-C", path, "config", "user.name", "Test Runner"], check=True)
    subprocess.run(["git", "-C", path, "config", "user.email", "test@example.com"], check=True)
    file_path = os.path.join(path, "README.md")
    with open(file_path, "w") as f:
        f.write("# Test Repo\nLine 1\nLine 2\n")
    subprocess.run(["git", "-C", path, "add", "README.md"], check=True)
    subprocess.run(["git", "-C", path, "commit", "-q", "-m", commit_msg], check=True)


class TestSessionStore(unittest.TestCase):
    """Test session file location, serialization, and error recovery."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.session_file = os.path.join(self.temp_dir.name, "sessions.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_default_session_path(self):
        with patch.dict(os.environ, {}, clear=True):
            path = get_session_file_path()
            self.assertTrue(
                path.endswith("sessions.json") or path.endswith(".dev-context-sessions.json")
            )

    def test_env_var_override(self):
        custom = "/tmp/custom-sessions-test.json"
        with patch.dict(os.environ, {"DEV_CONTEXT_SESSION_FILE": custom}):
            self.assertEqual(get_session_file_path(), custom)

    def test_fallback_when_config_unwritable(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("os.makedirs", side_effect=PermissionError("Mock Permission Denied")):
                fallback = get_session_file_path()
                expected = os.path.expanduser("~/.dev-context-sessions.json")
                self.assertEqual(fallback, expected)

    def test_save_and_load_roundtrip(self):
        data = {
            "last_project": "/path/to/my-project",
            "projects": {
                "/path/to/my-project": {
                    "project_name": "my-project",
                    "project_path": "/path/to/my-project",
                    "branch": "feature/auth",
                    "last_active_timestamp": 1732200000.0,
                    "goal": "Implement JWT rotation",
                    "footprint": "+42 -8 across 3 files",
                    "recent_files": ["auth.py", "tokens.py", "test_auth.py"],
                    "history": [],
                }
            },
            "history": [],
        }
        saved = save_sessions(data, file_path=self.session_file)
        self.assertTrue(saved)
        self.assertTrue(os.path.exists(self.session_file))

        loaded = load_sessions(file_path=self.session_file)
        self.assertEqual(loaded["last_project"], "/path/to/my-project")
        proj = loaded["projects"]["/path/to/my-project"]
        self.assertEqual(proj["project_name"], "my-project")
        self.assertEqual(proj["branch"], "feature/auth")
        self.assertEqual(proj["goal"], "Implement JWT rotation")
        self.assertEqual(proj["footprint"], "+42 -8 across 3 files")
        self.assertEqual(proj["recent_files"], ["auth.py", "tokens.py", "test_auth.py"])

    def test_load_corrupted_json(self):
        with open(self.session_file, "w") as f:
            f.write("{this is invalid json garbage!!!")

        loaded = load_sessions(file_path=self.session_file)
        self.assertEqual(loaded["last_project"], None)
        self.assertEqual(loaded["projects"], {})
        self.assertEqual(loaded["history"], [])

    def test_load_non_dict_json(self):
        with open(self.session_file, "w") as f:
            f.write("[\"not\", \"a\", \"dict\"]")

        loaded = load_sessions(file_path=self.session_file)
        self.assertEqual(loaded["last_project"], None)
        self.assertEqual(loaded["projects"], {})

    def test_load_nonexistent_file(self):
        missing_file = os.path.join(self.temp_dir.name, "does_not_exist.json")
        loaded = load_sessions(file_path=missing_file)
        self.assertEqual(loaded["last_project"], None)
        self.assertEqual(loaded["projects"], {})


class TestFootprintCalculation(unittest.TestCase):
    """Test dirty diff statistics and recent files list."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = os.path.realpath(os.path.join(self.temp_dir.name, "test_repo"))
        init_git_repo(self.repo_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_clean_repo(self):
        footprint, recent = calculate_footprint(self.repo_dir)
        self.assertEqual(footprint, "clean")
        self.assertEqual(recent, [])

    def test_unstaged_modifications(self):
        readme = os.path.join(self.repo_dir, "README.md")
        with open(readme, "a") as f:
            f.write("Line 3 added\nLine 4 added\n")

        footprint, recent = calculate_footprint(self.repo_dir)
        self.assertIn("README.md", recent)
        self.assertTrue(footprint.startswith("+2 -0 across 1 file"))

    def test_staged_modifications(self):
        new_file = os.path.join(self.repo_dir, "staged.txt")
        with open(new_file, "w") as f:
            f.write("New staged file content\n")
        subprocess.run(["git", "-C", self.repo_dir, "add", "staged.txt"], check=True)

        footprint, recent = calculate_footprint(self.repo_dir)
        self.assertIn("staged.txt", recent)
        self.assertTrue("+1 -0 across 1 file" in footprint)

    def test_untracked_files(self):
        untracked = os.path.join(self.repo_dir, "untracked.txt")
        with open(untracked, "w") as f:
            f.write("Untracked data\n")

        footprint, recent = calculate_footprint(self.repo_dir)
        self.assertIn("untracked.txt", recent)
        self.assertEqual(footprint, "+0 -0 across 1 file")

    def test_multiple_files_staged_and_unstaged(self):
        # 1. Unstaged in README.md
        with open(os.path.join(self.repo_dir, "README.md"), "a") as f:
            f.write("Another line\n")

        # 2. Staged in staged.txt
        with open(os.path.join(self.repo_dir, "staged.txt"), "w") as f:
            f.write("Staged line 1\nStaged line 2\n")
        subprocess.run(["git", "-C", self.repo_dir, "add", "staged.txt"], check=True)

        # 3. Untracked file
        with open(os.path.join(self.repo_dir, "extra.txt"), "w") as f:
            f.write("Extra\n")

        footprint, recent = calculate_footprint(self.repo_dir)
        self.assertEqual(len(recent), 3)
        self.assertIn("across 3 files", footprint)

    def test_non_git_path(self):
        plain_dir = os.path.join(self.temp_dir.name, "plain_folder")
        os.makedirs(plain_dir, exist_ok=True)
        footprint, recent = calculate_footprint(plain_dir)
        self.assertEqual(footprint, "clean")
        self.assertEqual(recent, [])


class TestGoalSettingAndRecording(unittest.TestCase):
    """Test setting goals, session recording, and history tracking."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = os.path.realpath(os.path.join(self.temp_dir.name, "my_project"))
        init_git_repo(self.repo_dir)
        self.session_file = os.path.join(self.temp_dir.name, "sessions.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_set_active_goal(self):
        session = set_active_goal(self.repo_dir, "Refactor database models", file_path=self.session_file)
        self.assertEqual(session["goal"], "Refactor database models")
        self.assertEqual(session["project_name"], "my_project")
        self.assertEqual(session["project_path"], os.path.abspath(self.repo_dir))
        self.assertGreater(session["last_active_timestamp"], 0)

        # Verify persisted
        loaded = get_last_session(self.repo_dir, file_path=self.session_file)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["goal"], "Refactor database models")

    def test_update_goal_preserves_other_state(self):
        set_active_goal(self.repo_dir, "Goal 1", file_path=self.session_file)
        time.sleep(0.01)
        updated = set_active_goal(self.repo_dir, "Goal 2", file_path=self.session_file)
        self.assertEqual(updated["goal"], "Goal 2")

    def test_record_session_preserves_existing_goal(self):
        set_active_goal(self.repo_dir, "Preserve this goal", file_path=self.session_file)

        # Simulate work / file edit
        with open(os.path.join(self.repo_dir, "test.txt"), "w") as f:
            f.write("dirty change\n")

        # Auto-record without specifying new goal
        session = record_session(self.repo_dir, goal=None, file_path=self.session_file)
        self.assertEqual(session["goal"], "Preserve this goal")
        self.assertIn("test.txt", session["recent_files"])

    def test_per_project_and_global_history(self):
        set_active_goal(self.repo_dir, "Step 1", file_path=self.session_file)
        set_active_goal(self.repo_dir, "Step 2", file_path=self.session_file)

        data = load_sessions(file_path=self.session_file)
        proj = data["projects"][os.path.abspath(self.repo_dir)]
        self.assertGreaterEqual(len(proj["history"]), 2)
        self.assertGreaterEqual(len(data["history"]), 2)
        self.assertEqual(data["last_project"], os.path.abspath(self.repo_dir))

    def test_get_last_session_per_repo_and_global(self):
        repo1 = os.path.join(self.temp_dir.name, "repo1")
        repo2 = os.path.join(self.temp_dir.name, "repo2")
        init_git_repo(repo1)
        init_git_repo(repo2)

        set_active_goal(repo1, "Repo 1 Goal", file_path=self.session_file)
        set_active_goal(repo2, "Repo 2 Goal", file_path=self.session_file)

        # Query specific repo
        s1 = get_last_session(repo1, file_path=self.session_file)
        self.assertEqual(s1["goal"], "Repo 1 Goal")

        # Query global last (should be repo2)
        sg = get_last_session(None, file_path=self.session_file)
        self.assertEqual(sg["goal"], "Repo 2 Goal")


class TestAutoRecordingAndDashboard(unittest.TestCase):
    """Test dashboard integration, continuity card, and relative time."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = os.path.realpath(os.path.join(self.temp_dir.name, "dashboard_repo"))
        init_git_repo(self.repo_dir)
        self.session_file = os.path.join(self.temp_dir.name, "sessions.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_format_rel_time(self):
        now = time.time()
        self.assertEqual(format_rel_time(now - 10), "just now")
        self.assertEqual(format_rel_time(now - 120), "2 minutes ago")
        self.assertEqual(format_rel_time(now - 7200), "2 hours ago")
        self.assertEqual(format_rel_time(now - 86400 * 3), "3 days ago")
        self.assertEqual(format_rel_time(0), "never")

    def test_dashboard_continuity_card_with_goal(self):
        set_active_goal(self.repo_dir, "Implement Task 2", file_path=self.session_file)

        orig_cwd = os.getcwd()
        try:
            os.chdir(self.repo_dir)
            buf = StringIO()
            with patch("sys.stdout", buf):
                print_dashboard(session_file=self.session_file)
            output = buf.getvalue()
        finally:
            os.chdir(orig_cwd)

        clean = strip_ansi(output)
        self.assertIn("DEV FLIGHT CONTEXT", clean)
        self.assertIn("SESSION", clean)
        self.assertIn("dashboard_repo", clean)
        self.assertIn("Goal: Implement Task 2", clean)
        self.assertIn("Changes:", clean)

    def test_dashboard_continuity_card_no_goal_set(self):
        # Record session with no goal
        record_session(self.repo_dir, goal=None, file_path=self.session_file)

        orig_cwd = os.getcwd()
        try:
            os.chdir(self.repo_dir)
            buf = StringIO()
            with patch("sys.stdout", buf):
                print_dashboard(session_file=self.session_file)
            output = buf.getvalue()
        finally:
            os.chdir(orig_cwd)

        clean = strip_ansi(output)
        self.assertIn("DEV FLIGHT CONTEXT", clean)
        self.assertIn("SESSION", clean)
        self.assertIn('Goal: No goal set. Run: dc goal "..."', clean)

    def test_dashboard_auto_records_repo(self):
        orig_cwd = os.getcwd()
        try:
            os.chdir(self.repo_dir)
            buf = StringIO()
            with patch("sys.stdout", buf):
                print_dashboard(session_file=self.session_file)
        finally:
            os.chdir(orig_cwd)

        # Check session store now has this repo recorded
        data = load_sessions(file_path=self.session_file)
        self.assertIn(os.path.abspath(self.repo_dir), data["projects"])

    def test_dashboard_outside_git_shows_previous_project(self):
        # Record session for repo_dir
        set_active_goal(self.repo_dir, "Previous Work", file_path=self.session_file)

        # Run dashboard in a non-git directory
        plain_dir = os.path.join(self.temp_dir.name, "plain_folder")
        os.makedirs(plain_dir, exist_ok=True)

        orig_cwd = os.getcwd()
        try:
            os.chdir(plain_dir)
            buf = StringIO()
            with patch("sys.stdout", buf):
                print_dashboard(session_file=self.session_file)
            output = buf.getvalue()
        finally:
            os.chdir(orig_cwd)

        clean = strip_ansi(output)
        self.assertIn("DEV FLIGHT CONTEXT", clean)
        self.assertIn("SESSION", clean)
        self.assertIn("dashboard_repo", clean)
        self.assertIn("Goal: Previous Work", clean)


class TestCLICommands(unittest.TestCase):
    """Test dc goal and dc session CLI commands."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = os.path.realpath(os.path.join(self.temp_dir.name, "cli_repo"))
        init_git_repo(self.repo_dir)
        self.session_file = os.path.join(self.temp_dir.name, "sessions.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cmd_goal_sets_goal(self):
        orig_cwd = os.getcwd()
        try:
            os.chdir(self.repo_dir)
            buf = StringIO()
            with patch("sys.stdout", buf):
                cmd_goal("Build session manager", file_path=self.session_file)
            output = buf.getvalue()
        finally:
            os.chdir(orig_cwd)

        self.assertIn("Active goal set for cli_repo", output)
        self.assertIn("Build session manager", output)

        session = get_last_session(self.repo_dir, file_path=self.session_file)
        self.assertEqual(session["goal"], "Build session manager")

    def test_cmd_goal_queries_goal(self):
        set_active_goal(self.repo_dir, "Existing Goal", file_path=self.session_file)

        orig_cwd = os.getcwd()
        try:
            os.chdir(self.repo_dir)
            buf = StringIO()
            with patch("sys.stdout", buf):
                cmd_goal(None, file_path=self.session_file)
            output = buf.getvalue()
        finally:
            os.chdir(orig_cwd)

        self.assertIn("Active goal for cli_repo:", output)
        self.assertIn("Existing Goal", output)

    def test_cmd_session_display(self):
        set_active_goal(self.repo_dir, "Fix session bug", file_path=self.session_file)

        orig_cwd = os.getcwd()
        try:
            os.chdir(self.repo_dir)
            buf = StringIO()
            with patch("sys.stdout", buf):
                cmd_session(file_path=self.session_file)
            output = buf.getvalue()
        finally:
            os.chdir(orig_cwd)

        self.assertIn("Session Details:", output)
        self.assertIn("cli_repo", output)
        self.assertIn("Fix session bug", output)
        self.assertIn("Footprint:", output)

    def test_cmd_session_empty(self):
        orig_cwd = os.getcwd()
        try:
            os.chdir(self.repo_dir)
            buf = StringIO()
            with patch("sys.stdout", buf):
                cmd_session(file_path=self.session_file)
            output = buf.getvalue()
        finally:
            os.chdir(orig_cwd)

        self.assertIn("No recorded sessions found.", output)


class TestErrorResilience(unittest.TestCase):
    """Test error conditions, git timeouts, and graceful fallbacks."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = os.path.realpath(os.path.join(self.temp_dir.name, "resilience_repo"))
        init_git_repo(self.repo_dir)
        self.session_file = os.path.join(self.temp_dir.name, "sessions.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_git_timeout_handling(self):
        with patch("subprocess.check_output", side_effect=subprocess.TimeoutExpired(cmd="git", timeout=5)):
            footprint, recent = calculate_footprint(self.repo_dir)
            self.assertEqual(footprint, "clean")
            self.assertEqual(recent, [])

    def test_git_missing_binary(self):
        with patch("subprocess.check_output", side_effect=FileNotFoundError("No git binary")):
            footprint, recent = calculate_footprint(self.repo_dir)
            self.assertEqual(footprint, "clean")
            self.assertEqual(recent, [])

    def test_find_repo_root(self):
        subdir = os.path.join(self.repo_dir, "a", "b", "c")
        os.makedirs(subdir, exist_ok=True)
        root = find_repo_root(subdir)
        self.assertEqual(os.path.abspath(root), os.path.abspath(self.repo_dir))

        plain = os.path.join(self.temp_dir.name, "plain_folder")
        os.makedirs(plain, exist_ok=True)
        self.assertIsNone(find_repo_root(plain))


if __name__ == "__main__":
    unittest.main()
