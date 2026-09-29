"""温控审计引擎测试。"""
from __future__ import annotations

import math

import pytest

from app.thermal import ThermalValidationError, audit

from .reference import make_records_from_sim, rk4_simulate

TAU_CLOSED = 300.0
TAU_OPEN = 90.0
LIMIT = 8.0
EXPOSURE = 600.0


def params(**over):
    base = {
        "tau_closed": TAU_CLOSED,
        "tau_open": TAU_OPEN,
        "box_temp_limit": LIMIT,
        "exposure_limit_seconds": EXPOSURE,
    }
    base.update(over)
    return base


def run(records, **over):
    return audit({"records": records, "parameters": params(**over)})


def iso_records(times, boxes, ambs, lids):
    from datetime import datetime, timezone

    def iso(t):
        return datetime.fromtimestamp(1_700_000_000 + t, tz=timezone.utc).isoformat()

    return [
        {"time": iso(t), "box_temp": b, "ambient_temp": a, "lid_open": l}
        for t, b, a, l in zip(times, boxes, ambs, lids)
    ]


# ---------- 解析解交叉验证 ----------

def test_closed_form_matches_independent_rk4():
    times = list(range(0, 3601, 600))
    ambs = [25.0, 26.0, 24.5, 27.0, 23.0, 26.5, 24.0]
    lids = [False, True, False, False, True, False, False]
    recs = make_records_from_sim(times, ambs, lids, 20.0, TAU_CLOSED, TAU_OPEN)
    res = run(recs)

    sim = rk4_simulate(recs, TAU_CLOSED, TAU_OPEN, dt=0.25)
    # 取闭式曲线采样点与独立 RK4 积分逐点比较
    for pt in res["curve"][::37]:
        u = pt["elapsed_seconds"]
        # 在 sim 中线性插值
        for (ta, va), (tb, vb) in zip(sim, sim[1:]):
            if ta - 1e-9 <= u <= tb + 1e-9:
                ref = va + (vb - va) * (u - ta) / (tb - ta)
                assert abs(pt["box_temp"] - ref) < 1e-6, (u, pt["box_temp"], ref)
                break
        else:
            raise AssertionError(f"仿真未覆盖 t={u}")

    # 各段末端与下一实测读数（RK4 自洽数据）一致
    for seg in res["segments"]:
        assert abs(seg["model_record_gap"]) < 1e-8


# ---------- 场景：采样点全部合格、途中超温必须被捕获 ----------

def test_mid_segment_excursion_caught_though_samples_pass():
    # 核心业务场景：质控员录入的全部读数均未超限（4.0/7.81/7.25/3.21/3.01℃，
    # 全部 < 8℃），且数据与一阶模型完全自洽（model_record_gap≈1e-12）。
    # 第 2 段环境温由 25℃ 线性降到 3℃：箱温先追热冲高到闭式内部极大值
    # 约 18℃（t≈537s），再被冷环境拉回。只按离散采样点裁决必然误放行；
    # 解析解给出上穿 63.4s、下穿 1507.3s，连续超温约 1444s。
    times = [0, 60, 1560, 2460, 3360]
    ambs = [25.0, 25.0, 3.0, 3.0, 3.0]
    lids = [False] * 5
    recs = make_records_from_sim(times, ambs, lids, 4.0, TAU_CLOSED, TAU_OPEN)
    assert all(r["box_temp"] < LIMIT for r in recs)
    res = run(recs, exposure_limit_seconds=300)
    assert res["status"] == "reject"
    assert res["first_failure_time"] is not None
    hot = [
        s
        for s in res["segments"]
        if s["max_temp"]["value"] > LIMIT and s["max_temp"]["kind"] == "interior"
    ]
    assert len(hot) == 1
    spike = hot[0]["max_temp"]
    assert spike["value"] > 15.0
    # 超温峰严格位于段内部，而非任一记录时刻
    assert spike["elapsed_seconds"] not in times
    # 自洽数据：各段末模型值与下一读数一致
    assert all(abs(s["model_record_gap"]) < 1e-9 for s in res["segments"])
    # 连续超温区间证据完整
    iv = res["exceedance_intervals"][0]
    assert iv["reaches_limit"] is True
    assert iv["duration_seconds"] == pytest.approx(1443.9, abs=1.0)
    assert res["first_failure_time"]["elapsed_seconds"] == pytest.approx(
        iv["elapsed_start_seconds"] + 300, abs=1e-6
    )


