import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { v4 as uuidv4 } from 'uuid'
import { userApi } from '@/api'
import { useMemoryStore } from '@/stores/memoryStore'

// 前端在 localStorage 生成并持久化 userId（Phase 4 换为 JWT）
const USER_ID_KEY = 'finance_user_id'
const DISPLAY_NAME_KEY = 'finance_display_name'
const COLD_START_KEY = 'finance_cold_start_done'

export const useUserStore = defineStore('user', () => {
  const userId = ref<string>('')
  const displayName = ref<string>('')
  const coldStartDone = ref<boolean>(false)
  const loading = ref(false)

  const isReady = computed(() => !!userId.value)

  function _loadFromStorage() {
    let id: string = localStorage.getItem(USER_ID_KEY) ?? ''
    if (!id) {
      id = uuidv4()
      localStorage.setItem(USER_ID_KEY, id)
    }
    userId.value = id
    displayName.value = localStorage.getItem(DISPLAY_NAME_KEY) || ''
    coldStartDone.value = localStorage.getItem(COLD_START_KEY) === 'true'
  }

  async function init() {
    _loadFromStorage()
    // 同步后端状态（如果已完成冷启动，刷新 profile）
    if (coldStartDone.value) {
      try {
        const { data } = await userApi.getProfile(userId.value)
        coldStartDone.value = data.cold_start_done
        displayName.value = data.display_name || ''
        _persistToStorage()
      } catch {
        // 网络失败不阻塞启动
      }
    }
  }

  async function completeColdStart(
    name: string,
    preferences?: Record<string, unknown>
  ) {
    loading.value = true
    try {
      await userApi.init(userId.value, name, preferences)
      displayName.value = name
      coldStartDone.value = true
      _persistToStorage()
      
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
        memoryStore.setStats(stats as unknown as Record<string, number>)
        memoryStore.setTotalMemories(total_memories)
      } catch (e) {
        console.warn('[userStore] 冷启动后加载画像失败（不阻断流程）:', e)
      }
    } finally {
      loading.value = false
    }
  }

  function _persistToStorage() {
    localStorage.setItem(COLD_START_KEY, String(coldStartDone.value))
    if (displayName.value) {
      localStorage.setItem(DISPLAY_NAME_KEY, displayName.value)
    }
  }

  return {
    userId,
    displayName,
    coldStartDone,
    loading,
    isReady,
    init,
    completeColdStart,
  }
})
