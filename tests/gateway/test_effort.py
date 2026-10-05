"""Check the pinned gateway's real reasoning bridges without network or OAuth."""
import copy
import unittest
from unittest.mock import patch

import cma
import litellm
from litellm.llms.chatgpt.authenticator import Authenticator
from litellm.llms.chatgpt.responses.transformation import ChatGPTResponsesAPIConfig
from litellm.llms.anthropic.experimental_pass_through.adapters.handler import LiteLLMMessagesToCompletionTransformationHandler
from litellm.llms.anthropic.experimental_pass_through.adapters.transformation import LiteLLMAnthropicMessagesAdapter
from litellm.llms.anthropic.experimental_pass_through.responses_adapters.transformation import LiteLLMAnthropicToResponsesAPIAdapter
from litellm.llms.anthropic.experimental_pass_through.utils import normalize_reasoning_effort_value


class EffortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_cost = copy.deepcopy(litellm.model_cost)
        cls.auth = patch.object(Authenticator, 'get_access_token', return_value='offline-test')
        cls.auth.start()
        cls.routes = cma.worker_routes('offline-worker')
        cls.router = litellm.Router(model_list=cls.routes)

    @classmethod
    def tearDownClass(cls):
        cls.auth.stop()
        litellm.model_cost.clear()
        litellm.model_cost.update(cls.original_cost)

    def test_all_advertised_subscription_efforts_survive_real_bridges(self):
        adapter = LiteLLMAnthropicMessagesAdapter()
        for route in self.routes:
            provider, model = route['litellm_params']['model'].split('/', 1)
            for level in cma.LEVELS:
                with self.subTest(model=model, effort=level):
                    self.assertEqual(normalize_reasoning_effort_value(level, model, provider), level)
                    body = {'thinking': {'type': 'adaptive'}, 'output_config': {'effort': level}}
                    kwargs = {'model': model, 'custom_llm_provider': provider}
                    adapter._translate_thinking_to_openai(body, kwargs, custom_llm_provider=provider)
                    LiteLLMMessagesToCompletionTransformationHandler._normalize_reasoning_effort(kwargs)
                    effort = kwargs['reasoning_effort']
                    self.assertEqual(effort.get('effort') if isinstance(effort, dict) else effort, level)
                    reasoning = LiteLLMAnthropicToResponsesAPIAdapter.translate_thinking_to_reasoning(
                        body['thinking'], body['output_config'])
                    upstream = ChatGPTResponsesAPIConfig().transform_responses_api_request(
                        model, 'Reply OK', {'reasoning': reasoning}, {}, {})
                    self.assertEqual(upstream['reasoning']['effort'], level)

    def test_worker_configuration_does_not_force_effort(self):
        for route in self.routes:
            params = route['litellm_params']
            self.assertNotIn('reasoning_effort', params)
            self.assertNotIn('reasoning', params)
            self.assertEqual(route['model_info']['max_input_tokens'], 272000)
            self.assertTrue(route['model_info']['supports_vision'])


if __name__ == '__main__':
    unittest.main()