def test_pass_when_always_below_limit():
    times = list(range(0, 2401, 300))
    ambs = [3.0, 3.5, 4.0, 3.8, 3.2, 3.0, 2.8, 2.5, 2.0]
    lids = [False] * 9
    recs = make_records_from_sim(times, ambs, lids, 4.0, TAU_CLOSED, TAU_OPEN)
    res = run(recs)
    assert res["status"] == "pass"
    assert res["exceedance_intervals"] == []
    assert res["first_failure_time"] is None
    assert res["total_exceedance_seconds"] == 0


# ---------- 跨记录延续 ----------

def test_exposure_accumulates_across_records():
    # 每段超温时间不足限额，但相邻段超温区间在记录点相接 → 合并后超限
    times = [0, 400, 800, 1200, 1600]
    ambs = [20.0, 20.0, 20.0, 20.0, 20.0]
    lids = [False, False, False, False, False]
    recs = make_records_from_sim(times, ambs, lids, 4.0, TAU_CLOSED, TAU_OPEN)
    res = run(recs)
    assert res["status"] == "reject"
    interval = res["exceedance_intervals"][0]
    # 首个失效时刻 = 区间起点 + 允许暴露时长
    ff = res["first_failure_time"]
    assert ff["elapsed_seconds"] == pytest.approx(
        interval["elapsed_start_seconds"] + EXPOSURE, abs=1e-6
    )
    assert ff["elapsed_seconds"] <= interval["elapsed_end_seconds"] + 1e-9
    # 各段内部的超温碎片数 >= 2，证明做了跨段合并
    pieces = sum(len(s["exceedance_intervals"]) for s in res["segments"])
    assert pieces >= 2
    assert len(res["exceedance_intervals"]) == 1


def test_short_excursion_below_limit_passes():
    # 超温但持续时间不足限额（暴露 10 分钟，限额 1 小时）
    times = [0, 600, 1200, 1800]
    ambs = [4.0, 25.0, 25.0, 4.0]
    lids = [False, False, False, False]
    recs = make_records_from_sim(times, ambs, lids, 4.0, TAU_CLOSED, TAU_OPEN)
    res = run(recs, exposure_limit_seconds=3600)
    assert res["status"] == "pass"
    assert res["exceedance_intervals"]
    assert res["exceedance_intervals"][0]["duration_seconds"] < 3600


def test_gap_below_limit_breaks_continuity():
    # 两段超温之间有明确低于阈值的间隙 → 两个独立区间，各自时长不足
    times = [0, 500, 1000, 1500, 2000, 2500]
    ambs = [20.0, 20.0, 2.0, 2.0, 20.0, 20.0]
    lids = [False] * 6
    recs = make_records_from_sim(times, ambs, lids, 6.0, TAU_CLOSED, TAU_OPEN)
    res = run(recs, exposure_limit_seconds=10_000)
    assert len(res["exceedance_intervals"]) == 2
    assert res["status"] == "pass"


# ---------- 箱盖热惯性切换 ----------

def test_lid_open_switches_tau():
    times = [0, 600, 1200, 1800]
    ambs = [25.0, 25.0, 25.0, 25.0]
    lids = [False, True, False, False]
    recs = make_records_from_sim(times, ambs, lids, 4.0, TAU_CLOSED, TAU_OPEN)
    res = run(recs)
    taus = [s["tau_seconds"] for s in res["segments"]]
    assert taus == [TAU_CLOSED, TAU_OPEN, TAU_CLOSED]
    assert res["segments"][1]["lid_open"] is True
    # 开启段响应更快：比较"本段闭合的温差占初始温差比例"（公平指标，
    # 与起点高度无关），tau_open < tau_closed ⇒ 开启段比例应更高
    seg0, seg1 = res["segments"][0], res["segments"][1]
    gap0 = 25.0 - seg0["box_temp_start"]
    gap1 = 25.0 - seg1["box_temp_start"]
    frac0 = (seg0["box_temp_end_model"] - seg0["box_temp_start"]) / gap0
    frac1 = (seg1["box_temp_end_model"] - seg1["box_temp_start"]) / gap1
    assert frac1 > frac0
    # 与闭式恒温解 1-exp(-Δ/τ) 核对
    assert frac0 == pytest.approx(1 - math.exp(-600 / TAU_CLOSED), abs=1e-9)
    assert frac1 == pytest.approx(1 - math.exp(-600 / TAU_OPEN), abs=1e-9)


# ---------- 解析极值与穿越点 ----------

