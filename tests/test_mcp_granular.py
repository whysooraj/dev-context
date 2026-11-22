#!/usr/bin/env python3
"""
Comprehensive tests for Phase 2: Granular, High-Value MCP Tools Suite:
1. Unit tests for all 8 granular MCP tools via simulated JSON-RPC stdio calls:
   - get_project_context
   - get_current_goal
   - update_session
   - get_open_tasks
   - get_recent_changes
   - mark_task_status
   - get_next_action
   - get_resume_handoff
2. Input validation tests (invalid types, enum checks, missing required params, -32602 error code).
3. Missing project handling.
4. Concurrency test: simultaneous thread execution of update_session and reads without data loss.
5. Full stdio stream test via run_mcp_server.
"""

import os
import sys
import json
import tempfile
import unittest
import threading
import subprocess
from io import StringIO
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dev_context import (
    handle_mcp_message,
    handle_mcp_tool_call,
    run_mcp_server,
    MCP_TOOLS,
    set_active_goal,
    update_session,
    get_last_session,
    get_open_tasks,
)
import dev_context_mcp


def init_git_repo(path, commit_msg="Initial test commit"):
    """Initialize a git repository with an initial commit and a README."""
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init", "-q", path], check=True)
    subprocess.run(["git", "-C", path, "config", "user.name", "MCP Granular Tester"], check=True)
    subprocess.run(["git", "-C", path, "config", "user.email", "tester@example.com"], check=True)
    readme = os.path.join(path, "README.md")
    with open(readme, "w") as f:
        f.write("# Granular Test Repo - Lightweight context testing utility\n\nA test repository for MCP tools.\n")
    subprocess.run(["git", "-C", path, "add", "README.md"], check=True)
    subprocess.run(["git", "-C", path, "commit", "-q", "-m", commit_msg], check=True)


