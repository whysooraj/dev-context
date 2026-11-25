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

import json
import sys
from pathlib import Path

# Add project root to sys.path
_root = Path(__file__).resolve().parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


MCP_TOOLS = [
    {
        "name": "get_project_context",
        "description": "Returns compact project metadata (name, branch, path, remote url, purpose/summary from README or session, last commit, dirty count).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Optional project name or filesystem path (defaults to cwd)",
                }
            },
        },
    },
    {
        "name": "get_current_goal",
        "description": "Returns active objective, status ('in_progress'|'blocked'|'completed'), last_step, next_action, and active blockers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Optional project name or filesystem path (defaults to cwd)",
                }
            },
        },
    },
    {
        "name": "update_session",
        "description": "Atomic, thread-safe session update using update_session. Returns success confirmation and updated session state.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Optional project name or filesystem path (defaults to cwd)",
                },
                "objective": {
                    "type": "string",
                    "description": "Active session goal or objective",
                },
                "status": {
                    "type": "string",
                    "enum": ["in_progress", "blocked", "completed"],
                    "description": "Active work status",
                },
                "last_step": {
                    "type": "string",
                    "description": "Last completed concrete step",
                },
                "next_action": {
                    "type": "string",
                    "description": "Immediate concrete next action",
                },
                "blocker": {
                    "type": "string",
                    "description": "Blocker description to append to active blockers list",
                },
                "decision": {
                    "type": "object",
                    "description": "Architecture/design decision record",
                    "properties": {
                        "decision": {"type": "string", "description": "What was decided"},
                        "rationale": {"type": "string", "description": "Why this choice was made"},
                        "rejected_alternatives": {
                            "type": ["string", "array"],
                            "description": "Alternative options considered and rejected",
                        },
                    },
                    "required": ["decision"],
                },
                "file_changed": {
                    "type": "object",
                    "description": "File change record",
                    "properties": {
                        "path": {"type": "string", "description": "Relative or absolute file path"},
                        "why": {"type": "string", "description": "Reason for modification"},
                    },
                    "required": ["path"],
                },
            },
        },
    },
    {
        "name": "get_open_tasks",
        "description": "Returns filtered list of open and blocked tasks with stable IDs, states, project tags, and text.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Optional project name filter (e.g. 'besynx', 'dev-context')",
                },
                "include_blocked": {
                    "type": "boolean",
                    "description": "Whether to include blocked tasks (default: true)",
                },
            },
        },
    },
    {
        "name": "get_recent_changes",
        "description": "Returns uncommitted diff footprint summary (+X -Y), list of modified files, and recent commit messages.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Optional project name or filesystem path (defaults to cwd)",
                },
                "limit_commits": {
                    "type": "integer",
                    "description": "Maximum number of recent commits to return (default: 5)",
                },
            },
        },
    },
    {
        "name": "mark_task_status",
        "description": "Update task state or remove a task by stable ID with status action and optional reason.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Task stable 4-hex ID (e.g. 'a101') or numeric index",
                },
                "status": {
                    "type": "string",
                    "enum": ["start", "done", "block", "rm"],
                    "description": "Status action: 'start' (in_progress), 'done' (completed), 'block' (blocked), or 'rm' (delete)",
                },
                "reason": {
                    "type": "string",
                    "description": "Optional reason explaining why the task is blocked",
                },
            },
            "required": ["id", "status"],
        },
    },
    {
        "name": "get_next_action",
        "description": "Returns explicit next action string from session, or top priority task from roadmap if no session next_action set.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Optional project name or filesystem path (defaults to cwd)",
                },
            },
        },
    },
    {
        "name": "get_resume_handoff",
        "description": "Returns the full, compact dc resume handoff payload for instant agent cross-session resumption.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Optional project name or filesystem path (defaults to cwd)",
                },
                "format": {
                    "type": "string",
                    "enum": ["markdown", "json"],
                    "description": "Output format: 'markdown' or 'json' (default: markdown)",
                },
            },
        },
    },
    # Backward compatibility tools
    {
        "name": "get_active_context",
        "description": "Returns active project, branch, session goal, footprint (modified files and diff stats), recent files, and other dirty workspace repos.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "list_tasks",
        "description": "Returns tasks from the roadmap focus queue with stable IDs, states, and text.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Optional project filter (e.g. 'besynx', 'dev-context')",
                }
            },
        },
    },
    {
        "name": "set_goal",
        "description": "Updates current project session goal.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "Session goal objective",
                }
            },
            "required": ["goal"],
        },
    },
    {
        "name": "update_task",
        "description": "Update task state or delete a task by stable ID or index.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Task stable 4-hex ID (e.g. 'a101') or numeric index",
                },
                "action": {
                    "type": "string",
                    "enum": ["start", "done", "block", "rm"],
                    "description": "Action to perform: 'start' (mark in_progress), 'done' (mark completed), 'block' (mark blocked), or 'rm' (delete task)",
                },
            },
            "required": ["id", "action"],
        },
    },
]


