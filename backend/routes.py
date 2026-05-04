import time
from typing import Dict

from fastapi import APIRouter, HTTPException

from backend.models import (
    CodeGenInputPayload,
    HumanDecision,
    LLMConfig,
    PipelineStepRequest,
    SaveEditableRequest,
    SelectVersionRequest,
)
from backend.storage import Storage, STEPS

router = APIRouter()
storage = Storage()


@router.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@router.get("/pipeline")
def get_pipeline_state() -> Dict:
    return storage.load_state()


@router.post("/llm/config")
def set_llm_config(config: LLMConfig) -> Dict:
    state = storage.load_state()
    state["llm_config"] = config.model_dump()
    storage.save_state(state)
    return {"message": "saved"}


@router.get("/llm/metrics")
def get_metrics() -> Dict:
    return storage.load_state().get("metrics", {})


@router.post("/pipeline/run")
def run_step(req: PipelineStepRequest) -> Dict:
    if req.step not in STEPS:
        raise HTTPException(status_code=400, detail="unknown step")

    begin = time.time()
    state = storage.load_state()
    version = storage.new_version(req.step)

    mock_output = f"# {req.step} output\n\n{req.prompt}\n\n> generated at {version}"
    files = {}
    if req.step == "coding":
        files = {
            "src/main.js": "console.log('generated from coding step');",
            "README.generated.md": "# Generated Code Package\n\nThis is a mock generated artifact.",
        }
        storage.write_code_files(version, files, req.source_version)

    storage.write_step_content(req.step, version, mock_output)
    state["active_versions"][req.step] = version
    state["gates"][req.step] = "done"

    latency = (time.time() - begin) * 1000
    metrics = state.get("metrics", {})
    total = metrics.get("total_calls", 0) + 1
    succ = metrics.get("success_calls", 0) + 1
    avg = ((metrics.get("avg_latency_ms", 0.0) * (total - 1)) + latency) / total
    state["metrics"] = {
        "total_calls": total,
        "success_calls": succ,
        "failed_calls": metrics.get("failed_calls", 0),
        "avg_latency_ms": round(avg, 2),
        "last_error": "",
    }
    storage.save_state(state)

    return {"step": req.step, "version": version, "output": mock_output, "files": files}


@router.post("/pipeline/decision")
def pipeline_decision(req: HumanDecision) -> Dict:
    state = storage.load_state()
    state["gates"][req.step] = req.action
    storage.save_state(state)
    return {"message": "decision saved"}


@router.post("/pipeline/edit")
def save_editable(req: SaveEditableRequest) -> Dict:
    storage.write_step_content(req.step, req.version, req.content)
    return {"message": "saved"}


@router.get("/pipeline/versions/{step}")
def list_versions(step: str) -> Dict:
    return {"items": storage.list_versions(step)}


@router.post("/pipeline/version/select")
def select_version(req: SelectVersionRequest) -> Dict:
    state = storage.load_state()
    state["active_versions"][req.step] = req.version
    storage.save_state(state)
    return {"message": "selected"}


@router.delete("/pipeline/versions/{step}/{version}")
def delete_version(step: str, version: str) -> Dict:
    storage.delete_version(step, version)
    return {"message": "deleted"}


@router.get("/pipeline/content/{step}/{version}")
def get_content(step: str, version: str) -> Dict:
    return {"content": storage.get_content(step, version)}


@router.get("/pipeline/codegen-input")
def codegen_input() -> CodeGenInputPayload:
    state = storage.load_state()
    solution_v = state.get("active_versions", {}).get("solution", "")
    arch_v = state.get("active_versions", {}).get("architecture", "")
    coding_v = state.get("active_versions", {}).get("coding", "")

    return CodeGenInputPayload(
        solution_markdown=storage.get_content("solution", solution_v) if solution_v else "",
        architecture_markdown=storage.get_content("architecture", arch_v) if arch_v else "",
        all_code_markdown=storage.all_code_as_markdown(coding_v) if coding_v else "",
    )
