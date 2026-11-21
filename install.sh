#!/usr/bin/env bash
set -e

INSTALL_DIR="${HOME}/.local/bin"
mkdir -p "${INSTALL_DIR}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Installing dev-context to ${INSTALL_DIR}..."
cp "${SCRIPT_DIR}/bin/dev-context" "${INSTALL_DIR}/dev-context"
chmod +x "${INSTALL_DIR}/dev-context"

# Setup Fish wrapper if fish is present
if [ -d "${HOME}/.config/fish" ]; then
    mkdir -p "${HOME}/.config/fish/conf.d"
    cp "${SCRIPT_DIR}/wrappers/dev-context.fish" "${HOME}/.config/fish/conf.d/dev_context_wrappers.fish"
    echo "Configured Fish shell wrapper: ~/.config/fish/conf.d/dev_context_wrappers.fish"
fi

# Create default ROADMAP.md if not present
ROADMAP_FILE="${HOME}/Projects/ROADMAP.md"
if [ ! -f "${ROADMAP_FILE}" ]; then
    mkdir -p "${HOME}/Projects"
    cat << 'EOF' > "${ROADMAP_FILE}"
# Projects & Ideas Roadmap

## Active Sprint
- [ ] Task 1
- [ ] Task 2

## Ideas Backlog
- [ ] New feature idea
EOF
    echo "Created initial roadmap: ${ROADMAP_FILE}"
fi

echo "Installation complete. Run 'dev-context' or launch agy / claude / codex to test."
