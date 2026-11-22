<div align="center">
  <a href="https://github.com/whysooraj/dev-context">
    <img src="assets/logo.png" alt="dev-context logo" width="850" />
  </a>
</div>

<div align="center">
  <p><strong>Sub-second pre-flight context dashboard, native agent injection, and task engine for terminal coding agents.</strong></p>
  <p>Eliminate blank-line paralysis before Antigravity, Claude Code, Cursor, or Codex opens.</p>
</div>

---

## One-Line Install

Run the interactive multi-step installer:

```bash
curl -fsSL https://raw.githubusercontent.com/whysooraj/dev-context/main/install.sh | bash
```

The installer detects your local environment and guides you through 5 setup steps:

1. **Coding Agent Hooks**: Wraps detected agents (`agy`, `claude`, `codex`) or custom CLI commands.
2. **Shell Environment**: Writes clean, non-destructive hooks for Fish (`conf.d/dev_context_wrappers.fish`), Bash (`~/.bashrc`), or Zsh (`~/.zshrc`).
3. **Binary Location**: Installs standalone `dev-context` and short `dc` alias to `~/.local/bin/`.
4. **Focus Queue**: Scaffolds a starter `ROADMAP.md` in your projects directory.
5. **Native Agent Setup**: Configures Model Context Protocol (MCP) server for Claude Code and Cursor.

---

## The Problem

When launching terminal AI coding agents, you are greeted by an empty prompt line:

```text
> What would you like to work on?
_
```

If you manage multiple open-source repositories or work solo across projects:

- You forget which repositories currently have uncommitted working trees or dirty branches.
- You lose track of which repo you were touching earlier in the day.
- Your backlog ideas remain scattered across tabs, issue trackers, and scratchpads.
- Context switching cost delays getting into deep flow.

`dev-context` resolves this in under 150ms before your agent cursor appears.

---

## Performance Benchmarks

`dev-context` is built with a pure Python standard-library engine using parallel worktree inspection and thread-pool execution. No external daemon or database is required.

Benchmark executed across synthetic multi-depth Git workspaces (commits, branch logs, staged/unstaged changes, skip directories):

| Repositories | Discovered | Min Latency | Mean Latency | p95 Latency | Max Latency |
| ------------ | ---------- | ----------- | ------------ | ----------- | ----------- |
| 10 repos     | 10 repos   | 21ms        | 25ms         | 28ms        | 31ms        |
| 50 repos     | 50 repos   | 115ms       | 127ms        | 138ms       | 145ms       |
| 100 repos    | 100 repos  | 238ms       | 256ms        | 272ms       | 289ms       |

Run the benchmark suite on your own machine:

```bash
python3 benchmarks/benchmark.py --scales 10 50 100 --iterations 5
```

---

## How It Works

<div align="center">
  <img src="assets/architecture.png" alt="dev-context execution flow architecture" width="100%" />
</div>

1. **Trigger**: You invoke `agy`, `claude`, `codex`, or `dc` in your terminal.
2. **Pre-Flight Hook**: An interactive shell wrapper intercepts the command without patching or modifying agent binaries.
3. **Sub-250ms Probe**: A pure Python probe scans git status, uncommitted trees across your projects directory, recent commits, and your Markdown focus queue.
4. **HUD Telemetry**: Formatted ANSI telemetry is printed to the terminal.
5. **Agent Hand-off**: The coding agent loads immediately below the telemetry, giving you instant operational context.

---

## Telemetry Output Preview

```text
--- DEV FLIGHT CONTEXT ---
[*] my-api-service (main) [CLEAN]
    Last commit (20 minutes ago): feat: add rate limiting middleware

[!] In-Progress / Uncommitted Work:
    * web-frontend (3 modified) - 45 minutes ago: fix: navigation layout
    * auth-service (2 modified) - 3 hours ago: test: add token verification tests

[+] Recent Activity:
    * worker-pipeline        2 hours ago     -> chore: bump dependencies
    * docs-site              Yesterday       -> docs: update deployment guide

[=] Focus Queue (ROADMAP.md):
    ## Active Sprint
    [1] [a101] [TODO] (my-api-service) add redis cache layer
    [2] [a102] [IN-PROGRESS] (web-frontend) responsive mobile navbar
    ## Ideas Backlog
    [3] [a103] [TODO] (auth-service) webauthn passkey support
--------------------------
```

