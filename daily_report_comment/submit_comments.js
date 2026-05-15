/**
 * submit_comments.js
 *
 * 工作机制：
 * ─────────────────────────────────────────────
 * 飞书工具栏只响应 isTrusted=true 的真实鼠标事件，JS 合成事件无效。
 * 执行 JS tool call 本身也会让工具栏消失（焦点变化）。
 *
 * 解决方案：MutationObserver 在工具栏出现的瞬间自动点击评论按钮，
 * 完全不需要硬编码坐标，也不需要截图。
 *
 * 每条 comment 提交流程：
 *   1. JS: __armCommentObserver()          — 挂载 observer，等待工具栏出现
 *   2. browser_batch: left_click_drag(x1,y → x2,y) — 真实拖选，触发工具栏
 *      observer 自动在工具栏出现时点击评论按钮，打开评论面板
 *   3. JS: await __typeAndSend(text)       — 在评论面板输入并发送
 *
 * 大纲导航：
 *   __navToMember(date, name)  — 返回大纲条目坐标，Claude 用 browser_batch 点击
 * ─────────────────────────────────────────────
 */

// ── 大纲导航 ──────────────────────────────────

window.__isCatalogueLoaded = function() {
  const cat = document.querySelector('.catalogue');
  return !!(cat && cat.innerHTML.length > 1000);
};

/**
 * 在大纲中查找指定日期 + 成员的条目坐标（用于 browser_batch 点击跳转）
 * @param {string} date  如 '0512'
 * @param {string} name  如 '孙聪'（可不传，只找日期行）
 */
window.__navToMember = function(date, name) {
  const items = Array.from(document.querySelectorAll('.catalogue__list-item'));
  const dateIdx = items.findIndex(el => el.textContent.trim().startsWith(date));
  if (dateIdx < 0) return { error: 'date_not_found', date };

  const targetItems = name ? items.slice(dateIdx + 1) : [items[dateIdx]];
  for (const el of targetItems) {
    const txt = el.textContent.trim();
    if (name && /^\d{4}/.test(txt)) break; // 到下一个日期了
    if (!name || txt.includes(name)) {
      // 先滚动到可见区域，再取坐标，避免大纲列表超出屏幕时坐标无效
      el.scrollIntoView({ behavior: 'instant', block: 'nearest' });
      const r = el.getBoundingClientRect();
      return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2), text: txt.substring(0, 25) };
    }
  }
  return { error: 'member_not_found', date, name };
};

/**
 * 从大纲获取指定日期下的所有成员名称
 * 大纲是全量加载的，不受虚拟滚动影响，可以拿到所有成员（包括尚未渲染的）
 * @param {string} date  如 '0507'
 * @returns {string[]}   成员名列表，如 ['高旭超', '王牧天', '王凯', '孙聪', '张晓宇']
 */
window.__getMembersForDate = function(date) {
  const items = Array.from(document.querySelectorAll('.catalogue__list-item'));
  const dateIdx = items.findIndex(el => el.textContent.trim().startsWith(date));
  if (dateIdx < 0) return [];

  const members = [];
  for (const el of items.slice(dateIdx + 1)) {
    const txt = el.textContent.trim();
    if (/^\d{4}/.test(txt)) break;           // 到下一个日期，停止
    const name = txt.replace(/^\d+\.\s*/, '').trim();
    if (name) members.push(name);
  }
  return members;
};

// ── 坐标准备 ──────────────────────────────────

/**
 * 获取每条 confirmed comment 对应 span 的拖选坐标
 * Claude 拿到坐标后用 browser_batch left_click_drag 做真实拖选
 */
window.__getSubmitCoords = function() {
  const queue = window.__CONFIRMED_COMMENTS;
  if (!queue || !queue.length) return { error: 'no confirmed comments' };

  const ZERO = /[​‌‍﻿​]/g;
  const clean = t => (t || '').replace(ZERO, '').trim();

  return queue.map(item => {
    const block = document.querySelector('[data-block-id="' + item.blockId + '"]');
    if (!block) return { ...item, error: 'block_not_found' };

    block.scrollIntoView({ behavior: 'instant', block: 'center' });

    let span = null;
    for (const s of block.querySelectorAll('span')) {
      if (clean(s.textContent).includes(clean(item.snippet))) { span = s; break; }
    }
    if (!span) span = block.querySelector('.zone-container.text-editor');
    if (!span) return { ...item, error: 'span_not_found' };

    const r = span.getBoundingClientRect();
    return {
      member: item.member,
      snippet: item.snippet,
      blockId: item.blockId,
      comment: item.comment,
      x1: Math.round(r.left),
      x2: Math.round(r.right),
      y: Math.round(r.top + r.height / 2),
    };
  });
};

