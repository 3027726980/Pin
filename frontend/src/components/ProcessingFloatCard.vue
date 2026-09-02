<!--
文档处理全局浮窗（右下角）：跨页面显示所有知识库的处理任务
- store 驱动（轮询在 stores/processing.ts，组件销毁不中断）
- 展开卡片：知识库名 + 文件名（省略号）+ 阶段标签；最多展示 4 条，其余折叠为"等 N 个"
- 折叠为小胶囊（文字省略）；可手动关闭；全部完成 → 绿色 + 消息提醒
-->
<template>
  <div v-if="store.visible" class="proc-float">
    <!-- 折叠态：小胶囊 -->
    <div
      v-if="store.minimized"
      class="proc-mini"
      :class="{ done: store.done }"
      role="button"
      title="展开处理进度"
      @click="store.toggleMinimize()"
    >
      <n-icon size="15"><CloudUploadOutline /></n-icon>
      <span class="mini-text">{{ store.done ? '✓ 处理完成' : `${store.tasks.length} 个文件处理中` }}</span>
      <n-icon size="14" style="flex-shrink: 0"><ChevronUpOutline /></n-icon>
    </div>

    <!-- 展开态：卡片 -->
    <n-card v-else size="small" class="proc-card" :class="{ done: store.done }">
      <template #header>
        <div class="proc-head">
          <span class="proc-title">
            <n-icon size="16" style="vertical-align: -3px; margin-right: 4px">
              <CloudUploadOutline />
            </n-icon>
            {{ store.done ? '处理完成' : '文档处理中' }}
          </span>
          <span class="proc-actions">
            <n-button text size="tiny" title="折叠" @click="store.toggleMinimize()">
              <n-icon><ChevronDownOutline /></n-icon>
            </n-button>
            <n-button text size="tiny" title="关闭" @click="onClose">
              <n-icon><CloseOutline /></n-icon>
            </n-button>
          </span>
        </div>
      </template>

      <!-- 完成态 -->
      <div v-if="store.done" class="proc-done">
        <n-icon size="24" color="#18a058"><CheckmarkCircleOutline /></n-icon>
        <span>全部文件处理完成</span>
      </div>

      <!-- 任务列表 -->
      <div v-else class="proc-list">
        <div v-for="t in visibleTasks" :key="t.doc_id" class="proc-item">
          <n-tag :type="stageType(t.stage)" size="tiny" :bordered="false" class="proc-stage">
            {{ stageLabel(t.stage) }}
          </n-tag>
          <span class="proc-file" :title="`${t.kb_name} / ${t.filename}`">
            <span class="proc-kb">{{ t.kb_name }}</span>
            <span class="proc-name">{{ t.filename }}</span>
          </span>
        </div>
        <div v-if="store.tasks.length > visibleTasks.length" class="proc-more">
          等 {{ store.tasks.length - visibleTasks.length }} 个文件…
        </div>
      </div>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { useMessage } from 'naive-ui'
import {
  CheckmarkCircleOutline,
  ChevronDownOutline,
  ChevronUpOutline,
  CloseOutline,
  CloudUploadOutline,
} from '@vicons/ionicons5'
import { useProcessingStore } from '@/stores/processing'

const store = useProcessingStore()
const message = useMessage()

const MAX_SHOW = 4
const visibleTasks = computed(() => store.tasks.slice(0, MAX_SHOW))

const STAGE_MAP: Record<string, { label: string; type: 'default' | 'info' | 'warning' }> = {
  queued: { label: '排队中', type: 'default' },
  parsing: { label: '解析中', type: 'info' },
  chunking: { label: '切片中', type: 'info' },
  vectorizing: { label: '向量化', type: 'warning' },
  processing: { label: '处理中', type: 'info' },
}

function stageLabel(stage: string): string {
  return STAGE_MAP[stage]?.label || '处理中'
}

function stageType(stage: string): 'default' | 'info' | 'warning' {
  return STAGE_MAP[stage]?.type || 'info'
}

function onClose() {
  if (store.done) {
    store.closeDone()
  } else {
    store.dismiss()
  }
}

// 本批次全部完成 → 弹消息提醒
watch(
  () => store.done,
  (v) => {
    if (v) message.success('文档处理完成，可以开始对话了')
  },
)
</script>

<style scoped>
.proc-float {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 3000;
}

/* 折叠胶囊 */
.proc-mini {
  display: flex;
  align-items: center;
  gap: 6px;
  max-width: 280px;
  padding: 9px 16px;
  border-radius: 20px;
  background: #2080f0;
  color: #fff;
  font-size: 13px;
  cursor: pointer;
  box-shadow: 0 4px 16px rgba(32, 128, 240, 0.35);
  transition: all 0.2s;
}
.proc-mini:hover {
  filter: brightness(1.1);
}
.proc-mini.done {
  background: #18a058;
  box-shadow: 0 4px 16px rgba(24, 160, 88, 0.35);
}
.mini-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 展开卡片 */
.proc-card {
  width: 360px;
  border: 1px solid rgba(32, 128, 240, 0.35);
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.12);
}
.proc-card.done {
  border-color: rgba(24, 160, 88, 0.45);
  background: linear-gradient(180deg, #f6fffa, #fff);
}
.proc-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}
.proc-title {
  font-weight: 600;
  font-size: 14px;
}
.proc-actions {
  display: flex;
  gap: 2px;
}

/* 完成态 */
.proc-done {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 2px;
  color: #18a058;
  font-weight: 600;
}

/* 任务列表 */
.proc-list {
  max-height: 240px;
  overflow-y: auto;
}
.proc-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 0;
  border-bottom: 1px dashed var(--n-border-color);
}
.proc-item:last-child {
  border-bottom: none;
}
.proc-stage {
  flex-shrink: 0;
}
.proc-file {
  display: flex;
  align-items: center;
  min-width: 0;
  gap: 6px;
  font-size: 13px;
}
.proc-kb {
  flex-shrink: 0;
  color: var(--n-text-color-3);
  font-size: 12px;
}
.proc-kb::after {
  content: '/';
  margin-left: 6px;
  color: var(--n-text-color-3);
}
.proc-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.proc-more {
  padding: 6px 0 2px;
  font-size: 12px;
  color: var(--n-text-color-3);
  text-align: center;
}
</style>
