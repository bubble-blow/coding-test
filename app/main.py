from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.services.llm import call_llm
from app.services.storage import (
    STEPS,
    collect_all_code_markdown,
    load_state,
    next_version_id,
    parse_code_blocks_to_files,
    persist_step_output,
    save_state,
)

app = FastAPI(title='AI Coding Platform')
app.mount('/web', StaticFiles(directory='web'), name='web')


class LLMConfig(BaseModel):
    base_url: str
    api_key: str
    model: str


class StepRunReq(BaseModel):
    step: str
    input_text: str
    base_version: Optional[int] = None


class VersionActionReq(BaseModel):
    step: str
    version_id: int
    action: str
    feedback: Optional[str] = None


@app.get('/')
def index() -> FileResponse:
    return FileResponse(Path('web/index.html'))


@app.get('/api/state')
def get_state() -> Dict[str, Any]:
    return load_state()


@app.post('/api/llm/config')
def set_config(cfg: LLMConfig) -> Dict[str, Any]:
    state = load_state()
    state['llm_config'] = cfg.model_dump()
    save_state(state)
    return {'ok': True}


@app.post('/api/step/run')
async def run_step(req: StepRunReq) -> Dict[str, Any]:
    if req.step not in STEPS:
        raise HTTPException(400, 'invalid step')

    state = load_state()
    step_state = state['steps'][req.step]

    final_input = req.input_text
    if req.step == 'coding':
        solution = selected_output(state, 'solution')
        architecture = selected_output(state, 'architecture')
        all_code = collect_all_code_markdown()
        final_input = (
            '## 方案设计\n' + solution + '\n\n'
            '## 架构设计\n' + architecture + '\n\n'
            '## 现有代码\n' + all_code + '\n\n'
            '## 编码任务\n' + req.input_text
        )

    try:
        output, log = await call_llm(state['llm_config'], req.step, final_input)
    except Exception as e:
        state['monitor_logs'].append({'step': req.step, 'error': str(e)})
        save_state(state)
        raise HTTPException(500, str(e))

    ver = next_version_id(step_state)
    files = parse_code_blocks_to_files(output) if req.step == 'coding' else {}
    persisted = persist_step_output(req.step, ver, output, files=files, base_version=req.base_version)

    version = {
        'id': ver,
        'input': req.input_text,
        'output': output,
        'status': 'generated',
        'feedback': '',
        'persisted': persisted,
    }
    step_state['input'] = req.input_text
    step_state['versions'].append(version)
    state['monitor_logs'].append(log)
    save_state(state)
    return {'ok': True, 'version': version}


@app.post('/api/step/version/action')
def version_action(req: VersionActionReq) -> Dict[str, Any]:
    state = load_state()
    step_state = state['steps'][req.step]
    versions = step_state['versions']
    version = next((v for v in versions if v['id'] == req.version_id), None)
    if not version:
        raise HTTPException(404, 'version not found')

    if req.action == 'select':
        step_state['selected_version'] = req.version_id
        version['status'] = 'selected'
        auto_fill_next_input(state, req.step, version['output'])
    elif req.action == 'revise':
        version['status'] = 'needs_revision'
        version['feedback'] = req.feedback or ''
    elif req.action == 'delete':
        step_state['versions'] = [v for v in versions if v['id'] != req.version_id]
        if step_state['selected_version'] == req.version_id:
            step_state['selected_version'] = None
    else:
        raise HTTPException(400, 'invalid action')

    save_state(state)
    return {'ok': True}


def selected_output(state: Dict[str, Any], step: str) -> str:
    sid = state['steps'][step].get('selected_version')
    if not sid:
        return ''
    for v in state['steps'][step]['versions']:
        if v['id'] == sid:
            return v['output']
    return ''


def auto_fill_next_input(state: Dict[str, Any], step: str, output: str) -> None:
    idx = STEPS.index(step)
    if idx + 1 >= len(STEPS):
        return
    nxt = STEPS[idx + 1]
    if state['steps'][nxt]['input'].strip():
        return
    state['steps'][nxt]['input'] = output
