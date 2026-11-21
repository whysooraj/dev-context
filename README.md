<div align="center">
  <img src="assets/logo.png" alt="dev-context logo" width="700" />
  <p>Instant pre-flight context recovery and flight check for CLI coding agents.</p>
</div>

---

## One-Line Install

Run the interactive multi-step installer:

```bash
curl -fsSL https://raw.githubusercontent.com/whysooraj/dev-context/main/install.sh | bash
```

The installer detects your environment and guides you through 4 setup steps:

1. **Agent Selection**: Wraps detected coding agents (`agy`, `claude`, `codex`) or custom agents.
2. **Shell Integration**: Configures Fish (`conf.d/dev_context_wrappers.fish`), Bash (`~/.bashrc`), or Zsh (`~/.zshrc`).
3. **Binary Location**: Installs standalone `dev-context` binary to `~/.local/bin/`.
4. **Focus Queue**: Sets up a starter `ROADMAP.md` in your workspace.

---

## Overview

When launching terminal coding agents (`agy`, `claude`, `codex`), the prompt starts with a blank line. If you maintain multiple open-source projects or work solo, it is easy to lose track of in-flight branches, dirty working trees, and queued ideas.

`dev-context` executes a sub-second (< 350ms) flight check before the prompt appears:

- **Current Repository State**: Active branch, uncommitted files, and last commit subject.
- **Uncommitted Workspace Repos**: Scans your workspace (`~/Projects`) to highlight repositories with uncommitted changes.
- **Recent Project Activity**: Lists recently modified repositories so you know what was worked on yesterday.
- **Focus Queue with IDs**: Displays pending tasks with numbers so you can check them off instantly.

## Output Preview

```text
─── DEV FLIGHT CONTEXT ───
📍 laya-file-organizer (master) [CLEAN]
   Last commit (35 minutes ago): feat: add pyproject.toml and curl install.sh script

⚡ In-Progress / Uncommitted Work:
   • why (3 modified) — 38 minutes ago: feat: add live deployed links
   • RF-FMNN (14 modified) — 2 days ago: perf: vectorize batch inference
   • aislop (1 modified) — 7 weeks ago: release: 0.17.0 (#429)

🕒 Recent Activity:
   • prism                  7 minutes ago    -> feat: add interactive global vs local proj
   • context-bridge         7 minutes ago    -> feat: add interactive global vs local proj
   • TradePilot             11 minutes ago   -> feat: add one-line installer script

📋 Focus Queue (ROADMAP.md):
   ## Active Sprint
   [1] laya-file-organizer: add interactive folder preview before sorting
   [2] spotify-roaster: improve roast variety and cache Spotify auth token
   [3] CodeWeaver: verify npx global execution path
   ## Ideas Backlog
   [4] Turnitout-Humanizer: local quantized model fallback
──────────────────────────
```

---

## Instant Task Management (No Text Editor Required)

Use `dc` (or `dev-context`) directly from the CLI:

```bash
# View dashboard flight check
dc

# Add to active sprint
dc add "spotify-roaster: fix auth token refresh"

# Quick add an idea to backlog
dc idea "besynx: explore WebRTC datachannel sync"

# View open tasks with IDs
dc list

# Mark task #2 complete
dc done 2

# Delete task #3
dc rm 3

# Target current repository instead of global workspace
dc add -l "add dry-run unit test"
dc done -l 1
```

All commands update the human-readable `ROADMAP.md` while remaining 100% git-trackable.

---

## Manual Installation

If you prefer to clone and install locally:

```bash
git clone https://github.com/whysooraj/dev-context.git ~/Projects/dev-context
cd ~/Projects/dev-context
./install.sh
```

## Shell Integration Details

`dev-context` wraps CLI commands without modifying or monkey-patching binaries.

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

## Environment Variables

- `DEV_CONTEXT_DIR`: Override base projects directory (default: `~/Projects`).
- `DEV_CONTEXT_SKIP=1`: Temporarily bypass flight check for scripts or subshells.

## License

MIT
