#!/usr/bin/env python3
"""
extract_okr.py
==============
从飞书思维导图按组织名提取 OKR，输出结构化 JSON。

用法:
    python3 extract_okr.py <url> <org1> [org2] ...

输出:
    /tmp/okr_tree.json   — 带深度的原始节点树
    /tmp/okr_parsed.json — 解析后的 O/KR/notes 结构
"""

import sys
import re
import json
import subprocess

HARNESS_PATH = "/Users/tyc/Developer/browser-harness/.venv/bin/browser-harness"

# UI 噪声前缀（飞书拖拽手柄等），提取时过滤
UI_NOISE_PREFIXES = ["拖拽", "drag"]

# ── 注入到飞书页面的 JS 提取器 ─────────────────────────────────────────────
_JS_EXTRACTOR = r"""
(function(orgNames) {
    const UI_NOISE_PREFIXES = ['拖拽', 'drag'];

    function isNoise(title) {
        if (!title) return true;
        const t = title.toLowerCase();
        return UI_NOISE_PREFIXES.some(p => t.startsWith(p));
    }

    /**
     * 按组织名找到对应的 div.node 根容器。
     * 飞书思维导图树层级由嵌套的 div.node 表达（非 div.node-wrapper）。
     */
    function findOrgRootNode(orgName) {
        const wrappers = Array.from(document.querySelectorAll('div.node-wrapper'));
        const target = wrappers.find(w =>
            w.innerText?.split('\n')[0]?.trim() === orgName
        );
        if (!target) return null;
        let p = target.parentElement;
        while (p && !p.classList.contains('node')) p = p.parentElement;
        return p || null;
    }

    /**
     * 提取子树，返回带相对深度的节点列表。
     * depth = 从 rootNode 到节点之间经过的 div.node 层数。
     */
    function extractSubtree(rootNode) {
        const items = [];
        rootNode.querySelectorAll('div.node-wrapper').forEach(w => {
            const title = (w.innerText?.split('\n')[0] || '').trim();
            if (isNoise(title)) return;

            let depth = 0, p = w.parentElement;
            while (p && p !== rootNode) {
                if (p.classList.contains('node')) depth++;
                p = p.parentElement;
            }
            items.push({ depth, title });
        });
        return items;
    }

    const result = {};
    orgNames.forEach(name => {
        const root = findOrgRootNode(name);
        if (!root) {
            result[name] = { error: '未找到组织节点，请确认名称与思维导图中的文字完全一致' };
            return;
        }
        const items = extractSubtree(root);
        result[name] = { totalNodes: items.length, items };
    });
    return JSON.stringify(result);
})
"""


def extract_org_trees(url: str, org_names: list) -> dict:
    """
    打开飞书思维导图，提取各组织的完整 OKR 子树（带深度）。
    返回 {org_name: {totalNodes, items: [{depth, title}]}, ...}
    """
    names_json = json.dumps(org_names, ensure_ascii=False)
    js_call = f"({_JS_EXTRACTOR})({names_json})"

    script = f"""
import time
new_tab("{url}")
wait_for_load()
time.sleep(8)
result = js({json.dumps(js_call)})
print(result)
"""
    proc = subprocess.run(
        [HARNESS_PATH], input=script, capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise RuntimeError(f"browser-harness 失败:\n{proc.stderr}")

    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    raise ValueError(f"未能从输出中解析 JSON:\n{proc.stdout}")


def parse_okr_from_tree(tree_items: list) -> list:
    """
    从带深度的节点列表解析 O/KR 结构，KR 的深度下方子节点收入 notes。

    节点格式示例（飞书常见）：
        【25%】O1：OA2和基于OA2的低熵化
        【70%】KR1: pWin ~ N0D1(cv, 60%)
        业财SST系统开发由谁接手（depth=3，归入上方 KR 的 notes）

    notes 归属逻辑：遇到 KR 时记录 kr_depth；
    后续 depth > kr_depth 的节点全部归入该 KR.notes，
    直到下一个 O 或 KR 节点切换 current_kr。
    """
    o_pat  = re.compile(r"(?:【([^】]*)】\s*)?O(\d+)[：:、\s]+(.+)")
    kr_pat = re.compile(r"(?:【([^】]*)】\s*)?KR(\d+)[：:、\s]+(.+)")

    objectives  = []
    current_o   = None
    current_kr  = None
    kr_depth    = None

    for item in tree_items:
        title = item["title"]
        depth = item["depth"]

        m = o_pat.match(title)
        if m:
            current_o = {
                "index":  int(m.group(2)),
                "weight": m.group(1) or "",
                "text":   m.group(3).strip(),
                "krs":    [],
            }
            objectives.append(current_o)
            current_kr = None
            kr_depth   = None
            continue

        m = kr_pat.match(title)
        if m and current_o is not None:
            current_kr = {
                "index":  int(m.group(2)),
                "weight": m.group(1) or "",
                "text":   m.group(3).strip(),
                "notes":  [],
            }
            current_o["krs"].append(current_kr)
            kr_depth = depth
            continue

        # depth > kr_depth → 归入当前 KR 的 notes
        if current_kr is not None and kr_depth is not None and depth > kr_depth:
            current_kr["notes"].append(title)

    return objectives


def tree_to_text(tree_items: list, indent: str = "  ") -> str:
    """带深度节点列表 → 缩进文本，方便喂给 LLM。"""
    return "\n".join(indent * item["depth"] + item["title"] for item in tree_items)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 3:
        print("用法: python3 extract_okr.py <url> <org1> [org2] ...")
        print("示例: python3 extract_okr.py https://xxx.feishu.cn/mindnotes/xxx 公司0512 应用工程部")
        sys.exit(1)

    url, org_names = sys.argv[1], sys.argv[2:]

    print(f"[1/3] 正在提取: {url}")
    print(f"      目标组织: {org_names}")
    trees = extract_org_trees(url, org_names)

    print("[2/3] 解析 OKR 条目 ...")
    parsed = {}
    for name, info in trees.items():
        if "error" in info:
            print(f"  ❌ [{name}] {info['error']}")
            continue
        okrs = parse_okr_from_tree(info["items"])
        parsed[name] = okrs
        print(f"  ✓  [{name}] {info['totalNodes']} 节点 → {len(okrs)} 个 Objective")
        for o in okrs:
            kr_count   = len(o["krs"])
            note_count = sum(len(kr["notes"]) for kr in o["krs"])
            print(f"       O{o['index']} [{o['weight']}] {o['text'][:40]}  "
                  f"({kr_count} KRs, {note_count} notes)")

    print("[3/3] 保存结果 ...")
    with open("/tmp/okr_tree.json", "w") as f:
        json.dump(trees, f, ensure_ascii=False, indent=2)
    with open("/tmp/okr_parsed.json", "w") as f:
        json.dump(parsed, f, ensure_ascii=False, indent=2)

    print("\n  /tmp/okr_tree.json   — 原始节点树（带深度）")
    print("  /tmp/okr_parsed.json — O/KR/notes 结构化数据")


if __name__ == "__main__":
    main()
