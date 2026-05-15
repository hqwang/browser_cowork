#!/usr/bin/env python3
"""
submit_feishu.py  —  飞书日报 Comment 全流程脚本

用法：
    /Users/tyc/Developer/browser-harness/.venv/bin/python3 \\
        /Users/tyc/browser_cowork/daily_report_comment/submit_feishu.py \\
        --date 0513 \\
        --url  https://b3sh6jivuw.feishu.cn/docx/N55YdbMsCoUFdvxz6oucR4gxn3d

流程：
    1. 打开/切换到飞书文档 tab
    2. 提取指定日期的日报内容
    3. 根据内容生成 comment 建议，注入确认弹窗
    4. 轮询等待用户在弹窗中点击「确定」
    5. 自动批量提交全部勾选的 comment
"""

import argparse
import json
import os
import random
import re
import sys
import time
from pathlib import Path

import anthropic

# ── 进程锁：防止同时运行两个实例 ────────────────────────────────
LOCK_FILE = Path("/tmp/feishu_submit.lock")

def acquire_lock():
    if LOCK_FILE.exists():
        pid = LOCK_FILE.read_text().strip()
        # 检查该 pid 是否仍在运行
        try:
            os.kill(int(pid), 0)
            print(f"✗ 已有实例在运行（PID {pid}），请先执行：")
            print(f"     kill {pid}  或  rm {LOCK_FILE}")
            sys.exit(1)
        except (ProcessLookupError, ValueError):
            pass  # 进程已死，锁文件是残留，继续
    LOCK_FILE.write_text(str(os.getpid()))

def release_lock():
    LOCK_FILE.unlink(missing_ok=True)

# ── 加载 browser-harness ──────────────────────────────────────
VENV_BH = Path("/Users/tyc/Developer/browser-harness/src")
try:
    from browser_harness.helpers import js, cdp, wait, list_tabs, switch_tab, new_tab
    from browser_harness.admin import ensure_daemon
except ImportError:
    sys.path.insert(0, str(VENV_BH))
    from browser_harness.helpers import js, cdp, wait, list_tabs, switch_tab, new_tab
    from browser_harness.admin import ensure_daemon

SCRIPT_DIR = Path(__file__).parent


# ── 审核规则：从 日报审核规则.md 动态解析 ────────────────────────

def _load_review_rules(md_path: Path) -> dict[str, list[str]]:
    """
    解析日报审核规则.md，返回 {维度名: [子项描述, ...]} 字典。
    格式约定：
      ## 序号、维度名   → 开始一个维度
      - **子项名** 描述  → 该维度下的一条子项
      ---               → 文件正文结束，停止解析
    """
    rules: dict[str, list[str]] = {}
    current_dim: str | None = None
    for line in md_path.read_text(encoding="utf-8").splitlines():
        if line.strip() == "---":
            break
        # 匹配维度标题：## 一、目标对齐
        m = re.match(r"^##\s+[一二三四五六七八九十]+[、.]\s*(.+)", line)
        if m:
            current_dim = m.group(1).strip()
            rules[current_dim] = []
            continue
        # 匹配子项：- **名称** 描述文字
        if current_dim:
            m2 = re.match(r"^-\s+\*\*[^*]+\*\*\s+(.+)", line)
            if m2:
                desc = m2.group(1).strip()
                if not desc.endswith("？"):
                    desc += "？"
                rules[current_dim].append(desc)
    return rules


_REVIEW_RULES = _load_review_rules(SCRIPT_DIR / "日报审核规则.md")
_DIMENSION_NAMES = list(_REVIEW_RULES.keys())


def _gen_temp_rules() -> list[str]:
    """每个维度各随机抽 1 条子项，得到 len(维度) 条临时规则（共 6 条）。"""
    return [random.choice(items) for items in _REVIEW_RULES.values()]


