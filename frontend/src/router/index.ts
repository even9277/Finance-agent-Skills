import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '@/stores/userStore'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'Home',
      component: () => import('@/views/HomeView.vue'),
    },
    {
      path: '/report',
      name: 'Report',
      component: () => import('@/views/ReportView.vue'),
      meta: { requiresInit: true },
    },
    {
      path: '/chat',
      name: 'Chat',
      component: () => import('@/views/ChatView.vue'),
      meta: { requiresInit: true },
    },
  ],
})

// 路由守卫：冷启动未完成则重定向到首页
router.beforeEach(async (to) => {
  if (to.meta.requiresInit) {
    const userStore = useUserStore()
    if (!userStore.coldStartDone) {
      return { name: 'Home', query: { redirect: to.fullPath } }
    }
  }
})

export default router
