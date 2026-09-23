# File Preview Drawer Height Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让文件预览抽屉在桌面端占满标题栏以下的可用高度，消除底部空白，同时保留小屏单列滚动体验。

**Architecture:** 使用 Naive UI `NDrawerContent` 已提供的 `body-content-style` 将正文变成满高、隐藏外层滚动的容器。预览网格及其三列通过 `height: 100%`、`min-height: 0` 和 flex 布局传递可用高度，各列内容独立滚动；窄屏媒体查询恢复自然高度与抽屉正文滚动。

**Tech Stack:** Vue 3 SFC、TypeScript、Naive UI、CSS Grid/Flexbox、Vitest、Vite

---

### Task 1: 增加预览抽屉满高布局回归测试

**Files:**
- Modify: `frontend/src/views/knowledge/KnowledgeDetailView.test.ts`
- Test: `frontend/src/views/knowledge/KnowledgeDetailView.test.ts`

- [ ] **Step 1: Write the failing test**

在 `knowledge detail layout` 测试组中增加：

```ts
it('fills the preview drawer body instead of capping columns at 650px', () => {
  expect(source).toContain('body-content-style="height: 100%; overflow: hidden;"')
  expect(source).toContain('.preview-layout { display: grid;')
  expect(source).toContain('height: 100%; min-height: 0;')
  expect(source).not.toContain('max-height: 650px')
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test:unit -- src/views/knowledge/KnowledgeDetailView.test.ts`

Expected: FAIL，提示源码尚不包含 `body-content-style="height: 100%; overflow: hidden;"`，并仍含有 `max-height: 650px`。

### Task 2: 实现桌面端满高与小屏回退布局

**Files:**
- Modify: `frontend/src/views/knowledge/KnowledgeDetailView.vue:74-113`
- Modify: `frontend/src/views/knowledge/KnowledgeDetailView.vue:306-314`

- [ ] **Step 1: Configure the drawer body as the height container**

将文件预览的抽屉正文改为：

```vue
<n-drawer-content
  :title="previewRow ? `${previewRow.filename} · 预览与重新处理` : '文件预览'"
  body-content-style="height: 100%; overflow: hidden;"
  closable
>
```

- [ ] **Step 2: Pass available height through the loading and column containers**

为加载器添加 `preview-spin` 类，并将桌面端样式调整为：

```css
.preview-spin { height: 100%; }
.preview-spin :deep(.n-spin-content) { height: 100%; }
.preview-layout { display: grid; grid-template-columns: minmax(280px, 320px) minmax(0, 1fr) minmax(0, 1fr); gap: 16px; height: 100%; min-height: 0; }
.preview-strategy { min-width: 0; min-height: 0; overflow-y: auto; padding-right: 16px; border-right: 1px solid var(--n-border-color); }
.preview-source-column, .preview-result-column { min-width: 0; min-height: 0; }
.preview-source-column { display: flex; flex-direction: column; }
.preview-result-column :deep(.n-tabs) { height: 100%; }
.preview-result-column :deep(.n-tabs-pane-wrapper),
.preview-result-column :deep(.n-tab-pane) { min-height: 0; }
.preview-result-column :deep(.n-tab-pane) { height: 100%; overflow: auto; }
.text-pane { min-height: 0; overflow: auto; padding: 12px; border: 1px solid var(--n-border-color); border-radius: 4px; }
.preview-source-column .text-pane { flex: 1; }
```

- [ ] **Step 3: Restore natural flow below 1000px**

在现有媒体查询中设置预览布局和各容器为自然高度，并允许抽屉正文外层滚动：

```css
@media (max-width: 1000px) {
  .preview-layout { grid-template-columns: 1fr; height: auto; }
  .preview-spin, .preview-spin :deep(.n-spin-content) { height: auto; }
  .preview-strategy { min-height: auto; padding-right: 0; padding-bottom: 16px; border-right: 0; border-bottom: 1px solid var(--n-border-color); }
  .preview-source-column, .preview-result-column { min-height: auto; }
  .preview-source-column .text-pane { flex: none; }
  .preview-result-column :deep(.n-tabs),
  .preview-result-column :deep(.n-tab-pane) { height: auto; }
}
```

同时给抽屉正文添加类名，并在媒体查询中将其 `overflow` 恢复为 `auto`。

- [ ] **Step 4: Run the focused test**

Run: `npm run test:unit -- src/views/knowledge/KnowledgeDetailView.test.ts`

Expected: PASS，3 个布局测试全部通过。

### Task 3: 完整验证与提交

**Files:**
- Verify: `frontend/src/views/knowledge/KnowledgeDetailView.vue`
- Verify: `frontend/src/views/knowledge/KnowledgeDetailView.test.ts`

- [ ] **Step 1: Run all frontend unit tests**

Run: `npm run test:unit`

Expected: PASS，0 个失败测试。

- [ ] **Step 2: Run the production build**

Run: `npm run build`

Expected: `vue-tsc --noEmit` 与 `vite build` 均成功，命令退出码为 0。

- [ ] **Step 3: Verify the desktop and narrow browser layouts**

使用项目现有前端服务或临时 Vite 服务，在桌面视口打开知识库详情的文件预览：三列延伸到抽屉正文底部附近且内部独立滚动。将视口缩窄到 1000px 以下：内容切换为单列并由抽屉正文自然滚动。测试结束后关闭本轮临时启动的服务。

- [ ] **Step 4: Inspect the final diff**

Run: `git diff --check` 和 `git diff -- frontend/src/views/knowledge/KnowledgeDetailView.vue frontend/src/views/knowledge/KnowledgeDetailView.test.ts`

Expected: 无空白错误，变更仅涉及预览抽屉高度布局及对应测试。

- [ ] **Step 5: Commit**

```powershell
git add -- frontend/src/views/knowledge/KnowledgeDetailView.vue frontend/src/views/knowledge/KnowledgeDetailView.test.ts docs/superpowers/plans/2026-09-23-preview-drawer-height.md
git commit -m "fix: 让文件预览抽屉自适应可用高度"
```