def _gen_comments_llm(member_name: str, full_text: str, temp_rules: list[str], n: int = 1) -> list[str]:
    """调用大模型，根据日报内容和临时规则，生成 n 条有针对性的 comment。

    Args:
        member_name: 成员姓名
        full_text:   该成员当日日报全文
        temp_rules:  本轮从各维度随机抽取的临时规则列表
        n:           需要生成的 comment 数量

    Returns:
        长度恰好为 n 的字符串列表，每条不超过 40 字。
    """
    rules_text = "\n".join(f"{i + 1}. {r}" for i, r in enumerate(temp_rules))

    prompt = f"""你是一位团队 leader，正在给下属的日报写 comment。

本次审核关注点（共 {len(temp_rules)} 条，请优先围绕这些角度给建议）：
{rules_text}

{member_name} 今日日报：
{full_text}

要求：
- 针对日报中值得跟进或改进的点，给出 {n} 条建议
- 每条建议单独一行，不加编号或前缀
- 说话像真人，口语化，不要 AI 腔
- 每条不超过 40 字
- 直接输出 comment，不要任何解释"""

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=100 * n,
        messages=[{"role": "user", "content": prompt}],
    )
    lines = [ln.strip() for ln in resp.content[0].text.strip().splitlines() if ln.strip()]
    # 确保恰好 n 条：多截少补
    fallback = "今日日报请补充具体内容。"
    while len(lines) < n:
        lines.append(lines[-1] if lines else fallback)
    return lines[:n]


# ── CDP 拖选（isTrusted=true，可触发飞书工具栏）─────────────────

def drag_select(x1, y, x2, steps=8):
    cdp("Input.dispatchMouseEvent", type="mousePressed", x=x1, y=y, button="left", clickCount=1)
    for i in range(1, steps + 1):
        xi = round(x1 + (x2 - x1) * i / steps)
        cdp("Input.dispatchMouseEvent", type="mouseMoved", x=xi, y=y, button="left")
    cdp("Input.dispatchMouseEvent", type="mouseReleased", x=x2, y=y, button="left", clickCount=1)


# ── Tab 管理 ─────────────────────────────────────────────────

def open_doc(url: str):
    """切换到已有 tab，或新开 tab 并等待加载完成。"""
    keyword = url.split("feishu.cn/")[-1][:20]
    tab = next((t for t in list_tabs() if keyword in t.get("url", "")), None)
    if tab:
        switch_tab(tab)
        print(f"✓ 切换到已有 tab: {tab['title'][:50]}")
    else:
        new_tab(url)
        print("✓ 新开 tab，等待加载...")
        for _ in range(30):
            if js("document.readyState") == "complete":
                break
            wait(0.5)
        wait(2.0)


# ── 大纲加载 ─────────────────────────────────────────────────

def ensure_catalogue():
    """确保大纲已加载，坐标全部动态获取，无硬编码。"""
    if js("window.__isCatalogueLoaded && window.__isCatalogueLoaded()"):
        return True

    # 优先点 .catalogue__pin-wrapper（最可靠）
    pw = js("""(function(){
        const r = document.querySelector('.catalogue__pin-wrapper')?.getBoundingClientRect();
        return r && r.width > 0 ? {x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2)} : null;
    })()""")
    if pw:
        cdp("Input.dispatchMouseEvent", type="mousePressed",  x=pw["x"], y=pw["y"], button="left", clickCount=1)
        cdp("Input.dispatchMouseEvent", type="mouseReleased", x=pw["x"], y=pw["y"], button="left", clickCount=1)
        wait(1.2)
        if js("window.__isCatalogueLoaded && window.__isCatalogueLoaded()"):
            return True

    # fallback：hover 大纲条带触发懒加载
    pos = js("""(function(){
        const r = document.querySelector('.catalogue')?.getBoundingClientRect();
        return r ? {x: Math.round(r.left+r.width/2), y: Math.round(r.top+r.height/2)} : null;
    })()""")
    if pos:
        cdp("Input.dispatchMouseEvent", type="mouseMoved", x=pos["x"], y=pos["y"], button="none")
        wait(0.8)
        cdp("Input.dispatchMouseEvent", type="mousePressed",  x=pos["x"], y=pos["y"], button="left", clickCount=1)
        cdp("Input.dispatchMouseEvent", type="mouseReleased", x=pos["x"], y=pos["y"], button="left", clickCount=1)
        wait(1.0)

    return js("window.__isCatalogueLoaded && window.__isCatalogueLoaded()")


# ── 内容提取 + comment 生成 ───────────────────────────────────

def _nav_click(coord: dict):
    """点击大纲坐标，触发页面滚动到对应位置。"""
    cdp("Input.dispatchMouseEvent", type="mousePressed",  x=coord["x"], y=coord["y"], button="left", clickCount=1)
    cdp("Input.dispatchMouseEvent", type="mouseReleased", x=coord["x"], y=coord["y"], button="left", clickCount=1)


