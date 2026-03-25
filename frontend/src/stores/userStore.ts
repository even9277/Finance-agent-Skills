import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { userApi } from '@/api'
import { useAuthStore } from '@/stores/authStore'
import { useMemoryStore } from '@/stores/memoryStore'

export const useUserStore = defineStore('user', () => {
  const userId = ref<string>('')
  const displayName = ref<string>('')
  const coldStartDone = ref<boolean>(false)
  const loading = ref(false)

  const isReady = computed(() => !!userId.value)

  function _applyAuthUser() {
    const authStore = useAuthStore()
    const authUser = authStore.currentUser
    userId.value = authUser?.user_id || ''
    displayName.value = authUser?.display_name || ''
    coldStartDone.value = !!authUser?.cold_start_done
  }

  async function init() {
    const authStore = useAuthStore()
    _applyAuthUser()
    if (!authStore.isAuthenticated || !userId.value) {
      reset()
      return
    }

    try {
      const { data } = await userApi.getProfile(userId.value)
      coldStartDone.value = data.cold_start_done
      displayName.value = data.display_name || authStore.currentUser?.display_name || ''
      authStore.updateUserPatch({
        user_id: data.user_id,
        display_name: data.display_name,
        cold_start_done: data.cold_start_done,
        created_at: data.created_at,
      })
    } catch {
      // 网络失败不阻塞启动
      _applyAuthUser()
    }
  }

  async function completeColdStart(
    name: string,
    preferences?: Record<string, unknown>
  ) {
    const authStore = useAuthStore()
    if (!authStore.currentUser?.user_id) return
    loading.value = true
    try {
      await userApi.init(authStore.currentUser.user_id, name, preferences)
      userId.value = authStore.currentUser.user_id
      displayName.value = name
      coldStartDone.value = true
      authStore.updateUserPatch({
        display_name: name,
        cold_start_done: true,
      })
      
      // 修复：冷启动完成后，立即加载用户画像到 memoryStore
      // 确保侧边栏能立即展示刚设置的画像
      try {
        const memoryStore = useMemoryStore()

        // 1) 乐观更新：先把用户刚选择的偏好直接写入 store（避免页面跳转后短暂空白）
        if (preferences && typeof preferences === 'object') {
          const p = preferences as Record<string, unknown>
          const optimistic: Record<string, unknown> = {}
          if (typeof p.risk_profile === 'string') optimistic.risk_profile = p.risk_profile
          if (Array.isArray(p.sectors)) optimistic.sectors = p.sectors
          if (typeof p.return_expectation === 'number') optimistic.return_expectation = p.return_expectation
          if (typeof p.investment_horizon === 'string') optimistic.investment_horizon = p.investment_horizon
          if (Array.isArray(p.watchlist)) optimistic.watchlist = p.watchlist
          memoryStore.setProfile(optimistic as any)
        }

        // 2) 再从后端权威表拉取一次，校准最终画像（包含 Phase3 扩展字段）
        const { memoryApi } = await import('@/api')
        const res = await memoryApi.getProfile(userId.value)
        const { profile, stats, total_memories } = res.data
        memoryStore.setProfile(profile)
        memoryStore.setStats(stats)
        memoryStore.setTotalMemories(total_memories)
      } catch (e) {
        console.warn('[userStore] 冷启动后加载画像失败（不阻断流程）:', e)
      }
    } finally {
      loading.value = false
    }
  }

  function reset() {
    userId.value = ''
    displayName.value = ''
    coldStartDone.value = false
  }

  return {
    userId,
    displayName,
    coldStartDone,
    loading,
    isReady,
    init,
    completeColdStart,
    reset,
  }
})
