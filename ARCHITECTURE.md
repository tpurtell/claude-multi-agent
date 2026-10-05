# Architecture

Private state is outside Git. The proxy binds only 127.0.0.1; workers/PostgreSQL
stay on its private Compose network. Project/volume names are instance-specific.

```text
Claude Code (native OAuth; optional second secure store, shared sessions)
  isolated enhanced client: Agent.model/effort; optional RC host-gate patch
  Authorization: native OAuth; x-litellm-api-key: restricted gateway key
          |
  localhost LiteLLM proxy + PostgreSQL (key policy / usage / spend)
          |-- native Anthropic group --> Anthropic (client OAuth forwarded)
          |-- Codex primary --> chatgpt1 --> subscription 1
          |-- Codex -backup --> chatgpt2 --> subscription 2
          |-- optional DeepSeek / OpenRouter (separate paid API keys)
          `-- optional EXA (paid non-native search)

Direct Codex fallback: native CLI --> subscription; bypasses gateway
```

## Auth and routing

The gateway key is never ANTHROPIC_AUTH_TOKEN/API_KEY: those replace Claude's
native subscription auth. Only native groups forward client headers. API keys
stay in private .env, not images/code. Workers have distinct OAuth volumes and
serve only Sol/Astra; a process-global ChatGPT authenticator cannot serve two
accounts safely. Their worker key is private/internal; the proxy master/salt
and restricted virtual key are separate. No wildcard models or silent paid/
account fallback. Native IDs/aliases remain callable but hidden from listings.

Native protocol/header forwarding isn't a promise of byte-identical transport:
LiteLLM parses/routes requests and can alter envelopes across releases. Tests
verify auth scoping/tool loops, not vendor approval or model entitlement.

## Isolated client patch

The patcher checks an installed ELF64/Bun .bun/module layout, appends changed
JS source to a separate executable and invalidates caches only for edited
modules. It does not download/edit/redistribute the installed client. Manifest
checksums verify source/patch/output. Cache identity includes origin, finite
models and effort metadata; locking/atomic publication prevents races.

Agent.model additions require the exact loopback origin and enabled flag.
Agent.effort validates route/native capabilities and existing policy/env
resolution, then applies to a copied definition after model resolution; parent/
sibling defaults survive. Default/null means inheritance, not provider reset.
RC's host-gate exception is opt-in and leaves other eligibility checks intact.
Unknown layout/target signatures fail closed. No namespace/OS-policy changes.

## Version-sensitive callbacks

Reviewed LiteLLM 1.104 workarounds preserve dictionary completion usage and
tool-stop envelopes for Astra/Sol. System-to-developer conversion is ChatGPT-
provider-only. DeepSeek rewrites exactly Artifact's no-NUL tool-schema regex,
leaving history untouched. Catalog filtering hides native rows for ClaudeHybrid
only. Upgrade tests determine whether these workarounds are still appropriate.

## Skills/hooks and limits

SessionStart injects the concise orchestration core, including resume/compact;
SubagentStart injects a worker contract. Both read local package files only.
Detailed references stay on demand. Automatic loading is not guaranteed model
compliance, and managed/project instructions remain authoritative.

Linux-only patcher; human-only logins; no access/quota grants; no general WebUI
deployment or public HTTPS ingress; no exhaustive context-limit compaction test;
no Redis-wide quota coordination; no assumption every vendor upgrade works.
Second native Codex histories are separate; second native Claude histories share.
