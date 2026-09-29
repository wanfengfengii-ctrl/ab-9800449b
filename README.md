# 油样运输箱温控审计（全栈）

海上平台将油样转运至岸基实验室前，质控员用本系统核查运输箱在采样点之间
是否曾**连续**超过保存温度。系统以**一阶热响应模型逐段解析求解**箱温连续曲线，
按连续曲线（而非离散上传读数）裁决放行 / 拒收，并给出完整证据。

## 判定模型

每两个相邻记录构成一段。段内箱盖状态固定，环境温度按约定随时间线性变化，
箱温满足一阶惯性 ODE：

```
dT/dt = (Ta(t) − T(t)) / τ,        Ta(s) = Ta0 + b·s
```

段内解析解（**非数值步进**）：

```
T(s) = (Ta0 − b·τ) + b·s + c·e^(−s/τ),   c = T0 − Ta0 + b·τ
```

要点：

* **跨记录连续**：下一段初值 = 上一段的解析末值；录入箱温仅首条作为初值，
  其余读数只与模型曲线对照（偏差作为证据返回），不参与推进、不作为裁决点；
* **热惯性切换**：箱盖开启段用 `tau_open`，关闭段用 `tau_closed`；
* **段内极值**：解析解至多一个内点驻点 `s* = −τ·ln(b·τ/c)`，与端点比较即得
  该段严格极大/极小值及发生时刻；
* **阈值穿越**：在由驻点切分的单调子区间上对连续解析函数二分求根，
  得到精确的越限起止时刻；
* **连续暴露**：把各段越限子区间按全局时间合并（跨记录相连即同一区间），
  区间持续时间超过允许连续暴露时长即拒收；
  **首个失效时刻 = 最早超温区间起点 + 允许连续暴露时长**。

因此即使每条上传读数都未超限，只要读数之间连续曲线越限且持续超时，仍会判拒收。

## 目录结构

```
backend/            FastAPI 服务
  app/thermal.py    解析求解、求根、区间合并、输入校验（核心）
  app/main.py       /api/audit、/health、托管前端静态产物
  tests/            pytest（算法 15 项 + API 契约 6 项）
frontend/           Vite 原生 JS 前端（录入、SVG 连续曲线、证据表）
scripts/
  verify.sh         一次性校验编排：pytest → 前端构建 → API 冒烟
  smoke.py          放行/拒收/数据不合法三类 HTTP 契约冒烟
Dockerfile          多阶段：frontend-builder / runtime / verify
docker-compose.yml  app（常驻+健康检查）+ verify（一次性，健康后运行）
```

## 本地开发

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements.txt
pytest backend/tests -q

cd frontend && npm install && npm run dev      # 5173，代理 /api → :8000
cd backend && uvicorn app.main:app --reload    # 8000
```

## Docker 启动（端口由宿主机环境变量配置）

```bash
# 对外端口默认 8000，可用 APP_PORT 覆盖
APP_PORT=18080 docker compose up --build app
# 打开 http://localhost:18080
```

应用镜像内置 `HEALTHCHECK`（curl `/health`），Compose 也声明了健康检查。

## 一次性 verify 服务

`verify` 服务通过 `depends_on: condition: service_healthy` 确保 **app 健康后**
才启动，依次执行：后端 pytest → 前端 vite 构建 → 温控审计 API 冒烟，
然后**自行退出并以退出码报告结果**（0 成功，非 0 失败）：

```bash
# 方式一：run（推荐，直接拿到退出码）
docker compose build verify
APP_PORT=18080 docker compose run --rm verify

# 方式二：up 并在 verify 退出时一并停止
docker compose up --build --abort-on-container-exit --exit-code-from verify verify
```

## API

`POST /api/audit`

```json
{
  "records": [
    {"time": "2026-09-29T08:00:00Z", "box_temp": 2.0,
     "ambient_temp": 30.0, "lid": "closed"}
  ],
  "params": {
    "tau_closed": 600, "tau_open": 120,
    "max_box_temp": 8.0, "max_exposure": 30
  }
}
```

约束：4–30 条记录；时间严格递增；τ 与允许暴露时长为正。
非法请求返回 `422 {"status":"invalid","errors":[...]}`。

响应包含：`status`（pass/reject）、`verdict`（放行/拒收）、连续曲线采样、
各段解析极值与热惯性参数、`exposure_intervals`（每个连续超温区间的起止时刻与
持续时间）、`total_exposure`、`first_failure`（最早失效时刻及所在段）、
读数−模型偏差与文本证据。
