#!/usr/bin/env python3
"""
Unit and integration tests for dev-context Local MCP Server (`dc mcp` and `dev_context_mcp.py`).
Tests JSON-RPC 2.0 stdio protocol, tool schema, tool execution, and error handling.
"""

import os
import sys
import json
import tempfile
import unittest
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
    get_last_session,
    get_open_tasks,
)


def init_git_repo(path, commit_msg="Initial commit"):
    """Helper to initialize a test git repository."""
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init", "-q", path], check=True)
    subprocess.run(["git", "-C", path, "config", "user.name", "MCP Tester"], check=True)
    subprocess.run(["git", "-C", path, "config", "user.email", "mcp@example.com"], check=True)
    readme = os.path.join(path, "README.md")
    with open(readme, "w") as f:
        f.write("# MCP Test Repo\n")
    subprocess.run(["git", "-C", path, "add", "README.md"], check=True)
    subprocess.run(["git", "-C", path, "commit", "-q", "-m", commit_msg], check=True)


class TestMCPProtocol(unittest.TestCase):
    """Tests for core JSON-RPC 2.0 protocol handling."""

    def test_initialize(self):
        req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "claude-code", "version": "1.0.0"},
            },
        }
        resp = handle_mcp_message(req)
        self.assertEqual(resp["jsonrpc"], "2.0")
        self.assertEqual(resp["id"], 1)
        self.assertIn("protocolVersion", resp["result"])
        self.assertIn("tools", resp["result"]["capabilities"])
        self.assertEqual(resp["result"]["serverInfo"]["name"], "dev-context")

    def test_notifications_produce_no_response(self):
        req = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }
        resp = handle_mcp_message(req)
        self.assertIsNone(resp)

    def test_ping(self):
        req = {"jsonrpc": "2.0", "id": 42, "method": "ping"}
        resp = handle_mcp_message(req)
        self.assertEqual(resp["id"], 42)
        self.assertEqual(resp["result"], {})

    def test_unknown_method_error(self):
        req = {"jsonrpc": "2.0", "id": 5, "method": "nonexistent/method"}
        resp = handle_mcp_message(req)
        self.assertEqual(resp["id"], 5)
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], -32601)

    def test_invalid_request_type(self):
        resp = handle_mcp_message("not a dict")
        self.assertEqual(resp["error"]["code"], -32600)


class TestMCPToolsList(unittest.TestCase):
    """Tests for tools/list method and schema definitions."""

    def test_tools_list_contains_all_four_tools(self):
        req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        resp = handle_mcp_message(req)
        self.assertEqual(resp["id"], 2)
        tools = resp["result"]["tools"]
        tool_names = [t["name"] for t in tools]
        self.assertIn("get_active_context", tool_names)
        self.assertIn("list_tasks", tool_names)
        self.assertIn("set_goal", tool_names)
        self.assertIn("update_task", tool_names)

    def test_tools_input_schemas(self):
        tools_by_name = {t["name"]: t for t in MCP_TOOLS}
        # set_goal schema
        self.assertIn("goal", tools_by_name["set_goal"]["inputSchema"]["properties"])
        self.assertIn("goal", tools_by_name["set_goal"]["inputSchema"]["required"])

        # update_task schema
        self.assertIn("id", tools_by_name["update_task"]["inputSchema"]["properties"])
        self.assertIn("action", tools_by_name["update_task"]["inputSchema"]["properties"])
        self.assertIn("action", tools_by_name["update_task"]["inputSchema"]["required"])