def test_interior_extremum_is_reported():
    # 降温段：箱温先升后降，存在内部极大值
    times = [0, 900, 1800, 2700]
    ambs = [25.0, 10.0, 2.0, 2.0]
    lids = [False, False, False, False]
    recs = make_records_from_sim(times, ambs, lids, 7.5, TAU_CLOSED, TAU_OPEN)
    res = run(recs)
    seg = res["segments"][0]
    assert seg["max_temp"]["kind"] == "interior"
    # 与独立稠密 RK4 积分（dt=0.05s）的段内最大值核对
    sim = rk4_simulate(recs, TAU_CLOSED, TAU_OPEN, dt=0.05)
    ref_max = max(v for t, v in sim if 0 <= t <= 900)
    assert abs(seg["max_temp"]["value"] - ref_max) < 1e-4
    # 驻点时刻导数为零（由闭式导数核验）
    import math as _m

    s_star = seg["max_temp"]["elapsed_seconds"]
    b = seg["ambient_slope_per_second"]
    deriv = b - (recs[0]["box_temp"] - 25.0 + b * TAU_CLOSED) / TAU_CLOSED * _m.exp(
        -s_star / TAU_CLOSED
    )
    assert abs(deriv) < 1e-9


def test_crossings_are_up_down_paired():
    times = [0, 900, 1800, 2700, 3600]
    ambs = [20.0, 20.0, 20.0, 3.0, 3.0]
    lids = [False] * 5
    recs = make_records_from_sim(times, ambs, lids, 4.0, TAU_CLOSED, TAU_OPEN)
    res = run(recs)
    dirs = [d for s in res["segments"] for d in [c["direction"] for c in s["crossings"]]]
    assert "up" in dirs and "down" in dirs
    assert dirs.index("up") < dirs.index("down")


def test_crossing_root_is_accurate():
    # 恒温环境下可手工求穿越时刻并比对二分根
    T0, Tenv, tau, lim = 4.0, 20.0, 300.0, 8.0
    times = [0, 1000]
    recs = [
        {"time": 0, "box_temp": T0, "ambient_temp": Tenv, "lid_open": False},
        {"time": 1000, "box_temp": 9.9, "ambient_temp": Tenv, "lid_open": False},
    ]
    while len(recs) < 4:
        recs.append(
            {"time": 1000 + len(recs) * 1000, "box_temp": 9.9, "ambient_temp": Tenv, "lid_open": False}
        )
    res = run(recs)
    root_elapsed = res["segments"][0]["crossings"][0]["elapsed_seconds"]
    # T(s)=Tenv+(T0-Tenv)e^{-s/tau}=lim  →  s=-tau ln((lim-Tenv)/(T0-Tenv))
    expect = -tau * math.log((lim - Tenv) / (T0 - Tenv))
    assert abs(root_elapsed - expect) < 1e-6


# ---------- 时间格式 ----------

def test_iso_times_and_numeric_times_equivalent():
    times = [0, 600, 1200, 1800]
    ambs = [20.0, 20.0, 20.0, 20.0]
    lids = [False] * 4
    num = make_records_from_sim(times, ambs, lids, 4.0, TAU_CLOSED, TAU_OPEN)
    iso = iso_records(
        times, [r["box_temp"] for r in num], ambs, lids
    )
    r1 = run(num)
    r2 = run(iso)
    assert r1["status"] == r2["status"]
    assert (
        r1["first_failure_time"]["elapsed_seconds"]
        == r2["first_failure_time"]["elapsed_seconds"]
    )
    assert isinstance(r2["first_failure_time"]["time"], str)


# ---------- 数据合法性 ----------

@pytest.mark.parametrize(
    "mutate",
    [
        lambda rs: rs[:3],  # 少于 4 条
        lambda rs: rs + [rs[-1]] * 27,  # 31 条
    ],
)
def test_record_count_bounds(mutate):
    times = list(range(0, 5))
    base = [
        {"time": t, "box_temp": 4.0, "ambient_temp": 5.0, "lid_open": False}
        for t in times
    ]
    with pytest.raises(ThermalValidationError) as ei:
        run(mutate(base))
    assert ei.value.code == "bad_records"


def test_time_must_be_strictly_increasing():
    recs = [
        {"time": 0, "box_temp": 4.0, "ambient_temp": 5.0, "lid_open": False},
        {"time": 600, "box_temp": 4.0, "ambient_temp": 5.0, "lid_open": False},
        {"time": 600, "box_temp": 4.0, "ambient_temp": 5.0, "lid_open": False},
        {"time": 900, "box_temp": 4.0, "ambient_temp": 5.0, "lid_open": False},
    ]
    with pytest.raises(ThermalValidationError) as ei:
        run(recs)
    assert ei.value.code == "time_not_strict"


