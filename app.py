from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request as urlrequest

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
VERSIONS_DIR = DATA_DIR / "versions"
LLM_LOG_DIR = DATA_DIR / "llm_logs"

STAGES = [
    "requirement_analysis",
    "solution_design",
    "architecture_design",
    "code_writing",
    "code_review",
    "delivery_integration",
]

DOC_STAGES = {"requirement_analysis", "solution_design", "architecture_design"}
CODE_STAGES = {"code_writing"}
REVIEW_STAGES = {"code_review", "delivery_integration"}

PROMPT_CONTRACTS = {
    "requirement_analysis": "输出需求分析文档（Markdown）",
    "solution_design": "输出技术方案设计文档（Markdown）",
    "architecture_design": "输出软件架构设计文档（Markdown）",
    "code_writing": "输出完整代码文件，格式必须使用 fenced code block 并标注文件路径",
    "code_review": "输出代码评审意见（Markdown）",
    "delivery_integration": "输出上线/交付集成指引（Markdown）",
}

SYSTEM_PROMPTS = {
    "requirement_analysis": "你是一名资深产品经理。请严格输出需求分析文档（Markdown）。",
    "solution_design": "你是一名资深技术负责人。请严格输出技术方案设计文档（Markdown）。",
    "architecture_design": "你是一名资深架构师。请严格输出软件架构设计文档（Markdown）。",
    "code_writing": (
        "你是一名资深软件工程师。请输出完整代码文件，使用 fenced code block，"
        "每个代码块第一行必须是 '# file: 相对路径'。不得省略关键代码。"
    ),
    "code_review": "你是一名资深代码评审专家。请输出代码评审意见（Markdown）。",
    "delivery_integration": "你是一名资深DevOps工程师。请输出上线/交付集成指引（Markdown）。",
}


@dataclass
class VersionInfo:
    stage: str
    version: str
    path: Path


def ensure_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    VERSIONS_DIR.mkdir(exist_ok=True)
    LLM_LOG_DIR.mkdir(exist_ok=True)
    for stage in STAGES:
        (VERSIONS_DIR / stage).mkdir(exist_ok=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stage_dir(stage: str) -> Path:
    return VERSIONS_DIR / stage


def list_versions(stage: str) -> list[str]:
    dirs = [p.name for p in stage_dir(stage).iterdir() if p.is_dir() and p.name.startswith("v")]
    return sorted(dirs, key=lambda x: int(x[1:]))


def latest_version(stage: str) -> VersionInfo | None:
    versions = list_versions(stage)
    if not versions:
        return None
    v = versions[-1]
    return VersionInfo(stage=stage, version=v, path=stage_dir(stage) / v)


def next_version_name(stage: str) -> str:
    versions = list_versions(stage)
    if not versions:
        return "v1"
    return f"v{int(versions[-1][1:]) + 1}"


def create_version(stage: str, base_version: str | None = None) -> VersionInfo:
    v_name = next_version_name(stage)
    target = stage_dir(stage) / v_name
    target.mkdir(parents=True, exist_ok=False)

    if base_version:
        base_path = stage_dir(stage) / base_version
        if base_path.exists():
            for item in base_path.iterdir():
                if item.name == "meta.json":
                    continue
                dst = target / item.name
                if item.is_file():
                    shutil.copy2(item, dst)
                else:
                    shutil.copytree(item, dst, dirs_exist_ok=True)

    meta = {
        "stage": stage,
        "version": v_name,
        "created_at": now_iso(),
        "base_version": base_version,
        "status": "draft",
        "selected": False,
    }
    (target / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return VersionInfo(stage=stage, version=v_name, path=target)


def read_meta(v: VersionInfo) -> dict[str, Any]:
    p = v.path / "meta.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def write_meta(v: VersionInfo, meta: dict[str, Any]) -> None:
    (v.path / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def save_doc_output(v: VersionInfo, text: str) -> str:
    filename = "output.md"
    (v.path / filename).write_text(text, encoding="utf-8")
    return filename


def parse_code_blocks(output: str) -> list[tuple[str, str]]:
    pattern = re.compile(r"```(?:[\w#+.-]+)?\s*\n#\s*file:\s*(.+?)\n(.*?)```", re.DOTALL)
    files = []
    for path, content in pattern.findall(output):
        files.append((path.strip(), content.rstrip() + "\n"))
    return files


def save_code_output(v: VersionInfo, llm_output: str) -> list[str]:
    files = parse_code_blocks(llm_output)
    saved = []
    code_root = v.path / "code"
    code_root.mkdir(exist_ok=True)
    for rel, content in files:
        clean_rel = rel.lstrip("/")
        target = code_root / clean_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        saved.append(str(target.relative_to(v.path)))

    (v.path / "raw_output.md").write_text(llm_output, encoding="utf-8")
    return saved


def save_review_output(v: VersionInfo, text: str) -> str:
    filename = "review.md"
    (v.path / filename).write_text(text, encoding="utf-8")
    return filename


def read_all_code_for_prompt() -> str:
    latest = latest_version("code_writing")
    if not latest:
        return ""
    code_dir = latest.path / "code"
    if not code_dir.exists():
        return ""

    fragments: list[str] = []
    for file in sorted(code_dir.rglob("*")):
        if file.is_file():
            rel = file.relative_to(code_dir)
            content = file.read_text(encoding="utf-8")
            fragments.append(f"## 文件: {rel}\n```\n{content}\n```")
    return "\n\n".join(fragments)


def read_latest_doc(stage: str) -> str:
    latest = latest_version(stage)
    if not latest:
        return ""
    p = latest.path / "output.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def call_llm(stage: str, user_input: str, llm: dict[str, Any], extra_context: dict[str, Any]) -> str:
    base_url = (llm.get("base_url") or "").rstrip("/")
    api_key = llm.get("api_key") or ""
    model = llm.get("model") or ""
    if not base_url or not api_key or not model:
        raise ValueError("缺少 LLM 配置：base_url/api_key/model 均必填")

    system_prompt = SYSTEM_PROMPTS[stage]
    contract = PROMPT_CONTRACTS[stage]
    context_chunks = [f"输出契约：{contract}"]

    if stage == "code_writing":
        context_chunks.append("以下是当前技术方案设计文档：\n" + (extra_context.get("solution_doc") or "（空）"))
        context_chunks.append("以下是当前软件架构设计文档：\n" + (extra_context.get("architecture_doc") or "（空）"))
        context_chunks.append("以下是现有全部代码（Markdown拼接）：\n" + (extra_context.get("all_code_markdown") or "（空）"))

    user_prompt = "\n\n".join(context_chunks + [f"用户输入：\n{user_input}"])
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
    }

    req = urlrequest.Request(
        url=f"{base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=180) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"]
    except error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"LLM API HTTPError: {e.code} {detail}") from e
    except error.URLError as e:
        raise RuntimeError(f"LLM API URLError: {e.reason}") from e
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"LLM API 调用失败: {e}") from e


