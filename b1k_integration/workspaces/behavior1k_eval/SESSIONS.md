# Runtime Sessions

```yaml
version: runtime_sessions_v1
sessions:
- session_id: sess_b1k_turning_on_radio_0_smoke
  target_ref: target://behavior1k_r1pro_sim
  skillruntime_ref: skillruntime://behavior1k_vla
  task_description: Turn on the radio
  status: failed
  priority: normal
  updated_at: '2026-06-14T10:23:38.830083Z'
  claimed_by: runtime-watchdog@server
  claim_token: 4df4ad0849c0430094a9abf498cc4784
  timeouts:
    queue_timeout_s: 30.0
    preflight_timeout_s: 20.0
    execute_timeout_s: 1800.0
    policy_timeout_s: 180.0
  retry:
    max_retries: 0
    attempted: 0
  depends_on: []
  routing:
    target_endpoint: targetws://127.0.0.1:9004
    policy_endpoint: dummy://local
    adapter_resolution: strict_auto
  execution:
    max_steps: 200
    replan_every: 1
    action_chunk_mode: open_loop
    chunk_switch_mode: hard_switch
  runtime_hints:
    perception_queries: []
    force_environment_refresh: false
  safety_profile:
    profile: default_simulation
    stop_on_policy_timeout: true
  benchmark:
    benchmark_id: behavior-1k
    suite_id: smoke3
    task_name: turning_on_radio
    task_index: 0
    instance_id: 0
    policy_id: dummy_baseline
  result:
    status: failed
    success: false
    error_code: ADAPTER
    error_message: BEHAVIOR-1K `head_rgb` image must be HWC RGB, got (224, 224, 4)
    metadata: {}
- session_id: sess_b1k_turning_on_radio_0_b1k_20260614t093844z
  goal_id: goal_b1k_turning_on_radio_0
  target_ref: target://behavior1k_r1pro_sim
  skillruntime_ref: skillruntime://behavior1k_vla
  task_description: turning on radio
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
    target_endpoint: targetws://127.0.0.1:9004
    policy_endpoint: dummy://local
    adapter_resolution: strict_auto
  execution:
    max_steps: 200
    replan_every: 1
    action_chunk_mode: open_loop
    chunk_switch_mode: hard_switch
    steps:
    - mode: benchmark
      benchmark_id: behavior-1k
      task_name: turning_on_radio
      instance_id: 0
  runtime_hints:
    perception_queries: []
    force_environment_refresh: false
  safety_profile:
    profile: default
    stop_on_policy_timeout: true
  benchmark:
    benchmark_id: behavior-1k
    suite_id: smoke3
    task_name: turning_on_radio
    task_index: 0
    instance_id: 0
    policy_id: dummy_baseline
    run_id: b1k_20260614T093844Z
  result:
    metadata: {}
- session_id: sess_b1k_picking_up_trash_0_b1k_20260615t151830z
  goal_id: goal_b1k_picking_up_trash_0
  target_ref: target://behavior1k_r1pro_sim
  skillruntime_ref: skillruntime://behavior1k_vla
  task_description: picking up trash
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
    target_endpoint: targetws://127.0.0.1:9004
    policy_endpoint: dummy://local
    adapter_resolution: strict_auto
  execution:
    max_steps: 200
    replan_every: 1
    action_chunk_mode: open_loop
    chunk_switch_mode: hard_switch
    steps:
    - mode: benchmark
      benchmark_id: behavior-1k
      task_name: picking_up_trash
      instance_id: 0
  runtime_hints:
    perception_queries: []
    force_environment_refresh: false
  safety_profile:
    profile: default
    stop_on_policy_timeout: true
  benchmark:
    benchmark_id: behavior-1k
    suite_id: mini2
    task_name: picking_up_trash
    task_index: 1
    instance_id: 0
    policy_id: dummy_baseline
    run_id: b1k_20260615T151830Z
  result:
    metadata: {}
- session_id: sess_b1k_clean_up_your_desk_0_b1k_20260615t151830z
  goal_id: goal_b1k_clean_up_your_desk_0
  target_ref: target://behavior1k_r1pro_sim
  skillruntime_ref: skillruntime://behavior1k_vla
  task_description: clean up your desk
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
    target_endpoint: targetws://127.0.0.1:9004
    policy_endpoint: dummy://local
    adapter_resolution: strict_auto
  execution:
    max_steps: 200
    replan_every: 1
    action_chunk_mode: open_loop
    chunk_switch_mode: hard_switch
    steps:
    - mode: benchmark
      benchmark_id: behavior-1k
      task_name: clean_up_your_desk
      instance_id: 0
  runtime_hints:
    perception_queries: []
    force_environment_refresh: false
  safety_profile:
    profile: default
    stop_on_policy_timeout: true
  benchmark:
    benchmark_id: behavior-1k
    suite_id: mini2
    task_name: clean_up_your_desk
    task_index: 29
    instance_id: 0
    policy_id: dummy_baseline
    run_id: b1k_20260615T151830Z
  result:
    metadata: {}
- session_id: sess_b1k_picking_up_trash_0_b1k_20260615t151836z
  goal_id: goal_b1k_picking_up_trash_0
  target_ref: target://behavior1k_r1pro_sim
  skillruntime_ref: skillruntime://behavior1k_vla
  task_description: picking up trash
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
    target_endpoint: targetws://127.0.0.1:9004
    policy_endpoint: dummy://local
    adapter_resolution: strict_auto
  execution:
    max_steps: 200
    replan_every: 1
    action_chunk_mode: open_loop
    chunk_switch_mode: hard_switch
    steps:
    - mode: benchmark
      benchmark_id: behavior-1k
      task_name: picking_up_trash
      instance_id: 0
  runtime_hints:
    perception_queries: []
    force_environment_refresh: false
  safety_profile:
    profile: default
    stop_on_policy_timeout: true
  benchmark:
    benchmark_id: behavior-1k
    suite_id: mini2
    task_name: picking_up_trash
    task_index: 1
    instance_id: 0
    policy_id: dummy_baseline
    run_id: b1k_20260615T151836Z
  result:
    metadata: {}
- session_id: sess_b1k_clean_up_your_desk_0_b1k_20260615t151836z
  goal_id: goal_b1k_clean_up_your_desk_0
  target_ref: target://behavior1k_r1pro_sim
  skillruntime_ref: skillruntime://behavior1k_vla
  task_description: clean up your desk
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
    target_endpoint: targetws://127.0.0.1:9004
    policy_endpoint: dummy://local
    adapter_resolution: strict_auto
  execution:
    max_steps: 200
    replan_every: 1
    action_chunk_mode: open_loop
    chunk_switch_mode: hard_switch
    steps:
    - mode: benchmark
      benchmark_id: behavior-1k
      task_name: clean_up_your_desk
      instance_id: 0
  runtime_hints:
    perception_queries: []
    force_environment_refresh: false
  safety_profile:
    profile: default
    stop_on_policy_timeout: true
  benchmark:
    benchmark_id: behavior-1k
    suite_id: mini2
    task_name: clean_up_your_desk
    task_index: 29
    instance_id: 0
    policy_id: dummy_baseline
    run_id: b1k_20260615T151836Z
  result:
    metadata: {}
```
