import "./style.css";

const state = {
  records: [],
  result: null,
  errors: null,
  busy: false,
};

// ---------------------------------------------------------------------------
// 示例数据：读数本身全在阈值下，但连续曲线途中超温 => 拒收
// -------------------------------------------------------------------------

function isoAdd(baseIso, seconds) {
  const t = new Date(baseIso);
  t.setUTCSeconds(t.getUTCSeconds() + seconds);
  return t.toISOString();
}

function toLocalInput(iso) {
  // datetime-local 按 UTC 解释录入值
  return iso.slice(0, 19);
}

const SAMPLE_REJECT = {
  params: {
    tau_closed: 600,
    tau_open: 120,
    max_box_temp: 8,
    max_exposure: 30,
  },
  records: [
    { time: "2026-09-29T08:00:00Z", box_temp: 2.0, ambient_temp: 30, lid: "closed" },
    { time: "2026-09-29T08:01:40Z", box_temp: 4.2, ambient_temp: 30, lid: "closed" },
    { time: "2026-09-29T08:03:20Z", box_temp: 6.3, ambient_temp: 30, lid: "closed" },
    { time: "2026-09-29T08:05:00Z", box_temp: 7.4, ambient_temp: 28, lid: "open" },
    { time: "2026-09-29T08:06:40Z", box_temp: 7.9, ambient_temp: 25, lid: "closed" },
    { time: "2026-09-29T08:08:20Z", box_temp: 7.2, ambient_temp: 5, lid: "closed" },
  ],
};

const SAMPLE_PASS = {
  params: {
    tau_closed: 900,
    tau_open: 180,
    max_box_temp: 8,
    max_exposure: 120,
  },
  records: [
    { time: "2026-09-29T08:00:00Z", box_temp: 3.0, ambient_temp: 4, lid: "closed" },
    { time: "2026-09-29T08:10:00Z", box_temp: 3.5, ambient_temp: 6, lid: "closed" },
    { time: "2026-09-29T08:20:00Z", box_temp: 4.2, ambient_temp: 7, lid: "closed" },
    { time: "2026-09-29T08:30:00Z", box_temp: 4.8, ambient_temp: 6, lid: "closed" },
    { time: "2026-09-29T08:40:00Z", box_temp: 4.1, ambient_temp: 5, lid: "closed" },
  ],
};

// ---------------------------------------------------------------------------
// 渲染
// ---------------------------------------------------------------------------

const app = document.getElementById("app");

function render() {
  app.innerHTML = `
    <header>
      <h1>油样运输箱温控审计</h1>
      <p class="sub">
        一阶热响应模型逐段解析求解 · 按连续曲线而非离散读数裁决 ·
        4–30 条按时间严格递增的记录
      </p>
    </header>

    <section class="card">
      <div class="card-head">
        <h2>1. 模型参数与判定标准</h2>
        <div class="actions">
          <button id="load-reject" type="button">示例：途中升温（拒收）</button>
          <button id="load-pass" type="button">示例：冷链稳定（放行）</button>
        </div>
      </div>
      <div class="params-grid">
        <label>箱盖关闭热惯性 τ<sub>闭</sub>（秒）
          <input id="tau_closed" type="number" min="1" step="1" />
        </label>
        <label>箱盖开启热惯性 τ<sub>开</sub>（秒）
          <input id="tau_open" type="number" min="1" step="1" />
        </label>
        <label>允许箱温上限（℃）
          <input id="max_box_temp" type="number" step="0.1" />
        </label>
        <label>允许连续暴露时长（秒）
          <input id="max_exposure" type="number" min="1" step="1" />
        </label>
      </div>
    </section>

    <section class="card">
      <div class="card-head">
        <h2>2. 运输记录</h2>
        <div class="actions">
          <button id="add-row" type="button">＋ 增加记录</button>
        </div>
      </div>
      <div class="table-wrap">
        <table id="records-table">
          <thead>
            <tr>
              <th>#</th><th>时间 (UTC)</th><th>箱温读数 (℃)</th>
              <th>环境温 (℃)</th><th>箱盖</th><th></th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
      </div>
      <p class="hint">
        说明：箱温读数仅首条作为模型初值，其余读数用于与连续模型曲线对照；
        相邻记录间环境温度按线性变化，段内箱温以解析解连续推进。
      </p>
      <div class="submit-row">
        <button id="submit" class="primary" type="button" ${state.busy ? "disabled" : ""}>
          ${state.busy ? "审计中…" : "提交审计"}
        </button>
        <span id="row-count" class="hint"></span>
      </div>
    </section>

    ${state.errors ? renderErrors(state.errors) : ""}
    ${state.result ? renderResult(state.result) : ""}
  `;

  bindInputs();
}

