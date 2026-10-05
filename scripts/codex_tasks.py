#!/usr/bin/env python3
"""Blocking, process-group-owned Codex jobs; run with Claude's background Bash."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

from cma import ROOT, codex_environment, state_dir, write_private


def start_ticks(pid):
    try:
        text = Path('/proc/' + str(pid) + '/stat').read_text()
        return text[text.rindex(')') + 2:].split()[19]
    except (OSError, ValueError, IndexError):
        return None


def paths(args):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', args.name):
        raise ValueError('Task name must be a safe filename, starting with a letter or digit')
    directory = Path(args.runs_dir or os.getenv('CMA_RUNS_DIR', state_dir() / 'runs')).absolute()
    if directory.is_symlink() or directory.resolve() in (Path('/'), Path.home().resolve(), ROOT):
        raise ValueError('Use a dedicated nonsymlink runs directory')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory, directory / (args.name + '.pid.json')


def matches(record):
    pid = record['pid']
    return (isinstance(pid, int) and pid > 1 and start_ticks(pid) == record['start_ticks']
            and os.getpgid(pid) == pid)


def group_members(group):
    result = []
    for directory in Path('/proc').iterdir():
        if not directory.name.isdigit():
            continue
        pid = int(directory.name)
        try:
            if os.getpgid(pid) == group:
                result.append(pid)
        except ProcessLookupError:
            pass
    return result


def run(args):
    directory, record_path = paths(args)
    brief = Path(args.brief or directory / (args.name + '.md')).resolve(strict=True)
    cwd = Path(args.cwd or Path.cwd()).resolve(strict=True)
    with (directory / (args.name + '.lock')).open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Task already running; resume or stop it before starting a duplicate') from None
        preamble = (ROOT / 'skills/codex-fallback/references/worker-preamble.md').read_text()
        prompt = preamble + '\n\nTask brief: ' + str(brief) + '\n\n' + brief.read_text()
        command = [os.getenv('CMA_CODEX_BIN', 'codex'), '-c', 'model_provider="openai"',
                   '-c', 'forced_login_method="chatgpt"']
        if args.account == 'backup': command += ['-c', 'cli_auth_credentials_store="file"']
        command += ['exec', '--json', '--cd', str(cwd)]
        if args.yolo:
            command += ['--dangerously-bypass-approvals-and-sandbox']
        else:
            command += ['--sandbox', 'workspace-write', '-c', 'approval_policy="never"']
        if args.model: command += ['--model', args.model]
        if args.effort != 'default': command += ['-c', 'model_reasoning_effort="' + args.effort + '"']
        command += ['--output-last-message', str(directory / (args.name + '.report.md')), '-']
        print('Starting', args.name, 'in', cwd, '(blocking; use background Bash to receive completion)', flush=True)
        log = directory / (args.name + '.log')
        with log.open('w') as output:
            log.chmod(0o600)
            process = subprocess.Popen(command, cwd=cwd, env=codex_environment(args.account),
                stdin=subprocess.PIPE, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            record = {'pid': process.pid, 'start_ticks': start_ticks(process.pid),
                      'task': args.name, 'cwd': str(cwd)}
            write_private(record_path, record)
            def terminate(signum, frame):
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
            previous = {sig: signal.signal(sig, terminate) for sig in (signal.SIGINT, signal.SIGTERM)}
            try:
                try:
                    process.communicate(prompt.encode())
                except BrokenPipeError:
                    process.wait()
                result = process.returncode
            finally:
                # The group was created by this runner; remove lingering task
                # children too, rather than orphaning a server after CLI exit.
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    deadline = time.monotonic() + 2
                    while group_members(process.pid) and time.monotonic() < deadline:
                        time.sleep(0.05)
                    if group_members(process.pid): os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                for sig, handler in previous.items(): signal.signal(sig, handler)
                if record_path.exists() and json.loads(record_path.read_text()) == record:
                    record_path.unlink()
            write_private(directory / (args.name + '.result.json'), {'task': args.name, 'exit_code': result,
                'report': str(directory / (args.name + '.report.md')), 'log': str(log)})
            print('Finished', args.name, 'exit', result, '| report:', directory / (args.name + '.report.md'))
            return result if result >= 0 else 128 - result


def stop(args):
    _, path = paths(args)
    if not path.exists(): raise ValueError('No running task record for ' + args.name)
    record = json.loads(path.read_text())
    if not matches(record):
        raise ValueError('Stale/reused PID record; refusing to signal unrelated processes')
    os.killpg(record['pid'], signal.SIGTERM)
    deadline = time.monotonic() + 3
    while group_members(record['pid']) and time.monotonic() < deadline:
        time.sleep(0.05)
    if group_members(record['pid']):
        os.killpg(record['pid'], signal.SIGKILL)
    print('Stopped task process group:', args.name)
    # The active runner owns record cleanup and retains its lock until done.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('run', 'stop'):
        p = sub.add_parser(name); p.add_argument('name'); p.add_argument('--runs-dir')
        if name == 'run':
            p.add_argument('--brief'); p.add_argument('--cwd'); p.add_argument('--model')
            p.add_argument('--account', choices=('primary', 'backup'), default='primary')
            p.add_argument('--effort', choices=('default', 'low', 'medium', 'high', 'xhigh', 'max'), default='high')
            p.add_argument('--yolo', action='store_true')
    args = parser.parse_args()
    try:
        sys.exit(run(args) if args.command == 'run' else stop(args))
    except (OSError, ValueError, KeyError) as error:
        sys.exit('codex-task: ' + str(error))


if __name__ == '__main__': main()
