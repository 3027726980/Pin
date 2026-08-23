<template>
  <n-layout has-sider class="main-layout">
    <!-- 侧边栏 -->
    <n-layout-sider
      bordered
      collapse-mode="width"
      :collapsed-width="64"
      :width="220"
      :collapsed="collapsed"
      @update:collapsed="collapsed = $event"
    >
      <div class="logo-area" :class="{ collapsed }">
        <span class="logo-text">{{ collapsed ? 'P' : 'Pin' }}</span>
      </div>
      <n-menu
        :collapsed="collapsed"
        :value="activeMenu"
        :options="menuOptions"
        @update:value="onMenuChange"
      />
    </n-layout-sider>

    <!-- 右侧 -->
    <n-layout>
      <!-- 顶栏 -->
      <n-layout-header bordered class="header">
        <div class="header-left">
          <n-button text @click="collapsed = !collapsed">
            <n-icon size="20">
              <MenuOutline v-if="collapsed" />
              <ChevronBackOutline v-else />
            </n-icon>
          </n-button>
        </div>
        <div class="header-right">
          <n-dropdown :options="userDropdown" @select="onUserDropdown">
            <n-button text>
              <span>{{ userStore.userInfo?.username || '管理员' }}</span>
            </n-button>
          </n-dropdown>
        </div>
      </n-layout-header>

      <!-- 内容区 -->
      <n-layout-content class="content">
        <router-view />
      </n-layout-content>
    </n-layout>
  </n-layout>
</template>

<script setup lang="ts">
import { h, ref, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import type { Component } from 'vue'
import { NIcon } from 'naive-ui'
import {
  GridOutline,
  BookOutline,
  HardwareChipOutline,
  SettingsOutline,
  CogOutline,
  MenuOutline,
  ChevronBackOutline,
  LogOutOutline,
} from '@vicons/ionicons5'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const collapsed = ref(false)

// ── 菜单 ────────────────────────────
function renderIcon(icon: Component) {
  return () => h(NIcon, null, { default: () => h(icon) })
}

const menuOptions = [
  { label: '仪表盘', key: '/dashboard', icon: renderIcon(GridOutline) },
  { label: '知识库', key: '/knowledge', icon: renderIcon(BookOutline) },
  { label: 'Agent', key: '/agent', icon: renderIcon(HardwareChipOutline) },
  { label: '模型配置', key: '/settings/model-config', icon: renderIcon(SettingsOutline) },
  { label: '系统设置', key: '/settings/system', icon: renderIcon(CogOutline) },
]

const activeMenu = computed(() => {
  // 子路由高亮父菜单：/knowledge/:id → /knowledge
  if (route.path.startsWith('/knowledge')) return '/knowledge'
  if (route.path.startsWith('/agent')) return '/agent'
  if (route.path.startsWith('/settings/model-config')) return '/settings/model-config'
  if (route.path.startsWith('/settings/system')) return '/settings/system'
  return route.path
})

function onMenuChange(key: string) {
  router.push(key)
}

// ── 用户下拉 ────────────────────────
const userDropdown = [
  {
    label: '退出登录',
    key: 'logout',
    icon: renderIcon(LogOutOutline),
  },
]

function onUserDropdown(key: string) {
  if (key === 'logout') {
    userStore.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
.main-layout {
  height: 100vh;
}

.logo-area {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-bottom: 1px solid var(--n-border-color);
  transition: all 0.3s;
}

.logo-text {
  font-size: 20px;
  font-weight: 700;
  color: var(--n-text-color);
}

.logo-area.collapsed .logo-text {
  font-size: 18px;
}

.header {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
}

.header-left,
.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.content {
  padding: 24px;
  background: var(--n-color-body);
  min-height: calc(100vh - 56px);
}
</style>