function renderErrors(errors) {
  return `
    <section class="card invalid">
      <h2>数据不合法</h2>
      <ul class="error-list">
        ${errors.map((e) => `<li>${escapeHtml(e)}</li>`).join("")}
      </ul>
    </section>`;
}

function renderResult(d) {
  const reject = d.status === "reject";
  return `
    <section class="card verdict ${d.status}">
      <div class="verdict-main">
        <span class="badge">${reject ? "⛔ 拒收" : "✅ 放行"}</span>
        <div>
          <p>阈值 ${fmtT(d.threshold)} ℃ · 允许连续暴露 ${fmtDur(d.max_exposure)}</p>
          <p class="hint">累计超温 ${fmtDur(d.total_exposure)} ·
            超温区间 ${d.exposure_intervals.length} 个</p>
        </div>
      </div>
      ${
        d.first_failure
          ? `<p class="failure">最早使油样失效时刻：<strong>${fmtTime(
              d.first_failure.time
            )}</strong>（第 ${d.first_failure.segment_index + 1} 段内）</p>`
          : `<p class="ok-note">未出现超过允许连续暴露时长的超温区间。</p>`
      }
      <ul class="evidence">
        ${d.evidence.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}
      </ul>
    </section>

    <section class="card">
      <h2>箱温连续曲线</h2>
      ${renderChart(d)}
      <div class="legend">
        <span><i class="sw box"></i>箱温连续模型</span>
        <span><i class="sw amb"></i>环境温（线性）</span>
        <span><i class="sw th"></i>允许箱温</span>
        <span><i class="sw ex"></i>超温区间</span>
        <span><i class="sw fail"></i>首个失效时刻</span>
        <span><i class="sw dot"></i>上传读数</span>
      </div>
    </section>

    <section class="card">
      <h2>连续超温区间（累计暴露）</h2>
      ${
        d.exposure_intervals.length === 0
          ? `<p class="hint">无超温区间。</p>`
          : `<div class="table-wrap"><table>
              <thead><tr><th>#</th><th>起始时刻</th><th>结束时刻</th>
              <th>持续时长</th><th>裁决</th></tr></thead>
              <tbody>
                ${d.exposure_intervals
                  .map(
                    (iv, i) => `<tr class="${iv.duration > d.max_exposure ? "row-bad" : ""}">
                    <td>${i + 1}</td>
                    <td>${fmtTime(iv.start_time)}</td>
                    <td>${fmtTime(iv.end_time)}</td>
                    <td>${fmtDur(iv.duration)}</td>
                    <td>${iv.duration > d.max_exposure ? "超过允许暴露 → 失效" : "未超允许暴露"}</td>
                  </tr>`
                  )
                  .join("")}
              </tbody>
            </table></div>`
      }
    </section>

    <section class="card">
      <h2>各段解析极值与热惯性切换</h2>
      <div class="table-wrap"><table>
        <thead><tr>
          <th>段</th><th>起始</th><th>结束</th><th>时长</th><th>箱盖</th>
          <th>τ (秒)</th><th>箱温起</th><th>箱温止</th><th>段内极值</th>
        </tr></thead>
        <tbody>
          ${d.segments
            .map(
              (s) => `<tr class="${s.above_threshold.length ? "row-warn" : ""}">
              <td>${s.index + 1}</td>
              <td>${fmtTime(s.start_time)}</td>
              <td>${fmtTime(s.end_time)}</td>
              <td>${fmtDur(s.duration)}</td>
              <td>${s.lid === "open" ? "打开" : "关闭"}</td>
              <td>${fmtT(s.tau)}</td>
              <td>${fmtT(s.t_start)}</td>
              <td>${fmtT(s.t_end)}</td>
              <td>${
                s.extremum
                  ? `${s.extremum.kind === "max" ? "极大" : "极小"} ${fmtT(
                      s.extremum.value
                    )}℃ @ ${fmtTime(s.extremum.time)}`
                  : '<span class="hint">端点</span>'
              }</td>
            </tr>`
            )
            .join("")}
        </tbody>
      </table></div>
    </section>

    <section class="card">
      <h2>读数与模型对照（证据）</h2>
      <div class="table-wrap"><table>
        <thead><tr><th>#</th><th>时间</th><th>读数箱温</th>
        <th>连续模型箱温</th><th>偏差（读数−模型）</th></tr></thead>
        <tbody>
          ${d.reading_deviations
            .map(
              (r) => `<tr>
              <td>${r.index + 1}</td><td>${fmtTime(r.time)}</td>
              <td>${fmtT(r.recorded)}</td><td>${fmtT(r.modeled)}</td>
              <td class="${Math.abs(r.delta) > 0.5 ? "row-warn" : ""}">${
                r.index === 0 ? "—（初值）" : fmtSigned(r.delta)
              }</td>
            </tr>`
            )
            .join("")}
        </tbody>
      </table></div>
    </section>
  `;
}

