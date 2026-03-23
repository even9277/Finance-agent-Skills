<script setup lang="ts">
/**
 * 持仓 CSV 上传（Phase 1 预留占位，Phase 4 完整实现）
 */
</script>

<template>
  <div class="flex flex-col items-center justify-center p-8 text-center border-2 border-dashed border-slate-700 rounded-xl">
    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="1.5" class="mb-3">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="17 8 12 3 7 8" />
      <line x1="12" y1="3" x2="12" y2="15" />
    </svg>
    <p class="text-slate-400 text-sm font-medium mb-1">CSV 批量上传</p>
    <p class="text-slate-600 text-xs">Phase 4 实现：拖拽或点击上传持仓 CSV</p>
    <p class="text-[10px] text-slate-700 mt-3">字段：股票代码 / 股票名称 / 成本价 / 持仓数量</p>
  </div>
</template>
