#!/usr/bin/env python3
"""Inject local, bounded orchestration guidance; no network or credential reads."""
import json
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
try:
    event = json.load(sys.stdin)
except (ValueError, OSError):
    event = {}
kind = event.get('hook_event_name', 'SessionStart')
if kind == 'SubagentStart':
    body = (root / 'skills/codex-fallback/references/worker-preamble.md').read_text()
else:
    text = (root / 'skills/agent-orchestration/SKILL.md').read_text()
    body = text.split('---', 2)[2].strip()
body = body.replace('${CLAUDE_PLUGIN_ROOT}', str(root))
body += '\n\nGateway extensions active: ' + ('yes' if os.getenv('CLAUDE_HYBRID_SUBAGENT_PATCH') == '1' else
        'not declared; inspect the actual Agent tool schema before choosing custom models')
print(json.dumps({'hookSpecificOutput': {'hookEventName': kind, 'additionalContext': body}}))
