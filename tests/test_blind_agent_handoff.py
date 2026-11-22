"""
Advanced Independent Understanding Handoff Test.
Tests that Agent B can autonomously inspect raw code and Git diffs from an interrupted
Agent A session, identify unfinished implementation logic without explicit explanations,
complete the work, and produce passing verified code without human clarification.
"""

import os
import sys
import tempfile
import unittest
import subprocess
import json
import hmac
import hashlib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import dev_context
import dev_context_mcp


class TestBlindAgentHandoff(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = os.path.join(self.temp_dir.name, "auth-gateway")
        os.makedirs(self.repo_dir, exist_ok=True)
        self.session_file = os.path.join(self.temp_dir.name, "sessions.json")
        self.roadmap_file = os.path.join(self.repo_dir, "ROADMAP.md")

        # Initialize mock git repository
        subprocess.run(["git", "init", "-b", "main"], cwd=self.repo_dir, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Agent A"], cwd=self.repo_dir, check=True)
        subprocess.run(["git", "config", "user.email", "agent-a@example.com"], cwd=self.repo_dir, check=True)

        # Baseline commit
        with open(os.path.join(self.repo_dir, "README.md"), "w") as f:
            f.write("# Auth Gateway\n")
        subprocess.run(["git", "add", "."], cwd=self.repo_dir, check=True)
        subprocess.run(["git", "commit", "-m", "chore: initial commit"], cwd=self.repo_dir, capture_output=True, check=True)

        with open(self.roadmap_file, "w") as f:
            f.write("# Roadmap\n\n## Active Sprint\n\n## Ideas Backlog\n")
        self.task_id = dev_context.cmd_add("Implement JWT signature verification", file_path=self.roadmap_file, quiet=True)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_blind_handoff_and_autonomous_completion(self):
        """
        Agent A makes partial, unexplained changes and dies.
        Agent B inspects diff, locates NotImplementedError, writes working algorithm,
        and verifies tests pass with zero user clarification.
        """
        # =========================================================================
        # Stage 1: Agent A makes partial changes without spoonfed explanations
        # =========================================================================
        dev_context.cmd_start(self.task_id, file_path=self.roadmap_file, quiet=True)

        auth_code_path = os.path.join(self.repo_dir, "jwt_auth.py")
        with open(auth_code_path, "w") as f:
            f.write('''import hmac
import hashlib

def verify_jwt_signature(token_str: str, secret_key: str) -> bool:
    """Verifies format payload.signature using HMAC-SHA256."""
    parts = token_str.split(".")
    if len(parts) != 2:
        return False
    payload, sig = parts
    # Unfinished implementation left by Agent A:
    raise NotImplementedError("TODO: HMAC-SHA256 signature verification pending")
''')

        test_code_path = os.path.join(self.repo_dir, "test_jwt.py")
        with open(test_code_path, "w") as f:
            f.write('''import unittest
from jwt_auth import verify_jwt_signature

class TestJWT(unittest.TestCase):
    def test_signature(self):
        import hmac, hashlib
        secret = "secret-key-123"
        payload = "user_id_42"
        sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        valid_token = f"{payload}.{sig}"
        self.assertTrue(verify_jwt_signature(valid_token, secret))
        tampered_token = f"{payload}.tampered_signature"
        self.assertFalse(verify_jwt_signature(tampered_token, secret))

if __name__ == "__main__":
    unittest.main()
''')

        # Agent A records high-level goal, but DOES NOT explain files or internal lines:
        dev_context_mcp.update_session(
            cwd=self.repo_dir,
            session_file=self.session_file,
            objective="Implement JWT signature verification",
            status="in_progress",
            last_step="Drafted token verification interface",
            next_action="Run test suite and complete missing signature verification"
        )

        # Agent A terminates abruptly!

        # =========================================================================
        # Stage 2: Agent B launches and inspects the raw development state
        # =========================================================================
        # 1. Agent B calls get_resume_handoff
        handoff_res = dev_context_mcp.get_resume_handoff(
            cwd=self.repo_dir,
            session_file=self.session_file,
            format="json"
        )
        handoff = json.loads(handoff_res["result"]["content"][0]["text"])
        self.assertEqual(handoff["objective"], "Implement JWT signature verification")
        self.assertEqual(handoff["status"], "in_progress")

        # 2. Agent B calls get_recent_changes to inspect uncommitted files
        changes_res = dev_context_mcp.get_recent_changes(
            cwd=self.repo_dir,
            session_file=self.session_file
        )
        changes = json.loads(changes_res["result"]["content"][0]["text"])
        modified_files = changes["modified_files"]
        self.assertTrue(any("jwt_auth.py" in f for f in modified_files))
        self.assertTrue(any("test_jwt.py" in f for f in modified_files))

        # =========================================================================
        # Stage 3: Agent B inspects code, discovers NotImplementedError, and completes it
        # =========================================================================
        with open(auth_code_path, "r") as f:
            source = f.read()
        self.assertIn("NotImplementedError", source)

        # Agent B writes the correct working implementation
        completed_code = '''import hmac
import hashlib

def verify_jwt_signature(token_str: str, secret_key: str) -> bool:
    """Verifies format payload.signature using HMAC-SHA256."""
    parts = token_str.split(".")
    if len(parts) != 2:
        return False
    payload, sig = parts
    expected = hmac.new(secret_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)
'''
        with open(auth_code_path, "w") as f:
            f.write(completed_code)

        # =========================================================================
        # Stage 4: Verify test suite passes without errors
        # =========================================================================
        proc = subprocess.run([sys.executable, test_code_path], cwd=self.repo_dir, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, f"Tests failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}")

        # Agent B updates session memory with success
        dev_context_mcp.update_session(
            cwd=self.repo_dir,
            session_file=self.session_file,
            status="completed",
            last_step="Implemented HMAC-SHA256 compare_digest and verified test suite passed",
            next_action="Ready to merge into main"
        )
        dev_context.cmd_done(self.task_id, file_path=self.roadmap_file, quiet=True)

        # Final verification
        final_goal_res = dev_context_mcp.get_current_goal(cwd=self.repo_dir, session_file=self.session_file)
        final_goal = json.loads(final_goal_res["result"]["content"][0]["text"])
        self.assertEqual(final_goal["status"], "completed")


if __name__ == "__main__":
    unittest.main()
