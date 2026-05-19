/**
 * feishu-doc-lib.js
 *
 * 飞书文档浏览器端 JS 工具库
 * 适用场景：browser-harness / Claude-in-Chrome 环境下，通过 js() 注入后调用
 *
 * 注入方式（Python browser-harness）：
 *   js(Path('feishu-doc-lib.js').read_text())
 *
 * 涵盖：
 *   1. 文本清洗（零宽字符）
 *   2. 大纲（Catalogue）操作
 *   3. 内容提取（虚拟滚动安全）
 *   4. 评论工具栏触发（MutationObserver）
 *   5. 评论输入与发送
 *   6. 面板关闭
 *
 * 设计原则：
 *   - 所有坐标通过 getBoundingClientRect() 动态获取，禁止硬编码
 *   - 操作前先 scrollIntoView，避免大纲条目超出视口导致坐标无效
 *   - 虚拟滚动安全：成员列表从大纲读取，不从文档 DOM 遍历
 */

'use strict';

// ─────────────────────────────────────────────────────────────────
// § 1  文本清洗
// ─────────────────────────────────────────────────────────────────

/**
 * 清除飞书文档中常见的零宽字符并 trim
 * 必须在所有文本比较前调用，否则 includes / startsWith 会误判
 */
window.feishuLib = window.feishuLib || {};

feishuLib.clean = (function() {
  const ZERO = /[​‌‍﻿‎]/g;
  return t => (t || '').replace(ZERO, '').trim();
})();


// ─────────────────────────────────────────────────────────────────
// § 2  大纲（Catalogue）操作
// ─────────────────────────────────────────────────────────────────

/**
 * 大纲是否已完整加载（通过 innerHTML 长度判断）
 * @returns {boolean}
 */
feishuLib.isCatalogueLoaded = function() {
  const cat = document.querySelector('.catalogue');
  return !!(cat && cat.innerHTML.length > 1000);
};

/**
 * 获取大纲入口按钮的运行时坐标（用于 CDP 点击）
 * 返回 {x, y} 或 null（未找到时）
 */
feishuLib.getCatalogueButtonCoord = function() {
  const el = document.querySelector('.catalogue__pin-wrapper');
  if (!el) return null;
  const r = el.getBoundingClientRect();
  if (r.width === 0) return null;
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
};

/**
 * 获取指定日期 + 成员的大纲条目运行时坐标
 *
 * @param {string} date  日期前缀，如 '0512'
 * @param {string} [name]  成员名，如 '孙聪'；省略则只找日期行
 * @returns {{ x, y, text } | { error, date, name }}
 *
 * 使用方式（Python）：
 *   coord = js('feishuLib.navToMember("0512", "孙聪")')
 *   if 'error' not in coord:
 *       cdp('Input.dispatchMouseEvent', type='mousePressed', x=coord['x'], y=coord['y'], ...)
 */
feishuLib.navToMember = function(date, name) {
  const clean = feishuLib.clean;
  const items = Array.from(document.querySelectorAll('.catalogue__list-item'));
  const dateIdx = items.findIndex(el => clean(el.textContent).startsWith(date));
  if (dateIdx < 0) return { error: 'date_not_found', date };

  const targets = name ? items.slice(dateIdx + 1) : [items[dateIdx]];
  for (const el of targets) {
    const txt = clean(el.textContent);
    if (name && /^\d{4}/.test(txt)) break;  // 到下一个日期，停止
    if (!name || txt.includes(name)) {
      // 先滚动到可见区域，再取坐标（大纲超出视口时坐标无效）
      el.scrollIntoView({ behavior: 'instant', block: 'nearest' });
      const r = el.getBoundingClientRect();
      return {
        x: Math.round(r.x + r.width / 2),
        y: Math.round(r.y + r.height / 2),
        text: txt.substring(0, 30),
      };
    }
  }
  return { error: 'member_not_found', date, name };
};

/**
 * 从大纲获取指定日期下的所有成员名称
 * 大纲是全量加载的，不受文档虚拟滚动影响
 *
 * @param {string} date  如 '0507'
 * @returns {string[]}  成员名列表
 *
 * ⚠ 关键：永远从大纲获取成员列表，不要从文档 DOM 遍历
 *   （文档 DOM 受虚拟滚动影响，视口外成员以 placeholder-wrapper 存在）
 */
feishuLib.getMembersForDate = function(date) {
  const clean = feishuLib.clean;
  const items = Array.from(document.querySelectorAll('.catalogue__list-item'));
  const dateIdx = items.findIndex(el => clean(el.textContent).startsWith(date));
  if (dateIdx < 0) return [];

  const members = [];
  for (const el of items.slice(dateIdx + 1)) {
    const txt = clean(el.textContent);
    if (/^\d{4}/.test(txt)) break;  // 到下一个日期，停止
    const name = txt.replace(/^\d+\.\s*/, '').trim();
    if (name) members.push(name);
  }
  return members;
};


