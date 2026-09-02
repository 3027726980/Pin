/**
 * 文档处理任务全局状态（处理浮窗数据源）
 *
 * - 跨页面保持：store 模块级，轮询不随组件销毁
 * - 上传/手动触发处理时调用 startPolling()，全局无任务后自动停止
 * - 全部完成 → done=true（组件据此变绿 + 弹提醒）
 * - 手动关闭（dismiss）后本批次不再自动弹出，下次 startPolling 重置
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getProcessingTasks, type ProcessingTask } from '@/api/knowledge'

export const useProcessingStore = defineStore('processing', () => {
  const tasks = ref<ProcessingTask[]>([])
  const visible = ref(false) // 浮窗是否显示
  const minimized = ref(false) // 是否折叠为小胶囊
  const done = ref(false) // 本批次全部完成（触发绿色 + 提醒）

  let timer: ReturnType<typeof setInterval> | null = null
  let hadTasks = false // 上一轮是否有任务（完成检测）
  let dismissed = false // 用户手动关闭标记（本次轮询周期内不再自动弹）

  /** 拉取一次任务列表并更新状态 */
  async function refresh() {
    let list: ProcessingTask[]
    try {
      list = await getProcessingTasks()
    } catch {
      return // 网络/401 等静默失败，下轮重试
    }
    tasks.value = list

    if (list.length > 0) {
      hadTasks = true
      done.value = false
      if (!dismissed) visible.value = true
    } else if (hadTasks) {
      // 从"有任务"变为"无任务" → 本批次全部完成
      hadTasks = false
      done.value = true
      visible.value = true
      stopPolling()
    }
  }

  /** 开始全局轮询（幂等；新批次重置关闭标记） */
  function startPolling() {
    dismissed = false
    if (!visible.value) {
      visible.value = true
      minimized.value = false
    }
    refresh()
    if (!timer) {
      timer = setInterval(refresh, 2000)
    }
  }

  /** 停止轮询 */
  function stopPolling() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  /** 手动关闭浮窗（本次轮询周期不再自动弹出） */
  function dismiss() {
    visible.value = false
    dismissed = true
  }

  /** 切换折叠/展开 */
  function toggleMinimize() {
    minimized.value = !minimized.value
  }

  /** 收起"完成"状态（用户看完后手动收起） */
  function closeDone() {
    done.value = false
    visible.value = false
  }

  return {
    tasks,
    visible,
    minimized,
    done,
    startPolling,
    stopPolling,
    dismiss,
    toggleMinimize,
    closeDone,
  }
})
