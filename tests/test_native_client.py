"""Opt-in real native Claude Agent/effort wire test against a fake loopback API.

No real credentials, provider inference, installed-client edits or NAS changes.
Run: python3 test_native_client.py --allow-client --source /absolute/claude
"""
import argparse
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

SOURCE = None
FABLE_MODEL = 'claude-fable-5-2'
ROOT = Path(__file__).resolve().parent
PATCHER = ROOT / "prepare.py" if (ROOT / "prepare.py").exists() else ROOT.parent / "patches/prepare.py"


class NativeClientTests(unittest.TestCase):
    def test_real_agent_schema_and_effort_wire(self):
        if not SOURCE:
            self.skipTest("opt-in native executable test")
        spec = importlib.util.spec_from_file_location("native_test_prepare", PATCHER)
        patcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(patcher)
        requests = []
        failures = []
        # All four subscriptions, all five levels, DeepSeek aliases, MiMo default.
        cases = [(model, level) for model in patcher.SUBAGENT_MODELS
                 if "/xiaomi/" not in model for level in patcher.EFFORTS]
        cases.append(("claude/xiaomi/mimo-v2.6-pro", "default"))
        cases.extend((model, level) for model in patcher.SUBAGENT_MODELS
                     if "/xiaomi/" not in model for level in ("lower", "higher"))
        cases.append(('fable', 'high'))
        def wire_effort(model, level):
            if level == "default":
                return None
            if level in ("lower", "higher"):
                return ({"lower": "low", "higher": "high"}[level] if "/deepseek/" in model else
                        {"lower": "medium", "higher": "xhigh"}[level])
            return {"medium": "high", "xhigh": "max"}.get(level, level) if "/deepseek/" in model else level
        expected = Counter((FABLE_MODEL if model == 'fable' else model,
                            wire_effort(model, level)) for model, level in cases)
        schemas = []
        coordinator_rounds = []

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, *_):
                pass

            def json_response(self, data, status=200):
                body = json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self.json_response({"data": []})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                if self.path.split("?")[0].endswith("/count_tokens"):
                    return self.json_response({"input_tokens": 100})
                if not self.path.split("?")[0].endswith("/messages"):
                    return self.json_response({"error": "unexpected path"}, 404)
                model = body["model"]
                batch = []
                with lock:
                    first = model == "claude-opus-5-5" and not schemas
                    if model == "claude-opus-5-5":
                        number = len(coordinator_rounds)
                        coordinator_rounds.append(number)
                        batch = cases[number * 16:(number + 1) * 16]
                    if first:
                        agent = next(tool for tool in body.get("tools", []) if tool["name"] == "Agent")
                        schemas.append(agent["input_schema"])
                    elif model != "claude-opus-5-5":
                        requests.append((model, body.get("output_config", {}).get("effort")))
                    # Inspect only fake response tool errors, never any user content.
                    for message in body.get("messages", []):
                        content = message.get("content")
                        if isinstance(content, list):
                            failures.extend(block.get("content") for block in content
                                            if block.get("type") == "tool_result" and block.get("is_error"))
                blocks = ([{"type": "tool_use", "id": f"test_agent_{cases.index((target, effort))}", "name": "Agent",
                            "input": {"subagent_type": "general-purpose", "model": target,
                                      "effort": effort, "description": f"Wire probe {i}",
                                      "prompt": "Reply MOCK_OK; use no tools.", "run_in_background": False}}
                           for i, (target, effort) in enumerate(batch)] if batch else
                          [{"type": "text", "text": "MOCK_OK"}])
                stop = "tool_use" if batch else "end_turn"
                message = {"id": "msg_loopback_test", "type": "message", "role": "assistant",
                           "model": model, "content": blocks, "stop_reason": stop,
                           "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 10}}
                if not body.get("stream"):
                    return self.json_response(message)
                events = [("message_start", {"type": "message_start",
                           "message": dict(message, content=[], stop_reason=None)})]
                for index, block in enumerate(blocks):
                    initial = dict(block, input={}) if block["type"] == "tool_use" else dict(block, text="")
                    events.append(("content_block_start", {"type": "content_block_start",
                                                           "index": index, "content_block": initial}))
                    delta = ({"type": "input_json_delta", "partial_json": json.dumps(block["input"])}
                             if block["type"] == "tool_use" else {"type": "text_delta", "text": block["text"]})
                    events.append(("content_block_delta", {"type": "content_block_delta",
                                                           "index": index, "delta": delta}))
                    events.append(("content_block_stop", {"type": "content_block_stop", "index": index}))
                events.extend([("message_delta", {"type": "message_delta",
                              "delta": {"stop_reason": stop, "stop_sequence": None},
                              "usage": {"output_tokens": 10}}),
                              ("message_stop", {"type": "message_stop"})])
                raw = "".join(f"event: {event}\ndata: {json.dumps(payload)}\n\n"
                              for event, payload in events).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        lock = threading.Lock()
        with tempfile.TemporaryDirectory(prefix="claude-native-effort-test-") as temporary:
            root = Path(temporary)
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                origin = f"http://127.0.0.1:{server.server_port}"
                # Test-only origin: never modify production patch scope/config.
                patcher.GATEWAY = origin
                patcher.HYBRID_ENABLED = ('process.env.CLAUDE_HYBRID_SUBAGENT_PATCH==="1"&&'
                                          'process.env.ANTHROPIC_BASE_URL===' + json.dumps(origin))
                source = Path(SOURCE).resolve(strict=True)
                original_hash = patcher.digest(source.read_bytes())
                executable = patcher.prepare(source, root / "cache")
                env = {key: value for key, value in os.environ.items()
                       if not key.startswith(("ANTHROPIC_", "CLAUDE_", "CLAUDECODE"))
                       and key not in ("DISABLE_AUTOUPDATER",)}
                env.update(ANTHROPIC_BASE_URL=origin, ANTHROPIC_API_KEY="sk-offline-test-only",
                           ANTHROPIC_MODEL="claude-opus-5-5",
                           ANTHROPIC_DEFAULT_OPUS_MODEL="claude-opus-5-5",
                           CLAUDE_CONFIG_DIR=str(root / "config"),
                           CLAUDE_HYBRID_SUBAGENT_PATCH="1",
                           CLAUDE_HYBRID_REMOTE_CONTROL_PATCH="0",
                           CLAUDE_CODE_SNAPPY_PELICAN="1",
                           CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
                           DISABLE_AUTOUPDATER="1")
                result = subprocess.run([str(executable), "--print", "--output-format", "json",
                                         "--tools", "Agent", "--max-turns", "4", "--effort", "high",
                                         "--dangerously-skip-permissions",
                                         "--no-session-persistence",
                                         "Run the requested fake Agent wire probes."],
                                        cwd=root, env=env, text=True, capture_output=True, timeout=90)
                self.assertEqual(patcher.digest(source.read_bytes()), original_hash)
                self.assertEqual(result.returncode, 0, result.stderr[-3000:] + result.stdout[-3000:])
                self.assertTrue(schemas, result.stdout[-3000:])
                properties = schemas[0]["properties"]
                self.assertTrue(set(patcher.SUBAGENT_MODELS) <= set(properties["model"]["enum"]))
                effort = properties["effort"]
                effort_values = effort.get("enum", [])
                if "anyOf" in effort:
                    effort_values = next(item["enum"] for item in effort["anyOf"] if "enum" in item)
                self.assertTrue(set((*patcher.EFFORTS, "default", "lower", "higher")) <= set(effort_values), effort)
                self.assertFalse(failures, failures)
                # Native defaults may supply inherited effort to MiMo internally;
                # capability suppression must prevent graded effort on its wire.
                self.assertEqual(Counter(requests), expected)
                print(f"Real native client: {len(cases)} Agent launches, schema and wire efforts verified.")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-client", action="store_true", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument('--expected-fable-model', default=FABLE_MODEL,
                        help='Expected native fable alias on the wire (override for older clients)')
    options = parser.parse_args()
    SOURCE = options.source
    FABLE_MODEL = options.expected_fable_model
    unittest.main(argv=[__file__, "-v"])
