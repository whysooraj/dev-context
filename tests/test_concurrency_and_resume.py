#!/usr/bin/env python3
"""
Comprehensive tests for Phase 1 dev-context upgrade:
- Concurrency stress test: 10 threads concurrently updating session without data loss.
- Corrupted json recovery test: auto-recovers and backs up corrupted session files.
- `dc resume` output verification test (markdown and JSON).
- `dc inspect` test for inspecting workspace repositories.
- `dc goal` flags test (--next, --blocker, --last-step, --status).
"""

import os
import sys
import json
import time
import glob
import tempfile
import unittest
import threading
import subprocess
from io import StringIO
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dev_context import (
    load_sessions,
    save_sessions,
    update_session,
    record_session,
    set_active_goal,
    get_last_session,
    get_resume_context,
    cmd_resume,
    resolve_repo_path,
    get_repo_inspection,
    cmd_inspect,
    cmd_goal,
    session_file_lock,
)

import re

def strip_ansi(text):
    return re.sub(r'\x1b\[[0-9;]*m', '', text)


def init_git_repo(path, commit_msg="Initial commit"):
    """Helper to initialize a git repository with an initial commit."""
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init", "-q", path], check=True)
    subprocess.run(["git", "-C", path, "config", "user.name", "Test Runner"], check=True)
    subprocess.run(["git", "-C", path, "config", "user.email", "test@example.com"], check=True)
    file_path = os.path.join(path, "README.md")
    with open(file_path, "w") as f:
        f.write("# Test Repo\nLine 1\nLine 2\n")
    subprocess.run(["git", "-C", path, "add", "README.md"], check=True)
    subprocess.run(["git", "-C", path, "commit", "-q", "-m", commit_msg], check=True)


class TestSessionConcurrency(unittest.TestCase):
    """Concurrency stress tests for session memory engine."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = os.path.realpath(os.path.join(self.temp_dir.name, "concurrent_repo"))
        init_git_repo(self.repo_dir)
        self.session_file = os.path.join(self.temp_dir.name, "sessions.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_concurrent_updates_10_threads_no_data_loss(self):
        """Stress test: 10 threads concurrently updating session must preserve all updates."""
        # Initialize session
        update_session(
            self.repo_dir,
            objective="Base Concurrent Objective",
            file_path=self.session_file
        )

        num_threads = 10
        updates_per_thread = 5
        errors = []

        def worker(thread_idx):
            try:
                for i in range(updates_per_thread):
                    update_session(
                        self.repo_dir,
                        next_action=f"action_from_thread_{thread_idx}_step_{i}",
                        last_step=f"completed_step_{thread_idx}_{i}",
                        decisions=[{
                            "decision": f"decision_t{thread_idx}_i{i}",
                            "rationale": f"rationale for t{thread_idx} i{i}",
                            "rejected_alternatives": [f"alt_t{thread_idx}_i{i}"]
                        }],
                        files_changed={
                            f"file_t{thread_idx}.py": {
                                "why": f"Thread {thread_idx} work {i}",
                                "lines_added": i + 1,
                                "lines_deleted": 0
                            }
                        },
                        file_path=self.session_file
                    )
                    time.sleep(0.005)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Encountered errors during concurrent updates: {errors}")

        # Verify session file contents
        sessions = load_sessions(file_path=self.session_file)
        self.assertIn(os.path.abspath(self.repo_dir), sessions["projects"])

        proj = sessions["projects"][os.path.abspath(self.repo_dir)]
        self.assertEqual(proj["objective"], "Base Concurrent Objective")

        # Verify all 50 decisions are present without loss
        decisions = proj.get("decisions", [])
        total_expected = num_threads * updates_per_thread
        self.assertEqual(len(decisions), total_expected, f"Expected {total_expected} decisions, found {len(decisions)}")

        recorded_decision_names = {d["decision"] for d in decisions}
        for t in range(num_threads):
            for i in range(updates_per_thread):
                expected_name = f"decision_t{t}_i{i}"
                self.assertIn(expected_name, recorded_decision_names)

        # Verify files_changed has all 10 files
        files_changed = proj.get("files_changed", {})
        self.assertEqual(len(files_changed), num_threads)
        for t in range(num_threads):
            self.assertIn(f"file_t{t}.py", files_changed)

    def test_reentrant_lock(self):
        """Verify session_file_lock can be reentered within the same thread."""
        lock_path = f"{self.session_file}.lock"
        with session_file_lock(lock_path):
            with session_file_lock(lock_path):
                update_session(self.repo_dir, objective="Reentrant Test", file_path=self.session_file)

        session = get_last_session(self.repo_dir, file_path=self.session_file)
        self.assertEqual(session["objective"], "Reentrant Test")


class TestCorruptedJsonRecovery(unittest.TestCase):
    """Test auto-recovery and backup creation on corrupted session files."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.session_file = os.path.join(self.temp_dir.name, "sessions.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_corrupted_json_recovery_and_backup(self):
        """Corrupted JSON must be backed up to .corrupted.* and safe default returned."""
        corrupted_content = '{"projects": { unclosed invalid json'
        with open(self.session_file, "w", encoding="utf-8") as f:
            f.write(corrupted_content)

        # Attempt to load corrupted file
        data = load_sessions(file_path=self.session_file)
        self.assertEqual(data, {"last_project": None, "projects": {}, "history": []})

        # Verify backup file was created
        pattern = f"{self.session_file}.corrupted.*"
        backups = glob.glob(pattern)
        self.assertGreaterEqual(len(backups), 1, "Expected backup file matching pattern")

        with open(backups[0], "r", encoding="utf-8") as f:
            saved_content = f.read()
        self.assertEqual(saved_content, corrupted_content)

        # Verify subsequent save and load works seamlessly
        new_data = {
            "last_project": "/test/path",
            "projects": {"/test/path": {"project_name": "path", "goal": "Recovered"}},
            "history": []
        }
        success = save_sessions(new_data, file_path=self.session_file)
        self.assertTrue(success)

        reloaded = load_sessions(file_path=self.session_file)
        self.assertEqual(reloaded["last_project"], "/test/path")
        self.assertEqual(reloaded["projects"]["/test/path"]["goal"], "Recovered")


