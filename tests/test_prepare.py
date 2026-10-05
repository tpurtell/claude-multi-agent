"""Offline checks: host/auth scope, Bun caches, upgrade rebuilds and corruption."""
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import prepare

SOURCE = (b'function rcGate(){if(!nativeProvider())return!1;'
          b'if(tunnel()!==void 0)return!0;if(env.ANTHROPIC_UNIX_SOCKET)return!1;'
          b'return officialHost()}function eligibility(){'
          b'if(!rcGate())return"not_first_party";return"still_check_oauth_and_org"}')
AGENT_SOURCE = (b'var schema={model:enumFactory(["sonnet","opus","haiku","fable"])'
                b'.optional().describe(`Optional model override for this agent. Original semantics.`)};')
AGENT_HANDLER = b'''import{effort}from"/effort.js";
async function launch({agentInput:n,toolUseContext:e,canUseTool:p,assistantMessage:g,onProgress:h}){
let s={effort:"high"},X=false,qe=n.model,pt="opus",Pe={};
let {effectiveIsolation:Ye,isRemoteLaunch:he,shouldRunAsync:K}=isolation();
let Qe=X?"inherit":qe,se=resolve(identity(s,pt),pt,Qe,Pe),xe=type(s);e.agentLifecycle.markTypeInvoked(s.agentType);
return {agentDefinition:s,model:se};}'''
EFFORT_SOURCE = b'''
function supports(e){if(disabled(e))return!1;let n=override(e,"effort");return n??e!=="haiku";}
function max(e){if(disabled(e))return!1;let n=override(e,"max_effort");return n??e==="opus";}
function xhigh(e){if(disabled(e))return!1;let n=override(e,"xhigh_effort");return n??e==="opus";}
function effort(e,n,{turnEffort:r,hookEffortValue:s,carriedEffort:d=carry(e)}={}){
if(!supports(e))return;return forced??(cap&&n==="max"?"high":n);}
'''


