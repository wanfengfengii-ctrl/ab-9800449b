"""温控审计核心算法测试。"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from app.thermal import (
    Params,
    Record,
    ValidationError,
    audit,
    sample_curve,
    validate_and_build,
)

T0 = datetime(2026, 9, 29, 8, 0, 0, tzinfo=timezone.utc)


def rec(offset_s, box, amb, lid="closed"):
    return Record(T0 + timedelta(seconds=offset_s), box, amb, lid)


def make_params(
    tau_c=600.0, tau_o=120.0, tmax=8.0, exposure=30.0
):
    return Params(tau_c, tau_o, tmax, exposure)


# ---------------------------------------------------------------------------
# 基本物理正确性
# ---------------------------------------------------------------------------


def test_constant_cold_ambient_passes():
    records = [rec(600 * i, 2.0, 2.0) for i in range(5)]
    result = audit(records, make_params())
    assert result.status == "pass"
    assert result.exposure_intervals == []
    assert result.first_failure_time is None
    # 恒温环境且初值已平衡：箱温恒为 2
    for s in result.segments:
        assert s.t_start == pytest.approx(2.0)
        assert s.t_end == pytest.approx(2.0)


def test_constant_hot_ambient_matches_closed_form_crossing():
    """恒温热环境：穿越时刻必须与闭式解一致。

    T(t)=Ta+(T0-Ta)e^{-t/tau}; 穿越 Tmax:
        t* = -tau * ln((Tmax-Ta)/(T0-Ta))
    """
    tau, ta, t0, tmax = 600.0, 30.0, 2.0, 8.0
    exposure = 30.0
    # 每 100s 一条，共 8 条
    records = [rec(100 * i, t0, ta) for i in range(8)]
    result = audit(records, make_params(tmax=tmax, exposure=exposure))

    t_cross = -tau * math.log((tmax - ta) / (t0 - ta))
    assert result.status == "reject"
    iv = result.exposure_intervals[0]
    assert (iv.start_time - T0).total_seconds() == pytest.approx(t_cross, abs=1e-6)
    assert iv.duration == pytest.approx(700.0 - t_cross, abs=1e-6)
    # 最早失效 = 穿越起点 + 允许暴露时长
    assert (result.first_failure_time - T0).total_seconds() == pytest.approx(
        t_cross + exposure, abs=1e-6
    )


def test_readings_all_below_threshold_but_continuous_curve_exceeds():
    """关键场景：每条上传读数都未超限，途中升温仍须判失效。"""
    tau, ta, tmax = 600.0, 30.0, 8.0
    # 记录点上的箱温读数（人为录入，全部 < 8）
    readings = [2.0, 4.2, 6.3, 7.4, 7.9]
    records = [rec(100 * i, readings[i], ta) for i in range(5)]
    assert all(v < tmax for v in readings)

    result = audit(records, make_params(tmax=tmax, exposure=30.0))
    assert result.status == "reject"
    # 模型曲线在 t≈144.7s 穿越，采样点 100s 与 200s 上都未被直接裁决
    t_cross = -tau * math.log((tmax - ta) / (2.0 - ta))
    assert 100 < t_cross < 200
    assert (result.exposure_intervals[0].start_time - T0).total_seconds() == pytest.approx(
        t_cross, abs=1e-6
    )
    # 读数与模型偏差被作为证据保留
    deltas = {d.index: d.delta for d in result.readings_deviation}
    assert deltas[1] != 0.0


def test_cross_segment_continuity_never_reset_to_readings():
    records = [rec(100 * i, 2.0, 25.0) for i in range(6)]
    result = audit(records, make_params())
    for a, b in zip(result.segments[:-1], result.segments[1:]):
        assert b.t_start == pytest.approx(a.t_end)
    # 模型末值不等于最后一条读数（读数不参与推进）
    assert result.segments[-1].t_end != pytest.approx(2.0)
    assert result.segments[-1].t_end > 8.0


def test_lid_open_switches_thermal_inertia():
    """箱盖开启段使用 tau_open，且段间箱温连续。"""
    records = [
        rec(0, 2.0, 30.0, "closed"),
        rec(100, 2.0, 30.0, "closed"),
        rec(200, 2.0, 30.0, "open"),
        rec(300, 2.0, 30.0, "open"),
        rec(600, 2.0, 30.0, "closed"),
    ]
    params = make_params(tau_c=600.0, tau_o=60.0)
    result = audit(records, params)
    # 段 [i, i+1] 采用起始记录（第 i 条）的箱盖状态（左连续约定）
    taus = [s.tau for s in result.segments]
    assert taus == [600.0, 600.0, 60.0, 60.0]
    lids = [s.lid for s in result.segments]
    assert lids == ["closed", "closed", "open", "open"]
    for a, b in zip(result.segments[:-1], result.segments[1:]):
        assert b.t_start == pytest.approx(a.t_end)

    # 同温起始（2℃→30℃，前 100s）下，开启段升温远快于关闭段：
    # 28(1-e^-100/60)≈22.95 vs 28(1-e^-100/600)≈4.30
    closed_run = audit(
        [rec(100 * i, 2.0, 30.0, "closed") for i in range(4)], params
    )
    open_run = audit(
        [rec(100 * i, 2.0, 30.0, "open") for i in range(4)], params
    )
    closed_gain = closed_run.segments[0].t_end - closed_run.segments[0].t_start
    open_gain = open_run.segments[0].t_end - open_run.segments[0].t_start
    assert open_gain == pytest.approx(28 * (1 - math.exp(-100 / 60)), rel=1e-9)
    assert closed_gain == pytest.approx(28 * (1 - math.exp(-100 / 600)), rel=1e-9)
    assert open_gain > closed_gain * 5


def test_interior_extremum_with_linear_ambient():
    """环境先降后升：箱温在段内出现极值，位置与数值须精确。"""
    # 单段无法构造（每段一条斜率），用三段：环境 20 -> -10 -> 20，箱温初值 5
    records = [
        rec(0, 5.0, 20.0),
        rec(300, 5.0, -10.0),
        rec(600, 5.0, 20.0),
        rec(900, 5.0, 20.0),
    ]
    result = audit(records, make_params(tmax=8.0, exposure=30.0))
    # 用密集数值采样解析公式复核每个报告的极值
    for seg in result.segments:
        if seg.extremum_time is None:
            continue
        dur = seg.duration
        b = seg.ambient_slope
        tau = seg.tau
        ta0 = records[seg.index].ambient_temp
        t_start = seg.t_start
        c = t_start - ta0 + b * tau

        def T(s):
            return ta0 - b * tau + b * s + c * math.exp(-s / tau)

        grid = [T(dur * k / 200001) for k in range(200002)]
        s_star = (seg.extremum_time - seg.start_time).total_seconds()
        if seg.extremum_kind == "max":
            assert seg.extremum_value == pytest.approx(max(grid), abs=1e-8)
            assert T(s_star) == pytest.approx(max(grid), abs=1e-8)
        else:
            assert seg.extremum_value == pytest.approx(min(grid), abs=1e-8)
            assert T(s_star) == pytest.approx(min(grid), abs=1e-8)


def test_exposure_intervals_merge_across_records():
    """超温跨越多条记录须合并为同一连续区间，暴露时长跨记录延续。"""
    # 400s 处短暂降到阈值下方不足以中断（构造持续高温环境）
    records = [rec(100 * i, 2.0, 30.0) for i in range(6)]
    result = audit(records, make_params(tmax=8.0, exposure=60.0))
    # 恒温环境只会有一个连续超温区间
    assert len(result.exposure_intervals) == 1
    iv = result.first_failure_time and result.exposure_intervals[0]
    assert iv.duration > 60.0


def test_short_excursion_below_max_duration_passes():
    """超温但连续暴露未超过允许时长 => 放行，仍报告越限区间证据。

    tau=60s, Ta=30 恒定, T0=7.95: 穿越 8℃ 时刻
        t* = -60 ln((8-30)/(7.95-30)) ≈ 365.4s
    观测窗 480s，超温持续约 115s，远小于允许暴露 3000s。
    读数取与模型一致的平衡轨迹（后两条读数本身也 >8，
    但连续暴露时长未超限，仍应放行）。
    """
    box_readings = [7.95, 27.02, 29.60, 29.95, 29.99]
    records = [rec(120 * i, box_readings[i], 30.0) for i in range(5)]
    result = audit(
        records, make_params(tau_c=60.0, tau_o=20.0, tmax=8.0, exposure=3000.0)
    )
    t_cross = -60.0 * math.log((8.0 - 30.0) / (7.95 - 30.0))
    assert result.status == "pass"
    assert len(result.exposure_intervals) == 1
    iv = result.exposure_intervals[0]
    assert (iv.start_time - T0).total_seconds() == pytest.approx(t_cross, abs=1e-6)
    assert iv.duration == pytest.approx(480.0 - t_cross, abs=1e-4)
    assert iv.duration < 3000.0
    assert result.first_failure_time is None


def test_two_separated_excursions_reported_separately():
    """环境温度两次脉冲：形成两个独立超温区间，分别报告起止。"""
    # 箱温初值 8.1 即超温；环境先冷（拉回阈值下）再热（再次超温）
    records = [
        rec(0, 8.1, -10.0),
        rec(600, 8.0, -10.0),
        rec(1200, 8.0, 40.0),
        rec(1800, 8.0, 40.0),
    ]
    result = audit(
        records, make_params(tau_c=300.0, tau_o=60.0, tmax=8.0, exposure=60.0)
    )
    assert result.status == "reject"
    assert len(result.exposure_intervals) >= 2
    # 区间按时间排序且互不相交
    times = [(iv.start_time, iv.end_time) for iv in result.exposure_intervals]
    for (s1, e1), (s2, e2) in zip(times[:-1], times[1:]):
        assert e1 < s2


def test_first_failure_points_to_earliest_interval_only():
    records = [rec(100 * i, 2.0, 30.0) for i in range(6)]
    result = audit(records, make_params(tmax=8.0, exposure=60.0))
    t_cross = -600.0 * math.log((8.0 - 30.0) / (2.0 - 30.0))
    assert (result.first_failure_time - T0).total_seconds() == pytest.approx(
        t_cross + 60.0, abs=1e-6
    )
    assert result.first_failure_segment == 1  # 穿越发生在第 2 段 (100,200)


# ---------------------------------------------------------------------------
# 曲线采样
# ---------------------------------------------------------------------------


def test_sample_curve_continuous_and_endpoints():
    records = [rec(100 * i, 2.0, 25.0) for i in range(5)]
    params = make_params()
    curve = sample_curve(records, params, points_per_segment=10)
    assert len(curve) == 41
    assert curve[0][0] == T0
    assert curve[-1][0] == T0 + timedelta(seconds=400)
    # 时间严格递增
    for a, b in zip(curve[:-1], curve[1:]):
        assert b[0] > a[0]


# ---------------------------------------------------------------------------
# 输入校验
# ---------------------------------------------------------------------------


def test_rejects_fewer_than_four_records():
    raw = [
        {"time": (T0 + timedelta(seconds=60 * i)).isoformat(),
         "box_temp": 2.0, "ambient_temp": 20.0, "lid": "closed"}
        for i in range(3)
    ]
    with pytest.raises(ValidationError) as ei:
        validate_and_build(raw, {"tau_closed": 600, "tau_open": 120,
                                 "max_box_temp": 8, "max_exposure": 30})
    assert any("至少需要 4 条" in e for e in ei.value.errors)


def test_rejects_more_than_thirty_records():
    raw = [
        {"time": (T0 + timedelta(seconds=60 * i)).isoformat(),
         "box_temp": 2.0, "ambient_temp": 20.0, "lid": "closed"}
        for i in range(31)
    ]
    with pytest.raises(ValidationError) as ei:
        validate_and_build(raw, {"tau_closed": 600, "tau_open": 120,
                                 "max_box_temp": 8, "max_exposure": 30})
    assert any("最多允许 30 条" in e for e in ei.value.errors)


def test_rejects_non_increasing_time_and_bad_lid_and_nonpositive_tau():
    raw = [
        {"time": T0.isoformat(), "box_temp": 2.0, "ambient_temp": 20.0, "lid": "closed"},
        {"time": T0.isoformat(), "box_temp": 2.0, "ambient_temp": 20.0, "lid": "open"},
        {"time": (T0 + timedelta(seconds=120)).isoformat(),
         "box_temp": 2.0, "ambient_temp": 20.0, "lid": "ajar"},
        {"time": (T0 + timedelta(seconds=180)).isoformat(),
         "box_temp": 2.0, "ambient_temp": 20.0, "lid": "closed"},
    ]
    with pytest.raises(ValidationError) as ei:
        validate_and_build(raw, {"tau_closed": 0, "tau_open": -1,
                                 "max_box_temp": 8, "max_exposure": 0})
    msg = " | ".join(ei.value.errors)
    assert "严格晚于" in msg
    assert "open 或 closed" in msg
    assert any("正数" in e for e in ei.value.errors)


def test_rejects_non_finite_and_missing_fields():
    raw = [
        {"time": "not-a-time", "box_temp": "x", "ambient_temp": 20.0, "lid": "closed"},
        {"time": (T0 + timedelta(seconds=60)).isoformat(),
         "box_temp": float("inf"), "ambient_temp": 20.0, "lid": "closed"},
        {"time": (T0 + timedelta(seconds=120)).isoformat(),
         "box_temp": 2.0, "ambient_temp": 20.0, "lid": "closed"},
        {"time": (T0 + timedelta(seconds=180)).isoformat(),
         "box_temp": 2.0, "ambient_temp": 20.0, "lid": "closed"},
    ]
    with pytest.raises(ValidationError) as ei:
        validate_and_build(raw, {"tau_closed": 600, "tau_open": 120,
                                 "max_box_temp": 8, "max_exposure": 30})
    assert len(ei.value.errors) >= 3
