#!/usr/bin/env python3
"""
Zero-dependency stdio Model Context Protocol (MCP) server for dev-context.
Provides tools:
- get_project_context
- get_current_goal
- update_session
- get_open_tasks
- get_recent_changes
- mark_task_status
- get_next_action
- get_resume_handoff
- get_active_context
- list_tasks
- set_goal
- update_task
"""

import sys
from pathlib import Path

# Add project root to sys.path
_root = Path(__file__).resolve().parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from dev_context import run_mcp_server, handle_mcp_message, handle_mcp_tool_call, MCP_TOOLS


def get_project_context(project=None, cwd=None, session_file=None):
    """Direct callable wrapper for get_project_context tool."""
    args = {}
    if project is not None:
        args["project"] = project
    return handle_mcp_tool_call("direct", "get_project_context", args, session_file=session_file, cwd=cwd)


def get_current_goal(project=None, cwd=None, session_file=None):
    """Direct callable wrapper for get_current_goal tool."""
    args = {}
    if project is not None:
        args["project"] = project
    return handle_mcp_tool_call("direct", "get_current_goal", args, session_file=session_file, cwd=cwd)


def update_session(project=None, objective=None, status=None, last_step=None, next_action=None, blocker=None, decision=None, file_changed=None, cwd=None, session_file=None):
    """Direct callable wrapper for update_session tool."""
    args = {}
    if project is not None:
        args["project"] = project
    if objective is not None:
        args["objective"] = objective
    if status is not None:
        args["status"] = status
    if last_step is not None:
        args["last_step"] = last_step
    if next_action is not None:
        args["next_action"] = next_action
    if blocker is not None:
        args["blocker"] = blocker
    if decision is not None:
        args["decision"] = decision
    if file_changed is not None:
        args["file_changed"] = file_changed
    return handle_mcp_tool_call("direct", "update_session", args, session_file=session_file, cwd=cwd)


def get_open_tasks(project=None, include_blocked=True, cwd=None, roadmap_file=None):
    """Direct callable wrapper for get_open_tasks tool."""
    args = {"include_blocked": include_blocked}
    if project is not None:
        args["project"] = project
    return handle_mcp_tool_call("direct", "get_open_tasks", args, roadmap_file=roadmap_file, cwd=cwd)


def get_recent_changes(project=None, limit_commits=5, cwd=None, session_file=None):
    """Direct callable wrapper for get_recent_changes tool."""
    args = {"limit_commits": limit_commits}
    if project is not None:
        args["project"] = project
    return handle_mcp_tool_call("direct", "get_recent_changes", args, session_file=session_file, cwd=cwd)


def mark_task_status(task_id, status, reason=None, cwd=None, roadmap_file=None, session_file=None):
    """Direct callable wrapper for mark_task_status tool."""
    args = {"id": task_id, "status": status}
    if reason is not None:
        args["reason"] = reason
    return handle_mcp_tool_call("direct", "mark_task_status", args, roadmap_file=roadmap_file, session_file=session_file, cwd=cwd)


def get_next_action(project=None, cwd=None, roadmap_file=None, session_file=None):
    """Direct callable wrapper for get_next_action tool."""
    args = {}
    if project is not None:
        args["project"] = project
    return handle_mcp_tool_call("direct", "get_next_action", args, roadmap_file=roadmap_file, session_file=session_file, cwd=cwd)


def get_resume_handoff(project=None, format="markdown", cwd=None, session_file=None):
    """Direct callable wrapper for get_resume_handoff tool."""
    args = {"format": format}
    if project is not None:
        args["project"] = project
    return handle_mcp_tool_call("direct", "get_resume_handoff", args, session_file=session_file, cwd=cwd)


def main():
    run_mcp_server()


if __name__ == "__main__":
    main()
