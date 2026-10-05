#!/usr/bin/env python3
"""Build an isolated Claude hybrid client; never modify the installation.

Supports Linux ELF64 little-endian Bun binaries with a tail .bun section and
52-byte module records. Unknown layouts fail closed. No third-party dependencies.
Format references: oven-sh/bun StandaloneModuleGraph and Piebald-AI/tweakcc's
nativeInstallation.ts (module cache invalidation and tail-section invariants).
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

GATEWAY = "http://127.0.0.1:4000"
TRAILER = b"\n---- Bun! ----\n"
IDENT = rb"[A-Za-z_$][\w$]*"
GATE = re.compile(
    rb"function (" + IDENT + rb")\(\)\{if\(!(" + IDENT + rb")\(\)\)return!1;"
    rb"if\((" + IDENT + rb")\(\)!==void 0\)return!0;"
    rb"if\((" + IDENT + rb")\.ANTHROPIC_UNIX_SOCKET\)return!1;return (" + IDENT + rb")\(\)\}"
)
AGENT_MODEL = re.compile(
    rb'model:(' + IDENT + rb')\((\["sonnet","opus","haiku","fable"\])\)'
    rb'(?=\.optional\(\)\.describe\(`Optional model override for this agent\.)'
)
# Intentionally explicit: these are the six reviewed ClaudeHybrid agent routes.
# Keep aligned with litellm/claude-hybrid.json when changing this key's models.
SUBAGENT_MODELS = (
    'claude/chatgpt/gpt-6.1-sol',
    'claude/chatgpt/gpt-6-astra',
    'claude/chatgpt/gpt-6.1-sol-backup',
    'claude/chatgpt/gpt-6-astra-backup',
    'claude/deepseek/deepseek-flash',
    'claude/xiaomi/mimo-v2.6-pro',
)
HYBRID_ENABLED = ('process.env.CLAUDE_HYBRID_SUBAGENT_PATCH==="1"&&'
                  'process.env.ANTHROPIC_BASE_URL===' + json.dumps(GATEWAY))
EFFORT_CAP = re.compile(
    rb'function (' + IDENT + rb')\((' + IDENT + rb')\)\{'
    rb'if\(!?'+ IDENT + rb'\(\2\)\)return!1;let '+ IDENT + rb'='
    + IDENT + rb'\(\2,"(effort|max_effort|xhigh_effort)"\);'
)
EFFORT_RESOLVER = re.compile(
    rb'function (' + IDENT + rb')\((' + IDENT + rb'),'+ IDENT +
    rb',\{turnEffort:'+ IDENT + rb',hookEffortValue:'+ IDENT +
    rb',carriedEffort:'+ IDENT + rb'='+ IDENT + rb'\(\2\)\}=\{\}\)\{'
)
EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max')
MODEL_EFFORTS = {model: (('low', 'high', 'max') if '/deepseek/' in model else
                       () if '/xiaomi/' in model else EFFORTS)
                 for model in SUBAGENT_MODELS}
EFFORT_DESCRIPTION = (
    'Per-launch reasoning effort. Omit, null or "default" preserves normal '
    'agent/session defaults (not a forced provider reset). Sol 6.1 and Astra, '
    'including backup: low/medium/high/xhigh/max. DeepSeek Flash: low/high/max '
    '(its medium and xhigh are aliases, not distinct levels). MiMo: default/null '
    'only; graded effort is not supported. Native Claude uses installed client '
    'capabilities: current Opus/Sonnet/Fable support all five; Haiku 4.5 default '
    'only. Invalid or policy/environment-overridden choices are rejected, not '
    'silently downgraded. Explicit effort is for foreground/background standalone '
    'agents, not forks, remote/cloud agents or named teammates.'
)


def configure(gateway, models):
    """Finite reviewed routes only, scoped to one explicit loopback origin."""
    global GATEWAY, SUBAGENT_MODELS, MODEL_EFFORTS, HYBRID_ENABLED
    parsed = urlsplit(gateway)
    require(parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost', '::1')
            and parsed.port is not None and not parsed.username and not parsed.password
            and parsed.path in ('', '/') and not parsed.query and not parsed.fragment,
            'Patches require an explicit loopback HTTP origin with a port')
    approved = json.loads((Path(__file__).resolve().parents[1] / 'profiles/models.json').read_text())['other_models']
    require(models and len(models) == len(set(models)) and set(models) <= set(approved),
            'Patch catalog must be a nonempty subset of the reviewed model roster')
    GATEWAY = gateway.rstrip('/')
    SUBAGENT_MODELS = tuple(models)
    MODEL_EFFORTS = {model: (('low', 'high', 'max') if '/deepseek/' in model else
                           () if '/xiaomi/' in model else EFFORTS) for model in models}
    HYBRID_ENABLED = ('process.env.CLAUDE_HYBRID_SUBAGENT_PATCH==="1"&&'
                      'process.env.ANTHROPIC_BASE_URL===' + json.dumps(GATEWAY))


def patch_effort_source(source):
    """Use native request/permission-layer plumbing, not a parallel effort state."""
    caps = list(EFFORT_CAP.finditer(source))
    require(len(caps) == 3 and {m[3].decode() for m in caps} ==
            {'effort', 'max_effort', 'xhigh_effort'}, 'Effort capability helpers changed')
    resolvers = list(EFFORT_RESOLVER.finditer(source))
    require(len(resolvers) == 1, 'Effort resolver changed')
    resolver = resolvers[0][1].decode()
    symbols = {m[3].decode(): m[1].decode() for m in caps}
    # Override only technical capabilities of our exact six routes. Native
    # Claude capabilities and the separate managed-policy effort caps survive.
    for match in reversed(caps):
        param, capability = match[2].decode(), match[3].decode()
        value = 'levels.length>0' if capability == 'effort' else (
            'levels.includes(' + json.dumps(capability.removesuffix('_effort')) + ')')
        pos = source.index(b'{', match.start()) + 1
        addition = ('{const levels=cmaEffortLevels(' + param + ');'
                    'if(levels!==undefined)return ' + value + ';}').encode()
        source = source[:pos] + addition + source[pos:]
    helper = r'''
function cmaEffortEnabled(){return ENABLED;}
const cmaEffortCatalog=CATALOG;
function cmaEffortLevels(model){
  return cmaEffortEnabled()&&Object.hasOwn(cmaEffortCatalog,model)?cmaEffortCatalog[model]:undefined;
}
function cmaExplicitEffort(value){return value!==undefined&&value!==null&&value!=="default";}
function cmaCheckAgentKind(input){
  if(cmaEffortEnabled()&&cmaExplicitEffort(input.effort)&&input.name)
    throw new Error("ClaudeHybrid: explicit effort is not supported for named teammates; omit it or use a standalone agent.");
}
function cmaApplyAgentEffort(definition,value,model,unsupported){
  if(!cmaEffortEnabled()||!cmaExplicitEffort(value))return definition;
  if(unsupported)throw new Error("ClaudeHybrid: explicit effort is not supported for fork/remote agents; omit it to inherit normally.");
  const levels=cmaEffortLevels(model)??(SUPPORTS(model)?[
    "low","medium","high",...(XHIGH(model)?["xhigh"]:[]),...(MAX(model)?["max"]:[])]:[]);
  if(!levels.includes(value))throw new Error("ClaudeHybrid: effort "+JSON.stringify(value)+" is invalid for "+model+". Supported: default/null"+(levels.length?", "+levels.join(", "):"")+".");
  const effective=RESOLVER(model,value,{carriedEffort:null});
  if(effective!==value)throw new Error("ClaudeHybrid: requested effort "+value+" for "+model+" would be overridden to "+String(effective)+" by client settings, policy or CLAUDE_CODE_EFFORT_LEVEL; remove the override or choose an allowed effort.");
  return {...definition,effort:value};
}
// Native Bun's prelinked import/export slots cannot safely be extended. The
// Agent module already imports this module, so publish a private runtime bridge
// without changing any existing export positions or cached importers.
Object.defineProperty(globalThis,"__cmaHybridEffort",{value:Object.freeze({
  checkKind:cmaCheckAgentKind,apply:cmaApplyAgentEffort
})});
// Optional wire diagnostic: only these three metadata fields, never headers,
// credentials, prompts, tools or response content. Off in normal operation.
if(cmaEffortEnabled()&&process.env.CLAUDE_HYBRID_EFFORT_TRACE==="1"){
  const originalFetch=globalThis.fetch;
  globalThis.fetch=function(resource,options){
    try{
      const url=new URL(typeof resource==="string"?resource:resource.url??String(resource));
      if(url.origin===process.env.ANTHROPIC_BASE_URL&&url.pathname==="/v1/messages"&&typeof options?.body==="string"){
        const body=JSON.parse(options.body);
        console.error("[ClaudeHybrid effort wire] "+JSON.stringify({model:body.model,effort:body.output_config?.effort??null,thinking:body.thinking?.type??null}));
      }
    }catch{}
    return Reflect.apply(originalFetch,this,arguments);
  };
}
'''
    for key, value in {'ENABLED': HYBRID_ENABLED,
                       'CATALOG': json.dumps(MODEL_EFFORTS, separators=(',', ':')),
                       'SUPPORTS': symbols['effort'], 'XHIGH': symbols['xhigh_effort'],
                       'MAX': symbols['max_effort'], 'RESOLVER': resolver}.items():
        helper = helper.replace(key, value)
    return source + helper.encode(), 'Agent.effort capabilities/validation'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def patch_source(source):
    matches = list(GATE.finditer(source))
    require(len(matches) == 1, f"Expected one Remote Control gate, found {len(matches)}")
    match = matches[0]
    # Bind the structural match to its Remote Control caller, not any unrelated
    # first-party check with a coincidentally similar implementation.
    caller = b'if(!' + match[1] + b'())return"not_first_party"'
    require(caller in source, "Remote Control gate caller changed")
    addition = (b'||(process.env.CLAUDE_HYBRID_REMOTE_CONTROL_PATCH==="1"&&'
                b'process.env.ANTHROPIC_BASE_URL===' + json.dumps(GATEWAY).encode() + b')')
    replacement = match[0][:-1] + addition + b'}'
    return source[:match.start()] + replacement + source[match.end():], match[1].decode()


def patch_agent_source(source):
    matches = list(AGENT_MODEL.finditer(source))
    require(len(matches) == 1, f"Expected one Agent model enum, found {len(matches)}")
    match = matches[0]
    # Feed the actual tool schema, not only prose or /model. Keep a finite enum;
    # model resolution and organization/gateway authorization are untouched.
    catalog = (b'...(process.env.CLAUDE_HYBRID_SUBAGENT_PATCH==="1"&&'
               b'process.env.ANTHROPIC_BASE_URL===' + json.dumps(GATEWAY).encode() +
               b'?' + json.dumps(SUBAGENT_MODELS, separators=(',', ':')).encode() + b':[])')
    effort = ('...(' + HYBRID_ENABLED + '?{effort:' + match[1].decode() + '(' +
              json.dumps(('default', *EFFORTS)) + ').nullable().optional().describe(' +
              json.dumps(EFFORT_DESCRIPTION) + ')}:{}),').encode()
    replacement = effort + b'model:' + match[1] + b'(' + match[2][:-1] + b',' + catalog + b'])'
    return source[:match.start()] + replacement + source[match.end():], 'Agent.model'


def patch_agent_launch_source(source, effort_module):
    handler = re.compile(rb'async function '+ IDENT + rb'\(\{agentInput:('+ IDENT +
                         rb'),toolUseContext:('+ IDENT + rb'),canUseTool:'+ IDENT +
                         rb',assistantMessage:'+ IDENT + rb',onProgress:'+ IDENT + rb'\}\)\{')
    starts = list(handler.finditer(source))
    require(len(starts) == 1, 'Agent launch handler changed')
    start = starts[0]
    # Bind to the final resolved model, AFTER hooks/policy/model overrides.
    final = re.compile(
        rb'let ('+ IDENT + rb')=('+ IDENT + rb')\?"inherit":'+ IDENT +
        rb',('+ IDENT + rb')='+ IDENT + rb'\('+ IDENT + rb'\(('+ IDENT + rb'),'+ IDENT +
        rb'\),'+ IDENT + rb',\1,'+ IDENT + rb'\),'+ IDENT + rb'='+ IDENT + rb'\(\4\);'
        + re.escape(start[2]) + rb'\.agentLifecycle\.markTypeInvoked\(\4\.agentType\);'
    )
    finals = list(final.finditer(source, start.end()))
    require(len(finals) == 1, 'Agent final model/definition handoff changed')
    end = finals[0]
    remote = re.findall(rb'\{effectiveIsolation:'+ IDENT + rb',isRemoteLaunch:('+ IDENT +
                        rb'),shouldRunAsync:'+ IDENT + rb'\}=', source[start.end():end.start()])
    require(remote and len(set(remote)) == 1, 'Agent remote launch guard changed')
    insertion = (end[4] + b'=globalThis.__cmaHybridEffort.apply(' + end[4] + b',' + start[1] +
                 b'.effort,' + end[3] + b',' + end[2] + b'||' + remote[0] + b');')
    pos = source.index(b';', end.start()) + 1
    source = source[:pos] + insertion + source[pos:]
    pos = start.end()
    source = source[:pos] + b'globalThis.__cmaHybridEffort.checkKind(' + start[1] + b');' + source[pos:]
    require(re.search(rb'import\{[^}]+\}from' + re.escape(json.dumps(effort_module).encode()), source),
            'Agent no longer imports the effort module')
    return source, 'Agent.effort launch override'


def patch_binary(original):
    """Append changed module sources; preserve all other source/caches."""
    require(original[:6] == b'\x7fELF\x02\x01', "Unsupported client: expected ELF64 little-endian")
    u16 = lambda off: struct.unpack_from('<H', original, off)[0]
    u64 = lambda off: struct.unpack_from('<Q', original, off)[0]
    phoff, shoff = u64(32), u64(40)
    require(u16(54) == 56 and u16(58) == 64, "Unsupported ELF header sizes")
    require(0 < u16(60) < 65535 and u16(62) < u16(60), "Unsupported ELF section numbering")
    sections = [struct.unpack_from('<IIQQQQIIQQ', original, shoff + i * 64)
                for i in range(u16(60))]
    string_section = sections[u16(62)]
    strings = original[string_section[4]:string_section[4] + string_section[5]]
    candidates = [(i, s) for i, s in enumerate(sections)
                  if strings[s[0]:].split(b'\0', 1)[0] == b'.bun']
    require(len(candidates) == 1, "Expected exactly one .bun section")
    section_index, section = candidates[0]
    _, section_type, _, address, offset, size, *_ = section
    require(section_type == 1 and offset + size <= len(original), "Invalid .bun section")
    require(u64(offset) + 8 == size, "Unsupported Bun section header")
    blob = bytearray(original[offset + 8:offset + size])
    require(blob.endswith(TRAILER), "Missing Bun trailer")
    footer = len(blob) - len(TRAILER) - 32
    count, table, table_len, entry, argv, argv_len, flags = struct.unpack_from('<QIIIIII', blob, footer)
    require(count == footer and table_len > 0 and table_len % 52 == 0, "Unsupported Bun module layout")
    require(table + table_len <= footer and entry < table_len // 52, "Invalid Bun module table")

    def slice_at(record, field):
        start, length = struct.unpack_from('<II', blob, record + field)
        require(start + length <= footer, "Bun pointer outside data")
        return bytes(blob[start:start + length])

    effort_modules = []
    for i in range(table_len // 52):
        record = table + i * 52
        if blob[record + 49] == 1 and EFFORT_RESOLVER.search(slice_at(record, 8)):
            effort_modules.append(slice_at(record, 0).decode())
    require(len(effort_modules) == 1, 'Expected one native effort module')
    targets = []
    patchers = {'remote_control': (GATE, patch_source), 'subagent_models': (AGENT_MODEL, patch_agent_source)}
    patchers['effort_capabilities'] = (EFFORT_RESOLVER, patch_effort_source)
    details = {}
    for i in range(table_len // 52):
        record = table + i * 52
        name = slice_at(record, 0)
        require(name and b'\0' not in name, "Invalid Bun module name")
        for field in (8, 16, 24, 32, 40):
            slice_at(record, field)
        if blob[record + 49] != 1:  # JavaScript loader, not binary assets
            continue
        source = slice_at(record, 8)
        patched = source
        for patch_name, (pattern, patcher) in patchers.items():
            if pattern.search(patched):
                require(patch_name not in details, f"Ambiguous patch modules: {patch_name}")
                require(blob[record + 48] in (0, 1), "Unsupported source encoding")
                patched, symbol = patcher(patched)
                details[patch_name] = {'module': name.decode(), 'symbol': symbol}
                if patch_name == 'subagent_models':
                    patched, _ = patch_agent_launch_source(patched, effort_modules[0])
        if patched != source:
            targets.append((i, record, patched))
    require(details.keys() == patchers.keys(), f"Missing patch targets: {patchers.keys() - details.keys()}")
    new_blob = blob[:footer] + b''.join(patched + b'\0' for _, _, patched in targets) + blob[footer:]
    new_footer = footer + sum(len(patched) + 1 for _, _, patched in targets)
    require(new_footer < 2**32, "Bun data exceeds u32 pointers")
    cursor = footer
    for module_index, record, patched in targets:
        struct.pack_into('<II', new_blob, record + 8, cursor, len(patched))
        cursor += len(patched) + 1
        # Drop ONLY the changed module's sourcemap, bytecode, moduleInfo and origin.
        # Leaving moduleInfo active can ignore edited source even without bytecode.
        new_blob[record + 16:record + 48] = bytes(32)
        new_blob[record + 48] = 0  # UTF-8, independent of Bun's UTF-16 enum versions
        if flags & (1 << 5):
            source_hash = table + table_len + module_index * 4
            require(source_hash + 4 <= footer, "Invalid Bun source hash table")
            struct.pack_into('<I', new_blob, source_hash, 0)
    struct.pack_into('<Q', new_blob, new_footer, new_footer)
    # Appended source is no longer contiguous with the compiler's source run.
    struct.pack_into('<I', new_blob, new_footer + 28, flags & ~(1 << 4))
    new_section = struct.pack('<Q', len(new_blob)) + new_blob

    programs = [struct.unpack_from('<IIQQQQQQ', original, phoff + i * 56)
                for i in range(u16(56))]
    loads = [(i, p) for i, p in enumerate(programs) if p[0] == 1]
    owners = [(i, p) for i, p in loads if p[2] <= offset and offset + size <= p[2] + p[5]]
    require(len(owners) == 1, "Expected one mapped Bun segment")
    program_index, owner = owners[0]
    _, perms, fileoff, vaddr, _, filesize, memsize, alignment = owner
    require(perms == 6 and filesize == memsize and alignment == 4096, "Unsupported Bun segment")
    align = lambda n: (n + alignment - 1) // alignment * alignment
    old_end = fileoff + filesize
    require(offset + align(size) == old_end and address - vaddr == offset - fileoff,
            "Bun is not the tail of its mapped segment")
    require(old_end <= shoff and phoff + len(programs) * 56 <= offset, "ELF tables overlap Bun data")
    require(all(i == program_index or (p[2] + p[5] <= offset and
                (p[0] != 1 or p[3] + p[6] <= address)) for i, p in enumerate(programs)),
            "Other ELF segments overlap Bun tail")
    for i, s in enumerate(sections):
        if s[1] != 8 and i != section_index:
            require(s[4] + s[5] <= offset or s[4] >= old_end, "Section overlaps Bun tail")
    delta = align(len(new_section)) - align(size)
    output = bytearray(original[:offset]) + new_section
    output += bytes(align(len(new_section)) - len(new_section))
    output += original[old_end:]
    struct.pack_into('<Q', output, 40, shoff + delta)
    struct.pack_into('<QQ', output, phoff + program_index * 56 + 32, filesize + delta, memsize + delta)
    for i, s in enumerate(sections):
        header = shoff + delta + i * 64
        if i == section_index:
            struct.pack_into('<Q', output, header + 32, len(new_section))
        elif s[1] != 8 and s[4] >= old_end:
            struct.pack_into('<Q', output, header + 24, s[4] + delta)
    return bytes(output), {'patches': details}


def prepare(source, cache):
    source = source.resolve(strict=True)
    original = source.read_bytes()
    source_hash = digest(original)
    patch_hash = digest(Path(__file__).read_bytes() + json.dumps(
        {'gateway': GATEWAY, 'models': SUBAGENT_MODELS, 'efforts': MODEL_EFFORTS},
        sort_keys=True).encode())
    identity = source_hash + '-' + patch_hash[:16]
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(cache.is_dir() and not cache.is_symlink() and cache.stat().st_uid == os.getuid(),
            "Cache must be a user-owned nonsymlink directory")
    cache.chmod(0o700)
    with (cache / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        destination = cache / identity
        executable = destination / 'claude'
        manifest_path = destination / 'manifest.json'
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            require(manifest['source_sha256'] == source_hash and manifest['patch_sha256'] == patch_hash,
                    "Cached client manifest mismatch")
            require(digest(executable.read_bytes()) == manifest['patched_sha256'],
                    f"Cached client modified: move {destination} aside and relaunch")
            return executable
        require(not destination.exists(), "Incomplete client cache; move it aside and relaunch")
        print('ClaudeHybrid: preparing isolated client (Remote Control + subagent models/effort)…', file=sys.stderr)
        output, details = patch_binary(original)
        with tempfile.TemporaryDirectory(prefix='.building-', dir=cache) as temp:
            build = Path(temp)
            candidate = build / 'claude'
            candidate.write_bytes(output)
            candidate.chmod(0o700)
            # --version uses no subscription quota and checks native loading.
            version = subprocess.check_output([source, '--version'], timeout=20, text=True).strip()
            patched_version = subprocess.check_output([candidate, '--version'], timeout=20, text=True).strip()
            require(version == patched_version, "Patched client version smoke test failed")
            require(digest(source.read_bytes()) == source_hash, "Claude updated during preparation; relaunch")
            manifest = dict(details, source=str(source), source_sha256=source_hash,
                            patch_sha256=patch_hash, patched_sha256=digest(output), version=version)
            (build / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
            # Publish both files together, while serializing concurrent launchers.
            build.rename(destination)
        print(f'ClaudeHybrid: cached {version}; original installation unchanged.', file=sys.stderr)
        return executable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default=shutil.which('claude'))
    parser.add_argument('--gateway', default=GATEWAY)
    parser.add_argument('--models-file', type=Path,
                        help='Private config JSON containing the enabled models list')
    parser.add_argument('--cache', type=Path, default=Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'claude-multi-agent' / 'clients')
    args = parser.parse_args()
    try:
        configure(args.gateway, json.loads(args.models_file.read_text())['models']
                  if args.models_file else SUBAGENT_MODELS)
        require(args.source, 'Claude executable not found on PATH')
        print(prepare(Path(args.source), args.cache))
    except (ValueError, OSError, KeyError, struct.error, subprocess.SubprocessError) as exc:
        sys.exit(f'ClaudeHybrid client preparation failed: {exc}\n'
                 'No installed client was changed. To launch without this workaround, set '
                 'CLAUDE_HYBRID_CLIENT_PATCH=0.')


if __name__ == '__main__':
    main()
