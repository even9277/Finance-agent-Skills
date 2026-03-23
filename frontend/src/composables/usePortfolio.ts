/**
 * 持仓管理逻辑（Phase 1: 预留接口签名，返回 mock/空数据）
 * Phase 4: 完整实现
 */
import { usePortfolioStore } from '@/stores/portfolioStore'

export function usePortfolio() {
  const store = usePortfolioStore()

  async function uploadHoldings(_file: File): Promise<void> {
    // Phase 4: POST /api/portfolio/holdings/upload
    console.warn('uploadHoldings: Phase 4 实现')
  }

  async function syncPrices(): Promise<void> {
    // Phase 4: POST /api/portfolio/sync
    console.warn('syncPrices: Phase 4 实现')
  }

  async function getWatchlist(): Promise<void> {
    // Phase 4: GET /api/portfolio/watchlist
    store.setWatchlist([])
  }

  async function getHoldings(): Promise<void> {
    // Phase 4: GET /api/portfolio/holdings
    store.setHoldings([])
  }

  return { uploadHoldings, syncPrices, getWatchlist, getHoldings, store }
}
