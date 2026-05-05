from __future__ import annotations

import time
from typing import Any, Dict, Tuple

import httpx

STEP_PROMPTS = {
    'requirements': '请输出需求分析文档（Markdown），包含目标、范围、用户故事、验收标准。',
    'solution': '请输出技术方案设计文档（Markdown），包含技术选型、模块划分、数据流、风险。',
    'architecture': '请输出软件架构设计文档（Markdown），包含架构图说明、分层、接口契约、部署方案。',
    'coding': '请输出完整代码文件。请使用 markdown fenced code block，并把代码块语言标签写成文件路径，例如 ```backend/main.py。',
    'review': '请输出代码评审意见（Markdown），包含问题级别、修改建议和优先级。',
    'delivery': '请输出交付集成与上线指引（Markdown），包含构建、部署、验证与回滚。',
}


async def call_llm(config: Dict[str, str], step: str, user_input: str) -> Tuple[str, Dict[str, Any]]:
    url = config.get('base_url', '').rstrip('/')
    api_key = config.get('api_key', '')
    model = config.get('model', '')
    if not url or not api_key or not model:
        raise ValueError('LLM 配置不完整')

    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': STEP_PROMPTS[step]},
            {'role': 'user', 'content': user_input},
        ],
        'temperature': 0.2,
    }

    started = time.time()
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f'{url}/chat/completions',
            headers={'Authorization': f'Bearer {api_key}'},
            json=payload,
        )
    duration_ms = int((time.time() - started) * 1000)
    resp.raise_for_status()
    data = resp.json()
    content = data['choices'][0]['message']['content']

    log = {
        'step': step,
        'request_chars': len(user_input),
        'response_chars': len(content or ''),
        'duration_ms': duration_ms,
        'model': model,
    }
    return content, log
