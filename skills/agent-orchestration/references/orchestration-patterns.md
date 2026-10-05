# Working patterns

## Brief

Persist a bounded brief before dispatch. Include task and reason; branch/base;
worktree; relevant files and evidence; constraints and things not to change;
test commands and acceptance gates; decision priorities; resource ownership;
report/checkpoint paths; and exact authority for commits/push/deployment.
Do not include credentials. Give structural agents exact transformations and
checks, not an open-ended numerics or policy task just because they are cheap.

```text
Agent(subagent_type="general-purpose",
      model="claude/chatgpt/gpt-6.1-sol-backup",
      effort="high", run_in_background=true,
      description="Implement parser tests",
      prompt="Read BRIEF.md and the project rules. Work only in your assigned
              worktree. Keep STATUS.md current. Return diff, tests and issues.")
```

The example requires the enhanced tool schema; on a plain client use the
codex-fallback skill. Model picker entries alone do not change Agent.model.

## Shared resources and nested workers

Parallelize disjoint work. Serialize shared GPUs, ports, non-isolated caches
and deployments; keep an allocation file per wave and agree one lock order.
Acquire only around the hardware run, add a timeout, and tear down owned jobs
before releasing locks. Do not assume another project has CuteAFD's hosts or
locks. For nested Claude agents, message routing can deliver a component's
SendMessage to the orchestrator rather than its parent; relay updates and put
everything the parent needs in the final report. Verify current harness behavior.

## Recovery

- Transport/tool-schema error: diagnose the actual first failure, not the generic
  fallback trailer. Run local checks; stop retrying identical invalid requests.
- Capacity/overload: bounded delay, then resume the same brief/checkpoint. A
  practical default is up to three retries several minutes apart; respect an
  earlier user budget/time limit.
- Quota: preserve work, then choose another authorized subscription/model. Do not
  silently turn a subscription task into a paid API task.
- Restart/upgrade: checkpoint all agents and list owned jobs first. Restart the
  client to load new schemas; an already running daemon/session is not patched
  by reinstalling a launcher. Collect jobs whose old session lost notifications.
- Ordinary checkpoint: STATUS.md records worktree, branch/head, changed files,
  passed/failed tests, jobs/PIDs/resources, next actions and blockers. Resumption
  must check those jobs before launching duplicates.

## Integration and learning

Read reports, inspect diffs, reproduce meaningful gates and integrate in a
temporary worktree when appropriate. Have a different model review high-risk
changes without supplying the author's desired conclusion. The coordinator
owns tradeoffs, conflict resolution and releases. Record model strengths and
workflow lessons in the project's source-of-truth agent guide in the same step
as memory updates; memory should link there rather than duplicate mutable rules.
