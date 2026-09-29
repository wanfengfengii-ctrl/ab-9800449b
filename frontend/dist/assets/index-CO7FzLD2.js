(function(){const t=document.createElement("link").relList;if(t&&t.supports&&t.supports("modulepreload"))return;for(const s of document.querySelectorAll('link[rel="modulepreload"]'))i(s);new MutationObserver(s=>{for(const l of s)if(l.type==="childList")for(const f of l.addedNodes)f.tagName==="LINK"&&f.rel==="modulepreload"&&i(f)}).observe(document,{childList:!0,subtree:!0});function n(s){const l={};return s.integrity&&(l.integrity=s.integrity),s.referrerPolicy&&(l.referrerPolicy=s.referrerPolicy),s.crossOrigin==="use-credentials"?l.credentials="include":s.crossOrigin==="anonymous"?l.credentials="omit":l.credentials="same-origin",l}function i(s){if(s.ep)return;s.ep=!0;const l=n(s);fetch(s.href,l)}})();const g={reject:{label:"拒收演示：读数全合格、途中升温",records:[{time:0,box_temp:4,ambient_temp:25,lid_open:!1},{time:60,box_temp:7.806654,ambient_temp:25,lid_open:!1},{time:1560,box_temp:7.254505,ambient_temp:3,lid_open:!1},{time:2460,box_temp:3.211819,ambient_temp:3,lid_open:!1},{time:3360,box_temp:3.010546,ambient_temp:3,lid_open:!1}],parameters:{tau_closed:300,tau_open:90,box_temp_limit:8,exposure_limit_seconds:600}},pass:{label:"放行演示：全程低温",records:[{time:0,box_temp:4,ambient_temp:3,lid_open:!1},{time:300,box_temp:3.551819,ambient_temp:3.5,lid_open:!1},{time:600,box_temp:3.703003,ambient_temp:4,lid_open:!1},{time:900,box_temp:3.817165,ambient_temp:3.8,lid_open:!1},{time:1200,box_temp:3.585587,ambient_temp:3.2,lid_open:!1},{time:1500,box_temp:3.268274,ambient_temp:3,lid_open:!1},{time:1800,box_temp:3.025116,ambient_temp:2.8,lid_open:!1},{time:2100,box_temp:2.772452,ambient_temp:2.5,lid_open:!1},{time:2400,box_temp:2.41629,ambient_temp:2,lid_open:!1}],parameters:{tau_closed:300,tau_open:90,box_temp_limit:8,exposure_limit_seconds:600}},short:{label:"短时超温：有暴露但不足时长",records:[{time:0,box_temp:4,ambient_temp:4,lid_open:!1},{time:600,box_temp:15.92102,ambient_temp:25,lid_open:!0},{time:1200,box_temp:23.771294,ambient_temp:25,lid_open:!1},{time:1800,box_temp:12.912692,ambient_temp:4,lid_open:!1}],parameters:{tau_closed:300,tau_open:90,box_temp_limit:8,exposure_limit_seconds:3600}}},d={records:structuredClone(g.reject.records),parameters:{...g.reject.parameters},result:null,error:null,loading:!1},P=document.getElementById("app");function $(e){const t=Math.round(e),n=Math.floor(t/3600),i=Math.floor(t%3600/60),s=t%60;return n>0?`${n}:${String(i).padStart(2,"0")}:${String(s).padStart(2,"0")}`:`${i}:${String(s).padStart(2,"0")}`}function y(e){return Number(e).toFixed(2)}function p(e){const t=Number(e),n=Math.floor(t/3600),i=Math.floor(t%3600/60),s=Math.round(t%60);return n>0?`${n} 小时 ${i} 分 ${s} 秒`:i>0?`${i} 分 ${s} 秒`:`${s} 秒`}function W(){const e=d.parameters;return`
  <div class="panel">
    <h2>① 运输记录（按时间严格递增，4–30 条）</h2>
    <div style="max-height:340px;overflow:auto">
    <table class="records">
      <thead><tr>
        <th style="width:26%"># 时间(秒或ISO)</th><th>箱温℃</th><th>环境温℃</th><th>箱盖开启</th><th></th>
      </tr></thead>
      <tbody>
        ${d.records.map((t,n)=>`
        <tr>
          <td><input data-k="time" data-i="${n}" value="${t.time}" /></td>
          <td><input data-k="box_temp" data-i="${n}" type="number" step="0.01" value="${t.box_temp}" /></td>
          <td><input data-k="ambient_temp" data-i="${n}" type="number" step="0.01" value="${t.ambient_temp}" /></td>
          <td style="text-align:center"><input data-k="lid_open" data-i="${n}" type="checkbox" ${t.lid_open?"checked":""} /></td>
          <td><button class="row-btn" data-del="${n}" title="删除该行">✕</button></td>
        </tr>`).join("")}
      </tbody>
    </table>
    </div>
    <div class="count-note">当前 ${d.records.length} 条（须 4–30 条）</div>

    <h2 style="margin-top:18px">② 模型参数与保存要求</h2>
    <div class="params-grid">
      <label class="field"><span>箱盖关闭热惯性 τ关闭（秒）</span>
        <input id="tau_closed" type="number" step="any" value="${e.tau_closed}" /></label>
      <label class="field"><span>箱盖开启热惯性 τ开启（秒）</span>
        <input id="tau_open" type="number" step="any" value="${e.tau_open}" /></label>
      <label class="field"><span>允许箱温（℃）</span>
        <input id="box_temp_limit" type="number" step="0.1" value="${e.box_temp_limit}" /></label>
      <label class="field"><span>允许连续暴露时长（秒）</span>
        <input id="exposure_limit_seconds" type="number" step="any" value="${e.exposure_limit_seconds}" /></label>
    </div>
    <div class="hint">约定：相邻记录之间环境温度按<b>线性变化</b>；箱温按一阶模型
      <code>dT/dt=(T_env−T)/τ</code> 逐段闭式求解；箱盖状态在记录时刻切换 τ。</div>

    <div class="btn-row">
      <button class="action" id="submit">提交审计</button>
      <button class="ghost" id="addRow">+ 增加记录</button>
    </div>
    <div class="btn-row">
      <button class="ghost" data-preset="reject">拒收演示数据</button>
      <button class="ghost" data-preset="pass">放行演示数据</button>
      <button class="ghost" data-preset="short">短时超温数据</button>
    </div>
    ${d.error?`<div class="error-box">${d.error}</div>`:""}
  </div>`}function M(){const e=d.records.map((n,i)=>{const s=document.querySelector(`[data-k="time"][data-i="${i}"]`).value.trim();return{time:/^-?\d+(\.\d+)?$/.test(s)?Number(s):s,box_temp:Number(document.querySelector(`[data-k="box_temp"][data-i="${i}"]`).value),ambient_temp:Number(document.querySelector(`[data-k="ambient_temp"][data-i="${i}"]`).value),lid_open:document.querySelector(`[data-k="lid_open"][data-i="${i}"]`).checked}}),t={tau_closed:Number(document.getElementById("tau_closed").value),tau_open:Number(document.getElementById("tau_open").value),box_temp_limit:Number(document.getElementById("box_temp_limit").value),exposure_limit_seconds:Number(document.getElementById("exposure_limit_seconds").value)};return{recs:e,params:t}}async function z(){const{recs:e,params:t}=M();d.records=e,d.parameters=t,d.loading=!0,d.error=null,d.result=null,_();try{const i=await(await fetch("/api/audit",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({records:e,parameters:t})})).json();i.status==="invalid"?d.error=i.errors.map(s=>`<div><code>${s.code}</code> ${s.message}${s.field?`（字段：${s.field}）`:""}</div>`).join(""):d.result=i}catch(n){d.error=`无法连接审计 API：${n.message}`}finally{d.loading=!1,_()}}function A(e){if(d.loading)return'<div class="verdict"><div class="badge">…</div><div class="sub">正在连续求解各段箱温…</div></div>';if(d.error)return`<div class="verdict invalid"><div class="badge">数据不合法</div>
      <div class="sub">服务端拒绝裁决，请依据右侧字段提示修正后重新提交。</div></div>`;if(!e)return`<div class="verdict"><div class="badge" style="background:var(--panel-2);color:var(--muted)">待提交</div>
      <div class="sub">填写记录与参数后点击「提交审计」，服务端将以一阶热响应模型逐段解析求解。</div></div>`;if(e.status==="pass")return`<div class="verdict pass"><div class="badge">放 行</div>
      <div class="sub">箱温连续曲线全程未形成达到 <strong>${p(e.parameters.exposure_limit_seconds)}</strong> 的连续超温区间。<br/>
      累计超温时长 <strong>${p(e.total_exceedance_seconds)}</strong>，
      连续超温区间 <strong>${e.exceedance_intervals.length}</strong> 个。</div></div>`;const t=e.first_failure_time;return`<div class="verdict reject"><div class="badge">拒 收</div>
    <div class="sub">存在连续超温达到 <strong>${p(e.parameters.exposure_limit_seconds)}</strong> 的区间，油样自 <strong>${t.time}</strong>
    （距首条记录 ${$(t.elapsed_seconds)}）起失效。<br/>
    共 ${e.exceedance_intervals.length} 个连续超温区间，累计超温 ${p(e.total_exceedance_seconds)}。</div></div>`}function C(e){if(!e||e.status!=="reject")return"";const t=e.first_failure_time,n=e.exceedance_intervals[t.interval_index];return`<div class="failure-card">
    <h3>最早失效时刻证据</h3>
    <div class="kv">
      超温区间起点：<b>${n.start_time}</b>（${$(n.elapsed_start_seconds)}）<br/>
      连续超温区间终点：<b>${n.end_time}</b>（${$(n.elapsed_end_seconds)}）<br/>
      该区间持续：<b>${p(n.duration_seconds)}</b> ≥ 允许 ${p(e.parameters.exposure_limit_seconds)}<br/>
      最早失效时刻 = 区间起点 + 允许暴露时长 = <b>${t.time}</b>
      （距首条记录 ${$(t.elapsed_seconds)}）
    </div></div>`}function H(e){const c=e.curve,k=c[c.length-1].elapsed_seconds,w=c.flatMap(a=>[a.box_temp,a.ambient_temp]).concat([e.parameters.box_temp_limit]);let u=Math.min(...w),x=Math.max(...w);const T=Math.max(1,(x-u)*.08);u-=T,x+=T;const r=a=>56+a/k*846,m=a=>336-(a-u)/(x-u)*318,L=[];let b=null;for(let a=0;a<c.length;a++)if(c[a].lid_open&&b===null&&(b=c[a].elapsed_seconds),(!c[a].lid_open||a===c.length-1)&&b!==null){const o=c[a].lid_open?c[a].elapsed_seconds:c[a-1].elapsed_seconds;L.push([b,o]),b=null}const j=a=>c.map((o,q)=>`${q===0?"M":"L"}${r(o.elapsed_seconds).toFixed(2)},${m(o[a]).toFixed(2)}`).join(" "),R=e.exceedance_intervals.map(a=>`<rect x="${r(a.elapsed_start_seconds)}" y="18" width="${r(a.elapsed_end_seconds)-r(a.elapsed_start_seconds)}" height="318" fill="#ff5d5d" fill-opacity="0.16" />`).join(""),F=L.map(([a,o])=>`<rect x="${r(a)}" y="18" width="${r(o)-r(a)}" height="318" fill="#f5a623" fill-opacity="0.10" />`).join(""),S=[],E=5;for(let a=0;a<=E;a++){const o=u+(x-u)*a/E;S.push(`<line x1="56" y1="${m(o)}" x2="902" y2="${m(o)}" stroke="#22303f" stroke-width="1"/>
      <text x="48" y="${m(o)+4}" fill="#93a4b5" font-size="11" text-anchor="end">${o.toFixed(1)}</text>`)}const N=[],I=6;for(let a=0;a<=I;a++){const o=k*a/I;N.push(`<line x1="${r(o)}" y1="336" x2="${r(o)}" y2="341" stroke="#93a4b5"/>
      <text x="${r(o)}" y="356" fill="#93a4b5" font-size="11" text-anchor="middle">${$(o)}</text>`)}const v=e.parameters.box_temp_limit,B=e.records_echo.map(a=>`<circle cx="${r(a.elapsed_seconds)}" cy="${m(a.box_temp)}" r="4.5" fill="#0f1720" stroke="#e6edf3" stroke-width="2">
          <title>记录 ${a.time}：箱温 ${y(a.box_temp)}℃，环境 ${y(a.ambient_temp)}℃，箱盖${a.lid_open?"开启":"关闭"}</title></circle>`).join(""),h=e.first_failure_time,O=h?`<line x1="${r(h.elapsed_seconds)}" y1="18" x2="${r(h.elapsed_seconds)}" y2="336"
        stroke="#ff5d5d" stroke-width="1.6" stroke-dasharray="6 4"/>
      <text x="${r(h.elapsed_seconds)}" y="30" fill="#ff5d5d" font-size="11" text-anchor="middle">最早失效 ${h.time}</text>`:"";return`<svg viewBox="0 0 920 380" role="img" aria-label="箱温连续曲线">
    ${F}${R}
    ${S.join("")}${N.join("")}
    <line x1="56" y1="${m(v)}" x2="902" y2="${m(v)}" stroke="#f5a623" stroke-width="1.6" stroke-dasharray="8 4"/>
    <text x="902" y="${m(v)-5}" fill="#f5a623" font-size="11" text-anchor="end">允许箱温 ${v}℃</text>
    <path d="${j("ambient_temp")}" fill="none" stroke="#7d8fa1" stroke-width="1.6" stroke-dasharray="3 3"/>
    <path d="${j("box_temp")}" fill="none" stroke="#4da3ff" stroke-width="2.4"/>
    ${B}${O}
    <line x1="56" y1="336" x2="902" y2="336" stroke="#93a4b5"/>
    <line x1="56" y1="18" x2="56" y2="336" stroke="#93a4b5"/>
    <text x="56" y="374" fill="#93a4b5" font-size="11">经过时间（时:分:秒） →</text>
  </svg>
  <div class="legend">
    <span class="swatch"><i style="background:#4da3ff"></i>箱温连续曲线（闭式解析解）</span>
    <span class="swatch"><i style="background:#7d8fa1"></i>环境温（段间线性）</span>
    <span class="swatch"><i style="background:#f5a623"></i>允许箱温</span>
    <span class="swatch"><i style="background:var(--hot);border:1px solid #ff5d5d"></i>连续超温区间</span>
    <span class="swatch"><i style="background:var(--lid);border:1px solid #f5a623"></i>箱盖开启时段</span>
    <span class="swatch">◦ 空心圆点为录入的箱温读数</span>
  </div>`}function D(e){return e.exceedance_intervals.length?`<table class="data">
    <thead><tr><th>#</th><th>起始时刻</th><th>结束时刻</th><th class="num">持续时长(秒)</th><th>是否达到暴露限额</th></tr></thead>
    <tbody>${e.exceedance_intervals.map(t=>`<tr>
        <td>${t.index+1}</td><td>${t.start_time}</td><td>${t.end_time}</td>
        <td class="num">${p(t.duration_seconds)}（${t.duration_seconds.toFixed(1)}s）</td>
        <td><span class="tag ${t.reaches_limit?"yes":"no"}">${t.reaches_limit?"达到 → 拒收":"未达到"}</span></td>
      </tr>`).join("")}</tbody></table>`:'<div class="hint">无任何箱温超过允许值的连续区间。</div>'}function J(e){return`<table class="data">
    <thead><tr>
      <th>#</th><th>段起→止(s)</th><th>箱盖</th><th class="num">τ(秒)</th>
      <th class="num">段内最高℃</th><th>最高位置</th>
      <th class="num">段内最低℃</th><th>穿越(相对秒)</th>
    </tr></thead>
    <tbody>${e.segments.map(t=>{const n=t.crossings.map(i=>`<span class="${i.direction}">${i.direction==="up"?"↑上穿":"↓下穿"}@${i.elapsed_seconds.toFixed(1)}</span>`).join("，");return`<tr>
        <td>${t.index+1}</td>
        <td>${t.elapsed_start_seconds} → ${t.elapsed_end_seconds}<br/><span class="hint" style="margin:0">${t.duration_seconds.toFixed(0)}s</span></td>
        <td><span class="tag ${t.lid_open?"open":"closed"}">${t.lid_open?"开启":"关闭"}</span></td>
        <td class="num">${t.tau_seconds}</td>
        <td class="num">${y(t.max_temp.value)}</td>
        <td>${t.max_temp.kind==="interior"?"段内 "+t.max_temp.elapsed_seconds.toFixed(1)+"s":t.max_temp.kind==="start"?"段起点":"段终点"}</td>
        <td class="num">${y(t.min_temp.value)}</td>
        <td>${n||"—"}</td>
      </tr>`}).join("")}</tbody></table>`}function K(e){return e?`
  <div class="model-note">
    求解方式：<code>${e.model.equation}</code>；${e.model.ambient_assumption}；${e.model.solver}。<br/>
    每段以记录时刻实测箱温为初值锚定（段末模型值与下一读数偏差见审计数据），
    ${e.model.tau_switching}。${e.model.exceedance_rule}。
  </div>
  ${C(e)}
  <div class="chart-wrap">${H(e)}</div>

  <div class="section-title">累计连续超温区间（跨记录取并集）</div>
  ${D(e)}

  <div class="section-title">各段解析极值与阈值穿越</div>
  ${J(e)}`:""}function _(){P.innerHTML=`
  <header>
    <h1>海上平台油样运输箱 · 温控审计</h1>
    <p>一阶热响应模型逐段闭式解析 · 阈值穿越精确定位 · 跨记录连续暴露累计 —— 拒绝"只看离散读数"的误放行</p>
  </header>
  <div class="layout">
    ${W()}
    <div>
      ${A(d.result)}
      ${d.result?K(d.result):'<div class="chart-wrap"><div class="hint">提交后在此展示箱温连续曲线、各段解析极值、累计暴露区间与最早失效时刻。</div></div>'}
    </div>
  </div>`,V()}function V(){var e,t;(e=document.getElementById("submit"))==null||e.addEventListener("click",z),(t=document.getElementById("addRow"))==null||t.addEventListener("click",()=>{const{recs:n,params:i}=M();if(n.length>=30)return;const s=n[n.length-1];n.push({time:typeof s.time=="number"?s.time+600:s.time,box_temp:s.box_temp,ambient_temp:s.ambient_temp,lid_open:!1}),d.records=n,d.parameters=i,_()}),document.querySelectorAll("[data-del]").forEach(n=>n.addEventListener("click",()=>{const{recs:i,params:s}=M();i.splice(Number(n.dataset.del),1),d.records=i,d.parameters=s,_()})),document.querySelectorAll("[data-preset]").forEach(n=>{n.addEventListener("click",()=>{const i=g[n.dataset.preset];d.records=structuredClone(i.records),d.parameters={...i.parameters},d.result=null,d.error=null,_()})})}_();