// ---------------------------------------------------------------------------
// SVG 曲线图
// ---------------------------------------------------------------------------

function renderChart(d) {
  const W = 920;
  const H = 360;
  const M = { l: 56, r: 20, t: 20, b: 40 };
  const iw = W - M.l - M.r;
  const ih = H - M.t - M.b;

  const t0 = Date.parse(d.time_range.start) / 1000;
  const t1 = Date.parse(d.time_range.end) / 1000;
  const secs = (iso) => Date.parse(iso) / 1000 - t0;

  const temps = [
    ...d.curve.map((p) => p.box_temp),
    ...d.curve.map((p) => p.ambient_temp),
    d.threshold,
  ];
  const yMin = Math.min(...temps) - 1;
  const yMax = Math.max(...temps) + 1;

  const X = (iso) => M.l + (secs(iso) / (t1 - t0)) * iw;
  const Y = (v) => M.t + (1 - (v - yMin) / (yMax - yMin)) * ih;

  const path = (key) =>
    d.curve
      .map((p, i) => `${i === 0 ? "M" : "L"}${X(p.time).toFixed(1)},${Y(p[key]).toFixed(1)}`)
      .join(" ");

  // 网格与纵坐标
  const yTicks = [];
  const steps = 5;
  for (let i = 0; i <= steps; i++) {
    const v = yMin + ((yMax - yMin) * i) / steps;
    yTicks.push(v);
  }
  const grid = yTicks
    .map(
      (v) =>
        `<line x1="${M.l}" x2="${W - M.r}" y1="${Y(v)}" y2="${Y(v)}" class="grid"/>
         <text x="${M.l - 8}" y="${Y(v) + 4}" text-anchor="end" class="axis">${v.toFixed(1)}</text>`
    )
    .join("");

  // x 轴时间刻度
  const nTick = Math.min(6, d.records.length);
  const xTicks = d.records
    .filter((_, i) => i % Math.ceil(d.records.length / nTick) === 0)
    .map(
      (r) =>
        `<line x1="${X(r.time)}" x2="${X(r.time)}" y1="${H - M.b}" y2="${H - M.b + 5}" class="axis-line"/>
         <text x="${X(r.time)}" y="${H - M.b + 18}" text-anchor="middle" class="axis">${shortTime(
          r.time
        )}</text>`
    )
    .join("");

  // 超温阴影
  const shade = d.exposure_intervals
    .map(
      (iv) =>
        `<rect x="${X(iv.start_time)}" y="${M.t}" width="${Math.max(
          0,
          X(iv.end_time) - X(iv.start_time)
        )}" height="${ih}" class="exposure"/>`
    )
    .join("");

  // 读数列
  const lidOpen = new Set(d.records.filter((r) => r.lid === "open").map((r) => r.time));
  const dots = d.records
    .map(
      (r) =>
        `<circle cx="${X(r.time)}" cy="${Y(r.box_temp)}" r="3.5" class="dot ${
          lidOpen.has(r.time) ? "open" : ""
        }"/>`
    )
    .join("");

  const failLine = d.first_failure
    ? `<line x1="${X(d.first_failure.time)}" x2="${X(d.first_failure.time)}"
         y1="${M.t}" y2="${H - M.b}" class="fail-line"/>
       <circle cx="${X(d.first_failure.time)}" cy="${M.t + 4}" r="4" class="fail-dot"/>
       <text x="${X(d.first_failure.time)}" y="${M.t + 2}" text-anchor="middle" class="fail-label">失效</text>`
    : "";

  return `
    <svg viewBox="0 0 ${W} ${H}" class="chart" role="img">
      ${grid}${xTicks}${shade}
      <line x1="${M.l}" x2="${W - M.r}" y1="${Y(d.threshold)}" y2="${Y(d.threshold)}" class="threshold"/>
      <path d="${path("ambient_temp")}" class="ambient-line" fill="none"/>
      <path d="${path("box_temp")}" class="box-line" fill="none"/>
      ${dots}${failLine}
    </svg>`;
}

// ---------------------------------------------------------------------------
// 交互
// ---------------------------------------------------------------------------

