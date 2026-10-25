<!-- 作者：LHF；时间：2026-10-25；作用：本地技能上传、格式诊断、预览与维护。 -->
<template>
  <div>
    <n-space justify="space-between" align="center" style="margin-bottom: 18px">
      <h2 style="margin: 0">技能管理</h2>
      <n-space><n-button :loading="loading" @click="refresh">刷新</n-button><n-button type="primary" :loading="uploading" @click="chooseFile()">上传技能 ZIP</n-button></n-space>
    </n-space>
    <input ref="fileInput" type="file" accept=".zip,application/zip" style="display: none" @change="onFile" />
    <n-alert type="info" :show-icon="false" style="margin-bottom: 16px">上传包含 SKILL.md 的技能包，在 Agent 配置中绑定后即可使用；Python 脚本在模型选择调用时执行。</n-alert>
    <n-spin :show="loading">
      <n-empty v-if="!items.length" description="暂无技能，请上传 ZIP 技能包" />
      <n-card v-for="item in items" :key="item.name" :title="item.name" style="margin-bottom: 12px">
        <p>{{ item.description || item.error }}</p>
        <n-space align="center" justify="space-between">
          <n-space><n-tag :type="item.valid ? 'success' : 'error'">{{ item.valid ? '格式有效' : '格式错误' }}</n-tag><span>已绑定 {{ item.bound_agents?.length || 0 }} 个 Agent</span></n-space>
          <n-space align="center">
            <n-switch :value="item.enabled" :disabled="!item.valid" @update:value="value => toggle(item, value)" />
            <n-button size="small" :disabled="!item.valid" @click="preview(item.name)">预览</n-button>
            <n-button size="small" @click="chooseFile(item.name)">替换包</n-button>
            <n-popconfirm @positive-click="remove(item.name)"><template #trigger><n-button size="small" type="error">删除</n-button></template>删除此技能？已绑定技能需先解除绑定。</n-popconfirm>
          </n-space>
        </n-space>
      </n-card>
    </n-spin>
    <n-drawer v-model:show="drawer" :width="Math.min(800, viewport)">
      <n-drawer-content :title="detail?.name || '技能预览'" closable>
        <template v-if="detail">
          <p>{{ detail.description }}</p>
          <n-select v-model:value="selectedFile" :options="(detail.files || []).map(file => ({ label: file.path, value: file.path }))" @update:value="previewFile" />
          <pre class="skill-source">{{ fileContent }}</pre>
        </template>
      </n-drawer-content>
    </n-drawer>
  </div>
</template>
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { listSkills, getSkill, readSkillFile, uploadSkill, enableSkill, deleteSkill, type SkillInfo } from '@/api/skills'

const message = useMessage()
const items = ref<SkillInfo[]>([])
const loading = ref(false)
const uploading = ref(false)
const fileInput = ref<HTMLInputElement>()
const replacing = ref<string>()
const drawer = ref(false)
const detail = ref<SkillInfo>()
const selectedFile = ref('SKILL.md')
const fileContent = ref('')
const viewport = window.innerWidth

/** 动态重读目录，并展示单个包的验证诊断。 */
async function refresh() {
  loading.value = true
  try { items.value = await listSkills() } catch (error) { message.error((error as Error).message) }
  finally { loading.value = false }
}
/** 上传和替换共用选择器，替换名称独立传递。 */
function chooseFile(name?: string) { replacing.value = name; fileInput.value?.click() }
/** 文件选择器限制 ZIP 类型，服务端负责最终格式、体积和脚本校验。 */
async function onFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  uploading.value = true
  try {
    await uploadSkill(file, replacing.value)
    message.success(replacing.value ? '技能包已替换' : '技能已上传')
    await refresh()
  } catch (error) { message.error((error as Error).message) }
  finally { uploading.value = false; input.value = '' }
}
/** 保存本地启停状态。 */
async function toggle(item: SkillInfo, enabled: boolean) {
  try { await enableSkill(item.name, enabled); await refresh() } catch (error) { message.error((error as Error).message) }
}
/** 删除失败时保留列表并显示引用冲突原因。 */
async function remove(name: string) {
  try { await deleteSkill(name); await refresh() } catch (error) { message.error((error as Error).message) }
}
/** 打开技能正文及资源预览。 */
async function preview(name: string) {
  try { detail.value = await getSkill(name); selectedFile.value = 'SKILL.md'; drawer.value = true; await previewFile('SKILL.md') }
  catch (error) { message.error((error as Error).message) }
}
/** 资源按需读取，脚本显示源代码而不执行。 */
async function previewFile(path: string) {
  if (!detail.value) return
  try { const result = await readSkillFile(detail.value.name, path); fileContent.value = result.binary ? '此文件为二进制资源' : result.content || '' }
  catch (error) { fileContent.value = (error as Error).message }
}
onMounted(refresh)
</script>
<style scoped>
.skill-source { margin-top: 16px; padding: 12px; background: rgba(128,128,128,.06); white-space: pre-wrap; overflow-wrap: anywhere; font-size: 13px; }
</style>
