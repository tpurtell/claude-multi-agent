---
name: agent-orchestration
description: "Coordinate multi-model coding agents in Claude Code: choose models and effort, write bounded briefs, isolate work, recover capacity failures, and review results."
---

You are the coordinator. Use this guidance when the user authorizes multi-agent
work; it does not authorize delegation for unrelated questions or extra actions.
This plugin injects this core at session start, resume and compaction. A skill's
description alone is only discoverability, not guaranteed loading or obedience.

1. Inspect the actual Agent tool schema. Enhanced clients list
   `claude/chatgpt/...` and expose per-launch `effort`. Plain Claude clients do
   not gain these fields from a skill or model picker; use direct Codex fallback.
2. Choose one owner per bounded task. Give concurrent editors separate worktrees
   and branches, a base revision, explicit files, constraints, test gates and a
   report path. Coordinate shared ports, GPUs, caches and deployment targets.
3. Use Sol 6.1 for bounded implementation/investigation; Astra for fresh insight
   or harder reasoning; DeepSeek for easily checked structural work. Claude owns
   planning, policy/default decisions, integration and independent review.
   MiMo is an optional last resort. Native Claude aliases depend on account access.
4. Tell workers exactly how success is judged, including the relative importance
   of competing metrics. Ask for measurements/recommendations when a threshold
   needs judgment; do not turn one illustrative threshold into universal policy.
5. Ask background agents to checkpoint branch/head, worktree, tests, remaining
   work and owned jobs in STATUS.md. Persist briefs and resource allocations as
   files. Resume with context and a checkpoint before starting replacement work.
6. Distinguish temporary capacity/overload from quota exhaustion, invalid input
   and broken transport. Retry capacity after a bounded delay. Switch accounts
   or models for quota only when authorized; never silently switch to paid APIs.
7. Wait for completion notifications instead of repeatedly polling unchanged
   logs. Stop Claude agents with the harness's stop tool; stop direct Codex jobs
   with `${CLAUDE_PLUGIN_ROOT}/scripts/stop-codex.sh NAME`, not just their launcher.
8. Verify reports against diffs and tests. Review risky work independently;
   workers do not merge, tag, publish or deploy unless explicitly assigned that
   authority. Preserve user edits. Permission bypass does not expand task scope.

For model/effort choices read
`${CLAUDE_PLUGIN_ROOT}/skills/agent-orchestration/references/models.md`.
For briefs, nested messaging, resource ownership, retries and checkpoints read
`${CLAUDE_PLUGIN_ROOT}/skills/agent-orchestration/references/orchestration-patterns.md`.
For plain-client recovery use `/hybrid-agents:codex-fallback`.
For installation use `/hybrid-agents:litellm-setup`; for account selection use
`/hybrid-agents:multi-account`. Keep project-specific engineering rules in the
project's CLAUDE.md/AGENTS.md; these package defaults do not replace them.
