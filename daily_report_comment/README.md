## 飞书日报 Comment 自动提交

**目标**：计算昨天的日期，启动飞书日报 comment 提交脚本，处理 LLM_BATCH_REQUEST 信号（用当前 Claude 会话批量生成所有成员的评论），等待脚本弹出确认弹窗后通知用户。

**执行步骤**：

### 1. 计算昨天日期

用 bash 计算昨日 MMDD：
```bash
date -v-1d +%m%d
```

### 2. 启动脚本

使用 `mcp__Desktop_Commander__start_process` 运行：

```
command: /Users/tyc/Developer/browser-harness/.venv/bin/python3 /Users/tyc/browser_cowork/daily_report_comment/submit_feishu.py --date {YESTERDAY} --url https://b3sh6jivuw.feishu.cn/docx/N55YdbMsCoUFdvxz6oucR4gxn3d
timeout_ms: 30000
```

### 3. 轮询输出并处理 LLM_BATCH_REQUEST

使用 `mcp__Desktop_Commander__read_process_output(pid, timeout_ms=20000)` 轮询输出，处理以下情况：

#### 🔁 收到 `[LLM_BATCH_REQUEST:/path/to/_llm_request_batch.json]`

这是脚本委托当前 Claude 会话**批量**生成所有成员评论的信号。处理步骤：

1. 用 `mcp__Desktop_Commander__read_file` 读取 request 文件（路径从信号中提取）
2. 文件是 JSON，包含字段：`temp_rules`、`n`、`items`
   - `items` 是数组，每个元素包含：`member_name`、`full_text`、`prompt`、`n`
3. **遍历 `items`，用每个元素的 `prompt` 字段作为输入，逐一生成评论**：
   - 每人生成恰好 `n` 条建议
   - 每条不超过 40 字，口语化，像真人 leader 写的
   - 每条单独一行，不加编号或前缀
4. 将所有结果**一次性**写入同目录的 `_llm_response_batch.json`：
   ```json
   {"results": {"王牧天": ["评论1"], "王凯": ["评论2"], "李琳": ["评论3"]}}
   ```
   使用 `mcp__Desktop_Commander__write_file` 写入（路径为 request 文件同目录 + `_llm_response_batch.json`）
5. 继续轮询，等待下一个信号或最终结果

#### ✅ 收到 `弹窗已弹出`

告知用户：「✅ 昨日（{YESTERDAY}）飞书日报 comment 弹窗已弹出（{N} 条建议），请切换到飞书页面，确认后点击「确定」按钮，脚本将自动批量提交。」然后继续轮询等待最终结果。

#### ✅ 收到 `✅ 完成`

提取成功/失败数，汇报结果。

#### ✗ 收到 `✗ 无可提交内容`

告知用户昨日暂无日报内容，无需操作。

#### `exit code != 0` 或超时

汇报错误信息。

### 4. 常见错误处理

| 错误 | 处理 |
|------|------|
| `找不到文档 tab` | 告知用户需先在 Chrome 中打开飞书文档 |
| `大纲加载失败` | 告知用户刷新飞书页面后重试 |
| `已有实例在运行 (PID N)` | 告知用户执行 `kill N` 后重试 |
| `等待 Claude Desktop 批量响应超时` | 说明 LLM_BATCH_REQUEST 未及时处理，检查轮询是否正常 |

### 前提条件

- Chrome 已打开并登录飞书，文档 tab 存在
- 如未满足，友好提示用户手动操作后重试
