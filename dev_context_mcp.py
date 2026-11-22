#!/usr/bin/env python3
"""
Zero-dependency stdio Model Context Protocol (MCP) server for dev-context.
Provides tools:
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


def main():
    run_mcp_server()


if __name__ == "__main__":
    main()
