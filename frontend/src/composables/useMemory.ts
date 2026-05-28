import { ref } from 'vue'
import { memoryApi } from '@/api'
import type { MemoryProfile, MemoryItem } from '@/api'
import { useMemoryStore } from '@/stores/memoryStore'
import { useUserStore } from '@/stores/userStore'

export function useMemory() {
  const memoryStore = useMemoryStore()
  const userStore = useUserStore()

  const loading = ref(false)
  const error = ref<string | null>(null)

  let sectorsTimer: ReturnType<typeof setTimeout> | null = null
  let returnTimer: ReturnType<typeof setTimeout> | null = null

  async function loadProfile() {
    const userId = userStore.userId
    if (!userId) return

    loading.value = true
    error.value = null
    try {
      const res = await memoryApi.getProfile(userId)
      const { profile, stats, total_memories } = res.data
      memoryStore.setProfile(profile as MemoryProfile)
      memoryStore.setStats(stats)
      memoryStore.setTotalMemories(total_memories)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '加载画像失败'
      error.value = msg
      console.warn('[useMemory] loadProfile 失败:', msg)
    } finally {
      loading.value = false
    }
  }

  async function updateRisk(risk: string) {
    const userId = userStore.userId
    if (!userId) return
    memoryStore.updateRisk(risk)
    try {
      await memoryApi.updateRisk(userId, risk)
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '更新风险偏好失败'
      console.warn('[useMemory] updateRisk 失败:', error.value)
    }
  }

  function updateSectors(sectors: string[]) {
    const userId = userStore.userId
    if (!userId) return
    memoryStore.updateSectors(sectors)

    if (sectorsTimer) clearTimeout(sectorsTimer)
    sectorsTimer = setTimeout(async () => {
      try {
        await memoryApi.updateSectors(userId, sectors)
      } catch (e: unknown) {
        error.value = e instanceof Error ? e.message : '更新板块失败'
        console.warn('[useMemory] updateSectors 失败:', error.value)
      }
    }, 800)
  }

  function updateReturn(val: number, max?: number, horizon?: string) {
    const userId = userStore.userId
    if (!userId) return
    memoryStore.updateReturn(val, max)
    if (horizon) memoryStore.updateHorizon(horizon)

    if (returnTimer) clearTimeout(returnTimer)
    returnTimer = setTimeout(async () => {
      try {
        await memoryApi.updateReturn(userId, val, max, horizon)
      } catch (e: unknown) {
        error.value = e instanceof Error ? e.message : '更新期望收益失败'
        console.warn('[useMemory] updateReturn 失败:', error.value)
      }
    }, 800)
  }

  async function updateHorizon(horizon: string) {
    const userId = userStore.userId
    if (!userId) return
    memoryStore.updateHorizon(horizon)
    try {
      await memoryApi.updateHorizon(userId, horizon)
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '更新投资周期失败'
      console.warn('[useMemory] updateHorizon 失败:', error.value)
    }
  }

  async function clearAllMemories() {
    const userId = userStore.userId
    if (!userId) return
    try {
      await memoryApi.deleteAll(userId)
      memoryStore.resetProfile()
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '清空记忆失败'
      console.warn('[useMemory] clearAllMemories 失败:', error.value)
    }
  }

  async function loadMemoryItems(page = 1) {
    const userId = userStore.userId
    if (!userId) return
    try {
      const res = await memoryApi.getItems(userId, page)
      const { items, total } = res.data
      memoryStore.setMemoryItems(items as MemoryItem[], total, page)
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '加载记忆条目失败'
      console.warn('[useMemory] loadMemoryItems 失败:', error.value)
    }
  }

  async function addMemoryItem(category: string, content: string) {
    const userId = userStore.userId
    if (!userId) return null
    try {
      const res = await memoryApi.addItem(userId, category, content)
      await loadMemoryItems(1)
      return res.data
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '添加记忆失败'
      return null
    }
  }

  async function deleteSemanticMemoryItem(memoryId: string) {
    const userId = userStore.userId
    if (!userId) return
    try {
      await memoryApi.deleteItem(userId, memoryId)
      memoryStore.setMemoryItems(
        memoryStore.memoryItems.filter((i) => i.id !== memoryId),
        Math.max(0, memoryStore.totalItems - 1),
        1,
      )
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '删除记忆失败'
      console.warn('[useMemory] deleteSemanticMemoryItem 失败:', error.value)
    }
  }

  return {
    loading,
    error,
    loadProfile,
    updateRisk,
    updateSectors,
    updateReturn,
    updateHorizon,
    clearAllMemories,
    loadMemoryItems,
    addMemoryItem,
    deleteSemanticMemoryItem,
  }
}