def test_mixed_time_formats_rejected():
    recs = [
        {"time": 0, "box_temp": 4.0, "ambient_temp": 5.0, "lid_open": False},
        {"time": "2023-11-14T22:10:00+00:00", "box_temp": 4.0, "ambient_temp": 5.0, "lid_open": False},
        {"time": 1200, "box_temp": 4.0, "ambient_temp": 5.0, "lid_open": False},
        {"time": 1800, "box_temp": 4.0, "ambient_temp": 5.0, "lid_open": False},
    ]
    with pytest.raises(ThermalValidationError) as ei:
        run(recs)
    assert ei.value.code == "mixed_time"


def test_bad_values_and_params():
    good = [
        {"time": t, "box_temp": 4.0, "ambient_temp": 5.0, "lid_open": False}
        for t in range(0, 4)
    ]
    bad = [dict(r, box_temp=float("nan")) for r in good]
    with pytest.raises(ThermalValidationError):
        run(bad)
    bad_lid = [dict(r) for r in good]
    bad_lid[0]["lid_open"] = "yes"
    with pytest.raises(ThermalValidationError) as ei:
        run(bad_lid)
    assert ei.value.code == "bad_lid"
    with pytest.raises(ThermalValidationError):
        run(good, tau_closed=0)
    with pytest.raises(ThermalValidationError):
        run(good, exposure_limit_seconds=-1)


# ---------- 证据完整性 ----------

def test_interval_report_contains_required_evidence():
    times = list(range(0, 3001, 600))
    ambs = [20.0] * 6
    lids = [False] * 6
    recs = make_records_from_sim(times, ambs, lids, 4.0, TAU_CLOSED, TAU_OPEN)
    res = run(recs)
    assert res["status"] == "reject"
    iv = res["exceedance_intervals"][0]
    for key in (
        "start_time",
        "end_time",
        "duration_seconds",
        "reaches_limit",
        "elapsed_start_seconds",
        "elapsed_end_seconds",
    ):
        assert key in iv
    assert iv["start_time"] < iv["end_time"]
    assert iv["duration_seconds"] > 0
    ff = res["first_failure_time"]
    assert ff["time"] >= iv["start_time"]
    assert ff["interval_index"] == iv["index"]


def test_tangent_at_limit_is_not_exceedance():
    # 边界：段内内部极大值恰好等于阈值（相切而非严格穿越），
    # T 始终 <= limit，不得产生超温区间。
    # 在 T0=4、b<0、tau=300 上对起点环境温 a 二分，使闭式极大值恰为 8.0。
    import math as _m

    tau, dur, b, T0, target = 300.0, 1500.0, -20.0 / 1500.0, 4.0, 8.0

    def max_value(a):
        ratio = (T0 - a + b * tau) / (b * tau)
        s_star = tau * _m.log(ratio)
        return a + b * (s_star - tau) + (T0 - a + b * tau) * _m.exp(-s_star / tau), s_star

    lo, hi = 8.0, 40.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        v, _ = max_value(mid)
        if v < target:
            lo = mid
        else:
            hi = mid
    a = 0.5 * (lo + hi)
    vmax, s_star = max_value(a)
    assert abs(vmax - target) < 1e-9
    assert 0 < s_star < dur
    recs = [
        {"time": 0, "box_temp": T0, "ambient_temp": a, "lid_open": False},
        {"time": dur, "box_temp": 3.0, "ambient_temp": a + b * dur, "lid_open": False},
        {"time": dur + 900, "box_temp": 3.0, "ambient_temp": 3.0, "lid_open": False},
        {"time": dur + 1800, "box_temp": 3.0, "ambient_temp": 3.0, "lid_open": False},
    ]
    res = run(recs)
    assert res["status"] == "pass"
    assert res["exceedance_intervals"] == []


def test_curve_covers_entire_timeline():
    times = [0, 300, 900, 1500]
    recs = [
        {"time": t, "box_temp": 4.0, "ambient_temp": 6.0, "lid_open": False}
        for t in times
    ]
    res = run(recs)
    assert res["curve"][0]["elapsed_seconds"] == 0
    assert res["curve"][-1]["elapsed_seconds"] == 1500
