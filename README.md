# AI Coding 开发平台（MVP）

## 运行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

浏览器打开 http://localhost:8000

## 功能覆盖
- Python 后端 + 浏览器前端
- LLM 配置、流水线步骤、版本管理（选定/要求修改/删除）
- 输出可编辑，选定后自动填充下一步输入
- 代码版本落盘、迭代版本未修改文件自动复制
- 代码评审、交付集成步骤支持
- 交付集成：输入 URL 子路径，复制代码到 `public/` 并提供预览链接


## LLM 配置说明
- `base_url`：OpenAI兼容接口根路径（示例：`https://api.openai.com/v1`）
- `api_key`：接口密钥
- `model`：模型名（示例：`gpt-4.1-mini`）
- 执行步骤时会调用 `POST {base_url}/chat/completions`。
