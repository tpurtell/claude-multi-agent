---
name: litellm-setup
description: Prepare, install, verify or upgrade this package's separate localhost Docker LiteLLM gateway and enhanced Claude launcher without replacing existing deployments.
---

Read `${CLAUDE_PLUGIN_ROOT}/README.md` (agent installation contract), then
`${CLAUDE_PLUGIN_ROOT}/OPS.md` for the operation requested. Scripts are bundled
under `${CLAUDE_PLUGIN_ROOT}/scripts`; run them from any working directory.

For a new authorized installation:

1. Check Linux/Bash, Python 3.10+, Docker Compose, a native Bun/ELF Claude client,
   optional Codex CLI, free port and filesystem. Record existing configuration;
   choose a dedicated CMA_HOME and never reuse the user's existing LiteLLM stack.
2. Prepare `scripts/cma init --accounts 2 --port 4000 --yolo` only if full-access
   launching was approved. Otherwise omit --yolo. This generates real private
   keys; it does not start services or overwrite Claude/Codex configuration.
3. Run `scripts/cma up` and `scripts/cma check`. The key allows exactly this
   installation's routes; native Claude rows are hidden but remain callable.
4. Ask the user to authorize each selected Codex subscription with
   `scripts/cma login-chatgpt primary` and `backup` at the appropriate time. Do
   not claim the deployment can infer until OAuth and model access are tested.
   A handoff is expected if the user is absent; complete all non-login work.
5. Run `scripts/cma prepare-client` to verify the isolated patch against the
   installed client. Unknown binary/schema layouts fail closed. Install only
   cma-prefixed launchers with `scripts/cma install-launchers` if authorized.
6. Relaunch through `cma-claude`; check the actual Agent.model/effort schema and
   real tool loops with consent to spend quota. Remote Control's unsupported
   client workaround is separate: pass --remote-control-patch only if requested.

Never copy the user's Anthropic Max OAuth credentials to Docker or GitHub. They
are forwarded per native request by the client. Gateway keys must not replace
ANTHROPIC_AUTH_TOKEN/API_KEY; they use x-litellm-api-key. No Redis is needed for
the intentionally single-process proxy; each subscription worker has a separate
process-global OAuth store, and quotas/spend state are not globally coordinated.

Provider API keys belong in the caller's environment/private state, not images,
command arguments, README examples or commits. DeepSeek/MiMo/EXA are optional
billable providers. Read OPS.md before upgrades, backup, or recovery; do not
upgrade just because a troubleshooting task mentions a newer release.
