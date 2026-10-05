# Model roster and effort

Only choose models advertised by the current gateway AND the actual Agent tool
schema. The generated installation enables four Codex routes with two accounts;
DeepSeek/MiMo appear only when their corresponding provider keys are configured.

| ID | Role | Suggested effort | Allowed explicit effort |
| --- | --- | --- | --- |
| `claude/chatgpt/gpt-6.1-sol` | Bounded engineering | high; xhigh for subtle work | low, medium, high, xhigh, max |
| `claude/chatgpt/gpt-6.1-sol-backup` | Same, second Codex subscription | high/xhigh | same |
| `claude/chatgpt/gpt-6-astra` | Difficult design, independent insight | medium/high | low, medium, high, xhigh, max |
| `claude/chatgpt/gpt-6-astra-backup` | Same, second Codex subscription | medium/high | same |
| `claude/deepseek/deepseek-flash` | Mechanical refactors, digests, simple scripts | high; max for larger sweeps | low, high, max |
| `claude/xiaomi/mimo-v2.6-pro` | Optional fallback through OpenRouter | default | omit, null, default only |
| Native `opus`, `sonnet`, `haiku`, `fable` | Account-supported Claude work | default | installed client validates capabilities |

DeepSeek's medium/xhigh map upstream to high and are not advertised as distinct
levels. Native Claude capabilities change with the client/model/account; do not
invent them or force unsupported effort. Omitted/null/default retains existing
agent/session defaults; it does not force an upstream reset. Explicit effort is
supported on standalone foreground/background agents, not forks, named teammates
or remote/cloud agent launches. Settings/policy/forced-environment conflicts fail
explicitly instead of silently downgrading effort.

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