// ─────────────────────────────────────────────────────────────────
// § 3  内容提取（虚拟滚动安全）
// ─────────────────────────────────────────────────────────────────

/**
 * 在已渲染的 DOM 中查找指定成员的 heading3 blockId
 * 两轮策略：
 *   1. 在 heading2 锚点范围内精确查找（heading2 在视口时）
 *   2. fallback：直接按名字找 heading3（heading2 已虚拟滚动卸载时）
 *
 * @param {string} date   如 '0507'
 * @param {string} name   如 '张晓宇'
 * @returns {string|null} blockId 或 null
 */
feishuLib.findHeadingId = function(date, name) {
  const clean = feishuLib.clean;
  const all = document.querySelectorAll('[data-block-id]');

  // 第一轮：精确（heading2 存在时）
  let inDate = false;
  for (const el of all) {
    const tp = el.getAttribute('data-block-type') || '';
    const tx = clean(el.innerText);
    if (tp === 'heading2' && tx.startsWith(date)) { inDate = true; continue; }
    if (tp === 'heading2' && inDate) break;
    if (inDate && tp === 'heading3' && tx.includes(name))
      return el.getAttribute('data-block-id');
  }

  // 第二轮 fallback：heading2 已卸载
  for (const el of document.querySelectorAll('[data-block-type="heading3"]')) {
    if (clean(el.innerText).includes(name))
      return el.getAttribute('data-block-id');
  }
  return null;
};

/**
 * 从 heading3 blockId 向下提取内容块（不依赖 heading2 在 DOM 中）
 * 遇到 heading2 / heading3 时停止
 *
 * @param {string} headingId  成员 heading3 的 blockId
 * @returns {Array<{blockId, type, text}>}
 */
feishuLib.fetchBlocksFromHeading = function(headingId) {
  const clean = feishuLib.clean;
  const isPlaceholder = c => /【.*?】/.test(c) || c.length < 3 || /^[\d.]+$/.test(c);
  const isSectionHeader = c => /^[一二三四]、/.test(c);

  const all = Array.from(document.querySelectorAll('[data-block-id]'));
  const si = all.findIndex(el => el.getAttribute('data-block-id') === headingId);
  if (si < 0) return [];

  const blocks = [];
  for (let i = si + 1; i < all.length; i++) {
    const el = all[i];
    const tp = el.getAttribute('data-block-type') || '';
    if (tp === 'heading2' || tp === 'heading3') break;
    const text = clean(el.innerText);
    if (!text || isPlaceholder(text) || isSectionHeader(text)) continue;
    blocks.push({ blockId: el.getAttribute('data-block-id'), type: tp, text });
  }
  return blocks;
};

/**
 * 提取整个日期下所有成员的日报内容（完整版，含结构化分段）
 *
 * ⚠ 使用前必须先导航到对应成员，确保其内容块已被渲染
 *
 * @param {string} targetDate  如 '0512'，null 表示全部
 * @returns {{ targetDate, dates: [{date, dateKey, members: [{name, sections, rawBlocks}]}] }}
 */
feishuLib.extractReportContent = function(targetDate) {
  const clean = feishuLib.clean;
  const blocks = Array.from(document.querySelectorAll('[data-block-id]'));
  const result = { targetDate: targetDate || 'all', dates: [] };
  let currentDate = null, currentMember = null;

  blocks.forEach(block => {
    const id   = block.getAttribute('data-block-id');
    const type = block.getAttribute('data-block-type') || '';
    const text = clean(block.innerText);
    if (!text || id === '1') return;

    // 日期标题 heading2："0512（周二）"
    if (type === 'heading2' && /^\d{4}/.test(text)) {
      const dateKey = text.match(/^(\d{4})/)?.[1];
      if (targetDate && dateKey !== targetDate) { currentDate = null; currentMember = null; return; }
      currentDate = { date: text, dateKey, members: [] };
      result.dates.push(currentDate);
      currentMember = null;
      return;
    }
    if (!currentDate) return;

    // 成员标题 heading3："1.\n王牧天"
    if (type === 'heading3') {
      const memberName = clean(text).replace(/^\d+\.\s*/, '');
      currentMember = { name: memberName, sections: {}, rawBlocks: [] };
      currentDate.members.push(currentMember);
      return;
    }
    if (!currentMember) return;

    const c = clean(text);
    if (!c) return;

    // section 标记
    if (c.startsWith('一、')) { currentMember._sec = 'leader确认'; return; }
    if (c.startsWith('二、')) { currentMember._sec = '今日工作';   return; }
    if (c.startsWith('三、')) { currentMember._sec = '待跟进';     return; }
    if (c.startsWith('四、')) { currentMember._sec = 'Todo';       return; }

    const sec = currentMember._sec || '其他';
    if (!currentMember.sections[sec]) currentMember.sections[sec] = [];

    const isPlaceholder = /【.*?】$/.test(c) || c.length < 3 || /^[\d.]+$/.test(c);
    if (!isPlaceholder) {
      const cleanText = c.replace(/^\d+\.\s*/, '');
      currentMember.sections[sec].push({ blockId: id, text: cleanText });
      currentMember.rawBlocks.push({ blockId: id, type, text: cleanText });
    }
  });

  result.dates.forEach(d => d.members.forEach(m => delete m._sec));
  return result;
};


