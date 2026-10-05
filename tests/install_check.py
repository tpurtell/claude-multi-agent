#!/usr/bin/env python3
"""Opt-in actual client preparation/public marketplace install in a fake home."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-native', action='store_true')
    args = parser.parse_args()
    if not args.allow_native: parser.error('Pass --allow-native for isolated native preparation/install tests')
    original = Path(shutil.which('claude')).resolve(strict=True)
    before = hashlib.sha256(original.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix='cma-install-test-') as temp:
        home = Path(temp)
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('CLAUDE_', 'ANTHROPIC_', 'OPENAI_', 'CODEX_'))}
        env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / '.config'),
                   XDG_CACHE_HOME=str(home / '.cache'), XDG_DATA_HOME=str(home / '.local/share'),
                   CLAUDE_CONFIG_DIR=str(home / '.claude'), CMA_HOME=str(home / 'cma-state'))
        for key in ('DEEPSEEK_API_KEY', 'OPENROUTER_API_KEY', 'EXA_API_KEY'): env.pop(key, None)
        subprocess.run([sys.executable, str(ROOT / 'scripts/cma.py'), 'init', '--accounts', '2',
                        '--port', '49713'], env=env, check=True)
        prepared = subprocess.check_output([sys.executable, str(ROOT / 'patches/prepare.py'),
            '--source', str(original), '--gateway', 'http://127.0.0.1:49713',
            '--models-file', str(home / 'cma-state/config.json'), '--cache', str(home / 'clients')],
            env=env, text=True, timeout=60).strip()
        assert Path(prepared).is_relative_to(home)
        version = subprocess.check_output([prepared, '--version'], env=env, text=True).strip()
        manifest = json.loads((Path(prepared).parent / 'manifest.json').read_text())
        assert manifest['source_sha256'] == before and len(manifest['patches']) == 3
        print('Isolated real client preparation:', version)
        for command in (['plugin', 'marketplace', 'add', 'tpurtell/claude-multi-agent'],
                        ['plugin', 'install', 'hybrid-agents@tpurtell-agent-tools', '--scope', 'user'],
                        ['plugin', 'list']):
            result = subprocess.run([str(original), *command], env=env, cwd=home,
                                    text=True, capture_output=True, timeout=90)
            if result.returncode: raise RuntimeError('Isolated plugin command failed: ' + result.stderr[:1000])
            print(result.stdout.strip())
        installed = home / '.claude/plugins/installed_plugins.json'
        assert installed.is_file() and 'hybrid-agents@tpurtell-agent-tools' in installed.read_text()
    assert hashlib.sha256(original.read_bytes()).hexdigest() == before
    print('PASS: real native binary preserved; public marketplace installed only in disposable home; no inference or logins.')


if __name__ == '__main__': main()
