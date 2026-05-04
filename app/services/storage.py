from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

DATA_DIR = Path('data')
STATE_FILE = DATA_DIR / 'state.json'
DOC_ROOT = DATA_DIR / 'documents'
CODE_ROOT = DATA_DIR / 'code'

STEPS = ['requirements', 'solution', 'architecture', 'coding', 'review', 'delivery']


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DOC_ROOT.mkdir(parents=True, exist_ok=True)
    CODE_ROOT.mkdir(parents=True, exist_ok=True)
    for step in STEPS:
        (DOC_ROOT / step).mkdir(parents=True, exist_ok=True)
        (CODE_ROOT / step).mkdir(parents=True, exist_ok=True)


def _default_state() -> Dict[str, Any]:
    return {
        'llm_config': {'base_url': '', 'api_key': '', 'model': ''},
        'steps': {s: {'input': '', 'versions': [], 'selected_version': None} for s in STEPS},
        'monitor_logs': [],
    }


def load_state() -> Dict[str, Any]:
    ensure_dirs()
    if not STATE_FILE.exists():
        state = _default_state()
        save_state(state)
        return state
    return json.loads(STATE_FILE.read_text(encoding='utf-8'))


def save_state(state: Dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')


def next_version_id(step_state: Dict[str, Any]) -> int:
    return len(step_state['versions']) + 1


def persist_step_output(step: str, version_id: int, text_output: str, files: Optional[Dict[str, str]] = None, base_version: Optional[int] = None) -> Dict[str, Any]:
    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    doc_dir = DOC_ROOT / step / f'v{version_id}'
    code_dir = CODE_ROOT / step / f'v{version_id}'
    doc_dir.mkdir(parents=True, exist_ok=True)
    code_dir.mkdir(parents=True, exist_ok=True)

    if base_version is not None:
        src_doc = DOC_ROOT / step / f'v{base_version}'
        src_code = CODE_ROOT / step / f'v{base_version}'
        if src_doc.exists():
            _copy_dir(src_doc, doc_dir)
        if src_code.exists():
            _copy_dir(src_code, code_dir)

    doc_path = doc_dir / f'{step}_{timestamp}.md'
    doc_path.write_text(text_output, encoding='utf-8')

    saved_files = []
    if files:
        for rel, content in files.items():
            safe_rel = rel.strip().lstrip('/').replace('..', '')
            out = code_dir / safe_rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(content, encoding='utf-8')
            saved_files.append(str(out))

    return {'doc_path': str(doc_path), 'code_dir': str(code_dir), 'saved_files': saved_files}


def _copy_dir(src: Path, dst: Path) -> None:
    for p in src.rglob('*'):
        rel = p.relative_to(src)
        target = dst / rel
        if p.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)


def parse_code_blocks_to_files(text: str) -> Dict[str, str]:
    # 格式: ```path/to/file.py\n...\n```
    result: Dict[str, str] = {}
    pattern = re.compile(r'```([^\n`]+)\n(.*?)```', re.S)
    for m in pattern.finditer(text):
        filename = m.group(1).strip()
        content = m.group(2).rstrip()
        if '/' in filename or '.' in filename:
            result[filename] = content
    return result


def collect_all_code_markdown() -> str:
    parts: List[str] = []
    for root in [CODE_ROOT]:
        if not root.exists():
            continue
        for file in sorted(root.rglob('*')):
            if file.is_file():
                rel = file.relative_to(DATA_DIR)
                lang = file.suffix.lstrip('.') or 'text'
                parts.append(f'### {rel}\n```{lang}\n{file.read_text(encoding="utf-8", errors="ignore")}\n```')
    return '\n\n'.join(parts)
