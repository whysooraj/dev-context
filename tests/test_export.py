#!/usr/bin/env python3
"""
Unit and integration tests for dev-context Agent Context Export (`dc export`)
and Agent Setup Command (`dc setup-agent`).
"""

import os
import sys
import json
import tempfile
import unittest
import subprocess
from io import StringIO
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dev_context import (
    get_active_context_data,
    format_context_markdown,
    cmd_export,
    cmd_setup_agent,
    set_active_goal,
    cmd_add,
)


def init_git_repo(path, commit_msg="Initial commit"):
    """Helper to initialize a test git repository."""
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init", "-q", path], check=True)
    subprocess.run(["git", "-C", path, "config", "user.name", "Export Tester"], check=True)
    subprocess.run(["git", "-C", path, "config", "user.email", "export@example.com"], check=True)
    readme = os.path.join(path, "README.md")
    with open(readme, "w") as f:
        f.write("# Export Test Repo\n")
    subprocess.run(["git", "-C", path, "add", "README.md"], check=True)
    subprocess.run(["git", "-C", path, "commit", "-q", "-m", commit_msg], check=True)


class TestGetActiveContextData(unittest.TestCase):
    """Tests for get_active_context_data engine."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = self.temp_dir.name
        self.repo_dir = os.path.join(self.workspace, "active-repo")
        init_git_repo(self.repo_dir, "feat: initial commit for export test")
        self.session_file = os.path.join(self.workspace, "sessions.json")
        self.roadmap_file = os.path.join(self.workspace, "ROADMAP.md")
        with open(self.roadmap_file, "w") as f:
            f.write("# Roadmap\n\n## Active Sprint\n- [ ] (active-repo) First priority task <!-- id:a101 -->\n- [ ] (other) Second priority task <!-- id:a102 -->\n")

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_clean_git_repo_context(self):
        set_active_goal(self.repo_dir, "Ship agent export", file_path=self.session_file)
        data = get_active_context_data(
            cwd=self.repo_dir,
            projects_dir=self.workspace,
            session_file=self.session_file,
            roadmap_file=self.roadmap_file,
        )

        self.assertTrue(data["active_project"]["in_git"])
        self.assertEqual(data["active_project"]["name"], "active-repo")
        self.assertEqual(data["active_project"]["status"], "clean")
        self.assertEqual(data["active_project"]["dirty_count"], 0)
        self.assertEqual(data["session_goal"], "Ship agent export")
        self.assertEqual(data["footprint"]["summary"], "clean")
        self.assertEqual(len(data["priority_tasks"]), 2)
        self.assertEqual(data["priority_tasks"][0]["id"], "a101")
        self.assertEqual(data["priority_tasks"][0]["project"], "active-repo")

    def test_dirty_git_repo_footprint_and_files(self):
        # Create dirty uncommitted changes
        test_file = os.path.join(self.repo_dir, "modified.txt")
        with open(test_file, "w") as f:
            f.write("Line 1\nLine 2\n")

        data = get_active_context_data(
            cwd=self.repo_dir,
            projects_dir=self.workspace,
            session_file=self.session_file,
            roadmap_file=self.roadmap_file,
        )

        self.assertEqual(data["active_project"]["status"], "dirty")
        self.assertGreater(data["active_project"]["dirty_count"], 0)
        self.assertIn("modified.txt", data["footprint"]["files"])
        self.assertIn("across 1 file", data["footprint"]["summary"])

    def test_workspace_alerts_detects_other_dirty_repos(self):
        # Create a second repo in workspace that has dirty changes
        other_repo = os.path.join(self.workspace, "other-repo")
        init_git_repo(other_repo, "feat: init other")
        dirty_file = os.path.join(other_repo, "draft.txt")
        with open(dirty_file, "w") as f:
            f.write("wip\n")

        data = get_active_context_data(
            cwd=self.repo_dir,
            projects_dir=self.workspace,
            session_file=self.session_file,
            roadmap_file=self.roadmap_file,
        )

        # other-repo should appear in workspace_alerts, but not active-repo
        alerts = data["workspace_alerts"]
        alert_names = [a["name"] for a in alerts]
        self.assertIn("other-repo", alert_names)
        self.assertNotIn("active-repo", alert_names)

    def test_context_outside_git_repo(self):
        outside_dir = os.path.join(self.workspace, "plain_folder")
        os.makedirs(outside_dir, exist_ok=True)

        data = get_active_context_data(
            cwd=outside_dir,
            projects_dir=self.workspace,
            session_file=self.session_file,
            roadmap_file=self.roadmap_file,
        )

        self.assertFalse(data["active_project"]["in_git"])
        self.assertIsNone(data["active_project"]["name"])
        self.assertEqual(data["active_project"]["status"], "clean")
        self.assertEqual(data["footprint"]["summary"], "clean")


class TestFormatContextMarkdown(unittest.TestCase):
    """Tests for format_context_markdown output formatting."""

    def test_markdown_structure(self):
        ctx = {
            "active_project": {
                "name": "besynx",
                "path": "/home/user/Projects/besynx",
                "in_git": True,
                "branch": "main",
                "status": "dirty",
                "dirty_count": 2,
                "last_commit": {
                    "relative_time": "10 minutes ago",
                    "subject": "feat: p2p sync",
                },
            },
            "session_goal": "Implement device pairing",
            "footprint": {
                "summary": "+24 -5 across 2 files",
                "files": ["src/sync.rs", "src/crypto.rs"],
            },
            "priority_tasks": [
                {
                    "id": "b101",
                    "state_label": "[TODO]",
                    "text": "Add websocket heartbeat",
                    "project": "besynx",
                }
            ],
            "workspace_alerts": [
                {
                    "name": "laya",
                    "path": "/home/user/Projects/laya",
                    "dirty_count": 3,
                    "rel_time": "1 hour ago",
                    "subject": "fix: folder preview",
                }
            ],
            "roadmap_file": "/home/user/Projects/ROADMAP.md",
        }

        md = format_context_markdown(ctx)
        self.assertIn("# Developer Context Briefing", md)
        self.assertIn("## Active Project", md)
        self.assertIn("**Project**: besynx (`main`)", md)
        self.assertIn("**Session Goal**: Implement device pairing", md)
        self.assertIn("+24 -5 across 2 files", md)
        self.assertIn("`src/sync.rs`", md)
        self.assertIn("## Priority Tasks", md)
        self.assertIn("[b101] [TODO] Add websocket heartbeat", md)
        self.assertIn("## Workspace Alerts", md)
        self.assertIn("**laya** (3 modified)", md)


class TestExportCLI(unittest.TestCase):
    """CLI integration tests for `dc export`."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = os.path.join(self.temp_dir.name, "cli-repo")
        init_git_repo(self.repo_dir, "feat: cli test")
        self.bin_path = str(PROJECT_ROOT / "bin" / "dev-context")

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_cli_export_markdown_default(self):
        res = subprocess.run(
            ["python3", self.bin_path, "export"],
            cwd=self.repo_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("# Developer Context Briefing", res.stdout)
        self.assertIn("## Active Project", res.stdout)
        self.assertIn("cli-repo", res.stdout)

    def test_cli_export_agent_flag(self):
        res = subprocess.run(
            ["python3", self.bin_path, "export", "--agent"],
            cwd=self.repo_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("# Developer Context Briefing", res.stdout)
        self.assertIn("## Active Project", res.stdout)

    def test_cli_export_json(self):
        res = subprocess.run(
            ["python3", self.bin_path, "export", "--json"],
            cwd=self.repo_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        parsed = json.loads(res.stdout)
        self.assertIn("active_project", parsed)
        self.assertEqual(parsed["active_project"]["name"], "cli-repo")
        self.assertIn("session_goal", parsed)
        self.assertIn("footprint", parsed)
        self.assertIn("priority_tasks", parsed)
        self.assertIn("workspace_alerts", parsed)


class TestSetupAgentCLI(unittest.TestCase):
    """Tests for `dc setup-agent` command."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = os.path.join(self.temp_dir.name, "agent-repo")
        init_git_repo(self.repo_dir, "feat: agent repo")
        self.bin_path = str(PROJECT_ROOT / "bin" / "dev-context")

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_setup_agent_cursor(self):
        res = subprocess.run(
            ["python3", self.bin_path, "setup-agent", "cursor"],
            cwd=self.repo_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        cursorrules = os.path.join(self.repo_dir, ".cursorrules")
        self.assertTrue(os.path.isfile(cursorrules))
        with open(cursorrules, "r") as f:
            content = f.read()
        self.assertIn("dev-context Rules", content)
        self.assertIn("dc export --agent", content)

    def test_setup_agent_claude_rules_only(self):
        res = subprocess.run(
            ["python3", self.bin_path, "setup-agent", "claude", "--rules-only"],
            cwd=self.repo_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        rules_file = os.path.join(self.repo_dir, ".claude", "rules", "dev-context.md")
        self.assertTrue(os.path.isfile(rules_file))
        with open(rules_file, "r") as f:
            content = f.read()
        self.assertIn("dev-context Integration Rules", content)
        self.assertIn("get_active_context", content)

    def test_setup_agent_invalid_choice(self):
        res = subprocess.run(
            ["python3", self.bin_path, "setup-agent", "invalid-agent"],
            cwd=self.repo_dir,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(res.returncode, 0)


if __name__ == "__main__":
    unittest.main()
