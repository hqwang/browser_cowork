"""主脚本：读 xq_info JSON，把全部内容灌进 Subo 流水线表单。

用法：
    XQ_INFO_IN=/tmp/xq_info.json browser-harness -c \
        "exec(open('<skill-path>/scripts/fill_form.py').read())"

注意：脚本 **不会** 自动点提交。结束后截图到 /tmp/subo_submit_review.png，
让用户人工核对再自行点 提交（这是不可逆动作，一定要让用户授权）。
"""

import json
import os
import shutil
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else "/tmp"
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import form_helpers as fh   # noqa: E402
import mappings as mp       # noqa: E402

FORM_URL = "https://b3sh6jivuw.feishu.cn/share/base/form/shrcnJAnk4pUjerGBOaWHTFiJIf"
INPUT_PATH = os.environ.get("XQ_INFO_IN", "/tmp/xq_info.json")
REVIEW_PNG = os.environ.get("XQ_INFO_REVIEW_PNG", "/tmp/subo_submit_review.png")


def load_input():
    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def fill_top_section(data):
    print("\n=== Top dropdowns ===")
    fh.select_top_dropdown("是否涉及版本计划", "自主迭代", open_wait=0.8)
    time.sleep(0.8)

    target_xq = f"XQ-{data['xqID']}"
    print(f"  xqID -> {target_xq}")
    fh.scroll_label_into_view("xqID")
    pos = fh.find_editor_xy("xqID")
    if pos:
        click_at_xy(pos["x"], pos["y"])  # noqa: F821
        time.sleep(0.8)
        fh.set_search_value(data["xqID"])
        time.sleep(0.8)
        fh.click_option_in_open_panel(target_xq, contains=True)
        fh.safe_close_panels()

    fh.select_top_dropdown("是否数据需求", mp.map_xq_type(data["xqType"]), open_wait=0.8)
    fh.select_top_dropdown("模版名称", "全流程", open_wait=0.8)


def fill_one_subo(row_idx: int, subo: dict) -> dict:
    """填一行，返回各字段的填充状态 {field: True/False/'skip'}。"""
    pt_form = mp.map_point_type(subo["pointType"])
    print(f"  [row {row_idx}] {pt_form} | {subo['spendHour']} | {subo['pointPerson']} | {subo['pointName']}")
    status = {"pointType": False, "spendHour": False, "pointPerson": False, "pointName": False}

    # 节点序号
    try:
        fh.scroll_to_last_table_row()
        rows = fh.find_table_rows()
        if not rows:
            print("    ! 节点序号 no rows found，跳过该字段继续填其他列")
        else:
            fh.open_cell_editor(rows[-1]["type"])
            if fh.select_cell_dropdown(pt_form):
                status["pointType"] = True
            else:
                print("    ! 节点序号 选项未匹配，继续填其他列")
                fh.safe_close_panels()
    except Exception as e:
        print(f"    ! 节点序号 异常: {e}")
        fh.safe_close_panels()

    # 工时
    try:
        fh.scroll_to_last_table_row()
        rows = fh.find_table_rows()
        if not rows:
            print("    ! 工时 no rows found")
        else:
            fh.open_cell_editor(rows[-1]["hours"])
            if fh.type_into_simple_input(subo["spendHour"], target_y=rows[-1]["hours"]["y"]):
                status["spendHour"] = True
            else:
                print("    ! 工时输入框未找到")
    except Exception as e:
        print(f"    ! 工时 异常: {e}")

    # 节点负责人
    try:
        fh.scroll_to_last_table_row()
        rows = fh.find_table_rows()
        if not rows:
            print("    ! 节点负责人 no rows found")
        else:
            fh.open_cell_editor(rows[-1]["person"])
            fh.set_search_value(subo["pointPerson"])
            time.sleep(0.3)
            if fh.click_option_in_open_panel(subo["pointPerson"], contains=True):
                status["pointPerson"] = True
            else:
                print("    ! 节点负责人 选项未匹配")
            fh.safe_close_panels()
    except Exception as e:
        print(f"    ! 节点负责人 异常: {e}")
        fh.safe_close_panels()

    # 节点名称
    try:
        fh.scroll_to_last_table_row()
        rows = fh.find_table_rows()
        if not rows:
            print("    ! 节点名称 no rows found")
        else:
            if fh.type_into_rich_text_cell(len(rows) - 1, col_index=4, text=subo["pointName"]):
                status["pointName"] = True
            else:
                print("    ! 节点名称 写入失败")
            time.sleep(1.0)
            fh.safe_close_panels()
    except Exception as e:
        print(f"    ! 节点名称 异常: {e}")
        fh.safe_close_panels()

    return status


