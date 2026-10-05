"""Hide redundant native Claude rows for ClaudeHybrid, without denying inference.

Claude Code already supplies the native Claude menu. This supported listing
hook leaves only this key's extra models in the gateway catalog, and does not
change other keys, authentication, aliases, or request routing.
"""
from litellm.integrations.custom_logger import CustomLogger


class HybridCatalog(CustomLogger):
    async def async_filter_listed_models(self, user_api_key_dict, model_names):
        if user_api_key_dict.key_alias != 'ClaudeHybrid':
            return model_names
        return tuple(name for name in model_names
                     if not name.startswith(('claude/anthropic/', 'claude-')))


callback = HybridCatalog()

