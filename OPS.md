# Operations

Use installed cma or ./scripts/cma in the stable checkout. For another instance,
export its absolute CMA_HOME before every command. Never reuse deployment state.

| Action | Command |
| --- | --- |
| Container status | `cma status` |
| Readiness/key/catalog/OAuth presence | `cma check` |
| Apply this instance's config/key | `cma up` |
| Stop/remove containers, retain volumes | `cma down` |
| Reconcile only virtual key | `cma sync-key` |
| Regenerate config without starting | `cma render` |
| Isolated client preparation | `cma prepare-client` |
| DB/config/keys/Codex OAuth backup | `cma backup` |
| Current native model catalog | `cma refresh-native --account primary`, then `cma up` |
| Explicit live tool-loop test | `cma smoke --model MODEL --allow-spend` |
| Local diagnostics | `scripts/diagnose-agent-env.sh` |

For scoped Compose logs/advanced operations:

```bash
cma_state=${CMA_HOME:-$HOME/.local/share/claude-multi-agent}
cma_project=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["project"])' "$cma_state/config.json")
docker compose --project-name "$cma_project" --env-file "$cma_state/.env" \
  -f "$cma_state/compose.json" logs --tail=100 proxy
```

Keep complete logs/config private: they can contain prompts, device codes or
provider errors. Never publish .env, key JSON, OAuth volumes or backup/dump files.

## Three independent account systems

1. Native Claude: cma-claude uses the primary login. `cma login-claude backup`
   authorizes `$CMA_HOME/claude-account-2`; cma-claude2 selects it. Override with
   CMA_CLAUDE_SECONDARY_DIR for an existing store. Settings/projects/history and
   ~/.claude.json stay shared. Shared account labels may be stale.
2. Gateway Codex: `cma login-chatgpt primary|backup` runs the worker device flow.
   Each has its own OAuth volume/refresh process. -backup IDs select worker 2;
   changing the native coordinator account does not affect that selection.
3. Native Codex fallback: `cma login-codex primary|backup`. Primary retains the
   existing Codex home; backup uses `$CMA_HOME/codex-account-2` or
   CMA_CODEX_SECONDARY_HOME, with file-backed auth and separate config/history.
   Fallback invocations select the official OpenAI provider and ChatGPT login
   method explicitly, so a configured gateway/API-key default cannot silently
   turn the fallback into the broken proxy or paid API path.

Device login needs the owner. Valid worker tokens refresh normally, so
login-chatgpt can reuse an existing login; it isn't an account-replacement
command. Before deliberate replacement, back up and follow logout/login for
only that store. Don't revoke or overwrite the other account. Distinguish
expiration, entitlement, capacity, quota, transport and invalid parameters.
Workers are initially healthy but empty: LiteLLM otherwise starts the device
flow eagerly while building its router. Explicit login runs in a one-off
container sharing only that account volume. On success it marks authorized_workers
in private config; cma up recreates worker/proxy services to load those routes.
If a volume is lost or startup auth fails, remove that worker from authorized_workers
to return to the healthy login-pending mode; don't delete the other account's
store. One-off login works even if the long-lived worker is not healthy.

## Launchers, permissions and updates

`cma-claude --resume` starts a fresh enhanced process using shared sessions.
Old daemons/RC sessions retain old schemas/environment; restart after changes.
Cached clients disable their updater: upgrade the normal installed Claude,
run cma prepare-client and relaunch. Source/patch/origin/catalog checksums drive
automatic rebuilds; unknown layouts fail closed. Never edit the original binary.

`CMA_NO_PATCH=1 cma-claude` retains the native client/picker but lacks custom
Agent models and gateway effort adaptations (new clients still have their native
effort argument). Use direct Codex until the patch is reviewed. RC's host-gate
workaround is separate and off by default: `CMA_REMOTE_CONTROL_PATCH=1
cma-claude --rc`. Other OAuth/org/subscription eligibility checks still apply.
This unsupported interface can break; close test RC sessions afterward.

### Native Agent effort (Claude Code 2.1.296)

The native per-invocation effort field arrived in 2.1.292. Our newer patch
extends the existing absolute/relative schemas and uses native transport and
resume persistence; the 2.1.289 branch remains for rollback. Sol/Astra retain
low/medium/high/xhigh/max; DeepSeek medium→high and xhigh→max are explicit
aliases for its three real levels, not new provider capabilities. MiMo permits
omitted/null/default, not a graded override. Native Claude keeps its own effort
resolution. Gateway policy/environment conflicts still fail explicitly.

