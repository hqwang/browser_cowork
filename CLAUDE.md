language: use chinese reply to save token.

## 浏览器自动化操作规范

模拟页面操作时，优先通过 DOM 元素定位，禁止直接使用硬编码的绝对坐标或固定尺寸：

1. **优先用语义定位**：`document.querySelector(selector).click()` 或读取 `getBoundingClientRect()` 获取运行时坐标
2. **禁止写死坐标**：不允许出现 `click_at_xy(x, y)` 或 `cdp(..., x=123, y=456)` 这类数字字面量
3. **找不到 selector 时**：先用 JS 探查 DOM 结构（`className`、`id`、`aria-label`、`data-*`），找到稳定标识后再操作，不要猜坐标
4. **坐标只能来自**：`getBoundingClientRect()` 动态计算，或封装好的定位函数