---

## Session Continuity Engine

`dev-context` automatically records session checkpoints whenever you run the flight check or update goals:

```bash
# Record active goal for current repository
dc goal "Implement Task 4: Native Agent Injection & MCP Server"

# Query active goal
dc goal

# View session continuity card, footprint stats, and modified files
dc session
```

### Footprint Calculation

Tracks uncommitted changes and diff stats across working trees:

- Unstaged and staged line statistics via `git diff --shortstat` (e.g. `+45 -12 across 3 files`).
- List of modified and touched files.
- Persisted in atomic session store at `~/.config/dev-context/sessions.json`.

---

## Stable IDs and Multi-State Tasks

Task lists in `ROADMAP.md` use deterministic 4-character hex tags for rock-solid stability:

```markdown
## Active Sprint
- [ ] (besynx) Setup p2p sync <!-- id:b101 -->
- [-] (laya) Filter downloads <!-- id:b102 -->
- [!] (dev-context) Blocked issue <!-- id:b103 -->
- [x] (dev-context) Initial test suite <!-- id:b104 -->
```

Supported States:
- `[TODO]` (`- [ ]`): Open task
- `[IN-PROGRESS]` (`- [-]` or `- [~]`): Work in progress
- `[BLOCKED]` (`- [!]`): Blocked on dependency
- `[DONE]` (`- [x]`): Completed

### Task Commands

```bash
# Add a high-priority task with auto-generated ID
dc add "my-api-service: add redis cache layer"

# Add a task scoped to a specific project
dc add -p laya "folder preview before move"

# Add an idea to the backlog
dc idea -p auth-service "webauthn passkey support"

# View open tasks with stable IDs and state badges
dc list

# Filter open tasks for a specific project
dc list -p laya

# Mark task in-progress by ID or index
dc start b101
dc start 1

# Mark task blocked
dc block b101

# Mark task complete
dc done b101
dc done 1

# Delete task by ID or index
dc rm b101

# Scope task operations to current repository ROADMAP.md
dc add -l "add dry-run unit test"
dc list -l
dc done -l 1
```

---

## Native Agent Injection (`dc export`)

Pipe structured pre-flight context directly into AI coding agents upon startup:

```bash
# Pipe context briefing into Claude Code
claude -p "$(dc export)"

# Explicit agent prompt format
claude -p "$(dc export --agent)"

# Structured JSON export for agent automation pipelines
dc export --json | jq .
```

Sample JSON Export:

```json
{
  "active_project": {
    "name": "dev-context",
    "path": "/home/user/Projects/dev-context",
    "in_git": true,
    "branch": "main",
    "status": "clean",
    "dirty_count": 0,
    "last_commit": {
      "relative_time": "15 minutes ago",
      "subject": "feat: add native agent export"
    }
  },
  "session_goal": "Implement Task 4: Native Agent Injection",
  "footprint": {
    "summary": "+85 -10 across 3 files",
    "files": ["bin/dev-context", "README.md", "tests/test_export.py"]
  },
  "priority_tasks": [
    {
      "id": "a101",
      "state": "open",
      "state_label": "[TODO]",
      "text": "Add local MCP server",
      "project": "dev-context"
    }
  ],
  "workspace_alerts": [
    {
      "name": "besynx",
      "path": "/home/user/Projects/besynx",
      "dirty_count": 2,
      "rel_time": "1 hour ago",
      "subject": "feat: p2p sync"
    }
  ]
}
```

---

## Built-in Local MCP Server (`dc mcp`)

`dev-context` contains a zero-dependency JSON-RPC 2.0 Model Context Protocol (MCP) server that runs over standard I/O.

### Configure with Claude Code

Register the server with Claude Code:

```bash
claude mcp add dev-context -- dc mcp
```

Or run the automated setup command:

