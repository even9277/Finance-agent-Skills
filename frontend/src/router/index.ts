import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { useUserStore } from '@/stores/userStore'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('@/views/LoginView.vue'),
    },
    {
      path: '/',
      name: 'Home',
      component: () => import('@/views/HomeView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/report',
      name: 'Report',
      component: () => import('@/views/ReportView.vue'),
      meta: { requiresAuth: true, requiresInit: true },
    },
    {
      path: '/chat',
      name: 'Chat',
      component: () => import('@/views/ChatView.vue'),
      meta: { requiresAuth: true, requiresInit: true },
    },
  ],
})

// 路由守卫：先校验登录态，再处理冷启动重定向
router.beforeEach(async (to) => {
  const authStore = useAuthStore()
  if (!authStore.initialized) {
    await authStore.init()
  }

  if (to.name === 'Login' && authStore.isAuthenticated) {
    return { name: 'Home' }
  }

  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    return { name: 'Login', query: { redirect: to.fullPath } }
  }

  if (to.meta.requiresAuth) {
    const userStore = useUserStore()
    if (!userStore.isReady) {
      await userStore.init()
    }
    if (to.meta.requiresInit && !userStore.coldStartDone) {
      return { name: 'Home', query: { redirect: to.fullPath } }
    }
  }
})

export default router
