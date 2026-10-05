"""Offline coverage of dictionary events and missing final tool envelopes."""
import unittest
from litellm.types.utils import ModelResponseStream
from litellm.llms.anthropic.experimental_pass_through.adapters.streaming_iterator import AnthropicStreamWrapper

from litellm.llms.anthropic.experimental_pass_through.responses_adapters.streaming_iterator import AnthropicResponsesStreamWrapper
import subscription_messages
from litellm.llms.chatgpt.responses.transformation import ChatGPTResponsesAPIConfig


class SubscriptionMessagesTests(unittest.TestCase):
    def test_subscription_system_is_developer_without_mutating_input(self):
        original = [{'role': 'system', 'content': 'Claude Code system prompt'},
                    {'role': 'user', 'content': 'test'}]
        config = ChatGPTResponsesAPIConfig()
        result = config.transform_responses_api_request('gpt-6.1-sol', original, {}, {}, {})
        self.assertEqual(result['input'][0]['role'], 'developer')
        self.assertEqual(result['input'][0]['content'], original[0]['content'])
        self.assertEqual(original[0]['role'], 'system')

    def test_other_subscription_models_not_modified(self):
        result = ChatGPTResponsesAPIConfig().transform_responses_api_request(
            'other-model', [{'role': 'system', 'content': 'original'}], {}, {}, {})
        self.assertEqual(result['input'][0]['role'], 'system')

    def test_chat_compatibility_bridge_tool_stop(self):
        stream = iter([
            ModelResponseStream(model='gpt-6.1-sol', choices=[{'index': 0, 'delta': {
                'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'call_1', 'type': 'function',
                    'function': {'name': 'report', 'arguments': '{"word":"OK"}'}}]}, 'finish_reason': None}]),
            ModelResponseStream(model='gpt-6.1-sol', choices=[{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]),
        ])
        events = list(AnthropicStreamWrapper(stream, 'gpt-6.1-sol'))
        self.assertTrue(any(e.get('content_block', {}).get('type') == 'tool_use' for e in events))
        self.assertEqual(next(e for e in events if e['type'] == 'message_delta')['delta']['stop_reason'], 'tool_use')

    def completed(self, wrapper, output=None, status='completed'):
        wrapper._process_event({'type': 'response.completed', 'response': {
            'output': output or [], 'status': status,
            'usage': {'input_tokens': 7, 'output_tokens': 3, 'total_tokens': 10,
                      'input_tokens_details': {'cached_tokens': 0}},
        }})
        return next(c for c in wrapper._chunk_queue if c['type'] == 'message_delta')

    def tool(self, wrapper):
        wrapper._process_event({'type': 'response.output_item.added', 'item': {
            'type': 'function_call', 'id': 'fc_1', 'call_id': 'call_1', 'name': 'report'}})

    def test_tool_stop_when_final_envelope_omits_tool(self):
        wrapper = AnthropicResponsesStreamWrapper(None, 'gpt-6.1-sol')
        self.tool(wrapper)
        chunk = self.completed(wrapper)
        self.assertEqual(chunk['delta']['stop_reason'], 'tool_use')
        self.assertEqual(chunk['usage']['input_tokens'], 7)
        self.assertEqual(chunk['usage']['output_tokens'], 3)

    def test_backup_astra_model_is_supported(self):
        wrapper = AnthropicResponsesStreamWrapper(None, 'gpt-6-astra')
        self.tool(wrapper)
        self.assertEqual(self.completed(wrapper)['delta']['stop_reason'], 'tool_use')

    def test_plain_text_stays_end_turn(self):
        self.assertEqual(self.completed(AnthropicResponsesStreamWrapper(None, 'gpt-6.1-sol'))['delta']['stop_reason'], 'end_turn')

    def test_incomplete_tool_is_not_changed_to_tool_use(self):
        wrapper = AnthropicResponsesStreamWrapper(None, 'gpt-6.1-sol')
        self.tool(wrapper)
        self.assertEqual(self.completed(wrapper, status='incomplete')['delta']['stop_reason'], 'max_tokens')

    def test_other_models_unchanged(self):
        wrapper = AnthropicResponsesStreamWrapper(None, 'other-model')
        self.tool(wrapper)
        self.assertEqual(self.completed(wrapper)['delta']['stop_reason'], 'end_turn')


if __name__ == '__main__':
    unittest.main()

