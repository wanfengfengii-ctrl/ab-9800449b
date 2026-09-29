"""API 层冒烟与契约测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app

T0 = datetime(2026, 9, 29, 8, tzinfo=timezone.utc)
client = TestClient(app)


def _hot_payload(exposure=30.0):
    return {
        "records": [
            {
                "time": (T0 + timedelta(seconds=100 * i)).isoformat(),
                "box_temp": 2.0,
                "ambient_temp": 30.0,
                "lid": "closed",
            }
            for i in range(6)
        ],
        "params": {
            "tau_closed": 600.0,
            "tau_open": 120.0,
            "max_box_temp": 8.0,
            "max_exposure": exposure,
        },
    }


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


def test_audit_reject_contract():
    r = client.post("/api/audit", json=_hot_payload())
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "reject"
    assert data["verdict"] == "拒收"
    assert data["first_failure"] is not None
    assert data["first_failure"]["segment_index"] == 1
    assert len(data["exposure_intervals"]) == 1
    iv = data["exposure_intervals"][0]
    assert iv["end_time"] > iv["start_time"]
    assert iv["duration"] > 30.0
    # 曲线、逐段证据齐全
    assert len(data["curve"]) == 5 * 24 + 1
    assert len(data["segments"]) == 5
    for seg in data["segments"]:
        assert {"start_time", "end_time", "tau", "extremum", "above_threshold"} <= set(seg)
    assert any("最早失效" in line for line in data["evidence"])


def test_audit_pass_contract():
    r = client.post("/api/audit", json=_hot_payload(exposure=100000.0))
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "pass"
    assert data["verdict"] == "放行"
    assert data["first_failure"] is None


def test_invalid_payload_returns_422_invalid():
    payload = _hot_payload()
    payload["records"] = payload["records"][:2]  # 少于 4 条
    r = client.post("/api/audit", json=payload)
    assert r.status_code == 422
    body = r.json()
    assert body["status"] == "invalid"
    assert isinstance(body["errors"], list) and body["errors"]


def test_malformed_body_422():
    r = client.post("/api/audit", json={"records": [], "params": {}})
    assert r.status_code == 422
    assert r.json()["status"] == "invalid"


def test_non_json_body_422():
    r = client.post(
        "/api/audit",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 422
    assert r.json()["status"] == "invalid"
    assert r.json()["errors"]


def test_openapi_available():
    r = client.get("/openapi.json")
    assert r.status_code == 200
    assert "/api/audit" in r.json()["paths"]
