"""把 飞书表格里『估时』cell 的多行文本切成 subo 列表。

输入示例（一个 cell 的 innerText）：
    A股十大股东股份类型字段同步逻辑升级，4WPH
    A股十大股东股份类型字段全量刷数，2WPH
或：
    1. 熟悉批处理+流处理逻辑。4wph
    2. 结合底表梳理...4wph
或：
    Subo-1: 字段计算逻辑优化，4WPH
或：
    线上回归，2WPH
或仅：
    2WPH

输出：[{"pointName": str, "spendHour": int|float}, ...]
"""

import re

# 序号前缀：纯数字+点 或 Subo-N:
PREFIX_PAT = re.compile(r"^\s*(?:\d+\.\s*|Subo-\d+:\s*)")

# 末尾的「数字+单位」，单位是任意字母（包含笔误如 wph→whh）
TRAIL_PAT = re.compile(
    r"^(.*?)[\s，,。:：]?\s*([0-9]+(?:\.[0-9]+)?)\s*[A-Za-z]+\s*$"
)


def split_items(cell_text):
    """把估时 cell 的多行文本切成可解析的字符串列表。

    规则：
    - 去零宽空格 ​
    - 单独的「N.」「N」行（飞书有时把序号单独放一行）丢弃
    - 其他非空行保留
    """
    items = []
    for raw_line in cell_text.replace("​", "").split("\n"):
        s = raw_line.strip()
        if not s:
            continue
        if re.fullmatch(r"\d+\.?", s):
            continue
        items.append(s)
    return items


def parse_estimate_line(line, pointType_fallback=""):
    """把一条估时字符串解析为 {pointName, spendHour}。

    pointType_fallback：当估时只有数字单位（如「2WPH」）没有任务名时，
    用流程节点名作为任务名兜底。
    返回 None 表示解析失败。
    """
    s = PREFIX_PAT.sub("", line.strip())
    m = TRAIL_PAT.match(s)
    if not m:
        return None
    name = m.group(1).rstrip(" ，,。:：").strip()
    h = float(m.group(2))
    if h.is_integer():
        h = int(h)
    if not name:
        name = pointType_fallback
    return {"pointName": name, "spendHour": h}


def parse_row(pointType, pointPerson, est_cell):
    """把一行（流程节点 / 节点负责人 / 估时）解析为多个 subo 字典。

    完成节点（est_cell 为空）返回空列表。
    """
    out = []
    for item in split_items(est_cell):
        parsed = parse_estimate_line(item, pointType_fallback=pointType)
        if parsed is None:
            # 调用方决定是否报错；这里只是跳过
            continue
        out.append({
            "pointType": pointType,
            "pointPerson": pointPerson,
            "spendHour": parsed["spendHour"],
            "pointName": parsed["pointName"],
        })
    return out


def classify_xq_type(roles_text):
    """判断 xqType：客户端/前端/服务端任一为「功能型」否则「数据型」。"""
    func_roles = ("客户端", "前端", "服务端")
    return "功能型" if any(r in roles_text for r in func_roles) else "数据型"


def extract_xq_id(title):
    """从标题里抽 XQ-{id}。返回 id 字符串或 None。"""
    m = re.search(r"XQ-(\S+)", title or "")
    return m.group(1) if m else None
