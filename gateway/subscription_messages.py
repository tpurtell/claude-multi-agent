"""v1.104 Responses-to-Messages compatibility for the hybrid Codex models.

ChatGPT emits dictionary completion events and may omit tool output from the
final envelope after streaming it earlier. Upstream uses getattr on that dict,
losing usage/status, and reports end_turn even after a real tool_use block.
This scopes bridge fixes to Astra/Sol and system-role conversion to the ChatGPT
provider; native Anthropic is untouched.
"""
from types import SimpleNamespace

from litellm.integrations.custom_logger import CustomLogger
from litellm.llms.anthropic.experimental_pass_through.responses_adapters.streaming_iterator import AnthropicResponsesStreamWrapper
from litellm.llms.anthropic.experimental_pass_through.adapters.streaming_iterator import AnthropicStreamWrapper
from litellm.llms.chatgpt.responses.transformation import ChatGPTResponsesAPIConfig


def applies(model):
    return model.rsplit('/', 1)[-1] in ('gpt-6.1-sol', 'gpt-6-astra', 'gpt-6-astra-backup', 'gpt-6.1-sol-backup')


def install():
    cls = AnthropicResponsesStreamWrapper
    if getattr(cls, '_cma_subscription_messages_installed', False):
        return
    original = cls._process_event

    def process(self, event):
        if not applies(self.model):
            return original(self, event)
        if isinstance(event, dict) and event.get('type') in ('response.completed', 'response.incomplete', 'response.failed'):
            response = event.get('response')
            if isinstance(response, dict):
                event = {**event, 'response': SimpleNamespace(**response)}
        result = original(self, event)
        if self._pending_tool_ids:
            for chunk in self._chunk_queue:
                if chunk.get('type') == 'message_delta' and chunk.get('delta', {}).get('stop_reason') == 'end_turn':
                    chunk['delta']['stop_reason'] = 'tool_use'
        return result

    cls._process_event = process
    cls._cma_subscription_messages_installed = True

    # The ChatGPT adapter can take the Chat-Completions-compatible bridge
    # even though its backend is Responses. Normalize the public event at
    # this boundary too; keep all tool arguments/thinking/content unchanged.
    chat_cls = AnthropicStreamWrapper
    next_sync = chat_cls.__next__
    next_async = chat_cls.__anext__

    def normalize(wrapper, event):
        if not applies(wrapper.model) or not isinstance(event, dict):
            return event
        if event.get('type') == 'content_block_start' and event.get('content_block', {}).get('type') == 'tool_use':
            wrapper._cma_tool_seen = True
        if (event.get('type') == 'message_delta' and getattr(wrapper, '_cma_tool_seen', False)
                and event.get('delta', {}).get('stop_reason') == 'end_turn'):
            return {**event, 'delta': {**event['delta'], 'stop_reason': 'tool_use'}}
        return event

    def sync_next(self):
        return normalize(self, next_sync(self))

    async def async_next(self):
        return normalize(self, await next_async(self))

    chat_cls.__next__ = sync_next
    chat_cls.__anext__ = async_next

    # Codex subscription input accepts developer, but rejects system roles.
    # Apply only inside the ChatGPT provider, including the isolated worker.
    config = ChatGPTResponsesAPIConfig
    original_request = config.transform_responses_api_request

    def request(self, model, input, response_api_optional_request_params, litellm_params, headers):
        result = original_request(self, model, input, response_api_optional_request_params, litellm_params, headers)
        if applies(model) and isinstance(result.get('input'), list):
            result['input'] = [{**item, 'role': 'developer'}
                               if isinstance(item, dict) and item.get('role') == 'system' else item
                               for item in result['input']]
        return result

    config.transform_responses_api_request = request


install()
callback = CustomLogger()