// ─────────────────────────────────────────────────────────────────
// § 4  评论工具栏触发（MutationObserver）
// ─────────────────────────────────────────────────────────────────

/**
 * 挂载 MutationObserver，在工具栏出现时自动点击评论按钮
 *
 * ⚠ 必须在 CDP drag_select 之前调用！
 *   原因：执行 JS（本次调用）本身会导致飞书失焦，但 observer 是持续监听的，
 *   不会因失焦失效；而 drag_select 后执行 JS 会让工具栏消失。
 *
 * 调用顺序：
 *   1. js('feishuLib.armCommentObserver()')   ← 挂钩子
 *   2. cdp drag_select(x1, y, x2)            ← 真实拖选，触发工具栏
 *      → observer 自动在工具栏出现时点击评论按钮
 *   3. js('feishuLib.observerResult()')       ← 检查是否成功
 */
feishuLib.armCommentObserver = function() {
  if (window.__feishu_obs) window.__feishu_obs.disconnect();
  window.__feishu_obs_result = null;

  const obs = new MutationObserver(mutations => {
    for (const m of mutations) {
      for (const node of m.addedNodes) {
        if (node.nodeType !== 1) continue;
        const btn = (node.matches?.('.comment-item') ? node : null)
                 || node.querySelector?.('.comment-item');
        if (btn) {
          btn.click();
          obs.disconnect();
          window.__feishu_obs_result = 'clicked:' + btn.className.substring(0, 40);
          return;
        }
      }
    }
  });

  obs.observe(document.body, { childList: true, subtree: true });
  window.__feishu_obs = obs;
  // 5 秒超时保护
  setTimeout(() => {
    obs.disconnect();
    window.__feishu_obs_result = window.__feishu_obs_result || 'timeout';
  }, 5000);

  return 'observer armed';
};

/**
 * 查询 observer 执行结果
 * @returns {'pending' | 'clicked:...' | 'timeout'}
 */
feishuLib.observerResult = function() {
  return window.__feishu_obs_result || 'pending';
};

/**
 * 获取指定 block 中目标 snippet 文字的拖选坐标
 * 用于 CDP drag_select 时的 x1, x2, y 参数
 *
 * @param {string} blockId
 * @param {string} snippet  目标文字片段（用于定位 span）
 * @returns {{ x1, x2, y } | null}
 */
feishuLib.getSpanCoord = function(blockId, snippet) {
  const clean = feishuLib.clean;
  const block = document.querySelector(`[data-block-id="${blockId}"]`);
  if (!block) return null;

  block.scrollIntoView({ behavior: 'instant', block: 'center' });

  let span = null;
  for (const s of block.querySelectorAll('span')) {
    if (clean(s.textContent).includes(clean(snippet))) { span = s; break; }
  }
  if (!span) span = block.querySelector('.zone-container.text-editor');
  if (!span) return null;

  const r = span.getBoundingClientRect();
  return {
    x1: Math.round(r.left),
    x2: Math.round(r.right),
    y:  Math.round(r.top + r.height / 2),
  };
};


// ─────────────────────────────────────────────────────────────────
// § 5  评论输入与发送
// ─────────────────────────────────────────────────────────────────

/**
 * 在评论面板中输入文字并点击发送
 * 前提：armCommentObserver 已自动打开评论面板
 *
 * @param {string} commentText  评论内容（内部自动清理换行）
 * @returns {Promise<{success: true} | {error: string}>}
 */
