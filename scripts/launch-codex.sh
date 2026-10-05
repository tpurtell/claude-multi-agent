#!/usr/bin/env bash
set -Eeuo pipefail
cma_script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3 "$cma_script_dir/codex_tasks.py" run "$@"
