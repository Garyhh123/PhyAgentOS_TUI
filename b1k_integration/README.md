# BEHAVIOR-1K Integration

Standalone integration package for PhyAgentOS (sibling of the `PhyAgentOS/` framework package).

## Layout

```
b1k_integration/
├── benchmark/          # Task suites, registry, runner (Challenge50)
├── eval_compat/        # Hydra demo policy for legacy eval.py subprocess
├── openpi/             # pi0_b1k policy server (b1k-ws://)
├── scripts/            # Three-terminal launch + e2e scripts
└── workspaces/
    └── behavior1k_eval/
```

Framework code (TargetWS server, adapters, `b1k-ws://` client) stays in `PhyAgentOS/`.

## Quick start

From the **repository root**:

```bash
# Terminal A — simulation TargetWS
bash b1k_integration/scripts/start_behavior1k_server.sh --gui --port 9004

# Terminal B — pi0_b1k policy server
export CHECKPOINT_DIR=/path/to/pi0_b1k/checkpoint
bash b1k_integration/scripts/start_b1k_openpi_policy_server.sh

# Terminal C — one e2e session (paos conda)
conda activate paos
python b1k_integration/scripts/run_b1k_openpi_real_e2e.py \
  --workspace b1k_integration/workspaces/behavior1k_eval
```

See `b1k_integration/workspaces/behavior1k_eval/OPENPI_E2E.md` for full details.
