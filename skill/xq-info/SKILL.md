---
name: xq-info
description: Extract structured requirement (xq) info — xqID, xqType, suboList — from a Feishu Wiki "subo 拆解 DAG 图" document and save as JSON. Use this skill whenever the user asks to "提取需求信息", "拆解 subo", "解析需求文档", or pastes/links a Feishu Wiki URL whose title contains "XQ-" or "DAG图" or "subo拆解", even if they don't say the word "skill". The output JSON is the input contract for the companion skill `subo-submit`.
---

# xq_info — 从需求拆解文档提取结构化信息

## 使命

产品经理把需求拆解写在飞书 Wiki 文档里（标题含 `XQ-{id}`，正文有「子任务拆解」表格）。这个 skill 把文档里的关键信息提取成统一的 JSON，给后续的 `subo-submit` 用。

模板示例：<https://b3sh6jivuw.feishu.cn/wiki/SIsZwCEcMioTdlk2EsNcY6dVnZb>

## 输出契约（重要）

最终保存的 JSON 长这样：

```json
{
  "xqID": "20250628602",
  "xqType": "功能型",
  "suboList": [
    {"pointType": "...", "pointPerson": "...", "spendHour": 4, "pointName": "..."}
  ]
}
```

字段语义：
- `xqID`：从标题里提取 `XQ-{xqID}` 后面的 ID 字符串。例：标题`【subo拆解DAG图】xxx XQ-20250628602` → `xqID = "20250628602"`。
- `xqType`：看「子任务拆解」段落下面列出的角色行。如果包含 `客户端 / 前端 / 服务端` 任意一个 → `功能型`；否则 → `数据型`。
- `suboList`：从「子任务拆解」段落下方的表格逐项展开。表头为「流程节点 / 节点负责人 / 估时」。
  - `pointType`：「流程节点」列原文
  - `pointPerson`：「节点负责人」列原文
  - 「估时」单元格通常包含多条任务，每条形如 `任务名{分隔符}数字单位`（如 `xxx，4WPH` / `1. xxx 4wph` / `Subo-1: xxx，4WPH` / 仅 `2WPH`）。每条任务展开为一个 subo：
    - `spendHour`：数字部分（不含单位 WPH/wph 等），整数则用 int，否则 float
    - `pointName`：任务描述部分，去掉前缀 `1.` / `Subo-N:` 和尾部数字单位
    - 若估时单元格只有数字单位无任务名，`pointName` 取该行的 `pointType`

## 关键技术点

飞书文档的表格用了 **虚拟渲染**（class `bear-virtual-renderUnit-placeholder`）：视口外的单元格不渲染，直接读 `body.innerText` 会丢掉大半数据。必须**逐行 `scrollIntoView` + 增量收集**才能拿全。完整流程在 `scripts/extract.py`。

## 工作流

> **强制要求**：必须使用 `browser-harness`，禁止用 Chrome DevTools MCP 替代（MCP 连接的 Chrome 实例未登录飞书，会失败）。
> 所有 `browser-harness` 调用必须加 `no_proxy='127.0.0.1,localhost'` 前缀，绕过全局代理。

0. **验证 Chrome 连接是否可用**（每次使用前先跑这一步）：
   ```bash
   no_proxy='127.0.0.1,localhost' NO_PROXY='127.0.0.1,localhost' \
     browser-harness -c "print(page_info())" 2>&1
   ```
   - 有输出（形如 `{'url': ..., 'title': ...}`） → 正常，继续下一步
   - 报错 / 无输出 → 让用户 **完全退出 Chrome（Command+Q）后重新打开**，再重试本步

1. **打开文档**。用 `browser-harness` 连接用户已登录的 Chrome。如果对方还没装，先按 `references/setup_browser_harness.md` 安装。
   ```bash
   no_proxy='127.0.0.1,localhost' NO_PROXY='127.0.0.1,localhost' \
     browser-harness -c "new_tab('<wiki_url>'); wait_for_load(); print(page_info())"
   ```
2. **跑提取脚本**，结果默认输出到 `/tmp/xq_info.json`：
   ```bash
   no_proxy='127.0.0.1,localhost' NO_PROXY='127.0.0.1,localhost' \
     browser-harness -c "import runpy; runpy.run_path('<skill-path>/scripts/extract.py', init_globals=globals())"
   ```
   脚本会：
   - 从 `document.title` 中正则取 `XQ-(\S+)` 作为 `xqID`
   - 找文档正文里的角色行（`服务端/前端/客户端/...`）判断 `xqType`
   - 定位 `<table>` 元素（一般有 2 个，[0] 是表头，[1] 是数据），逐 row `scrollIntoView` 让虚拟渲染挂载，把每行 cell 的 innerText 抓下来；空行（仅含零宽空格）跳过
   - 用 `parse_subo.split_items` + 正则把估时 cell 切成多条任务、各取 `pointName` 和 `spendHour`
3. **检查 unparsed**。脚本会打印没匹配的条目；如果有，说明出现了新格式，回到 `parse_subo.py` 加正则。
4. **保存输出**。打印 JSON 摘要给用户确认（节点条数、subo 总数），文件保存到约定路径。

## 常见数据校验

- 表格通常有 28 行，最后一行是「完成」（流程终点，估时为空）—— 跳过它，不进 suboList
- 估时里偶尔有笔误的单位（如 `6whh` 应为 `6wph`）—— 只取数字，不校验单位拼写
- 「Subo-N:」「1.」「2.」这些前缀都不属于任务名，需要剥离
- 任务描述里出现的中文逗号/句号/英文逗号都可以是分隔符；也存在用空格分隔的格式

## 文件清单

- `scripts/extract.py` — 直接给 browser-harness 用的提取脚本
- `scripts/parse_subo.py` — 解析估时单元格的纯 Python 函数（无浏览器依赖，可单测）
- `references/setup_browser_harness.md` — 一次性安装/连接 Chrome 指引
