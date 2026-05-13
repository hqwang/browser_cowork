---
name: subo-submit
description: Auto-fill the Feishu "Subo 流水线表单" using a JSON file produced by the `xq-info` skill. Use this whenever the user wants to "录入 subo", "提交需求拆解", "填 subo 表单", "把 xq-info.json 灌到飞书表单里", or pastes a Feishu shrcn… form URL together with a JSON containing xqID/xqType/suboList. Filling 70+ rows by hand takes hours; this skill does it in minutes via browser-harness.
---

# subo_submit — 把 xq-info.json 自动灌进 Subo 流水线表单

## 输入

`xq-info` skill 产出的 JSON 文件，结构：

```json
{
  "xqID": "20250628602",
  "xqType": "功能型",
  "suboList": [
    {"pointType": "...", "pointPerson": "...", "spendHour": 4, "pointName": "..."}
  ]
}
```

默认读 `/tmp/xq-info.json`，可通过 `XQ_INFO_IN` 环境变量覆盖。

## 表单地址

固定为公司内部表单：<https://b3sh6jivuw.feishu.cn/share/base/form/shrcnJAnk4pUjerGBOaWHTFiJIf>

## 要做的事

1. 顶部 4 个字段（按用户原始任务定义的顺序）：
   - 「是否涉及版本计划」选 `自主迭代`（选完会动态出现 xqID 字段）
   - 「xqID」选 `XQ-{xqID}`（链接型下拉，需在搜索框输入数字过滤）
   - 「是否数据需求」选 `{功能型→功能型需求, 数据型→数据型需求}`，缺省 `#N/A`
   - 「模版名称」选 `全流程`
2. 「Subo 涉及的拆解」表格逐条录入，每条 4 字段：
   - 节点序号（下拉）= `pointType`
   - 拆解工时估分PH（输入）= `spendHour`
   - 节点负责人（成员选择器）= `pointPerson`
   - 节点名称（富文本）= `pointName`
3. 第一行表格里已经有空行，直接填；之后每写完一条点一次「+ 添加一行」再填下一条。
4. **不要点「提交」**。最后给用户截图看一眼，等他确认再让他自己点提交（提交不可逆）。

## 关键的语义映射（必须做）

不同来源对节点名称的写法略有差异，表单的下拉是权威。映射一致需要做：

| 输入 pointType | 表单实际选项 |
|---|---|
| 开发-基础数据开发 | 开发-基础数据 |
| 开发-数据平台开发 | 开发-数据开发 |
| 开发-android开发 | 开发-安卓开发 |
| 开发-iOS开发 | 开发-ios开发 |
| 上线-基础数据上线 | 上线-基础数据部上线 |
| 上线-数据平台上线 | 上线-数开上线 |
| 上线-android上线 | 上线-安卓上线 |
| 上线-iOS上线 | 上线-ios上线 |

## 「硅基化」节点的处理

输入里 `*-硅基化` 类节点（例如 `测试-服务端测试-硅基化`）在表单中**没有对应选项**。**直接跳过**，不要灌到表单里，并在最后日志里提示用户。

如果以后表单加了硅基化选项，删除 `scripts/fill_form.py` 里 `SKIP_SUBSTRINGS = ("硅基化",)` 这行即可。

## 执行流程

> **强制要求**：必须使用 `browser-harness`，禁止用 Chrome DevTools MCP 替代（MCP 连接的 Chrome 实例未登录飞书，会失败）。
> 所有调用必须加 `no_proxy='127.0.0.1,localhost'` 前缀，绕过全局代理。

