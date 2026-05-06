# 自动回归与可观测性面板设计文档

## 1. 背景

本项目原有流程由用户手动依次执行 `requirements -> solution -> architecture -> coding -> review -> delivery`。其中 `coding` 和 `review` 之间需要人工根据评审意见点击“要求修改”或重新执行，缺少自动修复闭环；同时运行日志只有简单状态，无法查看耗时、Token、成功率等指标。

本次新增两个模块：

- 自动回归：一次触发后自动执行 `coding -> review`，评审失败时把 review 意见作为下一轮 coding 修改要求，直到通过或达到最大重试次数。
- 可观测性面板：记录每次阶段运行的状态、耗时、Token、版本号和失败原因，并在前端展示总览、按阶段统计和最近运行。

## 2. 自动回归模块设计

### 2.1 功能目标

自动回归用于减少 `coding` 与 `review` 之间的人工操作，适合在 `requirements`、`solution`、`architecture` 已经生成并选中的情况下使用。

当前自动回归包含两个阶段：

```text
coding -> review
```

如果 review 未通过，则进入下一轮：

```text
coding -> review -> coding -> review ...
```

终止条件：

- review 输出 `结论: PASS`
- 达到最大重试次数
- 某次 LLM 调用失败或超时

### 2.2 后端接口

接口位置：

```text
app.py -> api_auto_regression()
POST /api/auto-regression
```

请求体：

```json
{
  "input": "本轮编码目标",
  "max_retries": 1
}
```

响应示例：

```json
{
  "ok": true,
  "passed": true,
  "attempts": 1,
  "history": [
    {
      "attempt": 1,
      "coding_version": "coding-v4",
      "review_version": "review-v6",
      "passed": true
    }
  ]
}
```

### 2.3 核心流程

核心函数：

```text
app.py -> api_auto_regression()
app.py -> execute_step_core()
app.py -> review_passed()
```

流程说明：

1. 读取用户输入 `base_input` 和最大重试次数 `max_retries`。
2. 第 1 轮执行 `coding`，并自动选中新生成的 coding 版本。
3. 执行 `review`，并自动选中新生成的 review 版本。
4. 调用 `review_passed()` 判断评审是否通过。
5. 如果通过，保存状态并返回成功结果。
6. 如果失败，把 review 内容拼接为下一轮 coding 修改要求。
7. 重复执行，直到通过、重试次数耗尽或 LLM 调用失败。

核心代码摘要：

```python
for attempt in range(1, max_retries + 2):
    coding_result = execute_step_core(
        state,
        "coding",
        next_input,
        mode="auto_regression",
        attempt=attempt,
        auto_select=True,
    )

    review_result = execute_step_core(
        state,
        "review",
        review_input,
        mode="auto_regression",
        attempt=attempt,
        auto_select=True,
    )

    passed = review_passed(review_result["version"]["content"])
    if passed:
        save_state(state)
        return jsonify({
            "ok": True,
            "passed": True,
            "attempts": attempt,
            "history": history,
        })

    next_input = (
        f"{base_input}\n\n"
        f"## 自动回归第 {attempt} 轮评审反馈\n"
        f"{review_text}\n\n"
        "请修复以上评审指出的问题..."
    )
```

### 2.4 Review 通过判断

最初版本使用关键词判断，容易因为 `风险`、`bug`、`需修复` 等普通词误判失败。现在已改为优先解析结构化结论：

```text
结论: PASS
结论: FAIL
```

评审提示词要求：

```text
请在评审结果第一行严格输出“结论: PASS”或“结论: FAIL”。
只有存在阻塞上线的问题时才输出“结论: FAIL”；
非阻塞优化建议、代码风格建议、可后续迭代的问题不影响通过。
```

核心代码：

```python
def review_passed(review_text: str) -> bool:
    text = review_text.lower()
    first_lines = "\n".join(review_text.strip().splitlines()[:5])
    if re.search(r"结论\s*[:：]\s*PASS\b", first_lines, re.IGNORECASE):
        return True
    if re.search(r"结论\s*[:：]\s*FAIL\b", first_lines, re.IGNORECASE):
        return False

    fail_markers = ["必改", "阻塞上线", "严重", "语法错误", "无法运行", "未实现"]
    pass_markers = ["未发现问题", "无明显问题", "可以通过", "通过评审", "无阻塞问题", "没有发现"]
    if any(marker in review_text for marker in fail_markers) or "fatal error" in text:
        return False
    return any(marker in review_text for marker in pass_markers)
```

