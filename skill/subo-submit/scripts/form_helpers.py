"""与飞书 bitable form 交互的最小工具集，供 browser-harness 内调用。

依赖 browser-harness 已注入到 globals 的：
    js(code) -> str
    click_at_xy(x, y)
    type_text(s)

设计原则：
- 保持极简，写 SKILL 时遇到的坑都靠等待 + 重新查询 DOM 解决，不引入超时框架
- 找元素永远 scope 到「当前可见的下拉面板」，避免跨字段误命中同名 option
"""

from __future__ import annotations

import json
import time


# ---------- 通用 ----------

def jq(code: str):
    """js() 的薄包装。"""
    return js(code)  # noqa: F821 — js 由 browser-harness 注入


def safe_close_panels():
    """关闭可能打开的下拉。JS 发 Escape 事件 + 隐藏残留面板，比坐标点击更可靠。"""
    jq("""(() => {
      // 1. 向 document 发 Escape，触发飞书的面板关闭逻辑
      document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', keyCode:27, bubbles:true}));
      document.activeElement && document.activeElement.dispatchEvent(
        new KeyboardEvent('keydown', {key:'Escape', keyCode:27, bubbles:true}));
    })()""")
    time.sleep(0.2)
    # 兜底：把仍可见的面板藏掉，避免坐标干扰后续字段操作
    jq("""(() => {
      document.querySelectorAll('.b-select-dropdown-content').forEach(p => {
        if (p.getBoundingClientRect().height > 0) p.style.display = 'none';
      });
    })()""")


# ---------- 字段定位 ----------

def find_editor_xy(label_text: str) -> dict | None:
    """通过 label 文本找到对应的 form-item 编辑区中心点。

    支持 select_editor / link_editor / text_editor — 任意一种 .bitable-form_editor。
    """
    code = """(() => {
      const lbls = Array.from(document.querySelectorAll('label, span, div')).filter(el =>
        (el.textContent||'').trim() === %s && el.offsetParent);
      for (const lbl of lbls) {
        let p = lbl;
        for (let i = 0; i < 10 && p; i++) {
          const sel = p.querySelector('.bitable-form_editor');
          if (sel) {
            const r = sel.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) {
              return JSON.stringify({x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2)});
            }
          }
          p = p.parentElement;
        }
      }
      return JSON.stringify({err: 'not found'});
    })()""" % json.dumps(label_text)
    res = json.loads(jq(code))
    return None if res.get("err") else res


def scroll_label_into_view(label_text: str):
    jq("""(() => {
      const lbls = Array.from(document.querySelectorAll('label, span, div')).filter(el =>
        (el.textContent||'').trim() === %s && el.offsetParent);
      if (lbls.length) lbls[0].scrollIntoView({block:'center'});
    })()""" % json.dumps(label_text))
    time.sleep(0.3)


# ---------- 下拉面板交互 ----------

def set_search_value(value: str) -> bool:
    """把 value 写入当前打开下拉面板里的 search input，并触发 input 事件以过滤选项。"""
    res = jq("""(() => {
      const panels = Array.from(document.querySelectorAll('.b-select-dropdown-content'))
        .filter(p => p.getBoundingClientRect().height > 0);
      if (!panels.length) return JSON.stringify({err: 'no panel'});
      const inp = panels[0].querySelector('input');
      if (!inp) return JSON.stringify({err: 'no input'});
      const native = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      native.call(inp, %s);
      inp.dispatchEvent(new Event('input', {bubbles: true}));
      return JSON.stringify({ok: 1});
    })()""" % json.dumps(value))
    return "err" not in json.loads(res)


