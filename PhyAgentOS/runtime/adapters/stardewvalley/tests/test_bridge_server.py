import pytest

starlette = pytest.importorskip("starlette")
from starlette.testclient import TestClient

from PhyAgentOS.runtime.adapters.stardewvalley.bridge.action_parser import ActionParseError
from PhyAgentOS.runtime.adapters.stardewvalley.bridge.bridge_server import create_app


class FakeRuntime:
    stardojo_port = 10783

    def __init__(self, image_path=None):
        self.executed = []
        self.image_path = image_path
        self.latest_image_path = None

    def observe(self):
        if self.image_path is not None:
            self.latest_image_path = self.image_path
        return {"location": "Farm"}

    def execute(self, action):
        if action == "bad()":
            raise ActionParseError("Skill not allowed: bad")
        self.executed.append(action)
        if self.image_path is not None:
            self.latest_image_path = self.image_path
        return {"position": [62, 17]}


def test_health():
    client = TestClient(create_app(FakeRuntime()))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "stardojo_port": 10783}


def test_observe():
    client = TestClient(create_app(FakeRuntime()))

    response = client.get("/observe")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "obs": {"location": "Farm", "latest_image_url": None}}


def test_execute():
    runtime = FakeRuntime()
    client = TestClient(create_app(runtime))

    response = client.post("/execute", json={"action": "move(1, 0)"})

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "action": "move(1, 0)",
        "obs": {"position": [62, 17], "latest_image_url": None},
    }
    assert runtime.executed == ["move(1, 0)"]


def test_execute_requires_action():
    client = TestClient(create_app(FakeRuntime()))

    response = client.post("/execute", json={})

    assert response.status_code == 400
    assert response.json()["ok"] is False
    assert "action" in response.json()["error"]


def test_execute_reports_parser_error_as_400():
    client = TestClient(create_app(FakeRuntime()))

    response = client.post("/execute", json={"action": "bad()"})

    assert response.status_code == 400
    assert response.json() == {"ok": False, "error": "Skill not allowed: bad"}



def test_observe_adds_latest_image_url_and_serves_latest_image(tmp_path):
    image = tmp_path / "latest.jpeg"
    image.write_bytes(b"fake image bytes")
    client = TestClient(create_app(FakeRuntime(image_path=image)))

    response = client.get("/observe")

    assert response.status_code == 200
    assert response.json()["obs"]["latest_image_url"] == "http://testserver/images/latest"

    image_response = client.get("/images/latest")
    assert image_response.status_code == 200
    assert image_response.content == b"fake image bytes"


def test_latest_image_returns_404_before_any_screenshot():
    client = TestClient(create_app(FakeRuntime()))

    response = client.get("/images/latest")

    assert response.status_code == 404
    assert response.json()["ok"] is False



class FakeBenchmarkRuntime:
    def __init__(self):
        self.started = []
        self.executed = []
        self.stopped = False

    def start(self, task_name, task_id, max_steps=None):
        self.started.append((task_name, task_id, max_steps))
        return {
            "obs": {"location": "Farm"},
            "benchmark": {
                "active": True,
                "task_name": task_name,
                "task_id": task_id,
                "step": 0,
                "completed": False,
            },
        }

    def status(self):
        return {"active": bool(self.started), "step": len(self.executed)}

    def execute(self, action):
        if action == "bad()":
            raise ActionParseError("Skill not allowed: bad")
        self.executed.append(action)
        return {
            "obs": {"position": [len(self.executed), 0]},
            "benchmark": {
                "active": True,
                "step": len(self.executed),
                "completed": len(self.executed) >= 2,
                "eval": {"quantity": len(self.executed)},
            },
        }

    def stop(self):
        self.stopped = True
        return {"active": False, "stopped": True}


def test_benchmark_start_route():
    benchmark = FakeBenchmarkRuntime()
    client = TestClient(create_app(FakeRuntime(), benchmark_runtime=benchmark))

    response = client.post("/benchmark/start", json={"task_name": "farming_lite", "task_id": 0, "max_steps": 5})

    assert response.status_code == 200
    assert benchmark.started == [("farming_lite", 0, 5)]
    assert response.json()["ok"] is True
    assert response.json()["obs"] == {"location": "Farm", "latest_image_url": None}
    assert response.json()["benchmark"]["task_name"] == "farming_lite"


def test_benchmark_status_route():
    benchmark = FakeBenchmarkRuntime()
    client = TestClient(create_app(FakeRuntime(), benchmark_runtime=benchmark))
    client.post("/benchmark/start", json={"task_name": "farming_lite", "task_id": 0})

    response = client.get("/benchmark/status")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "benchmark": {"active": True, "step": 0}}


def test_benchmark_execute_route():
    benchmark = FakeBenchmarkRuntime()
    client = TestClient(create_app(FakeRuntime(), benchmark_runtime=benchmark))

    response = client.post("/benchmark/execute", json={"action": "move(1, 0)"})

    assert response.status_code == 200
    assert benchmark.executed == ["move(1, 0)"]
    assert response.json()["ok"] is True
    assert response.json()["action"] == "move(1, 0)"
    assert response.json()["obs"] == {"position": [1, 0], "latest_image_url": None}
    assert response.json()["benchmark"]["eval"] == {"quantity": 1}


def test_benchmark_execute_reports_parser_error_as_400():
    benchmark = FakeBenchmarkRuntime()
    client = TestClient(create_app(FakeRuntime(), benchmark_runtime=benchmark))

    response = client.post("/benchmark/execute", json={"action": "bad()"})

    assert response.status_code == 400
    assert response.json() == {"ok": False, "error": "Skill not allowed: bad"}


def test_benchmark_start_requires_json_object():
    client = TestClient(create_app(FakeRuntime(), benchmark_runtime=FakeBenchmarkRuntime()))

    response = client.post("/benchmark/start", json=[])

    assert response.status_code == 400
    assert response.json()["ok"] is False


def test_benchmark_stop_route():
    benchmark = FakeBenchmarkRuntime()
    client = TestClient(create_app(FakeRuntime(), benchmark_runtime=benchmark))

    response = client.post("/benchmark/stop")

    assert response.status_code == 200
    assert benchmark.stopped is True
    assert response.json() == {"ok": True, "benchmark": {"active": False, "stopped": True}}
