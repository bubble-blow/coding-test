# AI Coding 开发平台（MVP）

## 启动
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

浏览器打开 `http://127.0.0.1:8000`

## 功能覆盖
- Python后端 + 浏览器前端。
- 流水线：需求分析/方案设计/架构设计/代码编写/代码评审/交付集成。
- 人工决策：每一步可 approve 或 revise。
- 历史版本：方案/架构/编码支持查看、选定、删除历史版本。
- 输出可编辑：需求/方案/架构输出可修改保存。
- 版本目录：文档在 `generated/docs`，代码在 `generated/code`，按 step/run_id 分版本。
- 版本迭代复制：编码步骤支持从源版本复制未修改文件。
