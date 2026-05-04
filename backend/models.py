from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    provider: str = "openai"
    api_base: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.2
    max_tokens: int = 4096


class PipelineStepRequest(BaseModel):
    step: str
    prompt: str
    source_version: Optional[str] = None


class StepOutput(BaseModel):
    content: str
    files: Dict[str, str] = Field(default_factory=dict)


class VersionInfo(BaseModel):
    version: str
    created_at: str
    step: str


class HumanDecision(BaseModel):
    step: str
    action: str  # proceed | revise
    comment: str = ""


class SaveEditableRequest(BaseModel):
    step: str
    version: str
    content: str


class SelectVersionRequest(BaseModel):
    step: str
    version: str


class Metrics(BaseModel):
    total_calls: int = 0
    success_calls: int = 0
    failed_calls: int = 0
    avg_latency_ms: float = 0.0
    last_error: str = ""


class CodeGenInputPayload(BaseModel):
    solution_markdown: str
    architecture_markdown: str
    all_code_markdown: str
