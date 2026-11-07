"""Offline checks for native inline-tool recovery and provider scoping."""
import json
import subprocess
import unittest

import prepare
from test_prepare import SOURCE, fixture


REFUSAL = b'''const beta="inline-tools-2026-09-15";
function refused(e){if(!(e instanceof ApiError))return;let n=e.message;if((e.status===400||e.status===422)&&/Input tag 'tool_definition'/.test(n))return"unsupported_on_platform";if(e.status!==400)return;if(n.includes("header rejected"))return"header_rejected";return}'''


class InlineToolTests(unittest.TestCase):
    def test_native_recovery_classification_preserves_other_error_handling(self):
        self.check_classification(REFUSAL)

    def test_319_shared_tag_classifier_keeps_beta_and_provider_scope(self):
        source = REFUSAL.replace(
            b"/Input tag 'tool_definition'/.test(n)", b'tag(beta,n)')
        source += b"""const tags=new Map([[beta,/^tool_definition$/]]);
function tag(beta,message){return tags.get(beta).test(message.match(/Input tag '([\\w.-]+)'/)?.[1]??"")}"""
        self.check_classification(source)
        with self.assertRaisesRegex(ValueError, 'beta binding changed'):
            prepare.patch_inline_tool_fallback_source(source.replace(
                b'[beta,/^tool_definition$/]', b'[other,/^tool_definition$/]'))

    def check_classification(self, source):
        patched, _ = prepare.patch_inline_tool_fallback_source(source)
        script = '''const assert=require('node:assert/strict');
          class ApiError extends Error {constructor(status,message){super(message);this.status=status}}
          SOURCE
          const deep="litellm.BadRequestError: DeepseekException - unknown variant `tool_definition`, expected `tool_reference`";
          for(const enabled of ['0','1'])for(const host of [HOST,'https://other']){
            process.env.CLAUDE_HYBRID_SUBAGENT_PATCH=enabled;process.env.ANTHROPIC_BASE_URL=host;
            for(const status of [400,422]){
              assert.equal(refused(new ApiError(status,deep)),enabled==='1'&&host===HOST?'kind_not_enabled':undefined);
              assert.equal(refused(new ApiError(status,"Input tag 'tool_definition'")),'unsupported_on_platform');
              assert.equal(refused(new ApiError(status,deep.replace('DeepseekException','AnthropicException'))),undefined);
              assert.equal(refused(new ApiError(status,deep.replace('tool_reference','text'))),undefined);
            }
            assert.equal(refused(new ApiError(429,deep)),undefined);
            assert.equal(refused(new ApiError(400,'header rejected')),'header_rejected');
            assert.equal(refused(new Error(deep)),undefined);
          }
        '''.replace('SOURCE', patched.decode()).replace('HOST', json.dumps(prepare.GATEWAY))
        subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True)

    def test_binary_target_and_native_classifier_drift(self):
        original, _ = fixture(source=SOURCE + REFUSAL)
        output, manifest = prepare.patch_binary(original)
        self.assertEqual(manifest['patches']['inline_tool_fallback']['module'], '/gate.js')
        self.assertIn(b'DeepseekException', output)
        for bad in (REFUSAL + REFUSAL, REFUSAL.replace(b'e.status===422', b'e.status===409')):
            with self.assertRaisesRegex(ValueError, 'Inline tool refusal classifier changed'):
                prepare.patch_inline_tool_fallback_source(bad)


if __name__ == '__main__':
    unittest.main()
