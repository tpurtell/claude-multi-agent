---
name: multi-account
description: Select or authorize separate native Claude and Codex accounts without overwriting the primary login; distinguish Claude client accounts, LiteLLM Codex workers and direct Codex fallback accounts.
---

Read `${CLAUDE_PLUGIN_ROOT}/OPS.md` account operations first. Three independent
account choices exist; do not substitute one for another:

| Choice | Mechanism |
| --- | --- |
| Native Claude coordinator | Primary default ~/.claude credentials, or CLAUDE_SECURESTORAGE_CONFIG_DIR for backup; settings/sessions remain shared |
| Codex model inside LiteLLM | Explicit normal vs -backup route, separate Docker OAuth volumes/workers |
| Direct Codex CLI fallback | Normal Codex home vs separate CMA_CODEX_SECONDARY_HOME/CMA_HOME codex-account-2; native sessions/config are separate |

Use `scripts/cma login-claude primary|backup`, `login-chatgpt primary|backup`, or
`login-codex primary|backup` for the correct login. Device/browser authorization
requires the human. Do not scrape, publish or copy tokens between mechanisms.

Use `cma-claude2` to change the coordinator's Claude login; it keeps the same
gateway key/catalog and does not change which Codex model a worker picks.
Shared Claude profile labels can be stale; the secure-storage setting selects
credentials. No Bubblewrap: preserve root file ownership, SSH_AUTH_SOCK, writable
mounts and normal privilege handling. Diagnose with scripts/diagnose-agent-env.sh.

Prefer the account the user specified. On quota exhaustion checkpoint then
switch explicitly; on capacity overload retry boundedly before switching.
Codex fallback does not overlay auth.json or rewrite a shared refresh lock.
Second Codex homes use file-backed auth and have their own settings/session
history. Do not claim history sharing for that path.
