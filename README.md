# AI Coding 开发平台

一个基于 Python + 浏览器前端的端到端 AI Coding 流水线平台，覆盖：

- 需求分析
- 方案设计
- 架构设计
- 代码编写
- 代码评审
- 交付集成

## 运行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

打开：`http://127.0.0.1:8000`

## 目录

- `app.py`: Flask 后端（网页资源与功能接口）
- `templates/index.html`: 单页前端
- `static/app.js`: 页面逻辑
- `static/style.css`: 页面样式
- `data/`: 运行期数据
  - `data/versions/<stage>/vN`: 各阶段版本化文档与代码
  - `data/llm_logs`: LLM 调用监控日志

## 说明

- 设计为“单会话、跨版本”模式，不区分会话，仅区分版本。
- 文档与代码按阶段输出契约保存。
- 支持历史版本查看、选定、删除。
- 支持人工闸门：每一步结束后人工决定“进入下一步”或“要求修改”。
- 进入后一步骤后仍可重跑前一步，形成回退能力。
