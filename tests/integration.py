#!/usr/bin/env python3
"""Opt-in isolated real Docker stack test. Fake upstreams; no live account calls."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import cma
from smoke import probe

REQUESTS = []


class Upstream(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        REQUESTS.append({'path': self.path, 'body': body, 'headers': dict(self.headers)})
        if '/messages' in self.path:
            finished = any(item.get('role') == 'user' and isinstance(item.get('content'), list)
                           and any(block.get('type') == 'tool_result' for block in item['content'])
                           for item in body.get('messages', []))
            block = {'type': 'text', 'text': 'OK'} if finished else {
                'type': 'tool_use', 'id': 'tool_fake', 'name': 'report', 'input': {'word': 'OK'}}
            events = [{'type': 'message_start', 'message': {'id': 'msg_fake', 'type': 'message',
                'role': 'assistant', 'model': body['model'], 'content': [], 'stop_reason': None,
                'stop_sequence': None, 'usage': {'input_tokens': 8, 'output_tokens': 0}}},
                {'type': 'content_block_start', 'index': 0, 'content_block': block},
                {'type': 'content_block_stop', 'index': 0}, {'type': 'message_delta',
                 'delta': {'stop_reason': 'end_turn' if finished else 'tool_use', 'stop_sequence': None},
                 'usage': {'output_tokens': 3}}, {'type': 'message_stop'}]
            self.sse(events); return
        if '/responses' in self.path:
            inputs = body.get('input', [])
            if isinstance(inputs, str): inputs = []
            finished = any(item.get('type') == 'function_call_output' for item in inputs)
            item = {'type': 'message', 'id': 'msg_fake', 'role': 'assistant', 'status': 'completed',
                'content': [{'type': 'output_text', 'text': 'OK', 'annotations': []}]} if finished else {
                'type': 'function_call', 'id': 'fc_fake', 'call_id': 'call_fake',
                'name': 'report', 'arguments': '{"word":"OK"}', 'status': 'completed'}
            response = {'id': 'resp_fake', 'object': 'response', 'created_at': int(time.time()),
                'model': body['model'], 'status': 'completed', 'output': [item],
                'usage': {'input_tokens': 8, 'output_tokens': 3, 'total_tokens': 11,
                          'input_tokens_details': {'cached_tokens': 0}, 'output_tokens_details': {'reasoning_tokens': 0}}}
            if not body.get('stream'): self.send_json(response); return
            start_item = dict(item)
            if finished: start_item['content'] = []
            else: start_item['arguments'] = ''
            events = [{'type': 'response.created', 'response': {**response, 'status': 'in_progress', 'output': []}},
                {'type': 'response.output_item.added', 'output_index': 0, 'item': start_item}]
            if finished:
                events += [{'type': 'response.content_part.added', 'output_index': 0, 'content_index': 0,
                            'item_id': 'msg_fake', 'part': {'type': 'output_text', 'text': '', 'annotations': []}},
                           {'type': 'response.output_text.delta', 'output_index': 0, 'content_index': 0,
                            'item_id': 'msg_fake', 'delta': 'OK'}]
            else:
                events += [{'type': 'response.function_call_arguments.delta', 'output_index': 0,
                    'item_id': 'fc_fake', 'delta': '{"word":"OK"}'},
                    {'type': 'response.function_call_arguments.done', 'output_index': 0,
                     'item_id': 'fc_fake', 'arguments': '{"word":"OK"}', 'name': 'report'}]
            events += [{'type': 'response.output_item.done', 'output_index': 0, 'item': item},
                       {'type': 'response.completed', 'response': response}]
            self.sse(events); return
        if '/chat/completions' in self.path:
            finished = any(item.get('role') == 'tool' for item in body['messages'])
            message = {'role': 'assistant', 'content': 'OK'} if finished else {
                'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'call_fake', 'type': 'function',
                'function': {'name': 'report', 'arguments': '{"word":"OK"}'}}]}
            if not body.get('stream'):
                self.send_json({'id': 'chatcmpl_fake', 'object': 'chat.completion', 'created': int(time.time()),
                    'model': body['model'], 'choices': [{'index': 0, 'message': message,
                    'finish_reason': 'stop' if finished else 'tool_calls'}],
                    'usage': {'prompt_tokens': 8, 'completion_tokens': 3, 'total_tokens': 11}}); return
            if not finished: message['tool_calls'][0]['index'] = 0
            events = [{'id': 'chatcmpl_fake', 'object': 'chat.completion.chunk', 'created': int(time.time()),
                'model': body['model'], 'choices': [{'index': 0, 'delta': message, 'finish_reason': None}]},
                {'id': 'chatcmpl_fake', 'object': 'chat.completion.chunk', 'created': int(time.time()),
                'model': body['model'], 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop' if finished else 'tool_calls'}]}]
            self.sse(events); return
        self.send_error(404)

    def sse(self, events):
        self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
        for event in events:
            self.wfile.write(('data: ' + json.dumps(event) + '\n\n').encode())
        self.wfile.flush(); self.close_connection = True

    def send_json(self, value):
        data = json.dumps(value).encode(); self.send_response(200)
        self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(data)))
        self.end_headers(); self.wfile.write(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-docker', action='store_true')
    args = parser.parse_args()
    if not args.allow_docker: parser.error('Pass --allow-docker to create an isolated test stack')
    server = ThreadingHTTPServer(('0.0.0.0', 0), Upstream)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1', 0)); port = reserve.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='cma-docker-test-') as temp:
        os.environ['CMA_HOME'] = str(Path(temp) / 'state')
        for key in ('DEEPSEEK_API_KEY', 'OPENROUTER_API_KEY', 'EXA_API_KEY'): os.environ.pop(key, None)
        cma.init(argparse.Namespace(port=port, accounts=2, yolo=False))
        home = cma.state_dir(); cfg = cma.config(); project = cfg['project']
        base = 'http://host.docker.internal:' + str(server.server_port)
        proxy = json.loads((home / 'proxy.yaml').read_text())
        for route in proxy['model_list']:
            if route['model_name'].startswith('claude/anthropic/'):
                route['litellm_params']['api_base'] = base
        cma.write_private(home / 'proxy.yaml', proxy)
        for worker in ('chatgpt1', 'chatgpt2'):
            worker_config = json.loads((home / (worker + '.yaml')).read_text())
            for route in worker_config['model_list']:
                route['litellm_params'].update(model='openai/' + route['model_name'],
                                               api_base=base + '/v1', api_key='fake-test-worker')
            cma.write_private(home / (worker + '.yaml'), worker_config)
        compose = json.loads((home / 'compose.json').read_text())
        for name, service in compose['services'].items():
            if name != 'db': service['extra_hosts'] = ['host.docker.internal:host-gateway']
        cma.write_private(home / 'compose.json', compose)
        try:
            cma.compose('up', '-d', '--wait', '--wait-timeout', '300')
            cma.sync_key(); cma.check()
            key = json.loads((home / 'gateway-key.json').read_text())['key']
            for model in cfg['models']:
                print(json.dumps(probe(cfg['base_url'], model, key, 'xhigh')))
            print(json.dumps(probe(cfg['base_url'], 'claude-sonnet-5-5', key,
                                   native_oauth='sk-ant-oat01-TEST-NOT-A-CREDENTIAL')))
            native = [r for r in REQUESTS if '/messages' in r['path']]
            assert len(native) == 2, 'Native calls did not reach the fake native API'
            assert all({k.lower(): v for k, v in r['headers'].items()}.get('authorization') ==
                       'Bearer sk-ant-oat01-TEST-NOT-A-CREDENTIAL' for r in native), \
                'Native OAuth header was not forwarded'
            codex = [r for r in REQUESTS if '/messages' not in r['path']]
            assert codex and all({k.lower(): v for k, v in r['headers'].items()}.get('authorization') ==
                                'Bearer fake-test-worker' for r in codex), \
                'Native OAuth leaked to non-Anthropic requests'
            assert all(r['body'].get('reasoning', {}).get('effort') == 'xhigh' or
                       r['body'].get('reasoning_effort') == 'xhigh' for r in codex), 'Effort downgraded'
            print('PASS: real isolated Docker stack, restricted catalog, four Codex tool loops, native OAuth scoping, xhigh forwarding.')
        finally:
            assert cma.config()['project'] == project and project.startswith('cma-')
            cma.compose('down', '--volumes', check=False)
            server.shutdown(); server.server_close()


if __name__ == '__main__': main()
