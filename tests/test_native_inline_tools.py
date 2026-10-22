"""Opt-in native retry test with an injected unsupported-inline wire request.

Uses a fake API and stdio MCP server, dummy auth, and temporary config/cache.
The boundary injects the connector-style inline request because ordinary stdio
tools need not choose that native feature path. No real connector or provider
request is made. This tests native error recovery, schema retention and actual
MCP execution; it does not prove the interactive connector discovery path.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

SOURCE = None
LIVE_GATEWAY = None
LIVE_KEY = None
ROOT = Path(__file__).resolve().parent
PATCHER = ROOT / 'prepare.py' if (ROOT / 'prepare.py').exists() else ROOT.parent / 'patches/prepare.py'
MODEL = 'claude/deepseek/deepseek-flash'
TOOL = 'mcp__probe__echo'
TOOL_SCHEMA = {'type': 'object', 'properties': {'word': {'type': 'string'}}, 'required': ['word']}
ERROR = 'litellm.BadRequestError: DeepseekException - unknown variant `tool_definition`, expected `tool_reference`'
MCP_SERVER = '''import json,sys,pathlib,threading,time
signal=pathlib.Path(SIGNAL)
def changed():
 while not signal.exists():time.sleep(0.02)
 print(json.dumps({'jsonrpc':'2.0','method':'notifications/tools/list_changed'}),flush=True)
threading.Thread(target=changed,daemon=True).start()
for line in sys.stdin:
 request=json.loads(line);method=request.get('method')
 if 'id' not in request:continue
 if method=='initialize':result={'protocolVersion':'2024-11-05','capabilities':{'tools':{'listChanged':True}},'serverInfo':{'name':'probe','version':'1'}}
 elif method=='tools/list':result={'tools':[{'name':name,'description':'Return the supplied test word.','inputSchema':SCHEMA} for name in (['ping','echo'] if signal.exists() else ['ping'])]}
 elif method=='tools/call':result={'content':[{'type':'text','text':request['params']['arguments']['word']}]}
 else:result={}
 print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
'''.replace('SCHEMA', repr(TOOL_SCHEMA))


def blocks(value, kind):
    found = []
    if isinstance(value, dict):
        if value.get('type') == kind:
            found.append(value)
        for child in value.values():
            found.extend(blocks(child, kind))
    elif isinstance(value, list):
        for child in value:
            found.extend(blocks(child, kind))
    return found


class NativeInlineToolsTests(unittest.TestCase):
    def test_native_recovery_keeps_tool_definition_and_executes_it(self):
        if not SOURCE:
            self.skipTest('opt-in native executable test')
        spec = importlib.util.spec_from_file_location('inline_test_prepare', PATCHER)
        patcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(patcher)
        requests, errors = [], []
        rejected = False
        coordinator_round = 0

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self, *_):
                pass

            def send_json(self, body, status=200):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self.send_json({'data': []})

            def do_POST(self):
                nonlocal rejected, coordinator_round
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
                if self.path.split('?')[0].endswith('/count_tokens'):
                    return self.send_json({'input_tokens': 100})
                if not self.path.split('?')[0].endswith('/messages'):
                    return self.send_json({'error': 'unexpected path'}, 404)
                # Fault injection at the API boundary: reproduce the connector
                # request shape without a real connector login or vendor flags.
                if body['model'] == MODEL and not rejected:
                    definition = next((tool for tool in body.get('tools', []) if tool.get('name') == TOOL), None)
                    if definition is not None:
                        body['tools'] = [tool for tool in body['tools'] if tool.get('name') != TOOL]
                        body['messages'].append({'role': 'system', 'content': [{'type': 'tool_addition',
                            'tool': {'type': 'tool_definition', 'definition': definition}}]})
                requests.append({'body': body, 'beta': self.headers.get('anthropic-beta', '')})
                if len(requests) == 1:
                    (root / 'add-tool').touch()
                    time.sleep(0.3)
                errors.extend(block for block in blocks(body.get('messages', []), 'tool_result') if block.get('is_error'))
                inline = blocks(body.get('messages', []), 'tool_definition')
                if inline and body['model'] == MODEL:
                    rejected = True
                    if LIVE_GATEWAY:
                        return self.forward_live(body)
                    return self.send_json({'type': 'error', 'error': {'type': 'invalid_request_error', 'message': ERROR}}, 422)
                results = blocks(body.get('messages', []), 'tool_result')
                if LIVE_GATEWAY and body['model'] == MODEL:
                    return self.forward_live(body)
                if len(requests) > 8:
                    content = [{'type': 'text', 'text': 'MOCK_OK'}]
                elif body['model'] == 'claude-opus-5-5':
                    if coordinator_round == 0:
                        content = [{'type': 'tool_use', 'id': 'parent_search', 'name': 'ToolSearch', 'input': {'query': 'select:' + TOOL}}]
                    elif coordinator_round == 1:
                        content = [{'type': 'tool_use', 'id': 'parent_agent', 'name': 'Agent', 'input': {
                            'subagent_type': 'probe-agent', 'model': MODEL, 'description': 'Probe late MCP tool',
                            'prompt': 'Call the probe echo tool with MOCK_OK and reply MOCK_OK.', 'run_in_background': False}}]
                    else:
                        content = [{'type': 'text', 'text': 'MOCK_OK'}]
                    coordinator_round += 1
                elif rejected and any('MOCK_OK' in json.dumps(result.get('content')) for result in results):
                    content = [{'type': 'text', 'text': 'MOCK_OK'}]
                elif rejected:
                    content = [{'type': 'tool_use', 'id': 'call_echo', 'name': TOOL, 'input': {'word': 'MOCK_OK'}}]
                else:
                    content = [{'type': 'tool_use', 'id': 'call_search', 'name': 'ToolSearch', 'input': {'query': 'select:' + TOOL}}]
                stop = 'tool_use' if content[0]['type'] == 'tool_use' else 'end_turn'
                message = {'id': 'msg_probe', 'type': 'message', 'role': 'assistant', 'model': body['model'],
                           'content': [], 'stop_reason': None, 'stop_sequence': None,
                           'usage': {'input_tokens': 100, 'output_tokens': 10}}
                events = [('message_start', {'type': 'message_start', 'message': message})]
                for index, block in enumerate(content):
                    initial = dict(block, input={}) if block['type'] == 'tool_use' else dict(block, text='')
                    events.append(('content_block_start', {'type': 'content_block_start', 'index': index, 'content_block': initial}))
                    delta = ({'type': 'input_json_delta', 'partial_json': json.dumps(block['input'])} if block['type'] == 'tool_use'
                             else {'type': 'text_delta', 'text': block['text']})
                    events.append(('content_block_delta', {'type': 'content_block_delta', 'index': index, 'delta': delta}))
                    events.append(('content_block_stop', {'type': 'content_block_stop', 'index': index}))
                events += [('message_delta', {'type': 'message_delta', 'delta': {'stop_reason': stop}, 'usage': {'output_tokens': 10}}),
                           ('message_stop', {'type': 'message_stop'})]
                data = ''.join(f'event: {name}\ndata: {json.dumps(event)}\n\n' for name, event in events).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def forward_live(self, body):
                # Only the isolated child's synthetic task reaches the paid
                # provider. The coordinator and initial search remain fake.
                payload = {**body, 'max_tokens': 1024, 'output_config': {'effort': 'low'}}
                # DeepSeek thinking mode rejects a forced named-tool choice.
                # The synthetic agent instruction asks for the echo explicitly.
                payload['tool_choice'] = {'type': 'auto'}
                req = urllib.request.Request(LIVE_GATEWAY.rstrip('/') + '/v1/messages',
                    headers={'x-litellm-api-key': 'Bearer ' + LIVE_KEY, 'Content-Type': 'application/json',
                             'anthropic-beta': self.headers.get('anthropic-beta', '')}, data=json.dumps(payload).encode())
                try:
                    response = urllib.request.urlopen(req, timeout=90)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    data = response.read()
                    self.send_response(response.status)
                    self.send_header('Content-Type', response.headers.get('Content-Type', 'application/json'))
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)

        with tempfile.TemporaryDirectory(prefix='claude-inline-test-') as tmp:
            root = Path(tmp)
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            origin = f'http://127.0.0.1:{server.server_port}'
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                patcher.HYBRID_ENABLED = patcher.HYBRID_ENABLED.replace(json.dumps(patcher.GATEWAY), json.dumps(origin))
                patcher.GATEWAY = origin
                original_hash = patcher.digest(Path(SOURCE).resolve().read_bytes())
                executable = patcher.prepare(Path(SOURCE), root / 'cache')
                mcp = root / 'mcp.json'
                mcp_source = MCP_SERVER.replace('SIGNAL', repr(str(root / 'add-tool')))
                mcp.write_text(json.dumps({'mcpServers': {'probe': {'command': sys.executable, 'args': ['-u', '-c', mcp_source]}}}))
                env = {key: value for key, value in os.environ.items()
                       if not key.startswith(('ANTHROPIC_', 'CLAUDE_', 'CLAUDECODE'))}
                env.update(ANTHROPIC_BASE_URL=origin, ANTHROPIC_API_KEY='sk-offline-test-only',
                           ANTHROPIC_MODEL='claude-opus-5-5', CLAUDE_CONFIG_DIR=str(root / 'config'),
                           CLAUDE_HYBRID_SUBAGENT_PATCH='1', CLAUDE_HYBRID_REMOTE_CONTROL_PATCH='0',
                           CLAUDE_CODE_INLINE_TOOLS='1', CLAUDE_CODE_FORCE_MID_CONVERSATION_SYSTEM='1',
                           ENABLE_TOOL_SEARCH='true', CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1', DISABLE_AUTOUPDATER='1')
                result = subprocess.run([str(executable), '--print', '--output-format', 'json',
                    '--tools', 'ToolSearch,Agent', '--strict-mcp-config', '--mcp-config', str(mcp),
                    '--agents', json.dumps({'probe-agent': {'description': 'Probe an MCP echo tool',
                        'prompt': 'Use the probe echo tool.', 'tools': [TOOL]}}),
                    '--max-turns', '4', '--dangerously-skip-permissions', '--no-session-persistence',
                    '--debug-file', str(root / 'debug.log'), 'Discover the probe echo tool, call it with MOCK_OK, then reply MOCK_OK.'],
                    cwd=root, env=env, text=True, capture_output=True, timeout=75)
                summary = [{'inline': len(blocks(r['body'].get('messages', []), 'tool_definition')),
                            'model': r['body']['model'], 'tools': [t.get('name') for t in r['body'].get('tools', [])], 'beta': r['beta']} for r in requests]
                diagnostic = result.stderr[-2000:] + result.stdout[-2000:] + json.dumps(summary)
                diagnostic += '\n'.join(line for line in (root / 'debug.log').read_text().splitlines()
                                        if any(token in line.lower() for token in ('[inline-tools]', 'late tool', 'tool change')))[-3000:]
                self.assertTrue(rejected, diagnostic)
                self.assertEqual(result.returncode, 0, diagnostic)
                self.assertFalse(errors, errors)
                first_inline = next(i for i, r in enumerate(requests) if r['body']['model'] == MODEL and blocks(r['body'].get('messages', []), 'tool_definition'))
                retry = requests[first_inline + 1]
                self.assertNotIn('inline-tools-2026-09-15', retry['beta'])
                self.assertFalse(blocks(retry['body']['messages'], 'tool_definition'))
                self.assertIn('inline-tools-2026-09-15', requests[-1]['beta'],
                              'A DeepSeek failure must not disable inline tools on the native coordinator')
                definition = next(tool for tool in retry['body']['tools'] if tool.get('name') == TOOL)
                self.assertEqual(definition['input_schema'], TOOL_SCHEMA)
                self.assertIn('MOCK_OK', result.stdout)
                self.assertEqual(patcher.digest(Path(SOURCE).resolve().read_bytes()), original_hash)
                self.assertTrue(any('MOCK_OK' in json.dumps(item.get('content'))
                                    for request in requests if request['body']['model'] == MODEL
                                    for item in blocks(request['body']['messages'], 'tool_result')))
                print('Injected inline refusal: native 422 recovery -> declared schema -> MCP execution OK.')
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-client', action='store_true')
    parser.add_argument('--source', type=Path)
    parser.add_argument('--allow-spend', action='store_true', help='Forward only the synthetic DeepSeek child to a real gateway')
    parser.add_argument('--gateway-url')
    parser.add_argument('--key-file', type=Path)
    args = parser.parse_args()
    if args.allow_client:
        parser.error('--source is required') if not args.source else None
        SOURCE = args.source
    if args.allow_spend:
        if not args.allow_client or not args.gateway_url or not args.key_file:
            parser.error('--allow-spend needs --allow-client, --gateway-url and --key-file')
        LIVE_GATEWAY = args.gateway_url
        LIVE_KEY = json.loads(args.key_file.read_text())['key']
    unittest.main(argv=[sys.argv[0]], verbosity=2)
