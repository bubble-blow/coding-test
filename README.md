# AI Coding 开发平台（MVP）

一个基于 **Python + FastAPI** 的端到端 AI Coding 平台，目标交付为前端网页应用。

## 功能概览

- LLM API 配置（Base URL / API Key / Model）
- Pipeline 步骤：
  - 需求分析
  - 方案设计
  - 架构设计
  - 代码编写
  - 代码评审
  - 交付集成
- 每步支持：输入、执行、输出版本列表（选定 / 要求修改 / 删除）
- 前序步骤可回退并重新执行
- “选定”结果自动注入下一步输入
- LLM API 调用监控（请求/响应摘要、耗时、错误）
- 文档与代码按步骤与版本落盘管理

## 运行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

打开浏览器：

- http://127.0.0.1:8000/

## 目录

- `app/main.py`: FastAPI 服务与 API
- `app/services/llm.py`: LLM 调用与步骤提示词
- `app/services/storage.py`: 版本与文件持久化
- `web/index.html`: 前端页面
- `web/app.js`: 前端逻辑
- `web/style.css`: 页面样式
- `data/`: 运行时输出目录（自动创建）

## 说明

- 当前实现为 MVP，不含用户会话隔离（按题意“不区分会话”）。
- 调用 LLM 时不维护历史对话列表。
- 代码编写步骤会附带方案/架构文档和现有全部代码（Markdown 拼接）作为上下文。