def _find_heading_id(date: str, name: str) -> str | None:
    """在当前 DOM 中查找指定成员的 heading3 blockId。
    优先在 heading2 锚点内查找；heading2 已滚出 DOM 时直接按名字匹配。"""
    return js(f"""(function(){{
        const ZERO=/[\\u200b\\u200c\\u200d\\ufeff\\u200e]/g, clean=t=>(t||"").replace(ZERO,"").trim();
        // 第一轮：要求 heading2 存在（精确）
        let inDate=false;
        for(const el of document.querySelectorAll("[data-block-id]")){{
            const tp=el.getAttribute("data-block-type")||"", tx=clean(el.innerText);
            if(tp==="heading2"&&tx.startsWith("{date}")){{inDate=true;continue;}}
            if(tp==="heading2"&&inDate) break;
            if(inDate&&tp==="heading3"&&tx.includes("{name}")) return el.getAttribute("data-block-id");
        }}
        // 第二轮 fallback：heading2 已滚出虚拟 DOM，直接按名字找 heading3
        for(const el of document.querySelectorAll("[data-block-type='heading3']")){{
            if(clean(el.innerText).includes("{name}")) return el.getAttribute("data-block-id");
        }}
        return null;
    }})()""")


def extract_and_build_rows(date: str, n_comments: int = 1, temp_rules: list[str] | None = None) -> list:
    """提取指定日期日报内容，返回 comment 行列表。

    关键设计：大纲是全量加载的（不受虚拟滚动影响），用它获取成员列表；
    然后逐个导航到每位成员，触发其内容块渲染后再提取。

    Args:
        date:       日期字符串，如 "0513"
        n_comments: 每位成员生成的 comment 数量（默认 1）
        temp_rules: 本轮临时规则列表（每维度各 1 条）；为 None 时自动生成
    """
    if temp_rules is None:
        temp_rules = _gen_temp_rules()
    print(f"  临时审核规则（{len(temp_rules)} 条）:")
    for i, r in enumerate(temp_rules, 1):
        print(f"    {i}. {r}")
    code = (SCRIPT_DIR / "extract_content.js").read_text()

    # Step 1：从大纲获取该日期下的完整成员列表
    member_names: list[str] = js(f'window.__getMembersForDate("{date}")')
    if not member_names:
        # fallback：先导航触发渲染，再从 DOM 提取成员列表
        coord = js(f'window.__navToMember("{date}", "")')
        if "error" not in coord:
            _nav_click(coord)
            wait(2.0)
        data = js(f'({code})("{date}")')
        if not data.get("dates"):
            print(f"✗ 未找到 {date} 的日报内容")
            return []
        member_names = [m["name"] for m in data["dates"][0]["members"]]

    print(f"  大纲成员列表（{len(member_names)} 人）: {member_names}")
    rows = []

    # 辅助：通过 extract_content.js 提取（需要 heading2 在 DOM）
    def _fetch_blocks(member_name: str) -> list:
        fresh = js(f'({code})("{date}")')
        dates_list = fresh.get("dates") or [{}]
        fm = {m["name"]: m for m in dates_list[0].get("members", [])}
        return fm.get(member_name, {}).get("rawBlocks", [])

    # 辅助：直接从 heading3 blockId 向下遍历（不依赖 heading2 在 DOM）
    def _fetch_blocks_direct(heading_id: str) -> list:
        return js(f"""(function(){{
            const ZERO=/[\\u200b\\u200c\\u200d\\ufeff\\u200e]/g, clean=t=>(t||"").replace(ZERO,"").trim();
            const isPh=c=>/【.*?】/.test(c)||c.length<3||/^[\\d\\.]+$/.test(c);
            const SEC=/^[一二三四]、/;
            const all=Array.from(document.querySelectorAll("[data-block-id]"));
            const si=all.findIndex(el=>el.getAttribute("data-block-id")==="{heading_id}");
            if(si<0) return [];
            const blocks=[];
            for(let i=si+1;i<all.length;i++){{
                const el=all[i], tp=el.getAttribute("data-block-type")||"";
                if(tp==="heading2"||tp==="heading3") break;
                const text=clean(el.innerText);
                if(!text||isPh(text)||SEC.test(text)) continue;
                blocks.push({{blockId:el.getAttribute("data-block-id"),type:tp,text:text}});
            }}
            return blocks;
        }})()""")

    # 先点一次日期行，让页面跳到该日期顶部
    date_coord = js(f'window.__navToMember("{date}", "")')
    if "error" not in date_coord:
        _nav_click(date_coord)
        wait(1.5)

    for name in member_names:
        # Step 2：按顺序点成员行（不回跳日期），让虚拟列表逐步向下渲染
        member_coord = js(f'window.__navToMember("{date}", "{name}")')
        if "error" not in member_coord:
            _nav_click(member_coord)

        # Step 3：轮询等待该成员的 heading3 出现在 DOM（最多 8 秒）
        heading_id = None
        for _ in range(16):
            wait(0.5)
            heading_id = _find_heading_id(date, name)
            if heading_id:
                break

        # Step 4：提取 rawBlocks（优先直接从 heading3 向下遍历，不依赖 heading2）
        blocks = _fetch_blocks_direct(heading_id) if heading_id else _fetch_blocks(name)

        # Step 4：过滤有效 block
        SKIP_TEXTS: set[str] = set()   # 可按需添加要跳过的固定文本
        valid_blocks = []
        for b in blocks:
            if b.get("type") == "todo":
                continue
            text = " ".join(b["text"].splitlines()).strip()
            if text in SKIP_TEXTS:
                continue
            valid_blocks.append((b, text))

        if valid_blocks:
            # 用临时规则 + LLM 生成 n_comments 条 comment
            full_text = "\n".join(t for _, t in valid_blocks)
            comments = _gen_comments_llm(name, full_text, temp_rules, n_comments)
            for idx, comment in enumerate(comments):
                # 尽量将不同 comment 分散到不同 block；超出时复用最后一个 block
                block_idx = min(idx, len(valid_blocks) - 1)
                b, text = valid_blocks[block_idx]
                rows.append({
                    "member":  name,
                    "snippet": text[:40],
                    "blockId": b["blockId"],
                    "comment": comment,
                })
        else:
            # 空报或内容全被过滤：comment 挂到 heading3（轮询时已拿到）
            if heading_id:
                rows.append({
                    "member":  name,
                    "snippet": name,
                    "blockId": heading_id,
                    "comment": "今日日报内容为空，今日实际完成了哪些工作？请补充今日工作、待跟进和 Todo 内容。",
                })

    return rows


