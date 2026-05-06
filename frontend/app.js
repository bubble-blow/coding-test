const STEPS = ["requirements", "solution", "architecture", "coding", "review", "delivery"];
let state = null;

async function api(path, method = "GET", body) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  return res.json();
}

function defaultInput(step) {
  const idx = STEPS.indexOf(step);
  if (idx <= 0) return "";
  const prev = STEPS[idx - 1];
  const selectedId = state?.selected?.[prev];
  if (!selectedId) return "";
  const v = (state?.steps?.[prev] || []).find(x => x.id === selectedId);
  return v?.content || "";
}

function stepTemplate(step) {
  const inputable = !["review", "delivery"].includes(step);
  const val = inputable ? defaultInput(step) : "";
  const codePaths = (step === "review") ? (state?.review_code_paths || []) : [];
  const deliveryPaths = (step === "delivery") ? (state?.delivery_code_paths || []) : [];
  return `<div class="panel-card" id="card-${step}"><h3>${step}</h3>
    ${inputable ? `<textarea class="input-textarea" id="in-${step}" placeholder="输入">${val}</textarea>` : `<div>${step === "review" ? `代码文件路径：<pre>${codePaths.join("\n") || "(暂无)"}</pre>` : (step === "delivery" ? `待交付代码路径：<pre>${deliveryPaths.join("\n") || "(暂无)"}</pre>` : "无输入框（显示代码路径）")}</div>`}
    <button class="action-btn" onclick="execute('${step}')">执行</button>
    <div class="version-list" id="out-${step}"></div>
  </div>`;
}

function render() {
  document.getElementById("pipeline").innerHTML = STEPS.map(stepTemplate).join("");
  for (const step of STEPS) renderStep(step);
  const inflight = state.in_flight_requests || [];
  document.getElementById("inflight").textContent = JSON.stringify(inflight, null, 2);
  const ul = document.getElementById("inflight_list");
  ul.innerHTML = inflight.length
    ? inflight.map(r => `<li>步骤: ${r.step}｜开始: ${r.started_at}</li>`).join("")
    : `<li>当前无进行中请求</li>`;
  document.getElementById("logs").textContent = JSON.stringify(state.llm_logs, null, 2);
  renderObservability();
}