feishuLib.typeAndSend = async function(commentText) {
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  // 换行会导致 execCommand 截断，统一替换为空格
  const safeText = commentText.replace(/[\r\n]+/g, ' ').trim();

  // 查找评论输入框（语义选择器，不用坐标）
  let input = document.querySelector('[class*="comment-side"] [contenteditable="true"]')
           || document.querySelector('[class*="comment-panel"] [contenteditable="true"]')
           || document.querySelector('[class*="comment-input"] [contenteditable="true"]');

  // fallback：所有 contenteditable 中不属于文档编辑区的最后一个
  if (!input) {
    input = Array.from(document.querySelectorAll('[contenteditable="true"]'))
      .filter(el => !el.closest('[data-block-id]'))
      .pop();
  }
  if (!input) return { error: 'comment_input_not_found' };

  input.focus();
  input.click();
  await sleep(150);
  document.execCommand('selectAll', false, null);
  document.execCommand('delete', false, null);
  document.execCommand('insertText', false, safeText);
  await sleep(200);

  // 查找发送按钮（按文字匹配，不用坐标）
  const sendBtn = Array.from(document.querySelectorAll('button, [role="button"]'))
    .find(b => b.offsetParent !== null &&
               (b.textContent.trim() === '发送' || b.textContent.trim() === 'Send'));
  if (sendBtn) {
    sendBtn.click();
    await sleep(500);
    return { success: true };
  }

  // fallback: Ctrl+Enter
  input.dispatchEvent(new KeyboardEvent('keydown', {
    key: 'Enter', code: 'Enter', keyCode: 13, ctrlKey: true, bubbles: true,
  }));
  await sleep(400);
  return { success: true, via: 'ctrl+enter' };
};


// ─────────────────────────────────────────────────────────────────
// § 6  面板关闭
// ─────────────────────────────────────────────────────────────────

/**
 * 关闭评论面板（Escape + 点击文档区域）
 */
feishuLib.closeCommentPanel = async function() {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  await sleep(300);
  const docArea = document.querySelector('.page-block');
  if (docArea) docArea.click();
  await sleep(400);
};


// ─────────────────────────────────────────────────────────────────
// § 7  便捷方法（Python 调用示例）
// ─────────────────────────────────────────────────────────────────

/*

## Python 调用示例（browser-harness）

```python
from browser_harness.helpers import js, cdp, wait

# 注入库
js(Path('feishu-doc-lib.js').read_text())

# ── 大纲操作 ──────────────────────────────────────
# 检查大纲是否加载
loaded = js('feishuLib.isCatalogueLoaded()')

# 获取大纲按钮坐标（由 CDP 点击）
btn = js('feishuLib.getCatalogueButtonCoord()')
if btn:
    cdp('Input.dispatchMouseEvent', type='mousePressed',  x=btn['x'], y=btn['y'], button='left', clickCount=1)
    cdp('Input.dispatchMouseEvent', type='mouseReleased', x=btn['x'], y=btn['y'], button='left', clickCount=1)

# 获取某日期下所有成员（虚拟滚动安全）
members = js('feishuLib.getMembersForDate("0507")')
# → ['高旭超', '王牧天', '王凯', '孙聪', '张晓宇']

# 导航到某成员
coord = js('feishuLib.navToMember("0507", "张晓宇")')
if 'error' not in coord:
    cdp('Input.dispatchMouseEvent', type='mousePressed',  x=coord['x'], y=coord['y'], button='left', clickCount=1)
    cdp('Input.dispatchMouseEvent', type='mouseReleased', x=coord['x'], y=coord['y'], button='left', clickCount=1)

# ── 内容提取（逐人导航后提取）────────────────────
for name in members:
    # 导航触发渲染
    coord = js(f'feishuLib.navToMember("0507", "{name}")')
    cdp(...)  # 点击

    # 等待 heading3 出现（最多 8 秒）
    heading_id = None
    for _ in range(16):
        wait(0.5)
        heading_id = js(f'feishuLib.findHeadingId("0507", "{name}")')
        if heading_id: break

    # 提取内容块
    blocks = js(f'feishuLib.fetchBlocksFromHeading("{heading_id}")')

# ── 评论提交（单条）──────────────────────────────
# Step 1: 拿到 span 坐标
coord = js(f'feishuLib.getSpanCoord("{block_id}", "{snippet}")')

# Step 2: 先挂 observer，再 drag_select（顺序不能反！）
js('feishuLib.armCommentObserver()')
drag_select(coord['x1'], coord['y'], coord['x2'])  # CDP 真实拖选
wait(1.0)

# Step 3: 检查工具栏是否触发
obs = js('feishuLib.observerResult()')
# 'clicked:...' → 成功，评论面板已打开

# Step 4: 输入并发送
js(f'feishuLib.typeAndSend({json.dumps(comment)})')
wait(0.8)

# Step 5: 关闭面板（下一条前执行）
js('feishuLib.closeCommentPanel()')
```

*/

'feishu-doc-lib.js loaded ✓  (feishuLib namespace ready)';