### 2.5 Prompt 控制优化

自动回归测试中曾出现第 3 轮 LLM 超时，原因是 prompt 过长。旧逻辑会读取 `data/code` 下所有历史 coding 版本，导致每轮代码上下文膨胀。

现已改为只读取当前选中的 coding 版本：

```text
app.py -> build_code_markdown(version_id)
```

核心代码：

```python
def prepare_step_input(state: Dict, step: str, input_text: str) -> str:
    if step in ["coding", "review"]:
        input_text += "\n\n## 方案设计\n" + selected_content(state, "solution")
        input_text += "\n\n## 架构设计\n" + selected_content(state, "architecture")
        input_text += "\n\n## 现有代码\n" + build_code_markdown(state.get("selected", {}).get("coding"))
    return input_text
```

同时跳过二进制文件和缓存目录，避免 `.pyc` 造成 UTF-8 解码失败：

```python
if "__pycache__" in rel.parts or f.suffix.lower() in skip_suffixes:
    continue
```

## 3. 可观测性面板设计

### 3.1 功能目标

可观测性面板用于回答这些问题：

- 一共执行了多少次 LLM 阶段？
- 成功率是多少？
- 平均耗时是多少？
- 总 Token 消耗是多少？
- 最近哪些阶段执行成功或失败？
- 自动回归每一轮生成了哪个版本？

### 3.2 数据存储

运行记录存储在：

```text
data/state.json -> pipeline_runs
```

单条记录结构：

```json
{
  "id": "42914ab0-a87d-422d-b269-b9734918e6be",
  "step": "review",
  "mode": "manual",
  "started_at": "2026-05-06T07:46:11.331237+00:00",
  "ended_at": "2026-05-06T07:46:54.803264+00:00",
  "duration_ms": 43472,
  "status": "ok",
  "model": "ep-20260423223203-k4sbx",
  "usage": {
    "prompt_tokens": 36022,
    "completion_tokens": 1325,
    "total_tokens": 37347
  },
  "version_id": "review-v6"
}
```

字段说明：

- `step`：阶段名，如 `coding`、`review`
- `mode`：运行模式，`manual` 或 `auto_regression`
- `attempt`：自动回归第几轮，手动执行没有该字段
- `duration_ms`：阶段耗时
- `status`：`ok` 或 `error`
- `usage`：LLM 返回的 Token 用量
- `version_id`：本次生成的版本号
- `error`：失败时的错误信息

### 3.3 后端统计聚合

接口：

```text
GET /api/state
```

该接口会附加：

```text
observability
```

核心函数：

```text
app.py -> build_observability()
```

返回结构：

```json
{
  "totals": {
    "runs": 10,
    "success": 8,
    "failed": 2,
    "duration_ms": 123456,
    "tokens": 456789,
    "avg_duration_ms": 12345,
    "success_rate": 0.8
  },
  "by_step": {
    "coding": {
      "runs": 4,
      "success": 3,
      "failed": 1,
      "avg_duration_ms": 131000,
      "success_rate": 0.75,
      "tokens": 298266
    }
  },
  "recent_runs": []
}
```

核心代码摘要：

```python
def build_observability(state: Dict) -> Dict:
    runs = state.get("pipeline_runs", [])
    by_step = {}
    totals = {"runs": len(runs), "success": 0, "failed": 0, "duration_ms": 0, "tokens": 0}

    for run in runs:
        step = run.get("step", "")
        item = by_step.setdefault(step, {"runs": 0, "success": 0, "failed": 0, "duration_ms": 0, "tokens": 0})
        item["runs"] += 1
        totals["duration_ms"] += int(run.get("duration_ms", 0) or 0)
        tokens = int((run.get("usage") or {}).get("total_tokens", 0) or 0)
        totals["tokens"] += tokens
        item["tokens"] += tokens
```

### 3.4 前端展示

前端入口：

```text
frontend/index.html -> 可观测性面板区域
frontend/app.js -> renderObservability()
```

展示内容：

- 总运行次数
- 成功率
- 平均耗时
- Token 总量
- 按阶段统计表
- 最近运行记录表

自动回归触发入口：

```text
frontend/app.js -> autoRegression()
```

核心代码摘要：

