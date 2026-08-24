<template>
  <div class="tool-param-form">
    <n-form-item
      v-for="param in def.params"
      :key="param.key"
      :label="param.label"
      :required="param.required"
      :show-feedback="false"
      label-placement="left"
      label-width="110"
      style="margin-bottom: 14px"
    >
      <!-- string -->
      <n-input
        v-if="param.type === 'string'"
        v-model:value="values[param.key]"
        :placeholder="param.placeholder"
        size="small"
      />
      <!-- textarea -->
      <n-input
        v-else-if="param.type === 'textarea'"
        v-model:value="values[param.key]"
        type="textarea"
        :placeholder="param.placeholder"
        :autosize="{ minRows: 2, maxRows: 5 }"
        size="small"
      />
      <!-- number -->
      <n-input-number
        v-else-if="param.type === 'number'"
        v-model:value="values[param.key]"
        :min="param.min"
        :max="param.max"
        :step="param.step"
        :placeholder="param.placeholder"
        size="small"
        style="width: 100%"
      />
      <!-- boolean -->
      <n-switch v-else-if="param.type === 'boolean'" v-model:value="values[param.key]" />
      <!-- select -->
      <n-select
        v-else-if="param.type === 'select'"
        v-model:value="values[param.key]"
        :options="param.options || []"
        :placeholder="param.placeholder || '请选择'"
        size="small"
      />
    </n-form-item>
  </div>
</template>

<script setup lang="ts">
/**
 * 通用工具参数表单（Schema 驱动）
 *
 * 根据 ToolDef.param_schema 渲染对应控件，新增后端工具无需修改本组件：
 *   string    → n-input
 *   textarea  → n-input textarea
 *   number    → n-input-number（min/max/step）
 *   boolean   → n-switch
 *   select    → n-select（options 由后端 tool-defs 接口填充）
 *
 * props:
 *   def: 工具定义（来自 getToolDefs()）
 * v-model: 参数值对象 Record<string, any>（key = param.key）
 */
import type { ToolDef } from '@/api/agent'

const props = defineProps<{ def: ToolDef }>()

// v-model 参数值对象（直接读写 props 传入对象的属性，父组件持有的引用同步生效）
// 防御：父组件异步重置时可能传入 undefined，此处兜底初始化为空对象
const values = defineModel<Record<string, any>>({ required: true })
if (!values.value) {
  values.value = {}
}

// 未预填的参数用 default 兜底（父组件启用工具时已用 default 初始化，此处防御性补全）
for (const param of props.def.params) {
  if (values.value[param.key] === undefined || values.value[param.key] === null) {
    values.value[param.key] = param.default ?? (param.type === 'boolean' ? false : undefined)
  }
}
</script>
