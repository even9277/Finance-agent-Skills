/**
 * 持仓状态（Phase 1: 预留，Phase 4 完整实现）
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface HoldingItem {
  id: string
  stock_code: string
  stock_name?: string
  cost_price?: number
  quantity?: number
  current_price?: number
  pct_change?: number
  market_value?: number
  profit_loss?: number
  profit_loss_pct?: number
}

export const usePortfolioStore = defineStore('portfolio', () => {
  const holdings = ref<HoldingItem[]>([])
  const watchlist = ref<{ id: string; stock_code: string; stock_name?: string; pct_change?: number }[]>([])
  const lastSyncAt = ref<string | null>(null)
  const loading = ref(false)

  function setHoldings(data: HoldingItem[]) {
    holdings.value = data
  }

  function setWatchlist(data: typeof watchlist.value) {
    watchlist.value = data
  }

  function setLastSyncAt(ts: string) {
    lastSyncAt.value = ts
  }

  return { holdings, watchlist, lastSyncAt, loading, setHoldings, setWatchlist, setLastSyncAt }
})
