<script setup lang="ts">
/**
 * 持仓列表（Phase 1 骨架屏占位，Phase 4 完整实现）
 */
import type { HoldingItem } from '@/stores/portfolioStore'

defineProps<{ holdings: HoldingItem[]; loading?: boolean }>()

function pctColor(val?: number) {
  if (val === undefined || val === null) return 'text-slate-500'
  if (val > 0) return 'text-red-400'    // A股：涨红
  if (val < 0) return 'text-green-400'  // A股：跌绿
  return 'text-slate-400'
}

function fmtPct(val?: number) {
  if (val === undefined || val === null) return '--'
  return (val > 0 ? '+' : '') + val.toFixed(2) + '%'
}
</script>

<template>
  <div class="flex-1 overflow-hidden flex flex-col">
    <!-- 骨架屏加载 -->
    <template v-if="loading">
      <div class="space-y-2 p-4">
        <div v-for="i in 4" :key="i" class="h-12 bg-slate-800 rounded-lg animate-pulse" />
      </div>
    </template>

    <!-- 空状态引导 -->
    <template v-else-if="!holdings.length">
      <div class="flex-1 flex flex-col items-center justify-center p-8 text-center">
        <div class="w-16 h-16 bg-slate-800 rounded-2xl flex items-center justify-center mb-4">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="1.5">
            <rect x="2" y="3" width="20" height="14" rx="2" />
            <line x1="8" y1="21" x2="16" y2="21" />
            <line x1="12" y1="17" x2="12" y2="21" />
          </svg>
        </div>
        <p class="text-slate-400 text-sm font-medium mb-1">暂无持仓数据</p>
        <p class="text-slate-600 text-xs">持仓管理功能将在 Phase 4 上线</p>
        <div class="mt-4 px-4 py-2 bg-amber-500/10 border border-amber-500/20 rounded-lg">
          <p class="text-amber-400 text-xs">🚧 即将推出：CSV 批量导入 / 手动录入 / 前日涨跌同步</p>
        </div>
      </div>
    </template>

    <!-- 持仓表格 -->
    <template v-else>
      <div class="overflow-x-auto">
        <table class="w-full text-xs">
          <thead>
            <tr class="border-b border-slate-800">
              <th class="text-left px-3 py-2.5 text-slate-500 font-medium">股票</th>
              <th class="text-right px-3 py-2.5 text-slate-500 font-medium">成本价</th>
              <th class="text-right px-3 py-2.5 text-slate-500 font-medium">现价</th>
              <th class="text-right px-3 py-2.5 text-slate-500 font-medium">数量</th>
              <th class="text-right px-3 py-2.5 text-slate-500 font-medium">市值</th>
              <th class="text-right px-3 py-2.5 text-slate-500 font-medium">盈亏</th>
              <th class="text-right px-3 py-2.5 text-slate-500 font-medium">前日涨跌</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="h in holdings"
              :key="h.id"
              class="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors"
            >
              <td class="px-3 py-2.5">
                <div class="font-medium text-slate-200">{{ h.stock_name || h.stock_code }}</div>
                <div class="text-slate-600 text-[10px]">{{ h.stock_code }}</div>
              </td>
              <td class="text-right px-3 py-2.5 text-slate-400">
                {{ h.cost_price?.toFixed(2) ?? '--' }}
              </td>
              <td class="text-right px-3 py-2.5 text-slate-300">
                {{ h.current_price?.toFixed(2) ?? '--' }}
              </td>
              <td class="text-right px-3 py-2.5 text-slate-400">
                {{ h.quantity?.toLocaleString() ?? '--' }}
              </td>
              <td class="text-right px-3 py-2.5 text-slate-300">
                {{ h.market_value ? '¥' + h.market_value.toLocaleString() : '--' }}
              </td>
              <td :class="['text-right px-3 py-2.5', pctColor(h.profit_loss_pct)]">
                {{ fmtPct(h.profit_loss_pct) }}
              </td>
              <td :class="['text-right px-3 py-2.5 font-medium', pctColor(h.pct_change)]">
                {{ fmtPct(h.pct_change) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>