```bash
# 0) 验证 Chrome 连接是否可用（每次使用前先跑这一步）
no_proxy='127.0.0.1,localhost' NO_PROXY='127.0.0.1,localhost' \
  browser-harness -c "print(page_info())" 2>&1
# 有输出（形如 {'url': ..., 'title': ...}） → 正常，继续下一步
# 报错 / 无输出 → 让用户完全退出 Chrome（Command+Q）后重新打开，再重试本步

# 1) 确保 browser-harness 已装、Chrome 已登录飞书（参见 references/setup_browser_harness.md）
no_proxy='127.0.0.1,localhost' NO_PROXY='127.0.0.1,localhost' \
  browser-harness -c "ensure_real_tab(); print(page_info())"

# 2) 跑填表脚本（一次性把全部行灌进去）
# 注意：form_helpers/mappings 是普通模块，无法直接用 runpy.run_path 注入 browser-harness globals。
# 必须手动把 js/click_at_xy/type_text 等注册到 builtins，再 exec 主脚本。
no_proxy='127.0.0.1,localhost' NO_PROXY='127.0.0.1,localhost' \
  XQ_INFO_IN=/tmp/xq_info.json \
  browser-harness -c "
import sys, builtins
sys.path.insert(0, '<skill-path>/scripts')
for _n in ['js','click_at_xy','type_text','new_tab','wait_for_load','page_info','capture_screenshot']:
    if _n in globals(): setattr(builtins, _n, globals()[_n])
exec(open('<skill-path>/scripts/fill_form.py').read())
"
```

脚本会：
1. `new_tab(form_url)` 打开表单
2. 按顺序填顶部 4 个下拉（是否涉及版本计划 → xqID → 是否数据需求 → 模版名称）
3. 滚到表格，逐条写入数据，间隔点「添加一行」
4. 每个字段独立 try/except，单字段失败不中断当前行，继续填其余列
5. 每条写完打印进度 `[i/total] pointType | hours | person | pointName`
6. 末尾输出**填充率报告**：总行数、字段填充率、缺失行及原因、手动补充提示
7. 截图保存到 `/tmp/subo_submit_review.png`，请用户核对后自行点提交

## 表单元素的脾气（写脚本时踩过的坑）

- 是否涉及版本计划默认是「解决VOC」，必须先改成「自主迭代」，才能拿到「xqID」字段。
- `xqID` 那个字段在 DOM 里是 `bitable-form__editor__link_editor`（不是普通 select）。要点开后在搜索框里输 ID 数字，再点弹出的 `XQ-xxxxxx` 选项。
- 表格 cell 是「两次点击模式」：第一次点激活 cell（出现编辑边框），第二次点才打开下拉/输入。脚本里要 `click + sleep + click`。
- 下拉面板会出现在视口顶部（`.b-select-dropdown-content reverse`），即使触发它的 cell 在下面。定位选项时**只在「当前 visible 的 panel」内部找**，否则会把别的字段的同名选项也匹配上。
- 「节点名称」单元格用的是飞书的 Ace-style 富文本编辑器（`bitable-form__editor__text_editor`），不是普通 `<input>`。脚本通过聚焦内部 `[contenteditable]` 元素并用 `document.execCommand("insertText", ...)` 注入文本最稳。
- 关闭打开的下拉面板时，**别**点表单中下方的空白（容易戳中下一个字段）。统一点 `(50, 50)` 左上角更安全。

## 已知未解决问题

- **部分成员搜索失败**（`! 节点负责人 选项未匹配`）：郭吉祥、张雨等人在飞书成员选择器中搜索无结果，原因可能是飞书昵称与文档中的写法不一致，或所在部门不在表单可选范围。脚本会跳过并在报告中列出，需手动补充。
- **首行节点序号偶发失败**：表单初始行有时处于特殊状态，重试通常可解决。

## 文件清单

- `scripts/fill_form.py` — 主脚本，一次性灌入全部行，含填充率报告
- `scripts/form_helpers.py` — 选 dropdown / 输 input / 加行 / 关闭 panel 的小工具集合
- `scripts/mappings.py` — 节点名映射 + 跳过规则
- `references/setup_browser_harness.md` — 一次性环境安装指引