class TestMCPToolsExecution(unittest.TestCase):
    """Tests for executing tools via tools/call."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = self.temp_dir.name
        self.repo_dir = os.path.join(self.workspace, "mcp-test-repo")
        init_git_repo(self.repo_dir, "feat: mcp initial")
        self.session_file = os.path.join(self.workspace, "sessions.json")
        self.roadmap_file = os.path.join(self.workspace, "ROADMAP.md")
        with open(self.roadmap_file, "w") as f:
            f.write(
                "# Roadmap\n\n"
                "## Active Sprint\n"
                "- [ ] (besynx) Setup p2p sync <!-- id:b101 -->\n"
                "- [-] (laya) Filter downloads <!-- id:b102 -->\n"
                "- [!] (dev-context) Blocked issue <!-- id:b103 -->\n"
            )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_tool_call_get_active_context(self):
        set_active_goal(self.repo_dir, "Verify MCP context tool", file_path=self.session_file)
        req = {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "get_active_context",
                "arguments": {},
            },
        }
        resp = handle_mcp_message(
            req,
            session_file=self.session_file,
            roadmap_file=self.roadmap_file,
            cwd=self.repo_dir,
        )
        self.assertEqual(resp["id"], 10)
        self.assertFalse(resp["result"]["isError"])
        content = json.loads(resp["result"]["content"][0]["text"])
        self.assertEqual(content["active_project"]["name"], "mcp-test-repo")
        self.assertEqual(content["session_goal"], "Verify MCP context tool")
        self.assertIn(content["branch"], ("main", "master"))
        self.assertEqual(len(content["priority_tasks"]), 3)

    def test_tool_call_list_tasks_unfiltered_and_filtered(self):
        # 1. Unfiltered
        req = {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {"name": "list_tasks", "arguments": {}},
        }
        resp = handle_mcp_message(req, roadmap_file=self.roadmap_file, cwd=self.repo_dir)
        tasks = json.loads(resp["result"]["content"][0]["text"])
        self.assertEqual(len(tasks), 3)

        # 2. Filtered by project 'besynx'
        req_filt = {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {"name": "list_tasks", "arguments": {"project": "besynx"}},
        }
        resp_filt = handle_mcp_message(req_filt, roadmap_file=self.roadmap_file, cwd=self.repo_dir)
        tasks_filt = json.loads(resp_filt["result"]["content"][0]["text"])
        self.assertEqual(len(tasks_filt), 1)
        self.assertEqual(tasks_filt[0]["id"], "b101")
        self.assertEqual(tasks_filt[0]["project"], "besynx")

    def test_tool_call_set_goal(self):
        req = {
            "jsonrpc": "2.0",
            "id": 13,
            "method": "tools/call",
            "params": {
                "name": "set_goal",
                "arguments": {"goal": "Optimize query latencies"},
            },
        }
        resp = handle_mcp_message(
            req,
            session_file=self.session_file,
            roadmap_file=self.roadmap_file,
            cwd=self.repo_dir,
        )
        self.assertEqual(resp["id"], 13)
        self.assertFalse(resp["result"]["isError"])
        self.assertIn("Optimize query latencies", resp["result"]["content"][0]["text"])

        # Check persisted session
        sess = get_last_session(self.repo_dir, file_path=self.session_file)
        self.assertEqual(sess["goal"], "Optimize query latencies")

    def test_tool_call_set_goal_missing_argument(self):
        req = {
            "jsonrpc": "2.0",
            "id": 14,
            "method": "tools/call",
            "params": {"name": "set_goal", "arguments": {}},
        }
        resp = handle_mcp_message(req, session_file=self.session_file, cwd=self.repo_dir)
        self.assertTrue(resp["result"]["isError"])

    def test_tool_call_update_task_lifecycle(self):
        # 1. start task b101
        req_start = {
            "jsonrpc": "2.0",
            "id": 15,
            "method": "tools/call",
            "params": {"name": "update_task", "arguments": {"id": "b101", "action": "start"}},
        }
        resp_start = handle_mcp_message(req_start, roadmap_file=self.roadmap_file)
        self.assertFalse(resp_start["result"]["isError"])
        tasks, _ = get_open_tasks(self.roadmap_file)
        t_b101 = next(t for t in tasks if t["id"] == "b101")
        self.assertEqual(t_b101["state"], "in_progress")

        # 2. block task b101
        req_block = {
            "jsonrpc": "2.0",
            "id": 16,
            "method": "tools/call",
            "params": {"name": "update_task", "arguments": {"id": "b101", "action": "block"}},
        }
        resp_block = handle_mcp_message(req_block, roadmap_file=self.roadmap_file)
        self.assertFalse(resp_block["result"]["isError"])
        tasks, _ = get_open_tasks(self.roadmap_file)
        t_b101 = next(t for t in tasks if t["id"] == "b101")
        self.assertEqual(t_b101["state"], "blocked")

        # 3. done task b101
        req_done = {
            "jsonrpc": "2.0",
            "id": 17,
            "method": "tools/call",
            "params": {"name": "update_task", "arguments": {"id": "b101", "action": "done"}},
        }
        resp_done = handle_mcp_message(req_done, roadmap_file=self.roadmap_file)
        self.assertFalse(resp_done["result"]["isError"])

        # 4. rm task b102
        req_rm = {
            "jsonrpc": "2.0",
            "id": 18,
            "method": "tools/call",
            "params": {"name": "update_task", "arguments": {"id": "b102", "action": "rm"}},
        }
        resp_rm = handle_mcp_message(req_rm, roadmap_file=self.roadmap_file)
        self.assertFalse(resp_rm["result"]["isError"])
        tasks, _ = get_open_tasks(self.roadmap_file)
        ids = [t["id"] for t in tasks]
        self.assertNotIn("b102", ids)

    def test_tool_call_update_task_invalid_action_and_id(self):
        # Invalid action
        req_bad = {
            "jsonrpc": "2.0",
            "id": 19,
            "method": "tools/call",
            "params": {"name": "update_task", "arguments": {"id": "b103", "action": "fly"}},
        }
        resp_bad = handle_mcp_message(req_bad, roadmap_file=self.roadmap_file)
        self.assertTrue(resp_bad["result"]["isError"])

        # Non-existent task ID
        req_missing = {
            "jsonrpc": "2.0",
            "id": 20,
            "method": "tools/call",
            "params": {"name": "update_task", "arguments": {"id": "ffff", "action": "done"}},
        }
        resp_missing = handle_mcp_message(req_missing, roadmap_file=self.roadmap_file)
        self.assertTrue(resp_missing["result"]["isError"])

    def test_tool_call_unknown_tool(self):
        req = {
            "jsonrpc": "2.0",
            "id": 21,
            "method": "tools/call",
            "params": {"name": "destroy_world", "arguments": {}},
        }
        resp = handle_mcp_message(req)
        self.assertEqual(resp["error"]["code"], -32601)


class TestMCPStdioServerLoop(unittest.TestCase):
    """Tests for run_mcp_server in-memory stream loop."""

    def test_run_mcp_server_in_memory(self):
        input_data = (
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n"
        )
        in_stream = StringIO(input_data)
        out_stream = StringIO()

        run_mcp_server(input_stream=in_stream, output_stream=out_stream)
        lines = [json.loads(l) for l in out_stream.getvalue().splitlines() if l.strip()]

        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["id"], 1)
        self.assertEqual(lines[0]["result"]["serverInfo"]["name"], "dev-context")
        self.assertEqual(lines[1]["id"], 2)
        self.assertGreaterEqual(len(lines[1]["result"]["tools"]), 4)


class TestMCPCLIProcess(unittest.TestCase):
    """End-to-end integration test running subprocess for `dev-context mcp` and `dev_context_mcp.py`."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = os.path.join(self.temp_dir.name, "process-repo")
        init_git_repo(self.repo_dir, "feat: subprocess test")
        self.bin_path = str(PROJECT_ROOT / "bin" / "dev-context")
        self.mcp_script = str(PROJECT_ROOT / "dev_context_mcp.py")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_dc_mcp_subprocess_interaction(self):
        proc = subprocess.Popen(
            ["python3", self.bin_path, "mcp"],
            cwd=self.repo_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        init_req = json.dumps({"jsonrpc": "2.0", "id": 100, "method": "initialize", "params": {}}) + "\n"
        proc.stdin.write(init_req)
        proc.stdin.flush()

        resp_line = proc.stdout.readline()
        resp = json.loads(resp_line)
        self.assertEqual(resp["id"], 100)
        self.assertEqual(resp["result"]["serverInfo"]["name"], "dev-context")

        proc.stdin.close()
        proc.stdout.close()
        proc.stderr.close()
        proc.wait(timeout=5)
        self.assertEqual(proc.returncode, 0)

    def test_dev_context_mcp_py_subprocess_interaction(self):
        proc = subprocess.Popen(
            ["python3", self.mcp_script],
            cwd=self.repo_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        init_req = json.dumps({"jsonrpc": "2.0", "id": 200, "method": "initialize", "params": {}}) + "\n"
        proc.stdin.write(init_req)
        proc.stdin.flush()

        resp_line = proc.stdout.readline()
        resp = json.loads(resp_line)
        self.assertEqual(resp["id"], 200)
        self.assertEqual(resp["result"]["serverInfo"]["name"], "dev-context")

        proc.stdin.close()
        proc.stdout.close()
        proc.stderr.close()
        proc.wait(timeout=5)
        self.assertEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
