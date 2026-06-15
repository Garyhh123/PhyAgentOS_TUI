#!/usr/bin/env bash
# Start BEHAVIOR-1K TargetWS server (behavior conda + Isaac Sim + OmniGibson).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

BEHAVIOR_PYTHON="${BEHAVIOR_PYTHON:-/home/zyserver/miniconda3/envs/behavior/bin/python}"
# Force isaacsim3 — do NOT inherit a stale ISAAC_PATH=/home/zyserver/isaacsim from the shell.
export B1K_ISAAC_PATH="${B1K_ISAAC_PATH:-/home/zyserver/isaacsim3}"
export BEHAVIOR1K_ROOT="${BEHAVIOR1K_ROOT:-/home/zyserver/work/BEHAVIOR-1K}"
export DISPLAY="${DISPLAY:-:1}"
export OMNI_KIT_ACCEPT_EULA="${OMNI_KIT_ACCEPT_EULA:-YES}"

# Drop polluted PYTHONPATH (e.g. isaacsim pip_prebundle/scipy breaks behavior conda).
unset PYTHONPATH

PORT=9004
GUI=0
EXTRA=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --gui) GUI=1; shift ;;
    --port) PORT="$2"; shift 2 ;;
    *) EXTRA+=("$1"); shift ;;
  esac
done

ARGS=(--port "$PORT" --isaac-path "$B1K_ISAAC_PATH" --behavior1k-root "$BEHAVIOR1K_ROOT")
if [[ "$GUI" -eq 1 ]]; then
  ARGS+=(--gui)
else
  ARGS+=(--headless)
fi
ARGS+=("${EXTRA[@]}")

echo "[start_behavior1k_server] DISPLAY=$DISPLAY B1K_ISAAC_PATH=$B1K_ISAAC_PATH port=$PORT gui=$GUI"
echo "[start_behavior1k_server] PYTHONPATH cleared; server will rebuild OmniGibson + Isaac paths."
echo "[start_behavior1k_server] First boot may take several minutes — wait for Isaac window + TargetWS listening."

exec "$BEHAVIOR_PYTHON" PhyAgentOS/runtime/targets/remote/behavior1k/server.py "${ARGS[@]}"
