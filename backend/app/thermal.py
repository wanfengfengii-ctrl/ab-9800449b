"""一阶热响应模型的连续解析求解。

物理模型
========
箱温 T 对环境温度 Ta 作一阶惯性响应::

    dT/dt = (Ta(t) - T(t)) / tau

约定：
* 相邻两条记录之间，环境温度随时间线性变化：Ta(s) = Ta0 + b*s；
* 每一段内箱盖状态固定，热时间常数 tau 也固定；
  箱盖开启时热惯性切换 —— 开启段与关闭段可使用不同的 tau；
* 箱温曲线在记录时刻连续：下一段的初值 = 上一段的*解析*末值，
  录入的箱温只在首条记录作为初值，其余读数仅作为对照证据返回，
  绝不按离散采样点裁决。

每段解析解（s ∈ [0, dur]）::

    Ta(s) = Ta0 + b*s
    T(s)  = (Ta0 - b*tau) + b*s + c * exp(-s/tau)
    c     = T0 - Ta0 + b*tau

阈值穿越在单调子区间（端点或唯一内点驻点划分）上以二分法求连续函数
根，属于闭式函数求根，而不是用数值步进近似裁决。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

EPS = 1e-9
ROOT_TOL = 1e-10  # 求根的时间残差（秒）
BISECT_MAX_ITER = 200


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Record:
    time: datetime
    box_temp: float
    ambient_temp: float
    lid: Literal["open", "closed"]


@dataclass(frozen=True)
class Params:
    tau_closed: float          # 箱盖关闭时热时间常数（秒）
    tau_open: float            # 箱盖开启时热时间常数（秒）
    max_box_temp: float        # 允许箱温上限
    max_exposure: float        # 允许连续暴露时长（秒，超过即失效）


@dataclass
class Segment:
    index: int
    start_time: datetime
    end_time: datetime
    duration: float
    lid: str
    tau: float
    ambient_slope: float
    t_start: float             # 段内解析初值
    t_end: float               # 段内解析末值
    recorded_box_temp_end: float
    extremum_time: datetime | None
    extremum_value: float | None
    extremum_kind: str | None
    above_subintervals: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class ExposureInterval:
    start_time: datetime
    end_time: datetime
    duration: float


@dataclass(frozen=True)
class ReadingDeviation:
    index: int
    time: datetime
    recorded: float
    modeled: float
    delta: float


@dataclass
class AuditResult:
    status: Literal["pass", "reject"]
    records: list[Record]
    segments: list[Segment]
    exposure_intervals: list[ExposureInterval]
    max_exposure: float
    threshold: float
    first_failure_time: datetime | None
    first_failure_segment: int | None
    total_exposure: float
    readings_deviation: list[ReadingDeviation]
    start_time: datetime
    end_time: datetime


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------


class ValidationError(ValueError):
    """输入数据不合法（在转交给 422 响应前收集全部错误）。"""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


# ---------------------------------------------------------------------------
# 校验与解析
# ---------------------------------------------------------------------------


def _parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _finite_float(value: object, name: str, errors: list[str]) -> float | None:
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        errors.append(f"{name} 必须是数值")
        return None
    if f != f or f in (float("inf"), float("-inf")):
        errors.append(f"{name} 必须是有限数值")
        return None
    return f


def validate_and_build(
    raw_records: list[dict],
    raw_params: dict,
) -> tuple[list[Record], Params]:
    errors: list[str] = []

    if not isinstance(raw_records, list):
        raise ValidationError(["records 必须是数组"])

    n = len(raw_records)
    if n < 4:
        errors.append(f"至少需要 4 条记录，当前 {n} 条")
    if n > 30:
        errors.append(f"最多允许 30 条记录，当前 {n} 条")

    records: list[Record] = []
    prev_time: datetime | None = None
    for i, raw in enumerate(raw_records):
        if not isinstance(raw, dict):
            errors.append(f"第 {i + 1} 条记录必须是对象")
            continue
        try:
            t = _parse_dt(raw.get("time"))
        except (ValueError, TypeError):
            errors.append(f"第 {i + 1} 条记录的时间格式非法：{raw.get('time')!r}")
            t = None  # type: ignore[assignment]
        box = _finite_float(raw.get("box_temp"), f"第 {i + 1} 条记录箱温", errors)
        amb = _finite_float(
            raw.get("ambient_temp"), f"第 {i + 1} 条记录环境温", errors
        )
        lid = raw.get("lid")
        if lid not in ("open", "closed"):
            errors.append(f"第 {i + 1} 条记录箱盖状态必须是 open 或 closed")
        if t is not None:
            if prev_time is not None and t <= prev_time:
                errors.append(
                    f"第 {i + 1} 条记录时间 {t.isoformat()} 必须严格晚于"
                    f"上一条 {prev_time.isoformat()}"
                )
            prev_time = t
        if t is not None and box is not None and amb is not None and lid in (
            "open",
            "closed",
        ):
            records.append(Record(t, box, amb, lid))

    p = raw_params if isinstance(raw_params, dict) else {}
    tau_c = _finite_float(p.get("tau_closed"), "箱体热惯性(关闭) tau_closed", errors)
    tau_o = _finite_float(p.get("tau_open"), "箱体热惯性(开启) tau_open", errors)
    tmax = _finite_float(p.get("max_box_temp"), "允许箱温 max_box_temp", errors)
    expo = _finite_float(
        p.get("max_exposure"), "允许连续暴露时长 max_exposure", errors
    )
    for val, label, unit in (
        (tau_c, "箱盖关闭热时间常数", "秒"),
        (tau_o, "箱盖开启热时间常数", "秒"),
    ):
        if val is not None and not (val > 0):
            errors.append(f"{label}必须为正数（{unit}）")
    if expo is not None and not (expo > 0):
        errors.append("允许连续暴露时长必须为正数（秒）")

    if errors:
        raise ValidationError(errors)

    return records, Params(tau_c, tau_o, tmax, expo)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 段内解析解
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _SegmentModel:
    ta0: float
    b: float
    tau: float
    c: float

    def temp(self, s: float) -> float:
        return (
            self.ta0
            - self.b * self.tau
            + self.b * s
            + self.c * math.exp(-s / self.tau)
        )

    def deriv(self, s: float) -> float:
        # dT/ds = b - c/tau * exp(-s/tau)
        return self.b - (self.c / self.tau) * math.exp(-s / self.tau)

    def stationary(self, dur: float) -> float | None:
        """返回 (0, dur) 内的驻点时刻；不存在则 None。"""
        if abs(self.c) < EPS:
            # 导数恒为 b
            return None
        # b - c/tau * exp(-s/tau) = 0  =>  s* = -tau * ln(b*tau/c)
        x = self.b * self.tau / self.c
        if x <= 0:
            return None
        s_star = -self.tau * math.log(x)
        if EPS < s_star < dur - EPS:
            return s_star
        return None


def _find_root(m: _SegmentModel, lo: float, hi: float, target: float) -> float:
    """在 [lo, hi]（端点异号）上二分求 T(s)=target 的根。"""
    flo = m.temp(lo) - target
    fhi = m.temp(hi) - target
    if abs(flo) <= EPS:
        return lo
    if abs(fhi) <= EPS:
        return hi
    # 浮点安全：端点严格异号才进来
    for _ in range(BISECT_MAX_ITER):
        mid = 0.5 * (lo + hi)
        fm = m.temp(mid) - target
        if abs(fm) <= EPS or (hi - lo) < ROOT_TOL:
            return mid
        if flo * fm < 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return 0.5 * (lo + hi)


def _above_subintervals(
    m: _SegmentModel, dur: float, threshold: float
) -> list[tuple[float, float]]:
    """求段内 T(s) > threshold 的 s 区间集合（对端点触碰闭合为零宽，不产生区间）。

    用端点与唯一可能的内点驻点把区间划成至多两个单调子区间，
    在每个子区间内至多穿越一次阈值。
    """
    cuts = [0.0, dur]
    s_star = m.stationary(dur)
    if s_star is not None:
        cuts.insert(1, s_star)
    cuts.sort()

    result: list[tuple[float, float]] = []
    for a, z in zip(cuts[:-1], cuts[1:]):
        va, vz = m.temp(a), m.temp(z)
        above_a = va > threshold + EPS
        above_z = vz > threshold + EPS
        if above_a and above_z:
            result.append((a, z))
        elif above_a or above_z:
            root = _find_root(m, a, z, threshold)
            if above_a:
                if root - a > EPS:
                    result.append((a, root))
            else:
                if z - root > EPS:
                    result.append((root, z))
        else:
            # 两端都不高：单调子区间内部不可能更高（极值在端点）
            # 但驻点本身恰为子区间端点，无需再查。
            continue
    # 合并（理论上相邻子区间不会在阈值上方相接，防御性合并）
    merged: list[tuple[float, float]] = []
    for lo, hi in sorted(result):
        if merged and lo <= merged[-1][1] + EPS:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return [(lo, hi) for lo, hi in merged if hi - lo > EPS]


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def audit(records: list[Record], params: Params) -> AuditResult:
    n = len(records)
    segments: list[Segment] = []
    # 全局超温区间：元素为 (起始全局秒, 结束全局秒)
    raw_intervals: list[tuple[float, float]] = []
    t_global = 0.0

    t_curve = records[0].box_temp
    for i in range(n - 1):
        r0, r1 = records[i], records[i + 1]
        dur = (r1.time - r0.time).total_seconds()
        tau = params.tau_open if r0.lid == "open" else params.tau_closed
        b = (r1.ambient_temp - r0.ambient_temp) / dur
        m = _SegmentModel(ta0=r0.ambient_temp, b=b, tau=tau,
                          c=t_curve - r0.ambient_temp + b * tau)

        above = _above_subintervals(m, dur, params.max_box_temp)
        for lo, hi in above:
            raw_intervals.append((t_global + lo, t_global + hi))

        s_star = m.stationary(dur)
        ext_time = ext_val = ext_kind = None
        if s_star is not None:
            ext_time = r0.time.fromtimestamp(
                r0.time.timestamp() + s_star, tz=timezone.utc
            )
            ext_val = m.temp(s_star)
            ext_kind = "max" if m.deriv(0) > 0 else "min"
        seg = Segment(
            index=i,
            start_time=r0.time,
            end_time=r1.time,
            duration=dur,
            lid=r0.lid,
            tau=tau,
            ambient_slope=b,
            t_start=t_curve,
            t_end=m.temp(dur),
            recorded_box_temp_end=r1.box_temp,
            extremum_time=ext_time,
            extremum_value=ext_val,
            extremum_kind=ext_kind,
            above_subintervals=above,
        )
        segments.append(seg)

        t_curve = m.temp(dur)  # 连续传递，绝不重置成读数
        t_global += dur

    # 合并跨段相连的超温区间（间隙 <= EPS 视为同一次连续暴露）
    raw_intervals.sort()
    merged: list[list[float]] = []
    for lo, hi in raw_intervals:
        if merged and lo <= merged[-1][1] + EPS:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])

    base = records[0].time
    exposure: list[ExposureInterval] = []
    first_failure_time = None
    first_failure_segment = None
    for lo, hi in merged:
        start = base.fromtimestamp(base.timestamp() + lo, tz=timezone.utc)
        end = base.fromtimestamp(base.timestamp() + hi, tz=timezone.utc)
        duration = hi - lo
        exposure.append(ExposureInterval(start, end, duration))
        if duration > params.max_exposure + EPS and first_failure_time is None:
            # 首次失效时刻 = 首个超限区间起点 + 允许暴露时长
            fail_secs = lo + params.max_exposure
            first_failure_time = base.fromtimestamp(
                base.timestamp() + fail_secs, tz=timezone.utc
            )
            first_failure_segment = _segment_at(segments, lo)

    total_exposure = sum(iv.duration for iv in exposure)
    status: Literal["pass", "reject"] = (
        "reject" if first_failure_time is not None else "pass"
    )

    deviations = [
        ReadingDeviation(
            index=0,
            time=records[0].time,
            recorded=records[0].box_temp,
            modeled=segments[0].t_start,
            delta=0.0,
        )
    ]
    for seg in segments:
        dev = seg.recorded_box_temp_end - seg.t_end
        deviations.append(
            ReadingDeviation(
                index=seg.index + 1,
                time=seg.end_time,
                recorded=seg.recorded_box_temp_end,
                modeled=seg.t_end,
                delta=dev,
            )
        )

    return AuditResult(
        status=status,
        records=records,
        segments=segments,
        exposure_intervals=exposure,
        max_exposure=params.max_exposure,
        threshold=params.max_box_temp,
        first_failure_time=first_failure_time,
        first_failure_segment=first_failure_segment,
        total_exposure=total_exposure,
        readings_deviation=deviations,
        start_time=records[0].time,
        end_time=records[-1].time,
    )


def _segment_at(segments: list[Segment], global_sec: float) -> int:
    acc = 0.0
    for seg in segments:
        if acc - EPS <= global_sec < acc + seg.duration + EPS:
            return seg.index
        acc += seg.duration
    return segments[-1].index


def sample_curve(
    records: list[Record], params: Params, points_per_segment: int = 24
) -> list[tuple[datetime, float, float]]:
    """供前端绘制连续箱温曲线：每段均匀采样（仅用于绘图，不参与裁决）。

    返回 (时间, 箱温模型值, 线性环境温)。段末点不重复。
    """
    out: list[tuple[datetime, float, float]] = []
    t_curve = records[0].box_temp
    r0 = records[0]
    out.append((r0.time, t_curve, r0.ambient_temp))
    for i in range(len(records) - 1):
        r0, r1 = records[i], records[i + 1]
        dur = (r1.time - r0.time).total_seconds()
        tau = params.tau_open if r0.lid == "open" else params.tau_closed
        b = (r1.ambient_temp - r0.ambient_temp) / dur
        m = _SegmentModel(ta0=r0.ambient_temp, b=b, tau=tau,
                          c=t_curve - r0.ambient_temp + b * tau)
        for k in range(1, points_per_segment + 1):
            s = dur * k / points_per_segment
            ts = r0.time.fromtimestamp(r0.time.timestamp() + s, tz=timezone.utc)
            out.append((ts, m.temp(s), r0.ambient_temp + b * s))
        t_curve = m.temp(dur)
    return out
