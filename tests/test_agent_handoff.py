"""
End-to-end integration test demonstrating cross-agent session handoff.
Simulates:
1. Agent A (Claude Code) starts an objective, modifies code, records decisions and blockers.
2. Agent A is interrupted before completion.
3. Agent B (Codex/Cursor) resumes in the same repo via get_resume_handoff / dc resume.
4. Agent B receives 100% accurate state and executes the exact next action with zero repeated user prompts.
"""

import os
import sys
import tempfile
import unittest
import subprocess
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import dev_context
import dev_context_mcp


class TestCrossAgentHandoff(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = os.path.join(self.temp_dir.name, "rate-limiter")
        os.makedirs(self.repo_dir, exist_ok=True)
        self.session_file = os.path.join(self.temp_dir.name, "sessions.json")
        self.roadmap_file = os.path.join(self.repo_dir, "ROADMAP.md")

        # Initialize mock git repository
        subprocess.run(["git", "init", "-b", "main"], cwd=self.repo_dir, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=self.repo_dir, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.repo_dir, check=True)

        # Initial commit
        readme_path = os.path.join(self.repo_dir, "README.md")
        with open(readme_path, "w") as f:
            f.write("# Rate Limiter Service\n")
        subprocess.run(["git", "add", "."], cwd=self.repo_dir, check=True)
        subprocess.run(["git", "commit", "-m", "chore: initial commit"], cwd=self.repo_dir, capture_output=True, check=True)

        # Create initial roadmap task
        with open(self.roadmap_file, "w") as f:
            f.write("# Roadmap\n\n## Active Sprint\n\n## Ideas Backlog\n")
        self.task_id = dev_context.cmd_add("Implement sliding window rate limiter", file_path=self.roadmap_file, quiet=True)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_claude_to_codex_interrupted_handoff(self):
        """
        Demonstrate Agent A (Claude) -> Agent B (Codex) handoff after mid-task interruption.
        """
        # =========================================================================
        # Stage 1: Agent A (Claude Code) starts working
        # =========================================================================
        # Agent A marks task in-progress
        dev_context.cmd_start(self.task_id, file_path=self.roadmap_file, quiet=True)

        # Agent A creates code file
        limiter_code = os.path.join(self.repo_dir, "limiter.py")
        with open(limiter_code, "w") as f:
            f.write("class TokenBucket:\n    def __init__(self, rate):\n        self.rate = rate\n")

        # Agent A records progress and architectural decision via MCP update_session
        update_res = dev_context_mcp.update_session(
            cwd=self.repo_dir,
            session_file=self.session_file,
            objective="Implement TokenBucket rate limiter middleware",
            status="in_progress",
            last_step="Created TokenBucket class in limiter.py",
            next_action="Add expiry cleanup thread and write unit tests",
            blocker="Need decision on Redis vs in-memory lock",
            decision={
                "decision": "Use in-memory monotonic clock token bucket",
                "rationale": "Avoids Redis network latency for L1 edge gateway",
                "rejected_alternatives": "Redis token bucket"
            },
            file_changed={
                "path": "limiter.py",
                "why": "Core TokenBucket algorithm structure"
            }
        )
        self.assertFalse(update_res.get("result", {}).get("isError", False))
        payload_a = json.loads(update_res["result"]["content"][0]["text"])
        self.assertTrue(payload_a["success"])

        # =========================================================================
        # Stage 2: Agent A is abruptly interrupted (crashed / closed / token exhausted)
        # =========================================================================
        # Developer opens new session with Agent B (OpenAI Codex) in the same directory.
        # Developer does NOT repeat any instructions. Agent B queries MCP get_resume_handoff.

        # =========================================================================
        # Stage 3: Agent B (Codex) resumes using get_resume_handoff
        # =========================================================================
        handoff_raw = dev_context_mcp.get_resume_handoff(
            cwd=self.repo_dir,
            session_file=self.session_file,
            format="json"
        )
        handoff_json = json.loads(handoff_raw["result"]["content"][0]["text"])
        self.assertEqual(handoff_json["project"], "rate-limiter")
        self.assertEqual(handoff_json["status"], "in_progress")
        self.assertEqual(handoff_json["objective"], "Implement TokenBucket rate limiter middleware")
        self.assertEqual(handoff_json["last_step"], "Created TokenBucket class in limiter.py")
        self.assertEqual(handoff_json["next_action"], "Add expiry cleanup thread and write unit tests")
        self.assertIn("Need decision on Redis vs in-memory lock", handoff_json["blockers"])
        self.assertIn("limiter.py", handoff_json["files_changed"])
        self.assertEqual(handoff_json["files_changed"]["limiter.py"]["why"], "Core TokenBucket algorithm structure")

        # Agent B also checks markdown resume output for human readability
        handoff_md_res = dev_context_mcp.get_resume_handoff(
            cwd=self.repo_dir,
            session_file=self.session_file,
            format="markdown"
        )
        handoff_md = handoff_md_res["result"]["content"][0]["text"]
        self.assertIn("Implement TokenBucket rate limiter middleware", handoff_md)
        self.assertIn("Add expiry cleanup thread and write unit tests", handoff_md)
        self.assertIn("limiter.py", handoff_md)

        # =========================================================================
        # Stage 4: Agent B executes the exact next action and completes task
        # =========================================================================
        # Agent B adds the test file
        test_file = os.path.join(self.repo_dir, "test_limiter.py")
        with open(test_file, "w") as f:
            f.write("def test_bucket(): assert True\n")

        # Agent B updates session: resolves blocker, completes objective
        final_update = dev_context_mcp.update_session(
            cwd=self.repo_dir,
            session_file=self.session_file,
            status="completed",
            last_step="Added expiry cleanup thread and unit tests in test_limiter.py",
            next_action="Ship rate limiter to staging",
            blocker=None,
            file_changed={
                "path": "test_limiter.py",
                "why": "Unit tests verifying token replenishment"
            }
        )
        self.assertFalse(final_update.get("result", {}).get("isError", False))
        payload_b = json.loads(final_update["result"]["content"][0]["text"])
        self.assertTrue(payload_b["success"])

        # Agent B marks task done in roadmap
        dev_context.cmd_done(self.task_id, file_path=self.roadmap_file, quiet=True)

        # Verify final state
        tasks, _ = dev_context.get_open_tasks(self.roadmap_file, include_completed=True)
        self.assertEqual(tasks[0]["state"], "completed")

        final_goal_res = dev_context_mcp.get_current_goal(cwd=self.repo_dir, session_file=self.session_file)
        final_goal = json.loads(final_goal_res["result"]["content"][0]["text"])
        self.assertEqual(final_goal["status"], "completed")
        self.assertEqual(final_goal["next_action"], "Ship rate limiter to staging")


if __name__ == "__main__":
    unittest.main()