class TestGranularMCPTools(unittest.TestCase):
    """Unit tests for each of the 8 granular MCP tools."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = os.path.realpath(self.temp_dir.name)
        self.repo_dir = os.path.realpath(os.path.join(self.workspace, "my-app"))
        init_git_repo(self.repo_dir, "feat: init my-app")

        self.session_file = os.path.join(self.workspace, "sessions.json")
        self.roadmap_file = os.path.join(self.workspace, "ROADMAP.md")
        with open(self.roadmap_file, "w") as f:
            f.write(
                "# Roadmap\n\n"
                "## Active Sprint\n"
                "- [ ] (my-app) Implement auth router <!-- id:c101 -->\n"
                "- [-] (my-app) Add unit test coverage <!-- id:c102 -->\n"
                "- [!] (my-app) Fix memory leak <!-- id:c103 -->\n"
                "- [ ] (other-app) Unrelated task <!-- id:d101 -->\n"
            )

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    # 1. get_project_context
    def test_get_project_context_cwd_and_explicit(self):
        # Initial commit in repo
        req_cwd = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "get_project_context", "arguments": {}},
        }
        resp = handle_mcp_message(req_cwd, session_file=self.session_file, cwd=self.repo_dir)
        self.assertEqual(resp["id"], 1)
        self.assertNotIn("error", resp)
        data = json.loads(resp["result"]["content"][0]["text"])

        self.assertEqual(data["name"], "my-app")
        self.assertIn("branch", data)
        self.assertEqual(data["path"], os.path.abspath(self.repo_dir))
        self.assertEqual(data["purpose"], "Lightweight context testing utility")
        self.assertIsNotNone(data["last_commit"])
        self.assertEqual(data["last_commit"]["subject"], "feat: init my-app")
        self.assertEqual(data["dirty_count"], 0)

        # Test explicit path
        req_exp = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "get_project_context", "arguments": {"project": self.repo_dir}},
        }
        resp_exp = handle_mcp_message(req_exp, session_file=self.session_file, cwd=self.workspace)
        self.assertNotIn("error", resp_exp)
        data_exp = json.loads(resp_exp["result"]["content"][0]["text"])
        self.assertEqual(data_exp["name"], "my-app")

    # 2. get_current_goal
    def test_get_current_goal(self):
        # Initially empty goal
        req_empty = {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {"name": "get_current_goal", "arguments": {"project": self.repo_dir}},
        }
        resp_empty = handle_mcp_message(req_empty, session_file=self.session_file, cwd=self.repo_dir)
        self.assertNotIn("error", resp_empty)
        data_empty = json.loads(resp_empty["result"]["content"][0]["text"])
        self.assertEqual(data_empty["objective"], "")
        self.assertEqual(data_empty["status"], "in_progress")

        # Set goal via update_session
        update_session(
            self.repo_dir,
            objective="Ship Phase 2 MCP",
            status="blocked",
            last_step="Implemented tools schema",
            next_action="Write test cases",
            blockers=["Pending test validation"],
            file_path=self.session_file,
        )

        req_populated = {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {"name": "get_current_goal", "arguments": {"project": self.repo_dir}},
        }
        resp_pop = handle_mcp_message(req_populated, session_file=self.session_file, cwd=self.repo_dir)
        self.assertNotIn("error", resp_pop)
        data_pop = json.loads(resp_pop["result"]["content"][0]["text"])
        self.assertEqual(data_pop["objective"], "Ship Phase 2 MCP")
        self.assertEqual(data_pop["status"], "blocked")
        self.assertEqual(data_pop["last_step"], "Implemented tools schema")
        self.assertEqual(data_pop["next_action"], "Write test cases")
        self.assertIn("Pending test validation", data_pop["blockers"])

    # 3. update_session
    def test_update_session_atomic(self):
        req = {
            "jsonrpc": "2.0",
            "id": 20,
            "method": "tools/call",
            "params": {
                "name": "update_session",
                "arguments": {
                    "project": self.repo_dir,
                    "objective": "Complete Granular MCP Tools",
                    "status": "in_progress",
                    "last_step": "Created tool dispatchers",
                    "next_action": "Verify with test suite",
                    "blocker": "Waiting on upstream PR review",
                    "decision": {
                        "decision": "Use JSON-RPC error -32602 for input errors",
                        "rationale": "Follows standard MCP / JSON-RPC specification",
                        "rejected_alternatives": "Return empty result or generic code",
                    },
                    "file_changed": {
                        "path": "bin/dev-context",
                        "why": "Added 8 granular tools and input validators",
                    },
                },
            },
        }
        resp = handle_mcp_message(req, session_file=self.session_file, cwd=self.repo_dir)
        self.assertNotIn("error", resp)
        self.assertFalse(resp["result"]["isError"])
        res_data = json.loads(resp["result"]["content"][0]["text"])
        self.assertTrue(res_data["success"])

        sess_info = res_data["session"]
        self.assertEqual(sess_info["objective"], "Complete Granular MCP Tools")
        self.assertEqual(sess_info["status"], "in_progress")
        self.assertEqual(sess_info["last_step"], "Created tool dispatchers")
        self.assertEqual(sess_info["next_action"], "Verify with test suite")
        self.assertIn("Waiting on upstream PR review", sess_info["blockers"])
        self.assertEqual(len(sess_info["decisions"]), 1)
        self.assertEqual(sess_info["decisions"][0]["decision"], "Use JSON-RPC error -32602 for input errors")
        self.assertIn("bin/dev-context", sess_info["files_changed"])

        # Check file persistence
        persisted = get_last_session(self.repo_dir, file_path=self.session_file)
        self.assertEqual(persisted["objective"], "Complete Granular MCP Tools")

    # 4. get_open_tasks
    def test_get_open_tasks_filtering(self):
        # 1. All open tasks (default include_blocked=True)
        req_all = {
            "jsonrpc": "2.0",
            "id": 30,
            "method": "tools/call",
            "params": {"name": "get_open_tasks", "arguments": {}},
        }
        resp_all = handle_mcp_message(req_all, roadmap_file=self.roadmap_file, cwd=self.repo_dir)
        tasks_all = json.loads(resp_all["result"]["content"][0]["text"])
        self.assertEqual(len(tasks_all), 4)

        # 2. Exclude blocked tasks (include_blocked=False)
        req_no_blocked = {
            "jsonrpc": "2.0",
            "id": 31,
            "method": "tools/call",
            "params": {"name": "get_open_tasks", "arguments": {"include_blocked": False}},
        }
        resp_nb = handle_mcp_message(req_no_blocked, roadmap_file=self.roadmap_file, cwd=self.repo_dir)
        tasks_nb = json.loads(resp_nb["result"]["content"][0]["text"])
        self.assertEqual(len(tasks_nb), 3)
        self.assertNotIn("c103", [t["id"] for t in tasks_nb])

        # 3. Filter by project
        req_proj = {
            "jsonrpc": "2.0",
            "id": 32,
            "method": "tools/call",
            "params": {"name": "get_open_tasks", "arguments": {"project": "my-app"}},
        }
        resp_proj = handle_mcp_message(req_proj, roadmap_file=self.roadmap_file, cwd=self.repo_dir)
        tasks_proj = json.loads(resp_proj["result"]["content"][0]["text"])
        self.assertEqual(len(tasks_proj), 3)
        for t in tasks_proj:
            self.assertEqual(t["project"], "my-app")

    # 5. get_recent_changes
    def test_get_recent_changes(self):
        # Modify a file to create uncommitted diff
        new_file = os.path.join(self.repo_dir, "feature.py")
        with open(new_file, "w") as f:
            f.write("# new feature\nprint('hello world')\n")

        req = {
            "jsonrpc": "2.0",
            "id": 40,
            "method": "tools/call",
            "params": {"name": "get_recent_changes", "arguments": {"project": self.repo_dir, "limit_commits": 3}},
        }
        resp = handle_mcp_message(req, session_file=self.session_file, cwd=self.repo_dir)
        self.assertNotIn("error", resp)
        data = json.loads(resp["result"]["content"][0]["text"])

        self.assertEqual(data["project"], "my-app")
        self.assertIn("feature.py", data["modified_files"])
        self.assertGreater(len(data["recent_commits"]), 0)
        self.assertEqual(data["recent_commits"][0]["subject"], "feat: init my-app")

    # 6. mark_task_status
    def test_mark_task_status_lifecycle(self):
        # Start task c101
        req_start = {
            "jsonrpc": "2.0",
            "id": 50,
            "method": "tools/call",
            "params": {"name": "mark_task_status", "arguments": {"id": "c101", "status": "start"}},
        }
        resp_start = handle_mcp_message(req_start, roadmap_file=self.roadmap_file, cwd=self.repo_dir)
        self.assertFalse(resp_start["result"]["isError"])
        data_start = json.loads(resp_start["result"]["content"][0]["text"])
        self.assertTrue(data_start["success"])
        self.assertEqual(data_start["status"], "start")

        tasks, _ = get_open_tasks(self.roadmap_file)
        t_c101 = next(t for t in tasks if t["id"] == "c101")
        self.assertEqual(t_c101["state"], "in_progress")

        # Block task c101 with reason
        req_block = {
            "jsonrpc": "2.0",
            "id": 51,
            "method": "tools/call",
            "params": {"name": "mark_task_status", "arguments": {"id": "c101", "status": "block", "reason": "OAuth credentials missing"}},
        }
        resp_block = handle_mcp_message(req_block, session_file=self.session_file, roadmap_file=self.roadmap_file, cwd=self.repo_dir)
        self.assertFalse(resp_block["result"]["isError"])

        tasks, _ = get_open_tasks(self.roadmap_file)
        t_c101 = next(t for t in tasks if t["id"] == "c101")
        self.assertEqual(t_c101["state"], "blocked")

        # Done task c101
        req_done = {
            "jsonrpc": "2.0",
            "id": 52,
            "method": "tools/call",
            "params": {"name": "mark_task_status", "arguments": {"id": "c101", "status": "done"}},
        }
        resp_done = handle_mcp_message(req_done, roadmap_file=self.roadmap_file, cwd=self.repo_dir)
        self.assertFalse(resp_done["result"]["isError"])

        tasks, _ = get_open_tasks(self.roadmap_file)
        self.assertNotIn("c101", [t["id"] for t in tasks])

        # rm task c102
        req_rm = {
            "jsonrpc": "2.0",
            "id": 53,
            "method": "tools/call",
            "params": {"name": "mark_task_status", "arguments": {"id": "c102", "status": "rm"}},
        }
        resp_rm = handle_mcp_message(req_rm, roadmap_file=self.roadmap_file, cwd=self.repo_dir)
        self.assertFalse(resp_rm["result"]["isError"])

        # Nonexistent task ID returns isError
        req_none = {
            "jsonrpc": "2.0",
            "id": 54,
            "method": "tools/call",
            "params": {"name": "mark_task_status", "arguments": {"id": "face", "status": "start"}},
        }
        resp_none = handle_mcp_message(req_none, roadmap_file=self.roadmap_file, cwd=self.repo_dir)
        self.assertTrue(resp_none["result"]["isError"])

    # 7. get_next_action
    def test_get_next_action_session_and_roadmap_fallback(self):
        # 1. Fallback to roadmap when session next_action is not set
        req_fallback = {
            "jsonrpc": "2.0",
            "id": 60,
            "method": "tools/call",
            "params": {"name": "get_next_action", "arguments": {"project": "my-app"}},
        }
        resp_fb = handle_mcp_message(req_fallback, session_file=self.session_file, roadmap_file=self.roadmap_file, cwd=self.repo_dir)
        self.assertNotIn("error", resp_fb)
        data_fb = json.loads(resp_fb["result"]["content"][0]["text"])
        self.assertEqual(data_fb["source"], "roadmap")
        # In-progress task c102 or todo c101
        self.assertIn("c102", data_fb["next_action"])

        # 2. When explicit next_action is set in session
        update_session(self.repo_dir, next_action="Deploy canary to staging", file_path=self.session_file)
        req_sess = {
            "jsonrpc": "2.0",
            "id": 61,
            "method": "tools/call",
            "params": {"name": "get_next_action", "arguments": {"project": self.repo_dir}},
        }
        resp_sess = handle_mcp_message(req_sess, session_file=self.session_file, roadmap_file=self.roadmap_file, cwd=self.repo_dir)
        data_sess = json.loads(resp_sess["result"]["content"][0]["text"])
        self.assertEqual(data_sess["source"], "session")
        self.assertEqual(data_sess["next_action"], "Deploy canary to staging")

    # 8. get_resume_handoff
    def test_get_resume_handoff_markdown_and_json(self):
        update_session(
            self.repo_dir,
            objective="Resumption Verification",
            status="in_progress",
            last_step="Configured CI pipeline",
            next_action="Run load test suite",
            file_path=self.session_file,
        )

        # Markdown format
        req_md = {
            "jsonrpc": "2.0",
            "id": 70,
            "method": "tools/call",
            "params": {"name": "get_resume_handoff", "arguments": {"project": self.repo_dir, "format": "markdown"}},
        }
        resp_md = handle_mcp_message(req_md, session_file=self.session_file, cwd=self.repo_dir)
        self.assertNotIn("error", resp_md)
        text_md = resp_md["result"]["content"][0]["text"]
        self.assertIn("# Session Handoff: my-app", text_md)
        self.assertIn("Resumption Verification", text_md)
        self.assertIn("Run load test suite", text_md)

        # JSON format
        req_json = {
            "jsonrpc": "2.0",
            "id": 71,
            "method": "tools/call",
            "params": {"name": "get_resume_handoff", "arguments": {"project": self.repo_dir, "format": "json"}},
        }
        resp_json = handle_mcp_message(req_json, session_file=self.session_file, cwd=self.repo_dir)
        self.assertNotIn("error", resp_json)
        data_json = json.loads(resp_json["result"]["content"][0]["text"])
        self.assertEqual(data_json["project"], "my-app")
        self.assertEqual(data_json["objective"], "Resumption Verification")
        self.assertEqual(data_json["next_action"], "Run load test suite")


class TestMCPInputValidationAndErrors(unittest.TestCase):
    """Tests input validation and standard -32602 JSON-RPC error codes."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = os.path.realpath(os.path.join(self.temp_dir.name, "validation-repo"))
        init_git_repo(self.repo_dir)
        self.session_file = os.path.join(self.temp_dir.name, "sessions.json")
        self.roadmap_file = os.path.join(self.temp_dir.name, "ROADMAP.md")
        with open(self.roadmap_file, "w") as f:
            f.write("# Roadmap\n- [ ] Task <!-- id:v101 -->\n")

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_non_dict_arguments_returns_32602(self):
        req = {
            "jsonrpc": "2.0",
            "id": 101,
            "method": "tools/call",
            "params": {"name": "get_project_context", "arguments": "not-a-dict"},
        }
        resp = handle_mcp_message(req)
        self.assertEqual(resp["error"]["code"], -32602)

    def test_update_session_invalid_status_enum(self):
        req = {
            "jsonrpc": "2.0",
            "id": 102,
            "method": "tools/call",
            "params": {
                "name": "update_session",
                "arguments": {"project": self.repo_dir, "status": "invalid_status"},
            },
        }
        resp = handle_mcp_message(req, session_file=self.session_file, cwd=self.repo_dir)
        self.assertEqual(resp["error"]["code"], -32602)
        self.assertIn("Invalid status", resp["error"]["message"])

    def test_update_session_invalid_param_types(self):
        # objective not a string
        req_obj = {
            "jsonrpc": "2.0",
            "id": 103,
            "method": "tools/call",
            "params": {"name": "update_session", "arguments": {"objective": 12345}},
        }
        resp = handle_mcp_message(req_obj, session_file=self.session_file, cwd=self.repo_dir)
        self.assertEqual(resp["error"]["code"], -32602)

        # decision not a dict or missing decision field
        req_dec = {
            "jsonrpc": "2.0",
            "id": 104,
            "method": "tools/call",
            "params": {"name": "update_session", "arguments": {"decision": "just a string"}},
        }
        resp = handle_mcp_message(req_dec, session_file=self.session_file, cwd=self.repo_dir)
        self.assertEqual(resp["error"]["code"], -32602)

    def test_mark_task_status_missing_required_params(self):
        # Missing id
        req_noid = {
            "jsonrpc": "2.0",
            "id": 105,
            "method": "tools/call",
            "params": {"name": "mark_task_status", "arguments": {"status": "done"}},
        }
        resp = handle_mcp_message(req_noid, roadmap_file=self.roadmap_file)
        self.assertEqual(resp["error"]["code"], -32602)

        # Missing status
        req_nostat = {
            "jsonrpc": "2.0",
            "id": 106,
            "method": "tools/call",
            "params": {"name": "mark_task_status", "arguments": {"id": "v101"}},
        }
        resp = handle_mcp_message(req_nostat, roadmap_file=self.roadmap_file)
        self.assertEqual(resp["error"]["code"], -32602)

        # Invalid status enum
        req_badstat = {
            "jsonrpc": "2.0",
            "id": 107,
            "method": "tools/call",
            "params": {"name": "mark_task_status", "arguments": {"id": "v101", "status": "terminate"}},
        }
        resp = handle_mcp_message(req_badstat, roadmap_file=self.roadmap_file)
        self.assertEqual(resp["error"]["code"], -32602)

    def test_get_recent_changes_invalid_limit(self):
        req = {
            "jsonrpc": "2.0",
            "id": 108,
            "method": "tools/call",
            "params": {"name": "get_recent_changes", "arguments": {"limit_commits": "five"}},
        }
        resp = handle_mcp_message(req, cwd=self.repo_dir)
        self.assertEqual(resp["error"]["code"], -32602)

    def test_get_open_tasks_invalid_include_blocked(self):
        req = {
            "jsonrpc": "2.0",
            "id": 109,
            "method": "tools/call",
            "params": {"name": "get_open_tasks", "arguments": {"include_blocked": "true"}},
        }
        resp = handle_mcp_message(req, roadmap_file=self.roadmap_file)
        self.assertEqual(resp["error"]["code"], -32602)

    def test_get_resume_handoff_invalid_format(self):
        req = {
            "jsonrpc": "2.0",
            "id": 110,
            "method": "tools/call",
            "params": {"name": "get_resume_handoff", "arguments": {"format": "xml"}},
        }
        resp = handle_mcp_message(req, session_file=self.session_file, cwd=self.repo_dir)
        self.assertEqual(resp["error"]["code"], -32602)


