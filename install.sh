#!/usr/bin/env bash
# dev-context interactive multi-step installer
# Supports: curl -fsSL https://raw.githubusercontent.com/whysooraj/dev-context/main/install.sh | bash

set -e

# ANSI Colors
BOLD="\033[1m"
DIM="\033[2m"
RESET="\033[0m"
GREEN="\033[32m"
CYAN="\033[36m"
YELLOW="\033[33m"
BLUE="\033[34m"

# Connect stdin to terminal if piped via curl | bash
if [ ! -t 0 ] && [ -e /dev/tty ]; then
    exec < /dev/tty
fi

clear 2>/dev/null || true

echo -e "${BOLD}${CYAN}"
cat << 'EOF'
     _                             context
  __| | _____   __      ___ ___  _ __ | |_ _____  _| |_
 / _` |/ _ \ \ / /____ / __/ _ \| '_ \| __/ _ \ \/ / __|
| (_| |  __/\ V /_____| (_| (_) | | | | ||  __/>  <| |_
 \__,_|\___| \_/       \___\___/|_| |_|\__\___/_/\_\\__|
EOF
echo -e "${RESET}"
echo -e "${BOLD}Pre-flight Context Dashboard for Terminal Coding Agents${RESET}"
echo -e "${DIM}https://github.com/whysooraj/dev-context${RESET}"
echo -e "${DIM}──────────────────────────────────────────────────────────${RESET}\n"

# 1. Detect Agents
echo -e "${BOLD}[1/5] Detecting Installed AI Coding Agents...${RESET}"
AGENTS_FOUND=()
command -v agy >/dev/null 2>&1 && AGENTS_FOUND+=("agy")
command -v claude >/dev/null 2>&1 && AGENTS_FOUND+=("claude")
command -v codex >/dev/null 2>&1 && AGENTS_FOUND+=("codex")

if [ ${#AGENTS_FOUND[@]} -gt 0 ]; then
    for agent in "${AGENTS_FOUND[@]}"; do
        echo -e "  ${GREEN}✓${RESET} Found: ${BOLD}${agent}${RESET} (${DIM}$(command -v "$agent")${RESET})"
    done
else
    echo -e "  ${YELLOW}!${RESET} No agents currently detected on PATH."
fi
echo ""

# Ask agent selection
echo -e "${BOLD}Which coding agents should dev-context wrap?${RESET}"
echo -e "  1) All supported (agy, claude, codex) [Recommended]"
if [ ${#AGENTS_FOUND[@]} -gt 0 ]; then
    echo -e "  2) Detected only (${AGENTS_FOUND[*]})"
else
    echo -e "  2) agy only"
fi
echo -e "  3) Custom selection"
echo -e "  4) Skip agent wrapping (binary only)"
read -rp "Select option [1-4] (default 1): " agent_opt
agent_opt="${agent_opt:-1}"

SELECTED_AGENTS=()
case "$agent_opt" in
    1)
        SELECTED_AGENTS=("agy" "claude" "codex")
        ;;
    2)
        if [ ${#AGENTS_FOUND[@]} -gt 0 ]; then
            SELECTED_AGENTS=("${AGENTS_FOUND[@]}")
        else
            SELECTED_AGENTS=("agy")
        fi
        ;;
    3)
        echo -e "\nEnter agents separated by space (e.g. agy claude):"
        read -rp "> " custom_agents
        read -ra SELECTED_AGENTS <<< "$custom_agents"
        ;;
    4)
        SELECTED_AGENTS=()
        ;;
    *)
        SELECTED_AGENTS=("agy" "claude" "codex")
        ;;
esac

echo -e "Selected agents: ${CYAN}${SELECTED_AGENTS[*]:-None}${RESET}\n"

# 2. Detect Shells
echo -e "${BOLD}[2/5] Detecting Shell Environments...${RESET}"
SHELLS_FOUND=()
[ -d "${HOME}/.config/fish" ] && SHELLS_FOUND+=("fish")
[ -f "${HOME}/.bashrc" ] && SHELLS_FOUND+=("bash")
[ -f "${HOME}/.zshrc" ] && SHELLS_FOUND+=("zsh")

for sh in "${SHELLS_FOUND[@]}"; do
    echo -e "  ${GREEN}✓${RESET} Found config for: ${BOLD}${sh}${RESET}"
done
echo ""

echo -e "${BOLD}Which shells should be configured with wrappers?${RESET}"
echo -e "  1) All detected shells (${SHELLS_FOUND[*]}) [Recommended]"
echo -e "  2) Fish shell only"
echo -e "  3) Bash shell only (~/.bashrc)"
echo -e "  4) Zsh shell only (~/.zshrc)"
echo -e "  5) Skip shell modifications"
read -rp "Select option [1-5] (default 1): " shell_opt
shell_opt="${shell_opt:-1}"

SELECTED_SHELLS=()
case "$shell_opt" in
    1) SELECTED_SHELLS=("${SHELLS_FOUND[@]}") ;;
    2) SELECTED_SHELLS=("fish") ;;
    3) SELECTED_SHELLS=("bash") ;;
    4) SELECTED_SHELLS=("zsh") ;;
    5) SELECTED_SHELLS=() ;;
    *) SELECTED_SHELLS=("${SHELLS_FOUND[@]}") ;;
esac

echo -e "Configuring shells: ${CYAN}${SELECTED_SHELLS[*]:-None}${RESET}\n"

# 3. Destination Directory
INSTALL_DIR="${HOME}/.local/bin"
echo -e "${BOLD}[3/5] Binary Installation Directory${RESET}"
echo -e "Target path: ${CYAN}${INSTALL_DIR}/dev-context${RESET}"
read -rp "Press Enter to confirm or type custom directory [${INSTALL_DIR}]: " custom_dir
INSTALL_DIR="${custom_dir:-$INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"

# Download or copy binary
RAW_URL="https://raw.githubusercontent.com/whysooraj/dev-context/main/bin/dev-context"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "")"

if [ -n "$SCRIPT_DIR" ] && [ -f "${SCRIPT_DIR}/bin/dev-context" ]; then
    echo -e "  Copying binary from local repository..."
    cp "${SCRIPT_DIR}/bin/dev-context" "${INSTALL_DIR}/dev-context"
    [ -f "${SCRIPT_DIR}/dev_context_mcp.py" ] && cp "${SCRIPT_DIR}/dev_context_mcp.py" "${INSTALL_DIR}/dev_context_mcp.py"
else
    echo -e "  Downloading latest binary from GitHub..."
    curl -fsSL "${RAW_URL}" -o "${INSTALL_DIR}/dev-context"
    curl -fsSL "https://raw.githubusercontent.com/whysooraj/dev-context/main/dev_context_mcp.py" -o "${INSTALL_DIR}/dev_context_mcp.py" 2>/dev/null || true
fi
chmod +x "${INSTALL_DIR}/dev-context"
chmod +x "${INSTALL_DIR}/dev_context_mcp.py" 2>/dev/null || true
ln -sf "${INSTALL_DIR}/dev-context" "${INSTALL_DIR}/dc"
echo -e "  ${GREEN}✓${RESET} Installed: ${BOLD}${INSTALL_DIR}/dev-context${RESET} (alias: ${BOLD}dc${RESET})\n"

# 4. Roadmap & Focus Queue Setup
echo -e "${BOLD}[4/5] Focus Queue & Roadmap Setup${RESET}"
DEFAULT_ROADMAP_DIR="${HOME}/Projects"
read -rp "Where do you keep your git projects? [${DEFAULT_ROADMAP_DIR}]: " chosen_projects_dir
PROJECTS_DIR="${chosen_projects_dir:-$DEFAULT_ROADMAP_DIR}"
mkdir -p "${PROJECTS_DIR}"

ROADMAP_FILE="${PROJECTS_DIR}/ROADMAP.md"
if [ ! -f "${ROADMAP_FILE}" ]; then
    cat << 'EOF' > "${ROADMAP_FILE}"
# Projects & Ideas Roadmap

## Active Sprint
- [ ] First priority feature or bugfix
- [ ] Second priority feature

## Ideas Backlog
- [ ] Idea for new feature or project
EOF
    echo -e "  ${GREEN}✓${RESET} Created starter roadmap: ${ROADMAP_FILE}"
else
    echo -e "  ${CYAN}i${RESET} Existing roadmap found: ${ROADMAP_FILE} (preserved)"
fi
echo ""

# 5. Local MCP Server Setup
echo -e "${BOLD}[5/5] Native Agent Injection & MCP Server Setup${RESET}"
if command -v claude >/dev/null 2>&1; then
    echo -e "Claude Code detected on PATH."
    read -rp "Configure dev-context MCP server for Claude Code? [Y/n]: " mcp_opt
    mcp_opt="${mcp_opt:-Y}"
    if [[ "$mcp_opt" =~ ^[Yy]$ ]]; then
        "${INSTALL_DIR}/dev-context" setup-agent claude || true
    fi
else
    echo -e "  ${DIM}Claude CLI not detected. You can configure MCP anytime with: dc setup-agent claude${RESET}"
fi
echo ""

# Write Wrappers
if [ ${#SELECTED_AGENTS[@]} -gt 0 ]; then
    # Fish configuration
    if [[ " ${SELECTED_SHELLS[*]} " =~ " fish " ]]; then
        FISH_CONF_DIR="${HOME}/.config/fish/conf.d"
        mkdir -p "${FISH_CONF_DIR}"
        FISH_FILE="${FISH_CONF_DIR}/dev_context_wrappers.fish"
        {
            echo "# Generated by dev-context installer"
            for agent in "${SELECTED_AGENTS[@]}"; do
                cat << EOF
function ${agent} --wraps ${agent} --description 'Run dev-context flight check then ${agent}'
    if test -z "\$DEV_CONTEXT_SKIP"; and status is-interactive
        dev-context
    end
    command ${agent} \$argv
end
EOF
            done
        } > "${FISH_FILE}"
        echo -e "  ${GREEN}✓${RESET} Configured Fish wrappers: ${FISH_FILE}"
    fi

    # Bash configuration
    if [[ " ${SELECTED_SHELLS[*]} " =~ " bash " ]]; then
        BASH_FILE="${HOME}/.bashrc"
        # Remove old block if present
        if grep -q "# >>> dev-context wrappers >>>" "${BASH_FILE}" 2>/dev/null; then
            sed -i '/# >>> dev-context wrappers >>>/,/# <<< dev-context wrappers <<</d' "${BASH_FILE}"
        fi
        {
            echo "# >>> dev-context wrappers >>>"
            for agent in "${SELECTED_AGENTS[@]}"; do
                cat << EOF
${agent}() {
    if [ -z "\$DEV_CONTEXT_SKIP" ] && [ -t 1 ]; then
        dev-context
    fi
    command ${agent} "\$@"
}
EOF
            done
            echo "# <<< dev-context wrappers <<<"
        } >> "${BASH_FILE}"
        echo -e "  ${GREEN}✓${RESET} Configured Bash wrappers: ${BASH_FILE}"
    fi

    # Zsh configuration
    if [[ " ${SELECTED_SHELLS[*]} " =~ " zsh " ]]; then
        ZSH_FILE="${HOME}/.zshrc"
        if grep -q "# >>> dev-context wrappers >>>" "${ZSH_FILE}" 2>/dev/null; then
            sed -i '/# >>> dev-context wrappers >>>/,/# <<< dev-context wrappers <<</d' "${ZSH_FILE}"
        fi
        {
            echo "# >>> dev-context wrappers >>>"
            for agent in "${SELECTED_AGENTS[@]}"; do
                cat << EOF
${agent}() {
    if [ -z "\$DEV_CONTEXT_SKIP" ] && [ -t 1 ]; then
        dev-context
    fi
    command ${agent} "\$@"
}
EOF
            done
            echo "# <<< dev-context wrappers <<<"
        } >> "${ZSH_FILE}"
        echo -e "  ${GREEN}✓${RESET} Configured Zsh wrappers: ${ZSH_FILE}"
    fi
fi

# Ensure ~/.local/bin is on PATH check
if [[ ":$PATH:" != *":${INSTALL_DIR}:"* ]]; then
    echo -e "\n  ${YELLOW}! Warning:${RESET} ${INSTALL_DIR} is not currently in your \$PATH."
    echo -e "    Add it with: ${BOLD}export PATH=\"${INSTALL_DIR}:\$PATH\"${RESET}"
fi

echo -e "\n${BOLD}${GREEN}Installation Finished Successfully!${RESET}"
echo -e "${DIM}──────────────────────────────────────────────────────────${RESET}"
echo -e "Run ${BOLD}dev-context${RESET} directly or launch ${BOLD}${SELECTED_AGENTS[*]:-your agent}${RESET} to test."
echo ""
