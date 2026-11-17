# Model roster and effort

Only choose models advertised by the current gateway AND the actual Agent tool
schema. The generated installation enables four Codex routes with two accounts;
DeepSeek/MiMo appear only when their corresponding provider keys are configured.

| ID | Role | Suggested effort | Allowed explicit effort |
| --- | --- | --- | --- |
| `claude/gpt-sol` | Bounded engineering; primary, currently Sol 6.2 | high; xhigh for subtle work | low, medium, high, xhigh, max |
| `claude/chatgpt/gpt-6.1-sol-backup` | Same, second Codex subscription | high/xhigh | same |
| `claude/gpt-astra` | Difficult design, independent insight; primary, currently Astra 6.2 | medium/high | low, medium, high, xhigh, max |
| `claude/chatgpt/gpt-6-astra-backup` | Same, second Codex subscription | medium/high | same |
| `claude/deepseek/deepseek-flash` | Mechanical refactors, digests, simple scripts | high; max for larger sweeps | low, high, max; medium→high, xhigh→max |
| `claude/xiaomi/mimo-v2.6-pro` | Optional fallback through OpenRouter | default | omit, null, default only |
| Native `opus`, `sonnet`, `haiku`, `fable` | Account-supported Claude work | default | installed client validates capabilities |

The client maps DeepSeek's medium→high and xhigh→max before native effort
resolution; the gateway advertises only the three actual provider levels.
Native Claude capabilities change with the client/model/account; do not
invent them or force unsupported effort. Omitted/null/default retains existing
agent/session defaults; it does not force an upstream reset. Explicit effort is
supported on standalone foreground/background agents. Native 2.1.296 forks
ignore per-launch model/effort and inherit the parent; the older transport rejects
explicit fork effort. Named teammates and gateway remote/cloud agent launches
do not support this override. Gateway settings/policy/forced-environment conflicts
fail explicitly instead of silently downgrading effort; native Claude keeps its
own resolution behavior.

Primary GPT aliases keep the same Agent model IDs when upgraded. Their upstream
targets live in the instance's private `subscription_aliases` configuration;
retarget/reload the gateway rather than changing the client's finite roster.
The Agent effort interface exposes the five levels above; the 6.2 subscription
catalog's separate `ultra` delegation mode is not exposed by this patch.

Claude Code 2.1.292+ has native per-invocation Agent effort. The patch extends
that existing schema and retains native launch/background/resume persistence,
instead of adding a duplicate effort field or a second transport. Omit an
absolute effort unless the user or applicable instructions requested it, as
the native tool description requires. If the client offers feature-gated
lower/higher, retain its relative-step semantics; it excludes max, which must
be requested explicitly. Do not force-enable that feature or invent a graded
MiMo effort scale. Null/default preserves inheritance, not a provider reset.

Native Claude Max OAuth stays on the client. Each Codex subscription has its own
Docker worker and OAuth volume. `-backup` means explicit account selection, not
automatic retry. Neither subscription preference nor available budget is
universal: ask for a preference or use the user's stated one. Codex model access
must be verified after login; the package cannot grant account entitlements.

Subscriptions have zero *API billing attribution* in this gateway, not unlimited
or free usage. Quotas still apply. DeepSeek/MiMo/EXA are separately billable.
Codex routes advertise 272k input and 128k output. Claude may use a conservative
200k budget for unfamiliar model IDs; the picker does not propagate gateway
context metadata into Claude's internal budgeting. Normal subagent compaction
uses that agent's selected model; forced long-context live tests are not included.
