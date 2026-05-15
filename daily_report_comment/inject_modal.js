/**
 * inject_modal.js
 * 向飞书文档页面注入确认弹窗
 * 使用前需设置 window.__COMMENT_DATA = { rows: [ { member, snippet, blockId, comment } ] }
 * 用户点击"确定"后：window.__CONFIRMED_COMMENTS 包含勾选行的数组
 * 用户点击"取消"后：window.__MODAL_CANCELLED = true
 */
(function injectCommentModal() {
  // 若已存在则移除旧弹窗
  const existing = document.getElementById('__lark_comment_modal__');
  if (existing) existing.remove();

  const data = window.__COMMENT_DATA;
  if (!data || !data.rows || !data.rows.length) {
    alert('没有需要确认的 comment，请先设置 window.__COMMENT_DATA');
    return;
  }

  // ── 样式
  const style = document.createElement('style');
  style.textContent = `
    #__lark_comment_modal__ {
      position: fixed; inset: 0; z-index: 99999;
      background: rgba(0,0,0,.45);
      display: flex; align-items: center; justify-content: center;
      font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Helvetica Neue', sans-serif;
    }
    #__lark_comment_modal__ .modal-box {
      background: #fff; border-radius: 12px;
      width: min(92vw, 960px); max-height: 80vh;
      display: flex; flex-direction: column;
      box-shadow: 0 20px 60px rgba(0,0,0,.2);
      overflow: hidden;
    }
    #__lark_comment_modal__ .modal-header {
      padding: 18px 24px 14px; border-bottom: 1px solid #f0f0f0;
      display: flex; align-items: center; justify-content: space-between;
    }
    #__lark_comment_modal__ .modal-title {
      font-size: 16px; font-weight: 500; color: #1a1a1a;
    }
    #__lark_comment_modal__ .modal-subtitle {
      font-size: 12px; color: #999; margin-top: 2px;
    }
    #__lark_comment_modal__ .modal-body {
      flex: 1; overflow-y: auto; padding: 0;
    }
    #__lark_comment_modal__ table {
      width: 100%; border-collapse: collapse; font-size: 13px;
    }
    #__lark_comment_modal__ th {
      background: #fafafa; padding: 10px 14px;
      text-align: left; font-weight: 500; color: #555;
      border-bottom: 1px solid #f0f0f0; font-size: 12px;
      position: sticky; top: 0;
    }
    #__lark_comment_modal__ td {
      padding: 10px 14px; border-bottom: 1px solid #f5f5f5;
      vertical-align: top; color: #1a1a1a;
    }
    #__lark_comment_modal__ tr:hover td { background: #fafafe; }
    #__lark_comment_modal__ .member-cell {
      font-weight: 500; color: #1a1a1a; white-space: nowrap; min-width: 60px;
    }
    #__lark_comment_modal__ .snippet-cell {
      color: #555; font-size: 12px; max-width: 200px;
      background: #f8f8f8; border-radius: 4px; padding: 6px 8px !important;
      line-height: 1.5;
    }
    #__lark_comment_modal__ .comment-cell textarea {
      width: 100%; min-height: 70px; border: 1px solid #e0e0e0;
      border-radius: 6px; padding: 7px 9px; font-size: 13px;
      line-height: 1.6; resize: vertical; font-family: inherit;
      color: #1a1a1a; outline: none; box-sizing: border-box;
    }
    #__lark_comment_modal__ .comment-cell textarea:focus {
      border-color: #4e83fd;
    }
    #__lark_comment_modal__ .check-cell {
      text-align: center; width: 50px;
    }
    #__lark_comment_modal__ .check-cell input[type=checkbox] {
      width: 16px; height: 16px; cursor: pointer; accent-color: #4e83fd;
    }
    #__lark_comment_modal__ tr.unchecked td { opacity: .45; }
    #__lark_comment_modal__ .modal-footer {
      padding: 14px 24px; border-top: 1px solid #f0f0f0;
      display: flex; gap: 10px; justify-content: flex-end; align-items: center;
    }
    #__lark_comment_modal__ .count-tip {
      font-size: 12px; color: #888; flex: 1;
    }
    #__lark_comment_modal__ .btn {
      padding: 8px 22px; border-radius: 7px; font-size: 14px;
      cursor: pointer; border: none; font-family: inherit;
    }
    #__lark_comment_modal__ .btn-cancel {
      background: #fff; border: 1px solid #d9d9d9; color: #555;
    }
    #__lark_comment_modal__ .btn-cancel:hover { background: #f5f5f5; }
    #__lark_comment_modal__ .btn-confirm {
      background: #4e83fd; color: #fff;
    }
    #__lark_comment_modal__ .btn-confirm:hover { background: #3a70e8; }
    #__lark_comment_modal__ .tag-num {
      display: inline-block; background: #e8f0ff; color: #4e83fd;
      border-radius: 10px; padding: 1px 8px; font-size: 11px; margin-left: 6px;
    }
  `;
  document.head.appendChild(style);

  // ── 构建行 HTML
  const rows = data.rows;
  const rowsHTML = rows.map((row, i) => `
    <tr id="row_${i}" class="">
      <td class="check-cell">
        <input type="checkbox" id="chk_${i}" checked onchange="
          const tr = this.closest('tr');
          tr.classList.toggle('unchecked', !this.checked);
          document.getElementById('__confirmed_count__').textContent =
            document.querySelectorAll('#__lark_comment_modal__ input[type=checkbox]:checked').length + ' 条待提交';
        ">
      </td>
      <td class="member-cell">${escapeHtml(row.member)}</td>
      <td class="snippet-cell">${escapeHtml(row.snippet)}</td>
      <td class="comment-cell">
        <textarea id="cmt_${i}">${escapeHtml(row.comment)}</textarea>
      </td>
    </tr>
  `).join('');

  function escapeHtml(s) {
    return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  // ── 弹窗 DOM
  const modal = document.createElement('div');
  modal.id = '__lark_comment_modal__';
  modal.innerHTML = `
    <div class="modal-box">
      <div class="modal-header">
        <div>
          <div class="modal-title">日报 Comment 确认 <span class="tag-num">${rows.length} 条建议</span></div>
          <div class="modal-subtitle">勾选需要提交的 comment，可直接编辑文字后再确认</div>
        </div>
      </div>
      <div class="modal-body">
        <table>
          <thead>
            <tr>
              <th style="width:50px">提交</th>
              <th style="width:70px">成员</th>
              <th style="width:200px">日报片段</th>
              <th>Comment 建议（可编辑）</th>
            </tr>
          </thead>
          <tbody>${rowsHTML}</tbody>
        </table>
      </div>
      <div class="modal-footer">
        <span class="count-tip" id="__confirmed_count__">${rows.length} 条待提交</span>
        <button class="btn btn-cancel" id="__modal_cancel__">取消</button>
        <button class="btn btn-confirm" id="__modal_confirm__">确定，批量提交 Comment</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);

  // ── 绑定按钮
  document.getElementById('__modal_cancel__').onclick = function() {
    window.__MODAL_CANCELLED = true;
    window.__CONFIRMED_COMMENTS = null;
    modal.remove();
    style.remove();
  };

  document.getElementById('__modal_confirm__').onclick = function() {
    const confirmed = [];
    rows.forEach((row, i) => {
      const chk = document.getElementById('chk_' + i);
      if (chk && chk.checked) {
        confirmed.push({
          member: row.member,
          snippet: row.snippet,
          blockId: row.blockId,
          comment: document.getElementById('cmt_' + i).value
        });
      }
    });
    window.__CONFIRMED_COMMENTS = confirmed;
    window.__MODAL_CANCELLED = false;
    modal.remove();
    style.remove();
    console.log('[AutoComment] confirmed:', confirmed.length, 'items');
  };
})();
