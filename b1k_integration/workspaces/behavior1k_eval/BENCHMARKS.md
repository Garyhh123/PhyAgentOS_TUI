# Benchmark Registry — BEHAVIOR-1K

```yaml
version: benchmark_registry_v1
benchmarks:
  - id: behavior-1k
    title: BEHAVIOR-1K Challenge 2025
    enabled: true
    behavior1k_root: /home/zyserver/work/BEHAVIOR-1K
    eval_script: OmniGibson/omnigibson/learning/eval.py
    execution_backend: runtime_watchdog
    default_target_ref: target://behavior1k_r1pro_sim
    default_skillruntime_ref: skillruntime://behavior1k_vla
    default_adapter: behavior1k_openpi_adapter
    workspace: b1k_integration/workspaces/behavior1k_eval
    suites:
      - id: smoke3
        title: Smoke 3 tasks
        task_source: custom
        task_names:
          - turning_on_radio
          - wash_dog_toys
          - make_pizza
        default_instance_ids: [0]
      - id: challenge50
        title: Challenge 50 tasks
        task_source: challenge50
        default_instance_ids: [0]
      - id: mini2
        title: Mini 2 tasks
        task_source: custom
        task_names:
          - picking_up_trash
          - clean_up_your_desk
        default_instance_ids: [0]
    config:
      robot: R1Pro
      max_steps: 200
      target_endpoint: targetws://127.0.0.1:9004
      behavior1k_python: /home/zyserver/miniconda3/envs/behavior/bin/python
      isaac_env:
        isaac_path: /home/zyserver/isaacsim3
        display: ":1"
        env:
          ISAAC_PATH: /home/zyserver/isaacsim3
          CARB_APP_PATH: /home/zyserver/isaacsim3/kit
          EXP_PATH: /home/zyserver/isaacsim3/apps
```
