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
