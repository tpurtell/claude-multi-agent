"""Streaming tool round-trip probe. Explicit opt-in; never print credentials."""
import json
from pathlib import Path
import urllib.request


def stream(base, body, headers):
    request = urllib.request.Request(base + '/v1/messages', headers={**headers,
        'Content-Type': 'application/json', 'anthropic-version': '2023-06-01'},
        data=json.dumps({**body, 'stream': True}).encode())
    blocks, reason = {}, None
    with urllib.request.urlopen(request, timeout=120) as response:
        for line in response:
            if not line.startswith(b'data:'): continue
            data = line[5:].strip()
            if data == b'[DONE]': break
            event = json.loads(data)
            if event.get('type') == 'error': raise ValueError('Provider returned a streaming error')
            if event.get('type') == 'content_block_start':
                blocks[event['index']] = dict(event['content_block'])
            elif event.get('type') == 'content_block_delta':
                delta = event['delta']; block = blocks[event['index']]
                if delta['type'] == 'input_json_delta':
                    block['_json'] = block.get('_json', '') + delta['partial_json']
                elif delta['type'] == 'text_delta': block['text'] = block.get('text', '') + delta['text']
            elif event.get('type') == 'message_delta': reason = event['delta'].get('stop_reason')
    for block in blocks.values():
        if '_json' in block: block['input'] = json.loads(block.pop('_json'))
    return list(blocks.values()), reason


def probe(base, model, key, effort=None, native_oauth=None):
    headers = {'x-litellm-api-key': 'Bearer ' + key}
    if native_oauth:
        headers.update(Authorization='Bearer ' + native_oauth,
                       **{'anthropic-beta': 'oauth-2025-04-20'})
    else: headers['Authorization'] = 'Bearer ' + key
    body = {'model': model, 'max_tokens': 256,
        'messages': [{'role': 'user', 'content': 'Call report with word OK, then acknowledge the tool result.'}],
        'tools': [{'name': 'report', 'description': 'Return a test word; no external side effects.',
            'input_schema': {'type': 'object', 'properties': {'word': {'type': 'string'}},
                             'required': ['word']}}], 'tool_choice': {'type': 'auto'}}
    if effort:
        body.update(thinking={'type': 'adaptive'}, output_config={'effort': effort})
    content, reason = stream(base, body, headers)
    tools = [item for item in content if item['type'] == 'tool_use']
    if not tools or reason != 'tool_use': raise ValueError('Tool call/stop envelope missing or incorrect')
    body['messages'] += [{'role': 'assistant', 'content': content}, {'role': 'user', 'content': [
        {'type': 'tool_result', 'tool_use_id': item['id'], 'content': 'OK'} for item in tools]}]
    final, reason = stream(base, body, headers)
    if reason != 'end_turn' or not any(item['type'] == 'text' and item.get('text') for item in final):
        raise ValueError('Final text/end-turn envelope missing')
    return {'model': model, 'tool_round_trip': True, 'effort': effort or 'default'}