// ── Phase 2：MutationObserver 自动点击评论按钮 ──

/**
 * 挂载 observer，在工具栏出现时自动点击评论按钮。
 * 必须在 browser_batch 拖选之前调用。
 * 拖选完成后用 __observerResult() 检查是否成功。
 */
window.__armCommentObserver = function() {
  if (window.__COMMENT_OBS) window.__COMMENT_OBS.disconnect();
  window.__COMMENT_OBS_RESULT = null;

  const obs = new MutationObserver(mutations => {
    for (const m of mutations) {
      for (const node of m.addedNodes) {
        if (node.nodeType !== 1) continue;
        // 查找评论按钮（工具栏中 class 含 comment-item 的元素）
        const btn = node.matches && node.matches('.comment-item')
          ? node
          : node.querySelector && node.querySelector('.comment-item');
        if (btn) {
          btn.click();
          obs.disconnect();
          window.__COMMENT_OBS_RESULT = 'clicked:' + btn.className.substring(0, 40);
          return;
        }
      }
    }
  });

  obs.observe(document.body, { childList: true, subtree: true });
  window.__COMMENT_OBS = obs;
  // 5 秒超时保护
  setTimeout(() => { obs.disconnect(); window.__COMMENT_OBS_RESULT = window.__COMMENT_OBS_RESULT || 'timeout'; }, 5000);
  return 'observer armed';
};

window.__observerResult = function() {
  return window.__COMMENT_OBS_RESULT || 'pending';
};

// ── Phase 3：输入 + 发送 ──────────────────────

/**
 * 在评论面板中输入文字并点击发送
 * observer 已自动打开评论面板后调用此函数
 */
window.__typeAndSend = async function(commentText) {
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  // 找评论输入框：在 comment-side 面板内的 contenteditable
  // 优先用语义选择器，避免硬编码坐标
  let input = document.querySelector('[class*="comment-side"] [contenteditable="true"]')
           || document.querySelector('[class*="comment-panel"] [contenteditable="true"]')
           || document.querySelector('[class*="comment-input"] [contenteditable="true"]');

  // fallback：取所有 contenteditable 中不属于文档编辑区的最后一个
  if (!input) {
    input = Array.from(document.querySelectorAll('[contenteditable="true"]'))
      .filter(el => !el.closest('[data-block-id]'))
      .pop();
  }

  if (!input) return { error: 'comment_input_not_found' };

  // 换行符会导致 execCommand 截断，统一替换为空格
  const safeText = commentText.replace(/[\r\n]+/g, ' ').trim();

  input.focus();
  input.click();
  await sleep(150);
  document.execCommand('selectAll', false, null);
  document.execCommand('delete', false, null);
  document.execCommand('insertText', false, safeText);
  await sleep(200);

  // 找「发送」按钮：用文字匹配，不用坐标
  const sendBtn = Array.from(document.querySelectorAll('button, [role="button"]')).find(b =>
    b.offsetParent !== null &&  // 可见
    (b.textContent.trim() === '发送' || b.textContent.trim() === 'Send')
  );
  if (sendBtn) {
    sendBtn.click();
    await sleep(500);
    return { success: true };
  }

  // fallback: Ctrl+Enter
  input.dispatchEvent(new KeyboardEvent('keydown', {
    key: 'Enter', code: 'Enter', keyCode: 13, ctrlKey: true, bubbles: true
  }));
  await sleep(400);
  return { success: true, via: 'ctrl+enter' };
};

// ── 关闭评论面板 ─────────────────────────────

window.__closeCommentPanel = async function() {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  await sleep(300);
  // 点击文档内容区（用选择器，不用固定坐标）
  const docArea = document.querySelector('.page-block');
  if (docArea) docArea.click();
  await sleep(400);
};

'submit_comments.js loaded ✓';