class TestMCPMissingProjects(unittest.TestCase):
    """Tests handling of projects that do not exist."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.session_file = os.path.join(self.temp_dir.name, "sessions.json")

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_missing_project_in_get_project_context(self):
        req = {
            "jsonrpc": "2.0",
            "id": 201,
            "method": "tools/call",
            "params": {"name": "get_project_context", "arguments": {"project": "nonexistent_proj_999"}},
        }
        resp = handle_mcp_message(req, session_file=self.session_file, cwd=self.temp_dir.name)
        self.assertEqual(resp["error"]["code"], -32602)
        self.assertIn("nonexistent_proj_999", resp["error"]["message"])

    def test_missing_project_in_get_current_goal(self):
        req = {
            "jsonrpc": "2.0",
            "id": 202,
            "method": "tools/call",
            "params": {"name": "get_current_goal", "arguments": {"project": "nonexistent_proj_999"}},
        }
        resp = handle_mcp_message(req, session_file=self.session_file, cwd=self.temp_dir.name)
        self.assertEqual(resp["error"]["code"], -32602)

    def test_missing_project_in_get_resume_handoff(self):
        req = {
            "jsonrpc": "2.0",
            "id": 203,
            "method": "tools/call",
            "params": {"name": "get_resume_handoff", "arguments": {"project": "nonexistent_proj_999"}},
        }
        resp = handle_mcp_message(req, session_file=self.session_file, cwd=self.temp_dir.name)
        self.assertEqual(resp["error"]["code"], -32602)


class TestMCPConcurrency(unittest.TestCase):
    """Tests concurrency safety across MCP tool operations."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = os.path.realpath(os.path.join(self.temp_dir.name, "concurrent_repo"))
        init_git_repo(self.repo_dir)
        self.session_file = os.path.join(self.temp_dir.name, "sessions.json")

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_10_threads_concurrent_update_session(self):
        """10 threads concurrently updating the session via MCP tools/call must not corrupt file."""
        num_threads = 10
        barrier = threading.Barrier(num_threads)
        errors = []

        def worker(tid):
            barrier.wait()
            req = {
                "jsonrpc": "2.0",
                "id": tid,
                "method": "tools/call",
                "params": {
                    "name": "update_session",
                    "arguments": {
                        "project": self.repo_dir,
                        "objective": f"Objective from thread {tid}",
                        "status": "in_progress",
                        "blocker": f"Blocker-{tid}",
                        "decision": {
                            "decision": f"Decision-{tid}",
                            "rationale": f"Rationale-{tid}",
                        },
                        "file_changed": {
                            "path": f"src/file_{tid}.py",
                            "why": f"Change {tid}",
                        },
                    },
                },
            }
            try:
                resp = handle_mcp_message(req, session_file=self.session_file, cwd=self.repo_dir)
                if resp.get("error") or resp.get("result", {}).get("isError"):
                    errors.append(f"Thread {tid} error: {resp}")
            except Exception as e:
                errors.append(f"Thread {tid} exception: {e}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Encountered errors: {errors}")

        # Verify that all 10 decisions and blockers were preserved without data loss
        sess = get_last_session(self.repo_dir, file_path=self.session_file)
        self.assertIsNotNone(sess)
        self.assertEqual(len(sess.get("decisions", [])), 10)
        self.assertEqual(len(sess.get("blockers", [])), 10)
        self.assertEqual(len(sess.get("files_changed", {})), 10)


