from __future__ import annotations

import json
import re
import shutil
import requests
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
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
            "pipeline_runs": [],
            "delivery_code_paths": [],
        }
        STATE_FILE.write_text(json.dumps(init_state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_state() -> Dict:
    ensure_dirs()
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    state.setdefault("llm_config", {"base_url": "", "api_key": "", "model": "", "max_tokens": 8192})
    state.setdefault("steps", {k: [] for k in PIPELINE_STEPS})
    state.setdefault("selected", {k: None for k in PIPELINE_STEPS})
    state.setdefault("llm_logs", [])
    state.setdefault("pipeline_runs", [])
    state.setdefault("delivery_code_paths", [])
    for step in PIPELINE_STEPS:
        state["steps"].setdefault(step, [])
        state["selected"].setdefault(step, None)
    return state


def save_state(state: Dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


def next_version_id(step: str, versions: List[Dict]) -> str:
    return f"{step}-v{len(versions) + 1}"


def empty_usage() -> Dict:
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def add_usage(total: Dict, usage: Dict | None) -> None:
    if not usage:
        return
    for key in ["prompt_tokens", "completion_tokens", "total_tokens"]:
        total[key] = int(total.get(key, 0) or 0) + int(usage.get(key, 0) or 0)


def call_llm(state: Dict, step: str, input_text: str) -> Dict:
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
    total_usage = empty_usage()
    finish_reason = None
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
        add_usage(total_usage, data.get("usage"))
        if finish_reason != "length":
            break

        messages.append({"role": "assistant", "content": content})
        messages.append({
            "role": "user",
            "content": "你上一条输出被长度限制截断了。请从上次中断的位置继续，仅输出剩余内容，不要重复。",
        })

    return {
        "content": "\n".join(chunks),
        "usage": total_usage,
        "chunks": len(chunks),
        "finish_reason": finish_reason,
    }


def parse_code_blocks(content: str) -> Dict[str, str]:
    pattern = re.compile(r"```file:([^\n]+)\n(.*?)```", re.DOTALL)
    files: Dict[str, str] = {}
    for m in pattern.finditer(content):
        files[m.group(1).strip()] = m.group(2).rstrip() + "\n"
    return files


def inject_inspect_js(html: str) -> str:
    script_tag = '<script src="/plugin/inspect-inject.js"></script>'
    if script_tag in html:
        return html
    if "</body>" in html:
        return html.replace("</body>", f"{script_tag}</body>")
    return html + script_tag


def should_inject_inspect() -> bool:
    return (request.args.get("inspect") or "").lower() in {"1", "true", "yes", "on"}




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


def prepare_step_input(state: Dict, step: str, input_text: str) -> str:
    if step in ["coding", "review"]:
        input_text += "\n\n## 方案设计\n" + selected_content(state, "solution")
        input_text += "\n\n## 架构设计\n" + selected_content(state, "architecture")
        input_text += "\n\n## 现有代码\n" + build_code_markdown(state.get("selected", {}).get("coding"))
    return input_text


def append_run_log(
    state: Dict,
    *,
    run_id: str,
    step: str,
    started_at: str,
    ended_at: str,
    duration_ms: int,
    status: str,
    usage: Dict | None = None,
    version_id: str | None = None,
    error: str | None = None,
    attempt: int | None = None,
    mode: str = "manual",
) -> None:
    entry = {
        "id": run_id,
        "step": step,
        "mode": mode,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_ms": duration_ms,
        "status": status,
        "model": state["llm_config"].get("model", ""),
        "usage": usage or empty_usage(),
    }
    if version_id:
        entry["version_id"] = version_id
    if error:
        entry["error"] = error
    if attempt is not None:
        entry["attempt"] = attempt
    state["pipeline_runs"].append(entry)
    state["pipeline_runs"] = state["pipeline_runs"][-200:]
    state["llm_logs"].append({
        "step": step,
        "time": ended_at,
        "model": state["llm_config"].get("model", ""),
        "status": "ok" if status == "ok" else f"error: {error}",
        "duration_ms": duration_ms,
        "usage": usage or empty_usage(),
    })
    state["llm_logs"] = state["llm_logs"][-200:]


def select_version_in_state(state: Dict, step: str, vid: str) -> None:
    for v in state["steps"].get(step, []):
        v["selected"] = v["id"] == vid
    state["selected"][step] = vid
    if step == "review":
        state["delivery_code_paths"] = list_code_paths(state.get("selected", {}).get("coding"))


def persist_step_output(state: Dict, step: str, vid: str, output: str) -> None:
    if step in ["requirements", "solution", "architecture"]:
        step_dir = DOCS_DIR / step / vid
        step_dir.mkdir(parents=True, exist_ok=True)
        (step_dir / f"{step}.md").write_text(output, encoding="utf-8")

    if step == "coding":
        save_code_version(vid, output, state)


def execute_step_core(
    state: Dict,
    step: str,
    input_text: str,
    *,
    mode: str = "manual",
    attempt: int | None = None,
    auto_select: bool = False,
) -> Dict:
    req_id = str(uuid.uuid4())
    started_at = now_str()
    started_perf = perf_counter()
    IN_FLIGHT_REQUESTS[req_id] = {
        "id": req_id,
        "step": step,
        "mode": mode,
        "started_at": started_at,
        "attempt": attempt,
    }
    try:
        llm_result = call_llm(state, step, prepare_step_input(state, step, input_text))
        output = llm_result["content"]
        versions = state["steps"][step]
        vid = next_version_id(step, versions)
        version = VersionRecord(id=vid, created_at=now_str(), content=output).__dict__
        versions.append(version)
        persist_step_output(state, step, vid, output)
        if auto_select:
            select_version_in_state(state, step, vid)
            version["selected"] = True

        ended_at = now_str()
        duration_ms = int((perf_counter() - started_perf) * 1000)
        append_run_log(
            state,
            run_id=req_id,
            step=step,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            status="ok",
            usage=llm_result["usage"],
            version_id=vid,
            attempt=attempt,
            mode=mode,
        )
        return {"version": version, "llm": llm_result}
    except Exception as e:
        ended_at = now_str()
        duration_ms = int((perf_counter() - started_perf) * 1000)
        append_run_log(
            state,
            run_id=req_id,
            step=step,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            status="error",
            error=str(e),
            attempt=attempt,
            mode=mode,
        )
        raise
    finally:
        IN_FLIGHT_REQUESTS.pop(req_id, None)


def review_passed(review_text: str) -> bool:
    text = review_text.lower()
    first_lines = "\n".join(review_text.strip().splitlines()[:5])
    if re.search(r"结论\s*[:：]\s*PASS\b", first_lines, re.IGNORECASE):
        return True
    if re.search(r"结论\s*[:：]\s*FAIL\b", first_lines, re.IGNORECASE):
        return False

    fail_markers = ["必改", "阻塞上线", "严重", "语法错误", "无法运行", "未实现"]
    pass_markers = ["未发现问题", "无明显问题", "可以通过", "通过评审", "无阻塞问题", "没有发现"]
    if any(marker in review_text for marker in fail_markers) or "fatal error" in text:
        return False
    return any(marker in review_text for marker in pass_markers)


def build_observability(state: Dict) -> Dict:
    runs = state.get("pipeline_runs", [])
    by_step = {}
    totals = {"runs": len(runs), "success": 0, "failed": 0, "duration_ms": 0, "tokens": 0}
    for run in runs:
        step = run.get("step", "")
        item = by_step.setdefault(step, {"runs": 0, "success": 0, "failed": 0, "duration_ms": 0, "tokens": 0})
        item["runs"] += 1
        totals["duration_ms"] += int(run.get("duration_ms", 0) or 0)
        item["duration_ms"] += int(run.get("duration_ms", 0) or 0)
        tokens = int((run.get("usage") or {}).get("total_tokens", 0) or 0)
        totals["tokens"] += tokens
        item["tokens"] += tokens
        if run.get("status") == "ok":
            totals["success"] += 1
            item["success"] += 1
        else:
            totals["failed"] += 1
            item["failed"] += 1
    for item in by_step.values():
        item["avg_duration_ms"] = int(item["duration_ms"] / item["runs"]) if item["runs"] else 0
        item["success_rate"] = round(item["success"] / item["runs"], 3) if item["runs"] else 0
    totals["avg_duration_ms"] = int(totals["duration_ms"] / totals["runs"]) if totals["runs"] else 0
    totals["success_rate"] = round(totals["success"] / totals["runs"], 3) if totals["runs"] else 0
    return {"totals": totals, "by_step": by_step, "recent_runs": runs[-20:]}


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
    state["observability"] = build_observability(state)
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

    try:
        result = execute_step_core(state, step, payload.get("input", ""))
    except Exception as e:
        save_state(state)
        return jsonify({"error": str(e)}), 400
    save_state(state)
    return jsonify({"ok": True, "version": result["version"], "usage": result["llm"]["usage"]})


@app.post("/api/auto-regression")
def api_auto_regression():
    state = load_state()
    payload = request.json or {}
    base_input = payload.get("input", "")
    max_retries = max(0, min(int(payload.get("max_retries", 2) or 0), 5))
    history = []
    next_input = base_input

    for attempt in range(1, max_retries + 2):
        try:
            coding_result = execute_step_core(
                state,
                "coding",
                next_input,
                mode="auto_regression",
                attempt=attempt,
                auto_select=True,
            )
            review_input = (
                "请评审当前选中的代码版本。"
                "请在评审结果第一行严格输出“结论: PASS”或“结论: FAIL”。"
                "只有存在阻塞上线的问题时才输出“结论: FAIL”；"
                "非阻塞优化建议、代码风格建议、可后续迭代的问题不影响通过。"
                "如果输出“结论: FAIL”，请按必改问题列出可操作的修改建议；"
                "如果输出“结论: PASS”，可以继续列出非阻塞优化建议。"
            )
            review_result = execute_step_core(
                state,
                "review",
                review_input,
                mode="auto_regression",
                attempt=attempt,
                auto_select=True,
            )
        except Exception as e:
            save_state(state)
            return jsonify({"error": str(e), "history": history}), 400

        review_text = review_result["version"]["content"]
        passed = review_passed(review_text)
        item = {
            "attempt": attempt,
            "coding_version": coding_result["version"]["id"],
            "review_version": review_result["version"]["id"],
            "passed": passed,
        }
        history.append(item)
        if passed:
            save_state(state)
            return jsonify({"ok": True, "passed": True, "attempts": attempt, "history": history})

        next_input = (
            f"{base_input}\n\n"
            f"## 自动回归第 {attempt} 轮评审反馈\n"
            f"{review_text}\n\n"
            "请修复以上评审指出的问题，保留未受影响的文件，并继续按 ```file:path/to/file``` 格式输出完整代码文件。"
        )

    save_state(state)
    return jsonify({"ok": True, "passed": False, "attempts": max_retries + 1, "history": history})


def build_code_markdown(version_id: str | None) -> str:
    if not version_id:
        return ""
    root = CODE_DIR / version_id
    if not root.exists():
        return ""
    sections = []
    skip_suffixes = {".pyc", ".pyo", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".zip", ".gz"}
    for f in sorted(root.glob("**/*")):
        if f.is_file():
            rel = f.relative_to(root)
            if "__pycache__" in rel.parts or f.suffix.lower() in skip_suffixes:
                continue
            try:
                content = f.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            sections.append(f"### {rel}\n```\n{content}\n```")
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
    select_version_in_state(state, step, vid)
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


def collect_code_files(root: Path) -> str:
    sections = []
    skip_suffixes = {".pyc", ".pyo", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".zip", ".gz", ".pdf", ".woff", ".woff2"}
    for f in sorted(root.glob("**/*")):
        if not f.is_file():
            continue
        if "__pycache__" in f.parts or f.suffix.lower() in skip_suffixes:
            continue
        try:
            content = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        sections.append(f"### {f.relative_to(root)}\n```\\n{content}\\n```")
    return "\\n\\n".join(sections)


@app.post("/api/preview-modify")
def api_preview_modify():
    state = load_state()
    body = request.json or {}
    page_url = (body.get("page_url") or "").strip("/")
    suggestion = body.get("suggestion", "")
    selector = body.get("element_selector", "")
    own_text = body.get("element_own_text", "")
    if not page_url:
        return jsonify({"error": "缺少 page_url"}), 400

    target_path = DEPLOY_DIR / page_url
    if target_path.is_file():
        target_root = target_path.parent
        target_rel = page_url.rsplit("/", 1)[0] if "/" in page_url else ""
    else:
        target_root = target_path
        target_rel = page_url
    if not target_root.exists():
        return jsonify({"error": "页面路径不存在"}), 400

    prompt = (
        f"你需要按如下输出要求完成代码修改：{PROMPTS['coding']}\\n\\n"
        f"页面URL路径: /{page_url}\\n"
        f"目标元素选择器: {selector}\\n"
        f"目标元素标签内容(不含子元素): {own_text}\\n"
        f"用户修改意见: {suggestion}\\n\\n"
        "以下是当前路径下的全部代码文件：\\n"
        f"{collect_code_files(target_root)}\\n\\n"
        "请只输出需要修改后的代码文件，使用 ```file:path``` 包裹。"
    )
    try:
        llm_result = call_llm(state, "coding", prompt)
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    files = parse_code_blocks(llm_result["content"])
    if not files:
        return jsonify({"error": "LLM 未返回有效代码块"}), 400

    new_rel = (target_rel + "/" if target_rel else "") + f"_edited_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    new_root = DEPLOY_DIR / new_rel
    copy_dir_merge(target_root, new_root)
    for path, content in files.items():
        out = new_root / path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")
    return jsonify({"ok": True, "preview_url": f"/{new_rel}/?inspect=1"})


@app.get("/preview/<path:subpath>")
def preview(subpath: str):
    return send_from_directory(DEPLOY_DIR, subpath)


@app.get("/<path:req_path>")
def serve_deployed_or_frontend(req_path: str):
    deployed = DEPLOY_DIR / req_path
    if deployed.is_file():
        if should_inject_inspect() and deployed.suffix.lower() in {".html", ".htm"}:
            return inject_inspect_js(deployed.read_text(encoding="utf-8"))
        return send_from_directory(DEPLOY_DIR, req_path)
    if deployed.is_dir() and (deployed / "index.html").exists():
        if should_inject_inspect():
            return inject_inspect_js((deployed / "index.html").read_text(encoding="utf-8"))
        return send_from_directory(deployed, "index.html")
    if req_path.startswith("plugin/"):
        plugin_file = BASE_DIR / req_path
        if plugin_file.is_file():
            return send_from_directory(BASE_DIR / "plugin", req_path.replace("plugin/", "", 1))
    frontend_file = BASE_DIR / "frontend" / req_path
    if frontend_file.is_file():
        return send_from_directory(BASE_DIR / "frontend", req_path)
    return app.send_static_file("index.html")


if __name__ == "__main__":
    ensure_dirs()
    app.run(host="0.0.0.0", port=8000, debug=True)
