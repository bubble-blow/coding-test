import json
import shutil
from datetime import datetime, UTC
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path("generated")
DOC_ROOT = ROOT / "docs"
CODE_ROOT = ROOT / "code"
STATE_FILE = ROOT / "state.json"

STEPS = ["requirement", "solution", "architecture", "coding", "review", "delivery"]
EDITABLE_STEPS = {"requirement", "solution", "architecture"}
VERSIONED_STEPS = {"solution", "architecture", "coding"}


class Storage:
    def __init__(self) -> None:
        DOC_ROOT.mkdir(parents=True, exist_ok=True)
        CODE_ROOT.mkdir(parents=True, exist_ok=True)
        ROOT.mkdir(parents=True, exist_ok=True)
        if not STATE_FILE.exists():
            self.save_state(
                {
                    "llm_config": {},
                    "metrics": {
                        "total_calls": 0,
                        "success_calls": 0,
                        "failed_calls": 0,
                        "avg_latency_ms": 0.0,
                        "last_error": "",
                    },
                    "active_versions": {},
                    "gates": {step: "idle" for step in STEPS},
                }
            )

    def load_state(self) -> Dict:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))

    def save_state(self, state: Dict) -> None:
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def new_version(self, step: str) -> str:
        return datetime.now(UTC).strftime(f"{step}-%Y%m%d%H%M%S")

    def step_dir(self, step: str, version: str) -> Path:
        base = CODE_ROOT if step == "coding" else DOC_ROOT
        p = base / step / version
        p.mkdir(parents=True, exist_ok=True)
        return p

    def write_step_content(self, step: str, version: str, content: str) -> None:
        d = self.step_dir(step, version)
        (d / "content.md").write_text(content, encoding="utf-8")

    def write_code_files(self, version: str, files: Dict[str, str], source_version: Optional[str]) -> None:
        target = self.step_dir("coding", version)
        if source_version:
            src = CODE_ROOT / "coding" / source_version
            if src.exists():
                for f in src.rglob("*"):
                    if f.is_file():
                        rel = f.relative_to(src)
                        out = target / rel
                        out.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(f, out)

        for path, content in files.items():
            out = target / path
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(content, encoding="utf-8")

    def get_content(self, step: str, version: str) -> str:
        base = CODE_ROOT if step == "coding" else DOC_ROOT
        f = base / step / version / "content.md"
        return f.read_text(encoding="utf-8") if f.exists() else ""

    def list_versions(self, step: str) -> List[Dict]:
        base = CODE_ROOT if step == "coding" else DOC_ROOT
        root = base / step
        if not root.exists():
            return []
        versions = []
        for d in sorted(root.iterdir(), key=lambda x: x.name, reverse=True):
            if d.is_dir():
                versions.append({"version": d.name, "created_at": d.name.split("-", 1)[-1], "step": step})
        return versions

    def delete_version(self, step: str, version: str) -> None:
        base = CODE_ROOT if step == "coding" else DOC_ROOT
        shutil.rmtree(base / step / version, ignore_errors=True)

    def all_code_as_markdown(self, version: str) -> str:
        root = CODE_ROOT / "coding" / version
        if not root.exists():
            return ""
        sections = []
        for f in sorted(root.rglob("*")):
            if f.is_file():
                rel = f.relative_to(root)
                text = f.read_text(encoding="utf-8", errors="ignore")
                sections.append(f"## File: {rel}\n```\n{text}\n```")
        return "\n\n".join(sections)
