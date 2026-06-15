#!/usr/bin/env bash
# Legacy helper — policy server no longer needs OmniGibson in the openpi venv.
echo "[setup_b1k_openpi_policy_deps] OmniGibson install is no longer required for the policy server."
echo "[setup_b1k_openpi_policy_deps] Ensuring openpi uv venv exists..."
set -euo pipefail

B1K_BASELINES_ROOT="${B1K_BASELINES_ROOT:-/home/zyserver/work/b1k-baselines}"
OPENPI_DIR="${OPENPI_DIR:-${B1K_BASELINES_ROOT}/baselines/openpi}"

cd "${OPENPI_DIR}"
if [[ ! -x ".venv/bin/python" ]]; then
  GIT_LFS_SKIP_SMUDGE=1 uv sync
fi
echo "[setup_b1k_openpi_policy_deps] Done. Run: CHECKPOINT_DIR=... bash scripts/start_b1k_openpi_policy_server.sh"
