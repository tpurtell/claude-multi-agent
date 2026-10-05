import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HookTests(unittest.TestCase):
    def test_each_start_kind_has_correct_protocol_and_local_guidance(self):
        for kind, source in [('SessionStart', 'startup'), ('SessionStart', 'resume'),
                             ('SessionStart', 'compact'), ('SubagentStart', None)]:
            result = subprocess.check_output([sys.executable, str(ROOT / 'hooks/session-start.py')],
                input=json.dumps({'hook_event_name': kind, 'source': source}), text=True,
                env=os.environ | {'CLAUDE_HYBRID_SUBAGENT_PATCH': '1'})
            output = json.loads(result)['hookSpecificOutput']
            self.assertEqual(output['hookEventName'], kind)
            text = output['additionalContext']
            self.assertIn('Gateway extensions active: yes', text)
            self.assertNotIn('${CLAUDE_PLUGIN_ROOT}', text)
            self.assertLess(len(text), 6500)
            if kind == 'SessionStart': self.assertIn('Inspect the actual Agent tool schema', text)
            else: self.assertIn('Complete only your assigned bounded task', text)

    def test_missing_extension_is_not_claimed_as_available(self):
        env = os.environ.copy(); env.pop('CLAUDE_HYBRID_SUBAGENT_PATCH', None)
        result = subprocess.check_output([sys.executable, str(ROOT / 'hooks/session-start.py')],
            input='{}', text=True, env=env)
        self.assertIn('not declared', result)


if __name__ == '__main__': unittest.main()
