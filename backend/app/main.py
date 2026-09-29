"""海上平台油样运输箱温控审计 API。"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import thermal
from .thermal import ValidationError

app = FastAPI(
    title="油样运输箱温控审计",
    version="1.0.0",
    description="以一阶热响应模型连续解析箱温，裁决放行/拒收。",
)


@app.exception_handler(ValidationError)
async def validation_error_handler(request: Request, exc: ValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "status": "invalid",
            "errors": exc.errors,
            "message": "数据不合法",
        },
    )


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/api/audit")
async def post_audit(request: Request):
    try:
        payload = await request.json()
    except Exception:
        raise ValidationError(["请求体不是合法的 JSON"])
    if not isinstance(payload, dict):
        raise ValidationError(["请求体必须是 JSON 对象"])
    records, params = thermal.validate_and_build(
        payload.get("records", []), payload.get("params", {})
    )
    result = thermal.audit(records, params)
    curve = thermal.sample_curve(records, params)
    return _serialize(result, curve, records)


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def _serialize(result, curve, records):
    return {
        "status": result.status,  # pass | reject
        "verdict": "放行" if result.status == "pass" else "拒收",
        "threshold": result.threshold,
        "max_exposure": result.max_exposure,
        "time_range": {"start": _iso(result.start_time), "end": _iso(result.end_time)},
        "curve": [
            {"time": _iso(t), "box_temp": tb, "ambient_temp": ta}
            for t, tb, ta in curve
        ],
        "records": [
            {
                "index": i,
                "time": _iso(r.time),
                "box_temp": r.box_temp,
                "ambient_temp": r.ambient_temp,
                "lid": r.lid,
            }
            for i, r in enumerate(records)
        ],
        "segments": [
            {
                "index": s.index,
                "start_time": _iso(s.start_time),
                "end_time": _iso(s.end_time),
                "duration": s.duration,
                "lid": s.lid,
                "tau": s.tau,
                "ambient_slope": s.ambient_slope,
                "t_start": s.t_start,
                "t_end": s.t_end,
                "recorded_box_temp_end": s.recorded_box_temp_end,
                "extremum": (
                    None
                    if s.extremum_time is None
                    else {
                        "time": _iso(s.extremum_time),
                        "value": s.extremum_value,
                        "kind": s.extremum_kind,
                    }
                ),
                "above_threshold": [
                    {"start_offset": lo, "end_offset": hi, "duration": hi - lo}
                    for lo, hi in s.above_subintervals
                ],
            }
            for s in result.segments
        ],
        "exposure_intervals": [
            {
                "start_time": _iso(iv.start_time),
                "end_time": _iso(iv.end_time),
                "duration": iv.duration,
            }
            for iv in result.exposure_intervals
        ],
        "total_exposure": result.total_exposure,
        "first_failure": (
            None
            if result.first_failure_time is None
            else {
                "time": _iso(result.first_failure_time),
                "segment_index": result.first_failure_segment,
            }
        ),
        "reading_deviations": [
            {
                "index": d.index,
                "time": _iso(d.time),
                "recorded": d.recorded,
                "modeled": d.modeled,
                "delta": d.delta,
            }
            for d in result.readings_deviation
        ],
        "evidence": _evidence(result),
    }


def _evidence(result) -> list[str]:
    lines: list[str] = []
    if result.status == "pass":
        lines.append(
            f"全程箱温连续曲线未出现持续超过 {result.threshold:.3g}℃ 且时长超过 "
            f"{result.max_exposure:.0f}s 的连续暴露，符合放行条件。"
        )
        if result.exposure_intervals:
            lines.append(
                f"存在 {len(result.exposure_intervals)} 段短暂越限但均未超过允许连续暴露时长。"
            )
    else:
        lines.append(
            f"发现 {len(result.exposure_intervals)} 个连续超温区间"
            f"（阈值 {result.threshold:.3g}℃，允许连续暴露 {result.max_exposure:.0f}s）："
        )
        for i, iv in enumerate(result.exposure_intervals, 1):
            lines.append(
                f"  区间{i}: {_iso(iv.start_time)} 至 {_iso(iv.end_time)}，"
                f"持续 {iv.duration:.1f}s"
                + ("（已超过允许暴露时长）" if iv.duration > result.max_exposure else "")
            )
        lines.append(f"油样最早失效时刻：{_iso(result.first_failure_time)}")
    return lines


# 构建后的前端静态资源（生产镜像中由 Dockerfile 生成）
_static_dir = Path(os.environ.get("STATIC_DIR", "/app/frontend/dist"))
if _static_dir.is_dir():
    app.mount(
        "/",
        StaticFiles(directory=str(_static_dir), html=True),
        name="frontend",
    )
