"""字段值的语义映射 + 跳过规则。"""

# 输入 pointType -> 表单下拉里的实际选项
POINT_TYPE_MAP = {
    "开发-基础数据开发": "开发-基础数据",
    "开发-数据平台开发": "开发-数据开发",
    "开发-android开发": "开发-安卓开发",
    "开发-iOS开发":     "开发-ios开发",
    "上线-基础数据上线": "上线-基础数据部上线",
    "上线-数据平台上线": "上线-数开上线",
    "上线-android上线":  "上线-安卓上线",
    "上线-iOS上线":      "上线-ios上线",
}

# pointType 含这些子串就跳过这条 subo（表单暂无对应选项）
SKIP_SUBSTRINGS = ("硅基化",)

# xqType -> 表单选项
XQ_TYPE_MAP = {
    "功能型": "功能型需求",
    "数据型": "数据型需求",
    "#N/A":  "#N/A",
}


def map_point_type(raw: str) -> str:
    return POINT_TYPE_MAP.get(raw, raw)


def map_xq_type(raw: str) -> str:
    return XQ_TYPE_MAP.get(raw, raw)


def should_skip(point_type: str) -> bool:
    return any(s in point_type for s in SKIP_SUBSTRINGS)
