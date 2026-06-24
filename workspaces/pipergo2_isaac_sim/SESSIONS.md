# Runtime Sessions

```yaml
version: runtime_sessions_v1
sessions:
- session_id: sess_piper_language_nav
  goal_id: goal_piper_language_nav
  target_ref: target://pipergo2_isaac_remote
  skillruntime_ref: skillruntime://pipergo2_command_sim
  task_description: nav
  status: succeeded
  priority: high
  updated_at: '2026-06-14T09:25:34.044832Z'
  claimed_by: runtime-watchdog@server
  claim_token: e43f236fbb4e46068811e216c8be2de2
  timeouts:
    queue_timeout_s: 60.0
    preflight_timeout_s: 30.0
    execute_timeout_s: 900.0
    policy_timeout_s: 10.0
  retry:
    max_retries: 0
    attempted: 0
  depends_on: []
  routing:
    target_endpoint: targetws://127.0.0.1:9003
    policy_endpoint: dummy://local
    adapter_resolution: strict_auto
  execution:
    max_steps: 4
    replan_every: 1
    action_chunk_mode: open_loop
    chunk_switch_mode: hard_switch
    steps:
    - text: go to desk
  runtime_hints:
    perception_queries: []
    force_environment_refresh: false
  safety_profile:
    profile: default_simulation
    stop_on_policy_timeout: true
  result:
    status: succeeded
    success: true
    num_steps: 0
    artifact_dir: artifacts/runtime/sess_piper_language_nav
    metadata:
      message: 'navigate ok: dist=0.0651 settled=60'
      return_value: 1.0
      num_steps: 1
      final_status: {}
      artifacts: {}
- session_id: sess_piper_language_describe
  goal_id: goal_piper_language_describe
  target_ref: target://pipergo2_isaac_remote
  skillruntime_ref: skillruntime://pipergo2_command_sim
  task_description: describe scene
  status: pending
  priority: normal
  timeouts:
    queue_timeout_s: 30.0
    preflight_timeout_s: 20.0
    execute_timeout_s: 600.0
    policy_timeout_s: 5.0
  retry:
    max_retries: 0
    attempted: 0
  depends_on: []
  routing:
    target_endpoint: targetws://127.0.0.1:9003
    policy_endpoint: dummy://local
    adapter_resolution: strict_auto
  execution:
    max_steps: 4
    replan_every: 8
    action_chunk_mode: chunk_buffer
    chunk_switch_mode: hard_switch
    steps:
    - command: describe_visible_scene
      params: {}
    - text: describe what you see in the scene
  runtime_hints:
    perception_queries: []
    force_environment_refresh: false
  safety_profile:
    profile: default_simulation
    stop_on_policy_timeout: true
  result:
    metadata: {}
- session_id: sess_piper_action_arm
  goal_id: goal_piper_action_arm
  target_ref: target://pipergo2_isaac_remote
  skillruntime_ref: skillruntime://pipergo2_command_sim
  task_description: arm motion smoke
  status: pending
  priority: normal
  timeouts:
    queue_timeout_s: 30.0
    preflight_timeout_s: 20.0
    execute_timeout_s: 300.0
    policy_timeout_s: 5.0
  retry:
    max_retries: 0
    attempted: 0
  depends_on: []
  routing:
    target_endpoint: targetws://127.0.0.1:9003
    policy_endpoint: dummy://local
    adapter_resolution: strict_auto
  execution:
    max_steps: 8
    replan_every: 8
    action_chunk_mode: chunk_buffer
    chunk_switch_mode: hard_switch
    steps:
    - mode: control
      action:
        arm_joint_controller:
        - - 0.0
          - 0.5
          - -0.5
          - 0.0
          - 0.5
          - 0.0
          - 0.0
          - 0.5
      sim_steps: 30
  runtime_hints:
    perception_queries: []
    force_environment_refresh: false
  safety_profile:
    profile: default_simulation
    stop_on_policy_timeout: true
  result:
    metadata: {}
```