Feature-gated lower/higher remains controlled by the native client and is not
force-enabled. Its native stepping excludes max. Forks on the new client inherit
the parent's model/effort, ignoring overrides. Restart/resume in a fresh enhanced
process after preparing the client; existing sessions retain their old schema.

An opt-in test executes the real installed native client against a fake loopback
API: all four Codex routes at five efforts, DeepSeek mappings and MiMo default.
It also enables native relative effort only in the isolated test, verifying
lower/higher on all five graded routes (36 Agent launches in total).
It uses dummy authentication and isolated temporary config, never real provider
inference/credentials, and leaves the installed binary unchanged:

```bash
python3 tests/test_native_client.py --allow-client --source "$(command -v claude)"
```

If preparation fails, check `type -a claude` and each absolute executable's
`--version`. Duplicate npm installs under Homebrew/NVM can make terminal and
agent PATHs choose different versions. Keep one normal installation; preserve
account/session/config directories and active cached clients. A version change
triggers automatic rebuilding, not automatic rejection: changed/unrecognized
code or binary layouts trigger the fail-closed guard.
Before an npm upgrade, check `npm prefix -g` against the chosen Claude executable:
an npm from a different Node installation can recreate the duplicate. Use an
explicit `--prefix` for the intended installation when necessary; do not remove
unrelated Node/npm tools or account directories.

Verified 2026-10-12 on the actual native 2.1.296 executable: the opt-in fake-API
test passed, as did 34 offline host checks and 15 pinned LiteLLM bridge checks.
Background/persisted effort is covered by fixtures; real-provider inference,
Remote Control and native resume were not newly live-tested for this upgrade.

Verified again 2026-10-15 on native 2.1.299: its Agent handler adds a `timing`
argument, which the patch preserves unchanged. Native model/effort transport and
the existing structural checks remain intact. The 36-launch fake-API test,
35 offline host checks and 15 pinned gateway checks passed. Fixtures cover both
handler signatures, including foreground/background effort persistence and
rejection of unknown parameters. No live provider/RC/resume test was performed.

### Fable 5.2 and Claude Code 2.1.325 (2026-11-14)

The native `fable` alias followed Fable 5.1 in Claude Code 2.1.319. Anthropic
changed it to Fable 5.2 in 2.1.321. Our Agent patch retains the native alias
resolver; it does not replace that alias with a versioned model ID. Upgrade
the normal client, prepare the isolated client, and relaunch to pick up the
new resolver. Fable 5.2 requires 2.1.321 or later.

The default native gateway catalog now permits `claude-fable-5-2` and
`claude-haiku-5-5`, retaining the older IDs. Existing instances must run
`cma refresh-native --account primary`, then `cma up` to update their own
catalog/routes/key. A client upgrade alone cannot add an allowed gateway route.
The gateway still hides native Claude IDs from its extra-model picker listing.

2.1.325 normalizes the model before effort-capability/default resolution and
adds native definition inheritance before the final Agent model resolution.
The patch verifies those precise layouts and applies custom effort after
inheritance/model resolution, preserving native policy, budgets and transport.
Unknown layouts still fail closed; the installed executable is never patched.

Verification: offline host tests, real isolated 2.1.325 Agent schema/wire probes
(37 launches, including `model: "fable"` resolving to `claude-fable-5-2`) and
inline-refusal recovery/MCP execution. A private 2.1.319 regression probe uses
`--expected-fable-model claude-fable-5-1` to assert its earlier native default.
No live provider inference, Remote Control or native resume was tested for this
update. Already-running clients keep their old resolver until relaunched.

