import copy
import re
from types import SimpleNamespace
import unittest

from deepseek_compat import callback, normalize_schema


class DeepSeekSchemaTests(unittest.TestCase):
    def test_equivalent_no_nul_constraint(self):
        before = r'^[^\0]*$'
        after = normalize_schema({'type': 'string', 'pattern': before})['pattern']
        self.assertEqual(after, r'^[^\u0000]*$')
        for value in ('', 'hello', '/tmp/hello.png', '中文 😀', '\\0', 'a\x00b', '\x00'):
            self.assertEqual(bool(re.fullmatch(before, value)), bool(re.fullmatch(after, value)))

    def test_nested_artifact_schema_without_mutation(self):
        original = {'type': 'object', 'properties': {'file_paths': {'type': 'array',
            'items': {'type': 'string', 'minLength': 1, 'pattern': r'^[^\0]*$'}}},
            '$defs': {'path': {'type': 'string', 'pattern': r'^[^\0]*$'}},
            'allOf': [{'properties': {'path': {'pattern': r'^[^\0]*$'}}}]}
        snapshot = copy.deepcopy(original)
        fixed = normalize_schema(original)
        self.assertEqual(original, snapshot)
        self.assertEqual(fixed['properties']['file_paths']['items']['pattern'], r'^[^\u0000]*$')
        self.assertEqual(fixed['properties']['file_paths']['items']['minLength'], 1)
        self.assertEqual(fixed['$defs']['path']['pattern'], r'^[^\u0000]*$')
        self.assertEqual(fixed['allOf'][0]['properties']['path']['pattern'], r'^[^\u0000]*$')

    def test_other_regex_and_example_data_are_not_rewritten(self):
        schema = {'pattern': r'^\0foo$', 'examples': [{'pattern': r'^[^\0]*$'}],
                  'default': {'pattern': r'^[^\0]*$'}}
        self.assertEqual(normalize_schema(schema), schema)


class DeepSeekScopeTests(unittest.IsolatedAsyncioTestCase):
    def data(self, model):
        return {'model': model, 'system': 'Keep exactly',
                'messages': [{'role': 'user', 'content': 'Keep exactly'}],
                'tools': [{'name': 'Artifact', 'input_schema': {'type': 'object',
                          'properties': {'file_path': {'pattern': r'^[^\0]*$'}}}}]}

    async def test_native_and_other_providers_are_untouched(self):
        for model in ('claude-opus-5-5', 'claude/anthropic/claude-opus-5-5',
                      'claude/chatgpt/gpt-6.1-sol', 'claude/xiaomi/mimo-v2.6-pro',
                      'claude/local/deepseek-v41-flash'):
            data = self.data(model)
            self.assertIs(await callback.async_pre_call_hook(None, None, data, 'anthropic_messages'), data)

    async def test_flash_copy_preserves_original_messages_and_schema(self):
        data = self.data('claude/deepseek/deepseek-flash')
        original = copy.deepcopy(data)
        fixed = await callback.async_pre_call_hook(SimpleNamespace(), None, data, 'anthropic_messages')
        self.assertEqual(data, original)
        self.assertIs(fixed['messages'], data['messages'])
        self.assertEqual(fixed['system'], data['system'])
        self.assertEqual(fixed['tools'][0]['input_schema']['properties']['file_path']['pattern'], r'^[^\u0000]*$')


if __name__ == '__main__':
    unittest.main()

