"""FastAPI 业务 API 测试：放行/拒收/数据不合法三态与证据。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.main import app
from tests.reference import make_records_from_sim

client = TestClient(app)

PARAMS = {
    "tau_closed": 300,
    "tau_open": 90,
    "box_temp_limit": 8.0,
    "exposure_limit_seconds": 600,
}


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_schema_endpoint():
    r = client.get("/api/audit/schema")
    assert r.status_code == 200
    assert "tau_closed" in r.json()["parameters"]


def test_reject_returns_full_evidence():
    times = [0, 60, 1560, 2460, 3360]
    ambs = [25.0, 25.0, 3.0, 3.0, 3.0]
    lids = [False] * 5
    recs = make_records_from_sim(times, ambs, lids, 4.0, 300.0, 90.0)
    r = client.post("/api/audit", json={"records": recs, "parameters": PARAMS})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "reject"
    assert body["verdict"] == "拒收"
    iv = body["exceedance_intervals"][0]
    assert iv["start_time"] < iv["end_time"]
    assert iv["duration_seconds"] >= PARAMS["exposure_limit_seconds"]
    ff = body["first_failure_time"]
    assert ff["elapsed_seconds"] == iv["elapsed_start_seconds"] + 600
    assert len(body["curve"]) > len(recs)
    assert body["model"]["solver"]


def test_pass_scenario():
    times = list(range(0, 2401, 300))
    ambs = [3.0, 3.5, 4.0, 3.8, 3.2, 3.0, 2.8, 2.5, 2.0]
    recs = make_records_from_sim(times, ambs, [False] * 9, 4.0, 300.0, 90.0)
    r = client.post("/api/audit", json={"records": recs, "parameters": PARAMS})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pass"
    assert body["verdict"] == "放行"
    assert body["first_failure_time"] is None
    assert body["exceedance_intervals"] == []


def test_invalid_record_count_is_422():
    recs = [
        {"time": i, "box_temp": 4.0, "ambient_temp": 5.0, "lid_open": False}
        for i in range(3)
    ]
    r = client.post("/api/audit", json={"records": recs, "parameters": PARAMS})
    assert r.status_code == 422
    body = r.json()
    assert body["status"] == "invalid"
    assert body["verdict"] == "数据不合法"
    assert body["errors"][0]["code"] == "bad_records"


def test_invalid_strict_time_and_lid():
    recs = [
        {"time": 0, "box_temp": 4.0, "ambient_temp": 5.0, "lid_open": False},
        {"time": 600, "box_temp": 4.0, "ambient_temp": 5.0, "lid_open": False},
        {"time": 600, "box_temp": 4.0, "ambient_temp": 5.0, "lid_open": False},
        {"time": 900, "box_temp": 4.0, "ambient_temp": 5.0, "lid_open": False},
    ]
    r = client.post("/api/audit", json={"records": recs, "parameters": PARAMS})
    assert r.status_code == 422
    assert r.json()["errors"][0]["code"] == "time_not_strict"

    recs[2]["time"] = 800
    recs[0]["lid_open"] = "open"
    r = client.post("/api/audit", json={"records": recs, "parameters": PARAMS})
    assert r.status_code == 422
    assert r.json()["errors"][0]["code"] == "bad_lid"


def test_malformed_json_is_400():
    r = client.post("/api/audit", content="{not json", headers={"content-type": "application/json"})
    assert r.status_code == 400
    assert r.json()["status"] == "invalid"


def test_body_must_be_object():
    r = client.post("/api/audit", json=[1, 2, 3])
    assert r.status_code == 400
    assert r.json()["status"] == "invalid"


def test_iso_time_payload():
    from datetime import datetime, timezone

    def iso(t):
        return datetime.fromtimestamp(1_700_000_000 + t, tz=timezone.utc).isoformat()

    recs = [
        {"time": iso(t), "box_temp": 4.0, "ambient_temp": 3.0, "lid_open": False}
        for t in range(0, 4)
    ]
    r = client.post("/api/audit", json={"records": recs, "parameters": PARAMS})
    assert r.status_code == 200
    assert isinstance(r.json()["records_echo"][0]["time"], str)
