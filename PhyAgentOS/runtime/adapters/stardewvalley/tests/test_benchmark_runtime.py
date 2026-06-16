import pytest

from PhyAgentOS.runtime.adapters.stardewvalley.bridge.action_parser import ActionParseError
from PhyAgentOS.runtime.adapters.stardewvalley.bridge.benchmark_runtime import (
    BenchmarkError,
    BenchmarkRuntime,
)


class FakeTask:
    llm_description = "Collect two stones"
    object = "Stone"
    quantity = 2
    tool = "Pickaxe"
    evaluator = "harvest"
    difficulty = "easy"

    def __init__(self):
        self.init_calls = []
        self.current_quantity = 0

    def init_task(self, proxy):
        self.init_calls.append(proxy.port)

    def evaluate(self, obs, proxy):
        self.current_quantity = obs.get("quantity", 0)
        return {
            "completed": self.current_quantity >= self.quantity,
            "quantity": self.current_quantity,
            "proxy_port": proxy.port,
        }


class FakeProxy:
    def __init__(self, port):
        self.port = port


class FakeRuntime:
    stardojo_port = 10783

    def __init__(self):
        self.started = []
        self.actions = []
        self.quantity = 0

    def start_benchmark_task(self, task, proxy):
        task.init_task(proxy)
        self.started.append((task, proxy))
        return {"quantity": self.quantity, "location": "Farm"}

    def execute_raw(self, action):
        if action == "bad()":
            raise ActionParseError("Skill not allowed: bad")
        self.actions.append(action)
        self.quantity += 1
        return {"quantity": self.quantity, "position": [self.quantity, 0]}

    def format_observation(self, raw_obs):
        return {"quantity": raw_obs.get("quantity"), "position": raw_obs.get("position")}


def make_runtime():
    task = FakeTask()
    runtime = FakeRuntime()
    benchmark = BenchmarkRuntime(
        runtime,
        task_loader=lambda task_name, task_id: task,
        proxy_factory=FakeProxy,
    )
    return runtime, task, benchmark


def test_benchmark_start_initializes_task_and_returns_status():
    runtime, task, benchmark = make_runtime()

    result = benchmark.start("farming_lite", 0)

    assert task.init_calls == [10783]
    assert result["obs"] == {"quantity": 0, "position": None}
    assert result["benchmark"]["active"] is True
    assert result["benchmark"]["task_name"] == "farming_lite"
    assert result["benchmark"]["description"] == "Collect two stones"
    assert result["benchmark"]["max_steps"] == 30
    assert result["benchmark"]["completed"] is False
    assert result["benchmark"]["eval"]["quantity"] == 0


def test_benchmark_execute_evaluates_until_completed():
    runtime, task, benchmark = make_runtime()
    benchmark.start("farming_lite", 0)

    first = benchmark.execute("move(1, 0)")
    second = benchmark.execute("use(\"down\")")

    assert runtime.actions == ["move(1, 0)", "use(\"down\")"]
    assert first["benchmark"]["step"] == 1
    assert first["benchmark"]["completed"] is False
    assert second["benchmark"]["step"] == 2
    assert second["benchmark"]["completed"] is True
    assert second["benchmark"]["eval"]["quantity"] == 2


def test_benchmark_execute_requires_active_session():
    _, _, benchmark = make_runtime()

    with pytest.raises(BenchmarkError, match="No active benchmark session"):
        benchmark.execute("move(1, 0)")


def test_benchmark_truncates_at_max_steps():
    _, _, benchmark = make_runtime()
    benchmark.start("farming_lite", 0, max_steps=1)

    result = benchmark.execute("move(1, 0)")

    assert result["benchmark"]["step"] == 1
    assert result["benchmark"]["completed"] is False
    assert result["benchmark"]["truncated"] is True


def test_benchmark_stop_clears_session():
    _, _, benchmark = make_runtime()
    benchmark.start("farming_lite", 0)

    stopped = benchmark.stop()

    assert stopped["active"] is False
    assert stopped["stopped"] is True
    assert benchmark.status() == {"active": False}
