---
name: codex-fallback
description: Run and stop direct Codex CLI workers from Claude when the hybrid gateway or custom Agent schema is unavailable, keeping task briefs and reports.
---

Use direct Codex only for authorized tasks when the enhanced Claude Agent path
is unavailable or the user requests native Codex. This avoids LiteLLM entirely.
Read `${CLAUDE_PLUGIN_ROOT}/skills/codex-fallback/references/worker-preamble.md`.

Write a persistent brief with the assigned worktree, branch, tests and reporting
requirements. Launch one blocking command through Claude's background Bash tool:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/launch-codex.sh" task-name \
  --brief /absolute/BRIEF.md --cwd /absolute/worktree \
  --model gpt-6.1-sol --effort high --account backup --yolo
```

`--yolo` is explicit unsandboxed/no-approval execution. Use it only when the user
authorized full host access for this worker; omit it for workspace-write with
no approval prompts (commands requiring escalation then fail). It does not
grant permission to alter other projects, merge, deploy or disclose credentials.

The default runs directory is `$CMA_HOME/runs`; `--runs-dir` overrides it.
The final answer is NAME.report.md, events/errors NAME.log, exit status
NAME.result.json. Read these after completion; the launcher returns the actual
Codex exit code and refuses duplicate live tasks. Logs can contain task content;
keep them private and avoid putting secrets into prompts.

Stop the complete owned process group with:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/stop-codex.sh" task-name
```

Do not kill only the shell launcher. To resume after a stopped/finished CLI task,
append a RESUME NOTE to the brief stating worktree state and remaining jobs, then
relaunch once the old group is gone. This is worktree/checkpoint continuation,
not restoration of the Codex conversation. For native conversation resume use
`scripts/cma codex --account backup -- exec resume SESSION_ID` where supported.
If Codex is not logged in, use the multi-account skill; the user's browser/device
authorization cannot be automated or invented.
