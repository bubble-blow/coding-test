const STEPS = [
  ['requirements', '需求分析'],
  ['solution', '方案设计'],
  ['architecture', '架构设计'],
  ['coding', '代码编写'],
  ['review', '代码评审'],
  ['delivery', '交付集成'],
];

let state = null;

async function api(path, method='GET', body=null) {
  const res = await fetch(path, {
    method,
    headers: {'Content-Type': 'application/json'},
    body: body ? JSON.stringify(body) : null,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function loadState() {
  state = await api('/api/state');
  render();
}

function render() {
  document.getElementById('baseUrl').value = state.llm_config.base_url || '';
  document.getElementById('apiKey').value = state.llm_config.api_key || '';
  document.getElementById('model').value = state.llm_config.model || '';

  const container = document.getElementById('pipeline');
  container.innerHTML = '';
  for (const [step, label] of STEPS) {
    const s = state.steps[step];
    const div = document.createElement('section');
    div.className = 'step';
    div.innerHTML = `
      <h2>${label}</h2>
      <textarea id="in-${step}">${escapeHtml(s.input || '')}</textarea>
      <div>
        <button onclick="runStep('${step}')">执行</button>
        <button onclick="previewStep('${step}')">预览</button>
      </div>
      <div id="versions-${step}"></div>
    `;
    container.appendChild(div);
    const vDiv = div.querySelector(`#versions-${step}`);
    s.versions.forEach(v => {
      const item = document.createElement('div');
      item.className = 'version';
      item.innerHTML = `
        <div><b>版本 v${v.id}</b> [${v.status}]</div>
        <pre>${escapeHtml(v.output || '')}</pre>
        <button onclick="action('${step}', ${v.id}, 'select')">选定</button>
        <button onclick="revise('${step}', ${v.id})">要求修改</button>
        <button onclick="action('${step}', ${v.id}, 'delete')">删除</button>
      `;
      vDiv.appendChild(item);
    });
  }

  document.getElementById('monitor').textContent = JSON.stringify(state.monitor_logs.slice(-20), null, 2);
}

function escapeHtml(s) {
  return s.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}

async function saveConfig() {
  await api('/api/llm/config', 'POST', {
    base_url: document.getElementById('baseUrl').value,
    api_key: document.getElementById('apiKey').value,
    model: document.getElementById('model').value,
  });
  await loadState();
}

async function runStep(step) {
  const input_text = document.getElementById(`in-${step}`).value;
  await api('/api/step/run', 'POST', {step, input_text});
  await loadState();
}

async function action(step, version_id, actionName) {
  await api('/api/step/version/action', 'POST', {step, version_id, action: actionName});
  await loadState();
}

async function revise(step, version_id) {
  const feedback = prompt('请输入修改要求');
  await api('/api/step/version/action', 'POST', {step, version_id, action: 'revise', feedback: feedback || ''});
  await loadState();
}

function previewStep(step) {
  const t = document.getElementById(`in-${step}`).value;
  alert(`预览输入（${step}）:\n\n${t.slice(0, 2000)}`);
}

loadState().catch(e => alert(e.message));
