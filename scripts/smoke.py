"""温控审计 API 冒烟脚本：供 verify 服务在 app 健康后调用。

校验三类裁决（放行 / 拒收 / 数据不合法）的真实 HTTP 契约，
并核对拒收证据中的起止时刻、持续时长与首个失效时刻。
退出码非 0 即视为冒烟失败。
"""

from __future__ import annotations

import math
import sys
import time

import httpx

if len(sys.argv) != 2:
    print("用法: smoke.py <base_url>", file=sys.stderr)
    sys.exit(2)

BASE = sys.argv[1].rstrip("/")
TIMEOUT = httpx.Timeout(10.0)


def wait_healthy(deadline_s: float = 60.0) -> None:
    start = time.monotonic()
    last = None
    while time.monotonic() - start < deadline_s:
        try:
            r = httpx.get(f"{BASE}/health", timeout=TIMEOUT)
            if r.status_code == 200 and r.json().get("status") == "healthy":
                print(f"[health] OK: {r.json()}")
                return
            last = f"HTTP {r.status_code}: {r.text[:120]}"
        except httpx.HTTPError as exc:
            last = repr(exc)
        time.sleep(1.0)
    raise SystemExit(f"健康检查在 {deadline_s:.0f}s 内未通过：{last}")


def reject_payload():
    return {
        "records": [
            {
                "time": f"2026-09-29T08:{m:02d}:00Z",
                "box_temp": box,
                "ambient_temp": 30.0,
                "lid": "closed",
            }
            # 读数本身全部 < 8℃，但连续曲线途中穿越
            for m, box in zip((0, 1, 2, 3, 4), (2.0, 4.0, 6.0, 7.5, 7.9))
        ],
        "params": {
            "tau_closed": 600.0,
            "tau_open": 120.0,
            "max_box_temp": 8.0,
            "max_exposure": 30.0,
        },
    }


def check(label, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        raise SystemExit(f"冒烟失败：{label} {detail}")


def main():
    wait_healthy()

    # 1) 拒收：读数均未超限，连续曲线超温且连续暴露 > 30s
    r = httpx.post(f"{BASE}/api/audit", json=reject_payload(), timeout=TIMEOUT)
    check("拒收场景 HTTP 200", r.status_code == 200, str(r.status_code))
    d = r.json()
    check("status=reject", d.get("status") == "reject", d.get("status"))
    check("verdict=拒收", d.get("verdict") == "拒收")
    ivs = d.get("exposure_intervals", [])
    check("至少 1 个连续超温区间", len(ivs) >= 1, str(len(ivs)))
    iv = ivs[0]
    check("区间有起止时刻", bool(iv.get("start_time")) and bool(iv.get("end_time")))
    check("区间持续时间为正且超允许暴露", iv["duration"] > 30.0, f"{iv['duration']:.1f}s")
    check("结束晚于起始", iv["end_time"] > iv["start_time"])

    ff = d.get("first_failure")
    check("报告首个失效时刻", ff is not None and bool(ff.get("time")))
    # 首个失效时刻 = 最早超温区间起点 + 允许连续暴露时长
    t0 = time.strptime(iv["start_time"], "%Y-%m-%dT%H:%M:%S.%fZ")
    tf = time.strptime(ff["time"], "%Y-%m-%dT%H:%M:%S.%fZ")
    delta = time.mktime(tf) - time.mktime(t0)
    check(
        "首个失效 = 区间起点 + 30s",
        math.isclose(delta, 30.0, abs_tol=1e-3),
        f"delta={delta:.3f}s",
    )
    check("曲线采样存在", len(d.get("curve", [])) >= 10)
    check("逐段极值存在", len(d.get("segments", [])) == 4)
    check("证据文本含失效时刻", any("最早失效" in e for e in d.get("evidence", [])))

    # 2) 放行：冷链稳定
    ok_payload = reject_payload()
    ok_payload["params"]["max_exposure"] = 100000.0
    r = httpx.post(f"{BASE}/api/audit", json=ok_payload, timeout=TIMEOUT)
    d = r.json()
    check("放行场景 status=pass", r.status_code == 200 and d.get("status") == "pass")
    check("放行无失效时刻", d.get("first_failure") is None)

    # 3) 数据不合法：记录不足 4 条
    bad = reject_payload()
    bad["records"] = bad["records"][:2]
    r = httpx.post(f"{BASE}/api/audit", json=bad, timeout=TIMEOUT)
    check("非法数据返回 422", r.status_code == 422, str(r.status_code))
    body = r.json()
    check("422 状态标记 invalid", body.get("status") == "invalid")
    check("422 返回错误列表", isinstance(body.get("errors"), list) and body["errors"])

    # 4) 前端静态页面由同一服务托管
    r = httpx.get(f"{BASE}/", timeout=TIMEOUT)
    check("首页 HTTP 200", r.status_code == 200, str(r.status_code))
    check("首页为前端 HTML", "油样运输箱温控审计" in r.text)

    print("\n冒烟全部通过：放行 / 拒收 / 数据不合法 三类契约均符合预期。")


if __name__ == "__main__":
    main()
