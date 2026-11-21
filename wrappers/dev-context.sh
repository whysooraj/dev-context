# dev-context wrapper for Bash / Zsh
# Source in ~/.bashrc or ~/.zshrc

agy() {
  if [ -z "$DEV_CONTEXT_SKIP" ] && [ -t 1 ]; then
    dev-context
  fi
  command agy "$@"
}

claude() {
  if [ -z "$DEV_CONTEXT_SKIP" ] && [ -t 1 ]; then
    dev-context
  fi
  command claude "$@"
}

codex() {
  if [ -z "$DEV_CONTEXT_SKIP" ] && [ -t 1 ]; then
    dev-context
  fi
  command codex "$@"
}
