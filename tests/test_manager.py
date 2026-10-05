import argparse
from contextlib import redirect_stdout
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'patches'))
import cma
import prepare


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / 'state'
        self.env = patch.dict(os.environ, {'CMA_HOME': str(self.home)}, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop(); self.tmp.cleanup()

    def init(self, accounts=2, **keys):
        with patch.dict(os.environ, keys), redirect_stdout(io.StringIO()):
            cma.init(argparse.Namespace(port=40213, accounts=accounts, yolo=False))

    def test_init_private_idempotence_and_only_loopback_port(self):
        self.init()
        cfg = cma.config()
        compose = json.loads((self.home / 'compose.json').read_text())
        self.assertEqual(len(cfg['models']), 4)
        self.assertEqual(compose['services']['proxy']['ports'], ['127.0.0.1:40213:4000'])
        for name, service in compose['services'].items():
            if name != 'proxy': self.assertNotIn('ports', service)
        self.assertEqual(self.home.stat().st_mode & 0o777, 0o700)
        for name in ('.env', 'config.json', 'compose.json', 'proxy.yaml'):
            self.assertEqual((self.home / name).stat().st_mode & 0o777, 0o600)
        before = (self.home / '.env').read_bytes()
        with self.assertRaises(ValueError): self.init()
        self.assertEqual((self.home / '.env').read_bytes(), before)
        self.assertEqual(len(set(cma.env_secrets().values())), 4)

    def test_optional_providers_and_one_account_catalog(self):
        self.init(accounts=1, DEEPSEEK_API_KEY='dummy-deepseek', OPENROUTER_API_KEY='dummy-openrouter',
                  EXA_API_KEY='dummy-exa')
        self.assertEqual(len(cma.config()['models']), 4)
        self.assertFalse(any(model.endswith('-backup') for model in cma.config()['models']))
        routes = json.loads((self.home / 'proxy.yaml').read_text())
        self.assertIn('websearch_interception', routes['litellm_settings']['callbacks'])
        self.assertEqual(routes['search_tools'][0]['litellm_params']['api_key'], 'os.environ/EXA_API_KEY')
        self.assertNotIn('dummy-', (self.home / 'proxy.yaml').read_text())

    def test_header_forwarding_native_only_and_no_fixed_effort(self):
        self.init(DEEPSEEK_API_KEY='dummy', OPENROUTER_API_KEY='dummy')
        proxy = json.loads((self.home / 'proxy.yaml').read_text())
        self.assertEqual(proxy['litellm_settings']['model_group_settings'],
                         {'forward_client_headers_to_llm_api': ['claude/anthropic/*']})
        for route in proxy['model_list']:
            self.assertNotIn('reasoning_effort', route['litellm_params'])
            if route['model_name'].startswith('claude/anthropic/'):
                self.assertNotIn('api_key', route['litellm_params'])
            if '/chatgpt/' in route['model_name']:
                self.assertEqual(route['model_info']['max_input_tokens'], 272000)
                self.assertEqual(route['model_info']['reasoning_effort_levels'], cma.LEVELS)
                self.assertEqual(route['litellm_params']['allowed_openai_params'], ['reasoning_effort'])
        compose = json.loads((self.home / 'compose.json').read_text())
        self.assertNotEqual(compose['services']['chatgpt1']['volumes'][-1],
                            compose['services']['chatgpt2']['volumes'][-1])
        self.assertNotIn('database', str(compose['services']['chatgpt1']['environment']))

    def test_key_exact_policy_and_no_native_picker_duplicates(self):
        self.init()
        cfg = cma.config(); policy = cma.key_policy(cfg)
        self.assertEqual(set(policy['models']), set(cfg['models']) |
                         {'claude/anthropic/' + name for name in cfg['anthropic_model_ids']})
        self.assertTrue(set(policy['aliases'].values()) <= set(policy['models']))
        cma.write_private(self.home / 'gateway-key.json', {'key': 'sk-dummy'})
        response = io.BytesIO(json.dumps({'data': [{'id': name} for name in cfg['models']]}).encode())
        with patch.object(cma.urllib.request, 'urlopen', return_value=response):
            self.assertEqual([r['id'] for r in cma.catalog()], cfg['models'])
        response = io.BytesIO(b'{"data":[{"id":"claude/anthropic/claude-opus-5-5"}]}')
        with patch.object(cma.urllib.request, 'urlopen', return_value=response), self.assertRaises(ValueError):
            cma.catalog()

    def test_state_and_secret_guardrails(self):
        self.init()
        target = self.home / 'target'; target.write_text('unchanged')
        link = self.home / 'link'; link.symlink_to(target)
        with self.assertRaises(ValueError): cma.write_private(link, 'new')
        self.assertEqual(target.read_text(), 'unchanged')
        for value in ('new\nline', '${TOKEN}', ' two ', "a'b", 'a#b'):
            with self.assertRaises(ValueError): cma.write_env({'TEST': value})
        with patch.dict(os.environ, {'CMA_HOME': '/'}), self.assertRaises(ValueError): cma.state_dir()

    def test_launch_dispatch_env_and_installed_argument_forwarding(self):
        self.init()
        cma.write_private(self.home / 'gateway-key.json', {'key': 'sk-dummy'})
        secondary = self.home / 'claude-account-2'; secondary.mkdir()
        (secondary / '.credentials.json').write_text('dummy')
        args = argparse.Namespace(account='backup', no_patch=True, remote_control_patch=False,
                                  yolo=True, args=['--', '--resume'])
        with patch.dict(os.environ, {'CLAUDE_SECURESTORAGE_CONFIG_DIR': '/inherited',
                    'ANTHROPIC_AUTH_TOKEN': 'wrong', 'SSH_AUTH_SOCK': '/test-agent'}), \
                patch.object(cma, 'catalog', return_value=[{'id': n} for n in cma.config()['models']]), \
                patch.object(cma.os, 'execvpe') as execute:
            cma.launch(args)
            _, command, env = execute.call_args.args
            self.assertIn('--resume', command)
            self.assertIn('--dangerously-skip-permissions', command)
            self.assertEqual(env['CLAUDE_SECURESTORAGE_CONFIG_DIR'], str(secondary))
            self.assertNotIn('ANTHROPIC_AUTH_TOKEN', env)
            self.assertEqual(env['SSH_AUTH_SOCK'], '/test-agent')
            args.account = 'primary'; cma.launch(args)
            self.assertNotIn('CLAUDE_SECURESTORAGE_CONFIG_DIR', execute.call_args.args[2])
        bindir = Path(self.tmp.name) / 'bin'
        subprocess.run([sys.executable, str(ROOT / 'scripts/cma.py'), 'install-launchers',
                        '--bin-dir', str(bindir)], check=True, capture_output=True)
        self.assertIn('launch --account backup -- "$@"', (bindir / 'cma-claude2').read_text())
        repeat = subprocess.run([sys.executable, str(ROOT / 'scripts/cma.py'), 'install-launchers',
                        '--bin-dir', str(bindir)], capture_output=True)
        self.assertNotEqual(repeat.returncode, 0)

    def test_codex_backup_environment_and_direct_login(self):
        self.init()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'wrong', 'OPENAI_BASE_URL': 'http://wrong'}):
            env = cma.codex_environment('backup')
            self.assertEqual(env['CODEX_HOME'], str(self.home / 'codex-account-2'))
            self.assertNotIn('OPENAI_API_KEY', env); self.assertNotIn('OPENAI_BASE_URL', env)

    def test_patch_scope_subset_and_cache_configuration_identity(self):
        approved = json.loads((ROOT / 'profiles/models.json').read_text())['other_models']
        try:
            prepare.configure('http://127.0.0.1:40213', approved[:2])
            self.assertEqual(prepare.SUBAGENT_MODELS, tuple(approved[:2]))
            self.assertIn(':40213', prepare.HYBRID_ENABLED)
            for base in ('http://0.0.0.0:4000', 'https://example.com:4000',
                         'http://127.0.0.1:4000/path', 'http://user@127.0.0.1:4000'):
                with self.assertRaises(ValueError): prepare.configure(base, approved)
            with self.assertRaises(ValueError): prepare.configure('http://127.0.0.1:4000', ['claude/random'])
        finally:
            prepare.configure('http://127.0.0.1:4000', approved)


if __name__ == '__main__': unittest.main()