References: [Claude Code model configuration](https://code.claude.com/docs/en/model-config)
and [Fable 5.2](https://platform.claude.com/docs/en/models/fable-5-2/overview).

### Client compatibility: Claude Code 2.1.319 (2026-11-08)

The new client moves the finite native Agent model enum into an imported
constant, inlines effort-cap filtering, adds `pickedEffortModel` to native
budget resolution, renders the finalized agent definition without the old
lifecycle marker, and shares inline-tool error matching across beta types.
The patch now recognizes these layouts, verifies the enum declaration/import
and inline beta binding, and preserves native policy and request transport.
Older reviewed layouts remain supported; unknown layouts still fail closed.

Bun cache-pointer validation now checks bounds without copying the cache
payload. The newer bundle shares large cache spans across many module records;
copying each for validation made preparation needlessly slow. Actual changed
module sources and their cache invalidation remain scoped as before.

Verification used an isolated npm-native 2.1.319 executable before any normal
installation update: host tests, both opt-in native tests, pinned gateway bridge
checks and plugin validation. The public native test exercised all 36 model/
effort launches plus the injected inline-refusal recovery/MCP round trip.
Native 2.1.306 also passed the private model/effort and inline-recovery probes.
No provider inference, live Remote Control or native resume was newly tested.
Restart hybrid clients after updating the normal client and preparing the cache.

### DeepSeek inline-tool errors (Claude Code 2.1.306+)

DeepSeek's Anthropic endpoint can reject `tool_addition` containing an inline
`tool_definition`, saying `unknown variant tool_definition, expected
tool_reference` (HTTP 422). A plain reference is not equivalent: the inline
definition may be absent from the top-level tools list. Do not drop the block
or rename it to a reference without declaring its schema.

The isolated client patch recognizes this specific LiteLLM `DeepseekException`
error on the configured gateway when the hybrid patch is enabled, then uses
Claude's existing `kind_not_enabled` recovery to rebuild/retry with declarations
and references. Other provider errors retain native handling. This reason
avoids the host-wide refusal latch, so the native coordinator retains inline
support. Model roster and routing are unaffected. Relaunch after preparing the
new cache; running clients retain the old classifier.

```bash
python3 tests/test_native_inline_tools.py --allow-client --source "$(command -v claude)"
```

This isolated native test discovers a stdio MCP tool, injects a connector-style
inline request at the fake API boundary, returns DeepSeek's error, verifies the
retry carries the full schema and drops the inline beta, executes the MCP tool,
then verifies the coordinator still has its inline beta. It uses dummy auth and
temporary config/cache. It does not reproduce real connector login/discovery
or measure cache hits. Moving definitions into the top-level list can rebuild
the prefix; stable later requests can still use ordinary provider caching.

An explicitly billable variant adds `--allow-spend --gateway-url URL --key-file
PATH` and forwards only that synthetic DeepSeek child to a real gateway. The
coordinator and initial search remain fake. The original private deployment
passed that check on 2026-10-22; public users still need their own configured
provider credentials and entitlement. No live native Claude/RC test is implied.

No launcher creates namespaces/no-new-privileges flags. SSH inherits the
terminal's SSH_AUTH_SOCK. Missing agent keys cause ordinary auth failures.
Nobody-owned root files, read-only /mnt or sudo no-new-privileges errors imply
a parent/old sandboxed session; the launcher cannot undo inherited restrictions.
Yolo skips client approvals, not OS permissions or task authorization.
Change only this instance's private config.json yolo boolean for its default;
don't rewrite ~/.claude/settings.json/global Codex policy. Native Codex full
access uses its explicit --dangerously-bypass-approvals-and-sandbox flag.

For utility updates, pull the stable checkout and rerun tests/plugin validation,
then relaunch. Install-launchers refuses existing names; its wrappers point at
that stable checkout so source updates need no wrapper overwrite. Plugin-only
updates use Claude's marketplace/plugin update flow. Don't pin wrappers into a
versioned plugin cache. Port changes require updating private port AND base_url,
cma up, and client relaunch; caches include the origin.

## Direct Codex workers

Write a persistent brief; launch through Claude's background Bash as one blocking
command so completion wakes the coordinator:

```bash
scripts/launch-codex.sh parser-tests --brief /absolute/BRIEF.md \
  --cwd /absolute/worktree --model gpt-6.1-sol --effort high --account backup --yolo
scripts/stop-codex.sh parser-tests
```

Omit --yolo for workspace-write/no approvals (escalations fail). Runs default to
$CMA_HOME/runs; use --runs-dir or CMA_RUNS_DIR. The lock refuses duplicate live
task names. PID/start ticks reject reuse; stop signals the entire owned group
with TERM, then KILL after a grace period. Stale records fail closed. Runner
cleanup also stops lingering task children. Exit status is real, not just
successful launcher creation. NAME.report.md is the final answer, NAME.log
events/errors, NAME.result.json the exit code. Keep all private.

Append a RESUME NOTE and relaunch only once the old run is gone. This restores
worktree/checkpoint state, not native conversation context. Use codex exec resume
explicitly for that. Claude-harness agents use their harness stop/resume tools.

## External interactive workers

Load the external-agents skill for Grok/Antigravity control. Its bundled
`skills/external-agents/scripts/ext-agent.py` needs Linux, Python 3.10+, tmux and
already authenticated CLIs. `EXT_AGENT_RUNS` selects private state (default
`~/.cache/ext-agent`); `EXT_AGENT_GROK` / `EXT_AGENT_AGY` override executable paths.
Preamble/brief are explicit files. Default launches retain CLI approval behavior;
`--auto-approve` requires explicit authorization for that execution mode.

Use foreground bounded `wait` calls with progress returns to keep the driver
reachable without coordinator notification churn. Adopt existing runs after a
restart with list/status/transcript, never a duplicate start. Idle and the
first-idle `final.md` snapshot are not completion proof: verify deliverables and
rerun authorized gates. Stop workers through the bundled script; detached remote
jobs need their own authorized cleanup. Prune archives stopped runs but does not
delete their private evidence. Never commit transcripts, prompts or UI banners.

The [guide](skills/external-agents/references/guide.md) separates fake-CLI test
coverage from untested live provider behavior and gives the scorecard rubric.
No live provider calls or account changes are required for the unit suite.

## Gateway upgrades and backups

Review the candidate release and run its offline bridge tests:

```bash
scripts/test-gateway.sh docker.litellm.ai/berriai/litellm:REVIEWED_VERSION
cma upgrade --image docker.litellm.ai/berriai/litellm:REVIEWED_VERSION
```

Upgrade rejects latest/arbitrary registries, reruns offline tests, backs up,
pulls/recreates only this stack and verifies key/catalog. No live inference is
made. Retest streaming/tools/effort after login before relying on a new release;
passing offline tests is not a full live compatibility guarantee.

`cma backup` creates `$CMA_HOME/backups/UTC_TIMESTAMP/` (0700): database.dump,
.env (salt/keys), configs, gateway key, worker OAuth tarballs and manifest (0600).
Encrypt/store privately off-machine. This isn't atomic across DB/OAuth stores;
quiesce usage for coherence. Native Claude/default Codex credentials, client
caches and task logs aren't in gateway backups; back them up separately.
Keep the encryption salt paired with the DB. If a named gateway key exists but
its local key file is missing, restore it; don't create duplicate named keys.

Failed upgrades restore the previous image in config. Running containers may
remain on the failed image and DB migrations may not reverse. Image rollback
alone is not schema rollback. Prefer testing recovery in a separate copy first.

### Manual scoped recovery

Only restore a trusted backup with explicit overwrite authority for this
instance. Stop usage, back up current state, and record project/image/port.

1. cma down retains volumes. Restore .env/config.json/gateway-key.json into the
   dedicated CMA_HOME at mode 0600. Preserve the intended project/port. Run
   cma render to regenerate bind paths for the current machine/checkout.
2. With the scoped Compose command above, start only DB (`up -d --wait db`).
   Restore the exact dump: `exec -T db pg_restore -U litellm -d litellm --clean
   --if-exists --no-owner < /exact/trusted/backup/database.dump`.
3. Inspect trusted auth archives first; reject absolute paths, .., symlinks or
   unexpected files. Restore before starting authenticated workers, otherwise
   an empty store can trigger an eager device login. With the scoped Compose
   command, use a one-off container for only the selected volume:
   `run --rm --no-deps -T --entrypoint tar chatgptN -xzf - -C
   /app/chatgpt-auth < /exact/trusted/backup/chatgptN-auth.tar.gz`.
4. cma up, cma check, then authorized smoke tests. Provider refresh-token
   invalidation can still require reauthorization.

Don't paste restore steps blindly into an agent: name the exact backup/target
and overwrite scope. No automatic data-volume deletion/unreviewed restore is
provided by the normal utility. The isolated integration test deletes only the
test volumes it created and never performs production restore.

## Troubleshooting

| Symptom | First check |
| --- | --- |
| No custom Agent models/effort | Actual schema, fresh enhanced process, patch success—not just picker |
| Native auth error | Correct login, no shell API key replacing OAuth, plan access |
| Codex auth error | Correct worker login; file presence alone isn't validity |
| Unsupported effort | Metadata/bridge version, native policy/env; don't retry identical errors |
| DeepSeek Artifact schema 400 | Exact no-NUL compatibility callback loaded |
| RC unsupported | Explicit workaround; other eligibility checks still apply |
| Non-native search fails | EXA configured; don't assume native server-side WebSearch |
| SSH publickey error | SSH agent/socket, not model selection |
| Resume claims only Claude models | Fresh enhanced launcher; old conversation claims may be stale |
| Port collision | Pick another free port; don't stop an unknown service |

Arbitrary model additions need aligned profile, routes, metadata, finite schema,
effort validation and tests. The patch intentionally accepts only reviewed IDs.
