/**
 * useMemory composable - Phase 3 完整实现
 *
 * 所有 MemorySidebar 子组件通过此 composable 与 API 交互，
 * 不直接调用 memoryApi（方便测试和 mock）。
 *
 * debounce 策略：
 * - updateSectors / updateReturn：写入本地立即响应，延迟 800ms 发请求
 * - updateRisk / updateHorizon：立即发请求（单选操作，频次低）
 */

import { ref } from 'vue'
import { memoryApi, chatApi } from '@/api'
import type { MemoryProfile, MemoryItem, MemoryCommandResult } from '@/api'
import { useMemoryStore } from '@/stores/memoryStore'
import { useUserStore } from '@/stores/userStore'

export function useMemory() {
  const memoryStore = useMemoryStore()
  const userStore = useUserStore()

  const loading = ref(false)
  const error = ref<string | null>(null)

  // debounce 句柄
  let sectorsTimer: ReturnType<typeof setTimeout> | null = null
  let returnTimer: ReturnType<typeof setTimeout> | null = null

  // ── 加载画像 ─────────────────────────────────────────────

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

  // ── 更新风险偏好（立即 API 调用） ───────────────────────

  async function updateRisk(risk: string) {
    const userId = userStore.userId
    if (!userId) return
    const previous = { ...memoryStore.profile }
    memoryStore.updateRisk(risk)
    try {
      await memoryApi.updateRisk(userId, risk)
    } catch (e: unknown) {
      memoryStore.setProfile(previous)
      error.value = e instanceof Error ? e.message : '更新风险偏好失败'
      console.warn('[useMemory] updateRisk 失败:', error.value)
    }
  }

  // ── 更新关注板块（debounce 800ms）────────────────────────

  function updateSectors(sectors: string[]) {
    const userId = userStore.userId
    if (!userId) return
    const previous = [...memoryStore.profile.sectors]
    memoryStore.updateSectors(sectors)

    if (sectorsTimer) clearTimeout(sectorsTimer)
    sectorsTimer = setTimeout(async () => {
      try {
        await memoryApi.updateSectors(userId, sectors)
      } catch (e: unknown) {
        memoryStore.updateSectors(previous)
        error.value = e instanceof Error ? e.message : '更新板块失败'
        console.warn('[useMemory] updateSectors 失败:', error.value)
      }
    }, 800)
  }

  // ── 更新期望收益（debounce 800ms）────────────────────────

  function updateReturn(val: number, max?: number, horizon?: string) {
    const userId = userStore.userId
    if (!userId) return
    const previous = { ...memoryStore.profile }
    memoryStore.updateReturn(val, max)
    if (horizon) memoryStore.updateHorizon(horizon)

    if (returnTimer) clearTimeout(returnTimer)
    returnTimer = setTimeout(async () => {
      try {
        await memoryApi.updateReturn(userId, val, max, horizon)
      } catch (e: unknown) {
        memoryStore.setProfile(previous)
        error.value = e instanceof Error ? e.message : '更新期望收益失败'
        console.warn('[useMemory] updateReturn 失败:', error.value)
      }
    }, 800)
  }

  // ── 更新投资周期（立即 API 调用）────────────────────────

  async function updateHorizon(horizon: string) {
    const userId = userStore.userId
    if (!userId) return
    const previous = { ...memoryStore.profile }
    memoryStore.updateHorizon(horizon)
    try {
      await memoryApi.updateHorizon(userId, horizon)
    } catch (e: unknown) {
      memoryStore.setProfile(previous)
      error.value = e instanceof Error ? e.message : '更新投资周期失败'
      console.warn('[useMemory] updateHorizon 失败:', error.value)
    }
  }

  // ── 清空所有记忆 ────────────────────────────────────────

  async function clearAllMemories() {
    const userId = userStore.userId
    if (!userId) return
    try {
      // 宽范围删除只通过聊天命令生成 pending preview，禁止旧 confirm=true 直删。
      const { data } = await chatApi.sendMessage(userId, '忘掉我的文本记忆')
      if (data.memory_command) {
        memoryStore.setCommandResult(data.memory_command)
      }
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '清空记忆失败'
      console.warn('[useMemory] clearAllMemories 失败:', error.value)
    }
  }

  // ── 加载记忆条目（Mem0 语义层）─────────────────────────

  async function loadMemoryItems(page = 1) {
    const userId = userStore.userId
    if (!userId) return
    try {
      const res = await memoryApi.getItems(userId, page)
      const { items, total } = res.data
      memoryStore.setMemoryItems(
        items as MemoryItem[],
        total,
        page,
      )
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '加载记忆条目失败'
      console.warn('[useMemory] loadMemoryItems 失败:', error.value)
    }
  }

  // ── 添加记忆条目 ────────────────────────────────────────

  async function addMemoryItem(category: string, content: string) {
    const userId = userStore.userId
    if (!userId) return null
    try {
      const res = await memoryApi.addItem(userId, category, content)
      // 刷新列表
      await loadMemoryItems(1)
      return res.data
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '添加记忆失败'
      return null
    }
  }

  // ── 删除记忆条目 ────────────────────────────────────────

  async function deleteMemoryItem(memoryId: string) {
    const userId = userStore.userId
    if (!userId) return
    const previousItems = [...memoryStore.memoryItems]
    const previousTotal = memoryStore.totalItems
    try {
      await memoryApi.deleteItem(userId, memoryId)
      // 从本地列表移除
      memoryStore.setMemoryItems(
        memoryStore.memoryItems.filter(i => i.id !== memoryId),
        memoryStore.totalItems - 1,
        memoryStore.currentPage,
      )
    } catch (e: unknown) {
      memoryStore.setMemoryItems(previousItems, previousTotal, memoryStore.currentPage)
      error.value = e instanceof Error ? e.message : '删除记忆失败'
      console.warn('[useMemory] deleteMemoryItem 失败:', error.value)
    }
  }

  async function executeMemoryCommand(message: string, sessionId?: string): Promise<MemoryCommandResult | null> {
    const userId = userStore.userId
    if (!userId || !message.trim()) return null
    try {
      const { data } = await chatApi.sendMessage(userId, message, sessionId)
      const result = data.memory_command ?? null
      memoryStore.setCommandResult(result)
      if (result?.status === 'SUCCEEDED') {
        await loadProfile()
        await loadMemoryItems(1)
      }
      return result
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '执行记忆命令失败'
      return null
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
    deleteMemoryItem,
    executeMemoryCommand,
  }
}
