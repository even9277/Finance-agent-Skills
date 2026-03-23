import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { MemoryProfile, MemoryItem } from '@/api'

export const useMemoryStore = defineStore('memory', () => {
  // ── 结构化画像（来自 user_invest_profiles 权威表）──────────
  const profile = ref<MemoryProfile>({
    risk_profile: undefined,
    sectors: [],
    return_expectation: undefined,
    investment_horizon: undefined,
    watchlist: [],
    // Phase 3 扩展字段
    risk_level: undefined,
    expected_return_min: undefined,
    expected_return_max: undefined,
    constraints: [],
    response_pref: 'balanced',
    updated_by: undefined,
    updated_at: undefined,
  })

  const loaded = ref(false)
  const totalMemories = ref(0)

  // ── Phase 3 统计数据 ────────────────────────────────────────
  const stats = ref({
    from_conversations: 0,
    from_reports: 0,
    from_manual: 0,
    total_tasks: 0,
  })

  // ── Mem0 语义记忆条目（来自 /api/memory/items）──────────────
  const memoryItems = ref<MemoryItem[]>([])
  const itemsLoaded = ref(false)
  const currentPage = ref(1)
  const totalItems = ref(0)
  const hasMoreItems = computed(
    () => memoryItems.value.length < totalItems.value
  )

  // ── Actions ─────────────────────────────────────────────────

  function setProfile(data: MemoryProfile) {
    profile.value = { ...profile.value, ...data }
    loaded.value = true
  }

  function setStats(data: Record<string, number>) {
    stats.value = { ...stats.value, ...data }
  }

  function setTotalMemories(count: number) {
    totalMemories.value = count
  }

  function updateRisk(risk: string) {
    profile.value.risk_profile = risk
    profile.value.risk_level = risk
  }

  function updateSectors(sectors: string[]) {
    profile.value.sectors = sectors
  }

  function updateReturn(val: number, max?: number) {
    profile.value.return_expectation = val
    profile.value.expected_return_min = val
    if (max !== undefined) {
      profile.value.expected_return_max = max
    }
  }

  function updateHorizon(horizon: string) {
    profile.value.investment_horizon = horizon
  }

  function addWatchlist(code: string) {
    if (!profile.value.watchlist.includes(code)) {
      profile.value.watchlist = [...profile.value.watchlist, code]
    }
  }

  function removeWatchlist(code: string) {
    profile.value.watchlist = profile.value.watchlist.filter(c => c !== code)
  }

  function setMemoryItems(items: MemoryItem[], total: number, page: number) {
    if (page === 1) {
      memoryItems.value = items
    } else {
      memoryItems.value = [...memoryItems.value, ...items]
    }
    totalItems.value = total
    currentPage.value = page
    itemsLoaded.value = true
  }

  function clearItems() {
    memoryItems.value = []
    itemsLoaded.value = false
    currentPage.value = 1
    totalItems.value = 0
  }

  function resetProfile() {
    profile.value = {
      risk_profile: undefined,
      sectors: [],
      return_expectation: undefined,
      investment_horizon: undefined,
      watchlist: [],
      risk_level: undefined,
      expected_return_min: undefined,
      expected_return_max: undefined,
      constraints: [],
      response_pref: 'balanced',
      updated_by: undefined,
      updated_at: undefined,
    }
    loaded.value = false
    totalMemories.value = 0
    stats.value = { from_conversations: 0, from_reports: 0, from_manual: 0, total_tasks: 0 }
    clearItems()
  }

  return {
    profile,
    loaded,
    totalMemories,
    stats,
    memoryItems,
    itemsLoaded,
    currentPage,
    totalItems,
    hasMoreItems,
    // actions
    setProfile,
    setStats,
    setTotalMemories,
    updateRisk,
    updateSectors,
    updateReturn,
    updateHorizon,
    addWatchlist,
    removeWatchlist,
    setMemoryItems,
    clearItems,
    resetProfile,
  }
})