def click_option_in_open_panel(option_text: str, contains: bool = False) -> bool:
    """在当前打开的下拉面板里点一个匹配的选项。"""
    code = """(() => {
      const panels = Array.from(document.querySelectorAll('.b-select-dropdown-content'))
        .filter(p => p.getBoundingClientRect().height > 0);
      for (const panel of panels) {
        const opts = panel.querySelectorAll('li.b-select-option, li[class*=option]');
        for (const o of opts) {
          const t = (o.textContent || '').trim();
          const matched = %s ? t.includes(%s) : t === %s;
          if (matched) {
            const r = o.getBoundingClientRect();
            if (r.height > 0) return JSON.stringify({x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2)});
          }
        }
      }
      return JSON.stringify({err: 'not found'});
    })()""" % ("true" if contains else "false", json.dumps(option_text), json.dumps(option_text))
    res = json.loads(jq(code))
    if "err" in res:
        return False
    click_at_xy(res["x"], res["y"])  # noqa: F821
    time.sleep(0.3)
    return True


def select_top_dropdown(label: str, option: str, search: bool = False, contains: bool = False, open_wait: float = 0.3) -> bool:
    """点开 label 对应的下拉，选 option。open_wait 控制点开后等待面板渲染的时长。"""
    scroll_label_into_view(label)
    pos = find_editor_xy(label)
    if not pos:
        print(f"  [editor not found] {label}")
        return False
    click_at_xy(pos["x"], pos["y"])  # noqa: F821
    time.sleep(open_wait)
    if search:
        set_search_value(option)
        time.sleep(open_wait)
    ok = click_option_in_open_panel(option, contains=contains)
    safe_close_panels()
    return ok


# ---------- 表格行交互 ----------

def find_table_rows() -> list[dict]:
    """返回 Subo 拆解表格里所有数据行的 4 个 cell 中心坐标。"""
    code = """(() => {
      const tables = Array.from(document.querySelectorAll('table'));
      const t = tables.find(tb => tb.textContent.includes('节点序号') && tb.textContent.includes('节点名称'));
      if (!t) return JSON.stringify({err: 'no table'});
      const trs = Array.from(t.querySelectorAll('tr')).filter(tr => !tr.querySelector('th'));
      const out = [];
      trs.forEach((tr, idx) => {
        const tds = tr.querySelectorAll('td');
        if (tds.length < 5) return;
        const c = (cell) => {
          const r = cell.getBoundingClientRect();
          return {x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2)};
        };
        out.push({idx, type: c(tds[1]), hours: c(tds[2]), person: c(tds[3]), name: c(tds[4])});
      });
      return JSON.stringify(out);
    })()"""
    res = json.loads(jq(code))
    return [] if isinstance(res, dict) and res.get("err") else res


def click_add_row():
    """点「+ 添加一行」。用 JS .click() 直接触发，避免坐标偏移问题。"""
    before = int(jq("""(() => {
      const t = Array.from(document.querySelectorAll('table')).find(
        tb => tb.textContent.includes('节点序号') && tb.textContent.includes('节点名称'));
      if (!t) return 0;
      return Array.from(t.querySelectorAll('tr')).filter(tr => !tr.querySelector('th')).length;
    })()""") or 0)

    res = jq("""(() => {
      // 优先点 BUTTON 元素，否则点包含文字的 DIV
      const btn = Array.from(document.querySelectorAll('button')).find(el =>
        (el.textContent || '').trim() === '添加一行' && el.offsetParent);
      if (btn) { btn.scrollIntoView({block:'center'}); btn.click(); return 'clicked-button'; }
      const div = Array.from(document.querySelectorAll('div')).find(el =>
        (el.textContent || '').trim() === '添加一行' && el.offsetParent);
      if (div) { div.scrollIntoView({block:'center'}); div.click(); return 'clicked-div'; }
      return 'not-found';
    })()""")
    print(f"  [add-row] {res}")
    time.sleep(0.4)  # 等待新行渲染

    after = int(jq("""(() => {
      const t = Array.from(document.querySelectorAll('table')).find(
        tb => tb.textContent.includes('节点序号') && tb.textContent.includes('节点名称'));
      if (!t) return 0;
      return Array.from(t.querySelectorAll('tr')).filter(tr => !tr.querySelector('th')).length;
    })()""") or 0)
    print(f"  [add-row] rows before={before} after={after}")


