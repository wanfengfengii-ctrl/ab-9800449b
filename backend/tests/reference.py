"""独立于闭式解的参考实现：小步长 RK4 积分 dT/dt=(T_env-T)/tau。

仅用于测试中交叉核验生产代码的解析解，生产裁决路径不含任何数值步进。
"""
from __future__ import annotations

import math


def _ambient_linear(a, c, t_start, dur):
    def env(tt):
        return a + (c - a) * (tt - t_start) / dur

    return env


def _rk4_step(T, t, h, env, tau):
    k1 = (env(t) - T) / tau
    k2 = (env(t + h / 2) - (T + h * k1 / 2)) / tau
    k3 = (env(t + h / 2) - (T + h * k2 / 2)) / tau
    k4 = (env(t + h) - (T + h * k3)) / tau
    return T + h * (k1 + 2 * k2 + 2 * k3 + k4) / 6


def rk4_simulate(records, tau_closed, tau_open, dt=0.25):
    """以 records 的 box_temp[0] 为初值，按各段 lid_open 选 tau 向前积分。

    返回逐 dt 的 (t, T) 列表，段长非整数倍 dt 时尾部补齐到端点。
    """
    out = []
    T = float(records[0]["box_temp"])
    t = float(records[0]["time"])
    out.append((t, T))
    for i in range(len(records) - 1):
        r0, r1 = records[i], records[i + 1]
        dur = float(r1["time"]) - float(r0["time"])
        env = _ambient_linear(float(r0["ambient_temp"]), float(r1["ambient_temp"]), t, dur)
        tau = float(tau_open if r0["lid_open"] else tau_closed)

        n = int(math.floor(dur / dt))
        for k in range(n):
            h = min(dt, dur - k * dt)
            T = _rk4_step(T, t, h, env, tau)
            t += h
            out.append((t, T))
        if t < float(r1["time"]) - 1e-9:
            h = float(r1["time"]) - t
            if h > 1e-12:
                T = _rk4_step(T, t, h, env, tau)
                t = float(r1["time"])
                out.append((t, T))
    return out


def make_records_from_sim(times, ambients, lid, t0_box, tau_closed, tau_open):
    """给定每时刻环境温/箱盖，用 RK4 生成与模型自洽的箱温记录。"""
    raw = [
        {"time": times[0], "box_temp": t0_box, "ambient_temp": ambients[0], "lid_open": lid[0]}
    ]
    T = t0_box
    t = float(times[0])
    dt = 0.1
    for i in range(len(times) - 1):
        dur = float(times[i + 1]) - float(times[i])
        env = _ambient_linear(ambients[i], ambients[i + 1], t, dur)
        tau = float(tau_open if lid[i] else tau_closed)
        n = int(round(dur / dt))
        for _ in range(n):
            T = _rk4_step(T, t, dt, env, tau)
            t += dt
        raw.append(
            {
                "time": times[i + 1],
                "box_temp": T,
                "ambient_temp": ambients[i + 1],
                "lid_open": lid[i + 1],
            }
        )
    return raw