```javascript
async function autoRegression() {
  const input = auto_input.value || "";
  const max_retries = Number(auto_retries.value || 2);
  auto_result.textContent = "自动回归执行中...";
  const result = await api('/api/auto-regression', 'POST', { input, max_retries });
  auto_result.textContent = JSON.stringify(result, null, 2);
  await refresh();
}
```

## 4. 测试结果

### 4.1 自动回归失败路径测试

测试时间：

```text
2026-05-05
```

结果：

```text
第 1 轮 coding 成功 -> coding-v2
第 1 轮 review 成功 -> review-v3，未通过
第 2 轮 coding 成功 -> coding-v3
第 2 轮 review 成功 -> review-v4，未通过
第 3 轮 coding 超时失败
```

失败原因：

```text
HTTPSConnectionPool(host='ark.cn-beijing.volces.com', port=443): Read timed out. (read timeout=600)
```

结论：

- 自动回归机制可以正确执行 `coding -> review`
- 可以根据 review 结果进入下一轮
- 可以记录每轮耗时、Token、版本和错误
- 当 prompt 过长时，LLM 可能超时

### 4.2 结构化 PASS/FAIL 判断测试

本地样例测试结果：

```text
结论: PASS -> True
结论：FAIL -> False
无阻塞问题，可以通过 -> True
存在风险但非阻塞优化建议 -> False
存在语法错误 -> False
```

结论：

- 固定结论 `结论: PASS/FAIL` 能优先被解析
- 未输出固定结论时，关键词兜底仍可工作
- 失败词已收窄，减少普通建议导致误判失败的概率

### 4.3 真实 PASS 测试

为获得真实 PASS，先修复了 `review-v5` 指出的两个阻塞问题：

- `data/code/coding-v4/main.py`：补全 `flow-control` 分支和命令行入口
- `data/code/coding-v4/index.html`：删除 `btn-follow` 前多余的 `<`

验证：

```text
python3 -m compileall data/code/coding-v4
```

结果：

```text
coding-v4 下 Python 文件编译通过
```

随后重新执行 review，生成：

```text
review-v6
结论: PASS
```

本次 review 运行记录：

```json
{
  "step": "review",
  "mode": "manual",
  "status": "ok",
  "duration_ms": 43472,
  "usage": {
    "prompt_tokens": 36022,
    "completion_tokens": 1325,
    "total_tokens": 37347
  },
  "version_id": "review-v6"
}
```

当前选中版本：

```json
{
  "requirements": "requirements-v2",
  "solution": "solution-v1",
  "architecture": "architecture-v1",
  "coding": "coding-v4",
  "review": "review-v6",
  "delivery": null
}
```

结论：

- 真实 LLM review 已返回 `结论: PASS`
- 可观测性面板能记录本次成功运行
- 当前代码版本和评审版本已形成一次成功闭环

## 5. 使用说明

启动服务：

```bash
cd /home/littledavid/coding-test
.venv/bin/python app.py
```

打开页面：

```text
http://127.0.0.1:8000
```

自动回归测试建议：

1. 确认已选中 `requirements`、`solution`、`architecture`
2. 在“自动回归”区域输入本轮目标
3. 最大重试次数建议先设为 `0` 或 `1`
4. 点击“启动自动回归”
5. 在“可观测性面板 -> 最近运行”查看运行结果
6. 在 `coding` 和 `review` 阶段查看新生成版本

查看历史结果：

```text
data/state.json -> pipeline_runs
data/state.json -> steps.coding
data/state.json -> steps.review
data/code/<coding-version>/
```

## 6. 已知限制与后续优化

当前限制：

- 自动回归仍是同步 HTTP 请求，长时间运行时前端请求会一直等待
- coding 阶段仍可能生成较大输出，长上下文下仍有超时风险
- 目前没有停止按钮
- 可观测性依赖 LLM 返回 `usage` 字段，如果供应商不返回 usage，则 Token 统计为 0
- 运行过程没有后台任务 ID，刷新页面后只能看已完成的记录

后续建议：

- 将自动回归改为后台任务，前端轮询任务状态
- 增加停止自动回归按钮
- 增加 prompt 体积估算和上下文裁剪
- 增加只选择相关文件的代码索引
- 对 `/api/state` 中的 `api_key` 做脱敏
- 为自动回归增加独立的运行汇总对象，保存最终 passed、attempts 和 history
