#!/usr/bin/env bash
# Read-only diagnostics; never dump environment values or credentials.
set -Eeuo pipefail
printf 'user=%s cwd=%s\n' "$(id -un)" "$PWD"
if [[ -r /proc/self/status ]]; then rg '^NoNewPrivs:' /proc/self/status; fi
stat -c 'etc-owner=%U' /etc
printf 'ssh-agent-present=%s\n' "$([[ -n ${SSH_AUTH_SOCK:-} ]] && echo yes || echo no)"
printf 'separate-claude-store=%s\n' "$([[ -n ${CLAUDE_SECURESTORAGE_CONFIG_DIR:-} ]] && echo yes || echo no)"
for cma_command in claude codex docker python3; do
    command -v "$cma_command" || true
done
printf 'Directory write permission (not a write probe):\n'
for cma_directory in "$PWD" /tmp /var/tmp; do
    if [[ -w "$cma_directory" ]]; then printf '%s writable\n' "$cma_directory"; fi
done
