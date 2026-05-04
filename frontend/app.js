const steps = ["requirement", "solution", "architecture", "coding", "review", "delivery"];
const editableSteps = new Set(["requirement", "solution", "architecture"]);

async function api(url, method = "GET", body) {
  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  return res.json();
}

async function saveConfig() {
  await api("/api/llm/config", "POST", {
    provider: provider.value,
    api_base: api_base.value,
    api_key: api_key.value,
    model: model.value,
    temperature: 0.2,
    max_tokens: 4096,
  });
  alert("配置已保存");
}

function stepHTML(step) {
  return `<div class="step" id="box-${step}">
    <h3>${step}</h3>
    <textarea id="prompt-${step}" placeholder="输入该步骤任务描述"></textarea>
    <div>
      <button onclick="runStep('${step}')">运行</button>
      <button onclick="decision('${step}','proceed')">进入下一步</button>
      <button onclick="decision('${step}','revise')">要求修改</button>
      <button onclick="loadVersions('${step}')">历史版本</button>
    </div>
    <div id="versions-${step}"></div>
    <pre id="output-${step}"></pre>
  </div>`;
}

async function runStep(step) {
  const pipeline = await api("/api/pipeline");
  const sourceVersion = step === "coding" ? (pipeline.active_versions?.coding || "") : "";
  const data = await api("/api/pipeline/run", "POST", { step, prompt: document.getElementById(`prompt-${step}`).value, source_version: sourceVersion });
  document.getElementById(`output-${step}`).textContent = data.output;
  if (editableSteps.has(step)) {
    const v = data.version;
    document.getElementById(`output-${step}`).innerHTML += `\n\n<button onclick="saveEdit('${step}','${v}')">保存编辑</button>`;
  }
  refreshMetrics();
}

async function decision(step, action) {
  await api("/api/pipeline/decision", "POST", { step, action, comment: "" });
}

async function loadVersions(step) {
  const data = await api(`/api/pipeline/versions/${step}`);
  const root = document.getElementById(`versions-${step}`);
  root.innerHTML = (data.items || []).map(v =>
    `<div>${v.version}
      <button onclick="showVersion('${step}','${v.version}')">查看</button>
      <button onclick="selectVersion('${step}','${v.version}')">选定</button>
      <button onclick="deleteVersion('${step}','${v.version}')">删除</button>
    </div>`
  ).join("");
}

async function showVersion(step, version) {
  const data = await api(`/api/pipeline/content/${step}/${version}`);
  document.getElementById(`output-${step}`).textContent = data.content;
}

async function saveEdit(step, version) {
  const content = document.getElementById(`output-${step}`).textContent;
  await api("/api/pipeline/edit", "POST", { step, version, content });
  alert("已保存编辑");
}

async function selectVersion(step, version) {
  await api("/api/pipeline/version/select", "POST", { step, version });
}

async function deleteVersion(step, version) {
  await api(`/api/pipeline/versions/${step}/${version}`, "DELETE");
  await loadVersions(step);
}

async function refreshMetrics() {
  const data = await api("/api/llm/metrics");
  document.getElementById("metrics").textContent = JSON.stringify(data, null, 2);
}

async function previewCodegenInput() {
  const data = await api("/api/pipeline/codegen-input");
  document.getElementById("preview").textContent = JSON.stringify(data, null, 2);
}

function init() {
  document.getElementById("steps").innerHTML = steps.map(stepHTML).join("");
  refreshMetrics();
}

init();