def scroll_to_last_table_row():
    """把 Subo 表格最后一数据行滚到视口中心，确保后续 find_table_rows() 拿到有效坐标。"""
    jq("""(() => {
      const t = Array.from(document.querySelectorAll('table')).find(
        tb => tb.textContent.includes('节点序号') && tb.textContent.includes('节点名称'));
      if (!t) return;
      const trs = Array.from(t.querySelectorAll('tr')).filter(tr => !tr.querySelector('th'));
      if (trs.length) trs[trs.length - 1].scrollIntoView({block: 'center'});
    })()""")
    time.sleep(0.2)


def open_cell_editor(xy: dict):
    """单 cell 的「两次点击」激活 + 打开。调用前须先调 scroll_to_last_table_row()。"""
    click_at_xy(xy["x"], xy["y"])  # noqa: F821
    time.sleep(0.3)
    click_at_xy(xy["x"], xy["y"])  # noqa: F821
    time.sleep(0.8)


def select_cell_dropdown(option_text: str, contains: bool = False) -> bool:
    """已激活下拉 cell 后，搜+选选项。"""
    set_search_value(option_text)
    time.sleep(0.3)
    ok = click_option_in_open_panel(option_text, contains=contains)
    safe_close_panels()
    return ok


def type_into_simple_input(text: str, placeholder: str = "请输入内容", target_y: int | None = None) -> bool:
    """已激活的工时这种简单 input cell 中输入文本。

    target_y: 调用方传入当前行的 y 坐标（来自 find_table_rows），
    用于在 activeElement 未聚焦时精准定位同一行的 input，避免误命中上一行。
    """
    ref_y = target_y if target_y is not None else 488
    code = """(() => {
      const ph = %s;
      const refY = %d;
      // 优先用已聚焦的 input（open_cell_editor 点击后应已聚焦）
      const active = document.activeElement;
      if (active && active.tagName === 'INPUT' && active.placeholder === ph) {
        const r = active.getBoundingClientRect();
        return JSON.stringify({x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2)});
      }
      // 退回：所有可见 placeholder 匹配的 input，选最靠近 refY 的
      const inps = Array.from(document.querySelectorAll('input')).filter(i => {
        const r = i.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && i.placeholder === ph;
      });
      if (!inps.length) return JSON.stringify({err:'no input'});
      const inp = inps.sort((a, b) =>
        Math.abs(a.getBoundingClientRect().top - refY) - Math.abs(b.getBoundingClientRect().top - refY))[0];
      const r = inp.getBoundingClientRect();
      return JSON.stringify({x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2)});
    })()""" % (json.dumps(placeholder), ref_y)
    res = json.loads(jq(code))
    if "err" in res:
        return False
    click_at_xy(res["x"], res["y"])  # noqa: F821
    time.sleep(0.2)
    type_text(str(text))  # noqa: F821
    time.sleep(0.3)
    safe_close_panels()
    return True


def type_into_rich_text_cell(row_idx: int, col_index: int, text: str) -> bool:
    """节点名称这种 Ace 富文本 cell — 通过 contenteditable + execCommand 注入文本。

    col_index 在 td 序列里的位置（节点名称 = 4，节点序号=1，工时=2，负责人=3）。
    """
    code = """(() => {
      const tables = Array.from(document.querySelectorAll('table'));
      const t = tables.find(tb => tb.textContent.includes('节点序号'));
      const trs = Array.from(t.querySelectorAll('tr')).filter(tr => !tr.querySelector('th'));
      const tr = trs[%d];
      if (!tr) return JSON.stringify({err: 'no row'});
      const cell = tr.querySelectorAll('td')[%d];
      const editable = cell.querySelector('[contenteditable]');
      if (!editable) return JSON.stringify({err: 'no editable'});
      editable.setAttribute('contenteditable', 'true');
      editable.focus();
      const sel = window.getSelection();
      sel.removeAllRanges();
      const range = document.createRange();
      range.selectNodeContents(editable);
      range.collapse(false);
      sel.addRange(range);
      document.execCommand('insertText', false, %s);
      editable.dispatchEvent(new Event('input', {bubbles:true}));
      editable.blur();
      return JSON.stringify({ok: 1});
    })()""" % (row_idx, col_index, json.dumps(text))
    res = json.loads(jq(code))
    return "err" not in res