def print_report(filtered, results, skipped, elapsed: float = 0):
    """输出填充率报告及缺失内容提示。"""
    total_fields = len(filtered) * 4
    filled_fields = sum(
        sum(1 for v in r["status"].items() if v[1] is True)
        for r in results
    )
    fill_rate = filled_fields / total_fields * 100 if total_fields else 0

    missing = [r for r in results if not all(r["status"].values())]

    mins, secs = divmod(int(elapsed), 60)
    elapsed_str = f"{mins}m {secs}s" if mins else f"{secs}s"

    print("\n" + "=" * 60)
    print(f"=== 填充报告 ===")
    print(f"耗时: {elapsed_str}")
    print(f"总行数（过滤硅基化后）: {len(filtered)}")
    print(f"已跳过（硅基化）: {len(skipped)}")
    print(f"字段填充率: {filled_fields}/{total_fields} ({fill_rate:.1f}%)")
    print(f"有缺失的行数: {len(missing)}")

    if missing:
        print("\n--- 缺失详情（需手动补充）---")
        for r in missing:
            s = r["subo"]
            st = r["status"]
            missing_fields = [k for k, v in st.items() if not v]
            field_map = {
                "pointType": "节点序号",
                "spendHour": "拆解工时",
                "pointPerson": "节点负责人",
                "pointName": "节点名称",
            }
            reason_map = {
                "pointType": "下拉选项未匹配（表单无对应节点）",
                "pointPerson": "成员搜索未匹配（飞书昵称可能不同）",
                "spendHour": "输入框未激活",
                "pointName": "富文本写入失败",
            }
            missing_labels = [field_map[f] for f in missing_fields]
            reasons = list(dict.fromkeys(reason_map[f] for f in missing_fields))
            print(f"  行 {r['idx']:>2} | {mp.map_point_type(s['pointType'])} | {s['pointPerson']} | {s['pointName'][:20]}")
            print(f"         缺失字段: {', '.join(missing_labels)}")
            print(f"         原因: {'; '.join(reasons)}")

        print("\n⚠ 请在浏览器中手动补充以上缺失内容后再提交表单。")
    else:
        print("\n✓ 所有字段填充完整，请核对后提交。")
    print("=" * 60)


def main():
    data = load_input()
    suboList = data.get("suboList", [])

    filtered = []
    skipped = []
    for s in suboList:
        if mp.should_skip(s["pointType"]):
            skipped.append(s)
        else:
            filtered.append(s)

    print(f"input subo: {len(suboList)}  use: {len(filtered)}  skipped: {len(skipped)}")
    for s in skipped:
        print("  skip:", s["pointType"], "/", s["pointName"])

    start_time = time.time()

    new_tab(FORM_URL)        # noqa: F821
    wait_for_load()          # noqa: F821
    time.sleep(3.0)

    fill_top_section(data)

    js("""(() => {
      const lbls = Array.from(document.querySelectorAll('div, span, label')).filter(el =>
        (el.textContent || '').trim() === 'Subo涉及的拆解' && el.offsetParent);
      if (lbls.length) lbls[0].scrollIntoView({block: 'start'});
    })()""")             # noqa: F821
    time.sleep(0.8)

    print("\n=== Table rows ===")
    results = []
    for i, subo in enumerate(filtered):
        if i > 0:
            fh.click_add_row()
            js("""(() => {
              const t = Array.from(document.querySelectorAll('table')).find(
                tb => tb.textContent.includes('节点序号') && tb.textContent.includes('节点名称'));
              if (!t) return;
              const trs = Array.from(t.querySelectorAll('tr')).filter(tr => !tr.querySelector('th'));
              if (trs.length) trs[trs.length - 1].scrollIntoView({block: 'center'});
            })()""")     # noqa: F821
            time.sleep(0.8)
        try:
            status = fill_one_subo(i, subo)
        except Exception as e:
            print(f"    ! row {i} 整行异常: {e}")
            status = {"pointType": False, "spendHour": False, "pointPerson": False, "pointName": False}
            fh.safe_close_panels()
        results.append({"idx": i, "subo": subo, "status": status})

    try:
        path = capture_screenshot()  # noqa: F821
        shutil.copy(path, REVIEW_PNG)
        print(f"\n截图已保存：{REVIEW_PNG}")
    except Exception as e:
        print(f"截图失败：{e}")

    elapsed = time.time() - start_time
    print_report(filtered, results, skipped, elapsed)


main()
