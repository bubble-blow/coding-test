from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Dict, List, Optional

try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal
from pathlib import Path
import json
import shutil
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
STATE_FILE = DATA_DIR / "state.json"
DOCS_DIR = ROOT / "generated" / "docs"
CODE_DIR = ROOT / "generated" / "code"

STEPS = ["requirements", "solution", "architecture", "coding", "review", "integration"]


def ensure_dirs():
    for p in [DATA_DIR, DOCS_DIR, CODE_DIR]:
        p.mkdir(parents=True, exist_ok=True)


def default_state():
    return {
        "llm_config": {"base_url": "", "api_key": "", "model": ""},
        "runs": {step: [] for step in STEPS},
        "current": {"step": "requirements", "run_id": None},
        "monitor": [],
    }


def load_state():
    ensure_dirs()
    if not STATE_FILE.exists():
        save_state(default_state())
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def now_str():
    return datetime.utcnow().isoformat() + "Z"


class LLMConfig(BaseModel):
    base_url: str
    api_key: str
    model: str


class RunRequest(BaseModel):
    step: Literal["requirements", "solution", "architecture", "coding", "review", "integration"]
    prompt: str
    based_on_run_id: Optional[str] = None


class DecisionRequest(BaseModel):
    step: str
    run_id: str
    action: Literal["approve", "revise"]


class EditOutputRequest(BaseModel):
    step: str
    run_id: str
    content: str


class SelectVersionRequest(BaseModel):
    step: str
    run_id: str


app = FastAPI(title="AI Coding Platform")
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/state")
def get_state():
    return load_state()


@app.post("/api/llm/config")
def set_llm_config(cfg: LLMConfig):
    state = load_state()
    state["llm_config"] = cfg.model_dump()
    save_state(state)
    return {"ok": True}


def create_version_dir(base: Path, step: str, run_id: str):
    d = base / step / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def snapshot_code_from_prev(new_dir: Path, prev_run_id: Optional[str]):
    if not prev_run_id:
        return
    prev_dir = CODE_DIR / "coding" / prev_run_id
    if prev_dir.exists():
        for fp in prev_dir.rglob("*"):
            if fp.is_file():
                rel = fp.relative_to(prev_dir)
                target = new_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(fp, target)


def fake_llm_output(step: str, prompt: str, run_id: str):
    if step in ["requirements", "solution", "architecture", "review", "integration"]:
        return f"# {step} output\n\nrun: {run_id}\n\n{prompt}\n"
    if step == "coding":
        return {
            "files": {
                "main.py": "print('hello from generated code')\n",
                "README.md": "# Generated Project\n"
            }
        }


@app.post("/api/pipeline/run")
def run_step(req: RunRequest):
    state = load_state()
    run_id = f"{req.step}-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"

    output = fake_llm_output(req.step, req.prompt, run_id)
    run = {
        "run_id": run_id,
        "created_at": now_str(),
        "prompt": req.prompt,
        "output": output,
        "status": "done",
        "approved": False,
        "based_on_run_id": req.based_on_run_id,
    }

    if req.step == "coding":
        code_dir = create_version_dir(CODE_DIR, req.step, run_id)
        snapshot_code_from_prev(code_dir, req.based_on_run_id)
        for f, content in output["files"].items():
            target = code_dir / f
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
    else:
        doc_dir = create_version_dir(DOCS_DIR, req.step, run_id)
        (doc_dir / f"{req.step}.md").write_text(output, encoding="utf-8")

    state["runs"][req.step].append(run)
    state["current"] = {"step": req.step, "run_id": run_id}
    state["monitor"].append({"time": now_str(), "step": req.step, "event": "run", "run_id": run_id})
    save_state(state)
    return run


@app.post("/api/pipeline/decision")
def decision(req: DecisionRequest):
    state = load_state()
    runs = state["runs"].get(req.step, [])
    match = next((r for r in runs if r["run_id"] == req.run_id), None)
    if not match:
        raise HTTPException(404, "run not found")
    if req.action == "approve":
        match["approved"] = True
        idx = STEPS.index(req.step)
        next_step = STEPS[min(idx + 1, len(STEPS) - 1)]
        state["current"] = {"step": next_step, "run_id": req.run_id}
    state["monitor"].append({"time": now_str(), "step": req.step, "event": req.action, "run_id": req.run_id})
    save_state(state)
    return {"ok": True, "current": state["current"]}


@app.post("/api/pipeline/edit")
def edit_output(req: EditOutputRequest):
    state = load_state()
    runs = state["runs"].get(req.step, [])
    match = next((r for r in runs if r["run_id"] == req.run_id), None)
    if not match:
        raise HTTPException(404, "run not found")
    match["output"] = req.content
    if req.step != "coding":
        doc_dir = DOCS_DIR / req.step / req.run_id
        doc_dir.mkdir(parents=True, exist_ok=True)
        (doc_dir / f"{req.step}.md").write_text(req.content, encoding="utf-8")
    save_state(state)
    return {"ok": True}


@app.post("/api/pipeline/select")
def select_version(req: SelectVersionRequest):
    state = load_state()
    runs = state["runs"].get(req.step, [])
    if not any(r["run_id"] == req.run_id for r in runs):
        raise HTTPException(404, "run not found")
    state["current"] = {"step": req.step, "run_id": req.run_id}
    save_state(state)
    return {"ok": True}


@app.delete("/api/pipeline/run/{step}/{run_id}")
def delete_run(step: str, run_id: str):
    state = load_state()
    runs = state["runs"].get(step, [])
    state["runs"][step] = [r for r in runs if r["run_id"] != run_id]
    save_state(state)
    return {"ok": True}


@app.get("/api/files/coding/{run_id}")
def list_code_files(run_id: str):
    d = CODE_DIR / "coding" / run_id
    if not d.exists():
        raise HTTPException(404, "run code not found")
    out = []
    for f in d.rglob("*"):
        if f.is_file():
            out.append({"path": str(f.relative_to(d)), "content": f.read_text(encoding="utf-8")})
    return {"files": out}
