import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { storage } from '@/utils/storage'
import { TOKEN_KEY } from '@/api/request'

const LoginView = () => import('@/views/login/LoginView.vue')
const MainLayout = () => import('@/layouts/MainLayout.vue')
const DashboardView = () => import('@/views/dashboard/DashboardView.vue')
const KnowledgeListView = () => import('@/views/knowledge/KnowledgeListView.vue')
const KnowledgeDetailView = () => import('@/views/knowledge/KnowledgeDetailView.vue')
const AgentListView = () => import('@/views/agent/AgentListView.vue')
const ModelConfigView = () => import('@/views/settings/ModelConfigView.vue')

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: LoginView,
    meta: { title: '登录' },
  },
  {
    path: '/',
    component: MainLayout,
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: DashboardView,
        meta: { title: '仪表盘', requiresAuth: true },
      },
      {
        path: 'knowledge',
        name: 'Knowledge',
        component: KnowledgeListView,
        meta: { title: '知识库', requiresAuth: true },
      },
      {
        path: 'knowledge/:id',
        name: 'KnowledgeDetail',
        component: KnowledgeDetailView,
        meta: { title: '知识库详情', requiresAuth: true },
      },
      {
        path: 'agent',
        name: 'Agent',
        component: AgentListView,
        meta: { title: 'Agent', requiresAuth: true },
      },
      {
        path: 'settings/model-config',
        name: 'ModelConfig',
        component: ModelConfigView,
        meta: { title: '模型配置', requiresAuth: true },
      },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// ── 路由守卫 ────────────────────────
router.beforeEach((to, _from, next) => {
  const title = (to.meta.title as string) || 'Pin'
  document.title = title

  const isLoginPage = to.path === '/login'
  const token = storage.get<string>(TOKEN_KEY)

  if (to.meta.requiresAuth && !token) {
    // 需要登录但没 token → 跳登录
    next({ path: '/login', query: { redirect: to.fullPath } })
  } else if (isLoginPage && token) {
    // 已登录却去登录页 → 跳仪表盘
    next('/dashboard')
  } else {
    next()
  }
})

export default router
