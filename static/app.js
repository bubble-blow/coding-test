const stagesCN = {
  requirement_analysis: "需求分析",
  solution_design: "方案设计",
  architecture_design: "架构设计",
  code_writing: "代码编写",
  code_review: "代码评审",
  delivery_integration: "交付集成",
};

let allStages = [];

async function api(url, options = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}

function llmConfig() {
  return {
    base_url: document.getElementById("apiBase").value,
    api_key: document.getElementById("apiKey").value,
    model: document.getElementById("model").value,
  };
}

async function load() {
  const data = await api("/api/stages");
  allStages = data.stages;
  const root = document.getElementById("pipeline");
  root.innerHTML = "";

  for (const stage of allStages) {
    const card = document.createElement("div");
    card.className = "step";
    card.innerHTML = `
      <h3>${stagesCN[stage]}</h3>
      <textarea id="input-${stage}" placeholder="输入本步骤说明，或要求LLM修改"></textarea>
      <div class="row">
        <input id="base-${stage}" placeholder="基线版本，如 v1（可选）" />
        <button data-action="run" data-stage="${stage}">执行步骤</button>
        <button data-action="versions" data-stage="${stage}">刷新版本</button>
      </div>
      <div id="versions-${stage}" class="versions"></div>
    `;
    root.appendChild(card);
  }

  root.addEventListener("click", onClick);
  document.getElementById("refreshLogs").onclick = loadLogs;
  await refreshAllVersions();
}

async function onClick(e) {
  const btn = e.target.closest("button");
  if (!btn) return;
  const stage = btn.dataset.stage;
  const action = btn.dataset.action;
  if (!stage || !action) return;

  if (action === "run") {
    const input = document.getElementById(`input-${stage}`).value;
    const base = document.getElementById(`base-${stage}`).value || null;
    const body = { stage, input, base_version: base, llm: llmConfig() };
    const result = await api("/api/run_step", { method: "POST", body: JSON.stringify(body) });
    document.getElementById("preview").textContent = JSON.stringify(result, null, 2);
    await refreshVersions(stage);
    await loadLogs();
  }

  if (action === "versions") {
    await refreshVersions(stage);
  }

  if (action === "select") {
    await api("/api/select_version", {
      method: "POST",
      body: JSON.stringify({ stage, version: btn.dataset.version }),
    });
    await refreshVersions(stage);
  }

  if (action === "delete") {
    await api(`/api/version/${stage}/${btn.dataset.version}`, { method: "DELETE" });
    await refreshVersions(stage);
  }

  if (action === "preview") {
    const data = await api(`/api/version/${stage}/${btn.dataset.version}/content`);
    document.getElementById("preview").textContent = JSON.stringify(data.files, null, 2);
  }
}

async function refreshAllVersions() {
  for (const s of allStages) await refreshVersions(s);
}

async function refreshVersions(stage) {
  const data = await api(`/api/versions/${stage}`);
  const el = document.getElementById(`versions-${stage}`);
  el.innerHTML = "";
  for (const v of data.versions) {
    const item = document.createElement("div");
    item.className = "version-item";
    item.innerHTML = `
      <span>${v.version} ${v.selected ? "✅" : ""} (${v.status})</span>
      <button data-action="preview" data-stage="${stage}" data-version="${v.version}">预览</button>
      <button data-action="select" data-stage="${stage}" data-version="${v.version}">选定</button>
      <button data-action="delete" data-stage="${stage}" data-version="${v.version}">删除</button>
    `;
    el.appendChild(item);
  }
}

async function loadLogs() {
  const data = await api("/api/llm_logs");
  document.getElementById("logs").textContent = JSON.stringify(data.logs.slice(0, 10), null, 2);
}

load();
