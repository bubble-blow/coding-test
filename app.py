from __future__ import annotations

import json
import re
import shutil
import requests
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List
import uuid

from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder="frontend", static_url_path="/static")

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DOCS_DIR = DATA_DIR / "docs"
CODE_DIR = DATA_DIR / "code"
DEPLOY_DIR = BASE_DIR / "public"
STATE_FILE = DATA_DIR / "state.json"

PIPELINE_STEPS = [
    "requirements",
    "solution",
    "architecture",
    "coding",
    "review",
    "delivery",
]

IN_FLIGHT_REQUESTS: Dict[str, Dict] = {}

PROMPTS = {
    "requirements": "输出需求文档（markdown）",
    "solution": "输出技术方案设计文档（markdown）",
    "architecture": "输出软件架构设计文档（markdown）",
    "coding": "输出完整代码文件，格式为```file:path/to/file\n...\n```",
    "review": "输出代码评审意见（markdown）",
}


@dataclass
class VersionRecord:
    id: str
    created_at: str
    content: str
    selected: bool = False



def ensure_dirs() -> None:
    for p in [DATA_DIR, DOCS_DIR, CODE_DIR, DEPLOY_DIR]:
        p.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        init_state = {
            "llm_config": {
                "base_url": "",
                "api_key": "",
                "model": "",
                "max_tokens": 8192,
            },
            "steps": {k: [] for k in PIPELINE_STEPS},
            "selected": {k: None for k in PIPELINE_STEPS},
            "llm_logs": [],
            "delivery_code_paths": [],
        }
        STATE_FILE.write_text(json.dumps(init_state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_state() -> Dict:
    ensure_dirs()
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_state(state: Dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


def next_version_id(step: str, versions: List[Dict]) -> str:
    return f"{step}-v{len(versions) + 1}"


def call_llm(state: Dict, step: str, input_text: str) -> str:
    cfg = state.get("llm_config", {})
    base_url = (cfg.get("base_url") or "").rstrip("/")
    api_key = cfg.get("api_key") or ""
    model = cfg.get("model") or ""

    if not base_url or not api_key or not model:
        raise ValueError("LLM 配置不完整，请先配置 base_url / api_key / model")

    system_prompt = (
        "你是AI Coding平台中的步骤执行助手。"
        f"当前步骤：{step}。输出要求：{PROMPTS.get(step, '')}。"
        "请严格按要求输出完整内容，不要省略。"
    )

    url = f"{base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    max_tokens = int(cfg.get("max_tokens") or 8192)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": input_text},
    ]

    chunks = []
    for _ in range(6):
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": max_tokens,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=600)
        resp.raise_for_status()
        data = resp.json()

        choices = data.get("choices") or []
        if not choices:
            raise ValueError(f"LLM 返回异常: {data}")
        choice = choices[0]
        content = choice.get("message", {}).get("content", "")
        if not content:
            raise ValueError(f"LLM 返回空内容: {data}")
        chunks.append(content)
        finish_reason = choice.get("finish_reason")
        if finish_reason != "length":
            break

        messages.append({"role": "assistant", "content": content})
        messages.append({
            "role": "user",
            "content": "你上一条输出被长度限制截断了。请从上次中断的位置继续，仅输出剩余内容，不要重复。",
        })

    return "\n".join(chunks)


def parse_code_blocks(content: str) -> Dict[str, str]:
    pattern = re.compile(r"```file:([^\n]+)\n(.*?)```", re.DOTALL)
    files: Dict[str, str] = {}
    for m in pattern.finditer(content):
        files[m.group(1).strip()] = m.group(2).rstrip() + "\n"
    return files




def list_code_paths(version_id: str | None) -> List[str]:
    if not version_id:
        return []
    root = CODE_DIR / version_id
    if not root.exists():
        return []
    return [str(f.relative_to(root)) for f in sorted(root.glob("**/*")) if f.is_file()]

def selected_content(state: Dict, step: str) -> str:
    sid = state["selected"].get(step)
    if not sid:
        return ""
    for v in state["steps"][step]:
        if v["id"] == sid:
            return v["content"]
    return ""


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/api/state")
def api_state():
    state = load_state()
    code_paths = list_code_paths(state.get("selected", {}).get("coding"))
    state["review_code_paths"] = code_paths
    if not state.get("delivery_code_paths"):
        state["delivery_code_paths"] = code_paths
    state["in_flight_requests"] = list(IN_FLIGHT_REQUESTS.values())
    return jsonify(state)


@app.post("/api/config")
def api_config():
    state = load_state()
    state["llm_config"].update(request.json or {})
    save_state(state)
    return jsonify({"ok": True})


@app.post("/api/execute/<step>")
def api_execute(step: str):
    if step not in PIPELINE_STEPS:
        return jsonify({"error": "invalid step"}), 400
    state = load_state()
    payload = request.json or {}

    if step == "delivery":
        return handle_delivery(state, payload)

    input_text = payload.get("input", "")
    if step in ["coding", "review"]:
        input_text += "\n\n## 方案设计\n" + selected_content(state, "solution")
        input_text += "\n\n## 架构设计\n" + selected_content(state, "architecture")
        input_text += "\n\n## 现有代码\n" + build_all_code_markdown()

    req_id = str(uuid.uuid4())
    IN_FLIGHT_REQUESTS[req_id] = {"id": req_id, "step": step, "started_at": now_str()}
    try:
        output = call_llm(state, step, input_text)
    except Exception as e:
        state["llm_logs"].append({"step": step, "time": now_str(), "model": state["llm_config"].get("model", ""), "status": f"error: {e}"})
        save_state(state)
        return jsonify({"error": str(e)}), 400
    finally:
        IN_FLIGHT_REQUESTS.pop(req_id, None)
    versions = state["steps"][step]
    vid = next_version_id(step, versions)
    version = VersionRecord(id=vid, created_at=now_str(), content=output).__dict__
    versions.append(version)

    if step in ["requirements", "solution", "architecture"]:
        step_dir = DOCS_DIR / step / vid
        step_dir.mkdir(parents=True, exist_ok=True)
        (step_dir / f"{step}.md").write_text(output, encoding="utf-8")

    if step == "coding":
        save_code_version(vid, output, state)

    state["llm_logs"].append(
        {"step": step, "time": now_str(), "model": state["llm_config"].get("model", ""), "status": "ok"}
    )
    save_state(state)
    return jsonify({"ok": True, "version": version})


def build_all_code_markdown() -> str:
    if not CODE_DIR.exists():
        return ""
    sections = []
    for f in sorted(CODE_DIR.glob("**/*")):
        if f.is_file():
            rel = f.relative_to(CODE_DIR)
            sections.append(f"### {rel}\n```\n{f.read_text(encoding='utf-8')}\n```")
    return "\n\n".join(sections)




def copy_dir_merge(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            copy_dir_merge(item, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)

def save_code_version(vid: str, output: str, state: Dict) -> None:
    files = parse_code_blocks(output)
    target = CODE_DIR / vid
    target.mkdir(parents=True, exist_ok=True)

    prev = state["selected"].get("coding")
    if prev:
        prev_dir = CODE_DIR / prev
        if prev_dir.exists():
            copy_dir_merge(prev_dir, target)

    for path, content in files.items():
        fp = target / path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")


@app.post("/api/version/<step>/<vid>/select")
def api_select(step: str, vid: str):
    state = load_state()
    for v in state["steps"].get(step, []):
        v["selected"] = v["id"] == vid
    state["selected"][step] = vid
    if step == "review":
        state["delivery_code_paths"] = list_code_paths(state.get("selected", {}).get("coding"))
    save_state(state)
    return jsonify({"ok": True})


@app.delete("/api/version/<step>/<vid>")
def api_delete(step: str, vid: str):
    state = load_state()
    state["steps"][step] = [v for v in state["steps"].get(step, []) if v["id"] != vid]
    if state["selected"].get(step) == vid:
        state["selected"][step] = None
    save_state(state)
    return jsonify({"ok": True})


@app.post("/api/version/<step>/<vid>/modify")
def api_modify(step: str, vid: str):
    state = load_state()
    body = request.json or {}
    for v in state["steps"].get(step, []):
        if v["id"] == vid:
            v["content"] = body.get("content", v["content"])
    save_state(state)
    return jsonify({"ok": True})


def handle_delivery(state: Dict, payload: Dict):
    source_version = payload.get("source_version") or state["selected"].get("review")
    target_url = payload.get("target_url", "").strip("/")
    code_version = state["selected"].get("coding")
    if not code_version:
        return jsonify({"error": "请先选定代码版本"}), 400

    src = CODE_DIR / code_version
    dst = DEPLOY_DIR / target_url
    copy_dir_merge(src, dst)

    entry = {
        "id": next_version_id("delivery", state["steps"]["delivery"]),
        "created_at": now_str(),
        "content": json.dumps({"source": source_version, "target": target_url}, ensure_ascii=False),
        "selected": False,
        "preview": f"/{target_url}",
        "code_version": code_version,
    }
    state["steps"]["delivery"].append(entry)
    save_state(state)
    return jsonify({"ok": True, "version": entry})


@app.get("/preview/<path:subpath>")
def preview(subpath: str):
    return send_from_directory(DEPLOY_DIR, subpath)


@app.get("/<path:req_path>")
def serve_deployed_or_frontend(req_path: str):
    deployed = DEPLOY_DIR / req_path
    if deployed.is_file():
        return send_from_directory(DEPLOY_DIR, req_path)
    if deployed.is_dir() and (deployed / "index.html").exists():
        return send_from_directory(deployed, "index.html")
    frontend_file = BASE_DIR / "frontend" / req_path
    if frontend_file.is_file():
        return send_from_directory(BASE_DIR / "frontend", req_path)
    return app.send_static_file("index.html")


if __name__ == "__main__":
    ensure_dirs()
    app.run(host="0.0.0.0", port=8000, debug=True)