function fmtMs(ms) {
  if (!ms) return "0 ms";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

function fmtRate(rate) {
  return `${Math.round((rate || 0) * 100)}%`;
}

function renderObservability() {
  const obs = state.observability || {};
  const totals = obs.totals || {};
  document.getElementById("metrics").innerHTML = [
    ["运行次数", totals.runs || 0],
    ["成功率", fmtRate(totals.success_rate)],
    ["平均耗时", fmtMs(totals.avg_duration_ms || 0)],
    ["Token 总量", totals.tokens || 0],
  ].map(([label, value]) => `<div class="metric-card"><span>${label}</span><strong>${value}</strong></div>`).join("");

  const byStep = obs.by_step || {};
  const rows = Object.keys(byStep).map(step => {
    const item = byStep[step];
    return `<tr>
      <td>${step}</td>
      <td>${item.runs}</td>
      <td>${fmtRate(item.success_rate)}</td>
      <td>${fmtMs(item.avg_duration_ms)}</td>
      <td>${item.tokens}</td>
    </tr>`;
  }).join("");
  document.getElementById("step_metrics").innerHTML = rows
    ? `<table><thead><tr><th>阶段</th><th>次数</th><th>成功率</th><th>平均耗时</th><th>Token</th></tr></thead><tbody>${rows}</tbody></table>`
    : `<div class="empty-text">暂无运行数据</div>`;

  const recent = (obs.recent_runs || []).slice().reverse();
  document.getElementById("recent_runs").innerHTML = recent.length
    ? `<table><thead><tr><th>阶段</th><th>模式</th><th>状态</th><th>耗时</th><th>版本</th><th>Token</th></tr></thead><tbody>${recent.map(r => `<tr>
      <td>${r.step}</td>
      <td>${r.mode || "manual"}</td>
      <td>${r.status}</td>
      <td>${fmtMs(r.duration_ms)}</td>
      <td>${r.version_id || "-"}</td>
      <td>${r.usage?.total_tokens || 0}</td>
    </tr>`).join("")}</tbody></table>`
    : `<div class="empty-text">暂无运行记录</div>`;
}

function renderStep(step) {
  const box = document.getElementById(`out-${step}`);
  const list = state.steps[step] || [];
  const buildDebugPreviewUrl = (previewUrl) => {
    try {
      const u = new URL(previewUrl, window.location.origin);
      u.searchParams.set("inspect", "1");
      return `${u.pathname}${u.search}${u.hash || ""}`;
    } catch (_) {
      const joiner = previewUrl.includes("?") ? "&" : "?";
      return `${previewUrl}${joiner}inspect=1`;
    }
  };
  box.innerHTML = list.map(v => `<div class="version-item"><small>${v.id} ${v.created_at}</small>
  <textarea class="output-textarea" onchange="modify('${step}','${v.id}',this.value)">${v.content}</textarea>
  <div>
    <button class="action-btn" onclick="selectVer('${step}','${v.id}')">选定</button>
    <button class="action-btn" onclick="requireModify('${step}','${v.id}')">要求修改</button>
    <button class="action-btn" onclick="deleteVer('${step}','${v.id}')">删除</button>
    ${v.preview ? `<a target="_blank" href="${v.preview}">预览</a>
    <a target="_blank" href="${buildDebugPreviewUrl(v.preview)}">调试预览</a>` : ""}
  </div></div>`).join("");
}

async function refresh() { state = await api('/api/state'); render(); }
async function saveConfig() {
  await api('/api/config', 'POST', {
    base_url: base_url.value, api_key: api_key.value, model: model.value,
    max_tokens: Number(max_tokens.value || 8192)
  });
  await refresh();
}
async function execute(step) {
  if(step === 'delivery') {
    const target_url = prompt('请输入目标URL子路径');
    if (!target_url) return;
    await api(`/api/execute/${step}`, 'POST', { target_url });
    await refresh();
    return;
  }

  let input = document.getElementById(`in-${step}`)?.value || '';
  if (step === 'review') {
    const paths = (state?.review_code_paths || []).join('\n');
    input = `请基于以下代码文件路径进行评审：\n${paths}`;
  }

  const req = api(`/api/execute/${step}`, 'POST', { input });
  setTimeout(() => { refresh(); }, 50);
  await req;
  await refresh();
}
async function autoRegression() {
  const input = auto_input.value || "";
  if (!input.trim()) {
    auto_result.textContent = "请先输入本轮编码目标";
    return;
  }
  const max_retries = Number(auto_retries.value || 2);
  auto_result.textContent = "自动回归执行中...";
  const req = api('/api/auto-regression', 'POST', { input, max_retries });
  setTimeout(() => { refresh(); }, 50);
  const result = await req;
  auto_result.textContent = JSON.stringify(result, null, 2);
  await refresh();
}
async function selectVer(step, vid) {
  await api(`/api/version/${step}/${vid}/select`, 'POST');
  await refresh();
}
async function requireModify(step, vid) {
  const extra = prompt('请输入修改要求');
  const v = state.steps[step].find(x => x.id === vid);
  const req = api(`/api/execute/${step}`, 'POST', { input: (v?.content || '') + '\n修改要求:\n' + (extra || '') });
  setTimeout(() => { refresh(); }, 50);
  await req;
  await refresh();
}
async function deleteVer(step, vid) { await api(`/api/version/${step}/${vid}`, 'DELETE'); await refresh(); }
async function modify(step, vid, content) { await api(`/api/version/${step}/${vid}/modify`, 'POST', { content }); }

refresh();
