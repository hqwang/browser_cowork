"""在 browser-harness 里运行：从当前打开的飞书 Wiki 页面提取需求信息。

用法：
    browser-harness -c "exec(open('<skill-path>/scripts/extract.py').read())"

约定：
- 当前 tab 已经打开了目标飞书 Wiki 页面
- 输出 JSON 写入 OUT_PATH（默认 /tmp/xq_info.json），可通过环境变量覆盖

注意：飞书表格用虚拟渲染，必须逐行 scrollIntoView 把视口外的 cell 挂载，否则只能拿到约 4 行真正的内容。
"""

import json
import os
import sys
import time

# parse_subo 与 extract 在同目录，加入 sys.path
_HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else "/tmp"
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# 用户在 browser-harness 里，js / page_info / capture_screenshot 已注入到 globals
# 这里 import parse_subo 拿纯 Python 函数
import parse_subo  # noqa: E402

OUT_PATH = os.environ.get("XQ_INFO_OUT", "/tmp/xq_info.json")


def _q(s: str) -> str:
    """把 Python 字符串安全嵌入到 JS 源码里（用 JSON 编码）。"""
    return json.dumps(s, ensure_ascii=False)


def get_title() -> str:
    return js("document.title").strip()


def get_roles_text() -> str:
    """读「子任务拆解」段落下的角色行原文。

    简单做法：直接抓页面 body 的 innerText（顶部一段就足够判断），
    或聚焦到「子任务拆解」节点附近。这里宽松地抓 body 顶部 5KB。
    """
    return js("document.body.innerText.slice(0, 5000)")


def collect_table_rows():
    """逐行 scrollIntoView 把表格每个 cell 的 innerText 抓下来。

    返回 [(cell0, cell1, cell2), ...]，cell0=流程节点，cell1=节点负责人，cell2=估时。
    空行会被保留，由调用方决定是否丢弃。
    """
    # 先回到表格顶部
    js("""(() => {
      const tables = document.querySelectorAll('table');
      if (tables.length < 2) return;
      tables[1].rows[0].scrollIntoView({block: 'center'});
    })()""")
    time.sleep(0.6)

    n = int(js("""(() => {
      const t = document.querySelectorAll('table')[1];
      return t ? t.rows.length : 0;
    })()"""))
    if n == 0:
        return []

    results: dict = {}
    for i in range(n):
        js(f"""(() => {{
          const r = document.querySelectorAll('table')[1].rows[{i}];
          if (r) r.scrollIntoView({{block:'center'}});
        }})()""")
        time.sleep(0.35)
        # 抓附近 ±2 行（容错），保留非空更新
        raw = js(f"""(() => {{
          const t = document.querySelectorAll('table')[1];
          const out = [];
          const lo = Math.max(0, {i} - 2);
          const hi = Math.min(t.rows.length - 1, {i} + 2);
          for (let k = lo; k <= hi; k++) {{
            const r = t.rows[k];
            const cells = [];
            for (let j = 0; j < r.cells.length; j++) cells.push(r.cells[j].innerText);
            out.push({{k, cells}});
          }}
          return JSON.stringify(out);
        }})()""")
        for entry in json.loads(raw):
            k = entry["k"]
            cells = entry["cells"]
            non_empty = any(c.replace("​", "").strip() for c in cells)
            if k not in results or non_empty:
                if non_empty or k not in results:
                    results[k] = cells

    return [tuple(results[k][:3]) for k in sorted(results.keys()) if len(results[k]) >= 3]


def main():
    title = get_title()
    xq_id = parse_subo.extract_xq_id(title)
    if not xq_id:
        raise RuntimeError(f"无法从标题提取 xqID: {title!r}")

    roles_text = get_roles_text()
    xq_type = parse_subo.classify_xq_type(roles_text)

    rows = collect_table_rows()

    subo_list = []
    unparsed = []
    for cell0, cell1, cell2 in rows:
        pointType = (cell0 or "").replace("​", "").strip()
        pointPerson = (cell1 or "").replace("​", "").strip()
        if not pointType and not pointPerson and not cell2.replace("​", "").strip():
            continue  # 真空模板行
        if pointType == "完成":
            continue  # 流程终点
        items = parse_subo.split_items(cell2 or "")
        if not items:
            continue
        for item in items:
            parsed = parse_subo.parse_estimate_line(item, pointType_fallback=pointType)
            if parsed is None:
                unparsed.append({"pointType": pointType, "raw": item})
                continue
            subo_list.append({
                "pointType": pointType,
                "pointPerson": pointPerson,
                "spendHour": parsed["spendHour"],
                "pointName": parsed["pointName"],
            })

    out = {"xqID": xq_id, "xqType": xq_type, "suboList": subo_list}
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"=== xqID={xq_id} xqType={xq_type} subo={len(subo_list)} unparsed={len(unparsed)} ===")
    if unparsed:
        print("⚠ unparsed:")
        for u in unparsed:
            print(" -", u)
    print(f"saved -> {OUT_PATH}")


main()