function bindInputs() {
  const p = state.params || SAMPLE_REJECT.params;
  state.params = p;
  for (const k of Object.keys(p)) {
    const el = document.getElementById(k);
    if (el) el.value = p[k];
    el?.addEventListener("change", () => {
      p[k] = parseFloat(el.value);
    });
  }

  const tbody = document.querySelector("#records-table tbody");
  syncRowCount();

  document.getElementById("add-row")?.addEventListener("click", () => {
    const last = state.records[state.records.length - 1];
    const nextTime = last
      ? isoAdd(last.time, 100)
      : "2026-09-29T08:00:00.000Z";
    state.records.push({
      time: nextTime,
      box_temp: 3,
      ambient_temp: 5,
      lid: "closed",
    });
    render();
  });

  document.getElementById("load-reject")?.addEventListener("click", () => {
    loadSample(SAMPLE_REJECT);
  });
  document.getElementById("load-pass")?.addEventListener("click", () => {
    loadSample(SAMPLE_PASS);
  });
  document.getElementById("submit")?.addEventListener("click", submitAudit);

  tbody.querySelectorAll("tr").forEach((tr) => {
    const idx = Number(tr.dataset.idx);
    tr.querySelector(".t-time")?.addEventListener("change", (e) => {
      const v = e.target.value;
      if (v) state.records[idx].time = new Date(v + "Z").toISOString();
    });
    tr.querySelector(".t-box")?.addEventListener("input", (e) => {
      state.records[idx].box_temp = parseFloat(e.target.value);
    });
    tr.querySelector(".t-amb")?.addEventListener("input", (e) => {
      state.records[idx].ambient_temp = parseFloat(e.target.value);
    });
    tr.querySelector(".t-lid")?.addEventListener("change", (e) => {
      state.records[idx].lid = e.target.value;
    });
    tr.querySelector(".t-del")?.addEventListener("click", () => {
      state.records.splice(idx, 1);
      render();
    });
  });
}

function syncRowCount() {
  const tbody = document.querySelector("#records-table tbody");
  tbody.innerHTML = state.records
    .map(
      (r, i) => `
      <tr data-idx="${i}">
        <td>${i + 1}</td>
        <td><input class="t-time" type="datetime-local" step="1" value="${toLocalInput(
          r.time
        )}"/></td>
        <td><input class="t-box" type="number" step="0.1" value="${r.box_temp}"/></td>
        <td><input class="t-amb" type="number" step="0.1" value="${r.ambient_temp}"/></td>
        <td><select class="t-lid">
          <option value="closed" ${r.lid === "closed" ? "selected" : ""}>关闭</option>
          <option value="open" ${r.lid === "open" ? "selected" : ""}>打开</option>
        </select></td>
        <td><button class="t-del link-danger" type="button">删除</button></td>
      </tr>`
    )
    .join("");
  const counter = document.getElementById("row-count");
  if (counter) {
    const n = state.records.length;
    counter.textContent = `${n} 条记录${n < 4 || n > 30 ? "（需 4–30 条）" : ""}`;
  }
}

// 在 render 重建 DOM 后由 bindInputs 填充表格行并绑定事件。

function loadSample(sample) {
  state.params = { ...sample.params };
  state.records = sample.records.map((r) => ({ ...r }));
  state.result = null;
  state.errors = null;
  render();
}

async function submitAudit() {
  state.errors = null;
  state.result = null;
  state.busy = true;
  render();
  try {
    const res = await fetch("/api/audit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ records: state.records, params: state.params }),
    });
    const body = await res.json();
    if (res.status === 422) {
      state.errors = body.errors || ["数据不合法"];
    } else if (!res.ok) {
      state.errors = [`服务异常：HTTP ${res.status}`];
    } else {
      state.result = body;
    }
  } catch (err) {
    state.errors = [`请求失败：${err.message}`];
  } finally {
    state.busy = false;
    render();
    if (state.result) {
      document.querySelector(".verdict")?.scrollIntoView({ behavior: "smooth" });
    }
  }
}

// ---------------------------------------------------------------------------
// 格式化
// ---------------------------------------------------------------------------

function fmtTime(iso) {
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(
    d.getUTCHours()
  )}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())} UTC`;
}

function shortTime(iso) {
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}`;
}

function fmtDur(sec) {
  if (sec == null) return "—";
  if (sec < 60) return `${sec.toFixed(1)} 秒`;
  const m = Math.floor(sec / 60);
  const s = sec - m * 60;
  return `${m} 分 ${s.toFixed(1)} 秒`;
}

function fmtT(v) {
  return Number(v).toFixed(2);
}

function fmtSigned(v) {
  const s = v >= 0 ? "+" : "";
  return `${s}${v.toFixed(2)} ℃`;
}

function escapeHtml(s) {
  return String(s).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

// ---------------------------------------------------------------------------
// 启动
// ---------------------------------------------------------------------------

loadSample(SAMPLE_REJECT);
