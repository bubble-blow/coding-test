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

function stepTemplate(step) {
  const inputable = !["review", "delivery"].includes(step);
  return `<div class="card" id="card-${step}"><h3>${step}</h3>
    ${inputable ? `<textarea id="in-${step}" placeholder="输入"></textarea>` : `<div>无输入框（显示代码路径）</div>`}
    <button onclick="execute('${step}')">执行</button>
    <div class="versions" id="out-${step}"></div>
  </div>`;
}

function render() {
  document.getElementById("pipeline").innerHTML = STEPS.map(stepTemplate).join("");
  for (const step of STEPS) renderStep(step);
  document.getElementById("logs").textContent = JSON.stringify(state.llm_logs, null, 2);
}

function renderStep(step) {
  const box = document.getElementById(`out-${step}`);
  const list = state.steps[step] || [];
  box.innerHTML = list.map(v => `<div class="v-item"><small>${v.id} ${v.created_at}</small>
  <textarea onchange="modify('${step}','${v.id}',this.value)">${v.content}</textarea>
  <div>
    <button onclick="selectVer('${step}','${v.id}')">选定</button>
    <button onclick="requireModify('${step}','${v.id}')">要求修改</button>
    <button onclick="deleteVer('${step}','${v.id}')">删除</button>
    ${v.preview ? `<a target="_blank" href="${v.preview}">预览</a>` : ""}
  </div></div>`).join("");
}

async function refresh() { state = await api('/api/state'); render(); }
async function saveConfig() {
  await api('/api/config', 'POST', {
    base_url: base_url.value, api_key: api_key.value, model: model.value
  });
  await refresh();
}
async function execute(step) {
  if(step === 'delivery') {
    const target_url = prompt('请输入目标URL子路径');
    if (!target_url) return;
    await api(`/api/execute/${step}`, 'POST', { target_url });
  } else {
    const input = document.getElementById(`in-${step}`)?.value || '';
    await api(`/api/execute/${step}`, 'POST', { input });
  }
  await refresh();
}
async function selectVer(step, vid) {
  await api(`/api/version/${step}/${vid}/select`, 'POST');
  const idx = STEPS.indexOf(step);
  if (idx >= 0 && idx < STEPS.length - 1) {
    const next = STEPS[idx + 1];
    const v = state.steps[step].find(x => x.id === vid);
    const input = document.getElementById(`in-${next}`);
    if (input && v) input.value = v.content;
  }
  await refresh();
}
async function requireModify(step, vid) {
  const extra = prompt('请输入修改要求');
  const v = state.steps[step].find(x => x.id === vid);
  await api(`/api/execute/${step}`, 'POST', { input: (v?.content || '') + '\n修改要求:\n' + (extra || '') });
  await refresh();
}
async function deleteVer(step, vid) { await api(`/api/version/${step}/${vid}`, 'DELETE'); await refresh(); }
async function modify(step, vid, content) { await api(`/api/version/${step}/${vid}/modify`, 'POST', { content }); }

refresh();
