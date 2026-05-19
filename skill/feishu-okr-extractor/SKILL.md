---
name: feishu-okr-extractor
description: >
  从飞书思维导图中提取指定组织的 OKR 内容，进行结构化解析和多组织对比。
  当用户提到"飞书思维导图"、"飞书 mindnote"、"提取 OKR"、"OKR 对比"、"读取飞书 OKR"、
  "从飞书拿 OKR"、"mindmap 提取"等关键词，且涉及飞书链接或组织名称时，必须使用此 skill。
  支持公司、部门、小组、个人等任意层级的 OKR 提取，零内容关键词依赖（不需要特定子节点文本）。
---

# 飞书思维导图 OKR 提取 Skill

## 概览

本 skill 通过 browser-harness（本地 CDP 自动化）打开飞书思维导图，利用 **DOM 树结构**定位组织节点，提取完整的 OKR 子树并解析为结构化数据。

核心脚本：`scripts/extract_okr.py`

**为什么用 browser-harness 而不是 Chrome MCP**：feishu.cn 对 Chrome 扩展有内容安全策略限制，Chrome MCP 会被 Permission denied。browser-harness 通过 CDP 直连本地 Chrome，不受此限制。

---

## 前置条件

- 本机已安装 browser-harness：`/Users/tyc/Developer/browser-harness/.venv/bin/browser-harness`
- Chrome 已打开（browser-harness 连接运行中的 Chrome 实例）
- 已登录飞书（页面需要飞书认证）

---

## 核心原理：DOM 树结构定位

飞书思维导图的树层级通过嵌套的 `div.node` 元素表达（注意：不是 `div.node-wrapper`）：

```
div.node                    ← 某组织分支的根容器
  div.node-wrapper          ← 组织名标签（如"公司0512"）
  div.node.collapsed        ← 子节点容器
    div.node-wrapper        ← O1、KR1 等节点标签
    div.node
      div.node-wrapper      ← 更深层节点
```

**定位算法**：
1. 按组织名文本找到对应的 `div.node-wrapper`
2. 向上找最近的 `div.node` 父元素（即整个分支的根容器）
3. 在根容器内 `querySelectorAll('div.node-wrapper')` 得到完整子树
4. 通过计数 `div.node` 祖先数量得到相对深度

无需任何内容关键词，仅凭组织名即可定位。

---

## 使用流程

### 输入

- 飞书思维导图 URL（`https://xxx.feishu.cn/mindnotes/xxx`）
- 一个或多个组织名称（需与思维导图顶层节点文本完全匹配）

### 步骤

**第一步：运行提取脚本**

```bash
python3 /path/to/scripts/extract_okr.py \
  "https://xxx.feishu.cn/mindnotes/xxx" \
  "公司0512" "应用工程部"
```

脚本输出两个文件：
- `/tmp/okr_tree.json`：带深度的原始节点树
- `/tmp/okr_parsed.json`：解析后的 O/KR 结构（含 notes）

**第二步：读取并使用结果**

```python
import json
with open('/tmp/okr_parsed.json') as f:
    data = json.load(f)

# 结构示例：
# {
#   "公司0512": [
#     {
#       "index": 1, "weight": "25%", "text": "OA2和基于OA2的低熵化",
#       "krs": [
#         {
#           "index": 1, "weight": "70%", "text": "pWin ~ N0D1(cv, 60%)",
#           "notes": ["业财SST系统开发由谁接手...", "测试主R: 袁野"]
#         }
#       ]
#     }
#   ]
# }
```

---

## 数据结构说明

### okr_tree.json（原始树）

```json
{
  "公司0512": {
    "totalNodes": 173,
    "items": [
      {"depth": 0, "title": "公司0512"},
      {"depth": 1, "title": "【25%】O1：OA2和基于OA2的低熵化"},
      {"depth": 2, "title": "【70%】KR1: pWin ~ N0D1(cv, 60%)"},
      {"depth": 3, "title": "业财SST系统开发由谁接手..."}
    ]
  }
}
```

### okr_parsed.json（解析后）

```json
{
  "公司0512": [
    {
      "index": 1,
      "weight": "25%",
      "text": "OA2和基于OA2的低熵化",
      "krs": [
        {
          "index": 1,
          "weight": "70%",
          "text": "pWin ~ N0D1(cv, 60%)",
          "notes": [
            "业财SST系统开发由谁接手后续开发（dhn 0.3; wnb 0.5...）",
            "测试主R: 袁野"
          ]
        }
      ]
    }
  ]
}
```

**notes 字段**：KR 下的约束条件、负责人、子任务等深度 > KR 所在层的节点，全部平铺收录。notes 归属判断：顺序扫描节点，遇到 KR 记录其深度 `kr_depth`，后续 `depth > kr_depth` 的节点归入该 KR，直到下一个 O 或 KR 节点切换。

---

## 常见问题

**Q：节点文本只取第一行，会不会丢多行内容？**
A：飞书思维导图每个节点在 DOM 里是单行文本，`innerText.split('\n')[0]` 可以拿到完整节点标题。如果遇到多行节点，可改为取 `innerText.trim()`。

**Q：有节点被折叠（collapsed）怎么办？**
A：飞书的展开率通常在 99% 以上，折叠的多为说明性非 OKR 节点。如需完整提取，可在脚本中添加"点击所有 `div.node.collapsed` 展开"的步骤（见脚本注释）。

**Q：提取出来有「拖拽-移动节点」等 UI 噪声节点？**
A：脚本已过滤以「拖拽」开头的 UI 手柄节点。如有其他 UI 噪声，在 `UI_NOISE_PREFIXES` 列表中添加。

**Q：组织名匹配不到？**
A：确认组织名与思维导图顶层节点文字**完全一致**（含空格、全半角）。可先用 `page_info()` 或 `js("document.body.innerText")` 查看页面文本确认。

---

## 扩展：多组织 OKR 对比

提取多个组织后，可用 LLM 进行对比分析，输出对齐矩阵和差距分析报告。参考 `browser_cowork/okr-diff-report.html` 的报告格式。

对比分析提示词框架：
```
给定以下两个组织的 OKR：
[组织A] ...
[组织B] ...

请分析：
1. 对齐的目标（O 级别）
2. 有差距的 KR
3. 组织B 缺少覆盖的公司级目标
4. 组织B 独有的目标（超出公司范围的）
```
