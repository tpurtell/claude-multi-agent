#!/usr/bin/env python3
"""Claude-first localhost gateway manager. Standard library; secrets stay local."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PROFILE = json.loads((ROOT / 'profiles/models.json').read_text())
IMAGE = 'docker.litellm.ai/berriai/litellm:1.104.0'
LEVELS = ['low', 'medium', 'high', 'xhigh', 'max']


def state_dir():
    path = Path(os.environ.get('CMA_HOME', Path.home() / '.local/share/claude-multi-agent')).absolute()
    if path.is_symlink() or path.resolve() in (Path('/'), Path.home().resolve(), ROOT):
        raise ValueError('Use a dedicated nonsymlink CMA_HOME, not home, / or the checkout root')
    if path.exists() and path.stat().st_uid != os.getuid():
        raise ValueError('CMA_HOME must belong to the current user')
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    path.chmod(0o700)
    return path


def write_private(path, value):
    """Atomic replacement, including refreshed keys; refuse symlink targets."""
    if path.is_symlink():
        raise ValueError('Refusing symlinked state file: ' + str(path))
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    content = json.dumps(value, indent=2) + '\n' if not isinstance(value, str) else value
    fd, temporary = tempfile.mkstemp(prefix='.writing-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def config():
    return json.loads((state_dir() / 'config.json').read_text())


def env_secrets():
    return dict(line.split('=', 1) for line in (state_dir() / '.env').read_text().splitlines()
                if line and not line.startswith('#'))


def write_env(values):
    if any('\n' in value or '\r' in value or '$' in value or '#' in value or
           '"' in value or "'" in value or value.strip() != value for value in values.values()):
        raise ValueError('Secrets must be single-line plain tokens (no shell/Compose interpolation)')
    write_private(state_dir() / '.env', ''.join(key + '=' + value + '\n' for key, value in values.items()))


def api(path, payload=None, *, token=None, method=None):
    cfg = config()
    key = token or env_secrets()['LITELLM_MASTER_KEY']
    request = urllib.request.Request(cfg['base_url'] + path,
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
        data=None if payload is None else json.dumps(payload).encode(), method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        # Do not expose upstream bodies, URLs with query keys or auth headers.
        raise RuntimeError('Gateway request failed: HTTP ' + str(error.code)) from None


def compose(*args, check=True, capture=False):
    cfg = config()
    return subprocess.run(['docker', 'compose', '--project-name', cfg['project'],
        '--env-file', str(state_dir() / '.env'), '-f', str(state_dir() / 'compose.json'), *args],
        check=check, capture_output=capture, text=capture, env=compose_environment())


def compose_environment():
    # Shell exports take precedence over Compose --env-file. Do not accidentally
    # apply another deployment's exported database/master/provider secrets.
    env = os.environ.copy()
    for name in set(env_secrets()) | {'DEEPSEEK_API_KEY', 'OPENROUTER_API_KEY', 'EXA_API_KEY'}:
        env.pop(name, None)
    return env


def subscription_info(ident):
    return {'id': ident, 'mode': 'responses', 'supports_vision': True,
        'supports_reasoning': True, 'supports_function_calling': True,
        'reasoning_effort_levels': LEVELS, 'supports_none_reasoning_effort': False,
        'supports_minimal_reasoning_effort': False, 'supports_xhigh_reasoning_effort': True,
        'supports_max_reasoning_effort': True, 'max_input_tokens': 272000,
        'max_output_tokens': 128000, 'input_cost_per_token': 0, 'output_cost_per_token': 0,
        'cache_read_input_token_cost': 0, 'cache_creation_input_token_cost': 0}


def enabled_models(accounts, values):
    return [model for model in PROFILE['other_models']
        if (not model.endswith('-backup') or accounts == 2)
        and ('/deepseek/' not in model or values.get('DEEPSEEK_API_KEY'))
        and ('/xiaomi/' not in model or values.get('OPENROUTER_API_KEY'))]


def worker_routes(worker):
    return [{'model_name': model, 'litellm_params': {
        'model': 'chatgpt/' + model, 'timeout': 900, 'num_retries': 0,
        'allowed_openai_params': ['reasoning_effort'], 'input_cost_per_token': 0,
        'output_cost_per_token': 0}, 'model_info': subscription_info(worker + '-' + model)}
        for model in ('gpt-6.1-sol', 'gpt-6-astra')]


def render():
    home, cfg = state_dir(), config()
    values = env_secrets()
    cfg['models'] = enabled_models(cfg['accounts'], values)
    write_private(home / 'config.json', cfg)
    native = [{'model_name': 'claude/anthropic/' + model,
        'litellm_params': {'model': 'anthropic/' + model, 'timeout': 900, 'num_retries': 0,
                          'input_cost_per_token': 0, 'output_cost_per_token': 0},
        'model_info': {'mode': 'chat', 'supports_vision': True, 'supports_function_calling': True}}
        for model in cfg['anthropic_model_ids']]
    routes = list(native)
    for name in cfg['models']:
        if '/chatgpt/' in name:
            model = name.rsplit('/', 1)[-1].removesuffix('-backup')
            worker = 'chatgpt2' if name.endswith('-backup') else 'chatgpt1'
            routes.append({'model_name': name, 'litellm_params': {'model': 'openai/' + model,
                'api_base': 'http://' + worker + ':4000/v1', 'api_key': 'os.environ/CMA_WORKER_KEY',
                'timeout': 900, 'num_retries': 0, 'allowed_openai_params': ['reasoning_effort'],
                'input_cost_per_token': 0, 'output_cost_per_token': 0},
                'model_info': subscription_info('proxy-' + worker + '-' + model)})
        elif '/deepseek/' in name:
            routes.append({'model_name': name, 'litellm_params': {'model': 'deepseek/deepseek-flash',
                'api_key': 'os.environ/DEEPSEEK_API_KEY', 'num_retries': 0, 'timeout': 900},
                'model_info': {'supports_vision': True, 'supports_reasoning': True,
                    'reasoning_effort_levels': ['low', 'high', 'max'],
                    'supports_max_reasoning_effort': True, 'supports_xhigh_reasoning_effort': False}})
        elif '/xiaomi/' in name:
            routes.append({'model_name': name, 'litellm_params': {'model': 'openrouter/xiaomi/mimo-v2.6-pro',
                'api_key': 'os.environ/OPENROUTER_API_KEY', 'num_retries': 0, 'timeout': 900},
                'model_info': {'supports_vision': True, 'supports_function_calling': True}})
    callbacks = ['subscription_messages.callback', 'hybrid_catalog.callback', 'deepseek_compat.callback']
    settings = {'callbacks': callbacks, 'model_group_settings': {
        'forward_client_headers_to_llm_api': ['claude/anthropic/*']}}
    proxy = {'model_list': routes, 'litellm_settings': settings,
             'general_settings': {'master_key': 'os.environ/LITELLM_MASTER_KEY'}}
    if values.get('EXA_API_KEY'):
        proxy['search_tools'] = [{'search_tool_name': 'exa-search', 'litellm_params': {
            'search_provider': 'exa_ai', 'api_key': 'os.environ/EXA_API_KEY'}}]
        settings['callbacks'].insert(0, 'websearch_interception')
        settings['websearch_interception_params'] = {'enabled_providers': ['deepseek', 'openrouter', 'openai'],
                                                     'search_tool_name': 'exa-search'}
    write_private(home / 'proxy.yaml', proxy)  # JSON is valid YAML; no host PyYAML dependency.
    health = {'test': ['CMD', 'python', '-c',
        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4000/health/readiness', timeout=5)"],
        'interval': '5s', 'timeout': '8s', 'retries': 40, 'start_period': '60s'}
    shared = {'image': cfg['image'], 'init': True, 'restart': 'unless-stopped',
        'entrypoint': ['/bin/sh', '-c'],
        'logging': {'driver': 'json-file', 'options': {'max-size': '10m', 'max-file': '3'}},
        'healthcheck': health}
    mounts = [str(ROOT / 'gateway' / (module + '.py')) + ':/app/' + module + '.py:ro'
              for module in ('subscription_messages', 'hybrid_catalog', 'deepseek_compat')]
    services = {'db': {'image': cfg['postgres_image'], 'restart': 'unless-stopped',
        'environment': {'POSTGRES_USER': 'litellm', 'POSTGRES_DB': 'litellm',
                        'POSTGRES_PASSWORD': '${POSTGRES_PASSWORD}'},
        'volumes': ['database:/var/lib/postgresql/data'],
        'healthcheck': {'test': ['CMD-SHELL', 'pg_isready -U litellm -d litellm'],
                        'interval': '5s', 'timeout': '5s', 'retries': 30}}}
    deps = {'db': {'condition': 'service_healthy'}}
    for number in range(1, cfg['accounts'] + 1):
        worker = 'chatgpt' + str(number)
        # LiteLLM eagerly authenticates ChatGPT while constructing its router.
        # Start an empty, healthy worker before human login; activate its real
        # deployments only after the explicit one-off device flow succeeds.
        worker_config = {'model_list': worker_routes(worker)
                         if worker in cfg.get('authorized_workers', []) else [],
            'general_settings': {'master_key': 'os.environ/LITELLM_MASTER_KEY'},
            'litellm_settings': {'callbacks': ['subscription_messages.callback']}}
        write_private(home / (worker + '.yaml'), worker_config)
        services[worker] = dict(shared, command=[
            'umask 077; exec /app/docker/prod_entrypoint.sh --config /app/worker.yaml --port 4000'],
            environment={'LITELLM_MASTER_KEY': '${CMA_WORKER_KEY}', 'CHATGPT_TOKEN_DIR': '/app/chatgpt-auth',
                         'LITELLM_DISABLE_NO_REDIS_WARNING': 'true', 'LITELLM_MODE': 'PRODUCTION'},
            volumes=[str(home / (worker + '.yaml')) + ':/app/worker.yaml:ro', mounts[0],
                     worker + '-auth:/app/chatgpt-auth'])
        deps[worker] = {'condition': 'service_healthy'}
    services['proxy'] = dict(shared, command=[
        'umask 077; exec /app/docker/prod_entrypoint.sh --config /app/proxy.yaml --port 4000'],
        environment={'LITELLM_MASTER_KEY': '${LITELLM_MASTER_KEY}', 'LITELLM_SALT_KEY': '${LITELLM_SALT_KEY}',
            'CMA_WORKER_KEY': '${CMA_WORKER_KEY}',
            'DATABASE_URL': 'postgresql://litellm:${POSTGRES_PASSWORD}@db:5432/litellm',
            'STORE_MODEL_IN_DB': 'True', 'LITELLM_DISABLE_NO_REDIS_WARNING': 'true', 'LITELLM_MODE': 'PRODUCTION',
            'DEEPSEEK_API_KEY': '${DEEPSEEK_API_KEY:-}', 'OPENROUTER_API_KEY': '${OPENROUTER_API_KEY:-}',
            'EXA_API_KEY': '${EXA_API_KEY:-}'},
        volumes=[str(home / 'proxy.yaml') + ':/app/proxy.yaml:ro', *mounts],
        ports=['127.0.0.1:' + str(cfg['port']) + ':4000'], depends_on=deps)
    volumes = {'database': {}} | {'chatgpt' + str(n) + '-auth': {} for n in range(1, cfg['accounts'] + 1)}
    write_private(home / 'compose.json', {'services': services, 'volumes': volumes})


def init(args):
    home = state_dir()
    if (home / 'config.json').exists() or (home / '.env').exists():
        raise ValueError('State already exists; use render/provider instead of replacing credentials')
    if not 1024 <= args.port <= 65535:
        raise ValueError('Choose an unprivileged TCP port from 1024 to 65535')
    values = {key: 'sk-' + secrets.token_urlsafe(32) for key in ('LITELLM_MASTER_KEY', 'CMA_WORKER_KEY')}
    values.update(LITELLM_SALT_KEY=secrets.token_urlsafe(32), POSTGRES_PASSWORD=secrets.token_urlsafe(32))
    values.update({key: os.environ[key] for key in ('DEEPSEEK_API_KEY', 'OPENROUTER_API_KEY', 'EXA_API_KEY')
                   if os.environ.get(key)})
    cfg = {'version': 1, 'port': args.port, 'base_url': 'http://127.0.0.1:' + str(args.port),
        'project': 'cma-' + secrets.token_hex(4), 'accounts': args.accounts, 'image': IMAGE,
        'postgres_image': 'postgres:16-alpine', 'yolo': args.yolo,
        'anthropic_model_ids': PROFILE['anthropic_model_ids'], 'native_aliases': PROFILE['native_aliases'],
        'authorized_workers': []}
    write_env(values)
    write_private(home / 'config.json', cfg)
    render()
    print('Prepared private state at', home, '(no services started or launchers installed).')


def key_policy(cfg):
    aliases = {model: 'claude/anthropic/' + model for model in cfg['anthropic_model_ids']}
    aliases.update({name: 'claude/anthropic/' + target for name, target in cfg['native_aliases'].items()})
    if not set(cfg['native_aliases'].values()) <= set(cfg['anthropic_model_ids']):
        raise ValueError('Native aliases must point at configured native models')
    return {'key_alias': 'ClaudeHybrid', 'models': list(dict.fromkeys(aliases.values())) + cfg['models'],
            'aliases': aliases}


def sync_key():
    policy, path = key_policy(config()), state_dir() / 'gateway-key.json'
    if path.exists():
        key = json.loads(path.read_text())['key']
        api('/key/update', {'key': key, **policy})
    else:
        existing = api('/key/list?return_full_object=true')['keys']
        if any(isinstance(item, dict) and item.get('key_alias') == 'ClaudeHybrid' for item in existing):
            raise ValueError('Key already exists in the database; restore gateway-key.json from backup')
        key = api('/key/generate', policy)['key']
        write_private(path, {'key': key})
    actual = api('/key/info', token=key)['info']
    if not all(actual.get(name) == value for name, value in policy.items()):
        raise ValueError('Key policy read-back mismatch')
    print('Restricted gateway key provisioned and verified (not printed).')


def catalog():
    key = json.loads((state_dir() / 'gateway-key.json').read_text())['key']
    request = urllib.request.Request(config()['base_url'] + '/v1/models?limit=1000',
                                    headers={'x-litellm-api-key': 'Bearer ' + key})
    with urllib.request.urlopen(request, timeout=10) as response:
        rows = json.load(response)['data']
    expected = set(config()['models'])
    if len(rows) != len(expected) or {row['id'] for row in rows} != expected:
        raise ValueError('Gateway catalog does not exactly match this installation; run sync-key')
    by_id = {row['id']: row for row in rows}
    return [by_id[name] for name in config()['models']]


def check():
    cfg = config()
    with urllib.request.urlopen(cfg['base_url'] + '/health/readiness', timeout=10) as response:
        if response.status != 200:
            raise ValueError('Gateway not ready')
    policy = key_policy(cfg)
    key = json.loads((state_dir() / 'gateway-key.json').read_text())['key']
    actual = api('/key/info', token=key)['info']
    if not all(actual.get(name) == value for name, value in policy.items()):
        raise ValueError('Restricted key policy mismatch')
    print('Ready:', cfg['base_url'], '| exact restricted catalog:', len(catalog()), 'extras')
    for number in range(1, cfg['accounts'] + 1):
        code = "from pathlib import Path; p=Path('/app/chatgpt-auth/auth.json'); print('present' if p.is_file() and p.stat().st_size else 'login required')"
        result = compose('exec', '-T', 'chatgpt' + str(number), 'python', '-c', code, capture=True)
        print('Codex subscription', number, ':', result.stdout.strip())
        if 'chatgpt' + str(number) not in cfg.get('authorized_workers', []):
            print('  Routes inactive until explicit login-chatgpt succeeds, then run up.')
    print('No inference requests made; OAuth file presence is not proof that tokens remain valid.')


def clean_client_env():
    env = os.environ.copy()
    for name in ('CLAUDE_CONFIG_DIR', 'CLAUDE_CODE_OAUTH_TOKEN', 'ANTHROPIC_AUTH_TOKEN',
                 'ANTHROPIC_API_KEY', 'CLAUDE_SECURESTORAGE_CONFIG_DIR',
                 'CLAUDE_CODE_SUBAGENT_MODEL', 'CLAUDE_CODE_SUBAGENT_MODEL_FORCE',
                 'CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY', 'ANTHROPIC_CUSTOM_MODEL_OPTION',
                 'ANTHROPIC_CUSTOM_MODEL_OPTION_NAME', 'ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION'):
        env.pop(name, None)
    return env


def launch(args):
    cfg, env = config(), clean_client_env()
    env['ANTHROPIC_BASE_URL'] = cfg['base_url']
    key = json.loads((state_dir() / 'gateway-key.json').read_text())['key']
    env['ANTHROPIC_CUSTOM_HEADERS'] = 'x-litellm-api-key: Bearer ' + key
    env['ANTHROPIC_MODEL'] = os.getenv('CMA_COORDINATOR_MODEL', 'claude-opus-5-5')
    env.update(ANTHROPIC_DEFAULT_OPUS_MODEL='claude-opus-5-5', ANTHROPIC_DEFAULT_SONNET_MODEL='claude-sonnet-5-5',
               ANTHROPIC_DEFAULT_HAIKU_MODEL='claude-haiku-4-5')
    if args.account == 'backup':
        directory = Path(os.getenv('CMA_CLAUDE_SECONDARY_DIR', state_dir() / 'claude-account-2')).absolute()
        path = directory / '.credentials.json'
        if not path.is_file() or path.is_symlink():
            raise ValueError('Second Claude login missing; run cma login-claude backup')
        env['CLAUDE_SECURESTORAGE_CONFIG_DIR'] = str(directory)
    picker = {'modelPicker': {'replaceBuiltInOptions': False, 'options': [
        {'model': row['id'], 'label': row.get('display_name') or row['id'],
         'description': row.get('description') or 'ClaudeHybrid extra model'} for row in catalog()]}}
    executable = os.getenv('CMA_CLAUDE_BIN', 'claude')
    if not args.no_patch and os.getenv('CMA_NO_PATCH') != '1':
        env.update(CLAUDE_HYBRID_REMOTE_CONTROL_PATCH='1' if args.remote_control_patch or
                   os.getenv('CMA_REMOTE_CONTROL_PATCH') == '1' else '0',
                   CLAUDE_HYBRID_SUBAGENT_PATCH='1', DISABLE_AUTOUPDATER='1')
        executable = subprocess.check_output([sys.executable, str(ROOT / 'patches/prepare.py'),
            '--source', shutil.which(executable) or executable, '--gateway', cfg['base_url'],
            '--models-file', str(state_dir() / 'config.json'), '--cache', str(state_dir() / 'clients')],
            env=env, text=True).strip()
    else:
        env['CLAUDE_HYBRID_SUBAGENT_PATCH'] = '0'
        env['CLAUDE_HYBRID_REMOTE_CONTROL_PATCH'] = '0'
    options = ['--plugin-dir', str(ROOT), '--settings', json.dumps(picker, separators=(',', ':'))]
    if args.yolo or cfg['yolo']:
        options.append('--dangerously-skip-permissions')
    extra = args.args[1:] if args.args[:1] == ['--'] else args.args
    os.execvpe(executable, [executable, *options, *extra], env)


def codex_environment(account):
    env = os.environ.copy()
    # Direct Codex fallback must not inherit a gateway or API-key override.
    for key in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'CODEX_ACCESS_TOKEN', 'OPENAI_BASE_URL'):
        env.pop(key, None)
    if account == 'backup':
        home = Path(os.getenv('CMA_CODEX_SECONDARY_HOME', state_dir() / 'codex-account-2')).absolute()
        home.mkdir(parents=True, mode=0o700, exist_ok=True)
        env['CODEX_HOME'] = str(home)
    return env


def backup():
    directory = state_dir() / 'backups'
    directory.mkdir(mode=0o700, exist_ok=True)
    import datetime
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    bundle = directory / stamp
    bundle.mkdir(mode=0o700)
    target = bundle / 'database.dump'
    with target.open('xb') as output:
        target.chmod(0o600)
        cfg = config()
        subprocess.run(['docker', 'compose', '--project-name', cfg['project'], '--env-file',
            str(state_dir() / '.env'), '-f', str(state_dir() / 'compose.json'), 'exec', '-T',
            'db', 'pg_dump', '-U', 'litellm', '-d', 'litellm', '-Fc'], stdout=output, check=True,
            env=compose_environment())
    for name in ('.env', 'config.json', 'compose.json', 'proxy.yaml', 'chatgpt1.yaml', 'chatgpt2.yaml', 'gateway-key.json'):
        source = state_dir() / name
        if source.is_file(): write_private(bundle / name, source.read_text())
    for number in range(1, config()['accounts'] + 1):
        archive = bundle / ('chatgpt' + str(number) + '-auth.tar.gz')
        with archive.open('xb') as output:
            archive.chmod(0o600)
            subprocess.run(['docker', 'compose', '--project-name', cfg['project'], '--env-file',
                str(state_dir() / '.env'), '-f', str(state_dir() / 'compose.json'), 'exec', '-T',
                'chatgpt' + str(number), 'tar', '-czf', '-', '-C', '/app/chatgpt-auth', '.'],
                stdout=output, check=True, env=compose_environment())
    write_private(bundle / 'manifest.json', {'image': config()['image'], 'accounts': config()['accounts'],
                                            'project': config()['project'], 'created_utc': stamp})
    print('Private gateway backup bundle:', bundle)
    print('Contains database, salt/keys/config and Codex OAuth volumes. Encrypt/store privately; never commit it.')
    return bundle


def native_token(account):
    directory = Path.home() / '.claude' if account == 'primary' else Path(
        os.getenv('CMA_CLAUDE_SECONDARY_DIR', state_dir() / 'claude-account-2'))
    path = directory / '.credentials.json'
    if not path.is_file() or path.is_symlink(): raise ValueError('Native Claude login missing')
    return json.loads(path.read_text())['claudeAiOauth']['accessToken']


def start_stack():
    """Refresh bind-mounted configs without unnecessarily recreating the DB."""
    compose('up', '-d', '--wait', '--wait-timeout', '300', 'db')
    workers = ['chatgpt' + str(n) for n in range(1, config()['accounts'] + 1)]
    compose('up', '-d', '--no-deps', '--force-recreate', '--wait', '--wait-timeout', '300', *workers)
    compose('up', '-d', '--no-deps', '--force-recreate', '--wait', '--wait-timeout', '300', 'proxy')


def refresh_native(args):
    token = native_token(args.account)
    request = urllib.request.Request('https://api.anthropic.com/v1/models?limit=1000',
        headers={'Authorization': 'Bearer ' + token, 'anthropic-version': '2023-06-01',
                 'anthropic-beta': 'oauth-2025-04-20'})
    with urllib.request.urlopen(request, timeout=30) as response: result = json.load(response)
    if result.get('has_more'): raise ValueError('Native catalog pagination required; refusing an incomplete replacement')
    ids = [row['id'] for row in result['data']]
    if not ids or len(ids) != len(set(ids)) or not all(name.startswith('claude-') for name in ids):
        raise ValueError('Unexpected native catalog; configuration unchanged')
    cfg = config(); cfg['anthropic_model_ids'] = ids
    import re
    cfg['native_aliases'] = {re.sub(r'-\d{8}$', '', name): name for name in ids
                             if re.search(r'-\d{8}$', name)}
    write_private(state_dir() / 'config.json', cfg); render()
    print('Native catalog refreshed:', len(ids), 'models. Run up to reconcile routes/key. OAuth was not stored in Docker.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('init'); p.add_argument('--accounts', type=int, choices=(1, 2), default=2)
    p.add_argument('--port', type=int, default=4000); p.add_argument('--yolo', action='store_true')
    for name in ('render', 'up', 'down', 'check', 'sync-key', 'backup', 'status', 'prepare-client'):
        sub.add_parser(name)
    p = sub.add_parser('provider'); p.add_argument('name', choices=('deepseek', 'openrouter', 'exa'))
    p.add_argument('--disable', action='store_true')
    p = sub.add_parser('login-chatgpt'); p.add_argument('account', choices=('primary', 'backup'))
    p = sub.add_parser('login-claude'); p.add_argument('account', choices=('primary', 'backup'))
    p = sub.add_parser('login-codex'); p.add_argument('account', choices=('primary', 'backup'))
    p = sub.add_parser('codex'); p.add_argument('--account', choices=('primary', 'backup'), default='primary')
    p.add_argument('--yolo', action='store_true'); p.add_argument('args', nargs=argparse.REMAINDER)
    p = sub.add_parser('launch'); p.add_argument('--account', choices=('primary', 'backup'), default='primary')
    p.add_argument('--no-patch', action='store_true'); p.add_argument('--remote-control-patch', action='store_true')
    p.add_argument('--yolo', action='store_true'); p.add_argument('args', nargs=argparse.REMAINDER)
    p = sub.add_parser('install-launchers'); p.add_argument('--bin-dir', type=Path, default=Path.home() / '.local/bin')
    p = sub.add_parser('upgrade'); p.add_argument('--image', required=True)
    p = sub.add_parser('refresh-native'); p.add_argument('--account', choices=('primary', 'backup'), default='primary')
    p = sub.add_parser('smoke'); p.add_argument('--model', required=True)
    p.add_argument('--effort', choices=LEVELS); p.add_argument('--native-account', choices=('primary', 'backup'), default='primary')
    p.add_argument('--allow-spend', action='store_true')
    args = parser.parse_args()
    if args.command == 'init': init(args)
    elif args.command == 'render': render()
    elif args.command == 'up':
        render(); start_stack(); sync_key(); check()
    elif args.command == 'down': compose('down')  # Deliberately no --volumes deletion command.
    elif args.command == 'status': compose('ps')
    elif args.command == 'sync-key': sync_key()
    elif args.command == 'check': check()
    elif args.command == 'backup': backup()
    elif args.command == 'refresh-native': refresh_native(args)
    elif args.command == 'smoke':
        if not args.allow_spend: raise ValueError('smoke uses quota/money; explicitly pass --allow-spend')
        policy = key_policy(config())
        if args.model not in policy['models'] and args.model not in policy['aliases']:
            raise ValueError('Model not permitted by this installation')
        from smoke import probe
        native = args.model.startswith('claude/anthropic/') or args.model in policy['aliases']
        key = json.loads((state_dir() / 'gateway-key.json').read_text())['key']
        print(json.dumps(probe(config()['base_url'], args.model, key, args.effort,
                               native_token(args.native_account) if native else None)))
    elif args.command == 'prepare-client':
        subprocess.run([sys.executable, str(ROOT / 'patches/prepare.py'),
            '--source', shutil.which(os.getenv('CMA_CLAUDE_BIN', 'claude')) or 'claude',
            '--gateway', config()['base_url'], '--models-file', str(state_dir() / 'config.json'),
            '--cache', str(state_dir() / 'clients')], check=True)
    elif args.command == 'provider':
        name = {'deepseek': 'DEEPSEEK_API_KEY', 'openrouter': 'OPENROUTER_API_KEY', 'exa': 'EXA_API_KEY'}[args.name]
        values = env_secrets()
        if args.disable: values.pop(name, None)
        else:
            if not os.environ.get(name): raise ValueError('Supply ' + name + ' in the environment, never a CLI argument')
            values[name] = os.environ[name]
        write_env(values); render()
        print('Provider configuration updated; run up to recreate this stack and reconcile the key.')
    elif args.command == 'login-chatgpt':
        worker = 'chatgpt2' if args.account == 'backup' else 'chatgpt1'
        if worker == 'chatgpt2' and config()['accounts'] != 2: raise ValueError('No backup worker configured')
        print('User action required: open the printed URL and authorize this account. Do not log or share the device code.', flush=True)
        compose('run', '--rm', '--no-deps', '--entrypoint', 'python', worker, '-c',
            'import os; from litellm.llms.chatgpt.authenticator import Authenticator; '
            'Authenticator().get_access_token(); os.chmod("/app/chatgpt-auth/auth.json", 0o600)')
        cfg = config(); cfg['authorized_workers'] = list(dict.fromkeys([*cfg.get('authorized_workers', []), worker]))
        write_private(state_dir() / 'config.json', cfg); render()
        print('Account authorized; run up to activate its worker routes.')
    elif args.command == 'login-claude':
        env = clean_client_env()
        for name in ('ANTHROPIC_BASE_URL', 'ANTHROPIC_CUSTOM_HEADERS'): env.pop(name, None)
        if args.account == 'backup':
            directory = Path(os.getenv('CMA_CLAUDE_SECONDARY_DIR', state_dir() / 'claude-account-2')).absolute()
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            env['CLAUDE_SECURESTORAGE_CONFIG_DIR'] = str(directory)
        subprocess.run([os.getenv('CMA_CLAUDE_BIN', 'claude'), 'auth', 'login'], env=env, check=True)
    elif args.command in ('codex', 'login-codex'):
        env = codex_environment(args.account)
        command = [os.getenv('CMA_CODEX_BIN', 'codex'), '-c', 'model_provider="openai"',
                   '-c', 'forced_login_method="chatgpt"']
        if args.account == 'backup': command += ['-c', 'cli_auth_credentials_store="file"']
        if args.command == 'login-codex': command += ['login', '--device-auth']
        else:
            if args.yolo: command += ['--dangerously-bypass-approvals-and-sandbox']
            command += args.args[1:] if args.args[:1] == ['--'] else args.args
        os.execvpe(command[0], command, env)
    elif args.command == 'launch': launch(args)
    elif args.command == 'install-launchers':
        if '/plugins/cache/' in str(ROOT):
            raise ValueError('Clone a stable utility checkout first; plugin-cache paths change on upgrades. See README.md')
        args.bin_dir.mkdir(parents=True, exist_ok=True)
        entries = {'cma': '', 'cma-claude': 'launch', 'cma-claude2': 'launch --account backup',
                   'cma-codex': 'codex', 'cma-codex2': 'codex --account backup'}
        if any((args.bin_dir / name).exists() or (args.bin_dir / name).is_symlink() for name in entries):
            raise ValueError('A cma launcher already exists; refusing to overwrite it')
        for name, command in entries.items():
            target = args.bin_dir / name
            write_private(target, '#!/usr/bin/env bash\nset -Eeuo pipefail\nexec ' +
                shlex.quote(sys.executable) + ' ' + shlex.quote(str(ROOT / 'scripts/cma.py')) + ' ' +
                command + (' --' if command else '') + ' "$@"\n')
            target.chmod(0o700)
        print('Installed only cma-prefixed launchers in', args.bin_dir)
    elif args.command == 'upgrade':
        if not args.image.startswith(('docker.litellm.ai/berriai/litellm:', 'ghcr.io/berriai/litellm:')) or args.image.endswith(':latest'):
            raise ValueError('Supply a reviewed version tag, not latest or an arbitrary registry')
        subprocess.run([str(ROOT / 'scripts/test-gateway.sh'), args.image], check=True)
        backup()
        cfg = config(); old = cfg['image']; cfg['image'] = args.image
        write_private(state_dir() / 'config.pre-upgrade.json', config())
        write_private(state_dir() / 'config.json', cfg); render()
        try:
            compose('pull', 'proxy', *['chatgpt' + str(n) for n in range(1, cfg['accounts'] + 1)])
            start_stack(); sync_key(); check()
        except Exception:
            cfg['image'] = old; write_private(state_dir() / 'config.json', cfg); render()
            print('Upgrade failed. Config restored; database migrations may need the backup before rollback. See OPS.md.', file=sys.stderr)
            raise


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        if isinstance(error, urllib.error.URLError):
            message = 'Gateway unreachable; verify this stack is up (no credentials printed)'
        elif isinstance(error, subprocess.SubprocessError):
            message = 'External command failed; see its output (credentials are never printed by cma)'
        else:
            message = str(error)
        sys.exit('cma: ' + message)
