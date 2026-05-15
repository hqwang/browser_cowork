/**
 * extract_content.js
 * 注入飞书文档页面，提取日报内容，按日期和成员结构化返回
 * 用法：在 javascript_tool 中 eval 此文件内容，传入 targetDate（如 '0512'）或 null（全部）
 */
(function extractReportContent(targetDate) {
  const ZERO_WIDTH = /[​‌‍﻿​]/g;
  const clean = t => (t || '').replace(ZERO_WIDTH, '').trim();

  // 先滚动触发懒加载
  const blocks = Array.from(document.querySelectorAll('[data-block-id]'));

  const result = { targetDate: targetDate || 'all', dates: [] };
  let currentDate = null;
  let currentMember = null;

  blocks.forEach(block => {
    const id = block.getAttribute('data-block-id');
    const type = block.getAttribute('data-block-type') || '';
    const text = clean(block.innerText);

    if (!text || id === '1') return;

    // ── 日期标题 (heading2)，格式如 "0512（周二）"
    if (type === 'heading2' && /^\d{4}/.test(text)) {
      const dateKey = text.match(/^(\d{4})/)?.[1];
      if (targetDate && dateKey !== targetDate) {
        currentDate = null; currentMember = null; return;
      }
      currentDate = { date: text, dateKey, members: [] };
      result.dates.push(currentDate);
      currentMember = null;
      return;
    }

    if (!currentDate) return;

    // ── 成员标题 (heading3)，格式如 "1.\n王牧天"
    if (type === 'heading3') {
      const memberName = clean(text).replace(/^\d+\.\s*/, '');
      currentMember = { name: memberName, sections: {}, rawBlocks: [] };
      currentDate.members.push(currentMember);
      return;
    }

    if (!currentMember) return;

    // ── 内容块（text / ordered / bullet）
    const c = clean(text);
    if (!c) return;

    // 判断所属 section
    if (c.startsWith('一、')) { currentMember._sec = 'leader确认'; return; }
    if (c.startsWith('二、')) { currentMember._sec = '今日工作'; return; }
    if (c.startsWith('三、')) { currentMember._sec = '待跟进'; return; }
    if (c.startsWith('四、')) { currentMember._sec = 'Todo'; return; }

    const sec = currentMember._sec || '其他';
    if (!currentMember.sections[sec]) currentMember.sections[sec] = [];

    // 过滤模板占位文字
    const isPlaceholder = /【.*?】$/.test(c) || c.length < 3 || /^[\d\.]+$/.test(c);
    if (!isPlaceholder) {
      currentMember.sections[sec].push({ blockId: id, text: c.replace(/^\d+\.\s*/, '') });
      currentMember.rawBlocks.push({ blockId: id, type, text: c.replace(/^\d+\.\s*/, '') });
    }
  });

  // 清理内部状态键
  result.dates.forEach(d => d.members.forEach(m => delete m._sec));
  return result;
})
