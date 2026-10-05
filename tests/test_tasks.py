import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.env = os.environ | {'CMA_HOME': str(self.root / 'state'), 'CMA_RUNS_DIR': str(self.root / 'runs')}
        self.fake = self.root / 'codex'
        self.brief = self.root / 'BRIEF.md'; self.brief.write_text('A bounded dummy task.')
        self.runner = ROOT / 'scripts/codex_tasks.py'

    def tearDown(self): self.tmp.cleanup()

    def command(self, action='run', name='task'):
        command = [sys.executable, str(self.runner), action, name]
        if action == 'run': command += ['--brief', str(self.brief), '--cwd', str(self.root)]
        return command

    def install_fake(self, body):
        self.fake.write_text('#!/usr/bin/env python3\n' + body)
        self.fake.chmod(0o755); self.env['CMA_CODEX_BIN'] = str(self.fake)

    def test_report_real_exit_code_effort_and_no_prompt_in_argv(self):
        self.install_fake('''import json, pathlib, sys
args=sys.argv[1:]; prompt=sys.stdin.read()
assert 'A bounded dummy task.' in prompt
assert 'A bounded dummy task.' not in ' '.join(args)
assert '--sandbox' in args and '--dangerously-bypass-approvals-and-sandbox' not in args
assert 'model_reasoning_effort="high"' in args
pathlib.Path(args[args.index('--output-last-message')+1]).write_text('DONE')
sys.exit(7)
''')
        result = subprocess.run(self.command(), env=self.env, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 7, result.stderr)
        runs = self.root / 'runs'
        self.assertEqual((runs / 'task.report.md').read_text(), 'DONE')
        self.assertEqual(json.loads((runs / 'task.result.json').read_text())['exit_code'], 7)
        self.assertFalse((runs / 'task.pid.json').exists())

    def test_duplicate_refused_stop_kills_child_process_group(self):
        child_file = self.root / 'child.pid'
        self.install_fake('''import pathlib, subprocess, sys, time
sys.stdin.read()
p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(90)'])
pathlib.Path(%r).write_text(str(p.pid))
time.sleep(90)
''' % str(child_file))
        process = subprocess.Popen(self.command(), env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 5
            while not child_file.exists() and time.monotonic() < deadline: time.sleep(0.02)
            self.assertTrue(child_file.exists())
            duplicate = subprocess.run(self.command(), env=self.env, capture_output=True, timeout=5)
            self.assertNotEqual(duplicate.returncode, 0)
            self.assertIn(b'already running', duplicate.stderr)
            stopped = subprocess.run(self.command('stop'), env=self.env, capture_output=True, timeout=10)
            self.assertEqual(stopped.returncode, 0, stopped.stderr)
            process.communicate(timeout=10)
            child_status = Path('/proc/' + child_file.read_text() + '/stat')
            if child_status.exists():
                self.assertEqual(child_status.read_text().split(') ', 1)[1].split()[0], 'Z')
        finally:
            if process.poll() is None:
                subprocess.run(self.command('stop'), env=self.env, capture_output=True, timeout=10)
                process.communicate(timeout=10)

    def test_invalid_task_and_stale_pid_cannot_kill_caller(self):
        invalid = subprocess.run(self.command(name='../bad'), env=self.env, capture_output=True)
        self.assertNotEqual(invalid.returncode, 0)
        runs = self.root / 'runs'; runs.mkdir(exist_ok=True)
        (runs / 'task.pid.json').write_text(json.dumps({'pid': os.getpid(), 'start_ticks': 'wrong'}))
        result = subprocess.run(self.command('stop'), env=self.env, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'refusing to signal', result.stderr)


if __name__ == '__main__': unittest.main()
