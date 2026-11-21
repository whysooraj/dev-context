<div align="center">
  <img src="assets/logo.png" alt="dev-context logo" width="700" />
  <p>Instant pre-flight context recovery and flight check for CLI coding agents.</p>
</div>

---

## Overview

When launching terminal coding agents (`agy`, `claude`, `codex`), the prompt often starts with a blank line. If you maintain multiple open-source projects or work solo, it is easy to forget in-flight branches, uncommitted experiments, and backlog priorities.

`dev-context` runs an ultra-fast (< 350ms) flight check right before your coding agent begins:

- **Current Repository State**: Shows current branch, modified files, and latest commit subject.
- **Uncommitted Workspace Repos**: Scans your workspace (`~/Projects`) to surface repos with uncommitted work.
- **Recent Project Activity**: Lists recently committed projects so you know where you left off.
- **Focus Queue**: Surfaces active sprint goals and backlog ideas from `ROADMAP.md` or `TODO.md`.

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
   - [ ] laya-file-organizer: add interactive folder preview before sorting
   - [ ] spotify-roaster: improve roast variety and cache Spotify auth token
   - [ ] CodeWeaver: verify npx global execution path
──────────────────────────
```

## Quickstart

### 1. Install

Clone and run the installer:

```bash
git clone https://github.com/whysooraj/dev-context.git ~/Projects/dev-context
cd ~/Projects/dev-context
./install.sh
```

Or copy `bin/dev-context` directly into your path:

```bash
cp bin/dev-context ~/.local/bin/dev-context
chmod +x ~/.local/bin/dev-context
```

### 2. Shell Integration

`dev-context` hooks cleanly into your interactive shell functions without modifying the agent binaries.

#### Fish Shell (`~/.config/fish/conf.d/dev_context_wrappers.fish`)

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

#### Bash / Zsh (`~/.bashrc` or `~/.zshrc`)

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

## Roadmap & Focus Queue

`dev-context` checks for a task list in the following order:

1. Current directory `ROADMAP.md` or `TODO.md` (if inside a repo)
2. Workspace `~/Projects/ROADMAP.md`
3. User home `~/.roadmap.md`

Items formatted with `- [ ]` and markdown headings `## ` are extracted and displayed at the bottom of the flight check.

## Environment Variables

- `DEV_CONTEXT_DIR`: Override default workspace path (default: `~/Projects`).
- `DEV_CONTEXT_SKIP=1`: Temporarily bypass flight check for scripts or subshells.

## License

MIT