class TestResumeCommand(unittest.TestCase):
    """Test dc resume context handoff generation (markdown and JSON)."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = os.path.realpath(os.path.join(self.temp_dir.name, "resume_repo"))
        init_git_repo(self.repo_dir)
        self.session_file = os.path.join(self.temp_dir.name, "sessions.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_resume_markdown_output(self):
        """Verify dc resume produces rich, accurate handoff markdown."""
        update_session(
            self.repo_dir,
            objective="Implement WebAuthn passkey authentication",
            status="in_progress",
            last_step="Wrote challenge generation routine",
            next_action="Implement signature verification in auth.py",
            blockers=["Awaiting HSM staging credentials"],
            decisions=[{
                "decision": "Use FIDO2 Level 3 spec",
                "rationale": "Hardware key support",
                "rejected_alternatives": ["SMS OTP", "Email magic link"]
            }],
            files_changed={
                "src/passkey.py": {
                    "why": "Add challenge generator",
                    "lines_added": 35,
                    "lines_deleted": 2
                }
            },
            test_results={
                "command": "pytest tests/test_passkey.py",
                "passed": True,
                "summary": "8 passed in 0.2s"
            },
            file_path=self.session_file
        )

        ctx = get_resume_context(project="resume_repo", file_path=self.session_file)
        self.assertIsNotNone(ctx)

        md = ctx["markdown"]
        # 1. Project identity & branch
        self.assertIn("resume_repo", md)
        # 2. Objective & status
        self.assertIn("Implement WebAuthn passkey authentication", md)
        self.assertIn("in_progress", md)
        # 3. Changes & diff footprint & files changed
        self.assertIn("Footprint", md)
        self.assertIn("src/passkey.py", md)
        self.assertIn("+35/-2", md)
        self.assertIn("Add challenge generator", md)
        # 4. Last completed step
        self.assertIn("Wrote challenge generation routine", md)
        # 5. Blockers & unfinished work
        self.assertIn("Awaiting HSM staging credentials", md)
        # 6. Exact next concrete action
        self.assertIn("Implement signature verification in auth.py", md)
        # Extra: decisions & test results
        self.assertIn("Use FIDO2 Level 3 spec", md)
        self.assertIn("pytest tests/test_passkey.py", md)

    def test_resume_json_output(self):
        """Verify dc resume --json outputs structured JSON."""
        update_session(
            self.repo_dir,
            objective="API Rate Limiting",
            status="blocked",
            last_step="Created Redis client",
            next_action="Implement sliding window algorithm",
            blockers=["Redis port blocked on firewall"],
            file_path=self.session_file
        )

        buf = StringIO()
        with patch("sys.stdout", buf):
            cmd_resume(project="resume_repo", as_json=True, file_path=self.session_file)

        raw = buf.getvalue().strip()
        data = json.loads(raw)
        self.assertEqual(data["project"], "resume_repo")
        self.assertEqual(data["objective"], "API Rate Limiting")
        self.assertEqual(data["status"], "blocked")
        self.assertEqual(data["last_step"], "Created Redis client")
        self.assertEqual(data["next_action"], "Implement sliding window algorithm")
        self.assertIn("Redis port blocked on firewall", data["blockers"])

    def test_resume_nonexistent_project(self):
        """Verify dc resume -p nonexistent handles missing project gracefully."""
        buf = StringIO()
        with patch("sys.stdout", buf):
            cmd_resume(project="nonexistent_repo", file_path=self.session_file)
        output = strip_ansi(buf.getvalue())
        self.assertIn("not found in recorded sessions", output)


class TestInspectCommand(unittest.TestCase):
    """Test dc inspect <repo> command for workspace inspection."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace_dir = os.path.realpath(os.path.join(self.temp_dir.name, "workspace"))
        os.makedirs(self.workspace_dir, exist_ok=True)

        self.repo_a = os.path.realpath(os.path.join(self.workspace_dir, "service_alpha"))
        self.repo_b = os.path.realpath(os.path.join(self.workspace_dir, "service_beta"))
        init_git_repo(self.repo_a)
        init_git_repo(self.repo_b)

        self.session_file = os.path.join(self.temp_dir.name, "sessions.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_inspect_workspace_repo_state_and_memory(self):
        """Inspect service_beta without cd-ing into it."""
        # Set up session on service_beta
        update_session(
            self.repo_b,
            objective="Kafka Consumer Pipeline",
            status="in_progress",
            last_step="Wrote partition consumer",
            next_action="Add dead-letter queue",
            blockers=["Kafka broker down in staging"],
            file_path=self.session_file
        )

        # Make repo_b dirty
        with open(os.path.join(self.repo_b, "consumer.py"), "w") as f:
            f.write("# Consumer logic\n")

        # Run inspect while current working directory is repo_a
        orig_cwd = os.getcwd()
        try:
            os.chdir(self.repo_a)
            buf = StringIO()
            with patch("sys.stdout", buf):
                cmd_inspect("service_beta", projects_dir=self.workspace_dir, session_file=self.session_file)
            output = strip_ansi(buf.getvalue())
        finally:
            os.chdir(orig_cwd)

        self.assertIn("INSPECT: service_beta", output)
        self.assertIn("DIRTY", output)
        self.assertIn("SESSION MEMORY", output)
        self.assertIn("Objective:   Kafka Consumer Pipeline", output)
        self.assertIn("Status:      in_progress", output)
        self.assertIn("Last Step:   Wrote partition consumer", output)
        self.assertIn("Next Action: Add dead-letter queue", output)
        self.assertIn("Kafka broker down in staging", output)

    def test_inspect_json_output(self):
        """Verify dc inspect <repo> --json outputs comprehensive machine-readable data."""
        update_session(
            self.repo_a,
            objective="Authentication Refactor",
            file_path=self.session_file
        )

        data = get_repo_inspection(
            "service_alpha",
            projects_dir=self.workspace_dir,
            session_file=self.session_file
        )
        self.assertIsNotNone(data)
        self.assertEqual(data["project_name"], "service_alpha")
        self.assertTrue(data["is_git"])
        self.assertEqual(data["status"], "clean")
        self.assertEqual(data["session"]["objective"], "Authentication Refactor")

    def test_inspect_nonexistent_repo(self):
        """Verify inspect with unknown repo produces clean error message."""
        buf = StringIO()
        with patch("sys.stdout", buf):
            cmd_inspect("ghost_service", projects_dir=self.workspace_dir, session_file=self.session_file)
        output = strip_ansi(buf.getvalue())
        self.assertIn("not found in workspace", output)


class TestGoalCommandFlags(unittest.TestCase):
    """Test dc goal flags: --next, --blocker, --last-step, --status."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = os.path.realpath(os.path.join(self.temp_dir.name, "goal_repo"))
        init_git_repo(self.repo_dir)
        self.session_file = os.path.join(self.temp_dir.name, "sessions.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cmd_goal_with_all_flags(self):
        """Verify dc goal with flags sets all session fields."""
        orig_cwd = os.getcwd()
        try:
            os.chdir(self.repo_dir)
            buf = StringIO()
            with patch("sys.stdout", buf):
                cmd_goal(
                    text="Ship Phase 1 Upgrade",
                    next_action="Run test suite and verify coverage",
                    blockers=["Staging database migration pending"],
                    last_step="Finished concurrency lock engine",
                    status="in_progress",
                    file_path=self.session_file
                )
            output = strip_ansi(buf.getvalue())
        finally:
            os.chdir(orig_cwd)

        self.assertIn("Active goal set for goal_repo", output)
        self.assertIn("Ship Phase 1 Upgrade", output)
        self.assertIn("Run test suite and verify coverage", output)
        self.assertIn("Finished concurrency lock engine", output)
        self.assertIn("Staging database migration pending", output)

        session = get_last_session(self.repo_dir, file_path=self.session_file)
        self.assertEqual(session["objective"], "Ship Phase 1 Upgrade")
        self.assertEqual(session["status"], "in_progress")
        self.assertEqual(session["last_step"], "Finished concurrency lock engine")
        self.assertEqual(session["next_action"], "Run test suite and verify coverage")
        self.assertIn("Staging database migration pending", session["blockers"])


if __name__ == "__main__":
    unittest.main()
