"""温控审计 API 冒烟脚本（verify 服务内运行）。

校验：健康检查、参数约定接口、拒收裁决（含连续超温区间证据与最早失效时刻）、
数据不合法 (422)。任何断言失败即以非零退出码结束容器。
"""
from __future__ import annotations

import os
import sys

import httpx

BASE = os.environ.get("AUDIT_BASE_URL", "http://app:8000").rstrip("/")

REJECT_PAYLOAD = {
    "records": [
        {"time": 0, "box_temp": 4.0, "ambient_temp": 25.0, "lid_open": False},
        {"time": 60, "box_temp": 7.806654, "ambient_temp": 25.0, "lid_open": False},
        {"time": 1560, "box_temp": 7.254505, "ambient_temp": 3.0, "lid_open": False},
        {"time": 2460, "box_temp": 3.211819, "ambient_temp": 3.0, "lid_open": False},
        {"time": 3360, "box_temp": 3.010546, "ambient_temp": 3.0, "lid_open": False},
    ],
    "parameters": {
        "tau_closed": 300,
        "tau_open": 90,
        "box_temp_limit": 8.0,
        "exposure_limit_seconds": 600,
    },
}

PASS_PAYLOAD = {
    "records": [
        {"time": 0, "box_temp": 4.0, "ambient_temp": 3.0, "lid_open": False},
        {"time": 300, "box_temp": 3.551819, "ambient_temp": 3.5, "lid_open": False},
        {"time": 600, "box_temp": 3.703003, "ambient_temp": 4.0, "lid_open": False},
        {"time": 900, "box_temp": 3.817165, "ambient_temp": 3.8, "lid_open": False},
    ],
    "parameters": {
        "tau_closed": 300,
        "tau_open": 90,
        "box_temp_limit": 8.0,
        "exposure_limit_seconds": 600,
    },
}


def check(cond: bool, msg: str) -> None:
    if not cond:
        print(f"SMOKE FAIL: {msg}", file=sys.stderr)
        sys.exit(1)
    print(f"  ✓ {msg}")


def main() -> None:
    print(f"目标审计服务：{BASE}")
    with httpx.Client(base_url=BASE, timeout=10) as c:
        r = c.get("/healthz")
        check(r.status_code == 200 and r.json().get("status") == "ok", "GET /healthz 返回 200/ok")

        r = c.get("/api/audit/schema")
        check(r.status_code == 200 and "tau_closed" in r.json()["parameters"], "GET /api/audit/schema 含模型参数约定")

        r = c.post("/api/audit", json=REJECT_PAYLOAD)
        check(r.status_code == 200, f"拒收场景 HTTP 200（实际 {r.status_code}）")
        body = r.json()
        check(body["status"] == "reject", "拒收场景裁决为 reject/拒收")
        intervals = body["exceedance_intervals"]
        check(len(intervals) >= 1, "至少报告 1 个连续超温区间")
        iv = intervals[0]
        check(iv["start_time"] < iv["end_time"], "超温区间起点早于终点")
        check(iv["duration_seconds"] >= 600, "超温区间持续时长达到允许连续暴露时长")
        ff = body.get("first_failure_time")
        check(ff is not None, "给出最早失效时刻")
        check(
            abs(ff["elapsed_seconds"] - (iv["elapsed_start_seconds"] + 600)) < 1e-6,
            "最早失效时刻 = 区间起点 + 允许暴露时长",
        )
        check(len(body["curve"]) > len(REJECT_PAYLOAD["records"]), "返回稠密箱温连续曲线（非仅离散读数）")
        check(any(s["max_temp"]["kind"] == "interior" for s in body["segments"]), "存在段内解析极值证据")

        r = c.post("/api/audit", json=PASS_PAYLOAD)
        body = r.json()
        check(r.status_code == 200 and body["status"] == "pass", "放行场景裁决为 pass/放行")
        check(body["first_failure_time"] is None, "放行场景无失效时刻")

        r = c.post("/api/audit", json={"records": [], "parameters": {}})
        check(r.status_code == 422 and r.json()["status"] == "invalid", "空记录判为数据不合法 (422)")

        bad = {
            "records": [
                {"time": 0, "box_temp": 4, "ambient_temp": 5, "lid_open": False},
                {"time": 0, "box_temp": 4, "ambient_temp": 5, "lid_open": False},
                {"time": 1, "box_temp": 4, "ambient_temp": 5, "lid_open": False},
                {"time": 2, "box_temp": 4, "ambient_temp": 5, "lid_open": False},
            ],
            "parameters": {
                "tau_closed": 300,
                "tau_open": 90,
                "box_temp_limit": 8,
                "exposure_limit_seconds": 600,
            },
        }
        r = c.post("/api/audit", json=bad)
        check(
            r.status_code == 422 and r.json()["errors"][0]["code"] == "time_not_strict",
            "时间非严格递增判为 time_not_strict",
        )

    print("冒烟全部通过。")


if __name__ == "__main__":
    main()
