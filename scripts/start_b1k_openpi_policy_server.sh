#!/usr/bin/env bash
# Start BEHAVIOR-1K pi0 OpenPI policy server (PhyAgentOS wrapper, no OmniGibson in venv).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
B1K_BASELINES_ROOT="${B1K_BASELINES_ROOT:-/home/zyserver/work/b1k-baselines}"
OPENPI_DIR="${OPENPI_DIR:-${B1K_BASELINES_ROOT}/baselines/openpi}"
BEHAVIOR1K_ROOT="${BEHAVIOR1K_ROOT:-/home/zyserver/work/BEHAVIOR-1K}"
CHECKPOINT_DIR="${CHECKPOINT_DIR:-}"
TASK_NAME="${TASK_NAME:-turning_on_radio}"
PORT="${PORT:-8000}"
DEFAULT_PROMPT="${DEFAULT_PROMPT:-}"
MIN_GPU_FREE_MIB="${MIN_GPU_FREE_MIB:-12000}"
SERVE_SCRIPT="${REPO_ROOT}/PhyAgentOS/runtime/policy/openpi/serve_b1k_phyagentos.py"
VENV_PY="${OPENPI_DIR}/.venv/bin/python"

_preflight_port() {
  if command -v ss >/dev/null 2>&1; then
    if ss -tlnH "sport = :${PORT}" 2>/dev/null | grep -q .; then
      echo "[start_b1k_openpi_policy_server] ERROR: port ${PORT} is already in use." >&2
      echo "[start_b1k_openpi_policy_server] Stop the previous policy server (Ctrl+C in terminal B) or:" >&2
      echo "  fuser -k ${PORT}/tcp" >&2
      exit 1
    fi
  elif command -v fuser >/dev/null 2>&1; then
    if fuser "${PORT}/tcp" >/dev/null 2>&1; then
      echo "[start_b1k_openpi_policy_server] ERROR: port ${PORT} is already in use." >&2
      exit 1
    fi
  fi
}

_preflight_gpu() {
  if ! command -v nvidia-smi >/dev/null 2>&1; then
    return 0
  fi
  local free_mib
  free_mib="$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1 | tr -d ' ')"
  if [[ -z "${free_mib}" || ! "${free_mib}" =~ ^[0-9]+$ ]]; then
    return 0
  fi
  if (( free_mib < MIN_GPU_FREE_MIB )); then
    echo "[start_b1k_openpi_policy_server] ERROR: GPU free memory ${free_mib} MiB < ${MIN_GPU_FREE_MIB} MiB (pi0_b1k load needs ~12+ GiB free)." >&2
    echo "[start_b1k_openpi_policy_server] Common cause: a previous policy server crashed/OOM but its Python process still holds ~18 GiB on GPU." >&2
    echo "[start_b1k_openpi_policy_server] Inspect and kill stale processes:" >&2
    nvidia-smi --query-compute-apps=pid,process_name,used_gpu_memory --format=csv 2>/dev/null || nvidia-smi
    echo "[start_b1k_openpi_policy_server] Example: kill <pid>   # then re-run this script" >&2
    exit 1
  fi
}

if [[ -z "${CHECKPOINT_DIR}" ]]; then
  echo "[start_b1k_openpi_policy_server] ERROR: set CHECKPOINT_DIR." >&2
  exit 1
fi

if [[ ! -d "${OPENPI_DIR}" ]]; then
  echo "[start_b1k_openpi_policy_server] ERROR: openpi dir not found: ${OPENPI_DIR}" >&2
  exit 1
fi

if [[ ! -d "${CHECKPOINT_DIR}" ]]; then
  echo "[start_b1k_openpi_policy_server] ERROR: CHECKPOINT_DIR does not exist: ${CHECKPOINT_DIR}" >&2
  exit 1
fi

cd "${OPENPI_DIR}"

if [[ ! -x "${VENV_PY}" ]]; then
  echo "[start_b1k_openpi_policy_server] Creating openpi uv venv (first time)..." >&2
  GIT_LFS_SKIP_SMUDGE=1 uv sync
fi

_preflight_port
_preflight_gpu

export BEHAVIOR1K_ROOT
export PYTHONPATH="${REPO_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
# Avoid JAX grabbing all GPU memory up front; pi0_b1k still needs ~18 GiB once loaded.
export XLA_PYTHON_CLIENT_PREALLOCATE="${XLA_PYTHON_CLIENT_PREALLOCATE:-false}"
export XLA_PYTHON_CLIENT_MEM_FRACTION="${XLA_PYTHON_CLIENT_MEM_FRACTION:-0.90}"

ARGS=(
  "${SERVE_SCRIPT}"
  --task_name "${TASK_NAME}"
  --port "${PORT}"
  --behavior1k-root "${BEHAVIOR1K_ROOT}"
)
if [[ -n "${DEFAULT_PROMPT}" ]]; then
  ARGS+=(--default-prompt "${DEFAULT_PROMPT}")
fi
ARGS+=(policy:checkpoint --policy.config=pi0_b1k --policy.dir="${CHECKPOINT_DIR}")

echo "[start_b1k_openpi_policy_server] OPENPI_DIR=${OPENPI_DIR}"
echo "[start_b1k_openpi_policy_server] CHECKPOINT_DIR=${CHECKPOINT_DIR}"
echo "[start_b1k_openpi_policy_server] TASK_NAME=${TASK_NAME} PORT=${PORT}"
echo "[start_b1k_openpi_policy_server] Listening on b1k-ws://127.0.0.1:${PORT}"
echo "[start_b1k_openpi_policy_server] Note: policy server no longer requires OmniGibson in openpi venv."
if command -v nvidia-smi >/dev/null 2>&1; then
  echo "[start_b1k_openpi_policy_server] GPU free: $(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1 | tr -d ' ') MiB"
fi

# Use venv python directly — avoid ``uv run`` re-syncing deps (numba/coverage conflicts).
exec "${VENV_PY}" "${ARGS[@]}"