# ── 注入弹窗 + 轮询等待用户确认 ──────────────────────────────

def inject_modal_and_wait(rows: list, timeout: int = 300) -> list | None:
    """注入确认弹窗，阻塞等待用户点击「确定」或「取消」，返回确认列表。"""
    js("window.__CONFIRMED_COMMENTS = null; window.__MODAL_CANCELLED = false;")
    js(f"window.__COMMENT_DATA = {json.dumps({'rows': rows}, ensure_ascii=False)}")
    js((SCRIPT_DIR / "inject_modal.js").read_text())
    print(f"✓ 弹窗已弹出（{len(rows)} 条），请在飞书页面确认后点击「确定」...")
    print("  （脚本自动等待，无需其他操作）")

    deadline = time.time() + timeout
    while time.time() < deadline:
        cancelled  = js("window.__MODAL_CANCELLED")
        confirmed  = js("window.__CONFIRMED_COMMENTS")
        if cancelled:
            print("✗ 用户取消")
            return None
        if confirmed is not None:
            print(f"✓ 用户确认，共 {len(confirmed)} 条")
            return confirmed
        time.sleep(0.5)

    print("✗ 等待超时（5 分钟）")
    return None


# ── 核心：获取 span 坐标 ──────────────────────────────────────

def get_span_coord(block_id, snippet):
    return js(f"""(function() {{
        const ZERO = /[\\u200b\\u200c\\u200d\\ufeff\\u200e]/g;
        const clean = t => (t||'').replace(ZERO,'').trim();
        const block = document.querySelector('[data-block-id="{block_id}"]');
        if (!block) return null;
        block.scrollIntoView({{ behavior: 'instant', block: 'center' }});
        let span = null;
        for (const s of block.querySelectorAll('span')) {{
            if (clean(s.textContent).includes(clean({json.dumps(snippet)}))) {{ span = s; break; }}
        }}
        if (!span) span = block.querySelector('.zone-container.text-editor');
        if (!span) return null;
        const r = span.getBoundingClientRect();
        return {{ x1: Math.round(r.left), x2: Math.round(r.right), y: Math.round(r.top + r.height/2) }};
    }})()""")


# ── 批量提交 ─────────────────────────────────────────────────

