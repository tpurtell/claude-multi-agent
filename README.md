# Hybrid Agents for Claude

A Claude-first plugin and utility package for using Claude Code as a coordinator
of Claude, Codex, DeepSeek and optional MiMo workers. Includes client patches,
a separate localhost Docker LiteLLM gateway, multi-account launchers, direct
Codex recovery, skills and an operations runbook.

[Architecture posters: command center and pig-kidney transplant unit](docs/assets/README.md).

**Give this repository to Claude and ask it to follow the installation contract
below.** It can finish preparation, deployment and validation autonomously.
Browser/device logins require the owner. Do not paste tokens or API keys into chat.

Community tooling, **not endorsed by Anthropic or OpenAI**. Subscription proxies
and native-client patches are unsupported interfaces; vendors may change or
restrict them. Use accounts you control and check applicable terms. The package
does not grant entitlements or bypass login, quota, org policy or managed rules.

## Install the Claude plugin

In Claude Code:

```text
/plugin marketplace add tpurtell/claude-multi-agent
/plugin install hybrid-agents@tpurtell-agent-tools
```

For local development: `claude plugin validate /path/to/repo`, then
`claude --plugin-dir /path/to/repo`. Skills are:

- `/hybrid-agents:agent-orchestration`
- `/hybrid-agents:litellm-setup`
- `/hybrid-agents:codex-fallback`
- `/hybrid-agents:multi-account`

Skills can bundle scripts; ordinary skill loading is on demand. This plugin's
SessionStart hook injects the orchestration core on startup/resume/clear/compact;
SubagentStart injects the worker contract. Loading is automatic while its hooks
are enabled, not a guarantee of obedience. Hooks make no network calls, install
nothing, read no credentials, and respect disabled hooks/managed policy.
Plugin-only installation does not create services or patch the Agent schema.

## Installation contract for Claude

Read this section and [OPS.md](OPS.md), then inspect the scripts. Preserve the
user's existing configurations/services. Install only new `cma*` names; never
overwrite `claude`, `claude2`, `hybrid-claude`, `codex2` or another LiteLLM stack.
Complete all non-login stages if the owner is absent and report pending logins.

### 1. Prerequisites and stable checkout

Linux/Bash, Python 3.10+, Docker Compose, and a native ELF64/Bun Claude Code
installation on PATH. Patches were tested with **Claude Code 2.1.289**; compatible
updates rebuild automatically, unknown layouts fail closed. macOS/Windows
binaries are unsupported. Codex CLI is needed only for direct fallback.
The user needs Docker access; don't silently escalate/change group membership.

Installed launchers need a stable utility checkout, not a versioned plugin cache:

```bash
git clone https://github.com/tpurtell/claude-multi-agent.git \
  ~/.local/share/claude-multi-agent-src
cd ~/.local/share/claude-multi-agent-src
./scripts/cma --help
```

State defaults to `~/.local/share/claude-multi-agent`, outside the checkout.
Set `CMA_HOME` to a dedicated absolute directory for another installation.
Choose a free port; examples use **4000**. Leave existing services alone.

### 2. Prepare and start the dedicated gateway

```bash
./scripts/cma init --accounts 2 --port 4000 --yolo
./scripts/cma up
./scripts/cma check
```

**--yolo explicitly enables unsandboxed, no-approval Claude execution.** Use it
only with full-access authorization on a trusted machine; omit it for ordinary
permission checks. It does not expand task scope or change global settings.

`init` generates real private master/worker/salt/database secrets (0700 state,
0600 files), refuses existing state, and starts nothing. `up` starts only its
randomly named Compose project, provisions a restricted virtual key and verifies
the catalog. Only `127.0.0.1:4000` is published; PostgreSQL and OAuth workers
have no host ports. Public/LAN exposure requires a separate review.

The reviewed image is `docker.litellm.ai/berriai/litellm:1.104.0`. PostgreSQL
persists keys/permissions/usage/spend; each Codex worker has its own OAuth volume.
The intentionally single-process proxy has no Redis. There is no automatic
account switch or paid-provider fallback. Use --accounts 1 for one subscription.

### 3. Human login handoffs

The coordinator reuses the existing native Claude login. Only if missing, ask
the owner to run `./scripts/cma login-claude primary`; don't replace a working
login to test setup. Authorize the gateway Codex subscriptions separately:

```bash
./scripts/cma login-chatgpt primary
./scripts/cma login-chatgpt backup
./scripts/cma up
```

The owner opens each printed URL, enters its code, and chooses the right account.
Do not log/share/commit device codes. These worker logins are distinct from the
native Codex CLI's login. Without the owner, leave this explicit handoff pending.
A healthy stack/correct catalog does not establish inference. `check` reports
OAuth file presence, not token validity, model entitlement or remaining quota.
Before explicit login succeeds, workers start with no active ChatGPT deployments
to avoid LiteLLM's eager device flow blocking unattended startup. Login runs in
a one-off container using the same private OAuth volume; the following up
recreates only workers/proxy to activate routes without recreating PostgreSQL.

