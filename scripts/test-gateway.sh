#!/usr/bin/env bash
# Offline checks against an explicit image; no credentials, network or live state.
set -Eeuo pipefail
cma_repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cma_test_image=${1:-docker.litellm.ai/berriai/litellm:1.104.0}
exec docker run --rm --network none \
  -e LITELLM_LOCAL_MODEL_COST_MAP=True -e LITELLM_MASTER_KEY=sk-offline-test \
  -e PYTHONPATH=/code/gateway:/code/scripts -e PYTHONWARNINGS=ignore::UserWarning \
  -v "$cma_repo_dir:/code:ro" --workdir /code --entrypoint python "$cma_test_image" \
  -m unittest discover -s tests/gateway -p 'test_*.py' -v