def log_llm_call(payload: dict[str, Any]) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    (LLM_LOG_DIR / f"{stamp}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


@app.get("/")
def index():
    return render_template("index.html", stages=STAGES)


@app.get("/api/stages")
def api_stages():
    return jsonify({"stages": STAGES, "contracts": PROMPT_CONTRACTS})


@app.get("/api/versions/<stage>")
def api_versions(stage: str):
    if stage not in STAGES:
        return jsonify({"error": "invalid stage"}), 400

    out = []
    for v in list_versions(stage):
        info = VersionInfo(stage, v, stage_dir(stage) / v)
        out.append(read_meta(info))
    return jsonify({"versions": out})


@app.post("/api/run_step")
def api_run_step():
    data = request.get_json(force=True)
    stage = data.get("stage")
    user_input = data.get("input", "")
    base_version = data.get("base_version")
    llm = data.get("llm", {})

    if stage not in STAGES:
        return jsonify({"error": "invalid stage"}), 400

    extra_context = {}
    if stage in {"code_writing"}:
        extra_context["solution_doc"] = read_latest_doc("solution_design")
        extra_context["architecture_doc"] = read_latest_doc("architecture_design")
        extra_context["all_code_markdown"] = read_all_code_for_prompt()

    version = create_version(stage, base_version=base_version)

    request_payload = {
        "stage": stage,
        "contract": PROMPT_CONTRACTS[stage],
        "input": user_input,
        "llm": llm,
        "extra_context": extra_context,
        "timestamp": now_iso(),
    }
    try:
        llm_output = call_llm(stage, user_input, llm, extra_context)
    except Exception as e:  # noqa: BLE001
        log_llm_call({"request": request_payload, "error": str(e)})
        return jsonify({"error": str(e)}), 400

    if stage in DOC_STAGES:
        saved = [save_doc_output(version, llm_output)]
    elif stage in CODE_STAGES:
        saved = save_code_output(version, llm_output)
    else:
        saved = [save_review_output(version, llm_output)]

    meta = read_meta(version)
    meta["status"] = "done"
    meta["output_files"] = saved
    write_meta(version, meta)

    log_llm_call({"request": request_payload, "output": llm_output, "saved": saved})

    return jsonify({"version": meta, "preview": llm_output[:1000]})


@app.post("/api/select_version")
def api_select_version():
    data = request.get_json(force=True)
    stage = data.get("stage")
    version = data.get("version")
    if stage not in STAGES or not version:
        return jsonify({"error": "invalid request"}), 400

    for v in list_versions(stage):
        info = VersionInfo(stage, v, stage_dir(stage) / v)
        meta = read_meta(info)
        meta["selected"] = (v == version)
        write_meta(info, meta)
    return jsonify({"ok": True})


@app.delete("/api/version/<stage>/<version>")
def api_delete_version(stage: str, version: str):
    if stage not in STAGES:
        return jsonify({"error": "invalid stage"}), 400
    p = stage_dir(stage) / version
    if p.exists() and p.is_dir():
        shutil.rmtree(p)
        return jsonify({"ok": True})
    return jsonify({"error": "not found"}), 404


@app.get("/api/version/<stage>/<version>/content")
def api_version_content(stage: str, version: str):
    if stage not in STAGES:
        return jsonify({"error": "invalid stage"}), 400
    p = stage_dir(stage) / version
    if not p.exists():
        return jsonify({"error": "not found"}), 404

    content = {}
    for f in p.rglob("*"):
        if f.is_file() and f.name != "meta.json":
            content[str(f.relative_to(p))] = f.read_text(encoding="utf-8")
    return jsonify({"files": content})


@app.get("/api/llm_logs")
def api_llm_logs():
    logs = []
    for p in sorted(LLM_LOG_DIR.glob("*.json"), reverse=True)[:200]:
        logs.append(json.loads(p.read_text(encoding="utf-8")))
    return jsonify({"logs": logs})


if __name__ == "__main__":
    ensure_dirs()
    app.run(host="0.0.0.0", port=8000, debug=True)
