<!--
设置页容器：模型配置 / 系统设置 两个 Tab
-->
<template>
  <div class="page">
    <n-tabs type="line" animated>
      <n-tab-pane name="model" tab="模型配置">
        <ModelConfigView />
      </n-tab-pane>
      <n-tab-pane name="system" tab="系统设置">
        <SystemSettingsTab />
      </n-tab-pane>
    </n-tabs>
  </div>
</template>

<script setup lang="ts">
import ModelConfigView from './ModelConfigView.vue'
import SystemSettingsTab from './SystemSettingsTab.vue'
</script>
