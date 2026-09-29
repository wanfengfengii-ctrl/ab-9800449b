# 海上平台油样运输箱 · 温控审计（全栈）

质控员在把油样从海上平台转运至岸基实验室前，录入运输箱在采样点之间的
**箱温 / 环境温 / 箱盖状态** 记录（按时间严格递增，4–30 条），以及
**箱体热惯性、允许箱温、允许连续暴露时长**，并约定 **环境温度在相邻记录间线性变化**。
服务端以**同一阶热响应模型逐段闭式解析求解**箱温连续曲线，精确裁决：

- 不能因为每个上传读数都没超限，就忽略**两次记录之间升温**造成的样品失效；
- 准确处理**阈值穿越**、**箱盖开启时热惯性切换**、**跨记录延续**的连续暴露时长；
- 不按离散采样点、也不按欧拉/龙格-库塔等数值步进近似裁决。

提交后前端展示：**放行 / 拒收 / 数据不合法**结论、箱温连续曲线、各段解析极值、
累计连续超温区间，以及**最早使油样失效的时刻**。

---

## 1. 数学模型与裁决口径

在每条相邻记录构成的区间 `[t_i, t_{i+1}]` 内，令 `s = t − t_i`、`Δ = t_{i+1} − t_i`，
环境温按约定线性变化 `T_env(s) = a + b·s`，则

```
dT/dt = (T_env(t) − T(t)) / τ
```

的**闭式解析解**为

```
T(s) = a + b·(s − τ) + (T_i − a + b·τ)·exp(−s/τ)
T'(s) = b − (T_i − a + b·τ)/τ · exp(−s/τ)
```

- `T_i` 取该段起点记录时刻的**实测箱温**（每段锚定，段内由闭式解推进；
  返回的 `model_record_gap` 给出段末模型值与下一读数的偏差作为证据）；
- `τ` 取段起点箱盖状态：开启 `τ_open`、关闭 `τ_closed`，在记录时刻切换；
- **解析极值**：`T'(s)=0` 至多一个解析驻点 `s* = τ·ln((T_i−a+bτ)/(bτ))`，
  用它把每段切成单调子区间；
- **阈值穿越**：单调子区间上仅需比较端点，异号时二分求根（容差 `1e-12 s`）；
- **连续超温区间**：严格超限 `T > T_limit` 的子区间在全局取并集（跨记录相接即合并，
  只有真正跌回阈值之下的间隙才打断连续性）；
- **裁决**：任一连续超温区间持续时间 `≥ 允许连续暴露时长` 即**拒收**；
  **最早失效时刻 = 该区间起点 + 允许连续暴露时长**。

> 生产裁决路径不含任何数值积分；仓库中的 RK4 参考实现仅用于测试交叉验证。

### 关键业务场景（拒收演示数据）

录入读数全部低于 8℃：`4.0 / 7.81 / 7.25 / 3.21 / 3.01 ℃`，
但第 2 段环境温由 25℃ 线性降到 3℃，箱温先追热冲高到**段内闭式极大值约 18℃**
（位于 60s 与 1560s 两条记录之间），连续超温约 1444s。
只看离散读数会误放行，解析解判**拒收**并给出上穿/下穿时刻与最早失效时刻。

---

## 2. 目录结构

```
.
├── backend/
│   ├── app/
│   │   ├── thermal.py        # 一阶模型闭式求解 + 阈值穿越 + 暴露区间裁决
│   │   └── main.py           # FastAPI：/api/audit、/api/audit/schema、/healthz
│   ├── tests/                # pytest：引擎解析解/RK4 交叉验证 + API 测试
│   └── requirements.txt
├── frontend/
│   ├── src/main.js           # 录入表单、真实 API 调用、SVG 连续曲线、证据表格
│   ├── src/styles.css
│   └── vite.config.js        # 开发态代理 /api → 后端
├── scripts/
│   ├── verify.sh             # 一次性校验：pytest → 前端构建 → API 冒烟
│   ├── smoke.py              # 温控审计 API 冒烟（退出码报告结果）
│   └── healthcheck.py        # 容器健康检查
├── Dockerfile                # 多阶段：前端构建 → 应用镜像 → verify 镜像
└── docker-compose.yml        # app（健康检查）+ verify（一次性）
```