def _rpc_error(req_id, code, message):
    """Format standard JSON-RPC 2.0 error response."""
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": code,
            "message": message,
        },
    }


def _get_tool_dispatcher():
    """Resolve core tool call dispatcher without circular imports."""
    core = sys.modules.get("dev_context_bin")
    if core is not None and hasattr(core, "handle_mcp_tool_call"):
        return core.handle_mcp_tool_call
    import dev_context
    return dev_context.handle_mcp_tool_call


def handle_mcp_tool_call(req_id, tool_name, tool_args, session_file=None, roadmap_file=None, cwd=None):
    """Dispatch and execute an MCP tool invocation."""
    return _get_tool_dispatcher()(
        req_id,
        tool_name,
        tool_args,
        session_file=session_file,
        roadmap_file=roadmap_file,
        cwd=cwd,
    )


def handle_mcp_message(req, session_file=None, roadmap_file=None, cwd=None, tool_dispatcher=None):
    """Process a single JSON-RPC 2.0 MCP message."""
    if not isinstance(req, dict):
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32600, "message": "Invalid Request: expected JSON object"},
        }

    req_id = req.get("id")
    method = req.get("method")

    # Notifications (no id)
    if req_id is None:
        return None

    if method == "initialize":
        params = req.get("params", {})
        client_version = params.get("protocolVersion", "2024-11-05")
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": client_version,
                "capabilities": {
                    "tools": {},
                },
                "serverInfo": {
                    "name": "dev-context",
                    "version": "1.0.0",
                },
            },
        }

    elif method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    elif method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": MCP_TOOLS}}

    elif method == "tools/call":
        params = req.get("params")
        if not isinstance(params, dict):
            return _rpc_error(req_id, -32602, "Invalid params: 'params' must be an object")
        tool_name = params.get("name")
        if not tool_name or not isinstance(tool_name, str):
            return _rpc_error(req_id, -32602, "Missing or invalid tool name")
        tool_args = params.get("arguments", {})
        if not isinstance(tool_args, dict):
            return _rpc_error(req_id, -32602, "Invalid params: 'arguments' must be an object")
        dispatch = tool_dispatcher or _get_tool_dispatcher()
        return dispatch(req_id, tool_name, tool_args, session_file=session_file, roadmap_file=roadmap_file, cwd=cwd)

    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32601,
                "message": f"Method not found: {method}",
            },
        }


def run_mcp_server(input_stream=None, output_stream=None, session_file=None, roadmap_file=None, cwd=None, tool_dispatcher=None):
    """
    Run zero-dependency stdio JSON-RPC 2.0 MCP server loop.
    Reads line-delimited JSON-RPC from input_stream (stdin by default),
    writes line-delimited JSON-RPC to output_stream (stdout by default).
    """
    if input_stream is None:
        input_stream = sys.stdin
    if output_stream is None:
        output_stream = sys.stdout

    for line in input_stream:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception as e:
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {str(e)}"},
            }
            output_stream.write(json.dumps(err_resp) + "\n")
            output_stream.flush()
            continue

        resp = handle_mcp_message(
            req,
            session_file=session_file,
            roadmap_file=roadmap_file,
            cwd=cwd,
            tool_dispatcher=tool_dispatcher,
        )
        if resp is not None:
            output_stream.write(json.dumps(resp) + "\n")
            output_stream.flush()


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
