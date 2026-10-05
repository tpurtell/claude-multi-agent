"""Preserve Claude Artifact's no-NUL constraint in DeepSeek-compatible syntax.

DeepSeek's Anthropic endpoint rejects the JavaScript regex escape \\0 in tool
schemas. The equivalent Unicode escape \\u0000 is accepted. Rewrite only this
exact pattern on official Flash requests; native Anthropic is never modified.
"""
from litellm.integrations.custom_logger import CustomLogger

FLASH_MODELS = {'claude/deepseek/deepseek-flash', 'deepseek-v4-flash'}
SCHEMA_MAPS = {'properties', 'patternProperties', '$defs', 'definitions', 'dependentSchemas'}
SCHEMA_VALUES = {'items', 'additionalItems', 'additionalProperties', 'unevaluatedProperties',
                 'unevaluatedItems', 'contains', 'propertyNames', 'not', 'if', 'then', 'else'}
SCHEMA_LISTS = {'allOf', 'anyOf', 'oneOf', 'prefixItems'}


def normalize_schema(schema):
    if isinstance(schema, list):
        return [normalize_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    result = dict(schema)
    if schema.get('pattern') == r'^[^\0]*$':
        result['pattern'] = r'^[^\u0000]*$'
    for key, value in schema.items():
        if key in SCHEMA_MAPS and isinstance(value, dict):
            result[key] = {name: normalize_schema(child) for name, child in value.items()}
        elif key in SCHEMA_VALUES or key in SCHEMA_LISTS:
            result[key] = normalize_schema(value)
    return result


class DeepSeekToolSchemas(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        if data.get('model') not in FLASH_MODELS or not isinstance(data.get('tools'), list):
            return data
        # Copy just the tool schema; messages/system/history are unchanged.
        return {**data, 'tools': [
            {**tool, 'input_schema': normalize_schema(tool['input_schema'])}
            if isinstance(tool, dict) and 'input_schema' in tool else tool
            for tool in data['tools']]}


callback = DeepSeekToolSchemas()