## 3. HTTP API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/audit` | 提交记录与参数，返回裁决与全部证据 |
| `GET` | `/api/audit/schema` | 入参字段约定 |
| `GET` | `/healthz` | 健康检查 |

请求体：

```json
{
  "records": [
    {"time": 0, "box_temp": 4.0, "ambient_temp": 25.0, "lid_open": false}
  ],
  "parameters": {
    "tau_closed": 300,
    "tau_open": 90,
    "box_temp_limit": 8.0,
    "exposure_limit_seconds": 600
  }
}
```

- `time`：全表统一使用 **ISO 8601 字符串**（朴素时间按 UTC 解释，回显统一 UTC）
  或**数值纪元秒**，不得混用；必须严格递增；记录数 4–30。
- 成功返回 `200`，`status` 为 `pass`（放行）或 `reject`（拒收）。
- 数据不合法返回 `422`：`{"status":"invalid","verdict":"数据不合法","errors":[...]}`；
  非法 JSON / 非对象请求体返回 `400`。

拒收响应的核心证据字段：

```json
{
  "status": "reject",
  "exceedance_intervals": [
    {"start_time": 63.4, "end_time": 1507.3,
     "duration_seconds": 1443.9, "reaches_limit": true}
  ],
  "first_failure_time": {"time": 663.4, "elapsed_seconds": 663.4, "interval_index": 0},
  "segments": [{"max_temp": {...}, "min_temp": {...}, "crossings": [{"direction":"up", ...}]}],
  "curve": [ {"elapsed_seconds": ..., "box_temp": ..., "ambient_temp": ...} ]
}
```

---

## 4. 本地开发（不使用 Docker）

```bash
# 后端
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000     # http://localhost:8000

# 前端（另开终端，开发态热更新，/api 代理到 8000）
cd frontend
npm install
npm run dev                                             # http://localhost:5173
```

运行测试：

```bash
cd backend && . .venv/bin/activate && python -m pytest
```

## 5. Docker / Docker Compose

应用镜像为多阶段构建，**生产模式由 FastAPI 直接托管前端静态资源**。

```bash
# 端口由宿主机环境变量 APP_PORT 配置（默认 8000）
docker compose up -d --build app
# 自定义端口：
APP_PORT=9090 docker compose up -d --build app          # http://localhost:9090
```

`app` 服务带 `HEALTHCHECK`（按 `APP_PORT` 轮询 `/healthz`）。

### 一次性 verify 服务

`verify` 服务通过 `depends_on: condition: service_healthy` **在 app 健康后才启动**，
顺序执行 **① 后端代码测试 ② 前端生产构建 ③ 温控审计 API 冒烟**，随后**自行退出**，
以容器退出码报告结果（`0` 全部通过，非零表示失败）：

```bash
docker compose build
docker compose run --rm verify        # 观察输出与退出码
docker compose up --build             # app 健康后 verify 自动运行一次后退出
docker inspect <verify容器> --format '{{.State.ExitCode}}'
```

---

## 6. 前端页面

- 左侧录入 4–30 条记录与四个模型参数，内置三套预设：
  **拒收（读数全合格、途中升温）/ 放行 / 短时超温不足时长**；
- 右侧展示结论徽章、最早失效时刻证据卡；
- SVG 连续曲线图：箱温闭式曲线、环境温线性线、允许箱温阈值、
  超温区间红色遮罩、箱盖开启时段底色、录入读数空心点、最早失效竖线；
- 表格列出**累计连续超温区间**（起止时刻、持续时长、是否达到限额）
  与**各段解析极值 / 阈值穿越方向与时刻**。
