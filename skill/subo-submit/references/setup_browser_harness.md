# 一次性安装 browser-harness 并连接 Chrome

`browser-harness`（<https://github.com/browser-use/browser-harness>）是一个轻量的 CDP 桥，让 Python 直接控制用户已经登录飞书的真实 Chrome。两个 skill 都依赖它，第一次用前装一次。

## 先决条件

- macOS / Linux
- 已装 [`uv`](https://docs.astral.sh/uv/) (`brew install uv` 或官方 install 脚本)
- Chrome 已经登录用户的飞书账号（飞书 Wiki 是登录后才能访问的）

## 安装

```bash
mkdir -p ~/Developer && cd ~/Developer
git clone https://github.com/browser-use/browser-harness
cd browser-harness
uv tool install -e .
command -v browser-harness   # 应输出 /Users/<you>/.local/bin/browser-harness 之类
```

## 连接到正在跑的 Chrome

```bash
browser-harness -c "print(page_info())"
```

第一次运行：
- macOS：会自动尝试 `chrome://inspect/#remote-debugging`，请在 Chrome 弹窗里点「允许」
- 后续：直接连上去，不再弹窗

如果 Chrome 把请求挡在「会话失效」之类的页面，让 `browser-harness` 切回真实 tab：

```bash
browser-harness -c "ensure_real_tab(); print(page_info())"
```

## 排错

- `command not found: browser-harness` — 重新跑 `uv tool install -e .`
- 连不上 Chrome — 关掉所有 Chrome 进程后重开一次，再跑命令
- 被切到别的 tab — 在脚本开头先 `new_tab(url)` 强制开新页
