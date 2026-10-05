# Claude Multi-Agent

Claude-first orchestration across native Claude, Codex subscriptions, DeepSeek
and optional MiMo through a dedicated localhost LiteLLM gateway.

**Work in progress:** initial extraction and manager implementation. Installation
instructions, skills, recovery scripts and verification are being completed in
subsequent commits. Do not replace an existing deployment with this draft.

The package never installs Claude binaries or embeds subscription credentials.
Client patches are prepared in a separate checksum-verified cache. Gateway state
defaults to `~/.local/share/claude-multi-agent`; Docker exposes only loopback.

Based on practical multi-model Claude tooling and the orchestration guidance in
the author's CuteAFD work. No private NAS configuration or credentials are included.