class TestMCPStdioServerLoop(unittest.TestCase):
    """End-to-end simulated stdio protocol test with multiple tool calls."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = os.path.realpath(os.path.join(self.temp_dir.name, "stdio-repo"))
        init_git_repo(self.repo_dir, "feat: stdio repo")
        self.session_file = os.path.join(self.temp_dir.name, "sessions.json")
        self.roadmap_file = os.path.join(self.temp_dir.name, "ROADMAP.md")
        with open(self.roadmap_file, "w") as f:
            f.write("# Roadmap\n- [ ] (stdio-repo) Implement parser <!-- id:e101 -->\n")

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_simulated_stdio_pipeline(self):
        requests = [
            # 1. initialize
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            # 2. tools/list
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            # 3. get_project_context
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_project_context", "arguments": {"project": self.repo_dir}}},
            # 4. update_session
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "update_session",
                    "arguments": {
                        "project": self.repo_dir,
                        "objective": "Stdio Loop Objective",
                        "status": "in_progress",
                        "next_action": "Verify stdio pipeline",
                    },
                },
            },
            # 5. get_current_goal
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "get_current_goal", "arguments": {"project": self.repo_dir}}},
            # 6. get_next_action
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "get_next_action", "arguments": {"project": self.repo_dir}}},
            # 7. get_open_tasks
            {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "get_open_tasks", "arguments": {"project": "stdio-repo"}}},
            # 8. mark_task_status
            {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "mark_task_status", "arguments": {"id": "e101", "status": "start"}}},
            # 9. get_recent_changes
            {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "get_recent_changes", "arguments": {"project": self.repo_dir}}},
            # 10. get_resume_handoff
            {"jsonrpc": "2.0", "id": 10, "method": "tools/call", "params": {"name": "get_resume_handoff", "arguments": {"project": self.repo_dir, "format": "json"}}},
        ]

        in_stream = StringIO("\n".join(json.dumps(r) for r in requests) + "\n")
        out_stream = StringIO()

        run_mcp_server(
            input_stream=in_stream,
            output_stream=out_stream,
            session_file=self.session_file,
            roadmap_file=self.roadmap_file,
            cwd=self.repo_dir,
        )

        responses = [json.loads(line) for line in out_stream.getvalue().splitlines() if line.strip()]
        self.assertEqual(len(responses), 10)

        # initialize check
        self.assertEqual(responses[0]["id"], 1)
        self.assertEqual(responses[0]["result"]["serverInfo"]["name"], "dev-context")

        # tools/list check: includes all 8 granular tools
        tools = [t["name"] for t in responses[1]["result"]["tools"]]
        for tname in (
            "get_project_context",
            "get_current_goal",
            "update_session",
            "get_open_tasks",
            "get_recent_changes",
            "mark_task_status",
            "get_next_action",
            "get_resume_handoff",
        ):
            self.assertIn(tname, tools)

        # get_project_context
        ctx_data = json.loads(responses[2]["result"]["content"][0]["text"])
        self.assertEqual(ctx_data["name"], "stdio-repo")

        # update_session
        up_data = json.loads(responses[3]["result"]["content"][0]["text"])
        self.assertTrue(up_data["success"])

        # get_current_goal
        goal_data = json.loads(responses[4]["result"]["content"][0]["text"])
        self.assertEqual(goal_data["objective"], "Stdio Loop Objective")

        # get_next_action
        next_data = json.loads(responses[5]["result"]["content"][0]["text"])
        self.assertEqual(next_data["next_action"], "Verify stdio pipeline")

        # get_open_tasks
        tasks_data = json.loads(responses[6]["result"]["content"][0]["text"])
        self.assertEqual(len(tasks_data), 1)
        self.assertEqual(tasks_data[0]["id"], "e101")

        # mark_task_status
        mark_data = json.loads(responses[7]["result"]["content"][0]["text"])
        self.assertTrue(mark_data["success"])

        # get_recent_changes
        rc_data = json.loads(responses[8]["result"]["content"][0]["text"])
        self.assertEqual(rc_data["project"], "stdio-repo")

        # get_resume_handoff
        handoff_data = json.loads(responses[9]["result"]["content"][0]["text"])
        self.assertEqual(handoff_data["project"], "stdio-repo")
        self.assertEqual(handoff_data["objective"], "Stdio Loop Objective")


class TestDevContextMCPModuleDirectCallables(unittest.TestCase):
    """Tests the Python callable wrappers exported in dev_context_mcp."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = os.path.realpath(os.path.join(self.temp_dir.name, "direct-repo"))
        init_git_repo(self.repo_dir, "feat: direct callables test")
        self.session_file = os.path.join(self.temp_dir.name, "sessions.json")
        self.roadmap_file = os.path.join(self.temp_dir.name, "ROADMAP.md")
        with open(self.roadmap_file, "w") as f:
            f.write("# Roadmap\n- [ ] (direct-repo) Task One <!-- id:f101 -->\n")

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_direct_callables_execution(self):
        # 1. get_project_context
        r1 = dev_context_mcp.get_project_context(project=self.repo_dir, session_file=self.session_file)
        self.assertFalse(r1["result"]["isError"])
        d1 = json.loads(r1["result"]["content"][0]["text"])
        self.assertEqual(d1["name"], "direct-repo")

        # 2. update_session
        r2 = dev_context_mcp.update_session(
            project=self.repo_dir,
            objective="Direct callable test",
            status="in_progress",
            next_action="Run direct assertions",
            blocker="None so far",
            decision={"decision": "Wrap in direct helpers", "rationale": "High developer ergonomics"},
            file_changed={"path": "dev_context_mcp.py", "why": "Add python wrappers"},
            session_file=self.session_file,
        )
        self.assertFalse(r2["result"]["isError"])

        # 3. get_current_goal
        r3 = dev_context_mcp.get_current_goal(project=self.repo_dir, session_file=self.session_file)
        self.assertFalse(r3["result"]["isError"])
        d3 = json.loads(r3["result"]["content"][0]["text"])
        self.assertEqual(d3["objective"], "Direct callable test")

        # 4. get_open_tasks
        r4 = dev_context_mcp.get_open_tasks(project="direct-repo", roadmap_file=self.roadmap_file)
        d4 = json.loads(r4["result"]["content"][0]["text"])
        self.assertEqual(len(d4), 1)
        self.assertEqual(d4[0]["id"], "f101")

        # 5. mark_task_status
        r5 = dev_context_mcp.mark_task_status("f101", "done", roadmap_file=self.roadmap_file)
        self.assertFalse(r5["result"]["isError"])

        # 6. get_next_action
        r6 = dev_context_mcp.get_next_action(project=self.repo_dir, session_file=self.session_file)
        d6 = json.loads(r6["result"]["content"][0]["text"])
        self.assertEqual(d6["next_action"], "Run direct assertions")

        # 7. get_recent_changes
        r7 = dev_context_mcp.get_recent_changes(project=self.repo_dir, session_file=self.session_file)
        self.assertFalse(r7["result"]["isError"])

        # 8. get_resume_handoff
        r8 = dev_context_mcp.get_resume_handoff(project=self.repo_dir, format="json", session_file=self.session_file)
        self.assertFalse(r8["result"]["isError"])
        d8 = json.loads(r8["result"]["content"][0]["text"])
        self.assertEqual(d8["objective"], "Direct callable test")


if __name__ == "__main__":
    unittest.main()