def submit_all(confirmed: list) -> list:
    results = []
    total = len(confirmed)
    for i, item in enumerate(confirmed):
        member   = item["member"]
        snippet  = item["snippet"]
        comment  = item["comment"]
        block_id = str(item["blockId"])
        print(f"[{i+1}/{total}] {member} — {snippet[:30]}")

        js("window.__closeCommentPanel && window.__closeCommentPanel()")
        wait(0.6)

        coord = get_span_coord(block_id, snippet)
        if not coord:
            print(f"  ✗ 找不到 block/span (blockId={block_id})")
            results.append({**item, "error": "block_or_span_not_found"})
            continue

        js("window.__armCommentObserver()")
        drag_select(coord["x1"], coord["y"], coord["x2"])
        wait(1.0)

        obs = js("window.__observerResult()")
        if "clicked" not in str(obs):
            print(f"  ✗ 工具栏未触发: {obs}")
            results.append({**item, "error": f"toolbar:{obs}"})
            continue

        result = js(f"window.__typeAndSend({json.dumps(comment)})")
        wait(0.8)
        print(f"  ✓ {result}")
        results.append({**item, "success": True})

    return results


# ── 入口 ─────────────────────────────────────────────────────

def _draft_path(date: str) -> Path:
    return SCRIPT_DIR / f"{date}_draft.json"


def main():
    parser = argparse.ArgumentParser(description="飞书日报 Comment 全流程")
    parser.add_argument("--date", required=True, help="日期，如 0513")
    parser.add_argument("--url",  required=True, help="飞书文档 URL")
    parser.add_argument(
        "--mode",
        choices=["full", "extract", "submit"],
        default="full",
        help=(
            "full=提取+生成+提交（默认）; "
            "extract=只提取内容写入 draft JSON，等待外部填写 comment; "
            "submit=读取已有 draft JSON 直接提交"
        ),
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        metavar="N",
        help="每位成员生成的 comment 数量（默认 1）",
    )
    args = parser.parse_args()

    # 获取进程锁，防止重复运行
    acquire_lock()
    try:
        _main(args)
    finally:
        release_lock()


def _main(args):
    draft_file = _draft_path(args.date)

    # ── submit-only：跳过提取，直接读 draft ──────────────────────
    if args.mode == "submit":
        if not draft_file.exists():
            print(f"✗ 找不到 {draft_file}，请先运行 --mode extract 并填写 comment")
            sys.exit(1)
        rows = json.loads(draft_file.read_text(encoding="utf-8"))
        missing = [r["member"] for r in rows if not r.get("comment", "").strip()]
        if missing:
            print(f"✗ 以下成员 comment 尚未填写：{missing}")
            sys.exit(1)
        print(f"✓ 读取 {len(rows)} 条 comment（来自 {draft_file.name}）")
        _open_and_inject(args.url)
        confirmed = inject_modal_and_wait(rows)
        if not confirmed:
            sys.exit(0)
        _finish(confirmed)
        return

    # ── extract / full：需要打开飞书提取内容 ─────────────────────
    _open_and_inject(args.url)

    # 每轮运行统一生成一组临时规则，所有成员共用同一组规则
    temp_rules = _gen_temp_rules()
    rows = extract_and_build_rows(args.date, n_comments=args.count, temp_rules=temp_rules)
    if not rows:
        print("✗ 无可提交内容"); sys.exit(1)

    if args.mode == "extract":
        # 清空 comment 字段，等待外部（LLM 对话）填写
        for r in rows:
            r["comment"] = ""
        draft_file.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✓ 已提取 {len(rows)} 条内容，写入 {draft_file}")
        print("  请在对话里让 Claude 生成 comment，完成后执行 --mode submit 提交。")
        return

    # full 模式：继续弹窗 + 提交
    print(f"✓ 生成 {len(rows)} 条 comment 建议（每人 {args.count} 条）")
    confirmed = inject_modal_and_wait(rows)
    if not confirmed:
        sys.exit(0)
    _finish(confirmed)


def _open_and_inject(url: str):
    ensure_daemon()
    print("✓ browser-harness daemon 已就绪")
    open_doc(url)
    js((SCRIPT_DIR / "submit_comments.js").read_text())
    if not ensure_catalogue():
        print("✗ 大纲加载失败"); sys.exit(1)
    print("✓ 大纲已加载")


def _finish(confirmed: list):
    # 批量提交
    print("\n开始批量提交...")
    results = submit_all(confirmed)

    # 汇总
    ok   = sum(1 for r in results if r.get("success"))
    fail = len(results) - ok
    print(f"\n✅ 完成：{ok} 成功 / {fail} 失败")
    for r in results:
        if not r.get("success"):
            print(f"  ✗ {r['member']} [{r['snippet'][:20]}]: {r.get('error')}")


if __name__ == "__main__":
    main()