### 4. Prepare the client and install new launchers

```bash
./scripts/cma prepare-client
./scripts/cma install-launchers
cma-claude
```

Put ~/.local/bin on PATH. Installs only `cma`, `cma-claude`, `cma-claude2`,
`cma-codex`, `cma-codex2`, refusing conflicts. The launcher loads this plugin,
fetches its exact gateway catalog and prepares a checksum-verified isolated
client. It never edits the installed binary. Cache identity includes source,
patcher, origin and enabled models; preparation is locked and atomic.

Check /model AND the actual Agent definition. Enhanced clients expose custom
Agent.model and per-agent effort; a picker alone cannot do that. Native choices
stay built in, while the gateway lists only these configured extras:

| Gateway ID | Source |
| --- | --- |
| `claude/chatgpt/gpt-6.1-sol` | Codex subscription 1 |
| `claude/chatgpt/gpt-6-astra` | Codex subscription 1 |
| `claude/chatgpt/gpt-6.1-sol-backup` | Codex subscription 2 |
| `claude/chatgpt/gpt-6-astra-backup` | Codex subscription 2 |
| `claude/deepseek/deepseek-flash` | Optional official API |
| `claude/xiaomi/mimo-v2.6-pro` | Optional OpenRouter API |

Sol/Astra allow low/medium/high/xhigh/max; DeepSeek low/high/max; MiMo default
only. No forced gateway effort. See the [model guide](skills/agent-orchestration/references/models.md).
Codex advertises 272k input/128k output, though unfamiliar IDs can still use
Claude's conservative internal context budget.

Native Anthropic IDs/aliases remain permitted but hidden from gateway listings,
avoiding duplicates. `cma refresh-native` fetches the account's current catalog;
then cma up applies it. Native Max OAuth is forwarded only for native Anthropic
groups, never stored as a Docker/PostgreSQL provider credential.

### 5. Optional providers and search

With DEEPSEEK_API_KEY, OPENROUTER_API_KEY or EXA_API_KEY supplied through the
owner's private environment/secret manager (never a CLI argument or chat):

```bash
cma provider deepseek
cma provider openrouter
cma provider exa
cma up
```

These enable their models/search and are separately billable. EXA intercepts
non-native search; native Claude retains its path. Without EXA, don't assume
non-native workers support Claude's server-side WebSearch. Provider permissions
must allow the model. Disable with `cma provider NAME --disable` then cma up.

### 6. Explicit live verification

```bash
cma smoke --model claude/chatgpt/gpt-6.1-sol --effort high --allow-spend
cma smoke --model claude/chatgpt/gpt-6-astra-backup --effort xhigh --allow-spend
cma smoke --model claude-sonnet-5-5 --allow-spend
```

These streaming tool-call/follow-up tests use quota or paid API money. Next ask
enhanced Claude to launch a harmless custom-model Agent and verify its result.
Neither --version nor readiness proves live account access/Agent execution.

## Operations and recovery

Read [OPS.md](OPS.md) for accounts, process stopping, updates, backup/recovery
and Remote Control; [ARCHITECTURE.md](ARCHITECTURE.md) explains auth and patches.

```bash
cma check
CMA_NO_PATCH=1 cma-claude            # no custom Agent schema; native client
CMA_REMOTE_CONTROL_PATCH=1 cma-claude --rc  # opt-in unsupported RC workaround
cma login-codex backup
cma-codex2                         # native fallback bypasses the gateway
```

No account launcher uses Bubblewrap. Second Claude credentials are separate
while sessions/settings are shared. Second native Codex uses separate CODEX_HOME,
including separate config/history. Defaults are not rewritten globally.

## Development and verification

```bash
PYTHONPATH=patches:scripts python3 -m unittest discover -s tests -p 'test_*.py' -v
./scripts/test-gateway.sh
claude plugin validate .
python3 tests/integration.py --allow-docker
python3 tests/install_check.py --allow-native
```

The opt-in Docker test creates its own random project/port, uses fake upstreams
and removes only its own containers/volumes. No live credentials are used.
The native install check prepares a copy of the installed Claude binary and
installs the public marketplace only into a disposable home, without inference
or account login. Root `CLAUDE.md` is contributor guidance; installed plugin
runtime guidance is provided by the skills and startup hooks.
[VERIFICATION.md](VERIFICATION.md) lists tested behavior and remaining login/
upgrade limitations. Third-party binaries/images are not redistributed;
see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Official references

- [Claude skills/scripts](https://code.claude.com/docs/en/skills)
- [Claude marketplaces](https://code.claude.com/docs/en/plugin-marketplaces)
- [Claude hooks](https://code.claude.com/docs/en/hooks)
- [LiteLLM ChatGPT provider](https://docs.litellm.ai/docs/providers/chatgpt)
- [Codex authentication](https://developers.openai.com/codex/auth/)
- [Codex CLI](https://developers.openai.com/codex/cli/reference/)