def fixture(source=SOURCE):
    """Small actual ELF/Bun layout with independent per-module caches."""
    blob = bytearray()
    records = []
    for name, content in ((b'/gate.js', source), (b'/untouched.js', b'other();'),
                          (b'/agent.js', AGENT_SOURCE + AGENT_HANDLER), (b'/effort.js', EFFORT_SOURCE)):
        fields = []
        for data in (name, content, b'sourcemap', b'bytecode', b'moduleInfo', b'origin'):
            fields.extend((len(blob), len(data)))
            blob += data + b'\0'
        records.append(struct.pack('<12I4B', *fields, 0, 1, 2, 0))
    table = len(blob)
    blob += b''.join(records) + struct.pack('<IIII', 1234, 5678, 9012, 3456)
    blob += struct.pack('<QIIIIII', len(blob), table, 208, 0, 0, 0, 48) + prepare.TRAILER
    section = struct.pack('<Q', len(blob)) + blob
    names = b'\0.bun\0.shstrtab\0'
    size = (len(section) + 4095) // 4096 * 4096
    end = 4096 + size
    binary = bytearray(4096)
    binary[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<QQ', binary, 32, 64, end + len(names))
    struct.pack_into('<5H', binary, 54, 56, 1, 64, 3, 2)
    struct.pack_into('<II6Q', binary, 64, 1, 6, 4096, 8192, 8192, size, size, 4096)
    binary += section + bytes(size - len(section)) + names
    binary += bytes(64)
    binary += struct.pack('<IIQQQQIIQQ', 1, 1, 3, 8192, 4096, len(section), 0, 0, 8, 0)
    binary += struct.pack('<IIQQQQIIQQ', 6, 3, 0, 0, end, len(names), 0, 0, 1, 0)
    return bytes(binary), table


class PatchTests(unittest.TestCase):
    def run_effort(self, checks, *, enabled=True, host=prepare.GATEWAY, preamble=''):
        source, _ = prepare.patch_effort_source(EFFORT_SOURCE)
        setup = '''const assert=require('node:assert/strict');
          const disabled=()=>false,override=()=>undefined,carry=()=>undefined;
          let forced,cap=false;
          process.env.CLAUDE_HYBRID_SUBAGENT_PATCH=ENABLED;
          process.env.ANTHROPIC_BASE_URL=HOST;
        '''.replace('ENABLED', json.dumps('1' if enabled else '0')).replace('HOST', json.dumps(host))
        subprocess.run(['node', '-e', setup + preamble + source.decode() + checks], check=True, capture_output=True)

    def test_wire_diagnostic_does_not_log_request_secrets_or_change_transport(self):
        self.run_effort('''
          const options={body:JSON.stringify({model:'claude-opus-5-5',output_config:{effort:'low'},thinking:{type:'adaptive'},messages:['PRIVATE_PROMPT']}),headers:{Authorization:'SECRET'}};
          assert.equal(fetch(process.env.ANTHROPIC_BASE_URL+'/v1/messages?beta=true',options),sentinel);
          assert.equal(sent[0][1],options);
          fetch('https://other/v1/messages',options);
          assert.equal(logs.length,1);
          assert.deepEqual(JSON.parse(logs[0].slice(logs[0].indexOf('{'))),{model:'claude-opus-5-5',effort:'low',thinking:'adaptive'});
          assert(!logs.join('').includes('SECRET'));assert(!logs.join('').includes('PRIVATE_PROMPT'));
        ''', preamble='''
          process.env.CLAUDE_HYBRID_EFFORT_TRACE='1';
          const sent=[],logs=[],sentinel={};globalThis.fetch=(...args)=>{sent.push(args);return sentinel};
          console.error=line=>logs.push(line);
        ''')

    def test_effort_matrix_and_definition_isolation(self):
        self.run_effort('''
          const original=Object.freeze({effort:'high',model:'inherit'});
          const apply=globalThis.__cmaHybridEffort.apply;
          const models=Object.keys(cmaEffortCatalog);
          for(const model of models){
            for(const value of [undefined,null,'default'])assert.equal(apply(original,value,model,false),original);
            for(const value of ['low','medium','high','xhigh','max']){
              if(cmaEffortCatalog[model].includes(value)){
                const result=apply(original,value,model,false);
                assert.notEqual(result,original);assert.equal(result.effort,value);
              }else assert.throws(()=>apply(original,value,model,false),/invalid/);
            }
          }
          const first=apply(original,'low',models[0],false),second=apply(original,'max',models[1],false);
          assert.equal(first.effort,'low');assert.equal(second.effort,'max');assert.equal(original.effort,'high');
          for(const invalid of ['none','minimal',128,true,{}])assert.throws(()=>apply(original,invalid,models[0],false),/invalid/);
        ''')

    def test_native_capabilities_policy_and_environment_preserved(self):
        self.run_effort(r'''
          const apply=globalThis.__cmaHybridEffort.apply;
          assert.equal(apply({},'max','opus',false).effort,'max');
          assert.equal(apply({},'medium','sonnet46',false).effort,'medium');
          assert.throws(()=>apply({},'xhigh','sonnet46',false),/invalid/);
          assert.throws(()=>apply({},'low','haiku',false),/invalid/);
          cap=true;assert.throws(()=>apply({},'max','opus',false),/overridden/);
          cap=false;forced='high';assert.throws(()=>apply({},'low','opus',false),/overridden/);
          forced=undefined;
          assert.throws(()=>apply({},'low','opus',true),/fork\/remote/);
          assert.throws(()=>globalThis.__cmaHybridEffort.checkKind({name:'teammate',effort:'high'}),/teammates/);
          globalThis.__cmaHybridEffort.checkKind({name:'teammate',effort:null});
        ''')

    def test_effort_opt_out_and_host_scope(self):
        for host, enabled in [('https://other', True), (prepare.GATEWAY, False)]:
            self.run_effort('''const original={};
              assert.equal(globalThis.__cmaHybridEffort.apply(original,'garbage','haiku',true),original);
              assert.equal(supports('haiku'),false);
              assert.equal(max('claude/chatgpt/gpt-6-astra'),false);
              globalThis.__cmaHybridEffort.checkKind({name:'x',effort:'max'});
            ''', host=host, enabled=enabled)

    def test_effort_launch_handoff_after_model_resolution(self):
        source, _ = prepare.patch_agent_launch_source(AGENT_HANDLER, '/effort.js')
        self.assertIn(b's=globalThis.__cmaHybridEffort.apply(s,n.effort,se,X||he);', source)
        # Both foreground and background paths consume this final definition.
        self.assertLess(source.index(b'.apply('), source.index(b'.agentLifecycle.'))
        self.assertGreater(source.index(b'.apply('), source.index(b'se=resolve('))
        for bad in (AGENT_HANDLER.replace(b'isRemoteLaunch', b'remote'),
                    AGENT_HANDLER.replace(b'.markTypeInvoked', b'.changed'),
                    AGENT_HANDLER + AGENT_HANDLER):
            with self.assertRaises(ValueError):
                prepare.patch_agent_launch_source(bad, '/effort.js')

    def test_unknown_effort_layout_fails_closed(self):
        for bad in (EFFORT_SOURCE.replace(b'"max_effort"', b'"new"'),
                    EFFORT_SOURCE.replace(b'carriedEffort:', b'changed:'),
                    EFFORT_SOURCE + EFFORT_SOURCE):
            with self.assertRaises(ValueError):
                prepare.patch_effort_source(bad)

    def test_agent_model_enum_has_exact_reviewed_routes_only_on_cma(self):
        edited, _ = prepare.patch_agent_source(AGENT_SOURCE)
        native = ['sonnet', 'opus', 'haiku', 'fable']
        plan = Path(__file__).resolve().parents[1] / 'profiles/models.json'
        extras = json.loads(plan.read_text())['other_models']
        self.assertEqual(set(prepare.SUBAGENT_MODELS), set(extras))
        metadata = json.loads(plan.read_text())['other_model_metadata']
        for model, declaration in metadata.items():
            self.assertEqual(list(prepare.MODEL_EFFORTS[model]), declaration['model_info']['reasoning_effort_levels'])
        extras = list(prepare.SUBAGENT_MODELS)
        script = '''const process={env:JSON.parse(require('node:process').argv[1])};
          const enumFactory=values=>({nullable(){return this},optional(){return this},describe(){return values}});
          SOURCE
          console.log(JSON.stringify(schema.model));'''.replace('SOURCE', edited.decode())
        for host, expected in ((prepare.GATEWAY, native + extras), ('https://other', native)):
            env = {'ANTHROPIC_BASE_URL': host, 'CLAUDE_HYBRID_SUBAGENT_PATCH': '1'}
            values = json.loads(subprocess.check_output(['node', '-e', script, json.dumps(env)]))
            self.assertEqual(values, expected)
        env = {'ANTHROPIC_BASE_URL': prepare.GATEWAY, 'CLAUDE_HYBRID_SUBAGENT_PATCH': '0'}
        self.assertEqual(json.loads(subprocess.check_output(['node', '-e', script, json.dumps(env)])), native)
        schema_script = script.replace('JSON.stringify(schema.model)', 'JSON.stringify(schema.effort??null)')
        self.assertIsNone(json.loads(subprocess.check_output(['node', '-e', schema_script, json.dumps(env)])))
        env['CLAUDE_HYBRID_SUBAGENT_PATCH'] = '1'
        self.assertEqual(json.loads(subprocess.check_output(['node', '-e', schema_script, json.dumps(env)])),
                         ['default', 'low', 'medium', 'high', 'xhigh', 'max'])
        for bad_source in (b'', AGENT_SOURCE + AGENT_SOURCE):
            with self.assertRaises(ValueError):
                prepare.patch_agent_source(bad_source)

    def test_runtime_gate_preserves_other_checks_and_limits_host(self):
        edited, _ = prepare.patch_source(SOURCE)
        cases = []
        for native in (False, True):
            for socket in (False, True):
                for enabled in ('0', '1'):
                    for host in (prepare.GATEWAY, prepare.GATEWAY + '.evil', 'https://elsewhere'):
                        cases.append([native, socket, enabled, host])
        script = '''const cases=JSON.parse(process.argv[1]);
          console.log(JSON.stringify(cases.map(([native,socket,enabled,host])=>{
            const env={ANTHROPIC_UNIX_SOCKET:socket};
            const process={env:{CLAUDE_HYBRID_REMOTE_CONTROL_PATCH:enabled,ANTHROPIC_BASE_URL:host}};
            const nativeProvider=()=>native, tunnel=()=>undefined, officialHost=()=>false;
            SOURCE
            return rcGate();
          })));'''.replace('SOURCE', edited.decode())
        result = json.loads(subprocess.check_output(['node', '-e', script, json.dumps(cases)]))
        self.assertEqual(result, [n and not s and e == '1' and h == prepare.GATEWAY
                                  for n, s, e, h in cases])
        self.assertTrue(edited.endswith(b'return"still_check_oauth_and_org"}'))

    def test_obfuscated_symbols_are_not_pinned(self):
        edited, gate = prepare.patch_source(SOURCE.replace(b'rcGate', b'$new123'))
        self.assertEqual(gate, '$new123')
        self.assertIn(prepare.GATEWAY.encode(), edited)

    def test_missing_ambiguous_or_unrelated_gate_rejected(self):
        for source in (b'new layout', SOURCE + SOURCE, SOURCE.replace(b'not_first_party', b'other')):
            with self.assertRaises(ValueError):
                prepare.patch_source(source)

    def test_only_target_module_source_and_caches_change(self):
        original, table = fixture()
        output, details = prepare.patch_binary(original)
        self.assertEqual(details['patches']['remote_control']['module'], '/gate.js')
        self.assertEqual(details['patches']['subagent_models']['module'], '/agent.js')
        base = 4104
        self.assertEqual(output[base:base + table], original[base:base + table])
        self.assertEqual(output[base + table + 16:base + table + 48], bytes(32))
        self.assertEqual(output[base + table + 52:base + table + 104],
                         original[base + table + 52:base + table + 104])
        self.assertEqual(struct.unpack_from('<IIII', output, base + table + 208), (0, 5678, 0, 0))
        self.assertEqual(output[base + table + 120:base + table + 152], bytes(32))
        pointer, length = struct.unpack_from('<II', output, base + table + 8)
        self.assertEqual(output[base + pointer:base + pointer + length], prepare.patch_source(SOURCE)[0])
        with self.assertRaises(ValueError):
            prepare.patch_binary(output)  # Never accidentally double-patch.

    def test_tail_growth_moves_file_metadata_not_mapped_code(self):
        original, _ = fixture(SOURCE + b' ' * 2300)
        output, _ = prepare.patch_binary(original)
        old_sh = struct.unpack_from('<Q', original, 40)[0]
        new_sh = struct.unpack_from('<Q', output, 40)[0]
        delta = new_sh - old_sh
        self.assertGreater(delta, 0)
        self.assertEqual(delta % 4096, 0)
        old_size = struct.unpack_from('<Q', original, 96)[0]
        self.assertEqual(struct.unpack_from('<QQ', output, 96), (old_size + delta, old_size + delta))
        old_strings = struct.unpack_from('<Q', original, old_sh + 128 + 24)[0]
        self.assertEqual(struct.unpack_from('<Q', output, new_sh + 128 + 24)[0], old_strings + delta)
        self.assertEqual(output[128:4096], original[128:4096])

    def test_unknown_binary_formats_and_overlaps_rejected(self):
        with self.assertRaises(ValueError):
            prepare.patch_binary(b'#!/usr/bin/node')
        original, _ = fixture()
        bad = bytearray(original)
        struct.pack_into('<Q', bad, 64 + 40, 8192)  # Runtime bss beyond mapped data
        with self.assertRaises(ValueError):
            prepare.patch_binary(bad)

    def test_cache_reused_upgrade_rebuilt_corruption_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
                prepare.subprocess, 'check_output', return_value='2.test (Claude Code)\n') as version:
            root = Path(tmp)
            source = root / 'installed'
            first, _ = fixture()
            source.write_bytes(first)
            cached = prepare.prepare(source, root / 'cache')
            self.assertEqual(source.read_bytes(), first)
            self.assertEqual(prepare.prepare(source, root / 'cache'), cached)
            self.assertEqual(version.call_count, 2)
            source.write_bytes(fixture(SOURCE.replace(b'rcGate', b'newGate'))[0])
            upgraded = prepare.prepare(source, root / 'cache')
            self.assertNotEqual(cached, upgraded)
            self.assertEqual(version.call_count, 4)
            upgraded.write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'modified'):
                prepare.prepare(source, root / 'cache')


if __name__ == '__main__':
    unittest.main()