```bash
dc setup-agent claude
```

This registers the MCP server and writes project rules to `.claude/rules/dev-context.md`.

### Configure with Cursor

Generate Cursor rules in your workspace:

```bash
dc setup-agent cursor
```

Writes `.cursorrules` and `.cursor/rules/dev-context.mdc`.

### Exposed MCP Tools

| Tool | Parameters | Description |
| ---- | ---------- | ----------- |
| `get_active_context` | None | Returns active project, branch, session goal, footprint, recent files, and other dirty workspace repos. |
| `list_tasks` | `project` (optional string) | Returns tasks from the focus queue with stable IDs, states, and text. |
| `set_goal` | `goal` (required string) | Updates the session goal for the current active project. |
| `update_task` | `id` (string), `action` (`start`, `done`, `block`, `rm`) | Updates task state or deletes task by stable ID or index. |

---

## Workspace Discovery Logic

`dev-context` scans your workspace without external database services:

| Scan Target | Detection Method | Output Role |
| ----------- | ---------------- | ----------- |
| Current Directory | `git status --porcelain` + `git branch` | Shows dirty files, active branch, and last commit |
| Workspace Repos | Scans `~/Projects/*/.git` (or `$DEV_CONTEXT_DIR`) | Surfaces repos with uncommitted work |
| Recent Activity | `git log -1 --format=%ct|%cr|%s` | Shows top 4 recently modified projects |
| Focus Queue | Parses `- [ ] ` checklist items in `ROADMAP.md` | Indexes sprint priorities and backlog ideas |

### Roadmap File Resolution

The task manager searches for task lists in the following order:

1. Current repository `ROADMAP.md` or `TODO.md` (when inside a git repo)
2. Workspace root `~/Projects/ROADMAP.md`
3. Home directory `~/.roadmap.md`

---

## Shell Integration Reference

The installer configures interactive shell functions that pass all arguments and completions directly to the underlying binaries.

### Fish Shell (`~/.config/fish/conf.d/dev_context_wrappers.fish`)

```fish
function agy --wraps agy --description 'Run dev-context flight check then agy'
    if test -z "$DEV_CONTEXT_SKIP"; and status is-interactive
        dev-context
    end
    command agy $argv
end

function claude --wraps claude --description 'Run dev-context flight check then claude'
    if test -z "$DEV_CONTEXT_SKIP"; and status is-interactive
        dev-context
    end
    command claude $argv
end

function codex --wraps codex --description 'Run dev-context flight check then codex'
    if test -z "$DEV_CONTEXT_SKIP"; and status is-interactive
        dev-context
    end
    command codex $argv
end
```

### Bash / Zsh (`~/.bashrc` or `~/.zshrc`)

```bash
agy() {
  [ -z "$DEV_CONTEXT_SKIP" ] && [ -t 1 ] && dev-context
  command agy "$@"
}

claude() {
  [ -z "$DEV_CONTEXT_SKIP" ] && [ -t 1 ] && dev-context
  command claude "$@"
}

codex() {
  [ -z "$DEV_CONTEXT_SKIP" ] && [ -t 1 ] && dev-context
  command codex "$@"
}
```

---

## Manual Installation

To build and run from source:

```bash
git clone https://github.com/whysooraj/dev-context.git ~/Projects/dev-context
cd ~/Projects/dev-context
./install.sh
```

Or manually copy the script to your executable PATH:

```bash
cp bin/dev-context ~/.local/bin/dev-context
ln -sf ~/.local/bin/dev-context ~/.local/bin/dc
chmod +x ~/.local/bin/dev-context
```

---

## Environment Variables

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `DEV_CONTEXT_DIR` | `~/Projects` | Base directory scanned for git repositories and roadmap |
| `DEV_CONTEXT_SKIP` | `0` | Set to `1` to bypass the pre-flight check for automation or subshells |
| `DEV_CONTEXT_SESSION_FILE` | None | Override path for sessions JSON store |
| `DEV_CONTEXT_ROADMAP_FILE` | None | Override path for roadmap markdown file |

---

## License

MIT
