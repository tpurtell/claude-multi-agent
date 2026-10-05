#!/usr/bin/env bash
set -Eeuo pipefail
cma_script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec "$cma_script_dir/cma" check "$@"
